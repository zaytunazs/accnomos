import 'package:accnomos_mobile/services/home_todos.dart';
import 'package:flutter_test/flutter_test.dart';

/// The Home to-do list is built by code from the live responses (no model
/// call). These tests pin the wording and the tap targets.
void main() {
  test('a quiet day builds no to-dos', () {
    expect(
      buildHomeTodos(
        proposed: 0,
        needsALook: 0,
        overdue: const [],
        bankActionCount: 0,
        deadlineLabel: null,
        deadlineIso: null,
        deadlineDaysRemaining: null,
      ),
      isEmpty,
    );
  });

  test('review, overdue, bank and deadline rows in order', () {
    final todos = buildHomeTodos(
      proposed: 2,
      needsALook: 1,
      overdue: const [
        OverdueInvoice(number: 'INV-0041', daysOverdue: 12, totalPence: 123450),
      ],
      bankActionCount: 4,
      deadlineLabel: 'Jan 2027 quarter',
      deadlineIso: '2027-02-07',
      deadlineDaysRemaining: 12,
    );

    expect(todos.map((t) => t.title), [
      '3 receipts to review',
      'INV-0041 is 12 days overdue — send a reminder',
      'Match 4 bank lines',
      'VAT return due 7 Feb 2027',
    ]);
    expect(todos.map((t) => t.target), [
      HomeTodoTarget.review,
      HomeTodoTarget.invoices,
      HomeTodoTarget.bank,
      HomeTodoTarget.vat,
    ]);
    // Money is pence from the runtime, formatted by the shared helper.
    expect(todos[1].detail, contains('£1234.50'));
  });

  test('singular wording and an overdue deadline', () {
    final todos = buildHomeTodos(
      proposed: 1,
      needsALook: 0,
      overdue: const [],
      bankActionCount: 1,
      deadlineLabel: 'Dec quarter',
      deadlineIso: '2026-11-07',
      deadlineDaysRemaining: -3,
    );

    expect(todos[0].title, '1 receipt to review');
    expect(todos[1].title, 'Match 1 bank line');
    expect(todos[2].title, 'VAT return was due 7 Nov 2026');
    expect(todos[2].detail, contains('3 days overdue'));
  });

  test('a far-off deadline is not a to-do', () {
    final todos = buildHomeTodos(
      proposed: 0,
      needsALook: 0,
      overdue: const [],
      bankActionCount: 0,
      deadlineLabel: 'Jun quarter',
      deadlineIso: '2026-08-07',
      deadlineDaysRemaining: 90,
    );
    expect(todos, isEmpty);
  });
}
