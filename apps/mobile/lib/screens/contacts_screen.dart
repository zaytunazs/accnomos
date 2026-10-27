import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../services/auth.dart';
import '../services/books.dart';
import '../services/settings.dart';
import '../theme.dart';
import 'settings_screen.dart';

/// Contacts from `GET /contacts`: search the list, see each open balance,
/// and open a statement per contact. Money is worked out by the runtime.
class ContactsScreen extends StatefulWidget {
  const ContactsScreen({super.key});

  @override
  State<ContactsScreen> createState() => _ContactsScreenState();
}

class _ContactsScreenState extends State<ContactsScreen> {
  final AuthService _auth = AuthService();
  final _search = TextEditingController();
  AppSettings? _settings;
  Account? _account;
  bool _authChecked = false;
  bool _loading = false;
  String? _error;
  List<Map<String, dynamic>> _rows = const [];
  String _query = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

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

  Future<void> _reload() async {
    final settings = _settings;
    if (settings == null || _account == null || _loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final client = await booksClient(settings, _auth, _account);
      final decoded = await client.contacts();
      final contacts = decoded['contacts'];
      if (!mounted) return;
      setState(() {
        _rows = [
          if (contacts is List)
            for (final c in contacts)
              if (c is Map) Map<String, dynamic>.from(c),
        ];
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  List<Map<String, dynamic>> get _filtered {
    final q = _query.trim().toLowerCase();
    if (q.isEmpty) return _rows;
    return _rows.where((c) {
      final name = (c['name'] ?? '').toString().toLowerCase();
      final email = (c['email'] ?? '').toString().toLowerCase();
      return name.contains(q) || email.contains(q);
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          'Contacts',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        actions: [
          if (_account != null)
            IconButton(
              icon: const Icon(Icons.refresh_outlined),
              tooltip: 'Reload contacts',
              constraints:
                  const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _loading ? null : _reload,
            ),
        ],
      ),
      body: !_authChecked || _loading && _rows.isEmpty && _error == null
          ? const Center(child: CircularProgressIndicator())
          : _account == null
              ? _signedOut()
              : _error != null && _rows.isEmpty
                  ? _errorView()
                  : _listView(),
    );
  }

  Widget _signedOut() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'Sign in to see your contacts.',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 12),
            FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: AccnomosColors.teal,
                minimumSize: const Size.fromHeight(48),
              ),
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(
                    builder: (_) => const SettingsScreen()),
              ).then((_) => _load()),
              child: const Text('Sign in'),
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
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(_error ?? 'Could not load contacts.',
                textAlign: TextAlign.center),
            const SizedBox(height: 12),
            FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: AccnomosColors.teal,
                minimumSize: const Size.fromHeight(48),
              ),
              onPressed: _reload,
              child: const Text('Try again'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _listView() {
    final rows = _filtered;
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
          child: TextField(
            controller: _search,
            decoration: const InputDecoration(
              hintText: 'Search name or email',
              prefixIcon: Icon(Icons.search_outlined),
              border: OutlineInputBorder(),
              filled: true,
              fillColor: Colors.white,
            ),
            onChanged: (value) => setState(() => _query = value),
          ),
        ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Text(_error!,
                style: const TextStyle(color: AccnomosColors.muted)),
          ),
        Expanded(
          child: rows.isEmpty
              ? const Center(child: Text('No contacts found.'))
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                  itemCount: rows.length,
                  separatorBuilder: (_, _) =>
                      const SizedBox(height: 8),
                  itemBuilder: (context, i) =>
                      _row(context, rows[i]),
                ),
        ),
      ],
    );
  }

  Widget _row(BuildContext context, Map<String, dynamic> contact) {
    final totals = contact['totals'];
    final balance = totals is Map
        ? ((totals['balance_pence'] ?? 0) as num)
        : 0;
    return Card(
      margin: EdgeInsets.zero,
      child: ListTile(
        minVerticalPadding: 10,
        title: Text(
          (contact['name'] ?? 'Unnamed').toString(),
          style: const TextStyle(fontWeight: FontWeight.w700),
        ),
        subtitle: Text(_kindLabel(contact),
            style:
                const TextStyle(color: AccnomosColors.muted)),
        trailing: Text(
          _balanceLabel(balance),
          style: TextStyle(
            fontWeight: FontWeight.w800,
            color: balance > 0
                ? AccnomosColors.tealDark
                : balance < 0
                    ? const Color(0xFF8A3F06)
                    : AccnomosColors.muted,
          ),
        ),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => ContactDetailScreen(
              contactId: (contact['id'] ?? '').toString(),
              name: (contact['name'] ?? 'Contact').toString(),
              settings: _settings!,
              auth: _auth,
              account: _account,
            ),
          ),
        ),
      ),
    );
  }

  static String _kindLabel(Map<String, dynamic> contact) {
    switch ((contact['kind'] ?? '').toString()) {
      case 'customer':
        return 'Customer';
      case 'supplier':
        return 'Supplier';
      case 'both':
        return 'Customer · Supplier';
      default:
        return 'Contact';
    }
  }

  /// Signed from your side: + they owe you, − you owe them.
  static String _balanceLabel(num pence) {
    if (pence > 0) return '${gbp(pence)} owed';
    if (pence < 0) return 'owe ${gbp(-pence)}';
    return 'Settled';
  }
}

/// One contact's statement from `GET /contacts/{id}/statement`.
class ContactDetailScreen extends StatefulWidget {
  const ContactDetailScreen({
    super.key,
    required this.contactId,
    required this.name,
    required this.settings,
    required this.auth,
    required this.account,
  });

  final String contactId;
  final String name;
  final AppSettings settings;
  final AuthService auth;
  final Account? account;

  @override
  State<ContactDetailScreen> createState() => _ContactDetailState();
}

class _ContactDetailState extends State<ContactDetailScreen> {
  bool _loading = true;
  String? _error;
  Map<String, dynamic>? _statement;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final client =
          await booksClient(widget.settings, widget.auth, widget.account);
      final decoded =
          await client.contactStatement(widget.contactId);
      if (!mounted) return;
      setState(() => _statement = decoded);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = friendly(e));
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
        title: Text(
          widget.name,
          style: Theme.of(context).textTheme.titleMedium,
        ),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(_error!,
                            textAlign: TextAlign.center),
                        const SizedBox(height: 12),
                        FilledButton(
                          style: FilledButton.styleFrom(
                            backgroundColor: AccnomosColors.teal,
                            minimumSize:
                                const Size.fromHeight(48),
                          ),
                          onPressed: _reload,
                          child: const Text('Try again'),
                        ),
                      ],
                    ),
                  ),
                )
              : _statementView(),
    );
  }

  Widget _statementView() {
    final statement = _statement ?? const {};
    final lines = statement['lines'];
    final rows = [
      if (lines is List)
        for (final l in lines)
          if (l is Map) Map<String, dynamic>.from(l),
    ];
    final opening =
        (statement['opening_balance_pence'] ?? 0) as num;
    final closing =
        (statement['closing_balance_pence'] ?? 0) as num;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(16),
            border:
                Border.all(color: const Color(0xFFE3E1D8)),
          ),
          child: Column(
            children: [
              _balanceRow('Opening', opening),
              const SizedBox(height: 6),
              _balanceRow('Balance now', closing,
                  bold: true),
            ],
          ),
        ),
        const SizedBox(height: 12),
        if (rows.isEmpty)
          const Text(
            'No statement lines yet.',
            style: TextStyle(color: AccnomosColors.muted),
          )
        else
          for (final line in rows) _lineCard(line),
      ],
    );
  }

  Widget _balanceRow(String label, num pence, {bool bold = false}) {
    final style = TextStyle(
      fontWeight: bold ? FontWeight.w800 : FontWeight.w600,
      fontSize: bold ? 16 : 14,
    );
    return Row(
      children: [
        Expanded(child: Text(label, style: style)),
        Text(gbp(pence), style: style),
      ],
    );
  }

  Widget _lineCard(Map<String, dynamic> line) {
    final amount = (line['amount_pence'] ?? 0) as num;
    final balance = (line['balance_pence'] ?? 0) as num;
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        minVerticalPadding: 10,
        title: Text(
          (line['details'] ?? '—').toString(),
          style: const TextStyle(fontWeight: FontWeight.w700),
        ),
        subtitle: Text(
          '${ukDate((line['date'] ?? '').toString())}'
          '${(line['reference'] ?? '').toString().isNotEmpty ? ' · ${(line['reference'] ?? '').toString()}' : ''}',
          style: const TextStyle(color: AccnomosColors.muted),
        ),
        trailing: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text(gbp(amount),
                style: const TextStyle(
                    fontWeight: FontWeight.w800)),
            Text(gbp(balance),
                style: const TextStyle(
                    color: AccnomosColors.muted,
                    fontSize: 12)),
          ],
        ),
      ),
    );
  }
}
