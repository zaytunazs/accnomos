import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:accnomos_mobile/screens/payments_sheets.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';

/// Every payment sheet at 360 dp: it opens, it fits, the happy path hands
/// the runtime's answer back, and a refusal shows the runtime's sentence
/// with the sheet still open.
void main() {
  Future<void> setNarrow(WidgetTester tester) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1.0;
  }

  Future<void> resetSize(WidgetTester tester) async {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  }

  test('pounds parsing matches the web amount inputs', () {
    expect(parsePoundsToPence('120.50'), 12050);
    expect(parsePoundsToPence('120'), 12000);
    expect(parsePoundsToPence('£1,200.5'), 120050);
    expect(parsePoundsToPence(' 12.34 '), 1234);
    expect(parsePoundsToPence(''), isNull);
    expect(parsePoundsToPence('abc'), isNull);
    expect(parsePoundsToPence('12.345'), isNull);
    expect(parsePoundsToPence('-5'), isNull);
    expect(parsePoundsToPence('0'), isNull);
    expect(poundsInput(12050), '120.50');
  });

  testWidgets('record payment: balance pre-fills, confirm records, no overflow',
      (tester) async {
    await setNarrow(tester);
    int? seenPence;
    String? seenAccount;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => FilledButton(
              onPressed: () => showRecordPaymentSheet(
                context: context,
                invoiceNumber: 'INV-2041',
                balancePence: 21240,
                record: ({
                  required amountPence,
                  required paidOn,
                  required account,
                  paymentRef,
                }) async {
                  seenPence = amountPence;
                  seenAccount = account;
                  return {'number': 'INV-2041'};
                },
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    expect(find.text('Record payment on INV-2041'), findsOneWidget);
    expect(find.text('212.40'), findsOneWidget);

    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();
    expect(find.text('Record payment on INV-2041?'), findsOneWidget);
    expect(find.text('£212.40'), findsWidgets);

    await tester.tap(find.text('Record payment').last);
    await tester.pumpAndSettle();
    expect(seenPence, 21240);
    expect(seenAccount, '1200 Bank');
    expect(find.text('Record payment on INV-2041'), findsNothing);
    expect(tester.takeException(), isNull);
    await resetSize(tester);
  });

  testWidgets('record payment refusal shows the runtime sentence',
      (tester) async {
    await setNarrow(tester);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => FilledButton(
              onPressed: () => showRecordPaymentSheet(
                context: context,
                invoiceNumber: 'INV-1',
                balancePence: 100,
                record: ({
                  required amountPence,
                  required paidOn,
                  required account,
                  paymentRef,
                }) async {
                  throw RuntimeException(
                      'The reader refused that request (status 409). INV-1 is already paid');
                },
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Record payment').last);
    await tester.pumpAndSettle();
    expect(find.textContaining('INV-1 is already paid'), findsOneWidget);
    expect(find.text('Record payment on INV-1?'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await resetSize(tester);
  });

  testWidgets('create credit note: whole invoice posts confirm', (tester) async {
    await setNarrow(tester);
    String? seenReason;
    List<Map<String, String>>? seenLines;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => FilledButton(
              onPressed: () => showCreateCreditNoteSheet(
                context: context,
                invoiceNumber: 'INV-1',
                lines: [
                  {'description': 'Labour', 'quantity': '2'},
                  {'description': 'Parts', 'quantity': '1'},
                ],
                create: ({
                  required reason,
                  issueDate,
                  creditLines,
                }) async {
                  seenReason = reason;
                  seenLines = creditLines;
                  return {'number': 'CN-0001'};
                },
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    expect(find.text('Create credit note'), findsWidgets);

    await tester.enterText(find.byType(TextField).first, 'Returned goods');
    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();
    expect(find.text('Create credit note for INV-1?'), findsOneWidget);

    await tester.tap(find.text('Create credit note').last);
    await tester.pumpAndSettle();
    expect(seenReason, 'Returned goods');
    expect(seenLines, isNull);
    expect(find.text('Create credit note for INV-1?'), findsNothing);
    expect(tester.takeException(), isNull);
    await resetSize(tester);
  });

  testWidgets('create credit note: chosen lines send line and quantity',
      (tester) async {
    await setNarrow(tester);
    List<Map<String, String>>? seenLines;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => FilledButton(
              onPressed: () => showCreateCreditNoteSheet(
                context: context,
                invoiceNumber: 'INV-1',
                lines: [
                  {'description': 'Labour', 'quantity': '2'},
                  {'description': 'Parts', 'quantity': '1'},
                ],
                create: ({
                  required reason,
                  issueDate,
                  creditLines,
                }) async {
                  seenLines = creditLines;
                  return {'number': 'CN-0002'};
                },
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Chosen lines'));
    await tester.pumpAndSettle();
    expect(find.text('Labour'), findsOneWidget);
    final reasonField = find.byWidgetPredicate(
      (widget) =>
          widget is TextField &&
          widget.decoration?.labelText == 'Reason',
    );
    await tester.enterText(reasonField, 'Short delivery');
    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Create credit note').last);
    await tester.pumpAndSettle();
    expect(
      seenLines,
      [
        {'line': '1', 'quantity': '2'},
        {'line': '2', 'quantity': '1'},
      ],
    );
    expect(tester.takeException(), isNull);
    await resetSize(tester);
  });

  testWidgets('apply credit: pick a bill, confirm applies, no overflow',
      (tester) async {
    await setNarrow(tester);
    String? seenCredit;
    String? seenEvent;
    const credits = [
      {
        'id': 'payment:abc',
        'side': 'purchase',
        'date': '2026-10-20',
        'amount_pence': 5000,
        'source': 'payment',
        'reference': 'BILL-3',
      },
    ];
    const docs = [
      {
        'event_id': 'abcdef01',
        'side': 'purchase',
        'date': '2026-10-01',
        'reference': 'BILL-7',
        'outstanding_pence': 3000,
      },
    ];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => FilledButton(
              onPressed: () => showApplyCreditSheet(
                context: context,
                contactName: 'Brixton Timber',
                credits: credits,
                documents: docs,
                apply: ({
                  required credit,
                  required eventId,
                  amountPence,
                  date,
                }) async {
                  seenCredit = credit;
                  seenEvent = eventId;
                  return {'id': 'use1', 'kind': 'apply'};
                },
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    expect(find.text('Apply credit for Brixton Timber'), findsOneWidget);

    await tester.tap(find.text('Invoice or bill'));
    await tester.pumpAndSettle();
    await tester.tap(find.textContaining('BILL-7').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();
    expect(find.text('Apply credit for Brixton Timber?'), findsOneWidget);

    await tester.tap(find.text('Apply credit').last);
    await tester.pumpAndSettle();
    expect(seenCredit, 'payment:abc');
    expect(seenEvent, 'abcdef01');
    expect(find.text('Apply credit for Brixton Timber?'), findsNothing);
    expect(tester.takeException(), isNull);
    await resetSize(tester);
  });

  testWidgets('refund: defaults to the full credit, confirm refunds',
      (tester) async {
    await setNarrow(tester);
    int? seenPence;
    const credits = [
      {
        'id': 'credit_note:def',
        'side': 'sale',
        'date': '2026-10-20',
        'amount_pence': 2500,
        'source': 'credit_note',
        'reference': 'CN-0001',
      },
    ];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => FilledButton(
              onPressed: () => showRefundSheet(
                context: context,
                contactName: 'Peckham Bakery',
                credits: credits,
                refund: ({
                  required credit,
                  required amountPence,
                  required date,
                  required account,
                  reference,
                }) async {
                  seenPence = amountPence;
                  return {'id': 'use2', 'kind': 'refund'};
                },
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    expect(find.text('25.00'), findsOneWidget);

    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Refund').last);
    await tester.pumpAndSettle();
    expect(seenPence, 2500);
    expect(find.text('Refund credit for Peckham Bakery?'), findsNothing);
    expect(tester.takeException(), isNull);
    await resetSize(tester);
  });

  testWidgets('bill payment: posts the split for the open bill',
      (tester) async {
    await setNarrow(tester);
    Map<String, dynamic>? seenBody;
    const bill = {
      'event_id': 'abcdef01',
      'side': 'purchase',
      'date': '2026-10-01',
      'reference': 'BILL-9',
      'outstanding_pence': 48210,
    };
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => FilledButton(
              onPressed: () => showRecordBillPaymentSheet(
                context: context,
                openDoc: bill,
                record: (body) async {
                  seenBody = body;
                  return {'id': 'pay1'};
                },
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    expect(find.text('Pay BILL-9'), findsOneWidget);
    expect(find.text('482.10'), findsOneWidget);

    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Record payment').last);
    await tester.pumpAndSettle();
    expect(seenBody?['side'], 'purchase');
    expect(seenBody?['amount_pence'], 48210);
    expect(
      seenBody?['allocations'],
      [
        {'event_id': 'abcdef01', 'amount_pence': 48210}
      ],
    );
    expect(find.text('Pay BILL-9?'), findsNothing);
    expect(tester.takeException(), isNull);
    await resetSize(tester);
  });

  testWidgets('confirm sheet Back cancels without calling', (tester) async {
    await setNarrow(tester);
    var called = false;
    var confirmed = false;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => FilledButton(
              onPressed: () async {
                confirmed = await showConfirmSheet(
                  context: context,
                  title: 'Remove this payment?',
                  figures: const [ConfirmFigure('Amount', '£10.00')],
                  confirmLabel: 'Remove',
                  action: () async {
                    called = true;
                  },
                );
              },
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Back'));
    await tester.pumpAndSettle();
    expect(confirmed, isFalse);
    expect(called, isFalse);
    expect(tester.takeException(), isNull);
    await resetSize(tester);
  });
}
