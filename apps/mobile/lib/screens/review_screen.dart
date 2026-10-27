import 'dart:async';

import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/proposal.dart';
import '../services/auth.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import 'capture_screen.dart';
import 'edit_proposal_sheet.dart';

const _warnBg = Color(0xFFFFF7ED);
const _warnBorder = Color(0xFFF3C892);
const _warnInk = Color(0xFF8A3F06);

String _gbp(double value) => '£${value.toStringAsFixed(2)}';

/// Review queue: a swipeable card per proposed entry.
///
/// Signed in: live proposals from the runtime. Approve/Reject call the
/// runtime and remove the card; "Scan inbox" reads `00 Inbox` and shows
/// per-file errors. Entries the Autopilot approved appear in their own
/// section with Undo, but only when the reader exposes
/// `POST /books/undo/{event_id}` — otherwise the section stays hidden.
/// Signed out: the fictional sample cards stay as a demo.
class ReviewScreen extends StatefulWidget {
  const ReviewScreen({super.key});

  @override
  State<ReviewScreen> createState() => _ReviewScreenState();
}

class _ReviewScreenState extends State<ReviewScreen> {
  final PageController _pages = PageController();
  final AuthService _auth = AuthService();
  int _index = 0;
  final Map<String, bool> _alwaysDo = {};

  AppSettings? _settings;
  Account? _account;
  bool _authChecked = false;
  bool _loading = false;
  bool _busy = false;
  bool _scanning = false;
  String? _error;

  /// Live proposals when signed in.
  final List<Proposal> _live = [];

  /// Captured offline (signed-out extract flow) this session.
  final List<Proposal> _captured = [];

  /// Per-file scan errors from the latest `scan()`.
  List<ScanFileError> _scanErrors = const [];

  /// Entries the Autopilot approved, shown only when the reader exposes
  /// `POST /books/undo/{event_id}` (checked in `routes_books.py` terms via
  /// the reader's OpenAPI schema; hidden otherwise).
  List<AutopilotApproval> _auto = const [];
  bool _undoSupported = false;
  bool _undoBusy = false;

  bool get _signedIn => _account != null;

  List<Proposal> get _proposals =>
      _signedIn ? List.of(_live) : [..._captured, ...Proposal.samples];

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  void _say(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }

  String _friendly(Object e) => e.toString().replaceFirst('Exception: ', '');

  Future<void> _load() async {
    final settings = await AppSettings.load();
    Account? account;
    try {
      account = await _auth.account();
    } catch (_) {
      // No account (or no MSAL on this platform): signed-out fallback.
      account = null;
    }
    if (!mounted) return;
    setState(() {
      _settings = settings;
      _account = account;
      _authChecked = true;
    });
    if (account != null) await _reload();
  }

  Future<RuntimeClient> _booksClient() async {
    final settings = _settings!;
    final token = await _auth.token();
    Account? account = _account;
    try {
      account = await _auth.account() ?? account;
    } on MsalException {
      // Keep the account we already knew about.
    }
    if (mounted && account?.username != _account?.username) {
      setState(() => _account = account);
    }
    final user = account?.username ?? settings.userEmail;
    return RuntimeClient(
      settings,
      books: BooksAuth(
        graphToken: token,
        accountKind:
            _auth.kind == AccountKind.work ? 'work' : 'personal',
        user: (user != null && user.isNotEmpty) ? user : null,
        businessName: settings.businessName,
      ),
    );
  }

  /// Pull-to-refresh entry point: reloads live proposals when signed in.
  Future<void> _refresh() async {
    if (!_signedIn) return;
    await _reload(quiet: true);
  }

  /// Reload live proposals (signed-in only). [quiet] skips the full-screen
  /// spinner so pull-to-refresh keeps the list visible.
  Future<void> _reload({bool quiet = false}) async {
    if (!_signedIn || _loading) return;
    setState(() {
      if (!quiet) _loading = true;
      _error = null;
    });
    try {
      final client = await _booksClient();
      final raw = await client.proposals();
      if (!mounted) return;
      final live = <Proposal>[];
      for (final json in raw) {
        final status = (json['status'] ?? '').toString();
        if (status != 'proposed' && status != 'needs_a_look') continue;
        live.add(Proposal.fromBooksJson(json));
      }
      setState(() {
        _live
          ..clear()
          ..addAll(live);
        if (_index >= _live.length) {
          _index = _live.isEmpty ? 0 : _live.length - 1;
        }
      });
      if (_live.isNotEmpty && _pages.hasClients) {
        _pages.jumpToPage(_index);
      }
      // Autopilot entries load separately so the queue never waits on them.
      unawaited(_loadAutopilot(client));
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
    } finally {
      if (mounted && !quiet) setState(() => _loading = false);
    }
  }

  /// Load "Approved by Autopilot" entries, but only when the reader
  /// exposes `POST /books/undo/{event_id}`. The section stays hidden
  /// otherwise (current runtimes have no such route).
  Future<void> _loadAutopilot(RuntimeClient client) async {
    try {
      final supported = await client.supportsUndo();
      if (!mounted) return;
      if (!supported) {
        setState(() {
          _undoSupported = false;
          _auto = const [];
        });
        return;
      }
      final items = await client.autopilotApprovals();
      if (!mounted) return;
      setState(() {
        _undoSupported = true;
        _auto = items;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _undoSupported = false;
        _auto = const [];
      });
    }
  }

  /// Reverse one Autopilot approval. A 404 means the reader does not
  /// expose undo after all, so the section hides itself.
  Future<void> _undo(AutopilotApproval item) async {
    if (_undoBusy) return;
    setState(() => _undoBusy = true);
    try {
      final client = await _booksClient();
      await client.undoEvent(item.eventId);
      if (!mounted) return;
      setState(() =>
          _auto = _auto.where((a) => a.eventId != item.eventId).toList());
      await _reload(quiet: true);
      _say('Undone · back in your review list');
    } catch (e) {
      final message = _friendly(e);
      if (!mounted) return;
      if (message.contains('status 404')) {
        setState(() {
          _undoSupported = false;
          _auto = const [];
        });
        _say('Undo is not on this reader yet.');
      } else {
        _say(message);
      }
    } finally {
      if (mounted) setState(() => _undoBusy = false);
    }
  }

  /// `POST /books/scan`, then reload. Per-file errors stay on screen.
  Future<void> _scan() async {
    if (!_signedIn || _scanning) return;
    setState(() {
      _scanning = true;
      _error = null;
    });
    try {
      final client = await _booksClient();
      final outcome = await client.scan();
      if (!mounted) return;
      setState(() => _scanErrors = outcome.errors);
      await _reload();
      if (!mounted) return;
      final n = outcome.proposals.length;
      final m = outcome.errors.length;
      _say(m == 0
          ? 'Scan complete · $n proposal${n == 1 ? '' : 's'}'
          : 'Scan complete · $n proposal${n == 1 ? '' : 's'}, '
              '$m file${m == 1 ? '' : 's'} need a look');
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
    } finally {
      if (mounted) setState(() => _scanning = false);
    }
  }

  /// Prepend a freshly captured proposal and jump to it (signed-out flow).
  void _addProposal(Proposal proposal) {
    setState(() {
      _captured.insert(0, proposal);
      _index = 0;
    });
    if (_pages.hasClients) _pages.jumpToPage(0);
  }

  Future<void> _capture() async {
    final result = await Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const CaptureScreen()),
    );
    if (!mounted) return;
    if (result == true && _signedIn) {
      await _reload();
      _say('Inbox scanned · review list updated');
    } else if (result is Proposal) {
      _addProposal(result);
      _say('Receipt added to your review list');
    }
  }

  void _removeLive(String id) {
    setState(() {
      _live.removeWhere((p) => p.id == id);
      if (_index >= _live.length) {
        _index = _live.isEmpty ? 0 : _live.length - 1;
      }
    });
    if (_live.isNotEmpty && _pages.hasClients) {
      _pages.jumpToPage(_index);
    }
  }

  void _advance() {
    if (_index < _proposals.length - 1 && _pages.hasClients) {
      _pages.nextPage(
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    }
  }

  Future<void> _approveProposal(Proposal proposal) async {
    if (!_signedIn) {
      _say('Approved · posted to your books');
      _advance();
      return;
    }
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final client = await _booksClient();
      await client.approve(
        proposal.id,
        always: _alwaysDo[proposal.id] ?? false,
      );
      if (!mounted) return;
      _removeLive(proposal.id);
      _say('Approved · posted to your books');
    } catch (e) {
      _say(_friendly(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Open the edit sheet, then save-and-approve the corrected proposal.
  Future<void> _openEditSheet(Proposal proposal) async {
    final result = await showModalBottomSheet<EditResult>(
      context: context,
      isScrollControlled: true,
      builder: (_) => EditProposalSheet(proposal: proposal),
    );
    if (result == null || !mounted) return;
    await _saveAndApprove(proposal, result);
  }

  /// Send the sheet's `edits` inside `POST .../approve` (the runtime has no
  /// separate edit endpoint). Signed out, the corrected copy stays local.
  Future<void> _saveAndApprove(Proposal proposal, EditResult result) async {
    if (!_signedIn) {
      setState(() {
        final at = _captured.indexWhere((p) => p.id == proposal.id);
        if (at >= 0) {
          _captured[at] = result.updated;
        } else {
          _captured.insert(0, result.updated);
          _index = 0;
        }
      });
      if (_pages.hasClients) _pages.jumpToPage(_index);
      _say('Saved · approved locally');
      return;
    }
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final client = await _booksClient();
      await client.approve(
        proposal.id,
        edits: result.edits.isEmpty ? null : result.edits,
        always: _alwaysDo[proposal.id] ?? false,
      );
      if (!mounted) return;
      _removeLive(proposal.id);
      _say('Approved · posted to your books');
    } catch (e) {
      _say(_friendly(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _rejectProposal(Proposal proposal, {String reason = ''}) async {
    if (!_signedIn) {
      _say('Rejected');
      _advance();
      return;
    }
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final client = await _booksClient();
      await client.reject(proposal.id, reason: reason);
      if (!mounted) return;
      _removeLive(proposal.id);
      _say('Rejected');
    } catch (e) {
      _say(_friendly(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final proposals = _proposals;
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          proposals.isEmpty
              ? 'Review'
              : 'Review ${_index + 1} of ${proposals.length}',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        actions: [
          if (_signedIn)
            IconButton(
              icon: _scanning
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.refresh_outlined),
              tooltip: 'Scan inbox',
              constraints:
                  const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _scanning ? null : _scan,
            ),
          IconButton(
            icon: const Icon(Icons.photo_camera_outlined),
            tooltip: 'Photograph a receipt',
            constraints:
                const BoxConstraints(minWidth: 48, minHeight: 48),
            onPressed: _capture,
          ),
        ],
      ),
      body: !_authChecked || _loading
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: [
                if (!_signedIn)
                  Container(
                    width: double.infinity,
                    color: AccnomosColors.ink,
                    padding: const EdgeInsets.symmetric(
                        vertical: 6, horizontal: 12),
                    child: const Text(
                      'SAMPLE — FICTIONAL COMPANY · sign in to see your books',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                          color: AccnomosColors.ground,
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 0.6),
                    ),
                  ),
                if (_error != null)
                  Container(
                    width: double.infinity,
                    margin: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: _warnBg,
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: _warnBorder),
                    ),
                    child: Text(_error!,
                        style:
                            const TextStyle(color: _warnInk, height: 1.4)),
                  ),
                if (_scanErrors.isNotEmpty) _scanErrorBox(),
                if (_signedIn && _undoSupported && _auto.isNotEmpty)
                  _autopilotSection(),
                Expanded(
                  child: proposals.isEmpty
                      ? RefreshIndicator(
                          onRefresh: _refresh,
                          child: ListView(
                            physics:
                                const AlwaysScrollableScrollPhysics(),
                            children: [
                              Padding(
                                padding: const EdgeInsets.all(24),
                                child: Column(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Text(
                                      _signedIn
                                          ? 'Nothing waiting. Photograph a receipt or press “Scan inbox”.'
                                          : 'Nothing here yet.',
                                      textAlign: TextAlign.center,
                                      style: const TextStyle(
                                          color: AccnomosColors.muted,
                                          height: 1.4),
                                    ),
                                    if (_signedIn) ...[
                                      const SizedBox(height: 16),
                                      FilledButton(
                                        style: FilledButton.styleFrom(
                                          backgroundColor:
                                              AccnomosColors.teal,
                                          minimumSize:
                                              const Size.fromHeight(52),
                                          padding: const EdgeInsets
                                              .symmetric(horizontal: 8),
                                          shape: RoundedRectangleBorder(
                                              borderRadius:
                                                  BorderRadius.circular(
                                                      14)),
                                        ),
                                        onPressed: _scanning
                                            ? null
                                            : _scan,
                                        child: const Text('Scan inbox',
                                            softWrap: false,
                                            style: TextStyle(
                                                fontWeight:
                                                    FontWeight.w800)),
                                      ),
                                    ],
                                  ],
                                ),
                              ),
                            ],
                          ),
                        )
                      : RefreshIndicator(
                          onRefresh: _refresh,
                          child: PageView.builder(
                          controller: _pages,
                          itemCount: proposals.length,
                          onPageChanged: (i) =>
                              setState(() => _index = i),
                          itemBuilder: (context, i) {
                            final proposal = proposals[i];
                            switch (proposal.status) {
                              case ProposalStatus.needsALook:
                                return _needsALookCard(proposal);
                              case ProposalStatus.voiceNote:
                                return _voiceCard(proposal);
                              case ProposalStatus.proposed:
                                return _proposedCard(proposal);
                            }
                          },
                        ),
                      ),
                ),
              ],
            ),
    );
  }

  /// Per-file scan errors in an expandable list (plus the summary
  /// snackbar from [_scan]), so nothing is lost when several files fail.
  Widget _scanErrorBox() {
    final errors = _scanErrors;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(16, 12, 16, 0),
      decoration: BoxDecoration(
        color: _warnBg,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _warnBorder),
      ),
      child: ExpansionTile(
        initiallyExpanded: true,
        tilePadding:
            const EdgeInsets.only(left: 12, right: 4, top: 4, bottom: 4),
        childrenPadding:
            const EdgeInsets.only(left: 12, right: 12, bottom: 12),
        iconColor: _warnInk,
        collapsedIconColor: _warnInk,
        title: Row(
          children: [
            Expanded(
              child: Text(
                '${errors.length} file${errors.length == 1 ? '' : 's'} could not be read',
                style: const TextStyle(
                    color: _warnInk,
                    fontWeight: FontWeight.w700,
                    fontSize: 14),
              ),
            ),
            IconButton(
              constraints:
                  const BoxConstraints(minWidth: 48, minHeight: 48),
              icon:
                  const Icon(Icons.close, size: 18, color: _warnInk),
              tooltip: 'Dismiss',
              onPressed: () =>
                  setState(() => _scanErrors = const []),
            ),
          ],
        ),
        children: [
          for (final error in errors)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('• ',
                      style: TextStyle(color: _warnInk)),
                  Expanded(
                    child: Text(
                      '${error.path}: ${error.error}',
                      style: const TextStyle(
                          color: _warnInk, height: 1.4),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  /// Entries the Autopilot approved, each with an Undo button.
  /// Rendered only when the reader exposes `POST /books/undo/{event_id}`.
  Widget _autopilotSection() {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(16, 12, 16, 0),
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Approved by Autopilot',
            style: TextStyle(
              fontWeight: FontWeight.w800,
              fontSize: 14,
              color: AccnomosColors.ink,
            ),
          ),
          const SizedBox(height: 2),
          const Text(
            'Checked by your rules. Undo puts one back for review.',
            style: TextStyle(
                fontSize: 12, color: AccnomosColors.muted),
          ),
          for (final item in _auto)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          item.supplier,
                          softWrap: false,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              fontWeight: FontWeight.w700),
                        ),
                        Text(
                          _gbp(item.total),
                          style: const TextStyle(
                              color: AccnomosColors.muted),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 8),
                  OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size(72, 40),
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8),
                      shape: RoundedRectangleBorder(
                          borderRadius:
                              BorderRadius.circular(12)),
                    ),
                    onPressed: _undoBusy ? null : () => _undo(item),
                    child: const Text('Undo', softWrap: false),
                  ),
                ],
              ),
            ),
          const SizedBox(height: 6),
        ],
      ),
    );
  }

  Widget _header(Proposal proposal, {Color ink = AccnomosColors.ink}) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 72,
          height: 92,
          decoration: BoxDecoration(
            color: const Color(0xFFE0E0E0),
            borderRadius: BorderRadius.circular(8),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                proposal.supplier,
                style: TextStyle(
                  fontSize: 19,
                  fontWeight: FontWeight.w700,
                  color: ink,
                ),
              ),
              Text(
                _gbp(proposal.total),
                style: TextStyle(
                  fontSize: 26,
                  fontWeight: FontWeight.w800,
                  color: ink,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                '${proposal.date} · ${proposal.paidBy}',
                style: const TextStyle(color: AccnomosColors.muted),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _pill(String label, {required Color bg, required Color fg}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: fg,
          fontSize: 12,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }

  Widget _fieldRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: const TextStyle(color: AccnomosColors.muted),
            ),
          ),
          Text(
            value,
            style: const TextStyle(
              color: AccnomosColors.ink,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }

  Widget _noteBox(String text, {required Color bg, required Color fg}) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(text, style: TextStyle(color: fg, height: 1.4)),
    );
  }

  Widget _alwaysRow(Proposal proposal) {
    return Row(
      children: [
        Checkbox(
          value: _alwaysDo[proposal.id] ?? false,
          activeColor: AccnomosColors.teal,
          onChanged: (v) =>
              setState(() => _alwaysDo[proposal.id] = v ?? false),
        ),
        Expanded(
          child: Text('Always do this for ${proposal.supplier}'),
        ),
      ],
    );
  }

  Widget _decisionRow(Proposal proposal) {
    final buttonShape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(14),
    );
    return Row(
      children: [
        Expanded(
          flex: 2,
          child: FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: AccnomosColors.teal,
              minimumSize: const Size.fromHeight(52),
              shape: buttonShape,
            ),
            onPressed: _busy ? null : () => _approveProposal(proposal),
            child: const Text(
              'Approve',
              style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
            ),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: OutlinedButton(
            style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(52),
              padding: const EdgeInsets.symmetric(horizontal: 8),
              shape: buttonShape,
            ),
            onPressed: _busy ? null : () => _openEditSheet(proposal),
            child: const Text('Edit', softWrap: false),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: OutlinedButton(
            style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(52),
              padding: const EdgeInsets.symmetric(horizontal: 8),
              shape: buttonShape,
            ),
            onPressed: _busy ? null : () => _rejectProposal(proposal),
            child: const Text('Reject', softWrap: false, overflow: TextOverflow.fade),
          ),
        ),
      ],
    );
  }

  Widget _cardShell({required Widget child, Color? bg, Color? border}) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: bg ?? Colors.white,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: border ?? const Color(0xFFE3E1D8)),
        ),
        child: child,
      ),
    );
  }

  Widget _proposedCard(Proposal proposal) {
    return _cardShell(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _header(proposal),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _pill(
                '${(proposal.confidence * 100).round()}% sure',
                bg: AccnomosColors.tealTint,
                fg: AccnomosColors.tealDark,
              ),
              _pill(
                proposal.source,
                bg: AccnomosColors.ground,
                fg: AccnomosColors.ink,
              ),
            ],
          ),
          const Divider(height: 24),
          _fieldRow('Category', proposal.category),
          if (proposal.net != null)
            _fieldRow('Net', _gbp(proposal.net!)),
          if (proposal.vat != null)
            _fieldRow('VAT to reclaim (20%)', _gbp(proposal.vat!)),
          if (proposal.vatNumber != null)
            _fieldRow('VAT number ✓', proposal.vatNumber!),
          if (proposal.reviewerNote != null)
            _noteBox(
              'Why: ${proposal.reviewerNote}',
              bg: AccnomosColors.ground,
              fg: AccnomosColors.ink,
            ),
          _noteBox(
            proposal.verifierNote ??
                'Verifier agrees · all 5 fields match.',
            bg: AccnomosColors.tealTint,
            fg: AccnomosColors.tealDark,
          ),
          const SizedBox(height: 4),
          _alwaysRow(proposal),
          const SizedBox(height: 8),
          _decisionRow(proposal),
        ],
      ),
    );
  }

  Widget _needsALookCard(Proposal proposal) {
    final buttonShape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(14),
    );
    return _cardShell(
      bg: _warnBg,
      border: _warnBorder,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _header(proposal, ink: _warnInk),
          const SizedBox(height: 10),
          _pill('Needs a look', bg: _warnBorder, fg: _warnInk),
          const SizedBox(height: 10),
          Text(
            proposal.reason ?? '',
            style: const TextStyle(color: _warnInk, height: 1.4),
          ),
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: _warnInk,
                minimumSize: const Size.fromHeight(52),
                shape: buttonShape,
              ),
              onPressed: _busy
                  ? null
                  : () => _rejectProposal(proposal,
                      reason: 'Archived as duplicate'),
              child: const Text(
                'Archive as duplicate',
                style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
              ),
            ),
          ),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
              style: OutlinedButton.styleFrom(
                foregroundColor: _warnInk,
                side: const BorderSide(color: _warnInk),
                minimumSize: const Size.fromHeight(52),
                shape: buttonShape,
              ),
              onPressed: () =>
                  _say('Comparison arrives in the next update.'),
              child: const Text("It's different — compare"),
            ),
          ),
        ],
      ),
    );
  }

  Widget _voiceCard(Proposal proposal) {
    return _cardShell(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _header(proposal),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _pill(
                '${(proposal.confidence * 100).round()}% sure',
                bg: AccnomosColors.tealTint,
                fg: AccnomosColors.tealDark,
              ),
              _pill(
                'Voice note',
                bg: AccnomosColors.ground,
                fg: AccnomosColors.ink,
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            '“${proposal.quote ?? ''}”',
            style: const TextStyle(
              fontStyle: FontStyle.italic,
              fontSize: 16,
              height: 1.4,
              color: AccnomosColors.ink,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            'No VAT receipt, so no VAT claimed.',
            style: TextStyle(color: AccnomosColors.muted),
          ),
          const SizedBox(height: 4),
          _alwaysRow(proposal),
          const SizedBox(height: 8),
          _decisionRow(proposal),
        ],
      ),
    );
  }
}
