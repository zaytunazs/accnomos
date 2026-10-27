import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../services/auth.dart';
import '../services/proposal_editing.dart' show formatPence;
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import 'settings_screen.dart';

/// Bank, read-only except for confirming a match the runtime is sure
/// about: statements plus the unmatched lines. A "Confirm match" button
/// appears only where the runtime returns exactly one suggestion for the
/// line (`POST /books/bank/lines/{id}/match`); anything ambiguous is
/// matched from the web app.
class BankScreen extends StatefulWidget {
  const BankScreen({super.key});

  @override
  State<BankScreen> createState() => _BankScreenState();
}

class _BankScreenState extends State<BankScreen> {
  final AuthService _auth = AuthService();
  AppSettings? _settings;
  Account? _account;
  bool _authChecked = false;
  bool _loading = false;
  bool _confirming = false;
  String? _error;
  String? _notice;
  List<Map<String, dynamic>> _statements = const [];
  List<Map<String, dynamic>> _unmatched = const [];
  List<Map<String, dynamic>> _suggestions = const [];

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
      final results = await Future.wait([
        client.bankStatements(),
        client.bankLines(status: 'unmatched'),
        client.bankSuggestions(),
      ]);
      if (!mounted) return;
      setState(() {
        _statements = results[0].cast<Map<String, dynamic>>();
        _unmatched = results[1].cast<Map<String, dynamic>>();
        _suggestions = results[2].cast<Map<String, dynamic>>();
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Suggestions the runtime returned for [lineId].
  List<Map<String, dynamic>> _forLine(String lineId) => _suggestions
      .where((s) => (s['line_id'] ?? '').toString() == lineId)
      .toList();

  Future<void> _confirm(
      String lineId, List<Map<String, dynamic>> matches) async {
    if (_confirming || matches.length != 1) return;
    final suggestion = matches.single;
    final eventIds = <String>[
      for (final id in (suggestion['event_ids'] as List? ?? const []))
        id.toString(),
    ];
    if (eventIds.isEmpty) return;
    setState(() {
      _confirming = true;
      _notice = null;
    });
    try {
      await (await _booksClient()).bankMatch(lineId, eventIds);
      if (!mounted) return;
      setState(() => _notice = 'Match confirmed.');
      await _reload(quiet: true);
    } catch (e) {
      if (!mounted) return;
      setState(() => _notice = _friendly(e));
    } finally {
      if (mounted) setState(() => _confirming = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title:
            Text('Bank', style: Theme.of(context).textTheme.headlineSmall),
        actions: [
          if (_account != null)
            IconButton(
              icon: _loading
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.refresh_outlined),
              tooltip: 'Reload bank',
              constraints:
                  const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _loading ? null : () => _reload(quiet: true),
            ),
        ],
      ),
      body: !_authChecked || (_loading && _error == null && _statements.isEmpty && _unmatched.isEmpty)
          ? const Center(child: CircularProgressIndicator())
          : _account == null
              ? _signedOut(context)
              : _error != null && _statements.isEmpty && _unmatched.isEmpty
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
              'Sign in with Microsoft to see your bank statements.',
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
            Text(_error ?? 'Could not load the bank.',
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
          if (_notice != null) _noticeBox(),
          _heading('Statements'),
          if (_statements.isEmpty)
            const _EmptyLine('No statements imported yet.')
          else
            for (final s in _statements) _statementCard(s),
          const SizedBox(height: 8),
          _heading('Need an action'),
          if (_unmatched.isEmpty)
            const _EmptyLine('Nothing unmatched — every line is resolved.')
          else
            for (final line in _unmatched) _lineCard(line),
          const SizedBox(height: 12),
          const Text(
            'Read-only on the phone, except for confirming a single suggested match — everything else happens in the web app.',
            textAlign: TextAlign.center,
            style: TextStyle(color: AccnomosColors.muted, fontSize: 12),
          ),
        ],
      ),
    );
  }

  Widget _noticeBox() {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AccnomosColors.tealTint,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(_notice!,
          style: const TextStyle(
              color: AccnomosColors.tealDark, height: 1.4)),
    );
  }

  Widget _heading(String title) {
    return Padding(
      padding: const EdgeInsets.only(top: 8, bottom: 8),
      child: Text(title,
          style: const TextStyle(
              fontWeight: FontWeight.w800, color: AccnomosColors.ink)),
    );
  }

  Widget _statementCard(Map<String, dynamic> s) {
    final bank = (s['bank'] ?? '').toString();
    final first = _ukDate((s['first_date'] ?? '').toString());
    final last = _ukDate((s['last_date'] ?? '').toString());
    final lines = _asInt(s['lines']);
    final resolved = _asInt(s['resolved']);
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(bank.isEmpty ? 'Statement' : bank,
              style: const TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 2),
          Text('$first – $last · $resolved of $lines lines resolved',
              style: const TextStyle(
                  color: AccnomosColors.muted, fontSize: 12, height: 1.4)),
          const SizedBox(height: 4),
          Text(
            'In ${formatPence(_asInt(s['money_in_pence']))} · '
            'out ${formatPence(_asInt(s['money_out_pence']))}',
            style: const TextStyle(
                color: AccnomosColors.ink,
                fontSize: 13,
                fontWeight: FontWeight.w700),
          ),
        ],
      ),
    );
  }

  Widget _lineCard(Map<String, dynamic> line) {
    final lineId = (line['id'] ?? '').toString();
    final description = (line['description'] ?? '').toString();
    final date = _ukDate((line['date'] ?? '').toString());
    final amount = _asInt(line['amount_pence']);
    final matches = _forLine(lineId);
    final single = matches.length == 1;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                    description.isEmpty ? 'Bank line' : description,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style:
                        const TextStyle(fontWeight: FontWeight.w700)),
              ),
              const SizedBox(width: 8),
              Text(formatPence(amount),
                  style: const TextStyle(
                      fontWeight: FontWeight.w800,
                      color: AccnomosColors.ink,
                      fontSize: 16)),
            ],
          ),
          Text(date,
              style: const TextStyle(
                  color: AccnomosColors.muted, fontSize: 12)),
          const SizedBox(height: 6),
          if (single)
            _singleMatch(lineId, matches.single)
          else if (matches.isEmpty)
            const Text('No suggested match yet — match it in the web app.',
                style: TextStyle(
                    color: AccnomosColors.muted,
                    fontSize: 12,
                    height: 1.4))
          else
            Text(
                '${matches.length} possible matches — pick one in the web app.',
                style: const TextStyle(
                    color: AccnomosColors.muted,
                    fontSize: 12,
                    height: 1.4)),
        ],
      ),
    );
  }

  Widget _singleMatch(String lineId, Map<String, dynamic> suggestion) {
    final events = suggestion['events'];
    final first = events is List && events.isNotEmpty && events.first is Map
        ? Map<String, dynamic>.from(events.first as Map)
        : <String, dynamic>{};
    final who = (first['counterparty'] ?? '').toString();
    final amount = _asInt(first['amount_pence']);
    final date = _ukDate((first['date'] ?? '').toString());
    final label = who.isEmpty
        ? '${formatPence(amount)} on $date'
        : '$who · ${formatPence(amount)} on $date';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Suggested match: $label',
            style: const TextStyle(
                color: AccnomosColors.tealDark,
                fontSize: 12,
                height: 1.4)),
        const SizedBox(height: 8),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton(
            style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(48),
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14)),
            ),
            onPressed: _confirming ? null : () => _confirm(lineId, [suggestion]),
            child: _confirming
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Text('Confirm match'),
          ),
        ),
      ],
    );
  }

  static int _asInt(Object? value) =>
      value is num ? value.toInt() : int.tryParse('$value') ?? 0;

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

class _EmptyLine extends StatelessWidget {
  const _EmptyLine(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Text(text,
          style: const TextStyle(
              color: AccnomosColors.muted, height: 1.4)),
    );
  }
}
