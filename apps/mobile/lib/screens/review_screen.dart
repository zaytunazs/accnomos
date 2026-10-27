import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/proposal.dart';
import '../services/auth.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import 'capture_screen.dart';

const _warnBg = Color(0xFFFFF7ED);
const _warnBorder = Color(0xFFF3C892);
const _warnInk = Color(0xFF8A3F06);

String _gbp(double value) => '£${value.toStringAsFixed(2)}';

/// Review queue: a swipeable card per proposed entry.
///
/// Signed in: live proposals from the runtime. Approve/Reject call the
/// runtime and remove the card; "Scan inbox" reads `00 Inbox` and shows
/// per-file errors. Signed out: the fictional sample cards stay as a demo.
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
    } on MsalException {
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

  /// Reload live proposals (signed-in only).
  Future<void> _reload() async {
    if (!_signedIn || _loading) return;
    setState(() {
      _loading = true;
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
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
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
                Expanded(
                  child: proposals.isEmpty
                      ? Center(
                          child: Padding(
                            padding: const EdgeInsets.all(24),
                            child: Text(
                              _signedIn
                                  ? 'Nothing waiting. Photograph a receipt or press “Scan inbox”.'
                                  : 'Nothing here yet.',
                              textAlign: TextAlign.center,
                              style: const TextStyle(
                                  color: AccnomosColors.muted,
                                  height: 1.4),
                            ),
                          ),
                        )
                      : PageView.builder(
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
              ],
            ),
    );
  }

  Widget _scanErrorBox() {
    final errors = _scanErrors;
    return Container(
      width: double.infinity,
      constraints: const BoxConstraints(maxHeight: 148),
      margin: const EdgeInsets.fromLTRB(16, 12, 16, 0),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: _warnBg,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _warnBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '${errors.length} file${errors.length == 1 ? '' : 's'} could not be read',
                  style: const TextStyle(
                      color: _warnInk, fontWeight: FontWeight.w700),
                ),
              ),
              InkWell(
                onTap: () => setState(() => _scanErrors = const []),
                child: const Padding(
                  padding: EdgeInsets.all(8),
                  child: Icon(Icons.close, size: 18, color: _warnInk),
                ),
              ),
            ],
          ),
          Flexible(
            child: ListView.builder(
              shrinkWrap: true,
              itemCount: errors.length,
              itemBuilder: (context, i) => Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  '• ${errors[i].path}: ${errors[i].error}',
                  style:
                      const TextStyle(color: _warnInk, height: 1.4),
                ),
              ),
            ),
          ),
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
              shape: buttonShape,
            ),
            onPressed: () => _say('Editing arrives in the next update.'),
            child: const Text('Edit'),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: OutlinedButton(
            style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(52),
              shape: buttonShape,
            ),
            onPressed: _busy ? null : () => _rejectProposal(proposal),
            child: const Text('Reject'),
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
