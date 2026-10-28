import 'package:accnomos_mobile/models/dashboard.dart';
import 'package:accnomos_mobile/screens/more_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The More tab and the Home VAT tile follow the books' profile
/// (`GET /profile` features, services/runtime/app/profile.py), as the web's
/// menu and Home do: personal books have no invoices, payroll or VAT; a
/// business that is not VAT-registered has no VAT.
const personal = [
  'review', 'ask', 'files', 'bank', 'reports', 'contacts', 'jobs', 'vehicles',
];
const companyNoVat = [...personal, 'invoices', 'payroll'];
const companyVat = [...companyNoVat, 'vat'];

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

  String reportsNote(List<String>? f) =>
      moreEntries(f).firstWhere((e) => e.title == 'Reports').note;
  List<String> titles(List<String>? f) =>
      moreEntries(f).map((e) => e.title).toList();

  test('features not known yet: every entry, as before profiles', () {
    expect(titles(null), [
      'Files', 'Contacts', 'Invoices', 'Jobs', 'Vehicles', 'Bank',
      'Payroll', 'Month-end', 'Reports', 'Audit trail',
    ]);
    expect(reportsNote(null), contains('VAT'));
  });

  test('personal books: no invoices or payroll, and Reports says no VAT', () {
    expect(titles(personal), isNot(contains('Invoices')));
    expect(titles(personal), isNot(contains('Payroll')));
    expect(titles(personal), containsAll(['Files', 'Bank', 'Reports']));
    expect(reportsNote(personal), isNot(contains('VAT')));
  });

  test('a business that is not VAT-registered keeps invoices and payroll, no VAT', () {
    expect(titles(companyNoVat), containsAll(['Invoices', 'Payroll']));
    expect(reportsNote(companyNoVat), isNot(contains('VAT')));
    expect(reportsNote(companyVat), contains('VAT'));
  });

  testWidgets('the More screen leaves out what personal books lack',
      (tester) async {
    await tester.pumpWidget(
        const MaterialApp(home: MoreScreen(features: personal)));
    await tester.pumpAndSettle();
    expect(find.text('Invoices'), findsNothing);
    expect(find.text('Payroll'), findsNothing);
    expect(find.text('Files'), findsOneWidget);
    expect(find.text('Profit and loss, aged balances and trend'),
        findsOneWidget);
  });

  testWidgets('signed out, the More screen lists everything', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: MoreScreen()));
    await tester.pumpAndSettle();
    expect(find.text('Invoices'), findsOneWidget);
    expect(find.text('Payroll'), findsOneWidget);
  });

  test('the dashboard says whether Home shows VAT; an older runtime means yes',
      () {
    expect(Dashboard.fromJson({'vat_applies': false, 'vat': null}).vatApplies,
        isFalse);
    expect(Dashboard.fromJson({'vat_applies': true}).vatApplies, isTrue);
    expect(Dashboard.fromJson({}).vatApplies, isTrue);
  });
}
