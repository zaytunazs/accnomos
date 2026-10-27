import 'proposal_editing.dart';

/// The Home tab's to-do list, built by code from the same live responses
/// as the tiles. No model call: every row comes from counts and dates the
/// runtime already worked out.
///
/// Kept free of Flutter so `flutter test` covers the wording. Screens map
/// [HomeTodo.target] to the screen they push.
enum HomeTodoTarget { review, invoices, bank, vat }

class HomeTodo {
  const HomeTodo({
    required this.title,
    required this.detail,
    required this.target,
  });

  final String title;
  final String detail;
  final HomeTodoTarget target;
}

/// An unpaid sales invoice past its due date, as `GET /invoices` returns
/// it: `days_overdue` is worked out by the runtime, money is pence.
class OverdueInvoice {
  const OverdueInvoice({
    required this.number,
    required this.daysOverdue,
    required this.totalPence,
  });

  final String number;
  final int daysOverdue;
  final int totalPence;
}

/// Build the to-do rows, most urgent first: review queue, overdue sales
/// invoices (most overdue first), bank lines, then a VAT deadline due
/// within 30 days (or already past it). A quiet day returns no rows.
List<HomeTodo> buildHomeTodos({
  required int proposed,
  required int needsALook,
  required List<OverdueInvoice> overdue,
  required int bankActionCount,
  required String? deadlineLabel,
  required String? deadlineIso,
  required int? deadlineDaysRemaining,
}) {
  final todos = <HomeTodo>[];

  final waiting = proposed + needsALook;
  if (waiting > 0) {
    todos.add(HomeTodo(
      title: '$waiting receipt${waiting == 1 ? '' : 's'} to review',
      detail: _reviewDetail(proposed, needsALook),
      target: HomeTodoTarget.review,
    ));
  }

  final sorted = List.of(overdue)
    ..sort((a, b) => b.daysOverdue.compareTo(a.daysOverdue));
  for (final inv in sorted) {
    todos.add(HomeTodo(
      title:
          '${inv.number} is ${inv.daysOverdue} day${inv.daysOverdue == 1 ? '' : 's'} overdue — send a reminder',
      detail: '${formatPence(inv.totalPence)} owed · reminders go from the web app',
      target: HomeTodoTarget.invoices,
    ));
  }

  if (bankActionCount > 0) {
    todos.add(HomeTodo(
      title:
          'Match $bankActionCount bank line${bankActionCount == 1 ? '' : 's'}',
      detail: 'Confirm the suggested matches',
      target: HomeTodoTarget.bank,
    ));
  }

  if (deadlineIso != null && deadlineDaysRemaining != null) {
    final days = deadlineDaysRemaining;
    if (days <= 30) {
      final date = _ukDate(deadlineIso);
      final label =
          deadlineLabel == null || deadlineLabel.isEmpty ? '' : ' · $deadlineLabel';
      if (days < 0) {
        todos.add(HomeTodo(
          title: 'VAT return was due $date',
          detail:
              '${-days} day${days == -1 ? '' : 's'} overdue$label · open the VAT return',
          target: HomeTodoTarget.vat,
        ));
      } else if (days == 0) {
        todos.add(HomeTodo(
          title: 'VAT return is due today',
          detail: 'Due $date$label · open the VAT return',
          target: HomeTodoTarget.vat,
        ));
      } else {
        todos.add(HomeTodo(
          title: 'VAT return due $date',
          detail:
              'In $days day${days == 1 ? '' : 's'}$label · open the VAT return',
          target: HomeTodoTarget.vat,
        ));
      }
    }
  }

  return todos;
}

String _reviewDetail(int proposed, int needsALook) {
  final parts = <String>[];
  if (proposed > 0) {
    parts.add('$proposed proposed');
  }
  if (needsALook > 0) {
    parts.add('$needsALook need${needsALook == 1 ? 's' : ''} a look');
  }
  final summary = parts.join(' · ');
  return summary.isEmpty ? 'Open the review queue' : '$summary · open Review';
}

/// `2027-02-07` → `7 Feb 2027` in UK order, or the raw text when unknown.
String _ukDate(String iso) {
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
