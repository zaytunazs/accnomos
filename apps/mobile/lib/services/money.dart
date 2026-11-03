/// One money formatter for the whole app: `£1,234.56`, thousands separated,
/// a leading minus before the pound sign for negatives (`-£4,706.59`, never
/// `£-…`). [whole] drops the pence; [round] rounds to whole pounds instead of
/// truncating (VAT boxes 6–9 truncate, tiles round).
String formatMoneyPence(num pence, {bool whole = false, bool round = false}) {
  final negative = pence < 0;
  var p = pence.abs();
  int units;
  if (whole) {
    units = round ? (p / 100).round() : (p ~/ 100);
  } else {
    units = p.round();
  }
  final pounds = whole ? units : units ~/ 100;
  final grouped = pounds
      .toString()
      .replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (_) => ',');
  final tail = whole ? '' : '.${(units % 100).toString().padLeft(2, '0')}';
  final text = '£$grouped$tail';
  return negative && (whole ? units != 0 : units != 0) ? '-$text' : text;
}

/// The same, from a pounds number or string ("1234.5", 1234.5).
String formatMoneyPounds(Object? amount, {bool whole = false, bool round = false}) {
  final n = num.tryParse('${amount ?? 0}') ?? 0;
  return formatMoneyPence(n * 100, whole: whole, round: round);
}
