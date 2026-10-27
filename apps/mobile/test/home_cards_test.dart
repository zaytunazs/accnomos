import 'package:accnomos_mobile/models/dashboard.dart';
import 'package:accnomos_mobile/models/suggestions.dart';
import 'package:accnomos_mobile/screens/home_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Home's To-dos and Inbox cards: labelled samples when signed out, no
/// overflow on a compact 360 dp phone, and code-built dashboard suggestions.
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

  Widget shell(Widget home) => MaterialApp(home: home);

  Dashboard dashboardWith({
    int? proposed,
    int? needsALook,
    int? unmatched,
    int? overdue,
    int? oldestDays,
    String? vatDeadline,
  }) =>
      Dashboard(
        cashPence: 100,
        cashAsOf: '2026-10-24',
        owedToYouPence: 200,
        overdueInvoices: overdue,
        mostOverdueDays: oldestDays,
        owedByYouPence: null,
        vatLabel: null,
        vatBox5: null,
        vatDirection: null,
        vatDeadline: vatDeadline,
        attentionTotal: 1,
        attentionProposed: proposed,
        attentionNeedsALook: needsALook,
        attentionUnmatchedBankLines: unmatched,
      );

  test('suggestions name receipts, overdue invoices and bank lines', () {
    final suggestions = suggestionsFor(dashboardWith(
      proposed: 2,
      needsALook: 1,
      unmatched: 4,
      overdue: 2,
      oldestDays: 12,
      vatDeadline: '2026-11-07',
    ));
    expect(suggestions.length, 3);
    expect(suggestions[0].text, '3 receipts to review');
    expect(suggestions[0].target, SuggestionTarget.review);
    expect(suggestions[1].text, '2 invoices overdue · oldest 12 days');
    expect(suggestions[1].target, SuggestionTarget.invoices);
    expect(suggestions[2].text, '4 bank lines to match');
    expect(suggestions[2].target, SuggestionTarget.bank);
  });

  test('suggestions fall back to the VAT deadline and stay quiet', () {
    final suggestions =
        suggestionsFor(dashboardWith(vatDeadline: '2026-11-07'));
    expect(suggestions.map((s) => s.text), ['VAT due 7 Nov']);
    expect(suggestions.single.target, SuggestionTarget.vat);
    expect(suggestionsFor(dashboardWith()), isEmpty);
  });

  testWidgets('both cards show labelled samples when signed out',
      (tester) async {
    // Tall surface: the cards sit below the tiles, and ListView only
    // builds visible children.
    tester.view.physicalSize = const Size(800, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(shell(const Scaffold(body: HomeScreen())));
    await tester.pumpAndSettle();
    expect(find.text('SAMPLE — FICTIONAL COMPANY'), findsNWidgets(2));
    expect(find.text('TO-DOS'), findsOneWidget);
    expect(find.text('INBOX'), findsOneWidget);
    expect(find.text('Chase INV-0041 (12 days overdue)'), findsOneWidget);
    expect(find.text('Bramblewood Ltd'), findsOneWidget);
    expect(find.text('Sign in to check your inbox.'), findsOneWidget);
  });

  testWidgets('home does not overflow at 360 dp when signed out',
      (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(shell(const Scaffold(body: HomeScreen())));
    await tester.pumpAndSettle();
    expect(find.text('TO-DOS'), findsOneWidget);
    // Any RenderFlex overflow throws during pumpAndSettle above.
  });
}
