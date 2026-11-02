/// The household Home's figures, all worked out by the runtime from the
/// imported bank statements (`GET /personal/summary`, `GET /personal/recurring`,
/// services/runtime/app/personal.py). The phone only picks and orders them.

int _int(Object? v) => v is num ? v.toInt() : int.tryParse('$v') ?? 0;
int? _intOrNull(Object? v) =>
    v == null ? null : (v is num ? v.toInt() : int.tryParse('$v'));

class CategorySpend {
  const CategorySpend({
    required this.id,
    required this.name,
    required this.spentPence,
    this.budgetPence,
    this.remainingPence,
    this.percent,
    this.state = 'none',
  });

  final String id;
  final String name;
  final int spentPence;
  final int? budgetPence;
  final int? remainingPence;
  final int? percent;

  /// `none`, `ok`, `near` or `over`.
  final String state;

  factory CategorySpend.fromJson(Map<String, dynamic> j) => CategorySpend(
        id: '${j['id'] ?? ''}',
        name: '${j['name'] ?? ''}',
        spentPence: _int(j['spent_pence']),
        budgetPence: _intOrNull(j['budget_pence']),
        remainingPence: _intOrNull(j['remaining_pence']),
        percent: _intOrNull(j['percent']),
        state: '${j['state'] ?? 'none'}',
      );
}

class MonthSummary {
  const MonthSummary({
    required this.month,
    required this.incomePence,
    required this.spentPence,
    required this.leftPence,
    this.lines = 0,
    this.categories = const [],
    this.uncategorisedCount = 0,
  });

  /// `YYYY-MM`.
  final String month;
  final int incomePence;
  final int spentPence;
  final int leftPence;
  final int lines;
  final List<CategorySpend> categories;
  final int uncategorisedCount;

  factory MonthSummary.fromJson(Map<String, dynamic> j) => MonthSummary(
        month: '${j['month'] ?? ''}',
        incomePence: _int(j['income_pence']),
        spentPence: _int(j['spent_pence']),
        leftPence: _int(j['left_pence']),
        lines: _int(j['lines']),
        uncategorisedCount: _int(j['uncategorised_count']),
        categories: [
          if (j['categories'] is List)
            for (final c in j['categories'] as List)
              if (c is Map) CategorySpend.fromJson(Map<String, dynamic>.from(c)),
        ],
      );

  /// Budgeted categories, over first, then near, then the rest.
  List<CategorySpend> get budgeted {
    int rank(CategorySpend c) =>
        switch (c.state) { 'over' => 0, 'near' => 1, _ => 2 };
    final out = [
      for (final c in categories)
        if ((c.budgetPence ?? 0) > 0) c
    ];
    out.sort((a, b) {
      final r = rank(a).compareTo(rank(b));
      return r != 0 ? r : b.spentPence.compareTo(a.spentPence);
    });
    return out;
  }

  int get overBudget => categories.where((c) => c.state == 'over').length;
  int get nearBudget => categories.where((c) => c.state == 'near').length;

  /// Where the money went: the largest categories first.
  List<CategorySpend> top(int n) {
    final out = [
      for (final c in categories)
        if (c.spentPence > 0) c
    ];
    out.sort((a, b) => b.spentPence.compareTo(a.spentPence));
    return out.take(n).toList();
  }
}

class Bill {
  const Bill({
    required this.label,
    required this.categoryName,
    required this.amountPence,
    required this.nextDue,
    required this.daysUntil,
    this.cadence = 'monthly',
    this.status = 'active',
    this.varies = false,
  });

  final String label;
  final String categoryName;
  final int amountPence;
  final String nextDue;
  final int daysUntil;
  final String cadence;
  final String status;
  final bool varies;

  factory Bill.fromJson(Map<String, dynamic> j) => Bill(
        label: '${j['label'] ?? ''}',
        categoryName: '${j['category_name'] ?? ''}',
        amountPence: _int(j['amount_pence']),
        nextDue: '${j['next_due'] ?? ''}',
        daysUntil: _int(j['days_until']),
        cadence: '${j['cadence'] ?? ''}',
        status: '${j['status'] ?? ''}',
        varies: j['amount_varies'] == true,
      );
}

/// Bills and subscriptions expected in the next [days] days (estimates from
/// the statements), soonest first; stopped ones left out.
List<Bill> upcomingBills(Map<String, dynamic> recurring, {int days = 30}) {
  final out = <Bill>[
    if (recurring['items'] is List)
      for (final i in recurring['items'] as List)
        if (i is Map) Bill.fromJson(Map<String, dynamic>.from(i)),
  ];
  return out
      .where((b) => b.status != 'stopped' && b.daysUntil >= 0 && b.daysUntil <= days)
      .toList()
    ..sort((a, b) => a.daysUntil.compareTo(b.daysUntil));
}

/// `YYYY-MM` for [day]'s month, and for the month before it.
String monthKey(DateTime day) =>
    '${day.year.toString().padLeft(4, '0')}-${day.month.toString().padLeft(2, '0')}';
String previousMonthKey(DateTime day) =>
    monthKey(DateTime(day.year, day.month - 1, 1));

// --------------------------------------------------------------------------
// Household sample for signed-out visitors. Every figure is fictional.
// --------------------------------------------------------------------------

const sampleThisMonth = MonthSummary(
  month: '2026-11',
  incomePence: 325000,
  spentPence: 241035,
  leftPence: 83965,
  lines: 46,
  uncategorisedCount: 3,
  categories: [
    CategorySpend(id: 'housing', name: 'Housing', spentPence: 135000, budgetPence: 135000, remainingPence: 0, percent: 100, state: 'near'),
    CategorySpend(id: 'groceries', name: 'Groceries', spentPence: 28240, budgetPence: 35000, remainingPence: 6760, percent: 80, state: 'near'),
    CategorySpend(id: 'coffee', name: 'Coffee & snacks', spentPence: 6810, budgetPence: 4000, remainingPence: -2810, percent: 170, state: 'over'),
    CategorySpend(id: 'eating_out', name: 'Eating out', spentPence: 9450, budgetPence: 12000, remainingPence: 2550, percent: 78, state: 'ok'),
    CategorySpend(id: 'transport', name: 'Transport', spentPence: 15620, budgetPence: 18000, remainingPence: 2380, percent: 86, state: 'near'),
    CategorySpend(id: 'utilities', name: 'Utilities', spentPence: 21400, budgetPence: 24000, remainingPence: 2600, percent: 89, state: 'near'),
    CategorySpend(id: 'subscriptions', name: 'Subscriptions', spentPence: 4515, budgetPence: 5000, remainingPence: 485, percent: 90, state: 'near'),
    CategorySpend(id: 'other', name: 'Other', spentPence: 20000),
  ],
);

const sampleLastMonth = MonthSummary(
  month: '2026-10',
  incomePence: 325000,
  spentPence: 268420,
  leftPence: 56580,
);

final sampleRecurring = <String, dynamic>{
  'items': [
    {'label': 'NETFLIX.COM', 'category_name': 'Subscriptions', 'amount_pence': 1099, 'next_due': '2026-11-14', 'days_until': 4, 'cadence': 'monthly', 'status': 'active'},
    {'label': 'OCTOPUS ENERGY', 'category_name': 'Utilities', 'amount_pence': 14200, 'next_due': '2026-11-18', 'days_until': 8, 'cadence': 'monthly', 'status': 'active', 'amount_varies': true},
    {'label': 'PUREGYM', 'category_name': 'Health', 'amount_pence': 2499, 'next_due': '2026-11-21', 'days_until': 11, 'cadence': 'monthly', 'status': 'active'},
    {'label': 'RENT — HOMELET', 'category_name': 'Housing', 'amount_pence': 135000, 'next_due': '2026-12-01', 'days_until': 21, 'cadence': 'monthly', 'status': 'active'},
  ],
  'note': 'Estimates from your imported statements: same payee, a regular gap, a similar amount.',
};

const sampleReceiptsWaiting = 2;
