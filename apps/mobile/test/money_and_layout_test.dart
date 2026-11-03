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
          'Sent · part paid, £600.00 left · due 1 Dec 2026');
      expect(
          invoiceStatusLine({
            'status': 'sent',
            'days_overdue': 10,
            'money': {'payment_status': 'paid', 'balance_pence': 0},
          }),
          'Paid');
      expect(invoiceStatusLine({'status': 'draft'}), 'Draft');
      expect(invoiceOverdue({'status': 'sent', 'days_overdue': 3}), isTrue);
      expect(invoiceOverdue({'status': 'draft', 'days_overdue': 3}), isFalse);
    });

    test('bank: suggested lines still need an action', () {
      expect(bankLineNeedsAction({'status': 'unmatched'}), isTrue);
      expect(bankLineNeedsAction({'status': 'suggested'}), isTrue);
      expect(bankLineNeedsAction({'status': 'matched'}), isFalse);
      expect(bankLineNeedsAction({'status': 'transfer'}), isFalse);
      expect(bankLineNeedsAction({'status': 'ignored'}), isFalse);
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
    expect(label.maxLines, greaterThan(1));
    final rendered = tester.renderObject<RenderParagraph>(
        find.text('Lines with no category this month'));
    expect(rendered.didExceedMaxLines, isFalse);
  });

  test('goals dates are UK style', () {
    expect(ukDate(isoDate(DateTime(2026, 11, 3))), '3 Nov 2026');
  });
}
