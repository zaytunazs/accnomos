import 'package:msal_auth/msal_auth.dart';

import 'auth.dart';
import 'runtime_client.dart';
import 'settings.dart';

/// Shared wiring for the thin books screens (Contacts, Invoices, Jobs,
/// Vehicles). Every screen signs in the same way and formats money and dates
/// the same way; the runtime works out all totals.
Future<RuntimeClient> booksClient(
  AppSettings settings,
  AuthService auth,
  Account? account, {
  String? graphToken,
}) async {
  final token = graphToken ?? await auth.token();
  final user = account?.username ?? settings.userEmail;
  return RuntimeClient(
    settings,
    books: BooksAuth(
      graphToken: token,
      accountKind: auth.kind == AccountKind.work ? 'work' : 'personal',
      user: (user != null && user.isNotEmpty) ? user : null,
      businessName: settings.businessName,
    ),
  );
}

/// Pence to pounds, e.g. 1234 → £12.34, -50 → −£0.50.
String gbp(num pence) {
  final pounds = (pence / 100).toStringAsFixed(2);
  return pence < 0 ? '−£${pounds.substring(1)}' : '£$pounds';
}

/// ISO date to UK display, e.g. 2026-10-27 → 27 Oct 2026.
String ukDate(String iso) {
  final text = iso.trim();
  if (text.isEmpty) return '—';
  try {
    final d = DateTime.parse(text);
    const months = [
      'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
    ];
    return '${d.day} ${months[d.month - 1]} ${d.year}';
  } catch (_) {
    return text;
  }
}

/// ISO date to `YYYY-MM-DD` for runtime query bodies.
String isoDate(DateTime day) =>
    '${day.year.toString().padLeft(4, '0')}-'
    '${day.month.toString().padLeft(2, '0')}-'
    '${day.day.toString().padLeft(2, '0')}';

/// The quarter in [summary] (`GET /mileage/summary`) that holds [today],
/// or null when the summary names no quarter for it.
Map<String, dynamic>? currentQuarter(
    Map<String, dynamic> summary, DateTime today) {
  final quarters = summary['quarters'];
  if (quarters is! List) return null;
  final day = DateTime(today.year, today.month, today.day);
  for (final q in quarters) {
    if (q is! Map) continue;
    try {
      final start = DateTime.parse((q['start'] ?? '').toString());
      final end = DateTime.parse((q['end'] ?? '').toString());
      if (!day.isBefore(start) && !day.isAfter(end)) {
        return Map<String, dynamic>.from(q);
      }
    } catch (_) {
      continue;
    }
  }
  return null;
}

/// Strip `Exception: ` so runtime errors read as plain sentences.
String friendly(Object e) =>
    e.toString().replaceFirst('Exception: ', '');
