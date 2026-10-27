import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../services/auth.dart';
import '../services/proposal_editing.dart' show formatPence;
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/web_only.dart';
import 'settings_screen.dart';

/// Pay runs, read-only on the phone: every pay run with its status and
/// totals, and a detail view with the lines plus the estimate label.
/// Estimates only — confirming and exporting happen in the web app, which
/// says so on screen.
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
      final data = await (await _booksClient()).payrollRuns();
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
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text('Payroll',
            style: Theme.of(context).textTheme.headlineSmall),
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
                      borderRadius: BorderRadius.circular(14))),
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
          if (_runs.isEmpty)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: const Color(0xFFE3E1D8)),
              ),
              child: const Text('No pay runs yet — prepare one in the web app.',
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
          const WebOnlyCard(
            message:
                'Preparing, editing, exporting and confirming a pay run happen on the web — the phone shows estimates only.',
            page: '/payroll',
          ),
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
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Material(
        type: MaterialType.transparency,
        borderRadius: BorderRadius.circular(14),
        child: ListTile(
          title: Text(title,
              style: const TextStyle(fontWeight: FontWeight.w800)),
          subtitle: Text(
            '${status.isEmpty ? 'Pay run' : _capitalise(status)} · ${formatPence(total)} gross',
            style:
                const TextStyle(color: AccnomosColors.muted, fontSize: 12),
          ),
          trailing: const Icon(Icons.chevron_right_outlined),
          onTap: () => Navigator.of(context).push(
            MaterialPageRoute(
                builder: (_) => PayrollDetailScreen(run: run)),
          ),
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
      return '$month · paid ${_ukDate(payDate)}';
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

/// One pay run with its lines and the estimate label. Read-only: no
/// confirm or export on the phone.
class PayrollDetailScreen extends StatelessWidget {
  const PayrollDetailScreen({super.key, required this.run});
  final Map<String, dynamic> run;

  @override
  Widget build(BuildContext context) {
    final lines = <Map<String, dynamic>>[];
    if (run['lines'] is List) {
      for (final line in run['lines'] as List) {
        if (line is Map) lines.add(Map<String, dynamic>.from(line));
      }
    }
    final warnings = <String>[];
    if (run['warnings'] is List) {
      for (final w in run['warnings'] as List) {
        warnings.add(w.toString());
      }
    }
    final estimate = (run['estimate'] ?? '').toString();
    final status = (run['status'] ?? '').toString();
    final title = _PayrollScreenState._runTitle(run);
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(title,
            style: Theme.of(context).textTheme.headlineSmall),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: const Color(0xFFE3E1D8)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  status.isEmpty
                      ? 'Pay run'
                      : 'Status: ${_PayrollScreenState._capitalise(status)}',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 2),
                Text(
                  'Gross ${_PayrollScreenState._runTotal(run) == 0 ? '—' : formatPence(_PayrollScreenState._runTotal(run))}',
                  style: const TextStyle(
                      color: AccnomosColors.muted, height: 1.4),
                ),
                const Divider(height: 24),
                if (lines.isEmpty)
                  const Text('No lines in this run.',
                      style: TextStyle(
                          color: AccnomosColors.muted, height: 1.4))
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
                border:
                    Border.all(color: const Color(0xFFF3C892)),
              ),
              child: Text(warnings.join('\n'),
                  style: const TextStyle(
                      color: Color(0xFF8A3F06), height: 1.4)),
            ),
          if (estimate.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text(estimate,
                style: const TextStyle(
                    color: AccnomosColors.muted,
                    fontSize: 12,
                    height: 1.4)),
          ],
          const WebOnlyCard(
            message:
                'Preparing, editing, exporting and confirming a pay run happen on the web — the phone shows estimates only.',
            page: '/payroll',
          ),
        ],
      ),
    );
  }

  Widget _lineRow(Map<String, dynamic> line) {
    final staffId = (line['staff_id'] ?? '').toString();
    final hours = line['hours'];
    final hoursLabel = hours is num
        ? (hours == hours.toInt()
            ? '${hours.toInt()} h'
            : '$hours h')
        : '';
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
                Text(staffId.isEmpty ? 'Staff member' : staffId,
                    style: const TextStyle(fontWeight: FontWeight.w700)),
                Text(
                  [
                    if (hoursLabel.isNotEmpty) hoursLabel,
                    if (net is num) 'est. net ${formatPence(net.toInt())}',
                    if (notes.isNotEmpty) notes,
                  ].join(' · '),
                  style: const TextStyle(
                      color: AccnomosColors.muted, fontSize: 12),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Text(gross is num ? formatPence(gross.toInt()) : '—',
              style: const TextStyle(
                  fontWeight: FontWeight.w800,
                  color: AccnomosColors.ink,
                  fontSize: 16)),
        ],
      ),
    );
  }
}
