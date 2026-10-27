import 'package:accnomos_mobile/models/reports.dart';
import 'package:accnomos_mobile/models/vat_return.dart';
import 'package:accnomos_mobile/screens/more_screen.dart';
import 'package:accnomos_mobile/screens/reports_screen.dart';
import 'package:accnomos_mobile/screens/review_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Reports models follow the runtime shapes exactly (pence throughout);
/// the views fit a compact 360 dp phone without overflow.
void main() {
  const channel = MethodChannel('msal_auth');

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      throw PlatformException(
          code: 'NO_CURRENT_ACCOUNT', message: 'no account');
    });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  Widget shell(Widget home) => MaterialApp(home: Scaffold(body: home));

  group('models', () {
    test('gbp formats pence', () {
      expect(gbp(130000), '£1,300.00');
      expect(gbp(0), '£0.00');
      expect(gbp(-20135), '-£201.35');
      expect(ukDate('2026-07-01'), '1 Jul 2026');
      expect(ukDate(''), '—');
    });

    test('profit and loss parses sections and the sample flag', () {
      final pl = PlReport.fromJson({
        'start': '2026-07-01',
        'end': '2026-09-30',
        'label': 'Jul–Sep 2026',
        'sales': {
          'rows': [
            {'account': '4000 Sales', 'amount_pence': 130000}
          ],
          'total_pence': 130000,
        },
        'cost_of_sales': {
          'rows': [
            {'account': '5000 Materials', 'amount_pence': 25000}
          ],
          'total_pence': 25000,
        },
        'gross_profit_pence': 105000,
        'overheads': {'rows': [], 'total_pence': 0},
        'net_profit_pence': 105000,
        'entries': 8,
        'sample': true,
      });
      expect(pl.label, 'Jul–Sep 2026');
      expect(pl.sales.rows.single.account, '4000 Sales');
      expect(pl.grossPence, 105000);
      expect(pl.entries, 8);
      expect(pl.sample, isTrue);
    });

    test('aged parses debtors, creditors and buckets', () {
      final aged = AgedReport.fromJson({
        'as_of': '2026-10-27',
        'debtors': {
          'rows': [
            {
              'name': 'Acme Kitchens Ltd',
              'buckets': {'current': 60000, '61-90': 120000},
              'total_pence': 180000,
            }
          ],
          'buckets': {'current': 60000, '61-90': 120000},
          'total_pence': 180000,
        },
        'creditors': {'rows': [], 'buckets': {}, 'total_pence': 0},
        'sample': false,
      });
      expect(aged.debtors.rows.single.name, 'Acme Kitchens Ltd');
      expect(aged.debtors.rows.single.buckets['61-90'], 120000);
      expect(aged.debtors.totalPence, 180000);
      expect(aged.creditors.rows, isEmpty);
      expect(aged.sample, isFalse);
    });

    test('vat summary and trend parse oldest first', () {
      final vat = VatSummary.fromJson({
        'periods': [
          {
            'period': '2026-Q3',
            'label': 'Jul–Sep 2026',
            'vat_on_sales_pence': 26000,
            'vat_reclaimed_pence': 5865,
            'net_vat_pence': 20135,
            'sales_ex_vat_pounds': 1300,
            'purchases_ex_vat_pounds': 353,
            'entries': 7,
          }
        ],
        'total_net_vat_pence': 20135,
        'sample': false,
      });
      expect(vat.periods.single.netPence, 20135);
      expect(vat.totalNetPence, 20135);
      final trend = Trend.fromJson({
        'months': [
          {
            'month': '2026-10',
            'label': 'Oct 2026',
            'sales_pence': 50000,
            'purchases_pence': 0,
            'net_pence': 50000,
          }
        ],
        'sample': true,
      });
      expect(trend.months.single.label, 'Oct 2026');
      expect(trend.sample, isTrue);
    });

    test('export carries the file name and vat periods carry dates', () {
      final export = ReportExport.fromJson({
        'path': '07 Reports/2026-10-27-reports.xlsx',
        'name': '2026-10-27-reports.xlsx',
        'sample': false,
        'sheets': ['About', 'P&L'],
      });
      expect(export.name, '2026-10-27-reports.xlsx');
      final periods = VatPeriod.listFromJson({
        'periods': [
          {
            'period': '2026-Q4',
            'label': 'Oct–Dec 2026',
            'status': 'open',
            'current': true,
            'start': '2026-10-01',
            'end': '2026-12-31',
          }
        ]
      });
      expect(periods.single.start, '2026-10-01');
      expect(periods.single.end, '2026-12-31');
    });
  });

  group('undoMessage', () {
    test('names the open period for a submitted-period correction', () {
      expect(
        undoMessage(
          {
            'dated_today': true,
            'reason':
                'Your return for Jul–Sep 2026 was already submitted, so this correction goes in Oct–Dec 2026.',
          },
          'Novex · £51.90',
        ),
        'Your return for Jul–Sep 2026 was already submitted, so this correction goes in Oct–Dec 2026. Novex · £51.90 is back in Review.',
      );
    });

    test('plain undo and the autopilot section keep the old notes', () {
      expect(undoMessage({'dated_today': false}, 'Novex · £51.90'),
          'Undone · Novex · £51.90 is back in Review');
      expect(undoMessage(null, 'Novex · £51.90'),
          'Undone · Novex · £51.90 is back in Review');
      expect(undoMessage({'dated_today': true}, ''),
          'Undone · back in your review list');
      expect(
        undoMessage({'dated_today': true, 'reason': 'Some note.'}, ''),
        'Some note. It is back in Review.',
      );
    });
  });

  group('widgets at 360 dp', () {
    testWidgets('profit and loss shows sections and totals',
        (tester) async {
      tester.view.physicalSize = const Size(360, 740);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(shell(PlReportView(pl: _pl())));
      await tester.pumpAndSettle();
      expect(find.text('Profit and loss · Jul–Sep 2026'), findsOneWidget);
      expect(find.text('4000 Sales'), findsOneWidget);
      expect(find.text('£1,300.00'), findsNWidgets(2)); // the row and the total
      expect(find.text('Net profit'), findsOneWidget);
    });

    testWidgets('aged shows debtors and creditors', (tester) async {
      tester.view.physicalSize = const Size(360, 740);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(shell(AgedReportView(aged: _aged())));
      await tester.pumpAndSettle();
      expect(find.text('Debtors'), findsOneWidget);
      expect(find.text('Creditors'), findsOneWidget);
      expect(find.text('Acme Kitchens Ltd'), findsOneWidget);
      expect(find.text('£1,800.00'), findsWidgets);
    });

    testWidgets('vat summary and trend show figures', (tester) async {
      tester.view.physicalSize = const Size(360, 740);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(shell(VatSummaryView(vat: _vat())));
      await tester.pumpAndSettle();
      expect(find.text('Jul–Sep 2026'), findsOneWidget);
      expect(find.text('£201.35'), findsNWidgets(2)); // the row and the total

      await tester.pumpWidget(shell(TrendView(trend: _trend())));
      await tester.pumpAndSettle();
      expect(find.text('Sep 2026'), findsOneWidget);
      expect(find.text('Oct 2026'), findsOneWidget);
      expect(find.text('-£590.00'), findsOneWidget);
    });

    testWidgets('reports prompts for sign-in when signed out',
        (tester) async {
      tester.view.physicalSize = const Size(360, 740);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(const MaterialApp(home: ReportsScreen()));
      await tester.pumpAndSettle();
      expect(
          find.text('Sign in with Microsoft to see your reports.'),
          findsOneWidget);
    });

    testWidgets('more lists reports and opens it', (tester) async {
      tester.view.physicalSize = const Size(360, 740);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(const MaterialApp(home: MoreScreen()));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(find.text('Reports'), 100);
      expect(find.text('Reports'), findsOneWidget);
      await tester.tap(find.text('Reports'));
      await tester.pumpAndSettle();
      expect(
          find.text('Sign in with Microsoft to see your reports.'),
          findsOneWidget);
    });
  });
}

PlReport _pl() => PlReport.fromJson({
      'start': '2026-07-01',
      'end': '2026-09-30',
      'label': 'Jul–Sep 2026',
      'sales': {
        'rows': [
          {'account': '4000 Sales', 'amount_pence': 130000}
        ],
        'total_pence': 130000,
      },
      'cost_of_sales': {
        'rows': [
          {'account': '5000 Materials', 'amount_pence': 25000}
        ],
        'total_pence': 25000,
      },
      'gross_profit_pence': 105000,
      'overheads': {
        'rows': [
          {'account': '7500 Office supplies', 'amount_pence': 4325}
        ],
        'total_pence': 4325,
      },
      'net_profit_pence': 100675,
      'entries': 8,
      'sample': true,
    });

AgedReport _aged() => AgedReport.fromJson({
      'as_of': '2026-10-27',
      'debtors': {
        'rows': [
          {
            'name': 'Acme Kitchens Ltd',
            'buckets': {
              'current': 60000,
              '0-30': 0,
              '31-60': 0,
              '61-90': 120000,
              '90+': 0
            },
            'total_pence': 180000,
          }
        ],
        'buckets': {
          'current': 60000,
          '0-30': 0,
          '31-60': 0,
          '61-90': 120000,
          '90+': 0
        },
        'total_pence': 180000,
      },
      'creditors': {
        'rows': [
          {
            'name': 'Howdens Joinery with a very long name for wrapping',
            'buckets': {'90+': 30000},
            'total_pence': 30000,
          }
        ],
        'buckets': {'90+': 30000},
        'total_pence': 30000,
      },
      'sample': false,
    });

VatSummary _vat() => VatSummary.fromJson({
      'periods': [
        {
          'period': '2026-Q3',
          'label': 'Jul–Sep 2026',
          'vat_on_sales_pence': 26000,
          'vat_reclaimed_pence': 5865,
          'net_vat_pence': 20135,
          'sales_ex_vat_pounds': 1300,
          'purchases_ex_vat_pounds': 353,
          'entries': 7,
        }
      ],
      'total_net_vat_pence': 20135,
      'sample': false,
    });

Trend _trend() => Trend.fromJson({
      'months': [
        {
          'month': '2026-09',
          'label': 'Sep 2026',
          'sales_pence': 0,
          'purchases_pence': 59000,
          'net_pence': -59000,
        },
        {
          'month': '2026-10',
          'label': 'Oct 2026',
          'sales_pence': 50000,
          'purchases_pence': 0,
          'net_pence': 50000,
        },
      ],
      'sample': false,
    });

// Set by each widget test before pumping (binding-only shorthand).
TestFlutterView get testerView =>
    TestWidgetsFlutterBinding.instance.platformDispatcher.views.first;
