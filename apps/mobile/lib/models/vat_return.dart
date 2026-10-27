/// VAT return view from `GET /books/vat` (see
/// `services/runtime/app/routes_vat.py`): the 9 boxes HMRC expects.
class VatReturn {
  VatReturn({
    required this.periodKey,
    required this.start,
    required this.end,
    required this.boxes,
    required this.warnings,
    required this.eventsInPeriod,
  });

  final String periodKey;
  final String start;
  final String end;
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
