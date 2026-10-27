/// VAT return view from `GET /books/vat` (see
/// `services/runtime/app/routes_vat.py`): the 9 boxes HMRC expects.
class VatReturn {
  VatReturn({
    required this.periodKey,
    required this.start,
    required this.end,
    this.period = '',
    this.label = '',
    this.current = false,
    this.submitted = false,
    required this.boxes,
    required this.warnings,
    required this.eventsInPeriod,
  });

  final String periodKey;
  final String start;
  final String end;
  final String period; // "2026-Q4", as [VatPeriod.period]
  final String label; // "Oct–Dec 2026"
  final bool current;
  final bool submitted;
  final List<VatBox> boxes;
  final List<String> warnings;
  final int eventsInPeriod;

  factory VatReturn.fromJson(Map<String, dynamic> json) {
    final boxes = <VatBox>[];
    if (json['boxes'] is List) {
      for (final b in json['boxes'] as List) {
        if (b is Map) boxes.add(VatBox.fromJson(Map<String, dynamic>.from(b)));
      }
    }
    boxes.sort((a, b) => a.box.compareTo(b.box));
    final warnings = <String>[];
    if (json['warnings'] is List) {
      for (final w in json['warnings'] as List) {
        warnings.add(w.toString());
      }
    }
    return VatReturn(
      periodKey: (json['period_key'] ?? '').toString(),
      start: (json['start'] ?? '').toString(),
      end: (json['end'] ?? '').toString(),
      period: (json['period'] ?? '').toString(),
      label: (json['label'] ?? '').toString(),
      current: json['current'] == true,
      submitted: json['submitted'] == true,
      boxes: boxes,
      warnings: warnings,
      eventsInPeriod: (json['events_in_period'] as num?)?.toInt() ?? 0,
    );
  }
}

/// One numbered VAT box: amounts are pounds as HMRC receives them.
class VatBox {
  VatBox({
    required this.box,
    required this.label,
    required this.amount,
    required this.entries,
  });

  final int box;
  final String label;
  final String amount;
  final int entries;

  factory VatBox.fromJson(Map<String, dynamic> json) {
    return VatBox(
      box: (json['box'] as num?)?.toInt() ?? 0,
      label: (json['label'] ?? '').toString(),
      amount: (json['amount'] ?? '0').toString(),
      entries: (json['entries'] as num?)?.toInt() ?? 0,
    );
  }
}

/// One entry of `GET /books/vat/periods`: status and deadline worked out by
/// the runtime, so the phone only shows them.
class VatPeriod {
  VatPeriod({
    required this.period,
    required this.label,
    required this.status,
    required this.current,
    this.start = '',
    this.end = '',
  });

  final String period;
  final String label;
  final String status; // open | submitted | none
  final bool current;
  final String start; // "2026-10-01": the P&L span for this period
  final String end; // "2026-12-31"

  static List<VatPeriod> listFromJson(Map<String, dynamic> json) {
    final out = <VatPeriod>[];
    if (json['periods'] is List) {
      for (final p in json['periods'] as List) {
        if (p is! Map) continue;
        out.add(VatPeriod(
          period: (p['period'] ?? '').toString(),
          label: (p['label'] ?? '').toString(),
          status: (p['status'] ?? 'none').toString(),
          current: p['current'] == true,
          start: (p['start'] ?? '').toString(),
          end: (p['end'] ?? '').toString(),
        ));
      }
    }
    return out;
  }

  String get caption {
    final what = status == 'submitted'
        ? 'submitted'
        : current
            ? 'current'
            : status == 'open'
                ? 'open'
                : 'nothing recorded';
    return '$label · $what';
  }
}
