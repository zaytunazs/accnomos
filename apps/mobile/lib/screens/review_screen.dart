import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/proposal.dart';
import '../services/auth.dart';
import '../services/capture_queue.dart';
import '../services/graph.dart';
import '../services/review_rules.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/review_image.dart';
import 'capture_screen.dart';
import 'contacts_screen.dart';
import 'edit_proposal_sheet.dart';

const _warnBg = Color(0xFFFFF7ED);
const _warnBorder = Color(0xFFF3C892);
const _warnInk = Color(0xFF8A3F06);

String _gbp(double value) => '£${value.toStringAsFixed(2)}';

/// Snackbar text after an undo. When the undone entry's VAT period was
/// already submitted, the runtime dates the correction today and says so
/// (`dated_today` + `reason`): name the open period it lands in. [what]
/// is the entry ("Screwfix · £38.47"); empty for the Autopilot section.
@visibleForTesting
String undoMessage(Map<String, dynamic>? response, String what) {
  final reason = (response?['reason'] ?? '').toString().trim();
  if (response?['dated_today'] == true && reason.isNotEmpty) {
    return what.isEmpty
        ? '$reason It is back in Review.'
        : '$reason $what is back in Review.';
  }
  return what.isEmpty
      ? 'Undone · back in your review list'
      : 'Undone · $what is back in Review';
}

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

  /// "`<supplier>` isn't VAT-registered", ticked on cards that ask about it.
  final Map<String, bool> _notRegistered = {};

  /// The tick as an approve edit, merged into what else is sent.
  Map<String, dynamic>? _withVatTick(
      Proposal proposal, Map<String, dynamic>? edits) {
    if (!proposal.asksVatStatus || !(_notRegistered[proposal.id] ?? false)) {
      return edits;
    }
    return {...?edits, notVatRegisteredEdit: true};
  }

  String _approvedNote(Proposal proposal) =>
      proposal.asksVatStatus && (_notRegistered[proposal.id] ?? false)
          ? 'Approved · posted to your books · ${proposal.supplier} '
              'remembered as not VAT-registered'
          : 'Approved · posted to your books';

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

  /// Sample ids decided this session (signed-out approvals hide the card;
  /// Undo brings it back).
  final Set<String> _dismissed = {};

  /// Per-file scan errors from the latest `scan()`.
  List<ScanFileError> _scanErrors = const [];

  /// Entries the Autopilot approved, shown only when the reader exposes
  /// `POST /books/undo/{event_id}` (checked in `routes_books.py` terms via
  /// the reader's OpenAPI schema; hidden otherwise).
  List<AutopilotApproval> _auto = const [];
  bool _undoSupported = false;
  bool _undoBusy = false;

  /// Saved Autopilot rules for the rule-match test (signed in only).
  List<ReviewRule> _rules = const [];

  /// Event ids from the last approval, for the snackbar Undo action.
  /// Signed out, the removed cards themselves are kept instead.
  List<String> _lastEventIds = const [];
  List<Proposal> _lastRemoved = const [];
  String _lastWhat = '';

  bool get _signedIn => _account != null;

  List<Proposal> get _proposals => _signedIn
      ? List.of(_live)
      : [
          ..._captured,
          ...Proposal.samples.where((p) => !_dismissed.contains(p.id)),
        ];

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

  /// A decision snackbar with an Undo action when [onUndo] is given.
  void _sayDecision(String message, {Future<void> Function()? onUndo}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        action: onUndo == null
            ? null
            : SnackBarAction(
                label: 'Undo',
                onPressed: () => unawaited(onUndo()),
              ),
      ),
    );
  }

  List<ReviewRule> get _effectiveRules =>
      _signedIn ? _rules : sampleRules;

  /// Rule matches among the visible cards, only when Autopilot is L1
  /// (at L2 the runtime posts them on its own; at L0 rules are off).
  Map<String, ReviewRule> _ruleFor(List<Proposal> proposals) {
    final matches = <String, ReviewRule>{};
    if ((_settings?.autopilotLevel ?? 'L1') != 'L1') return matches;
    final rules = _effectiveRules;
    for (final proposal in proposals) {
      final rule = matchingRule(proposal.ruleView, rules);
      if (rule != null) matches[proposal.id] = rule;
    }
    return matches;
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
      // Autopilot entries and rules load separately so the queue never
      // waits on them.
      unawaited(_loadAutopilot(client));
      unawaited(_loadRules(client));
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

  /// Saved rules for the match test; failures leave an empty list so
  /// no card claims a match it was not shown.
  Future<void> _loadRules(RuntimeClient client) async {
    try {
      final raw = await client.rules();
      if (!mounted) return;
      setState(
          () => _rules = [for (final r in raw) ReviewRule.fromJson(r)]);
    } catch (_) {
      if (!mounted) return;
      setState(() => _rules = const []);
    }
  }

  /// Undo the last decision from the snackbar action. Signed in, each
  /// kept event id gets `POST /books/undo/{event_id}` (a reversing entry;
  /// the proposal goes back to Review). Signed out, the removed cards
  /// are put back where they were.
  Future<void> _undoLastDecision() async {
    final eventIds = _lastEventIds;
    final removed = _lastRemoved;
    final what = _lastWhat;
    if (eventIds.isEmpty && removed.isEmpty) {
      _say('Nothing to undo yet.');
      return;
    }
    if (!_signedIn) {
      setState(() {
        for (final proposal in removed) {
          _dismissed.remove(proposal.id);
          final isSample =
              Proposal.samples.any((p) => p.id == proposal.id);
          if (!isSample && !_captured.any((p) => p.id == proposal.id)) {
            _captured.insert(0, proposal);
          }
        }
        _index = 0;
        _lastRemoved = const [];
        _lastWhat = '';
      });
      if (_pages.hasClients) _pages.jumpToPage(0);
      _say('Undone · $what is back in Review');
      return;
    }
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final client = await _booksClient();
      // Reverse in the opposite order, so pressing again never reverses
      // an entry twice when one call fails halfway.
      final left = eventIds.reversed.toList();
      Map<String, dynamic>? undone;
      while (left.isNotEmpty) {
        undone = await client.undoEvent(left.first);
        left.removeAt(0);
      }
      if (!mounted) return;
      setState(() {
        _lastEventIds = const [];
        _lastWhat = '';
      });
      await _reload(quiet: true);
      _say(undoMessage(undone, what));
    } catch (e) {
      _say(_friendly(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Reverse one Autopilot approval. A 404 means the reader does not
  /// expose undo after all, so the section hides itself.
  Future<void> _undo(AutopilotApproval item) async {
    if (_undoBusy) return;
    setState(() => _undoBusy = true);
    try {
      final client = await _booksClient();
      final undone = await client.undoEvent(item.eventId);
      if (!mounted) return;
      setState(() =>
          _auto = _auto.where((a) => a.eventId != item.eventId).toList());
      await _reload(quiet: true);
      _say(undoMessage(undone, ''));
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
    if (result is CaptureScanSummary && _signedIn) {
      await _reload();
      _say('Scan complete · ${result.label}');
    } else if (result == true && _signedIn) {
      await _reload();
      _say('Inbox scanned · review list updated');
    } else if (result is List<Proposal>) {
      for (final proposal in result.reversed) {
        _addProposal(proposal);
      }
      _say(result.length == 1
          ? 'Receipt added to your review list'
          : '${result.length} receipts added to your review list');
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

  /// Event id from an approve response, for the snackbar Undo action.
  /// Null when the runtime returned none (then nothing can be undone).
  String? _eventIdOf(Map<String, dynamic> response) {
    for (final key in ['event_id', 'eventId']) {
      final value = response[key]?.toString();
      if (value != null && value.isNotEmpty) return value;
    }
    return null;
  }

  /// Take a card out of the signed-out list (samples hide, captures leave
  /// the session list) and remember it for Undo.
  void _removeLocal(Proposal proposal, {String? what}) {
    setState(() {
      _captured.removeWhere((p) => p.id == proposal.id);
      _dismissed.add(proposal.id);
      _lastRemoved = [proposal];
      _lastEventIds = const [];
      _lastWhat = what ?? '${proposal.supplier} · ${_gbp(proposal.total)}';
      if (_index >= _proposals.length) {
        _index = _proposals.isEmpty ? 0 : _proposals.length - 1;
      }
    });
    if (_proposals.isNotEmpty && _pages.hasClients) {
      _pages.jumpToPage(_index);
    }
  }

  Future<void> _approveProposal(Proposal proposal) async {
    if (!_signedIn) {
      _removeLocal(proposal);
      _sayDecision('Approved · posted to your books',
          onUndo: _undoLastDecision);
      return;
    }
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final client = await _booksClient();
      final response = await client.approve(
        proposal.id,
        edits: _withVatTick(proposal, null),
        always: _alwaysDo[proposal.id] ?? false,
      );
      if (!mounted) return;
      final eventId = _eventIdOf(response);
      _removeLive(proposal.id);
      setState(() {
        _lastEventIds = eventId == null ? const [] : [eventId];
        _lastRemoved = const [];
        _lastWhat = '${proposal.supplier} · ${_gbp(proposal.total)}';
      });
      _sayDecision(
        _approvedNote(proposal),
        onUndo: eventId == null ? null : _undoLastDecision,
      );
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
      _removeLocal(proposal);
      _sayDecision('Saved · approved locally',
          onUndo: _undoLastDecision);
      return;
    }
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final client = await _booksClient();
      final response = await client.approve(
        proposal.id,
        edits: _withVatTick(
            proposal, result.edits.isEmpty ? null : result.edits),
        always: _alwaysDo[proposal.id] ?? false,
      );
      if (!mounted) return;
      final eventId = _eventIdOf(response);
      _removeLive(proposal.id);
      setState(() {
        _lastEventIds = eventId == null ? const [] : [eventId];
        _lastRemoved = const [];
        _lastWhat = '${proposal.supplier} · ${_gbp(proposal.total)}';
      });
      _sayDecision(
        _approvedNote(proposal),
        onUndo: eventId == null ? null : _undoLastDecision,
      );
    } catch (e) {
      _say(_friendly(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _rejectProposal(Proposal proposal, {String reason = ''}) async {
    if (!_signedIn) {
      _removeLocal(proposal);
      _sayDecision('Rejected', onUndo: _undoLastDecision);
      return;
    }
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final client = await _booksClient();
      await client.reject(proposal.id, reason: reason);
      if (!mounted) return;
      _removeLive(proposal.id);
      // The runtime has no un-reject: the document is parked in
      // 04 Needs a look, so no Undo is offered.
      _say('Rejected · the document is parked in 04 Needs a look');
    } catch (e) {
      _say(_friendly(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Confirm, then approve every rule match: each is a normal approve
  /// call carrying the rule's edits, exactly as if Approve was pressed
  /// on it. Signed out, the cards hide locally instead.
  Future<void> _confirmBulkApprove(
    List<Proposal> matches,
    Map<String, ReviewRule> ruleFor,
  ) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Approve all ${matches.length} rule matches?'),
        content: SizedBox(
          width: double.maxFinite,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Each is posted to your books exactly as if you pressed '
                'Approve on it, with the category and account from your '
                'rule. Every one can be undone.',
              ),
              const SizedBox(height: 12),
              Flexible(
                child: ListView(
                  shrinkWrap: true,
                  children: [
                    for (final proposal in matches)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 4),
                        child: Row(
                          children: [
                            Expanded(
                              child: Text(
                                proposal.supplier,
                                softWrap: false,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            const SizedBox(width: 8),
                            Text(
                              _gbp(proposal.total),
                              style: const TextStyle(
                                  fontWeight: FontWeight.w700),
                            ),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            style: TextButton.styleFrom(
                minimumSize: const Size(48, 48)),
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: AccnomosColors.teal,
              minimumSize: const Size(48, 48),
            ),
            onPressed: () => Navigator.of(context).pop(true),
            child: Text('Approve ${matches.length}'),
          ),
        ],
      ),
    );
    if (confirm != true || !mounted) return;
    await _approveMatches(matches, ruleFor);
  }

  Future<void> _approveMatches(
    List<Proposal> matches,
    Map<String, ReviewRule> ruleFor,
  ) async {
    if (!_signedIn) {
      setState(() {
        for (final proposal in matches) {
          _captured.removeWhere((p) => p.id == proposal.id);
          _dismissed.add(proposal.id);
        }
        _lastRemoved = List.of(matches);
        _lastEventIds = const [];
        _lastWhat = '${matches.length} rule '
            'match${matches.length == 1 ? '' : 'es'}';
        _index = 0;
      });
      if (_pages.hasClients) _pages.jumpToPage(0);
      _sayDecision(
        'Approved ${matches.length} of ${matches.length} rule matches '
        '· posted to your books',
        onUndo: _undoLastDecision,
      );
      return;
    }
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final client = await _booksClient();
      final eventIds = <String>[];
      final done = <String>[];
      final failed = <String>[];
      for (var i = 0; i < matches.length; i++) {
        final proposal = matches[i];
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                  'Approving ${i + 1} of ${matches.length}: '
                  '${proposal.supplier} · ${_gbp(proposal.total)}…'),
              duration: const Duration(seconds: 1),
            ),
          );
        }
        try {
          final rule = ruleFor[proposal.id]!;
          final response = await client.approve(
            proposal.id,
            edits: ruleEdits(proposal.ruleView, rule),
            always: _alwaysDo[proposal.id] ?? false,
          );
          final eventId = _eventIdOf(response);
          if (eventId != null) eventIds.add(eventId);
          done.add(proposal.id);
        } catch (e) {
          failed.add(
              '${proposal.supplier}: ${_friendly(e)}');
        }
      }
      if (!mounted) return;
      for (final id in done) {
        _live.removeWhere((p) => p.id == id);
      }
      if (_index >= _live.length) {
        _index = _live.isEmpty ? 0 : _live.length - 1;
      }
      if (_live.isNotEmpty && _pages.hasClients) {
        _pages.jumpToPage(_index);
      }
      setState(() {
        _lastEventIds = eventIds;
        _lastRemoved = const [];
        _lastWhat =
            '${done.length} rule match${done.length == 1 ? '' : 'es'}';
      });
      if (failed.isNotEmpty) {
        _say('Not approved: ${failed.join(' · ')}');
      }
      _sayDecision(
        'Approved ${done.length} of ${matches.length} rule matches '
        '· posted to your books',
        onUndo: eventIds.isEmpty ? null : _undoLastDecision,
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final proposals = _proposals;
    final ruleFor = _ruleFor(proposals);
    final matches =
        proposals.where((p) => ruleFor.containsKey(p.id)).toList();
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
                if (matches.isNotEmpty) _bulkBanner(matches, ruleFor),
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
                                return _proposedCard(
                                  proposal,
                                  rule: ruleFor[proposal.id],
                                  matches: matches,
                                  ruleFor: ruleFor,
                                );
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

  /// Open the full-screen document viewer. Signed in, the filed copy is
  /// fetched from the user's own OneDrive; otherwise the captured photo
  /// or the drawn receipt is shown.
  void _openImage(Proposal proposal) {
    Future<Uint8List> Function()? remote;
    final filePath = proposal.filePath;
    if (_signedIn && filePath != null) {
      remote = () async {
        final token = await _auth.token();
        return GraphService().fileBytes(token, _auth.kind, filePath);
      };
    }
    unawaited(showReviewImage(
      context,
      proposal: proposal,
      remoteBytes: remote,
    ));
  }

  Widget _header(Proposal proposal, {Color ink = AccnomosColors.ink}) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ProposalThumbnail(
          proposal: proposal,
          onTap: () => _openImage(proposal),
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
          const SizedBox(width: 8),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.right,
              style: const TextStyle(
                color: AccnomosColors.ink,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// The runtime's own crop note (`crop.note`: SAM when available).
  Widget _cropLine(Proposal proposal, {Color ink = AccnomosColors.muted}) {
    final note = proposal.cropNote;
    if (note == null || note.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Text(
        'Reader crop: $note',
        style: TextStyle(color: ink, fontSize: 12, height: 1.4),
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

  /// One plain-English line per failed or warning check
  /// (`checks[].message`; never the check's code).
  Widget _failedChecksBox(Proposal proposal) {
    if (proposal.failedChecks.isEmpty) return const SizedBox.shrink();
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: _warnBg,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _warnBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final check in proposal.failedChecks)
            Padding(
              padding: const EdgeInsets.only(top: 2, bottom: 2),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    check.warn ? '! ' : '✕ ',
                    style: const TextStyle(
                      color: _warnInk,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  Expanded(
                    child: Text(
                      check.text,
                      style:
                          const TextStyle(color: _warnInk, height: 1.4),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  /// The verifier verdict. Disagreements list both readings of each
  /// disputed field; Edit highlights those fields.
  Widget _verifierBox(Proposal proposal) {
    final Color bg;
    final Color fg;
    switch (proposal.verifierTone) {
      case VerifierTone.differ:
        bg = _warnBg;
        fg = _warnInk;
      case VerifierTone.none:
        bg = AccnomosColors.ground;
        fg = AccnomosColors.muted;
      case VerifierTone.agree:
        bg = AccnomosColors.tealTint;
        fg = AccnomosColors.tealDark;
    }
    final border = proposal.verifierTone == VerifierTone.differ
        ? Border.all(color: _warnBorder)
        : null;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(10),
        border: border,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            proposal.verifierNote.isEmpty
                ? 'Second reading not run.'
                : proposal.verifierNote,
            style: TextStyle(color: fg, height: 1.4),
          ),
          for (final diff in proposal.verifierDiffs)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Text(
                      diff.field,
                      style: TextStyle(color: fg, fontSize: 13),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      diff.extractor,
                      textAlign: TextAlign.right,
                      style: TextStyle(
                        color: fg,
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      diff.verifier,
                      textAlign: TextAlign.right,
                      style: TextStyle(
                        color: fg,
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  /// 'Matches your Autopilot rule…': shown on the card when a saved rule
  /// matches and Autopilot is L1, with the bulk approval when several match.
  Widget _ruleNotice(
    Proposal proposal,
    ReviewRule rule,
    List<Proposal> matches,
    Map<String, ReviewRule> ruleFor,
  ) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AccnomosColors.tealTint,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            ruleMatchLine(rule, rule.typicalGrossPence),
            style: const TextStyle(
              color: AccnomosColors.tealDark,
              height: 1.4,
            ),
          ),
          if (matches.length > 1)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: OutlinedButton(
                style: OutlinedButton.styleFrom(
                  foregroundColor: AccnomosColors.tealDark,
                  side: const BorderSide(color: AccnomosColors.tealDark),
                  minimumSize: const Size(48, 44),
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12)),
                ),
                onPressed: _busy
                    ? null
                    : () => _confirmBulkApprove(matches, ruleFor),
                child: Text(
                  'Approve all ${matches.length} rule matches',
                  softWrap: false,
                  overflow: TextOverflow.fade,
                ),
              ),
            ),
        ],
      ),
    );
  }

  /// Banner above the cards when rule matches wait for review.
  Widget _bulkBanner(
    List<Proposal> matches,
    Map<String, ReviewRule> ruleFor,
  ) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(16, 12, 16, 0),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AccnomosColors.tealTint,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AccnomosColors.tealDark),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${matches.length} proposal${matches.length == 1 ? '' : 's'} '
            'match${matches.length == 1 ? 'es' : ''} rules you saved '
            'and pass${matches.length == 1 ? 'es' : ''} every check. '
            'Autopilot is at L1, so ${matches.length == 1 ? 'it waits' : 'they wait'} for you.',
            style: const TextStyle(
              color: AccnomosColors.tealDark,
              height: 1.4,
            ),
          ),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: AccnomosColors.teal,
                minimumSize: const Size.fromHeight(48),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14)),
              ),
              onPressed: _busy
                  ? null
                  : () => _confirmBulkApprove(matches, ruleFor),
              child: Text(
                'Approve all ${matches.length} rule matches',
                softWrap: false,
                overflow: TextOverflow.fade,
                style: const TextStyle(fontWeight: FontWeight.w800),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _notRegisteredRow(Proposal proposal) {
    return Container(
      margin: const EdgeInsets.only(top: 4),
      padding: const EdgeInsets.only(bottom: 4),
      decoration: BoxDecoration(
        color: _warnBg,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _warnBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Checkbox(
                key: ValueKey('review-not-vat-registered-${proposal.id}'),
                value: _notRegistered[proposal.id] ?? false,
                activeColor: AccnomosColors.teal,
                onChanged: (v) =>
                    setState(() => _notRegistered[proposal.id] = v ?? false),
              ),
              Expanded(
                child: Text(
                  "${proposal.supplier} isn't VAT-registered "
                  "(approving remembers this)",
                  style: const TextStyle(color: _warnInk, fontWeight: FontWeight.w600),
                ),
              ),
            ],
          ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              key: ValueKey('review-vat-status-${proposal.id}'),
              style: TextButton.styleFrom(
                foregroundColor: AccnomosColors.tealDark,
                minimumSize: const Size(48, 48),
              ),
              onPressed: () => _openSupplierContact(proposal),
              child: Text('Set for ${proposal.supplier} in Contacts'),
            ),
          ),
        ],
      ),
    );
  }

  /// Open the supplier behind a "Is `supplier` VAT-registered?" card in
  /// Contacts, with the VAT status control focused so the question is
  /// answered for good. Signed out there is no contact book to open.
  Future<void> _openSupplierContact(Proposal proposal) async {
    final settings = _settings;
    final account = _account;
    if (!_signedIn || settings == null || account == null) {
      _say('Sign in to open this supplier in Contacts.');
      return;
    }
    try {
      final client = await _booksClient();
      final decoded = await client.contacts();
      final list = decoded['contacts'];
      Map<String, dynamic>? match;
      if (list is List) {
        final want = proposal.supplier.trim().toLowerCase();
        for (final c in list) {
          if (c is Map &&
              (c['name'] ?? '')
                      .toString()
                      .trim()
                      .toLowerCase() ==
                  want) {
            match = Map<String, dynamic>.from(c);
            break;
          }
        }
      }
      if (!mounted) return;
      if (match == null) {
        _say('${proposal.supplier} is not in your contacts yet.');
        return;
      }
      final found = match;
      await Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => ContactDetailScreen(
            contactId: (found['id'] ?? '').toString(),
            name: proposal.supplier,
            settings: settings,
            auth: _auth,
            account: account,
            contact: found,
            focusVatStatus: true,
          ),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      _say(_friendly(e));
    }
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
            key: ValueKey('review-approve-${proposal.id}'),
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
            key: ValueKey('review-edit-${proposal.id}'),
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
            key: ValueKey('review-reject-${proposal.id}'),
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

  Widget _proposedCard(
    Proposal proposal, {
    ReviewRule? rule,
    required List<Proposal> matches,
    required Map<String, ReviewRule> ruleFor,
  }) {
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
          if (rule != null) _ruleNotice(proposal, rule, matches, ruleFor),
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
          _failedChecksBox(proposal),
          _verifierBox(proposal),
          _cropLine(proposal),
          if (proposal.asksVatStatus) _notRegisteredRow(proposal),
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
          _failedChecksBox(proposal),
          _cropLine(proposal, ink: _warnInk),
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
