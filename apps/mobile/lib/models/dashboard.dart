/// `GET /books/dashboard` (services/runtime/app/dashboard.py), as the Home
/// tiles need it. Money is integer pence; a null figure is unknown and shows
/// as "—".
class Dashboard {
  Dashboard({
    required this.cashPence,
    required this.cashAsOf,
    required this.owedToYouPence,
    required this.overdueInvoices,
    required this.mostOverdueDays,
    required this.owedByYouPence,
    required this.vatLabel,
    required this.vatBox5,
    required this.vatDirection,
    required this.vatDeadline,
    required this.attentionTotal,
    required this.attentionProposed,
    required this.attentionNeedsALook,
    required this.attentionUnmatchedBankLines,
  });

  final int? cashPence;
  final String? cashAsOf;
  final int? owedToYouPence;
  final int? overdueInvoices;

  /// Age in days of the most overdue invoice, if the runtime worked it out.
  final int? mostOverdueDays;
  final int? owedByYouPence;
  final String? vatLabel;

  /// Pounds, 2 dp, absolute (as HMRC takes it).
  final String? vatBox5;

  /// `pay`, `reclaim` or `nil`.
  final String? vatDirection;
  final String? vatDeadline;
  final int? attentionTotal;

  /// Proposed entries waiting in Review.
  final int? attentionProposed;

  /// Entries the reader could not file on its own.
  final int? attentionNeedsALook;

  /// Open bank lines: not matched, a transfer or ignored.
  final int? attentionUnmatchedBankLines;

  static Map<String, dynamic>? _map(Object? v) =>
      v is Map<String, dynamic> ? v : null;

  static int? _int(Object? v) => v is num ? v.toInt() : null;

  factory Dashboard.fromJson(Map<String, dynamic> json) {
    final cash = _map(json['cash']);
    final owedTo = _map(json['owed_to_you']);
    final owedBy = _map(json['owed_by_you']);
    final vat = _map(json['vat']);
    // The return to file next: the period that has ended, else the current one.
    final next = _map(vat?['due']) ?? _map(vat?['current']);
    final attention = _map(json['attention']);
    return Dashboard(
      cashPence: _int(cash?['balance_pence']),
      cashAsOf: cash?['as_of'] as String?,
      owedToYouPence: _int(owedTo?['total_pence']),
      overdueInvoices: _int(owedTo?['overdue']),
      mostOverdueDays: _int(owedTo?['most_overdue_days']),
      owedByYouPence: _int(owedBy?['total_pence']),
      vatLabel: next?['label'] as String?,
      vatBox5: next?['box5'] as String?,
      vatDirection: next?['box5_direction'] as String?,
      vatDeadline: next?['deadline'] as String?,
      attentionTotal: _int(attention?['total']),
      attentionProposed: _int(attention?['proposed']),
      attentionNeedsALook: _int(attention?['needs_a_look']),
      attentionUnmatchedBankLines:
          _int(attention?['unmatched_bank_lines']),
    );
  }
}

/// "£12,480" from pence (whole pounds, as the tiles show them); "—" if null.
String poundsFromPence(int? pence) {
  if (pence == null) return '—';
  final whole = (pence.abs() / 100).round().toString();
  final grouped = whole.replaceAllMapped(
      RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]},');
  return '${pence < 0 ? '-' : ''}£$grouped';
}

/// "24 Oct" from "2026-10-24"; "—" if null.
String shortDate(String? iso) {
  if (iso == null || iso.length < 10) return '—';
  const months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];
  final month = int.tryParse(iso.substring(5, 7)) ?? 0;
  final day = int.tryParse(iso.substring(8, 10)) ?? 0;
  if (month < 1 || month > 12) return '—';
  return '$day ${months[month - 1]}';
}
