/// Read-back for spoken requests: the figure a card will act on, in words,
/// so a mis-heard number ("fourteen" for "forty") is caught before Approve.
/// The same rules as the web app's `apps/web/src/lib/readback.ts`.
library;

const _ones = [
  'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', //
  'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen',
  'sixteen', 'seventeen', 'eighteen', 'nineteen',
];
const _tens = [
  '', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', //
  'eighty', 'ninety',
];

String _under1000(int n) {
  final h = n ~/ 100;
  final r = n % 100;
  final rest = r < 20
      ? _ones[r]
      : _tens[r ~/ 10] + (r % 10 != 0 ? '-${_ones[r % 10]}' : '');
  if (h == 0) return rest;
  return '${_ones[h]} hundred${r != 0 ? ' and $rest' : ''}';
}

/// A whole number in British English words: 1405 -> "one thousand, four
/// hundred and five".
String wholeInWords(int n) {
  if (n < 0) return 'minus ${wholeInWords(-n)}';
  if (n < 1000) return _under1000(n);
  final parts = <String>[];
  for (final (size, name) in const [
    (1000000000, 'billion'),
    (1000000, 'million'),
    (1000, 'thousand'),
  ]) {
    if (n >= size) {
      parts.add('${_under1000((n ~/ size) % 1000)} $name');
      n %= size;
    }
  }
  if (n != 0) parts.add(n < 100 ? 'and ${_under1000(n)}' : _under1000(n));
  return parts.join(', ').replaceFirst(', and ', ' and ');
}

/// 4050 -> "forty pounds and fifty pence"; 100 -> "one pound".
String penceInWords(int pence) {
  final sign = pence < 0 ? 'minus ' : '';
  final abs = pence.abs();
  final pounds = abs ~/ 100;
  final p = abs % 100;
  final lb = pounds != 0
      ? '${wholeInWords(pounds)} pound${pounds == 1 ? '' : 's'}'
      : '';
  final pc = p != 0 ? '${wholeInWords(p)} pence' : '';
  final body = lb.isNotEmpty && pc.isNotEmpty
      ? '$lb and $pc'
      : (lb.isNotEmpty ? lb : (pc.isNotEmpty ? pc : 'zero pounds'));
  return sign + body;
}

/// "12.5" -> "twelve point five"; "3.00" -> "three".
String quantityInWords(String q) {
  final m = RegExp(r'^(-?)(\d+)(?:\.(\d+))?$').firstMatch(q.trim());
  if (m == null) return q;
  final whole =
      '${m.group(1)!.isNotEmpty ? 'minus ' : ''}${wholeInWords(int.parse(m.group(2)!))}';
  final frac = (m.group(3) ?? '').replaceFirst(RegExp(r'0+$'), '');
  if (frac.isEmpty) return whole;
  return '$whole point ${frac.split('').map((d) => _ones[int.parse(d)]).join(' ')}';
}

class ReadBackLine {
  const ReadBackLine(this.label, this.figure, this.words);
  final String label;
  final String figure;
  final String words;
}

String _gbp(int pence) {
  final abs = pence.abs();
  final pounds = (abs ~/ 100).toString().replaceAllMapped(
    RegExp(r'\B(?=(\d{3})+(?!\d))'),
    (_) => ',',
  );
  return '${pence < 0 ? '-' : ''}£$pounds.${(abs % 100).toString().padLeft(2, '0')}';
}

List<ReadBackLine> _money(String label, Object? pence) => pence is num
    ? [ReadBackLine(label, _gbp(pence.round()), penceInWords(pence.round()))]
    : const [];

List<ReadBackLine> _qty(String label, Object? value, String unit) {
  if (value is! String && value is! num) return const [];
  final s = value.toString();
  final n = num.tryParse(s);
  if (n == null) return const [];
  final u = n == 1 ? unit : '${unit}s';
  return [ReadBackLine(label, '$s $u', '${quantityInWords(s)} $u')];
}

/// The text of the check box on a spoken card: what was heard, then each
/// figure with its words.
String spokenReadBack(String heard, List<ReadBackLine> lines) => [
  'Check the figures: speech gets numbers wrong more often than words.',
  if (heard.trim().isNotEmpty) 'We heard: “${heard.trim()}”',
  for (final l in lines) '${l.label}: ${l.figure} (${l.words})',
  'Not what you said? Reject it and type it instead.',
].join('\n');

/// The figures to read back for one proposed action; empty when the card
/// carries no figure a voice could mis-hear.
List<ReadBackLine> readBack(String kind, Map<String, dynamic> preview) {
  switch (kind) {
    case 'create_invoice':
    case 'create_quote':
    case 'convert_quote_to_invoice':
      final lines = preview['lines'];
      final each = lines is List && lines.length == 1 && lines.first is Map
          ? _money('Price each', (lines.first as Map)['unit_price_pence'])
          : const <ReadBackLine>[];
      return [...each, ..._money('Total', preview['total_pence'])];
    case 'chase_invoice':
      return _money('Owed', preview['total_pence']);
    case 'match_bank_line':
      return _money('Amount', preview['amount_pence']);
    case 'log_mileage':
      return _qty('Distance', preview['miles'], 'mile');
    case 'log_timesheet':
      return _qty('Time', preview['hours'], 'hour');
    case 'pay_overtime':
      return [
        ..._qty('Time', preview['hours'], 'hour'),
        ..._money('Extra pay', preview['extra_pence']),
      ];
    default:
      return const [];
  }
}
