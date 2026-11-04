import 'package:flutter/material.dart';
import 'package:msal_auth/msal_auth.dart';

import '../models/dashboard.dart';
import '../models/goals.dart';
import '../models/home_summary.dart';
import '../models/household.dart';
import '../services/app_mode.dart';
import '../services/auth.dart';
import '../services/books.dart' show booksClient, isoDate;
import '../services/books_events.dart';
import '../services/runtime_client.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/loading.dart';
import '../widgets/statement_import.dart';
import '../widgets/tile_grid.dart';
import 'goals_screen.dart';
import 'goals_widgets.dart';
import 'home_screen.dart' show SummaryCard, SummaryCardSkeleton;
import 'personal_screen.dart';
import 'review_screen.dart';
import 'settings_screen.dart';

/// Builds the runtime client for the household Home; tests inject a fake.
typedef HouseholdClientFactory = RuntimeClient Function(AppSettings settings);

/// Home for personal books: what needs doing, this month's money in and out,
/// budgets, goals, bills coming up and where the money went. Every figure is
/// worked out by the runtime from the imported bank statements; nothing about
/// VAT, sales or turnover. Signed out it shows the fictional household sample.
class HouseholdHomeScreen extends StatefulWidget {
  const HouseholdHomeScreen({
    super.key,
    this.clientFactory,
    @visibleForTesting this.testAccount,
    @visibleForTesting this.testAccountReady = false,
    @visibleForTesting this.today,
  });

  final HouseholdClientFactory? clientFactory;

  @visibleForTesting
  final Account? testAccount;

  @visibleForTesting
  final bool testAccountReady;

  @visibleForTesting
  final DateTime? today;

  @override
  State<HouseholdHomeScreen> createState() => _HouseholdHomeScreenState();
}

class _HouseholdHomeScreenState extends State<HouseholdHomeScreen> {
  final AuthService _auth = AuthService();
  AppSettings? _settings;
  Account? _account;
  bool _checked = false;
  bool _loading = false;
  String? _error;
  MonthSummary? _this;
  MonthSummary? _last;
  List<Bill> _bills = const [];
  String _billsNote = '';
  GoalsData? _goals;
  int? _receipts;
  HomeSummary? _summary;
  bool _summaryPending = false;
  bool _notePending = false;
  bool _billsLoaded = false;
  int _generation = 0;
  int _seenChange = BooksEvents.changed.value;

  DateTime get _today => widget.today ?? DateTime.now();

  @override
  void initState() {
    super.initState();
    BooksEvents.changed.addListener(_onBooksChanged);
    _load();
  }

  @override
  void dispose() {
    BooksEvents.changed.removeListener(_onBooksChanged);
    super.dispose();
  }

  /// An approval or other change elsewhere: the counts may have moved.
  void _onBooksChanged() {
    if (BooksEvents.changed.value == _seenChange) return;
    _seenChange = BooksEvents.changed.value;
    if (mounted && _account != null && !_loading) _reload();
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
      _settings = settings;
      _account = account;
      _checked = true;
    });
    if (account != null) await _reload();
  }

  Future<RuntimeClient> _client() async {
    final factory = widget.clientFactory;
    if (factory != null) return factory(_settings!);
    return booksClient(_settings!, _auth, _account);
  }

  /// Each section loads on its own and shows as soon as it arrives: the
  /// month first (the tiles), then bills, goals and the summary. One that
  /// fails leaves the rest standing.
  Future<void> _reload() async {
    final generation = ++_generation;
    setState(() {
      _loading = true;
      _error = null;
    });
    bool current() => mounted && generation == _generation;
    try {
      final c = await _client();
      final today = isoDate(_today);
      Future<void> soft<T>(Future<T> f, void Function(T value) apply) async {
        try {
          final v = await f;
          if (current()) setState(() => apply(v));
        } catch (_) {
          // This section stays as it was; the others still load.
        }
      }

      await Future.wait<void>([
        c.personalSummary(month: monthKey(_today)).then((json) {
          if (current()) setState(() => _this = MonthSummary.fromJson(json));
        }),
        soft(c.personalSummary(month: previousMonthKey(_today)),
            (Map<String, dynamic> json) => _last = MonthSummary.fromJson(json)),
        soft(c.personalRecurring(), (Map<String, dynamic> json) {
          _bills = upcomingBills(json);
          _billsNote = '${json['note'] ?? ''}';
          _billsLoaded = true;
        }),
        // Goals with code's note first, then the AI's note swapped in.
        () async {
          if (current()) setState(() => _notePending = true);
          await soft(c.goals(today: today, noteAi: false),
              (Map<String, dynamic> json) => _goals = GoalsData.fromJson(json));
          await soft(c.goals(today: today),
              (Map<String, dynamic> json) => _goals = GoalsData.fromJson(json));
          if (current()) setState(() => _notePending = false);
        }(),
        soft(c.dashboard(today: today), (Map<String, dynamic> json) {
          final d = Dashboard.fromJson(json);
          _receipts = (d.attentionProposed ?? 0) + (d.attentionNeedsALook ?? 0);
        }),
        // Code's summary at once, then the AI's words when they arrive.
        () async {
          if (current()) setState(() => _summaryPending = true);
          await soft(c.home(today: today, summaryAi: false),
              (Map<String, dynamic> json) =>
                  _summary = HomeSummary.fromHomeJson(json) ?? _summary);
          await soft(c.home(today: today), (Map<String, dynamic> json) {
            final worded = HomeSummary.fromHomeJson(json);
            if (worded != null) _summary = worded;
          });
          if (current()) setState(() => _summaryPending = false);
        }(),
      ]);
    } catch (e) {
      if (current()) setState(() => _error = goalError(e));
    } finally {
      if (current()) {
        setState(() {
          _loading = false;
          _billsLoaded = true;
        });
      }
    }
  }

  void _open(Widget screen) => Navigator.of(context)
      .push(MaterialPageRoute(builder: (_) => screen))
      .then((_) => _account != null ? _reload() : null);

  @override
  Widget build(BuildContext context) {
    if (!_checked) return const _HouseholdSkeleton();
    final signedIn = _account != null;
    final thisMonth = signedIn ? _this : sampleThisMonth;
    final lastMonth = signedIn ? _last : sampleLastMonth;
    final bills = signedIn ? _bills : upcomingBills(sampleRecurring);
    final billsNote = signedIn ? _billsNote : '${sampleRecurring['note']}';
    final goals = signedIn ? _goals : sampleGoals(household: true);
    final receipts = signedIn ? _receipts : sampleReceiptsWaiting;
    final noStatement = signedIn && thisMonth != null && thisMonth.lines == 0 &&
        (lastMonth == null || lastMonth.lines == 0);
    return RefreshIndicator(
      onRefresh: signedIn ? _reload : () async {},
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            signedIn
                ? 'Hello, ${AuthService.greetingName(_account!)}'
                : 'Your household at a glance',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 6),
          Text(
            signedIn
                ? 'Worked out by code from your own bank statements. Pull down to refresh.'
                : 'A fictional household, so you can see how it works. Sign in to see your own.',
            style: const TextStyle(color: AccnomosColors.muted, height: 1.4),
          ),
          if (signedIn && _summary != null) ...[
            const SizedBox(height: 14),
            SummaryCard(summary: _summary!, pending: _summaryPending),
          ] else if (signedIn && _summaryPending) ...[
            const SizedBox(height: 14),
            const SummaryCardSkeleton(),
          ],
          if (_error != null) ...[
            const SizedBox(height: 10),
            Text('Could not load your figures: $_error',
                style: const TextStyle(color: AccnomosColors.muted, fontSize: 12)),
          ],
          if (_loading && _this == null) ...[
            const SizedBox(height: 16),
            const _MonthSkeleton(),
          ],
          if (noStatement) ...[
            const SizedBox(height: 16),
            _Panel(
              title: 'Import a bank statement to start',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text(
                    'Your household figures come from your bank statements. Download a statement from your bank as a CSV, import it here, and this page fills in: money in and out, budgets, bills and goals.',
                    style: TextStyle(color: AccnomosColors.muted, height: 1.4),
                  ),
                  if (signedIn) ...[
                    const SizedBox(height: 12),
                    ImportStatementButton(clientFor: _client, onImported: _reload),
                  ],
                ],
              ),
            ),
          ] else if (thisMonth != null) ...[
            const SizedBox(height: 16),
            _AttentionTiles(
              receipts: receipts,
              month: thisMonth,
              nextBill: bills.isEmpty ? null : bills.first,
              onReview: () => _open(const ReviewScreen()),
              onBudget: () => _open(const PersonalScreen()),
            ),
            const SizedBox(height: 12),
            ThisMonthPanel(thisMonth: thisMonth, lastMonth: lastMonth),
            const SizedBox(height: 12),
            BudgetsPanel(
                month: thisMonth, onOpen: () => _open(const PersonalScreen())),
          ],
          if (goals != null) ...[
            const SizedBox(height: 12),
            _Panel(
              title: 'Goals & progress',
              action: TextButton(
                onPressed: () => _open(const GoalsScreen()),
                child: const Text('View all'),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (goals.goals.isEmpty)
                    const Text('No goals yet. Add one on the Goals tab.',
                        style: TextStyle(color: AccnomosColors.muted))
                  else
                    for (final g in goals.mostUrgentFirst.take(3))
                      GoalCard(goal: g, compact: true),
                  GoalsNotePanel(note: goals.note, pending: signedIn && _notePending),
                ],
              ),
            ),
          ] else if (signedIn && _loading) ...[
            const SizedBox(height: 12),
            const SkeletonCard(title: 'Goals & progress', lines: 4),
          ],
          if (!noStatement && (!signedIn || _billsLoaded)) ...[
            const SizedBox(height: 12),
            BillsPanel(bills: bills, note: billsNote),
          ] else if (!noStatement && signedIn) ...[
            const SizedBox(height: 12),
            const SkeletonCard(title: 'Bills and subscriptions coming up'),
          ],
          if (thisMonth != null && thisMonth.top(5).isNotEmpty) ...[
            const SizedBox(height: 12),
            WhereItWentPanel(month: thisMonth),
          ],
          if (!signedIn) ...[
            const SizedBox(height: 20),
            FilledButton(
              style: FilledButton.styleFrom(
                  backgroundColor: AccnomosColors.teal,
                  minimumSize: const Size.fromHeight(52),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8))),
              onPressed: () => Navigator.of(context)
                  .push(MaterialPageRoute(builder: (_) => const SettingsScreen()))
                  .then((_) => AppMode.refresh()),
              child: const Text('Connect your cloud',
                  style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
            ),
          ],
          const SizedBox(height: 10),
          const Text(
            'Accnomos never stores your data on its own servers.',
            textAlign: TextAlign.center,
            style: TextStyle(color: AccnomosColors.muted, fontSize: 12),
          ),
        ],
      ),
    );
  }
}

class _Panel extends StatelessWidget {
  const _Panel({required this.title, required this.child, this.action});
  final String title;
  final Widget child;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AccnomosColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(title,
                    style: const TextStyle(
                        fontSize: 17, fontWeight: FontWeight.w700)),
              ),
              ?action,
            ],
          ),
          const SizedBox(height: 10),
          child,
        ],
      ),
    );
  }
}

class _AttentionTiles extends StatelessWidget {
  const _AttentionTiles({
    required this.receipts,
    required this.month,
    required this.nextBill,
    required this.onReview,
    required this.onBudget,
  });

  final int? receipts;
  final MonthSummary month;
  final Bill? nextBill;
  final VoidCallback onReview;
  final VoidCallback onBudget;

  @override
  Widget build(BuildContext context) {
    final over = month.overBudget;
    final near = month.nearBudget;
    final bill = nextBill;
    return TileGrid(
      spacing: 10,
      children: [
        _Tile(
          icon: Icons.receipt_long_outlined,
          count: receipts?.toString() ?? '—',
          label: 'Receipts to review',
          note: (receipts ?? 0) == 0 ? 'Nothing waiting' : 'Check and approve',
          warn: (receipts ?? 0) > 0,
          onTap: onReview,
        ),
        _Tile(
          icon: Icons.label_off_outlined,
          count: '${month.uncategorisedCount}',
          label: 'Lines with no category',
          note: month.uncategorisedCount == 0 ? 'All sorted' : 'Shown as Other',
          warn: month.uncategorisedCount > 0,
          onTap: onBudget,
        ),
        _Tile(
          icon: Icons.pie_chart_outline,
          count: '$over',
          label: 'Budgets over',
          note: near > 0 ? '$near close to the limit' : 'This month',
          warn: over > 0,
          negative: over > 0,
          onTap: onBudget,
        ),
        _Tile(
          icon: Icons.event_outlined,
          count: bill == null
              ? '—'
              : bill.daysUntil == 0
                  ? 'Today'
                  : '${bill.daysUntil}d',
          label: 'Next bill',
          note: bill == null
              ? 'None in the next 30 days'
              : '${bill.label} · ${money(bill.amountPence)}',
          onTap: onBudget,
        ),
      ],
    );
  }
}

class _Tile extends StatelessWidget {
  const _Tile({
    required this.icon,
    required this.count,
    required this.label,
    required this.note,
    required this.onTap,
    this.warn = false,
    this.negative = false,
  });

  final IconData icon;
  final String count;
  final String label;
  final String note;
  final VoidCallback onTap;
  final bool warn;
  final bool negative;

  @override
  Widget build(BuildContext context) {
    final tone = ToneColors.of(negative ? 'negative' : warn ? 'warning' : 'positive');
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AccnomosColors.border),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(
                    color: tone.tint, borderRadius: BorderRadius.circular(8)),
                child: Icon(icon, size: 18, color: tone.text),
              ),
              const SizedBox(height: 10),
              const Spacer(),
              Text(count,
                  style: const TextStyle(
                      fontSize: 22, fontWeight: FontWeight.w700)),
              Text(label,
                  style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
              Text(note,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      fontSize: 12, color: AccnomosColors.muted)),
            ],
          ),
        ),
      ),
    );
  }
}

class ThisMonthPanel extends StatelessWidget {
  const ThisMonthPanel({super.key, required this.thisMonth, this.lastMonth});
  final MonthSummary thisMonth;
  final MonthSummary? lastMonth;

  @override
  Widget build(BuildContext context) {
    final last = lastMonth;
    String vs(int now, int? before) {
      if (before == null) return 'No figure last month';
      final d = now - before;
      if (d == 0) return 'Same as last month';
      return '${d > 0 ? 'Up' : 'Down'} ${money(d.abs())} on last month';
    }

    Widget figure(String label, int pence, String note, {Color? colour}) =>
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label,
                  style: const TextStyle(
                      fontSize: 13, color: AccnomosColors.muted)),
              const SizedBox(height: 2),
              FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text(moneyShort(pence),
                    style: TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.w700,
                        color: colour ?? AccnomosColors.ink,
                        fontFeatures: const [FontFeature.tabularFigures()])),
              ),
              Text(note,
                  style: const TextStyle(
                      fontSize: 12, color: AccnomosColors.muted)),
            ],
          ),
        );

    return _Panel(
      title: 'This month',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              figure('Money in', thisMonth.incomePence,
                  vs(thisMonth.incomePence, last?.incomePence)),
              const SizedBox(width: 10),
              figure('Money out', thisMonth.spentPence,
                  vs(thisMonth.spentPence, last?.spentPence)),
              const SizedBox(width: 10),
              figure('Left over', thisMonth.leftPence,
                  vs(thisMonth.leftPence, last?.leftPence),
                  colour: thisMonth.leftPence < 0
                      ? const Color(0xFFA12626)
                      : null),
            ],
          ),
          const SizedBox(height: 10),
          const Text(
              'From your bank statements; transfers between your own accounts and ignored lines left out.',
              style: TextStyle(fontSize: 12, color: AccnomosColors.muted)),
        ],
      ),
    );
  }
}

class BudgetsPanel extends StatelessWidget {
  const BudgetsPanel({super.key, required this.month, required this.onOpen});
  final MonthSummary month;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final rows = month.budgeted;
    return _Panel(
      title: 'Budgets',
      action: TextButton(onPressed: onOpen, child: const Text('Open budget')),
      child: rows.isEmpty
          ? const Text('No budgets set yet. Set a monthly amount per category on the Budget tab.',
              style: TextStyle(color: AccnomosColors.muted, height: 1.4))
          : Column(
              children: [
                for (final c in rows.take(6))
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: _BudgetRow(c: c),
                  ),
              ],
            ),
    );
  }
}

class _BudgetRow extends StatelessWidget {
  const _BudgetRow({required this.c});
  final CategorySpend c;

  @override
  Widget build(BuildContext context) {
    final budget = c.budgetPence ?? 0;
    final share = budget <= 0 ? 0.0 : (c.spentPence / budget).clamp(0.0, 1.0);
    final colour = switch (c.state) {
      'over' => AccnomosColors.budgetOver,
      'near' => AccnomosColors.budgetNear,
      _ => AccnomosColors.teal,
    };
    final remaining = c.remainingPence ?? (budget - c.spentPence);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
                child: Text(c.name,
                    style: const TextStyle(fontWeight: FontWeight.w600))),
            Text('${money(c.spentPence)} of ${money(budget)}',
                style: const TextStyle(
                    fontSize: 13,
                    fontFeatures: [FontFeature.tabularFigures()])),
          ],
        ),
        const SizedBox(height: 4),
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(
            value: share,
            minHeight: 8,
            color: colour,
            backgroundColor: const Color(0xFFE6ECEF),
          ),
        ),
        const SizedBox(height: 2),
        Text(
          remaining < 0
              ? '${money(-remaining)} over budget'
              : '${money(remaining)} left',
          style: TextStyle(
              fontSize: 12,
              color: remaining < 0 ? AccnomosColors.budgetOver : AccnomosColors.muted,
              fontWeight: remaining < 0 ? FontWeight.w700 : FontWeight.w400),
        ),
      ],
    );
  }
}

class BillsPanel extends StatelessWidget {
  const BillsPanel({super.key, required this.bills, required this.note});
  final List<Bill> bills;
  final String note;

  @override
  Widget build(BuildContext context) {
    return _Panel(
      title: 'Bills and subscriptions coming up',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (bills.isEmpty)
            const Text('Nothing expected in the next 30 days.',
                style: TextStyle(color: AccnomosColors.muted))
          else
            for (final b in bills.take(6))
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(b.label,
                              style:
                                  const TextStyle(fontWeight: FontWeight.w600)),
                          Text(
                              '${b.categoryName} · ${b.daysUntil == 0 ? 'due today' : 'in ${b.daysUntil} days'}',
                              style: const TextStyle(
                                  fontSize: 12, color: AccnomosColors.muted)),
                        ],
                      ),
                    ),
                    Text('${b.varies ? 'about ' : ''}${money(b.amountPence)}',
                        style: const TextStyle(
                            fontFeatures: [FontFeature.tabularFigures()])),
                  ],
                ),
              ),
          if (note.isNotEmpty)
            Text(note,
                style: const TextStyle(fontSize: 12, color: AccnomosColors.muted)),
        ],
      ),
    );
  }
}

class WhereItWentPanel extends StatelessWidget {
  const WhereItWentPanel({super.key, required this.month});
  final MonthSummary month;

  @override
  Widget build(BuildContext context) {
    final rows = month.top(5);
    final total = month.spentPence <= 0 ? 1 : month.spentPence;
    return _Panel(
      title: 'Where the money went',
      child: Column(
        children: [
          for (final c in rows)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                children: [
                  Expanded(child: Text(c.name)),
                  Text('${(c.spentPence * 100 / total).round()}%',
                      style: const TextStyle(color: AccnomosColors.muted)),
                  const SizedBox(width: 12),
                  SizedBox(
                    width: 96,
                    child: Text(money(c.spentPence),
                        textAlign: TextAlign.right,
                        style: const TextStyle(
                            fontFeatures: [FontFeature.tabularFigures()])),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

/// Tiles and "This month" while the month's figures load: the shapes of
/// what is coming, shimmering, never a lone spinner.
class _MonthSkeleton extends StatelessWidget {
  const _MonthSkeleton();

  @override
  Widget build(BuildContext context) => const Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TileGrid(children: [
            SkeletonTile(label: 'Receipts to review'),
            SkeletonTile(label: 'Lines with no category'),
            SkeletonTile(label: 'Budgets over'),
            SkeletonTile(label: 'Next bill'),
          ]),
          SizedBox(height: 12),
          SkeletonCard(title: 'This month', lines: 3),
          SizedBox(height: 12),
          SkeletonCard(title: 'Budgets', lines: 4),
        ],
      );
}

/// The whole household Home before the sign-in check has answered.
class _HouseholdSkeleton extends StatelessWidget {
  const _HouseholdSkeleton();

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.all(16),
        children: const [
          SummaryCardSkeleton(),
          SizedBox(height: 16),
          _MonthSkeleton(),
        ],
      );
}
