/// Pure helpers behind the Review edit sheet.
///
/// Kept free of Flutter so `flutter test` can cover the money and VAT
/// checks. All money maths happens in integer pence to dodge float drift.
///
/// Runtime contract (see `services/runtime/app/routes_books.py`): there is
/// no dedicated edit endpoint. Edits travel inside
/// `POST /books/proposals/{id}/approve` as the `edits` map, whose keys are
/// limited to `DOC_EDITS` in `services/runtime/app/approve.py` —
/// `category`, `net_total`, `vat_total`, `gross_total`, `date`,
/// `supplier_name`, `doc_type`, `payment_method` (plus `account`). The VAT
/// code below is therefore validated locally only and never sent.
library;

/// VAT codes offered by the edit sheet.
const List<String> kVatCodes = ['S', 'R', 'Z', 'E', 'O', 'N'];

/// Expected VAT rate per code: S standard 20 %, R reduced 5 %,
/// Z/E/O/N carry no VAT.
double vatRateForCode(String code) {
  switch (code.toUpperCase()) {
    case 'S':
      return 0.20;
    case 'R':
      return 0.05;
    default:
      return 0.0;
  }
}

/// Categories the runtime accepts (`CATEGORIES` in
/// `services/runtime/app/schemas.py`; anything else is rejected at approve).
const List<String> kCategories = [
  'Tools & small equipment',
  'Materials',
  'Office supplies',
  'Motor expenses',
  'Travel',
  'Subsistence',
  'Software & subscriptions',
  'Telephone & internet',
  'Rent',
  'Utilities',
  'Insurance',
  'Professional fees',
  'Advertising',
  'Postage',
  'Bank charges',
  'Sales',
  'Sundry',
];

/// Parse a pounds string ('£12.34', '12,34', ' 7 ') to integer pence.
/// Returns null when the text is not a non-negative amount.
int? parsePoundsToPence(String text) {
  var cleaned = text.trim().replaceAll('£', '').replaceAll(',', '').replaceAll(' ', '');
  if (cleaned.isEmpty) return null;
  final value = double.tryParse(cleaned);
  if (value == null || value.isNaN || value.isInfinite || value < 0) {
    return null;
  }
  return (value * 100).round();
}

/// Format integer pence as pounds ('£12.34').
String formatPence(int pence) => '£${(pence / 100).toStringAsFixed(2)}';

/// Returns a discrepancy line when net + VAT != gross, else null.
String? totalsDiscrepancy({
  required int netPence,
  required int vatPence,
  required int grossPence,
}) {
  final diff = netPence + vatPence - grossPence;
  if (diff == 0) return null;
  final direction = diff > 0 ? 'over' : 'short';
  return 'Net + VAT (${formatPence(netPence + vatPence)}) does not match '
      'gross (${formatPence(grossPence)}) — ${formatPence(diff.abs())} $direction.';
}

/// Returns a discrepancy line when the VAT amount does not fit the code's
/// rate, else null. Allows 1p of rounding (receipts often round per line).
String? vatRateDiscrepancy({
  required String code,
  required int netPence,
  required int vatPence,
}) {
  final expected = (netPence * vatRateForCode(code)).round();
  final diff = (vatPence - expected).abs();
  if (diff <= 1) return null;
  final rateLabel = _rateLabel(code);
  return 'VAT looks off for code $code ($rateLabel): expected about '
      '${formatPence(expected)}, entered ${formatPence(vatPence)}.';
}

String _rateLabel(String code) {
  switch (code.toUpperCase()) {
    case 'S':
      return '20%';
    case 'R':
      return '5%';
    default:
      return '0%';
  }
}

/// Guess the most likely VAT code from net and VAT. Falls back to 'S'.
String inferVatCode({required int netPence, required int vatPence}) {
  if (netPence <= 0) return 'S';
  if (vatPence <= 1) return 'Z';
  final ratio = vatPence / netPence;
  if ((ratio - 0.20).abs() <= 0.015) return 'S';
  if ((ratio - 0.05).abs() <= 0.01) return 'R';
  return 'S';
}

/// A UK VAT registration number is 9 digits. Format check only — no lookup.
/// Accepts an optional 'GB' prefix and spaces ('GB 123 4567 89').
bool isValidVrn(String text) {
  var cleaned = text.trim().toUpperCase().replaceAll(RegExp(r'\s+'), '');
  if (cleaned.startsWith('GB')) cleaned = cleaned.substring(2);
  return RegExp(r'^\d{9}$').hasMatch(cleaned);
}

/// Returns an error line for an invalid non-empty VRN, else null.
/// Empty means 'no VAT number', which is allowed.
String? vrnError(String text) {
  if (text.trim().isEmpty) return null;
  if (isValidVrn(text)) return null;
  return 'That does not look like a UK VAT number — 9 digits, e.g. 123456789.';
}

/// Build the `edits` map for `POST .../approve`, containing only fields
/// that changed. Keys match the runtime's `DOC_EDITS`; the VAT code is
/// deliberately absent (the runtime has no such field).
Map<String, dynamic> buildEdits({
  required String initialSupplier,
  required String currentSupplier,
  required String? initialDateIso,
  required String? currentDateIso,
  required bool dateTouched,
  required double? initialNet,
  required double? currentNet,
  required double? initialVat,
  required double? currentVat,
  required double? initialGross,
  required double? currentGross,
  required String initialCategory,
  required String currentCategory,
}) {
  final edits = <String, dynamic>{};
  final supplier = currentSupplier.trim();
  if (supplier.isNotEmpty && supplier != initialSupplier) {
    edits['supplier_name'] = supplier;
  }
  if (dateTouched && currentDateIso != null && currentDateIso != initialDateIso) {
    edits['date'] = currentDateIso;
  }
  if (currentNet != null && currentNet != initialNet) {
    edits['net_total'] = currentNet;
  }
  if (currentVat != null && currentVat != initialVat) {
    edits['vat_total'] = currentVat;
  }
  if (currentGross != null && currentGross != initialGross) {
    edits['gross_total'] = currentGross;
  }
  if (currentCategory.isNotEmpty && currentCategory != initialCategory) {
    edits['category'] = currentCategory;
  }
  return edits;
}

/// Format a [DateTime] as the runtime's ISO date ('YYYY-MM-DD').
String formatIsoDate(DateTime date) =>
    '${date.year.toString().padLeft(4, '0')}-'
    '${date.month.toString().padLeft(2, '0')}-'
    '${date.day.toString().padLeft(2, '0')}';

const _months = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

/// Format a [DateTime] the way proposal cards show it ('21 Oct 2026').
String formatDisplayDate(DateTime date) =>
    '${date.day} ${_months[date.month - 1]} ${date.year}';

/// Parse back either an ISO date or a card display date ('21 Oct 2026').
/// Returns null when neither parses.
DateTime? tryParseProposalDate(String text) {
  final trimmed = text.trim();
  final iso = DateTime.tryParse(trimmed);
  if (iso != null) return DateTime(iso.year, iso.month, iso.day);
  final match =
      RegExp(r'^(\d{1,2}) ([A-Za-z]{3}) (\d{4})$').firstMatch(trimmed);
  if (match == null) return null;
  final month = _months.indexWhere(
    (m) => m.toLowerCase() == match.group(2)!.toLowerCase(),
  );
  if (month < 0) return null;
  final day = int.parse(match.group(1)!);
  final year = int.parse(match.group(3)!);
  if (day < 1 || day > 31) return null;
  return DateTime(year, month + 1, day);
}
