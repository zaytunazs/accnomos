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

/// Your accountant, as on the web's Settings › Your accountant: who your
/// books are shared with, invite an accountant (Microsoft shares the folder,
/// or you share it yourself and it is recorded), remove access, and answer
/// or resolve their queries. The Accnomos accountants opt-in stays on the web
/// (it needs the consent text shown in full).
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
  AppSettings? _settings;
  bool _busy = false;

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

  Future<RuntimeClient> _clientNow() async =>
      _client(_settings ?? await AppSettings.load());

  /// Runs one change, then reloads; the runtime's sentence on failure.
  Future<void> _act(Future<void> Function(RuntimeClient c) work, String done) async {
    if (_busy) return;
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await work(await _clientNow());
      messenger.showSnackBar(SnackBar(duration: const Duration(seconds: 4), content: Text(done)));
      await _load();
    } catch (e) {
      messenger.showSnackBar(SnackBar(
          duration: const Duration(seconds: 6),
          content: Text(e.toString().replaceFirst('Exception: ', ''))));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _invite() async {
    final result = await showModalBottomSheet<Map<String, String>>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const _InviteSheet(),
    );
    if (result == null) return;
    await _act(
      (c) => c.inviteAccountant(
        email: result['email']!,
        name: result['name']!,
        role: result['role']!,
        method: result['method']!,
        message: result['message'] ?? '',
      ),
      result['method'] == 'graph'
          ? 'Invited: your books folder is shared with ${result['email']}.'
          : 'Recorded: share your books folder with ${result['email']} in OneDrive.',
    );
  }

  Future<void> _revoke(AccountantAccess a) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Remove access?'),
        content: Text(a.manual
            ? 'This removes ${a.who} from the list. You shared the folder yourself, so also stop sharing it in OneDrive.'
            : '${a.who} will no longer see your books folder.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Remove access')),
        ],
      ),
    );
    if (ok != true) return;
    await _act((c) => c.revokeAccountant(a.id), 'Access removed for ${a.who}.');
  }

  Future<void> _load() async {
    final settings = await AppSettings.load();
    _settings = settings;
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
        title: Text(
          'Your accountant',
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
          const SizedBox(height: 4),
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
                  trailing: a.team || a.id.isEmpty
                      ? null
                      : TextButton(
                          onPressed: _busy ? null : () => _revoke(a),
                          child: const Text('Remove'),
                        ),
                ),
              ),
          const SizedBox(height: 4),
          OutlinedButton.icon(
            icon: const Icon(Icons.person_add_alt_outlined),
            label: const Text('Invite an accountant'),
            onPressed: _busy ? null : _invite,
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
          for (final q in open)
            _QueryCard(
              query: q,
              busy: _busy,
              onReply: (text) => _act((c) => c.replyQuery(q.id, text), 'Answer sent.'),
              onResolve: () => _act((c) => c.resolveQuery(q.id), 'Marked resolved.'),
            ),
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

/// Invite an accountant: email, name, view or edit, and how the folder is shared.
class _InviteSheet extends StatefulWidget {
  const _InviteSheet();

  @override
  State<_InviteSheet> createState() => _InviteSheetState();
}

class _InviteSheetState extends State<_InviteSheet> {
  final _email = TextEditingController();
  final _name = TextEditingController();
  final _message = TextEditingController();
  String _role = 'read';
  String _method = 'graph';
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _name.dispose();
    _message.dispose();
    super.dispose();
  }

  void _send() {
    final email = _email.text.trim();
    if (!RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(email)) {
      setState(() => _error = 'Enter your accountant’s email address.');
      return;
    }
    Navigator.pop(context, {
      'email': email,
      'name': _name.text.trim(),
      'role': _role,
      'method': _method,
      'message': _message.text.trim(),
    });
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 16, 16, 16 + MediaQuery.of(context).viewInsets.bottom),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Invite an accountant', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 12),
            TextField(
              controller: _email,
              keyboardType: TextInputType.emailAddress,
              decoration: const InputDecoration(labelText: 'Email'),
            ),
            const SizedBox(height: 8),
            TextField(controller: _name, decoration: const InputDecoration(labelText: 'Name (optional)')),
            const SizedBox(height: 12),
            const Text('Access', style: TextStyle(fontWeight: FontWeight.w700)),
            RadioGroup<String>(
              groupValue: _role,
              onChanged: (v) => setState(() => _role = v ?? 'read'),
              child: const Column(children: [
                RadioListTile(value: 'read', title: Text('View only')),
                RadioListTile(value: 'edit', title: Text('View and edit')),
              ]),
            ),
            const Text('Sharing', style: TextStyle(fontWeight: FontWeight.w700)),
            RadioGroup<String>(
              groupValue: _method,
              onChanged: (v) => setState(() => _method = v ?? 'graph'),
              child: const Column(children: [
                RadioListTile(
                    value: 'graph',
                    title: Text('Share my books folder for me'),
                    subtitle: Text('Microsoft emails them the link.')),
                RadioListTile(
                    value: 'manual',
                    title: Text('I’ll share it myself in OneDrive'),
                    subtitle: Text('Accnomos only records who has access.')),
              ]),
            ),
            TextField(
              controller: _message,
              maxLines: 2,
              decoration: const InputDecoration(labelText: 'Message (optional)'),
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(_error!, style: const TextStyle(color: Color(0xFFA12626))),
              ),
            const SizedBox(height: 12),
            FilledButton(onPressed: _send, child: const Text('Invite')),
          ],
        ),
      ),
    );
  }
}

class _QueryCard extends StatefulWidget {
  const _QueryCard({required this.query, this.onReply, this.onResolve, this.busy = false});

  final ClientQuery query;
  final Future<void> Function(String text)? onReply;
  final Future<void> Function()? onResolve;
  final bool busy;

  @override
  State<_QueryCard> createState() => _QueryCardState();
}

class _QueryCardState extends State<_QueryCard> {
  final _reply = TextEditingController();

  @override
  void dispose() {
    _reply.dispose();
    super.dispose();
  }

  ClientQuery get query => widget.query;

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
            if (query.open && widget.onReply != null) ...[
              const SizedBox(height: 10),
              TextField(
                controller: _reply,
                minLines: 1,
                maxLines: 4,
                decoration: const InputDecoration(labelText: 'Your answer'),
              ),
              const SizedBox(height: 8),
              Wrap(spacing: 8, runSpacing: 8, children: [
                FilledButton(
                  onPressed: widget.busy
                      ? null
                      : () async {
                          final t = _reply.text.trim();
                          if (t.isEmpty) return;
                          await widget.onReply!(t);
                          if (mounted) _reply.clear();
                        },
                  child: const Text('Send answer'),
                ),
                if (widget.onResolve != null)
                  OutlinedButton(
                    onPressed: widget.busy ? null : widget.onResolve,
                    child: const Text('Mark resolved'),
                  ),
              ]),
            ],
          ],
        ),
      ),
    );
  }
}
