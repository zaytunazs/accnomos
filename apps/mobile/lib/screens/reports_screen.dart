import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/reports.dart';
import '../models/vat_return.dart';
import '../services/auth.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import 'settings_screen.dart';

const _warnBg = Color(0xFFFFF7ED);
const _warnBorder = Color(0xFFF3C892);
const _warnInk = Color(0xFF8A3F06);
const _line = Color(0xFFE3E1D8);

/// Aged buckets in column order (`GET /reports/aged`, like the web's
/// `AGED_BUCKETS` in `apps/web/src/lib/runtime.ts`).
const _buckets = ['current', '0-30', '31-60', '61-90', '90+'];

String _bucketLabel(String b) => b == 'current' ? 'Now due' : '$b days';

/// Reports from `GET /reports/*`, worked out by code from the user's own
/// ledger events. P&L follows the picked VAT period (like the web's reports
/// page); only "Save to 07 Reports" writes anything. The phone does no
/// maths: every figure is shown as the runtime gave it.
class ReportsScreen extends StatefulWidget {
  const ReportsScreen({super.key});

  @override
  State<ReportsScreen> createState() => _ReportsScreenState();
}

class _ReportsScreenState extends State<ReportsScreen>
    with SingleTickerProviderStateMixin {
  final AuthService _auth = AuthService();
  late final TabController _tabs = TabController(length: 4, vsync: this);
  AppSettings? _settings;
  Account? _account;
  bool _authChecked = false;
  bool _loading = false;
  String? _error;
  List<VatPeriod> _periods = const [];
  VatPeriod? _picked; // null: the current period
  PlReport? _pl;
  AgedReport? _aged;
  VatSummary? _vat;
  Trend? _trend;
  bool _saving = false;
  String? _savedName;
  String? _savedError;

  bool get _sample =>
      (_pl?.sample ?? false) ||
      (_aged?.sample ?? false) ||
      (_vat?.sample ?? false) ||
      (_trend?.sample ?? false);

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  String _friendly(Object e) => e.toString().replaceFirst('Exception: ', '');

  /// The picked period's span, or null for the current period (the runtime
  /// defaults to the VAT period we are in now). Empty dates count as unset.
  static String? _spanStart(VatPeriod? picked) =>
      picked != null && picked.start.isNotEmpty ? picked.start : null;
  static String? _spanEnd(VatPeriod? picked) =>
      picked != null && picked.end.isNotEmpty ? picked.end : null;

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

  /// Just the profit and loss for the picked period.
  Future<void> _reloadPl() async {
    if (_settings == null || _account == null || _loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final client = await _booksClient();
      final picked = _picked;
      final pl = PlReport.fromJson(await client.reportsPl(
        from: _spanStart(picked),
        to: _spanEnd(picked),
      ));
      if (!mounted) return;
      setState(() => _pl = pl);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Everything, and the period list too unless only the pick changed.
  Future<void> _reload({bool withPeriods = true}) async {
    final settings = _settings;
    if (settings == null || _account == null || _loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final client = await _booksClient();
      if (withPeriods || _periods.isEmpty) {
        _periods = VatPeriod.listFromJson(await client.vatPeriods());
      }
      final picked = _picked;
      final results = await Future.wait([
        client.reportsPl(from: _spanStart(picked), to: _spanEnd(picked)),
        client.reportsAged(),
        client.reportsVat(),
        client.reportsTrend(),
      ]);
      if (!mounted) return;
      setState(() {
        _pl = PlReport.fromJson(results[0]);
        _aged = AgedReport.fromJson(results[1]);
        _vat = VatSummary.fromJson(results[2]);
        _trend = Trend.fromJson(results[3]);
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Save every report as one spreadsheet in 07 Reports (posts nothing).
  Future<void> _export() async {
    if (_settings == null || _account == null || _saving) return;
    setState(() {
      _saving = true;
      _savedName = null;
      _savedError = null;
    });
    try {
      final client = await _booksClient();
      final picked = _picked;
      final saved = ReportExport.fromJson(await client.reportExport(
        from: _spanStart(picked),
        to: _spanEnd(picked),
      ));
      if (!mounted) return;
      setState(() => _savedName = saved.name);
    } catch (e) {
      if (!mounted) return;
      setState(() => _savedError = _friendly(e));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          'Reports',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        actions: [
          if (_account != null)
            IconButton(
              icon: _loading
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.refresh_outlined),
              tooltip: 'Reload reports',
              constraints:
                  const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _loading ? null : () => _reload(withPeriods: false),
            ),
        ],
      ),
      body: !_authChecked || (_loading && _pl == null)
          ? const Center(child: CircularProgressIndicator())
          : _account == null
              ? _signedOut()
              : _pl == null && _aged == null && _vat == null && _trend == null
                  ? _errorView()
                  : _body(),
    );
  }

  Widget _signedOut() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Text(
              'Sign in with Microsoft to see your reports.',
              textAlign: TextAlign.center,
              style: TextStyle(color: AccnomosColors.muted, height: 1.4),
            ),
            const SizedBox(height: 16),
            FilledButton(
              style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size.fromHeight(52),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14))),
              onPressed: () => Navigator.of(context)
                  .push(
                    MaterialPageRoute(
                        builder: (_) => const SettingsScreen()),
                  )
                  .then((_) => _load()),
              child: const Text('Open settings to sign in',
                  style: TextStyle(
                      fontWeight: FontWeight.w800, fontSize: 16)),
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
            Text(
              _error ?? 'Could not load the reports.',
              textAlign: TextAlign.center,
              style: const TextStyle(color: _warnInk, height: 1.4),
            ),
            const SizedBox(height: 16),
            OutlinedButton(
              style: OutlinedButton.styleFrom(
                minimumSize: const Size.fromHeight(48),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14)),
              ),
              onPressed: () => _reload(),
              child: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _body() {
    return Column(
      children: [
        if (_sample)
          Container(
            width: double.infinity,
            margin: const EdgeInsets.fromLTRB(16, 4, 16, 0),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: _warnBg,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: _warnBorder),
            ),
            child: const Text(
              'SAMPLE — these are the demo books',
              style: TextStyle(color: _warnInk, fontWeight: FontWeight.w800),
            ),
          ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (_periods.isNotEmpty) _periodPicker(),
              const SizedBox(height: 8),
              FilledButton(
                style: FilledButton.styleFrom(
                    backgroundColor: AccnomosColors.teal,
                    minimumSize: const Size.fromHeight(48),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(14))),
                onPressed: _saving ? null : _export,
                child: Text(
                  _saving ? 'Saving…' : 'Save to 07 Reports',
                  style: const TextStyle(
                      fontWeight: FontWeight.w800, fontSize: 16),
                ),
              ),
              if (_savedName != null)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text(
                    'Saved $_savedName in your OneDrive.',
                    style: const TextStyle(
                        color: AccnomosColors.muted, fontSize: 13),
                  ),
                ),
              if (_savedError != null)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text(
                    _savedError!,
                    style:
                        const TextStyle(color: _warnInk, fontSize: 13),
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: 8),
        TabBar(
          controller: _tabs,
          labelColor: AccnomosColors.tealDark,
          unselectedLabelColor: AccnomosColors.muted,
          indicatorColor: AccnomosColors.teal,
          tabs: const [
            Tab(text: 'P&L'),
            Tab(text: 'Aged'),
            Tab(text: 'VAT'),
            Tab(text: 'Trend'),
          ],
        ),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : TabBarView(
                  controller: _tabs,
                  children: [
                    _plTab(),
                    _agedTab(),
                    _vatTab(),
                    _trendTab(),
                  ],
                ),
        ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.all(8),
            child: Text(_error!,
                textAlign: TextAlign.center,
                style: const TextStyle(color: _warnInk, fontSize: 12)),
          ),
      ],
    );
  }

  Widget _periodPicker() {
    final current = _periods.where((p) => p.current).firstOrNull ?? _periods.first;
    final value = _picked?.period ?? current.period;
    return DropdownButtonFormField<String>(
      key: ValueKey(value),
      initialValue: value,
      isExpanded: true,
      decoration: const InputDecoration(
        labelText: 'Period for profit and loss',
        border: OutlineInputBorder(),
      ),
      items: [
        for (final p in _periods)
          DropdownMenuItem(
            value: p.period,
            child: Text(p.caption, overflow: TextOverflow.ellipsis),
          ),
      ],
      onChanged: _loading
          ? null
          : (period) {
              if (period == null) return;
              final pick = _periods.firstWhere((p) => p.period == period);
              setState(() {
                _picked = pick.current ? null : pick;
                _pl = null;
              });
              _reloadPl();
            },
    );
  }

  // Tab content (public widgets, so widget tests can pump them) -------- //

  Widget _plTab() {
    final pl = _pl;
    if (pl == null) {
      return const Center(child: Text('Nothing in this period.'));
    }
    return PlReportView(pl: pl);
  }

  Widget _agedTab() {
    final aged = _aged;
    if (aged == null) {
      return const Center(child: Text('Nothing unpaid.'));
    }
    return AgedReportView(aged: aged);
  }

  Widget _vatTab() {
    final vat = _vat;
    if (vat == null || vat.periods.isEmpty) {
      return const Center(child: Text('No VAT periods yet.'));
    }
    return VatSummaryView(vat: vat);
  }

  Widget _trendTab() {
    final trend = _trend;
    if (trend == null || trend.months.isEmpty) {
      return const Center(child: Text('No months yet.'));
    }
    return TrendView(trend: trend);
  }
}

/// Profit and loss for one period, as the runtime worked it out.
class PlReportView extends StatelessWidget {
  const PlReportView({super.key, required this.pl});

  final PlReport pl;

  @override
  Widget build(BuildContext context) {
    final loss = pl.netPence < 0;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _card([
          Text(
            'Profit and loss · ${pl.label}',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 2),
          Text(
            '${ukDate(pl.start)} – ${ukDate(pl.end)} · ${pl.entries} ${pl.entries == 1 ? 'entry' : 'entries'}',
            style:
                const TextStyle(color: AccnomosColors.muted, height: 1.4),
          ),
          const Divider(height: 24),
          _plSection('Sales', pl.sales),
          _plSection('Cost of sales', pl.costOfSales),
          _plTotal('Gross profit', pl.grossPence),
          _plSection('Overheads', pl.overheads),
          _plTotal(loss ? 'Net loss' : 'Net profit', pl.netPence,
              strong: true, warn: loss),
        ]),
        const SizedBox(height: 12),
        const Text(
          'As approved: each entry counts on its own date. Calculated by code — never by a model.',
          textAlign: TextAlign.center,
          style: TextStyle(color: AccnomosColors.muted, fontSize: 12),
        ),
      ],
    );
  }
}

Widget _plSection(String title, PlSection section) {
  return Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Padding(
        padding: const EdgeInsets.only(top: 8),
        child:
            Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
      ),
      if (section.rows.isEmpty)
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 4),
          child: Text('Nothing in this period.',
              style: TextStyle(color: AccnomosColors.muted)),
        ),
      for (final r in section.rows) _moneyRow(r.account, r.amountPence),
      _moneyRow('Total ${title.toLowerCase()}', section.totalPence,
          bold: true),
    ],
  );
}

Widget _plTotal(String title, int pence, {bool strong = false, bool warn = false}) {
  return Padding(
    padding: const EdgeInsets.symmetric(vertical: 6),
    child: Row(
      children: [
        Expanded(
          child: Text(title,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: strong ? 17 : 15,
                  color: warn ? _warnInk : AccnomosColors.ink)),
        ),
        Text(
          gbp(pence),
          style: TextStyle(
              fontWeight: FontWeight.w800,
              fontSize: strong ? 17 : 15,
              color: warn ? _warnInk : AccnomosColors.ink),
        ),
      ],
    ),
  );
}

Widget _moneyRow(String label, int pence, {bool bold = false}) {
  return Padding(
    padding: const EdgeInsets.symmetric(vertical: 5),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Text(label,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                  color: AccnomosColors.ink,
                  fontWeight: bold ? FontWeight.w700 : FontWeight.w400)),
        ),
        const SizedBox(width: 12),
        Text(
          gbp(pence),
          style: TextStyle(
              color: AccnomosColors.ink,
              fontWeight: bold ? FontWeight.w700 : FontWeight.w400,
              fontFeatures: const [FontFeature.tabularFigures()]),
        ),
      ],
    ),
  );
}

/// Aged debtors and creditors, the same figures as Contacts.
class AgedReportView extends StatelessWidget {
  const AgedReportView({super.key, required this.aged});

  final AgedReport aged;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _agedCard('Debtors', 'Customers who owe you.', aged.debtors),
        const SizedBox(height: 12),
        _agedCard('Creditors', 'Suppliers you owe.', aged.creditors),
      ],
    );
  }
}

Widget _agedCard(String title, String hint, AgedTable table) {
  return _card([
    Text(title,
        style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15)),
    Text(hint,
        style: const TextStyle(color: AccnomosColors.muted, fontSize: 13)),
    const SizedBox(height: 8),
    if (table.rows.isEmpty)
      const Text('Nothing unpaid.',
          style: TextStyle(
              color: AccnomosColors.muted, fontWeight: FontWeight.w600)),
    if (table.rows.isNotEmpty)
      SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: DataTable(
          columnSpacing: 16,
          columns: [
            const DataColumn(label: Text('Name')),
            for (final b in _buckets)
              DataColumn(label: Text(_bucketLabel(b)), numeric: true),
            const DataColumn(label: Text('Total'), numeric: true),
          ],
          rows: [
            for (final r in table.rows)
              DataRow(cells: [
                DataCell(ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 140),
                  child: Text(r.name, overflow: TextOverflow.ellipsis),
                )),
                for (final b in _buckets)
                  DataCell(Text(r.buckets[b] != null && r.buckets[b] != 0
                      ? gbp(r.buckets[b]!)
                      : '—')),
                DataCell(Text(gbp(r.totalPence),
                    style: const TextStyle(fontWeight: FontWeight.w700))),
              ]),
            DataRow(cells: [
              const DataCell(Text('Total',
                  style: TextStyle(fontWeight: FontWeight.w800))),
              for (final b in _buckets)
                DataCell(Text(gbp(table.buckets[b] ?? 0),
                    style: const TextStyle(fontWeight: FontWeight.w700))),
              DataCell(Text(gbp(table.totalPence),
                  style: const TextStyle(fontWeight: FontWeight.w800))),
            ]),
          ],
        ),
      ),
  ]);
}

/// VAT boxes per period, oldest first.
class VatSummaryView extends StatelessWidget {
  const VatSummaryView({super.key, required this.vat});

  final VatSummary vat;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _card([
          const Text('VAT by period',
              style: TextStyle(fontWeight: FontWeight.w800, fontSize: 15)),
          const Text('Positive net VAT is to pay.',
              style: TextStyle(color: AccnomosColors.muted, fontSize: 13)),
          const SizedBox(height: 8),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              columnSpacing: 16,
              columns: const [
                DataColumn(label: Text('Period')),
                DataColumn(label: Text('Net VAT'), numeric: true),
                DataColumn(label: Text('Sales ex VAT'), numeric: true),
                DataColumn(label: Text('Purchases ex VAT'), numeric: true),
              ],
              rows: [
                for (final p in vat.periods)
                  DataRow(cells: [
                    DataCell(Text(p.label)),
                    DataCell(Text(
                      p.netPence < 0
                          ? '${gbp(-p.netPence)} back'
                          : gbp(p.netPence),
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    )),
                    DataCell(Text('£${p.salesExPounds}')),
                    DataCell(Text('£${p.purchasesExPounds}')),
                  ]),
                DataRow(cells: [
                  const DataCell(Text('Total',
                      style: TextStyle(fontWeight: FontWeight.w800))),
                  DataCell(Text(gbp(vat.totalNetPence),
                      style: const TextStyle(fontWeight: FontWeight.w800))),
                  const DataCell(Text('')),
                  const DataCell(Text('')),
                ]),
              ],
            ),
          ),
        ]),
      ],
    );
  }
}

/// Monthly sales, purchases and net as a bar list (no chart library): each
/// bar is the month's sales against the best month.
class TrendView extends StatelessWidget {
  const TrendView({super.key, required this.trend});

  final Trend trend;

  @override
  Widget build(BuildContext context) {
    final maxSales =
        trend.months.map((m) => m.salesPence).fold(0, (a, b) => a > b ? a : b);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _card([
          const Text('Last 12 months',
              style: TextStyle(fontWeight: FontWeight.w800, fontSize: 15)),
          const Text(
              'Each month\u2019s net is its net profit, from the same accounts as the profit and loss.',
              style: TextStyle(color: AccnomosColors.muted, fontSize: 13)),
          const SizedBox(height: 8),
          for (final m in trend.months) _trendRow(m, maxSales),
        ]),
      ],
    );
  }
}

Widget _trendRow(TrendMonth m, int maxSales) {
  final fraction =
      maxSales <= 0 ? 0.0 : (m.salesPence / maxSales).clamp(0.0, 1.0);
  return Padding(
    padding: const EdgeInsets.symmetric(vertical: 6),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            SizedBox(
              width: 76,
              child: Text(m.label,
                  style: const TextStyle(fontWeight: FontWeight.w600)),
            ),
            Expanded(
              child: LayoutBuilder(
                builder: (context, box) => Container(
                  height: 10,
                  decoration: BoxDecoration(
                    color: const Color(0xFFEDEBE2),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  alignment: Alignment.centerLeft,
                  child: FractionallySizedBox(
                    widthFactor: fraction,
                    child: Container(
                      height: 10,
                      decoration: BoxDecoration(
                        color: AccnomosColors.teal,
                        borderRadius: BorderRadius.circular(999),
                      ),
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 8),
            Text(
              gbp(m.netPence),
              style: TextStyle(
                  fontWeight: FontWeight.w700,
                  color: m.netPence < 0 ? _warnInk : AccnomosColors.ink,
                  fontFeatures: const [FontFeature.tabularFigures()]),
            ),
          ],
        ),
        Padding(
          padding: const EdgeInsets.only(left: 84, top: 1),
          child: Text(
            'Sales ${gbp(m.salesPence)} · purchases ${gbp(m.purchasesPence)}',
            style:
                const TextStyle(color: AccnomosColors.muted, fontSize: 12),
          ),
        ),
      ],
    ),
  );
}

Widget _card(List<Widget> children) {
  return Container(
    width: double.infinity,
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: Colors.white,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: _line),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: children,
    ),
  );
}
