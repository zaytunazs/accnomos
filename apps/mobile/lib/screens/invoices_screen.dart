import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../services/auth.dart';
import '../services/proposal_editing.dart' show formatPence;
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import 'settings_screen.dart';

/// Sales invoices, read-only on the phone: what is unpaid, what is
/// overdue, and what came in before. Reminders and payments go from the
/// web app, which can send from the user's Outlook.
class InvoicesScreen extends StatefulWidget {
  const InvoicesScreen({super.key});

  @override
  State<InvoicesScreen> createState() => _InvoicesScreenState();
}

class _InvoicesScreenState extends State<InvoicesScreen> {
  final AuthService _auth = AuthService();
  AppSettings? _settings;
  Account? _account;
  bool _authChecked = false;
  bool _loading = false;
  String? _error;
  List<Map<String, dynamic>> _rows = const [];

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
      final rows = await (await _booksClient()).invoices();
      if (!mounted) return;
      setState(() => _rows = rows);
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
        title: Text('Invoices',
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
              tooltip: 'Reload invoices',
              constraints:
                  const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _loading ? null : () => _reload(quiet: true),
            ),
        ],
      ),
      body: !_authChecked || (_loading && _rows.isEmpty && _error == null)
          ? const Center(child: CircularProgressIndicator())
          : _account == null
              ? _signedOut(context)
              : _error != null && _rows.isEmpty
                  ? _errorView()
                  : _list(),
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
              'Sign in with Microsoft to see your sales invoices.',
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
            Text(_error ?? 'Could not load invoices.',
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

  Widget _list() {
    final unpaid =
        _rows.where((r) => (r['status'] ?? '') == 'sent').toList();
    final rest =
        _rows.where((r) => (r['status'] ?? '') != 'sent').toList();
    return RefreshIndicator(
      onRefresh: () => _reload(quiet: true),
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_rows.isEmpty)
            const Padding(
              padding: EdgeInsets.all(24),
              child: Text('No sales invoices yet.',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                      color: AccnomosColors.muted, height: 1.4)),
            ),
          if (unpaid.isNotEmpty) ...[
            _section('Unpaid'),
            for (final row in unpaid) _row(row),
          ],
          if (rest.isNotEmpty) ...[
            _section('Earlier'),
            for (final row in rest.take(20)) _row(row),
          ],
          const SizedBox(height: 12),
          const Text(
            'Read-only on the phone — send reminders and take payments from the web app.',
            textAlign: TextAlign.center,
            style: TextStyle(color: AccnomosColors.muted, fontSize: 12),
          ),
        ],
      ),
    );
  }

  Widget _section(String title) {
    return Padding(
      padding: const EdgeInsets.only(top: 8, bottom: 8),
      child: Text(title,
          style: const TextStyle(
              fontWeight: FontWeight.w800, color: AccnomosColors.ink)),
    );
  }

  Widget _row(Map<String, dynamic> row) {
    final number = (row['number'] ?? '').toString();
    final customer = row['customer'] is Map
        ? ((row['customer'] as Map)['name'] ?? '').toString()
        : '';
    final total = row['total_pence'] is num
        ? (row['total_pence'] as num).toInt()
        : 0;
    final due = (row['due_date'] ?? '').toString();
    final status = (row['status'] ?? '').toString();
    final days = row['days_overdue'];
    final overdueDays = days is num ? days.toInt() : null;
    final overdue = overdueDays != null && overdueDays > 0;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(number,
                    style: const TextStyle(fontWeight: FontWeight.w800)),
                if (customer.isNotEmpty)
                  Text(customer,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                          color: AccnomosColors.muted, fontSize: 12)),
                const SizedBox(height: 2),
                Text(
                  overdue
                      ? '$overdueDays days overdue · due ${_ukDate(due)}'
                      : status == 'sent'
                          ? 'Due ${_ukDate(due)}'
                          : '${_capitalise(status)} · ${_ukDate(due)}',
                  style: TextStyle(
                      fontSize: 12,
                      color: overdue
                          ? const Color(0xFF8A3F06)
                          : AccnomosColors.muted),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Text(formatPence(total),
              style: const TextStyle(
                  fontWeight: FontWeight.w800,
                  color: AccnomosColors.ink,
                  fontSize: 16)),
        ],
      ),
    );
  }

  static String _capitalise(String text) =>
      text.isEmpty ? text : text[0].toUpperCase() + text.substring(1);

  static String _ukDate(String iso) {
    final text = iso.trim();
    if (text.isEmpty) return '—';
    try {
      final d = DateTime.parse(text);
      const months = [
        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
      ];
      return '${d.day} ${months[d.month - 1]} ${d.year}';
    } catch (_) {
      return text;
    }
  }
}
