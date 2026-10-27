import 'dashboard.dart';

/// Where a dashboard suggestion opens.
enum SuggestionTarget { review, invoices, bank, vat }

/// One code-built line under the to-do list, from the dashboard payload —
/// e.g. "3 receipts to review". No model call; the runtime already worked
/// out every figure.
class HomeSuggestion {
  const HomeSuggestion({required this.text, required this.target});

  final String text;
  final SuggestionTarget target;
}

/// Up to three suggestions from [dashboard], most actionable first. Pure
/// (no widgets), so the phone and the tests share it.
List<HomeSuggestion> suggestionsFor(Dashboard dashboard) {
  final out = <HomeSuggestion>[];
  final proposed = dashboard.attentionProposed ?? 0;
  final needsALook = dashboard.attentionNeedsALook ?? 0;
  final toReview = proposed + needsALook;
  if (toReview > 0) {
    out.add(HomeSuggestion(
      text: '$toReview ${toReview == 1 ? 'receipt' : 'receipts'} to review',
      target: SuggestionTarget.review,
    ));
  }
  final overdue = dashboard.overdueInvoices ?? 0;
  if (overdue > 0) {
    final days = dashboard.mostOverdueDays;
    out.add(HomeSuggestion(
      text: overdue == 1
          ? '1 invoice overdue${days != null ? ' $days ${days == 1 ? 'day' : 'days'}' : ''}'
          : '$overdue invoices overdue${days != null ? ' · oldest $days days' : ''}',
      target: SuggestionTarget.invoices,
    ));
  }
  final unmatched = dashboard.attentionUnmatchedBankLines ?? 0;
  if (unmatched > 0) {
    out.add(HomeSuggestion(
      text:
          '$unmatched bank ${unmatched == 1 ? 'line' : 'lines'} to match',
      target: SuggestionTarget.bank,
    ));
  }
  if (out.length < 3 &&
      dashboard.vatDeadline != null &&
      dashboard.vatDeadline!.isNotEmpty) {
    out.add(HomeSuggestion(
      text: 'VAT due ${shortDate(dashboard.vatDeadline)}',
      target: SuggestionTarget.vat,
    ));
  }
  return out.take(3).toList();
}
