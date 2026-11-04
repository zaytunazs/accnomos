import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:accnomos_mobile/models/dashboard.dart';
import 'package:accnomos_mobile/models/goals.dart';
import 'package:accnomos_mobile/models/reports.dart' as reports;
import 'package:accnomos_mobile/models/vat_return.dart';
import 'package:accnomos_mobile/screens/bank_screen.dart';
import 'package:accnomos_mobile/screens/contacts_screen.dart';
import 'package:accnomos_mobile/screens/home_screen.dart';
import 'package:accnomos_mobile/screens/invoices_screen.dart';
import 'package:accnomos_mobile/screens/vat_screen.dart';
import 'package:accnomos_mobile/screens/vehicles_screen.dart';
import 'package:accnomos_mobile/services/books.dart';
import 'package:accnomos_mobile/services/money.dart';
import 'package:accnomos_mobile/widgets/tile_grid.dart';

VatReturn _vat(String b3, String b4, String b5) => VatReturn.fromJson({
      'period_key': '26A3',
      'boxes': [
        {'box': 3, 'label': 'Total VAT due', 'amount': b3, 'entries': 1},
        {'box': 4, 'label': 'VAT reclaimed', 'amount': b4, 'entries': 1},
        {'box': 5, 'label': 'Net VAT to pay HMRC (3 − 4)', 'amount': b5, 'entries': 2},
        {'box': 6, 'label': 'Total sales excluding VAT', 'amount': '19288', 'entries': 9},
      ],
    });

void main() {
  group('one money formatter', () {
    test('thousands, pence, and a leading minus', () {
      expect(formatMoneyPence(470659), '£4,706.59');
      expect(formatMoneyPence(-470659), '-£4,706.59');
      expect(formatMoneyPence(0), '£0.00');
      expect(formatMoneyPence(5), '£0.05');
      expect(formatMoneyPence(123456789), '£1,234,567.89');
      expect(formatMoneyPence(-1), '-£0.01');
      expect(formatMoneyPence(1928899, whole: true), '£19,288');
      expect(formatMoneyPence(1928899, whole: true, round: true), '£19,289');
      expect(formatMoneyPounds('3807.33'), '£3,807.33');
      expect(formatMoneyPounds('-21'), '-£21.00');
    });

    test('every screen helper uses it', () {
      expect(gbp(517758), '£5,177.58');
      expect(gbp(-470659), '-£4,706.59');
      expect(reports.gbp(268400), '£2,684.00');
      expect(money(159400), '£1,594.00');
      expect(moneyShort(-1795000), '-£17,950');
      expect(poundsFromPence(1795000), '£17,950');
      expect(formatPounds('19288', whole: true), '£19,288');
      expect(formatPounds('3807.33'), '£3,807.33');
    });
  });

  group('VAT box 5', () {
    test('a reclaim says HMRC owes you, never "to pay"', () {
      final vat = _vat('0.00', '21.00', '21.00');
      final five = vat.boxes.firstWhere((b) => b.box == 5);
      expect(vat.isRefund, isTrue);
      expect(vat.labelFor(five), 'Net VAT HMRC owes you (4 − 3)');
      expect(vat.displayFor(five), '£21.00');
    });

    test('a negative box 5 is a refund shown as a positive figure', () {
      final vat = _vat('10.00', '31.00', '-21.00');
      final five = vat.boxes.firstWhere((b) => b.box == 5);
      expect(vat.labelFor(five), contains('owes you'));
      expect(vat.displayFor(five), '£21.00');
    });

    test('a payment keeps the HMRC label', () {
      final vat = _vat('3900.00', '92.67', '3807.33');
      final five = vat.boxes.firstWhere((b) => b.box == 5);
      expect(vat.isRefund, isFalse);
      expect(vat.labelFor(five), 'Net VAT to pay HMRC (3 − 4)');
      expect(vat.displayFor(five), '£3,807.33');
      final six = vat.boxes.firstWhere((b) => b.box == 6);
      expect(vat.displayFor(six), '£19,288');
    });

    test('the tab opens on the period that is due next', () {
      final periods = [
        VatPeriod(period: '2026-Q4', label: 'Oct–Dec 2026', status: 'open', current: true, start: '2026-10-01'),
        VatPeriod(period: '2026-Q3', label: 'Jul–Sep 2026', status: 'open', current: false, start: '2026-07-01'),
        VatPeriod(period: '2026-Q2', label: 'Apr–Jun 2026', status: 'submitted', current: false, start: '2026-04-01'),
      ];
      expect(vatDuePeriod(const {}, periods), '2026-Q3');
      expect(vatDuePeriod(const {'due_period': '2026-Q4'}, periods), '2026-Q4');
      expect(vatDuePeriod(const {'due_period': 'nope'}, periods), '2026-Q3');
      expect(vatDuePeriod(const {}, [periods.first]), isNull);
      // `/books/vat` sends the hint as a map; the periods list as an id
      expect(vatDuePeriod(const {'due_period': {'period': '2026-Q4', 'label': 'Oct–Dec 2026'}}, periods), '2026-Q4');
      // every earlier period open with nothing in it (books that started this year): the one just before the
      // current period is due next, not Jan–Mar of last year
      final young = [
        ...periods.take(2),
        VatPeriod(period: '2026-Q2', label: 'Apr–Jun 2026', status: 'open', current: false, start: '2026-04-01'),
        VatPeriod(period: '2025-Q1', label: 'Jan–Mar 2025', status: 'open', current: false, start: '2025-01-01'),
      ];
      expect(vatDuePeriod(const {}, young), '2026-Q3');
    });
  });

  group('lists', () {
    test('invoice status lines: overdue, part paid, paid', () {
      expect(
          invoiceStatusLine({
            'status': 'sent',
            'due_date': '2026-08-24',
            'days_overdue': 75,
            'money': {'payment_status': 'open', 'balance_pence': 525960},
          }),
          'Overdue 75 days · due 24 Aug 2026');
      expect(
          invoiceStatusLine({
            'status': 'sent',
            'due_date': '2026-12-01',
            'days_overdue': 0,
            'money': {'payment_status': 'part_paid', 'balance_pence': 60000},
          }),
          'Sent · part paid, £600.00 left of £0.00 · due 1 Dec 2026');
      expect(
          invoiceStatusLine({
            'status': 'sent',
            'days_overdue': 10,
            'money': {'payment_status': 'paid', 'balance_pence': 0},
          }),
          'Paid');
      expect(invoiceStatusLine({'status': 'draft'}), 'Draft');
      // INV-0006: £1,057.68 invoiced, £318 paid → £739.68 owed is shown.
      final inv6 = {
        'status': 'sent',
        'total_pence': 105768,
        'balance_pence': 73968,
        'payment_status': 'part_paid',
        'days_overdue': 0,
        'due_date': '2026-11-20',
      };
      expect(invoiceShownPence(inv6), 73968);
      expect(invoiceStatusLine(inv6),
          'Sent · part paid, £739.68 left of £1,057.68 · due 20 Nov 2026');
      expect(invoiceShownPence({'status': 'draft', 'total_pence': 5000, 'balance_pence': 0}), 5000);
      expect(invoiceShownPence({'status': 'sent', 'total_pence': 5000, 'money': {'balance_pence': 1200}}), 1200);
      expect(invoiceOverdue({'status': 'sent', 'days_overdue': 3}), isTrue);
      expect(invoiceOverdue({'status': 'draft', 'days_overdue': 3}), isFalse);
    });

    test('bank: open lines by the server definition', () {
      expect(bankLineIsOpen({'status': 'unmatched'}), isTrue);
      expect(bankLineIsOpen({'status': 'suggested'}), isTrue);
      expect(bankLineIsOpen({'status': 'matched'}), isFalse);
      expect(bankLineIsOpen({'status': 'transfer'}), isFalse);
      expect(bankLineIsOpen({'status': 'ignored'}), isFalse);
      // Personal books: the household category decides, not ledger matching.
      expect(bankLineIsOpen({'status': 'unmatched', 'household_sorted': true}), isFalse);
      expect(bankLineIsOpen({'status': 'unmatched', 'household_sorted': false}), isTrue);
    });

    test('bank: household category per line', () {
      expect(householdCategoryLabel({'household_sorted': false, 'household_category': 'Other'}),
          'No category yet');
      expect(householdCategoryLabel({'household_sorted': true, 'household_source': 'rule', 'household_category': 'Groceries'}),
          'Groceries');
      expect(householdCategoryLabel({'household_sorted': true, 'household_source': 'hand', 'household_category': 'Car'}),
          'Car (set by you)');
      expect(householdCategoryLabel({'household_sorted': true, 'household_source': 'excluded'}),
          'Transfer / not counted');
      expect(householdCategoryLabel({'status': 'matched'}), isNull);
    });

    test('the mileage counterparty is not a supplier', () {
      expect(isSystemContact({'name': 'Mileage allowance', 'kind': 'supplier'}), isTrue);
      expect(isSystemContact({'name': 'Screwfix', 'kind': 'supplier'}), isFalse);
    });

    test('vehicles show the tax year, not just an empty quarter', () {
      expect(milesText(40.0), '40');
      expect(milesText(12.5), '12.5');
      expect(
          yearLine({
            'tax_year': '2026-27',
            'allowance_pence': 12330,
            'quarters': [
              {'miles': 200.0},
              {'miles': 74},
              {'miles': 0},
            ],
          }),
          'Tax year 2026-27 so far: £123.30 · 274 mi');
    });
  });

  testWidgets('Home tile labels wrap at 1.3x text instead of clipping',
      (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(
      home: MediaQuery(
        data: const MediaQueryData(
            size: Size(360, 740), textScaler: TextScaler.linear(1.3)),
        child: Scaffold(
          body: ListView(children: const [
            TileGrid(children: [
              HomeTile(
                  label: 'Lines with no category this month',
                  value: '12',
                  note: 'Shown as Other on the Budget tab'),
              HomeTile(label: 'Cash in bank', value: '£18,000', note: 'Balance on 2 Nov'),
            ]),
          ]),
        ),
      ),
    ));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final label = tester.widget<Text>(find.text('Lines with no category this month'));
    expect(label.maxLines, isNull); // wraps as far as it needs
    expect(label.overflow, isNot(TextOverflow.ellipsis));
    final rendered = tester.renderObject<RenderParagraph>(
        find.text('Lines with no category this month'));
    expect(rendered.didExceedMaxLines, isFalse);
  });

  test('goals dates are UK style', () {
    expect(ukDate(isoDate(DateTime(2026, 11, 3))), '3 Nov 2026');
  });
}
