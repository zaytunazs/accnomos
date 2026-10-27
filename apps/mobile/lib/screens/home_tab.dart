import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/vat_return.dart';
import '../services/auth.dart';
import '../services/home_todos.dart';
import '../services/proposal_editing.dart' show formatPence;
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import 'bank_screen.dart';
import 'invoices_screen.dart';
import 'review_screen.dart';
import 'settings_screen.dart';
import 'vat_screen.dart';

/// Home tab: labelled sample tiles when signed out, live "Today" numbers
/// when signed in.
///
/// Signed in, the tiles read the same responses the task lists — Review
/// waiting (`GET /books/proposals?status=proposed` plus the `needs_a_look`
/// count), unpaid and overdue sales invoices (`GET /invoices`), bank lines
/// needing an action (`GET /books/bank/summary`), the next VAT deadline
/// (`GET /books/deadlines` with the saved stagger), and this quarter's VAT
/// so far (`GET /books/vat`: `/books/summary` carries no VAT figures, so
/// the tile reads the return the VAT screen already shows). Every tile
/// taps through to its screen. Each tile fails on its own; there is never
/// a full-screen failure. The to-do list below is built by code from those
/// same responses — no model call.
class HomeTab extends StatefulWidget {
  const HomeTab({super.key});

  @override
  State<HomeTab> createState() => _HomeTabState();
}

class _HomeTabState extends State<HomeTab> {
  final AuthService _auth = AuthService();

  AppSettings? _settings;
  Account? _account;
  bool _authChecked = false;
  bool _loading = false;

  int? _proposed;
  int? _needsALook;
  String? _reviewError;

  int? _unpaidCount;
  int? _overdueCount;
  int? _unpaidPence;
  List<OverdueInvoice> _overdue = const [];
  String? _invoicesError;

  int? _bankAction;
  String? _bankNote;
  String? _bankError;

  String? _deadlineIso;
  String? _deadlineLabel;
  int? _deadlineDays;
  String? _deadlinesError;

  String? _vatBox5;
  String? _vatPeriod;
  String? _vatError;

  @override
  void initState() {
    super.initState();
    _load();
  }

  bool get _signedIn => _account != null;

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
    Account? account = _account;
    try {
      account = await _auth.account() ?? account;
    } on MsalException {
      // Keep the account we already knew about.
    }
    if (mounted && account?.username != _account?.username) {
      setState(() => _account = account);
    }
    final user = account?.username ?? settings.userEmail;
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

  /// Pull-to-refresh entry point: reloads every tile when signed in.
  Future<void> _refresh() => _reload(quiet: true);

  /// Reload every tile. Each loader catches its own failure into its
  /// tile's error slot, so one bad call never takes the screen down.
  Future<void> _reload({bool quiet = false}) async {
    if (!_signedIn || _loading) return;
    if (!quiet) setState(() => _loading = true);
    try {
      final client = await _booksClient();
      await Future.wait([
        _loadReview(client),
        _loadInvoices(client),
        _loadBank(client),
        _loadDeadlines(client),
        _loadVat(client),
      ]);
    } catch (e) {
      // Loaders never throw; this is only the client setup failing.
      if (!mounted) return;
      setState(() {
        _reviewError ??= _friendly(e);
        _invoicesError ??= _friendly(e);
        _bankError ??= _friendly(e);
        _deadlinesError ??= _friendly(e);
        _vatError ??= _friendly(e);
      });
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadReview(RuntimeClient client) async {
    try {
      final results = await Future.wait([
        client.proposals(status: 'proposed'),
        client.proposals(status: 'needs_a_look'),
      ]);
      if (!mounted) return;
      setState(() {
        _proposed = results[0].length;
        _needsALook = results[1].length;
        _reviewError = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _reviewError = _friendly(e));
    }
  }

  Future<void> _loadInvoices(RuntimeClient client) async {
    try {
      final rows = await client.invoices();
      var unpaid = 0;
      var overdue = 0;
      var pence = 0;
      final overdueRows = <OverdueInvoice>[];
      for (final row in rows) {
        if ((row['status'] ?? '').toString() != 'sent') continue;
        unpaid++;
        pence += _asInt(row['total_pence']);
        final days = row['days_overdue'];
        if (days is num && days > 0) {
          overdue++;
          overdueRows.add(OverdueInvoice(
            number: (row['number'] ?? '').toString(),
            daysOverdue: days.toInt(),
            totalPence: _asInt(row['total_pence']),
          ));
        }
      }
      overdueRows.sort((a, b) => b.daysOverdue.compareTo(a.daysOverdue));
      if (!mounted) return;
      setState(() {
        _unpaidCount = unpaid;
        _overdueCount = overdue;
        _unpaidPence = pence;
        _overdue = overdueRows.length > 5
            ? overdueRows.sublist(0, 5)
            : overdueRows;
        _invoicesError = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _invoicesError = _friendly(e));
    }
  }

  Future<void> _loadBank(RuntimeClient client) async {
    try {
      final summary = await client.bankSummary();
      final unmatched = _asInt(summary['unmatched']);
      final suggested = _asInt(summary['suggested']);
      if (!mounted) return;
      setState(() {
        _bankAction = unmatched + suggested;
        _bankNote = '$unmatched unmatched · $suggested suggested';
        _bankError = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _bankError = _friendly(e));
    }
  }

  Future<void> _loadDeadlines(RuntimeClient client) async {
    try {
      final settings = _settings!;
      final data = await client.deadlines(
        stagger: settings.vatStartMonth == null ? settings.vatStagger : null,
        startMonth: settings.vatStartMonth,
      );
      final next = (data['due'] is Map ? data['due'] : data['current'])
          as Map<String, dynamic>?;
      if (!mounted) return;
      setState(() {
        _deadlineIso = next?['deadline']?.toString();
        _deadlineLabel = next?['label']?.toString();
        final days = next?['days_remaining'];
        _deadlineDays = days is num ? days.toInt() : null;
        _deadlinesError =
            next == null ? 'No deadline in the response.' : null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _deadlinesError = _friendly(e));
    }
  }

  Future<void> _loadVat(RuntimeClient client) async {
    try {
      final vat = VatReturn.fromJson(await client.vat());
      VatBox? box5;
      for (final box in vat.boxes) {
        if (box.box == 5) box5 = box;
      }
      if (!mounted) return;
      setState(() {
        _vatBox5 = box5?.amount;
        _vatPeriod = vat.periodKey.isEmpty ? null : vat.periodKey;
        _vatError = box5 == null ? 'No Box 5 in the return.' : null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _vatError = _friendly(e));
    }
  }

  static int _asInt(Object? value) =>
      value is num ? value.toInt() : int.tryParse('$value') ?? 0;

  void _open(Widget screen) {
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => screen));
  }

  @override
  Widget build(BuildContext context) {
    if (!_authChecked || (_loading && !_signedIn)) {
      return const Center(child: CircularProgressIndicator());
    }
    if (!_signedIn) return _signedOut(context);
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _todayCard(context),
          const SizedBox(height: 20),
          _todoSection(context),
        ],
      ),
    );
  }

  Widget _signedOut(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text('Your books. Your cloud. Meta AI on your terms.',
            style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 6),
        const Text(
          'Accnomos keeps your bookkeeping in a folder you own (OneDrive first), '
          'reads receipts and invoices with Meta AI, and files VAT returns to HMRC '
          'only when you say so.',
          style: TextStyle(color: AccnomosColors.muted, height: 1.4),
        ),
        const SizedBox(height: 20),
        GridView.count(
          crossAxisCount: 2,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 12,
          crossAxisSpacing: 12,
          childAspectRatio: 1.2,
          children: const [
            _SampleTile(
                label: 'Cash in bank', value: '—', note: 'Connect to see'),
            _SampleTile(
                label: 'Owed to you', value: '—', note: 'Connect to see'),
            _SampleTile(
                label: 'VAT estimate',
                value: '—',
                note: 'Calculated by code'),
            _SampleTile(
                label: 'Needs a look', value: '0', note: 'Nothing waiting'),
          ],
        ),
        const SizedBox(height: 20),
        FilledButton(
          style: FilledButton.styleFrom(
              backgroundColor: AccnomosColors.teal,
              minimumSize: const Size.fromHeight(52),
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14))),
          onPressed: () => Navigator.of(context).push(
            MaterialPageRoute(builder: (_) => const SettingsScreen()),
          ),
          child: const Text('Connect your cloud',
              style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
        ),
        const SizedBox(height: 10),
        const Text(
          'Accnomos never stores your data on its own servers.',
          textAlign: TextAlign.center,
          style: TextStyle(color: AccnomosColors.muted, fontSize: 12),
        ),
      ],
    );
  }

  Widget _todayCard(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Today · ${_ukToday()}',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 12),
          GridView.count(
            crossAxisCount: 2,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            mainAxisSpacing: 12,
            crossAxisSpacing: 12,
            childAspectRatio: 1.3,
            children: [
              _liveTile(
                label: 'Needs a look',
                value: _proposed == null || _needsALook == null
                    ? '…'
                    : '${_proposed! + _needsALook!} waiting',
                note: _proposed == null || _needsALook == null
                    ? 'Review queue'
                    : '$_proposed proposed · $_needsALook need a look',
                error: _reviewError,
                onTap: () => _open(const ReviewScreen()),
              ),
              _liveTile(
                label: 'Owed to you',
                value: _unpaidPence == null
                    ? '…'
                    : formatPence(_unpaidPence!),
                note: _unpaidCount == null
                    ? 'Sales invoices'
                    : _unpaidCount == 0
                        ? 'Nothing unpaid'
                        : '$_unpaidCount unpaid · $_overdueCount overdue',
                error: _invoicesError,
                onTap: () => _open(const InvoicesScreen()),
              ),
              _liveTile(
                label: 'Bank to match',
                value: _bankAction == null
                    ? '…'
                    : _bankAction == 0
                        ? 'Up to date'
                        : '$_bankAction to match',
                note: _bankNote ?? 'Bank lines',
                error: _bankError,
                onTap: () => _open(const BankScreen()),
              ),
              _liveTile(
                label: 'VAT so far',
                value: _vatBox5 == null ? '…' : '£$_vatBox5',
                note: _vatPeriod == null
                    ? 'This quarter'
                    : 'Box 5 · $_vatPeriod',
                error: _vatError,
                onTap: () => _open(const VatScreen()),
              ),
              _liveTile(
                label: 'VAT deadline',
                value: _deadlineIso == null ? '…' : _ukShort(_deadlineIso!),
                note: _deadlineDays == null
                    ? 'Next return'
                    : _deadlineDays! < 0
                        ? 'Overdue by ${-_deadlineDays!} days'
                        : _deadlineDays == 0
                            ? 'Due today'
                            : 'Due in $_deadlineDays days',
                error: _deadlinesError,
                onTap: () => _open(const VatScreen()),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _todoSection(BuildContext context) {
    final todos = buildHomeTodos(
      proposed: _proposed ?? 0,
      needsALook: _needsALook ?? 0,
      overdue: _invoicesError == null ? _overdue : const [],
      bankActionCount: _bankError == null ? (_bankAction ?? 0) : 0,
      deadlineLabel: _deadlineLabel,
      deadlineIso: _deadlinesError == null ? _deadlineIso : null,
      deadlineDaysRemaining:
          _deadlinesError == null ? _deadlineDays : null,
    );
    final loaded = _proposed != null &&
        _unpaidCount != null &&
        _bankAction != null &&
        (_deadlineIso != null || _deadlinesError != null) &&
        (_vatBox5 != null || _vatError != null);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('To do', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        if (todos.isEmpty)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: const Color(0xFFE3E1D8)),
            ),
            child: Text(
              loaded
                  ? 'Nothing needs you — enjoy the day.'
                  : 'Working out what needs you…',
              style: const TextStyle(
                  color: AccnomosColors.muted, height: 1.4),
            ),
          )
        else
          for (final todo in todos)
            Container(
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
                  title: Text(todo.title,
                      style:
                          const TextStyle(fontWeight: FontWeight.w700)),
                  subtitle: Text(todo.detail),
                  trailing:
                      const Icon(Icons.chevron_right_outlined),
                  onTap: () => _open(_screenFor(todo.target)),
                ),
              ),
            ),
      ],
    );
  }

  Widget _screenFor(HomeTodoTarget target) {
    switch (target) {
      case HomeTodoTarget.review:
        return const ReviewScreen();
      case HomeTodoTarget.invoices:
        return const InvoicesScreen();
      case HomeTodoTarget.bank:
        return const BankScreen();
      case HomeTodoTarget.vat:
        return const VatScreen();
    }
  }

  /// One tappable tile: the value and note, or the tile's own error with
  /// a "pull to refresh" hint. Never blank, never full-screen.
  Widget _liveTile({
    required String label,
    required String value,
    required String note,
    required String? error,
    required VoidCallback onTap,
  }) {
    final failed = error != null;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(14),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: failed ? const Color(0xFFFFF7ED) : AccnomosColors.ground,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(
              color: failed
                  ? const Color(0xFFF3C892)
                  : const Color(0xFFE3E1D8)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label.toUpperCase(),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    color: AccnomosColors.muted,
                    letterSpacing: 0.6)),
            const Spacer(),
            if (failed)
              Text('Could not load',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w800,
                      color: Color(0xFF8A3F06)))
            else
              Text(value,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      fontSize: 19,
                      fontWeight: FontWeight.w800,
                      color: AccnomosColors.ink)),
            Text(failed ? 'Pull to refresh' : note,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                    fontSize: 12,
                    color: failed
                        ? const Color(0xFF8A3F06)
                        : AccnomosColors.muted)),
          ],
        ),
      ),
    );
  }

  static String _ukToday() {
    final now = DateTime.now();
    const months = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
    ];
    return '${now.day} ${months[now.month - 1]} ${now.year}';
  }

  /// `2027-02-07` → `7 Feb`; falls back to the raw text.
  static String _ukShort(String iso) {
    try {
      final d = DateTime.parse(iso.trim());
      const months = [
        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
      ];
      return '${d.day} ${months[d.month - 1]}';
    } catch (_) {
      return iso;
    }
  }
}

class _SampleTile extends StatelessWidget {
  const _SampleTile(
      {required this.label, required this.value, required this.note});
  final String label;
  final String value;
  final String note;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label.toUpperCase(),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: AccnomosColors.muted,
                  letterSpacing: 0.6)),
          const Spacer(),
          Text(value,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                  fontSize: 26,
                  fontWeight: FontWeight.w800,
                  color: AccnomosColors.ink)),
          Text(note,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                  fontSize: 12, color: AccnomosColors.muted)),
        ],
      ),
    );
  }
}
