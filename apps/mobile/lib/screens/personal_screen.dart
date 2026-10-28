import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../services/auth.dart';
import '../services/proposal_editing.dart' show formatPence;
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/web_only.dart';
import 'settings_screen.dart';

/// Builds a [RuntimeClient] for the personal screen. The app builds the
/// real client (with books credentials when signed in); tests inject a
/// fake that answers without touching the network.
typedef PersonalClientFactory = RuntimeClient Function(
    AppSettings settings, BooksAuth? books);

/// Household money, read-only on the phone apart from setting a budget
/// amount for a category: the month's money in, out and left over,
/// budgets with progress bars, recurring bills with next due dates, and
/// savings goals with the monthly amount the runtime works out.
/// Categories, rules and goals themselves are edited on the web.
class PersonalScreen extends StatefulWidget {
  const PersonalScreen({
    super.key,
    @visibleForTesting this.testAccount,
    @visibleForTesting this.testAccountReady = false,
    this.clientFactory,
  });

  /// Signed-in account to use without touching MSAL (tests only).
  @visibleForTesting
  final Account? testAccount;

  /// Skip the MSAL account lookup and use [testAccount] as-is (tests only).
  @visibleForTesting
  final bool testAccountReady;

  /// Builds the runtime client; null means the real [RuntimeClient].
  final PersonalClientFactory? clientFactory;

  @override
  State<PersonalScreen> createState() => _PersonalScreenState();
}

class _PersonalScreenState extends State<PersonalScreen> {
  final AuthService _auth = AuthService();
  AppSettings? _settings;
  Account? _account;
  bool _authChecked = false;
  bool _loading = false;
  String? _error;
  Map<String, dynamic> _summary = const {};
  Map<String, int> _budgets = const {};
  List<Map<String, dynamic>> _bills = const [];
  String _billsNote = '';
  List<Map<String, dynamic>> _goals = const [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  String _friendly(Object e) => e.toString().replaceFirst('Exception: ', '');

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
      _settings = settings;
      _account = account;
      _authChecked = true;
    });
    if (account != null) await _reload();
  }

  Future<RuntimeClient> _booksClient() async {
    final settings = _settings!;
    final factory = widget.clientFactory;
    if (factory != null) {
      return factory(
        settings,
        BooksAuth(
          graphToken: 'test-token',
          accountKind: 'personal',
          user: _account?.username,
          businessName: settings.businessName,
        ),
      );
    }
    final token = await _auth.token();
    Account? account = _account;
    try {
      account = await _auth.account() ?? account;
    } on MsalException {
      // Keep the account we already knew about.
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

  Future<void> _reload({bool quiet = false}) async {
    if (_settings == null || _account == null || _loading) return;
    if (!quiet) setState(() => _loading = true);
    setState(() => _error = null);
    try {
      final client = await _booksClient();
      final results = await Future.wait([
        client.personalSummary(),
        client.personalBudgets(),
        client.personalRecurring(),
        client.personalGoals(),
      ]);
      final summary = results[0] as Map<String, dynamic>;
      final budgetsRaw = results[1] as Map<String, dynamic>;
      final recurring = results[2] as Map<String, dynamic>;
      final goals = results[3] as List<Map<String, dynamic>>;
      final budgets = <String, int>{};
      budgetsRaw.forEach((key, value) {
        if (value is num) budgets[key.toString()] = value.toInt();
      });
      final bills = <Map<String, dynamic>>[];
      if (recurring['items'] is List) {
        for (final item in recurring['items'] as List) {
          if (item is Map) bills.add(Map<String, dynamic>.from(item));
        }
      }
      if (!mounted) return;
      setState(() {
        _summary = summary;
        _budgets = budgets;
        _bills = bills;
        _billsNote = (recurring['note'] ?? '').toString();
        _goals = goals;
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
        title: Text('Personal',
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
              tooltip: 'Reload personal finances',
              constraints:
                  const BoxConstraints(minWidth: 48, minHeight: 48),
              onPressed: _loading ? null : () => _reload(quiet: true),
            ),
        ],
      ),
      body: !_authChecked || (_loading && _error == null && _summary.isEmpty)
          ? const Center(child: CircularProgressIndicator())
          : _account == null
              ? _signedOut(context)
              : _error != null && _summary.isEmpty
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
              'Sign in with Microsoft to see your personal finances.',
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
            Text(_error ?? 'Could not load your personal finances.',
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
          _summaryCard(),
          const SizedBox(height: 16),
          _sectionTitle('Budgets'),
          const SizedBox(height: 8),
          ..._budgetRows(),
          const SizedBox(height: 16),
          _sectionTitle('Recurring bills'),
          const SizedBox(height: 8),
          ..._billRows(),
          const SizedBox(height: 16),
          _sectionTitle('Savings goals'),
          const SizedBox(height: 8),
          ..._goalRows(),
          const WebOnlyCard(
            message:
                'Categories, rules and goals are added and edited on the web — the phone only sets a budget amount.',
            page: '/personal',
          ),
        ],
      ),
    );
  }

  Widget _sectionTitle(String title) {
    return Text(title,
        style: const TextStyle(
            fontWeight: FontWeight.w800,
            fontSize: 16,
            color: AccnomosColors.ink));
  }

  static int _pence(Object? value) => value is num ? value.toInt() : 0;

  /// This month's money in, money out and what is left.
  Widget _summaryCard() {
    final inPence = _pence(_summary['income_pence']);
    final outPence = _pence(_summary['spent_pence']);
    final leftPence = _pence(_summary['left_pence']);
    return Container(
      width: double.infinity,
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
            _monthHeading((_summary['month'] ?? '').toString()),
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 12),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                  child: _moneyCell(
                      'Money in', formatPence(inPence), AccnomosColors.ink)),
              const SizedBox(width: 8),
              Expanded(
                  child: _moneyCell(
                      'Money out', formatPence(outPence), AccnomosColors.ink)),
              const SizedBox(width: 8),
              Expanded(
                  child: _moneyCell('Left over', formatPence(leftPence),
                      AccnomosColors.tealDark)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _moneyCell(String label, String value, Color valueColor) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: const TextStyle(color: AccnomosColors.muted, fontSize: 12)),
        const SizedBox(height: 2),
        Text(value,
            softWrap: true,
            style: TextStyle(
                fontWeight: FontWeight.w800,
                fontSize: 17,
                color: valueColor)),
      ],
    );
  }

  static String _monthHeading(String month) {
    final parts = month.split('-');
    if (parts.length != 2) return month.isEmpty ? 'This month' : month;
    const months = [
      'January', 'February', 'March', 'April', 'May', 'June',
      'July', 'August', 'September', 'October', 'November', 'December',
    ];
    final number = int.tryParse(parts[1]);
    if (number == null || number < 1 || number > 12) return month;
    return '${months[number - 1]} ${parts[0]}';
  }

  /// One row per category the summary reports, with a progress bar coloured
  /// by state: on track, near the limit, or over it. Categories without a
  /// budget show a grey track. Tapping a row sets that category's budget.
  List<Widget> _budgetRows() {
    final categories = <Map<String, dynamic>>[];
    if (_summary['categories'] is List) {
      for (final c in _summary['categories'] as List) {
        if (c is Map) categories.add(Map<String, dynamic>.from(c));
      }
    }
    if (categories.isEmpty) {
      return [
        _plainCard('No spending this month yet — '
            'import a bank statement on the web first.')
      ];
    }
    return [for (final c in categories) _budgetRow(c)];
  }

  Widget _budgetRow(Map<String, dynamic> category) {
    final id = (category['id'] ?? '').toString();
    final name = (category['name'] ?? id).toString();
    final spent = _pence(category['spent_pence']);
    final budget = _pence(category['budget_pence']);
    final state = (category['state'] ?? 'none').toString();
    final percent = category['percent'];
    final fraction =
        percent is num ? (percent.toDouble() / 100).clamp(0.0, 1.0) : 0.0;
    final shown = percent is num ? percent.toInt() : 0;
    final Color barColor;
    switch (state) {
      case 'over':
        barColor = AccnomosColors.budgetOver;
      case 'near':
        barColor = AccnomosColors.budgetNear;
      case 'ok':
        barColor = AccnomosColors.budgetOk;
      default:
        barColor = const Color(0xFFE3E1D8);
    }
    final detail = budget > 0
        ? '${formatPence(spent)} of ${formatPence(budget)}'
        : '${formatPence(spent)} · no budget set';
    final semanticsLabel = budget > 0
        ? '$name budget $shown per cent spent'
        : '$name, no budget set, ${formatPence(spent)} spent';
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
          contentPadding:
              const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
          title: Text(name,
              style: const TextStyle(fontWeight: FontWeight.w700)),
          subtitle: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 2),
              Text(detail,
                  style: const TextStyle(
                      color: AccnomosColors.muted, fontSize: 12)),
              const SizedBox(height: 6),
              Semantics(
                label: semanticsLabel,
                value: budget > 0 ? '$shown per cent' : null,
                child: ExcludeSemantics(
                  child: LinearProgressIndicator(
                    value: budget > 0 ? fraction : 0.0,
                    minHeight: 8,
                    borderRadius: BorderRadius.circular(4),
                    backgroundColor: const Color(0xFFEDEAE2),
                    valueColor: AlwaysStoppedAnimation<Color>(barColor),
                  ),
                ),
              ),
              const SizedBox(height: 2),
            ],
          ),
          trailing: const Icon(Icons.edit_outlined),
          onTap: () => _editBudget(id, name, budget),
        ),
      ),
    );
  }

  /// The one write on this screen: a £ amount for [categoryId], saved with
  /// the budgets already on the reader so the other categories keep theirs.
  Future<void> _editBudget(String categoryId, String name, int current) async {
    final controller = TextEditingController(
        text: current > 0 ? (current / 100).toStringAsFixed(2) : '');
    final pence = await showDialog<int>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text('$name budget'),
        content: TextField(
          controller: controller,
          key: const Key('budgetAmountField'),
          keyboardType:
              const TextInputType.numberWithOptions(decimal: true),
          decoration: const InputDecoration(
            prefixText: '£ ',
            helperText: 'A month. Empty means no budget.',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              final text = controller.text.trim().replaceFirst('£', '').trim();
              if (text.isEmpty) {
                Navigator.of(dialogContext).pop(0);
                return;
              }
              final pounds = double.tryParse(text);
              if (pounds == null || pounds < 0 || pounds > 100000000) {
                ScaffoldMessenger.of(dialogContext).showSnackBar(
                  const SnackBar(
                      content: Text('Enter an amount in pounds, e.g. 250.')),
                );
                return;
              }
              Navigator.of(dialogContext).pop((pounds * 100).round());
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
    if (pence == null || !mounted) return;
    setState(() => _error = null);
    try {
      final client = await _booksClient();
      final budgets = Map<String, int>.from(_budgets);
      if (pence <= 0) {
        budgets.remove(categoryId);
      } else {
        budgets[categoryId] = pence;
      }
      await client.savePersonalBudgets(budgets);
      await _reload(quiet: true);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = _friendly(e));
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(_friendly(e))),
      );
    }
  }

  /// Regular bills and subscriptions the runtime found in the statements.
  /// Estimates: the next due date is the last payment plus one cycle, not
  /// a date from the provider.
  List<Widget> _billRows() {
    if (_bills.isEmpty) {
      return [_plainCard('No recurring bills found in your statements yet.')];
    }
    final rows = [for (final bill in _bills) _billRow(bill)];
    if (_billsNote.isNotEmpty) {
      rows.add(Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Text(_billsNote,
            style: const TextStyle(
                color: AccnomosColors.muted, fontSize: 12, height: 1.4)),
      ));
    }
    return rows;
  }

  Widget _billRow(Map<String, dynamic> bill) {
    final label = (bill['label'] ?? 'Bill').toString();
    final category = (bill['category_name'] ?? '').toString();
    final amount = formatPence(_pence(bill['amount_pence']));
    final due = _ukDate((bill['next_due'] ?? '').toString());
    final varies = bill['amount_varies'] == true;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label,
                    style: const TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(height: 2),
                Text(
                  [
                    if (category.isNotEmpty) category,
                    if (varies) 'varies',
                  ].join(' · '),
                  style: const TextStyle(
                      color: AccnomosColors.muted, fontSize: 12),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(amount,
                  style: const TextStyle(
                      fontWeight: FontWeight.w800,
                      fontSize: 16,
                      color: AccnomosColors.ink)),
              const SizedBox(height: 2),
              Text('next due $due',
                  style: const TextStyle(
                      color: AccnomosColors.muted, fontSize: 12)),
            ],
          ),
        ],
      ),
    );
  }

  /// Savings goals with the monthly amount the runtime works out.
  List<Widget> _goalRows() {
    if (_goals.isEmpty) {
      return [_plainCard('No savings goals yet — add one on the web.')];
    }
    return [for (final goal in _goals) _goalRow(goal)];
  }

  Widget _goalRow(Map<String, dynamic> plan) {
    final goal = plan['goal'];
    final name = (goal is Map ? goal['name'] : plan['name'] ?? 'Goal').toString();
    final monthly = formatPence(_pence(plan['monthly_needed_pence']));
    final saved = formatPence(_pence(
        goal is Map ? goal['saved_pence'] : plan['saved_pence']));
    final target = goal is Map
        ? formatPence(_pence(goal['target_pence']))
        : '';
    final percent = plan['percent'];
    final status = (plan['status'] ?? '').toString();
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text(name,
                    style: const TextStyle(fontWeight: FontWeight.w700)),
              ),
              const SizedBox(width: 8),
              Flexible(
                child: Text('$monthly a month needed',
                    textAlign: TextAlign.end,
                    style: const TextStyle(
                        fontWeight: FontWeight.w800,
                        fontSize: 14,
                        color: AccnomosColors.tealDark)),
              ),
            ],
          ),
          const SizedBox(height: 2),
          Text(
            target.isEmpty
                ? 'Saved $saved'
                : 'Saved $saved of $target'
                    '${percent is num ? ' (${percent.toInt()}%)' : ''}'
                    '${status == 'reached' ? ' · reached' : ''}',
            style:
                const TextStyle(color: AccnomosColors.muted, fontSize: 12),
          ),
        ],
      ),
    );
  }

  Widget _plainCard(String text) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Text(text,
          style: const TextStyle(color: AccnomosColors.muted, height: 1.4)),
    );
  }

  static String _ukDate(String iso) {
    try {
      final date = DateTime.parse(iso.trim());
      const months = [
        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
      ];
      return '${date.day} ${months[date.month - 1]} ${date.year}';
    } catch (_) {
      return iso;
    }
  }
}
