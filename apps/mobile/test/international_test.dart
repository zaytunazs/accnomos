import 'dart:convert';

import 'package:accnomos_mobile/main.dart' show shellDestinations, shellTabIndex;
import 'package:accnomos_mobile/screens/more_screen.dart';
import 'package:accnomos_mobile/screens/region_screen.dart';
import 'package:accnomos_mobile/services/file_picker.dart';
import 'package:accnomos_mobile/services/money.dart';
import 'package:accnomos_mobile/services/region.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:accnomos_mobile/widgets/region_form.dart';
import 'package:accnomos_mobile/widgets/statement_import.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Books kept outside the UK (services/region.dart, the runtime's
/// app/region.py): no VAT tab or payroll, the books' own currency, the
/// country/tax/currency questions, and statements as CSV or PDF (bank
/// connections reach UK banks only, so the phone offers upload).

/// GET /profile for Australian books, as the runtime answers it.
const auProfile = {
  'name': 'Kim Design Pty Ltd',
  'kind': 'company',
  'exists': true,
  'settings': {
    'country': 'AU',
    'currency': 'AUD',
    'sales_tax': {'name': 'GST', 'rate_percent': 10.0, 'number': null},
  },
  'features': [
    'review', 'ask', 'files', 'bank', 'reports', 'contacts', 'jobs',
    'vehicles', 'invoices',
  ],
  'region': {
    'country': 'AU',
    'country_name': 'Australia',
    'uk': false,
    'currency': 'AUD',
    'tax_name': 'GST',
    'tax_label': 'GST',
    'tax_rate_percent': 10.0,
  },
};

const ukProfile = {
  'name': 'Sam Builds Ltd',
  'kind': 'company',
  'exists': true,
  'settings': {'company_number': '01234567', 'vat_number': null, 'vat_registered': false},
  'features': ['review', 'ask', 'files', 'bank', 'reports', 'contacts', 'jobs', 'vehicles', 'invoices', 'payroll'],
  'region': {
    'country': 'GB',
    'country_name': 'United Kingdom',
    'uk': true,
    'currency': 'GBP',
    'tax_name': 'VAT',
    'tax_label': 'VAT',
    'tax_rate_percent': 20,
  },
};

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    BooksRegion.current.value = BooksRegion.ukBooks;
  });
  tearDown(() => BooksRegion.current.value = BooksRegion.ukBooks);

  test('the region from GET /profile; anything else is UK books', () {
    final au = BooksRegion.fromJson(auProfile['region']);
    expect((au.uk, au.currency, au.taxLabel, au.rateText, au.sign), (false, 'AUD', 'GST', '10', r'A$'));
    expect(BooksRegion.fromJson(null).uk, isTrue);
    expect(BooksRegion.fromJson(ukProfile['region']).sign, '£');
  });

  test('money shows the books\' own currency', () {
    expect(formatMoneyPence(123450), '£1,234.50');
    BooksRegion.current.value = BooksRegion.fromJson(auProfile['region']);
    expect(formatMoneyPence(123450), r'A$1,234.50');
    expect(formatMoneyPence(-500), r'-A$5.00');
  });

  test('no VAT tab outside the UK: Reports takes its place', () {
    final abroad = [for (final d in shellDestinations(household: false, uk: false)) d.label];
    expect(abroad, ['Home', 'Review', 'Ask', 'Reports', 'More']);
    final uk = [for (final d in shellDestinations(household: false)) d.label];
    expect(uk, ['Home', 'Review', 'Ask', 'VAT', 'More']);
    expect(shellTabIndex('vat', household: false, uk: false), isNull);
    expect(shellTabIndex('reports', household: false, uk: false), 3);
    expect(shellTabIndex('vat', household: false), 3);
  });

  test('More has no payroll for books outside the UK (the runtime drops it)', () {
    final features = [for (final f in auProfile['features'] as List) '$f'];
    final titles = [for (final e in moreEntries(features)) e.title];
    expect(titles, isNot(contains('Payroll')));
    expect(titles, containsAll(['Invoices', 'Bank', 'Reports', 'Goals']));
    expect(moreEntries(features).firstWhere((e) => e.title == 'Reports').note, isNot(contains('VAT')));
  });

  test('a chosen country starts from its usual tax, rate and currency', () {
    final au = RegionAnswers.forCountry('AU');
    expect((au.taxName, au.taxRate, au.currency), ('GST', 10, 'AUD'));
    expect(au.toSettings(), {
      'country': 'AU',
      'currency': 'AUD',
      'sales_tax': {'name': 'GST', 'rate_percent': 10},
    });
    final us = RegionAnswers.forCountry('US');
    expect((us.taxName, us.taxRate, us.currency), ('Sales tax', 0, 'USD'));
    expect(RegionAnswers.forCountry('AQ').problem, contains('currency'));
    expect(const RegionAnswers().toSettings(), {'country': 'GB'});
    final none = au.copyWith(taxName: 'None');
    expect((none.toSettings()['sales_tax'] as Map)['rate_percent'], 0);
  });

  testWidgets('the country step: UK first, then GST and its percentage', (tester) async {
    var value = const RegionAnswers();
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: StatefulBuilder(
          builder: (context, setState) => SingleChildScrollView(
            child: RegionForm(value: value, onChanged: (v) => setState(() => value = v)),
          ),
        ),
      ),
    ));
    expect(find.text('United Kingdom'), findsWidgets);
    expect(find.text('Do you charge VAT, GST or sales tax?'), findsNothing);

    await tester.enterText(find.byKey(const Key('region-search')), 'Australia');
    await tester.pumpAndSettle();
    expect(value.country, 'AU');
    expect(find.text('Do you charge VAT, GST or sales tax?'), findsOneWidget);
    expect(tester.widget<ChoiceChip>(find.byKey(const Key('region-tax-GST'))).selected, isTrue);
    expect(find.widgetWithText(TextField, '10'), findsOneWidget);
    expect(find.text('Australian dollar (AUD)'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('region-rate')), '12.5');
    await tester.pump();
    expect(value.taxRate, 12.5);

    await tester.tap(find.byKey(const Key('region-tax-None')));
    await tester.pumpAndSettle();
    expect(value.taxName, 'None');
    expect(find.byKey(const Key('region-rate')), findsNothing);
  });

  testWidgets('Settings › Country and tax saves the profile and the region', (tester) async {
    final sent = <Map<String, dynamic>>[];
    final mock = MockClient((request) async {
      if (request.method == 'PUT') {
        sent.add(json.decode(request.body) as Map<String, dynamic>);
        return http.Response(json.encode(auProfile), 200, headers: {'content-type': 'application/json'});
      }
      return http.Response(json.encode(ukProfile), 200, headers: {'content-type': 'application/json'});
    });
    RuntimeClient client() => RuntimeClient(
          AppSettings(runtimeUrl: 'http://reader'),
          books: BooksAuth(graphToken: 'tok', accountKind: 'personal', user: 'kim@example.com'),
          httpClient: mock,
        );
    await tester.pumpWidget(MaterialApp(home: RegionScreen(clientFor: () async => client())));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('region-search')), 'Australia');
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('region-save')));
    await tester.tap(find.byKey(const Key('region-save')));
    await tester.pumpAndSettle();

    expect(sent, hasLength(1));
    expect(sent.single['name'], 'Sam Builds Ltd');
    expect(sent.single['kind'], 'company');
    final settings = sent.single['settings'] as Map;
    expect(settings['country'], 'AU');
    expect(settings['currency'], 'AUD');
    expect(settings['sales_tax'], {'name': 'GST', 'rate_percent': 10});
    expect(BooksRegion.current.value.currency, 'AUD');
    expect(find.text('Saved to your OneDrive.'), findsOneWidget);
  });

  testWidgets('statements come in as CSV or PDF', (tester) async {
    const channel = MethodChannel('test/files');
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (call) async {
      return {'name': 'october.pdf', 'bytes': Uint8List.fromList(utf8.encode('%PDF-1.4'))};
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, null));
    final uploads = <String>[];
    final mock = MockClient((request) async {
      uploads.add(request.url.path);
      return http.Response(json.encode({'lines': 3, 'new_lines': 3, 'duplicate_file': false}), 200,
          headers: {'content-type': 'application/json'});
    });
    final client = RuntimeClient(
      AppSettings(runtimeUrl: 'http://reader'),
      books: BooksAuth(graphToken: 'tok', accountKind: 'personal', user: 'kim@example.com'),
      httpClient: mock,
    );
    expect(FilePicker.statementTypes, contains('application/pdf'));
    final note = await tester.runAsync(
        () => pickAndImportStatement(client, picker: FilePicker(channel: channel)));
    expect(note, 'Imported 3 lines (3 new) from october.pdf.');
    expect(uploads, ['/books/bank/import']);

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: ImportStatementButton(clientFor: () async => client)),
    ));
    expect(find.text('Import a bank statement (CSV or PDF)'), findsOneWidget);
    expect(find.textContaining('Connect a bank'), findsNothing);
  });
}
