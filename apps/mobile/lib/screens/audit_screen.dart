import 'package:flutter/foundation.dart' show visibleForTesting;
import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../services/auth.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/web_only.dart';
import 'settings_screen.dart';

/// Who chips: each is one `GET /audit` actor filter (Planner plans are
/// applied by you, so its chip is the `plan_*` kinds).
const _whoFilters = <({String key, String label, String? actor, String? kind})>[
  (key: 'all', label: 'Everyone', actor: null, kind: null),
  (key: 'you', label: 'You', actor: 'user', kind: null),
  (key: 'autopilot', label: 'Autopilot', actor: 'autopilot', kind: null),
  (key: 'intake', label: 'Intake', actor: 'intake', kind: null),
  (key: 'triage', label: 'Triage', actor: 'triage', kind: null),
  (key: 'planner', label: 'Planner', actor: null, kind: 'plan'),
];

/// What dropdown: an event, or a family of events by prefix — the same
/// list as the web audit page.
const _kindFilters = [
  ('', 'Everything'),
  ('approved', 'Postings'),
  ('undone', 'Undos'),
  ('rejected', 'Rejections'),
  ('proposed', 'Documents read'),
  ('invoice', 'Invoices'),
  ('bank', 'Bank'),
  ('mail', 'Mail'),
  ('action', 'Ask actions'),
  ('payroll', 'Payroll'),
  ('timesheet', 'Timesheets'),
  ('mileage', 'Mileage'),
];

/// One line from `GET /audit` (services/runtime/app/audit_view.py).
class AuditLine {
  AuditLine({
    required this.at,
    required this.actorLabel,
    required this.byPerson,
    required this.event,
    required this.summary,
  });

  final DateTime at; // local time
  final String actorLabel; // "You", "Autopilot", "Intake", "Triage", ...
  final bool byPerson;
  final String event;
  final String summary;

  static AuditLine? fromJson(Map<String, dynamic> j) {
    final at = DateTime.tryParse((j['ts'] ?? '').toString());
    if (at == null) return null;
    return AuditLine(
      at: at.toLocal(),
      actorLabel: (j['actor_label'] ?? '').toString(),
      byPerson: j['actor_kind'] == 'user',
      event: (j['event'] ?? '').toString(),
      summary: (j['summary'] ?? '').toString(),
    );
  }
}

/// Lines (newest first) grouped by local day, newest day first.
List<MapEntry<DateTime, List<AuditLine>>> auditDays(List<AuditLine> lines) {
  final days = <DateTime, List<AuditLine>>{};
  for (final l in lines) {
    days.putIfAbsent(DateTime(l.at.year, l.at.month, l.at.day), () => []).add(l);
  }
  return days.entries.toList()..sort((a, b) => b.key.compareTo(a.key));
}

const _weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const _months = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/// "Wednesday 14 October 2026".
String auditDayHeading(DateTime d) =>
    '${_weekdays[d.weekday - 1]} ${d.day} ${_months[d.month - 1]} ${d.year}';

String _clock(DateTime t) =>
    '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

/// Builds a [RuntimeClient] for the audit screen. The app builds the
/// real client (with books credentials when signed in); tests inject a
/// fake that answers without touching the network.
typedef AuditClientFactory = RuntimeClient Function(
    AppSettings settings, BooksAuth? books);

/// The audit trail, read-only: everything done in the books and who did
/// it — you, or an agent. Who/what/date filters use the same `GET /audit`
/// query as the web; only the CSV export stays on the web.
class AuditScreen extends StatefulWidget {
  const AuditScreen({
    super.key,
    @visibleForTesting this.testAccount,
    @visibleForTesting this.testAccountReady = false,
    this.clientFactory,
  });

  /// Signed-in account to use without touching MSAL (tests only).
  @visibleForTesting
  final Account? testAccount;

  /// Skip the MSAL account lookup and use [testAccount] as-is (tests only).
  @visibleForTesting
  final bool testAccountReady;

  /// Builds the runtime client; null means the real [RuntimeClient].
  final AuditClientFactory? clientFactory;

  @override
  State<AuditScreen> createState() => _AuditScreenState();
}

class _AuditScreenState extends State<AuditScreen> {
  final AuthService _auth = AuthService();
  AppSettings? _settings;
  Account? _account;
  bool _authChecked = false;
  bool _loading = false;
  String? _error;
  List<AuditLine> _lines = const [];
  bool _truncated = false;
  String _who = 'all';
  String _kind = '';
  late DateTime _from;
  late DateTime _to;

  /// First day shown, `YYYY-MM-DD` in London time.
  static String _isoDay(DateTime day) =>
      '${day.year.toString().padLeft(4, '0')}-'
      '${day.month.toString().padLeft(2, '0')}-'
      '${day.day.toString().padLeft(2, '0')}';

  ({String? actor, String? kind}) get _auditFilter {
    final who = _whoFilters.firstWhere((w) => w.key == _who);
    // The What dropdown wins over the Planner chip's plan_* filter.
    return (actor: who.actor, kind: _kind.isEmpty ? who.kind : _kind);
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  String _friendly(Object e) => e.toString().replaceFirst('Exception: ', '');

  Future<void> _load() async {
    final settings = await AppSettings.load();
    Account? account;
    if (widget.testAccountReady) {
      account = widget.testAccount;
    } else {
      try {
        account = await _auth.account();
      } catch (_) {
        account = null;
      }
    }
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    if (!mounted) return;
    setState(() {
      _settings = settings;
      _account = account;
      _authChecked = true;
      _to = today;
      _from = today.subtract(const Duration(days: 31));
    });
    if (account != null) await _reload();
  }

  Future<RuntimeClient> _booksClient() async {
    final settings = _settings!;
    final factory = widget.clientFactory;
    if (factory != null) {
      return factory(
        settings,
        BooksAuth(
          graphToken: 'test-token',
          accountKind: 'personal',
          user: _account?.username,
          businessName: settings.businessName,
        ),
      );
    }
    final token = await _auth.token();
    final user = _account?.username ?? settings.userEmail;
    return RuntimeClient(
      settings,
      books: BooksAuth(
        graphToken: token,
        accountKind: _auth.kind == AccountKind.work ? 'work' : 'personal',
        user: (user != null && user.isNotEmpty) ? user : null,
        businessName: settings.businessName,
      ),
    );
  }

  Future<void> _pickDate(bool isFrom) async {
    final picked = await showDatePicker(
      context: context,
      initialDate: isFrom ? _from : _to,
      firstDate: DateTime(2000),
      lastDate: DateTime.now().add(const Duration(days: 1)),
    );
    if (picked == null || !mounted) return;
    setState(() {
      if (isFrom) {
        _from = picked;
      } else {
        _to = picked;
      }
    });
    await _reload();
  }

  Future<void> _reload({bool quiet = false}) async {
    if (_settings == null || _account == null || _loading) return;
    if (!quiet) setState(() => _loading = true);
    setState(() => _error = null);
    try {
      final filter = _auditFilter;
      final data = await (await _booksClient()).audit(
        from: _isoDay(_from),
        to: _isoDay(_to),
        actor: filter.actor,
        kind: filter.kind,
      );
      final lines = <AuditLine>[];
      if (data['entries'] is List) {
        for (final e in data['entries'] as List) {
          final line = e is Map ? AuditLine.fromJson(Map<String, dynamic>.from(e)) : null;
          if (line != null) lines.add(line);
        }
      }
      if (!mounted) return;
      setState(() {
        _lines = lines;
        _truncated = data['truncated'] == true;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text('Audit trail', style: Theme.of(context).textTheme.headlineSmall),
        actions: [
          if (_account != null)
            IconButton(
              icon: _loading
                  ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.refresh_outlined),
              tooltip: 'Reload the audit trail',
              constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _loading ? null : () => _reload(quiet: true),
            ),
        ],
      ),
      body: !_authChecked || (_loading && _lines.isEmpty && _error == null)
          ? const Center(child: CircularProgressIndicator())
          : _account == null
              ? _signedOut(context)
              : _error != null && _lines.isEmpty
                  ? _errorView()
                  : _body(),
    );
  }

  Widget _signedOut(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Text(
              'Sign in with Microsoft to see your audit trail.',
              textAlign: TextAlign.center,
              style: TextStyle(color: AccnomosColors.muted, height: 1.4),
            ),
            const SizedBox(height: 16),
            FilledButton(
              style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size.fromHeight(52),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14))),
              onPressed: () => Navigator.of(context)
                  .push(MaterialPageRoute(builder: (_) => const SettingsScreen()))
                  .then((_) => _load()),
              child: const Text('Open settings to sign in',
                  style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
            ),
          ],
        ),
      ),
    );
  }

  Widget _errorView() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(_error ?? 'Could not load the audit trail.',
                textAlign: TextAlign.center,
                style: const TextStyle(color: Color(0xFF8A3F06), height: 1.4)),
            const SizedBox(height: 16),
            OutlinedButton(
              style: OutlinedButton.styleFrom(
                minimumSize: const Size.fromHeight(48),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
              ),
              onPressed: () => _reload(),
              child: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _filters() {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                for (final w in _whoFilters)
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ChoiceChip(
                      label: Text(w.label),
                      selected: _who == w.key,
                      onSelected: (_) {
                        if (_who == w.key) return;
                        setState(() => _who = w.key);
                        _reload();
                      },
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  initialValue: _kind,
                  decoration: InputDecoration(
                    labelText: 'What',
                    border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12)),
                    contentPadding: const EdgeInsets.symmetric(
                        horizontal: 12, vertical: 12),
                  ),
                  items: [
                    for (final k in _kindFilters)
                      DropdownMenuItem(value: k.$1, child: Text(k.$2)),
                  ],
                  onChanged: (v) {
                    if (v == null || v == _kind) return;
                    setState(() => _kind = v);
                    _reload();
                  },
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size.fromHeight(44),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12)),
                  ),
                  onPressed: () => _pickDate(true),
                  child: Text('From ${_dayLabel(_from)}'),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton(
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size.fromHeight(44),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12)),
                  ),
                  onPressed: () => _pickDate(false),
                  child: Text('To ${_dayLabel(_to)}'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  static String _dayLabel(DateTime d) =>
      '${d.day} ${_months[d.month - 1].substring(0, 3)} ${d.year}';

  Widget _body() {
    final days = auditDays(_lines);
    return RefreshIndicator(
      onRefresh: () => _reload(quiet: true),
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _filters(),
          const SizedBox(height: 12),
          if (_lines.isEmpty)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: const Color(0xFFE3E1D8)),
              ),
              child: const Text('Nothing matches these filters.',
                  style: TextStyle(color: AccnomosColors.muted, height: 1.4)),
            ),
          for (final day in days) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(4, 8, 4, 6),
              child: Semantics(
                header: true,
                child: Text(auditDayHeading(day.key).toUpperCase(),
                    style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 0.6,
                        color: AccnomosColors.muted)),
              ),
            ),
            Container(
              margin: const EdgeInsets.only(bottom: 8),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: const Color(0xFFE3E1D8)),
              ),
              child: Column(children: [
                for (var i = 0; i < day.value.length; i++) ...[
                  if (i > 0) const Divider(height: 1, color: Color(0xFFE3E1D8)),
                  _row(day.value[i]),
                ],
              ]),
            ),
          ],
          if (_truncated)
            const Padding(
              padding: EdgeInsets.only(top: 4),
              child: Text('Showing the newest 200 lines. Narrow the dates to see more.',
                  style: TextStyle(color: AccnomosColors.muted, fontSize: 12)),
            ),
          const WebOnlyCard(
            message: 'Downloading the trail as a spreadsheet (CSV) happens on the web.',
            page: '/audit',
          ),
        ],
      ),
    );
  }

  Widget _row(AuditLine l) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 48,
            child: Text(_clock(l.at),
                style: const TextStyle(fontWeight: FontWeight.w700, color: AccnomosColors.muted)),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(spacing: 4, runSpacing: 4, children: [
                  _ActorChip(label: l.actorLabel, byPerson: l.byPerson),
                  if (l.event.startsWith('plan_')) const _ActorChip(label: 'Planner', byPerson: false),
                ]),
                const SizedBox(height: 4),
                Text(l.summary, style: const TextStyle(color: AccnomosColors.ink, height: 1.35)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ActorChip extends StatelessWidget {
  const _ActorChip({required this.label, required this.byPerson});

  final String label;
  final bool byPerson;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: byPerson ? '$label, a person' : '$label, an agent',
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(
          color: byPerson ? AccnomosColors.tealTint : AccnomosColors.ground,
          borderRadius: BorderRadius.circular(999),
        ),
        child: Text(label,
            style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w800,
                color: byPerson ? AccnomosColors.tealDark : AccnomosColors.ink)),
      ),
    );
  }
}
