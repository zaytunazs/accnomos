import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/month_end.dart';
import '../services/auth.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import 'home_cards.dart' show HomeCard;

/// Builds a [RuntimeClient] for the month-end screen and card; tests inject
/// a fake that answers without touching the network.
typedef MonthEndClientFactory = RuntimeClient Function(
    AppSettings settings, BooksAuth? books);

String _isoDay(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

Future<RuntimeClient> _client(AuthService auth, AppSettings settings,
    Account? account, MonthEndClientFactory? factory) async {
  if (factory != null) {
    return factory(
      settings,
      BooksAuth(
        graphToken: 'test-token',
        accountKind: 'personal',
        user: account?.username,
        businessName: settings.businessName,
      ),
    );
  }
  final token = await auth.token();
  final user = account?.username ?? settings.userEmail;
  return RuntimeClient(
    settings,
    books: BooksAuth(
      graphToken: token,
      accountKind: auth.kind == AccountKind.work ? 'work' : 'personal',
      user: (user != null && user.isNotEmpty) ? user : null,
      businessName: settings.businessName,
    ),
  );
}

/// The month-end checklist, read only: the last run's nine steps, its
/// summary, and what changed since the month was closed. The close itself
/// (and every card it proposes) is run and approved on the web.
class MonthEndScreen extends StatefulWidget {
  const MonthEndScreen({
    super.key,
    this.month,
    @visibleForTesting this.testAccount,
    @visibleForTesting this.testAccountReady = false,
    @visibleForTesting this.today,
    this.clientFactory,
  });

  /// `yyyy-mm`; null means the month that ended last.
  final String? month;

  @visibleForTesting
  final Account? testAccount;

  @visibleForTesting
  final bool testAccountReady;

  /// Today, for tests; null means the device's date.
  @visibleForTesting
  final DateTime? today;

  final MonthEndClientFactory? clientFactory;

  @override
  State<MonthEndScreen> createState() => _MonthEndScreenState();
}

class _MonthEndScreenState extends State<MonthEndScreen> {
  final AuthService _auth = AuthService();
  AppSettings? _settings;
  Account? _account;
  bool _checked = false;
  bool _loading = false;
  String? _error;
  MonthClose? _close;
  late final DateTime _today = widget.today ?? DateTime.now();
  late final List<String> _months = recentMonths(_today);
  late String _month = widget.month ?? _months.first;

  @override
  void initState() {
    super.initState();
    _start();
  }

  Future<void> _start() async {
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
    if (!mounted) return;
    setState(() {
      _settings = settings;
      _account = account;
      _checked = true;
    });
    if (account != null) await _reload();
  }

  Future<void> _reload() async {
    if (_settings == null || _account == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final client = await _client(_auth, _settings!, _account, widget.clientFactory);
      final data = await client.closeMonth(_month, today: _isoDay(_today));
      if (!mounted) return;
      setState(() => _close = MonthClose.fromJson(data));
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final close = _close;
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text('Month-end', style: Theme.of(context).textTheme.headlineSmall),
      ),
      body: RefreshIndicator(
        onRefresh: _reload,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
          children: [
            DropdownButtonFormField<String>(
              initialValue: _month,
              decoration: const InputDecoration(labelText: 'Month'),
              items: [
                for (final m in _months) DropdownMenuItem(value: m, child: Text(monthLabel(m))),
              ],
              onChanged: (m) {
                if (m == null) return;
                setState(() {
                  _month = m;
                  _close = null;
                });
                _reload();
              },
            ),
            const SizedBox(height: 12),
            if (_checked && _account == null)
              const Text('Sign in to see your month-end checklist.',
                  style: TextStyle(color: AccnomosColors.muted)),
            if (_loading) const LinearProgressIndicator(),
            if (_error != null)
              Text('Could not load the checklist: $_error',
                  style: const TextStyle(color: AccnomosColors.muted)),
            if (close != null) ...[
              Text(close.headline,
                  style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, height: 1.35)),
              const SizedBox(height: 6),
              const Text('Run the close and approve its cards on the web; the phone shows the last run.',
                  style: TextStyle(color: AccnomosColors.muted, fontSize: 12)),
              if (close.changes.isNotEmpty) ...[
                const SizedBox(height: 12),
                HomeCard(
                  label: 'Changed since the close',
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      for (final c in close.changes) Text('• $c', style: const TextStyle(height: 1.4)),
                      for (final f in close.figures)
                        Text('${f.$1}: ${f.$2} → ${f.$3}',
                            style: const TextStyle(color: AccnomosColors.muted, height: 1.4)),
                    ],
                  ),
                ),
              ],
              if (close.summary != null && close.summary!.isNotEmpty) ...[
                const SizedBox(height: 12),
                HomeCard(
                  label: close.label,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(close.summary!.replaceAll('*', ''), style: const TextStyle(height: 1.4)),
                      const SizedBox(height: 6),
                      Text(close.summaryByCode ? 'Written by code' : 'Written by your AI; figures checked by code',
                          style: const TextStyle(color: AccnomosColors.muted, fontSize: 12)),
                    ],
                  ),
                ),
              ],
              const SizedBox(height: 12),
              if (close.steps.isEmpty)
                Text('No close has been run for ${close.label} yet.',
                    style: const TextStyle(color: AccnomosColors.muted)),
              for (final s in close.steps) ...[
                _StepTile(step: s),
                const SizedBox(height: 8),
              ],
            ],
          ],
        ),
      ),
    );
  }
}

class _StepTile extends StatelessWidget {
  const _StepTile({required this.step});

  final CloseStep step;

  @override
  Widget build(BuildContext context) {
    final (bg, fg) = switch (step.status) {
      'ok' => (AccnomosColors.tealTint, AccnomosColors.tealDark),
      'needs_you' => (const Color(0xFFFFF7ED), const Color(0xFF8A3F06)),
      _ => (AccnomosColors.ground, AccnomosColors.muted),
    };
    return Semantics(
      label: 'Step ${step.n}: ${step.title}, ${step.statusLabel}',
      child: HomeCard(
        label: '${step.n}  ${step.title}',
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(vertical: 2, horizontal: 8),
              decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(10)),
              child: Text(step.statusLabel,
                  style: TextStyle(color: fg, fontSize: 12, fontWeight: FontWeight.w800)),
            ),
            const SizedBox(height: 6),
            Text(step.reason, style: const TextStyle(height: 1.4)),
            for (final f in step.found)
              if (f.text != step.reason)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text('${f.blocking ? 'Blocks the close: ' : ''}${f.text}',
                      style: TextStyle(
                          height: 1.4,
                          fontSize: 13,
                          color: f.level == 'note' ? AccnomosColors.muted : AccnomosColors.ink)),
                ),
          ],
        ),
      ),
    );
  }
}

/// Home › Month-end: "October: 3 things need you before close", from
/// `GET /close`; a tap opens the read-only checklist.
class MonthEndCard extends StatefulWidget {
  const MonthEndCard({
    super.key,
    required this.clientFor,
    this.today,
    this.refresh = 0,
  });

  final Future<RuntimeClient> Function() clientFor;
  final DateTime? today;
  final int refresh;

  @override
  State<MonthEndCard> createState() => _MonthEndCardState();
}

class _MonthEndCardState extends State<MonthEndCard> {
  CloseOverview? _overview;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(MonthEndCard old) {
    super.didUpdateWidget(old);
    if (old.refresh != widget.refresh) _load();
  }

  Future<void> _load() async {
    try {
      final client = await widget.clientFor();
      final data = await client.closeOverview(today: _isoDay(widget.today ?? DateTime.now()));
      if (mounted) setState(() => _overview = CloseOverview.fromJson(data));
    } catch (e) {
      if (mounted) setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    }
  }

  @override
  Widget build(BuildContext context) {
    final o = _overview;
    return InkWell(
      borderRadius: BorderRadius.circular(14),
      onTap: () => Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => MonthEndScreen(month: (o?.month.isNotEmpty ?? false) ? o!.month : null))),
      child: HomeCard(
        label: 'Month-end',
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              o?.headline ?? (_error != null ? 'Could not load the month-end status.' : 'Checking…'),
              style: TextStyle(
                  fontWeight: FontWeight.w700,
                  height: 1.35,
                  color: (o?.warn ?? false) ? const Color(0xFF8A3F06) : AccnomosColors.ink),
            ),
            for (final c in o?.changed ?? const <String>[])
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(c, style: const TextStyle(color: Color(0xFF8A3F06), fontSize: 13)),
              ),
          ],
        ),
      ),
    );
  }
}
