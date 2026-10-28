library;

/// The month-end close from `GET /close` and `GET /close/{yyyy-mm}`
/// (`services/runtime/app/month_end.py`). The phone only reads it: the
/// close is run, and its cards approved, on the web. Every text here was
/// written by the runtime's code (the summary by the user's AI, checked
/// by code); the phone never computes a figure.

String _s(Object? v) => (v ?? '').toString();

int? _int(Object? v) => (v as num?)?.toInt();

List<Map<String, dynamic>> _maps(Object? v) => [
      if (v is List)
        for (final x in v)
          if (x is Map) Map<String, dynamic>.from(x),
    ];

const _monthNames = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/// "2026-10" → "October 2026".
String monthLabel(String month) {
  final parts = month.split('-');
  if (parts.length != 2) return month;
  final m = int.tryParse(parts[1]);
  if (m == null || m < 1 || m > 12) return month;
  return '${_monthNames[m - 1]} ${parts[0]}';
}

/// The twelve months before [today]'s, newest first, as `yyyy-mm`.
List<String> recentMonths(DateTime today) {
  final out = <String>[];
  var y = today.year;
  var m = today.month;
  for (var i = 0; i < 12; i++) {
    m -= 1;
    if (m == 0) {
      m = 12;
      y -= 1;
    }
    out.add('$y-${m.toString().padLeft(2, '0')}');
  }
  return out;
}

/// One finding on a step: `blocking` stops the close, `needs_you` does
/// not, `note` is for information.
class CloseFinding {
  const CloseFinding({required this.text, required this.level});

  final String text;
  final String level;

  bool get blocking => level == 'blocking';

  static CloseFinding fromJson(Map<String, dynamic> j) =>
      CloseFinding(text: _s(j['text']), level: _s(j['level']));
}

/// One of the nine steps: `ok`, `needs_you` or `blocked`, with its reason.
class CloseStep {
  const CloseStep({
    required this.n,
    required this.title,
    required this.status,
    required this.reason,
    required this.found,
    required this.checked,
  });

  final int n;
  final String title;
  final String status;
  final String reason;
  final List<CloseFinding> found;
  final List<String> checked;

  String get statusLabel => switch (status) {
        'ok' => 'OK',
        'needs_you' => 'Needs you',
        'blocked' => 'Blocked',
        _ => status,
      };

  static CloseStep fromJson(Map<String, dynamic> j) => CloseStep(
        n: _int(j['n']) ?? 0,
        title: _s(j['title']),
        status: _s(j['status']),
        reason: _s(j['reason']),
        found: _maps(j['found']).map(CloseFinding.fromJson).toList(),
        checked: [
          if (j['checked'] is List)
            for (final c in j['checked'] as List) _s(c),
        ],
      );
}

/// A month's close as the phone shows it: the headline, the last run's
/// summary and steps, and what changed since the close, if anything.
class MonthClose {
  const MonthClose({
    required this.month,
    required this.label,
    required this.headline,
    required this.closed,
    required this.steps,
    this.summary,
    this.summaryByCode = false,
    this.lastRunAt,
    this.changes = const [],
    this.figures = const [],
  });

  final String month;
  final String label;
  final String headline;
  final bool closed;
  final List<CloseStep> steps;
  final String? summary;
  final bool summaryByCode;
  final DateTime? lastRunAt;

  /// One sentence per change since the close.
  final List<String> changes;

  /// (label, when closed, now) for each figure that moved.
  final List<(String, String, String)> figures;

  static MonthClose fromJson(Map<String, dynamic> j) {
    final run = j['run'] is Map ? Map<String, dynamic>.from(j['run'] as Map) : null;
    final changes = j['changes'] is Map ? Map<String, dynamic>.from(j['changes'] as Map) : null;
    final month = _s(j['month']);
    return MonthClose(
      month: month,
      label: _s(j['label']).isEmpty ? monthLabel(month) : _s(j['label']),
      headline: _s(j['headline']),
      closed: j['closed'] == true,
      steps: run == null ? const [] : _maps(run['steps']).map(CloseStep.fromJson).toList(),
      summary: run == null ? null : _s(run['summary_md']),
      summaryByCode: run != null && run['summary_fallback_reason'] != null,
      lastRunAt: DateTime.tryParse(_s(j['last_run_at']))?.toLocal(),
      changes: [
        if (changes != null && changes['items'] is List)
          for (final c in changes['items'] as List) _s(c),
      ],
      figures: [
        if (changes != null)
          for (final f in _maps(changes['figures']))
            (_s(f['label']), _s(f['before']), _s(f['after'])),
      ],
    );
  }
}

/// Home's line from `GET /close`: the month that ended last, plus any
/// closed month that changed since.
class CloseOverview {
  const CloseOverview({required this.month, required this.headline, required this.warn, this.changed = const []});

  final String month;
  final String headline;
  final bool warn;
  final List<String> changed;

  static CloseOverview fromJson(Map<String, dynamic> j) {
    final target = j['target'] is Map ? Map<String, dynamic>.from(j['target'] as Map) : <String, dynamic>{};
    final changed = _maps(j['changed']);
    return CloseOverview(
      month: _s(target['month']),
      headline: _s(target['headline']),
      warn: target['changes'] != null || changed.isNotEmpty,
      changed: [for (final c in changed) _s(c['headline'])],
    );
  }
}
