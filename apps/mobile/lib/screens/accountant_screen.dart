import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/accountant.dart';
import '../services/auth.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import 'audit_screen.dart' show AuditClientFactory;

const _months = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];

String _day(DateTime d) => '${d.day} ${_months[d.month - 1]} ${d.year}';

/// Your accountant, read-only: who your books are shared with and the
/// queries between you. Inviting, removing access, the Accnomos
/// accountants opt-in and answering queries are on the web
/// (Settings › Your accountant).
class AccountantScreen extends StatefulWidget {
  const AccountantScreen({
    super.key,
    @visibleForTesting this.testAccount,
    @visibleForTesting this.testAccountReady = false,
    this.clientFactory,
  });

  @visibleForTesting
  final Account? testAccount;

  @visibleForTesting
  final bool testAccountReady;

  /// Builds the runtime client; null means the real [RuntimeClient].
  final AuditClientFactory? clientFactory;

  @override
  State<AccountantScreen> createState() => _AccountantScreenState();
}

class _AccountantScreenState extends State<AccountantScreen> {
  final AuthService _auth = AuthService();
  Account? _account;
  bool _checked = false;
  bool _loading = false;
  String? _error;
  List<AccountantAccess> _access = const [];
  List<ClientQuery> _queries = const [];
  bool _showResolved = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<RuntimeClient> _client(AppSettings settings) async {
    final factory = widget.clientFactory;
    if (factory != null) {
      return factory(
        settings,
        BooksAuth(
          graphToken: 'test-token',
          accountKind: 'personal',
          user: _account?.username,
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
    if (!mounted) return;
    setState(() {
      _account = account;
      _checked = true;
    });
    if (account == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final client = await _client(settings);
      final results = await Future.wait([
        client.accountant(),
        client.queries(),
      ]);
      final access = AccountantAccess.activeFrom(
        results[0] as Map<String, dynamic>,
      );
      final queries = [
        for (final q in results[1] as List<Map<String, dynamic>>)
          if (ClientQuery.fromJson(q) case final ClientQuery parsed) parsed,
      ];
      if (!mounted) return;
      setState(() {
        _access = access;
        _queries = queries;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
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
          'Your accountant',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        actions: [
          if (_account != null)
            IconButton(
              icon: const Icon(Icons.refresh_outlined),
              tooltip: 'Reload',
              constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _loading ? null : _load,
            ),
        ],
      ),
      body:
          !_checked ||
              (_loading &&
                  _error == null &&
                  _access.isEmpty &&
                  _queries.isEmpty)
          ? const Center(child: CircularProgressIndicator())
          : _account == null
          ? const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text(
                  'Sign in with Microsoft to see who your books are shared with.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: AccnomosColors.muted),
                ),
              ),
            )
          : _body(),
    );
  }

  Widget _body() {
    final open = _queries.where((q) => q.open).toList();
    final resolved = _queries.where((q) => !q.open).toList();
    final waiting = open.where((q) => q.waitingOnYou).length;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
        children: [
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                _error!,
                style: const TextStyle(color: Color(0xFF8A3F06)),
              ),
            ),
          const Text(
            'Read-only here. To invite or remove an accountant, opt in to Accnomos accountants, '
            'or answer a query, use Settings › Your accountant on the web.',
            style: TextStyle(color: AccnomosColors.muted, height: 1.4),
          ),
          const SizedBox(height: 12),
          Text(
            'Who can see your books',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 6),
          if (_access.isEmpty)
            const Text(
              'Nobody: your books are not shared.',
              style: TextStyle(color: AccnomosColors.muted),
            )
          else
            for (final a in _access)
              Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: ListTile(
                  leading: Icon(
                    a.team
                        ? Icons.verified_user_outlined
                        : Icons.person_outline,
                    color: AccnomosColors.tealDark,
                  ),
                  title: Text(
                    a.team ? 'Accnomos accountants' : a.who,
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  subtitle: Text(
                    [
                      a.access,
                      if (a.since != null) 'since ${_day(a.since!)}',
                      if (a.manual) 'shared by you in OneDrive',
                    ].join(' · '),
                  ),
                ),
              ),
          const SizedBox(height: 12),
          Text(
            waiting > 0 ? 'Queries · $waiting waiting on you' : 'Queries',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 6),
          if (open.isEmpty)
            const Text(
              'No open queries.',
              style: TextStyle(color: AccnomosColors.muted),
            ),
          for (final q in open) _QueryCard(query: q),
          if (resolved.isNotEmpty)
            TextButton(
              onPressed: () => setState(() => _showResolved = !_showResolved),
              child: Text(
                _showResolved
                    ? 'Hide resolved'
                    : 'Show resolved (${resolved.length})',
              ),
            ),
          if (_showResolved)
            for (final q in resolved) _QueryCard(query: q),
        ],
      ),
    );
  }
}

class _QueryCard extends StatelessWidget {
  const _QueryCard({required this.query});

  final ClientQuery query;

  @override
  Widget build(BuildContext context) {
    final badge = !query.open
        ? 'Resolved'
        : query.waitingOnYou
        ? 'Waiting on you'
        : 'Waiting on your accountant';
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              query.about,
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 2),
            Text(
              badge,
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: query.waitingOnYou
                    ? const Color(0xFF8A3F06)
                    : AccnomosColors.muted,
              ),
            ),
            for (final m in query.messages) ...[
              const SizedBox(height: 8),
              Text(
                '${m.fromAccountant ? 'Accountant (${m.author})' : 'You'}'
                '${m.at != null ? ' · ${_day(m.at!)}' : ''}',
                style: const TextStyle(
                  fontSize: 12,
                  color: AccnomosColors.muted,
                ),
              ),
              Text(m.text),
            ],
          ],
        ),
      ),
    );
  }
}
