import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../services/auth.dart';
import '../services/proposal_editing.dart' show formatPence;
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../services/share.dart';
import 'settings_screen.dart';

/// Pay runs, as on the web's Payroll page (`/payroll/runs`): prepare a run
/// from a month's timesheets, edit hours, rates and notes, export the CSV for
/// your payroll provider (saved to 05 Payroll and shareable), confirm the
/// figures the provider calculated (that posts the wages journal) or reopen
/// it. The PAYE figures here are estimates, and the screen says so.
class PayrollScreen extends StatefulWidget {
  const PayrollScreen({super.key});

  @override
  State<PayrollScreen> createState() => _PayrollScreenState();
}

class _PayrollScreenState extends State<PayrollScreen> {
  final AuthService _auth = AuthService();
  AppSettings? _settings;
  Account? _account;
  bool _authChecked = false;
  bool _loading = false;
  String? _error;
  List<Map<String, dynamic>> _runs = const [];
  String? _estimate;
  String? _taxYear;
  Map<String, String> _staffNames = const {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  String _friendly(Object e) => e.toString().replaceFirst('Exception: ', '');

  Future<void> _load() async {
    final settings = await AppSettings.load();
    Account? account;
    try {
      account = await _auth.account();
    } catch (_) {
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

  Future<void> _reload({bool quiet = false}) async {
    if (_settings == null || _account == null || _loading) return;
    if (!quiet) setState(() => _loading = true);
    setState(() => _error = null);
    try {
      final client = await _booksClient();
      final data = await client.payrollRuns();
      try {
        final staff = await client.staff();
        _staffNames = {
          for (final m in staff) (m['id'] ?? '').toString(): (m['name'] ?? '').toString(),
        };
      } catch (_) {
        // Names are a nicety: the run still shows with staff ids.
      }
      final runs = <Map<String, dynamic>>[];
      if (data['runs'] is List) {
        for (final r in data['runs'] as List) {
          if (r is Map) runs.add(Map<String, dynamic>.from(r));
        }
      }
      if (!mounted) return;
      setState(() {
        _runs = runs;
        _estimate = (data['estimate'] ?? '').toString();
        _taxYear = (data['tax_year'] ?? '').toString();
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
        title: Text('Payroll'),
        actions: [
          if (_account != null)
            IconButton(
              icon: _loading
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.refresh_outlined),
              tooltip: 'Reload pay runs',
              constraints:
                  const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _loading ? null : () => _reload(quiet: true),
            ),
        ],
      ),
      body: !_authChecked || (_loading && _runs.isEmpty && _error == null)
          ? const Center(child: CircularProgressIndicator())
          : _account == null
              ? _signedOut(context)
              : _error != null && _runs.isEmpty
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
              'Sign in with Microsoft to see your pay runs.',
              textAlign: TextAlign.center,
              style: TextStyle(color: AccnomosColors.muted, height: 1.4),
            ),
            const SizedBox(height: 16),
            FilledButton(
              style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size.fromHeight(52),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12))),
              onPressed: () => Navigator.of(context)
                  .push(
                    MaterialPageRoute(
                        builder: (_) => const SettingsScreen()),
                  )
                  .then((_) => _load()),
              child: const Text('Open settings to sign in',
                  style:
                      TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
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
            Text(_error ?? 'Could not load pay runs.',
                textAlign: TextAlign.center,
                style: const TextStyle(
                    color: Color(0xFF8A3F06), height: 1.4)),
            const SizedBox(height: 16),
            OutlinedButton(
              style: OutlinedButton.styleFrom(
                minimumSize: const Size.fromHeight(48),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12)),
              ),
              onPressed: () => _reload(),
              child: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }

  /// Months to prepare: this one and the eleven before, newest first.
  static List<String> _periods(DateTime today) {
    final out = <String>[];
    var y = today.year, m = today.month;
    for (var i = 0; i < 12; i++) {
      out.add('$y-${m.toString().padLeft(2, '0')}');
      m -= 1;
      if (m == 0) {
        m = 12;
        y -= 1;
      }
    }
    return out;
  }

  Future<void> _prepare() async {
    final periods = _periods(DateTime.now());
    var period = periods.first;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) => AlertDialog(
          title: const Text('Prepare a pay run'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            DropdownButtonFormField<String>(
              initialValue: period,
              decoration: const InputDecoration(labelText: 'Month'),
              items: [
                for (final p in periods)
                  DropdownMenuItem(value: p, child: Text(_ukMonth('$p-01'))),
              ],
              onChanged: (v) => set(() => period = v ?? period),
            ),
            const SizedBox(height: 8),
            const Text('Hours come from that month’s timesheets; you can change them before exporting.',
                style: TextStyle(color: AccnomosColors.muted, fontSize: 13)),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Prepare')),
          ],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    try {
      final run = await (await _booksClient()).preparePayRun(period);
      if (!mounted) return;
      await _openRun(run);
    } catch (e) {
      messenger.showSnackBar(SnackBar(duration: const Duration(seconds: 6), content: Text(_friendly(e))));
    }
  }

  Future<void> _openRun(Map<String, dynamic> run) async {
    await Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => PayrollDetailScreen(
        run: run,
        staffNames: _staffNames,
        clientFor: _booksClient,
      ),
    ));
    await _reload(quiet: true);
  }

  Widget _body() {
    return RefreshIndicator(
      onRefresh: () => _reload(quiet: true),
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_taxYear != null && _taxYear!.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text('Tax year $_taxYear',
                  style: const TextStyle(
                      fontWeight: FontWeight.w800,
                      color: AccnomosColors.ink)),
            ),
          FilledButton.icon(
            icon: const Icon(Icons.playlist_add_outlined),
            label: const Text('Prepare a pay run'),
            onPressed: _prepare,
          ),
          const SizedBox(height: 12),
          if (_runs.isEmpty)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: AccnomosColors.border),
              ),
              child: const Text('No pay runs yet.',
                  style: TextStyle(
                      color: AccnomosColors.muted, height: 1.4)),
            )
          else
            for (final run in _runs) _runCard(run),
          if (_estimate != null && _estimate!.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(_estimate!,
                style: const TextStyle(
                    color: AccnomosColors.muted,
                    fontSize: 12,
                    height: 1.4)),
          ],
        ],
      ),
    );
  }

  Widget _runCard(Map<String, dynamic> run) {
    final title = _runTitle(run);
    final status = (run['status'] ?? '').toString();
    final total = _runTotal(run);
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AccnomosColors.border),
      ),
      child: Material(
        type: MaterialType.transparency,
        borderRadius: BorderRadius.circular(12),
        child: ListTile(
          title: Text(title,
              style: const TextStyle(fontWeight: FontWeight.w800)),
          subtitle: Text(
            '${status.isEmpty ? 'Pay run' : _capitalise(status)} · ${formatPence(total)} gross',
            style:
                const TextStyle(color: AccnomosColors.muted, fontSize: 12),
          ),
          trailing: const Icon(Icons.chevron_right_outlined),
          onTap: () => _openRun(run),
        ),
      ),
    );
  }

  /// Gross pay for the run: the confirmed figure when confirmed, else the
  /// sum of the estimate lines. Pence throughout.
  static int _runTotal(Map<String, dynamic> run) {
    final confirmed = run['confirmed_gross_pence'];
    if (confirmed is num) return confirmed.toInt();
    var total = 0;
    if (run['lines'] is List) {
      for (final line in run['lines'] as List) {
        if (line is Map) {
          final gross = line['gross_pence'];
          if (gross is num) total += gross.toInt();
        }
      }
    }
    return total;
  }

  static String _runTitle(Map<String, dynamic> run) {
    final start = (run['period_start'] ?? '').toString();
    final end = (run['period_end'] ?? '').toString();
    if (start.isEmpty) return 'Pay run';
    final payDate = (run['pay_date'] ?? '').toString();
    final month = _ukMonth(start);
    if (payDate.isNotEmpty && payDate != start) {
      // Only a confirmed run has been paid; a draft is still to pay.
      final status = (run['status'] ?? '').toString();
      final paid = status == 'confirmed' || status == 'paid' || status == 'submitted';
      return '$month · ${paid ? 'paid' : 'pay day'} ${_ukDate(payDate)}';
    }
    return end.isEmpty || end == start ? month : '$month ($start – $end)';
  }

  static String _capitalise(String text) =>
      text.isEmpty ? text : text[0].toUpperCase() + text.substring(1);

  static String _ukMonth(String iso) {
    try {
      final d = DateTime.parse(iso.trim());
      const months = [
        'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December',
      ];
      return '${months[d.month - 1]} ${d.year}';
    } catch (_) {
      return iso;
    }
  }

  static String _ukDate(String iso) {
    try {
      final d = DateTime.parse(iso.trim());
      const months = [
        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
      ];
      return '${d.day} ${months[d.month - 1]} ${d.year}';
    } catch (_) {
      return iso;
    }
  }
}

/// One pay run: its lines, estimates and warnings. A draft can be edited
/// (hours, hourly rate, notes), exported (05 Payroll/<period>.csv, then the
/// share sheet) and confirmed with the provider's real figures; a confirmed
/// run can be reopened. Same routes as the web.
class PayrollDetailScreen extends StatefulWidget {
  const PayrollDetailScreen({
    super.key,
    required this.run,
    this.staffNames = const {},
    this.clientFor,
  });

  final Map<String, dynamic> run;
  final Map<String, String> staffNames;

  /// Null shows the run read-only (no client to act with).
  final Future<RuntimeClient> Function()? clientFor;

  @override
  State<PayrollDetailScreen> createState() => _PayrollDetailScreenState();
}

class _LineEdit {
  _LineEdit(Map<String, dynamic> line)
      : staffId = (line['staff_id'] ?? '').toString(),
        hours = TextEditingController(text: _num(line['hours'])),
        rate = TextEditingController(
            text: line['rate_pence'] is num ? ((line['rate_pence'] as num) / 100).toStringAsFixed(2) : ''),
        notes = TextEditingController(text: (line['notes'] ?? '').toString());

  static String _num(Object? v) =>
      v is num ? (v == v.roundToDouble() ? v.toInt().toString() : v.toString()) : '';

  final String staffId;
  final TextEditingController hours;
  final TextEditingController rate;
  final TextEditingController notes;

  void dispose() {
    hours.dispose();
    rate.dispose();
    notes.dispose();
  }
}

class _PayrollDetailScreenState extends State<PayrollDetailScreen> {
  late Map<String, dynamic> _run = widget.run;
  List<_LineEdit> _edits = const [];
  bool _busy = false;
  String? _error;
  String? _exportedPath;

  String get _period {
    final start = (_run['period_start'] ?? '').toString();
    return start.length >= 7 ? start.substring(0, 7) : start;
  }

  bool get _draft => (_run['status'] ?? 'draft').toString() == 'draft';

  List<Map<String, dynamic>> get _lines => [
        if (_run['lines'] is List)
          for (final l in _run['lines'] as List)
            if (l is Map) Map<String, dynamic>.from(l),
      ];

  @override
  void initState() {
    super.initState();
    _resetEdits();
  }

  void _resetEdits() {
    for (final e in _edits) {
      e.dispose();
    }
    _edits = [for (final l in _lines) _LineEdit(l)];
  }

  @override
  void dispose() {
    for (final e in _edits) {
      e.dispose();
    }
    super.dispose();
  }

  String _name(String id) {
    final n = widget.staffNames[id];
    return n == null || n.isEmpty ? (id.isEmpty ? 'Staff member' : id) : n;
  }

  Future<void> _act(Future<Map<String, dynamic>> Function(RuntimeClient c) work, String done) async {
    final f = widget.clientFor;
    if (f == null || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final messenger = ScaffoldMessenger.of(context);
    try {
      final next = await work(await f());
      if (!mounted) return;
      setState(() {
        if (next.containsKey('lines')) {
          _run = next;
          _resetEdits();
        }
      });
      messenger.showSnackBar(SnackBar(duration: const Duration(seconds: 4), content: Text(done)));
    } catch (e) {
      if (mounted) setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  List<Map<String, dynamic>>? _editedLines() {
    final out = <Map<String, dynamic>>[];
    for (final e in _edits) {
      final hours = double.tryParse(e.hours.text.trim());
      final rate = double.tryParse(e.rate.text.trim().replaceAll('£', ''));
      if (hours == null || hours < 0) {
        setState(() => _error = '${_name(e.staffId)}: hours must be a number, e.g. 37.5.');
        return null;
      }
      if (rate == null || rate < 0) {
        setState(() => _error = '${_name(e.staffId)}: rate is pounds per hour, e.g. 18.50.');
        return null;
      }
      out.add({
        'staff_id': e.staffId,
        'hours': hours,
        'rate_pence': (rate * 100).round(),
        'notes': e.notes.text.trim(),
      });
    }
    return out;
  }

  Future<void> _save() async {
    final lines = _editedLines();
    if (lines == null) return;
    await _act((c) => c.editPayRun(_period, lines, payDate: _run['pay_date']?.toString()), 'Pay run saved.');
  }

  Future<void> _export() async {
    final f = widget.clientFor;
    if (f == null || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final res = await (await f()).exportPayRun(_period);
      if (!mounted) return;
      setState(() => _exportedPath = (res['path'] ?? '').toString());
      final csv = (res['csv'] ?? '').toString();
      if (csv.isNotEmpty) {
        await ShareText.share(csv, subject: 'Pay run $_period (estimate)', mime: 'text/csv');
      }
    } catch (e) {
      if (mounted) setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirm() async {
    final gross = TextEditingController(
        text: (_PayrollScreenState._runTotal(_run) / 100).toStringAsFixed(2));
    var erNi = 0;
    for (final l in _lines) {
      final v = l['est_er_ni_pence'];
      if (v is num) erNi += v.toInt();
    }
    final ni = TextEditingController(text: (erNi / 100).toStringAsFixed(2));
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Confirm the pay run'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('Enter the figures your payroll provider calculated, not the estimate. Confirming posts the wages journal.',
              style: TextStyle(height: 1.4)),
          const SizedBox(height: 8),
          TextField(
            controller: gross,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(labelText: 'Gross pay (£)'),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: ni,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(labelText: 'Employer NI (£)'),
          ),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Confirm')),
        ],
      ),
    );
    final g = double.tryParse(gross.text.trim().replaceAll('£', ''));
    final n = double.tryParse(ni.text.trim().replaceAll('£', ''));
    gross.dispose();
    ni.dispose();
    if (ok != true) return;
    if (g == null || n == null || g < 0 || n < 0) {
      setState(() => _error = 'Gross pay and employer NI are pounds, e.g. 4250.00.');
      return;
    }
    await _act((c) => c.confirmPayRun(_period, (g * 100).round(), (n * 100).round()),
        'Confirmed: the wages journal is posted.');
  }

  @override
  Widget build(BuildContext context) {
    final lines = _lines;
    final warnings = [
      if (_run['warnings'] is List)
        for (final w in _run['warnings'] as List) w.toString(),
    ];
    final estimate = (_run['estimate'] ?? '').toString();
    final status = (_run['status'] ?? '').toString();
    final title = _PayrollScreenState._runTitle(_run);
    final canAct = widget.clientFor != null;
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(title: Text(title)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AccnomosColors.border),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  status.isEmpty ? 'Pay run' : 'Status: ${_PayrollScreenState._capitalise(status)}',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 2),
                Text(
                  'Gross ${_PayrollScreenState._runTotal(_run) == 0 ? '—' : formatPence(_PayrollScreenState._runTotal(_run))}'
                  '${status == 'confirmed' ? ' (confirmed)' : ' (estimate)'}',
                  style: const TextStyle(color: AccnomosColors.muted, height: 1.4),
                ),
                const Divider(height: 24),
                if (lines.isEmpty)
                  const Text('No lines in this run.', style: TextStyle(color: AccnomosColors.muted, height: 1.4))
                else if (_draft && canAct)
                  for (var i = 0; i < _edits.length && i < lines.length; i++) _editRow(_edits[i], lines[i])
                else
                  for (final line in lines) _lineRow(line),
              ],
            ),
          ),
          if (warnings.isNotEmpty)
            Container(
              width: double.infinity,
              margin: const EdgeInsets.only(top: 12),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFFFFF7ED),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: const Color(0xFFF3C892)),
              ),
              child: Text(warnings.join('\n'), style: const TextStyle(color: Color(0xFF8A3F06), height: 1.4)),
            ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(_error!, style: const TextStyle(color: Color(0xFFA12626), height: 1.4)),
            ),
          if (canAct) ...[
            const SizedBox(height: 12),
            Wrap(spacing: 8, runSpacing: 8, children: [
              if (_draft && lines.isNotEmpty)
                FilledButton(onPressed: _busy ? null : _save, child: const Text('Save changes')),
              if (lines.isNotEmpty)
                OutlinedButton.icon(
                  icon: const Icon(Icons.ios_share_outlined),
                  label: const Text('Export CSV'),
                  onPressed: _busy ? null : _export,
                ),
              if (_draft && lines.isNotEmpty)
                OutlinedButton(onPressed: _busy ? null : _confirm, child: const Text('Confirm with real figures')),
              if (!_draft)
                OutlinedButton(
                  onPressed: _busy ? null : () => _act((c) => c.reopenPayRun(_period), 'Reopened: the journal is undone.'),
                  child: const Text('Reopen'),
                ),
            ]),
            if (_exportedPath != null && _exportedPath!.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text('Saved to $_exportedPath in your books.',
                    style: const TextStyle(color: AccnomosColors.muted, fontSize: 13)),
              ),
          ],
          if (estimate.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text(estimate, style: const TextStyle(color: AccnomosColors.muted, fontSize: 12, height: 1.4)),
          ],
        ],
      ),
    );
  }

  Widget _editRow(_LineEdit e, Map<String, dynamic> line) {
    final gross = line['gross_pence'];
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Expanded(child: Text(_name(e.staffId), style: const TextStyle(fontWeight: FontWeight.w700))),
            Text(gross is num ? formatPence(gross.toInt()) : '—', style: const TextStyle(fontWeight: FontWeight.w800)),
          ]),
          const SizedBox(height: 6),
          Row(children: [
            Expanded(
              child: TextField(
                controller: e.hours,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: 'Hours', isDense: true),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: TextField(
                controller: e.rate,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: '£ per hour', isDense: true),
              ),
            ),
          ]),
          const SizedBox(height: 6),
          TextField(controller: e.notes, decoration: const InputDecoration(labelText: 'Notes', isDense: true)),
          if (line['est_net_pence'] is num)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text('Estimated net ${formatPence((line['est_net_pence'] as num).toInt())}',
                  style: const TextStyle(color: AccnomosColors.muted, fontSize: 12)),
            ),
        ],
      ),
    );
  }

  Widget _lineRow(Map<String, dynamic> line) {
    final staffId = (line['staff_id'] ?? '').toString();
    final hours = line['hours'];
    final hoursLabel = hours is num ? (hours == hours.toInt() ? '${hours.toInt()} h' : '$hours h') : '';
    final gross = line['gross_pence'];
    final net = line['est_net_pence'];
    final notes = (line['notes'] ?? '').toString();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 7),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(_name(staffId), style: const TextStyle(fontWeight: FontWeight.w700)),
                Text(
                  [
                    if (hoursLabel.isNotEmpty) hoursLabel,
                    if (net is num) 'est. net ${formatPence(net.toInt())}',
                    if (notes.isNotEmpty) notes,
                  ].join(' · '),
                  style: const TextStyle(color: AccnomosColors.muted, fontSize: 12),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Text(gross is num ? formatPence(gross.toInt()) : '—',
              style: const TextStyle(fontWeight: FontWeight.w800, color: AccnomosColors.ink, fontSize: 16)),
        ],
      ),
    );
  }
}
