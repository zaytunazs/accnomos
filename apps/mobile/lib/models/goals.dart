import 'dart:convert';

import '../services/money.dart';

/// Goals tracked by code against the books (`GET /books/goals`,
/// services/runtime/app/goals.py). The runtime works out every figure,
/// status and suggestion; the phone only shows them, like the web's
/// components/goals.

int _int(Object? v) => v is num ? v.toInt() : int.tryParse('$v') ?? 0;
int? _intOrNull(Object? v) =>
    v == null ? null : (v is num ? v.toInt() : int.tryParse('$v'));
String _str(Object? v) => v == null ? '' : v.toString();
String? _strOrNull(Object? v) {
  final s = v?.toString();
  return s == null || s.trim().isEmpty ? null : s;
}

/// £1,234.56 from pence; a minus sign before the pound sign when negative.
String money(int pence) => formatMoneyPence(pence);

/// The large figure on a card: whole pounds when there are no pence.
String moneyShort(int pence) {
  if (pence % 100 != 0) return money(pence);
  return formatMoneyPence(pence, whole: true);
}

class GoalDriver {
  const GoalDriver({
    required this.name,
    required this.kind,
    required this.thisPence,
    required this.beforePence,
    required this.changePence,
  });

  final String name;

  /// `category`, `item` or `supplier`.
  final String kind;
  final int thisPence;
  final int beforePence;
  final int changePence;

  factory GoalDriver.fromJson(Map<String, dynamic> j) => GoalDriver(
        name: _str(j['name']),
        kind: _str(j['kind']),
        thisPence: _int(j['this_pence']),
        beforePence: _int(j['before_pence']),
        changePence: _int(j['change_pence']),
      );
}

class GoalView {
  const GoalView({
    required this.id,
    required this.name,
    required this.kind,
    required this.kindLabel,
    required this.status,
    required this.statusLabel,
    required this.tone,
    required this.periodLabel,
    required this.currentPence,
    required this.targetLabel,
    required this.varianceText,
    required this.sourceText,
    this.targetPence,
    this.baselineLabel,
    this.planToDatePence,
    this.percent,
    this.neededText,
    this.runRatePence,
    this.measure = 'manual',
    this.savedPence = 0,
    this.drivers = const [],
    this.suggestions = const [],
  });

  final String id;
  final String name;

  /// `save`, `spend_cap`, `spend_less` or `earn`.
  final String kind;
  final String kindLabel;
  final String status;
  final String statusLabel;

  /// `positive`, `warning`, `negative` or `neutral`.
  final String tone;
  final String periodLabel;
  final int currentPence;
  final int? targetPence;
  final String targetLabel;
  final String? baselineLabel;
  final int? planToDatePence;
  final int? percent;
  final String varianceText;
  final String? neededText;

  /// At the same daily pace, by the end: an estimate.
  final int? runRatePence;
  final String sourceText;
  final String measure;
  final int savedPence;
  final List<GoalDriver> drivers;
  final List<String> suggestions;

  bool get spending => kind == 'spend_cap' || kind == 'spend_less';

  /// Most urgent first on Home: off track, over the limit and missed, then
  /// at risk, then the rest.
  int get urgency => switch (status) {
        'off_track' || 'over_limit' || 'missed' => 0,
        'at_risk' => 1,
        _ => 2,
      };

  factory GoalView.fromJson(Map<String, dynamic> j) {
    final goal = j['goal'] is Map
        ? Map<String, dynamic>.from(j['goal'] as Map)
        : <String, dynamic>{};
    return GoalView(
      id: _str(goal['id']),
      name: _str(goal['name']),
      kind: _str(goal['kind']),
      kindLabel: _str(j['kind_label']),
      status: _str(j['status']),
      statusLabel: _str(j['status_label']),
      tone: _str(j['tone']).isEmpty ? 'neutral' : _str(j['tone']),
      periodLabel: _str(j['period_label']),
      currentPence: _int(j['current_pence']),
      targetPence: _intOrNull(j['target_pence']),
      targetLabel: _str(j['target_label']),
      baselineLabel: _strOrNull(j['baseline_label']),
      planToDatePence: _intOrNull(j['plan_to_date_pence']),
      percent: _intOrNull(j['percent']),
      varianceText: _str(j['variance_text']),
      neededText: _strOrNull(j['needed_text']),
      runRatePence: _intOrNull(j['run_rate_pence']),
      sourceText: _str(j['source_text']),
      measure: _str(goal['measure']).isEmpty ? 'manual' : _str(goal['measure']),
      savedPence: _int(goal['saved_pence']),
      drivers: [
        if (j['drivers'] is List)
          for (final d in j['drivers'] as List)
            if (d is Map) GoalDriver.fromJson(Map<String, dynamic>.from(d)),
      ],
      suggestions: [
        if (j['suggestions'] is List)
          for (final s in j['suggestions'] as List) s.toString(),
      ],
    );
  }
}

class GoalsNote {
  const GoalsNote({required this.text, required this.model, this.fallbackReason});

  final String text;

  /// `code` when no AI is set up.
  final String model;
  final String? fallbackReason;

  String get byLine => model != 'code' && fallbackReason == null
      ? 'Written by your AI ($model) from the figures below; every number checked by code.'
      : (fallbackReason ?? 'Written by code from the figures below.');

  factory GoalsNote.fromJson(Object? raw) {
    final j = raw is Map ? Map<String, dynamic>.from(raw) : <String, dynamic>{};
    return GoalsNote(
      text: _str(j['note_md']),
      model: _str(j['model']).isEmpty ? 'code' : _str(j['model']),
      fallbackReason: _strOrNull(j['fallback_reason']),
    );
  }
}

class GoalsData {
  const GoalsData({
    required this.goals,
    required this.note,
    this.household = false,
    this.sample = false,
  });

  final List<GoalView> goals;
  final GoalsNote note;
  final bool household;

  /// Fictional sample goals (signed out).
  final bool sample;

  List<GoalView> get mostUrgentFirst {
    final out = [...goals];
    out.sort((a, b) => a.urgency.compareTo(b.urgency));
    return out;
  }

  factory GoalsData.fromJson(Map<String, dynamic> j) => GoalsData(
        household: j['household'] == true,
        goals: [
          if (j['goals'] is List)
            for (final g in j['goals'] as List)
              if (g is Map) GoalView.fromJson(Map<String, dynamic>.from(g)),
        ],
        note: GoalsNote.fromJson(j['note']),
      );
}

/// The runtime's own sentence from a refused request: the reader's
/// `{"detail": "..."}` (a string, or FastAPI's list of field errors), else
/// the message as it came.
String goalError(Object e) {
  final text = e.toString().replaceFirst('Exception: ', '');
  final start = text.indexOf('{');
  if (start >= 0) {
    try {
      final decoded = json.decode(text.substring(start).replaceAll('…', ''));
      final detail = decoded is Map ? decoded['detail'] : null;
      if (detail is String && detail.trim().isNotEmpty) return detail.trim();
      if (detail is List && detail.isNotEmpty && detail.first is Map) {
        final msg = (detail.first as Map)['msg']?.toString() ?? '';
        if (msg.isNotEmpty) return msg.replaceFirst('Value error, ', '');
      }
    } catch (_) {
      // Not JSON: fall through to the plain message.
    }
  }
  return text;
}

// --------------------------------------------------------------------------
// Fictional sample goals for signed-out visitors. Every figure is made up.
// --------------------------------------------------------------------------

const _companySample = [
  GoalView(
    id: 'sample-sales',
    name: 'November sales',
    kind: 'earn',
    kindLabel: 'Sales target',
    status: 'at_risk',
    statusLabel: 'At risk',
    tone: 'warning',
    periodLabel: '1 Nov 2026 – 30 Nov 2026',
    currentPence: 1245000,
    targetPence: 3000000,
    targetLabel: '£30,000.00 sales target',
    planToDatePence: 1500000,
    percent: 41,
    varianceText: '£2,550.00 behind plan to date.',
    neededText: '£17,550.00 still to go by 30 Nov 2026.',
    runRatePence: 2490000,
    sourceText: 'Sales in your approved ledger, before VAT, from 1 Nov 2026',
    suggestions: ['£17,550.00 still to go by 30 Nov 2026.'],
  ),
  GoalView(
    id: 'sample-materials',
    name: 'Keep materials under £8,000',
    kind: 'spend_cap',
    kindLabel: 'Spending limit',
    status: 'on_track',
    statusLabel: 'On track',
    tone: 'positive',
    periodLabel: '1 Nov 2026 – 30 Nov 2026',
    currentPence: 362000,
    targetPence: 800000,
    targetLabel: '£8,000.00 spending limit on Materials',
    planToDatePence: 400000,
    percent: 45,
    varianceText: '£380.00 under plan to date.',
    neededText: '£4,380.00 left to spend by 30 Nov 2026.',
    runRatePence: 724000,
    sourceText: 'Approved purchases on Materials, before VAT, from 1 Nov 2026',
    drivers: [
      GoalDriver(name: 'Oak boards', kind: 'item', thisPence: 148000, beforePence: 121000, changePence: 27000),
      GoalDriver(name: 'Timber Yard Ltd', kind: 'supplier', thisPence: 210000, beforePence: 196000, changePence: 14000),
    ],
  ),
  GoalView(
    id: 'sample-vat',
    name: 'Put aside for the VAT bill',
    kind: 'save',
    kindLabel: 'Savings goal',
    status: 'off_track',
    statusLabel: 'Off track',
    tone: 'negative',
    periodLabel: '1 Oct 2026 – 31 Dec 2026',
    currentPence: 150000,
    targetPence: 600000,
    targetLabel: '£6,000.00 target',
    planToDatePence: 300000,
    percent: 25,
    varianceText: '£1,500.00 behind plan to date.',
    neededText: '£4,500.00 still to go: about £2,250.00 a month.',
    sourceText: 'The amount you have recorded as put aside',
    savedPence: 150000,
    suggestions: [
      'Record what you put aside as you go, so the progress stays current.',
    ],
  ),
];

const _householdSample = [
  GoalView(
    id: 'sample-school',
    name: 'School fees',
    kind: 'save',
    kindLabel: 'Savings goal',
    status: 'off_track',
    statusLabel: 'Off track',
    tone: 'negative',
    periodLabel: '1 Sep 2026 – 1 Sep 2027',
    currentPence: 9000,
    targetPence: 100000,
    targetLabel: '£1,000.00 target',
    planToDatePence: 17000,
    percent: 9,
    varianceText: '£80.00 behind plan to date.',
    neededText: '£910.00 still to go: about £91.00 a month.',
    sourceText: 'The amount you have recorded as put aside',
    savedPence: 9000,
    suggestions: [
      'Record what you put aside as you go, so the progress stays current.',
    ],
  ),
  GoalView(
    id: 'sample-coffee',
    name: 'Spend less on coffee',
    kind: 'spend_less',
    kindLabel: 'Spend less',
    status: 'over_limit',
    statusLabel: 'Over limit',
    tone: 'negative',
    periodLabel: '1 Jan 2026 – 31 Dec 2026',
    currentPence: 52180,
    targetPence: 16135,
    targetLabel: 'Cut by 30%: at most £161.35 so far',
    baselineLabel: '£230.50 spent on coffee over the same dates a year earlier',
    planToDatePence: 16135,
    percent: 323,
    varianceText: '£360.45 over the limit.',
    sourceText: 'Money out on your bank lines on coffee, transfers left out',
    drivers: [
      GoalDriver(name: 'Caffe Nero', kind: 'supplier', thisPence: 12975, beforePence: 4835, changePence: 8140),
      GoalDriver(name: 'Pret A Manger', kind: 'supplier', thisPence: 13860, beforePence: 9200, changePence: 4660),
    ],
    suggestions: [
      'You have spent £129.75 with Caffe Nero so far, £81.40 more than the same number of days before. Bringing it back to £48.35 would close part of the gap of £360.45.',
    ],
  ),
  GoalView(
    id: 'sample-groceries',
    name: 'Groceries under £350 this month',
    kind: 'spend_cap',
    kindLabel: 'Spending limit',
    status: 'on_track',
    statusLabel: 'On track',
    tone: 'positive',
    periodLabel: '1 Nov 2026 – 30 Nov 2026',
    currentPence: 8240,
    targetPence: 35000,
    targetLabel: '£350.00 spending limit on Groceries',
    planToDatePence: 11667,
    percent: 23,
    varianceText: '£34.27 under plan to date.',
    neededText: '£267.60 left to spend by 30 Nov 2026.',
    runRatePence: 24720,
    sourceText: 'Money out on your bank lines on Groceries, transfers left out',
  ),
];

GoalsData sampleGoals({required bool household}) => GoalsData(
      household: household,
      sample: true,
      goals: household ? _householdSample : _companySample,
      note: GoalsNote(
        model: 'code',
        fallbackReason: 'Sample — fictional figures, written by code.',
        text: household
            ? 'Spend less on coffee is over limit. You have spent £129.75 with Caffe Nero so far, £81.40 more than the same number of days before.'
            : 'Put aside for the VAT bill is off track. Record what you put aside as you go, so the progress stays current.',
      ),
    );
