import 'package:accnomos_mobile/screens/ask_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The Ask cards with nobody signed in: the sample thread must show the
/// question, the key-number table, the citations and the exact footer — and
/// fit a 360 dp wide phone without overflowing.
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

  Widget shell() => const MaterialApp(home: AskScreen());

  testWidgets('ask shows the sample cards when signed out', (tester) async {
    await tester.pumpWidget(shell());
    await tester.pumpAndSettle();
    expect(find.text('SAMPLE — FICTIONAL COMPANY'), findsOneWidget);
    expect(
        find.text('Why is my VAT higher than last quarter?'),
        findsOneWidget);
    expect(find.text('Net VAT (Box 5), Q3'), findsOneWidget);
    expect(find.text('£2,140.00'), findsOneWidget);
    expect(
        find.text('05 VAT returns/2026-Q3/return.json'), findsOneWidget);
    expect(find.text('Books.xlsx · VAT sheet'), findsOneWidget);
    expect(
        find.text('numbers by code · explanation by Muse Spark · 1.2 s'),
        findsOneWidget);
    expect(find.text('Chase Howdens for the invoice'), findsOneWidget);
    expect(find.text('Sign in to ask your own books'), findsOneWidget);
  });

  testWidgets('ask fits a 360 dp wide phone', (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(shell());
    await tester.pumpAndSettle();
    expect(find.text('SAMPLE — FICTIONAL COMPANY'), findsOneWidget);
    expect(find.text('Net VAT (Box 5), Q3'), findsOneWidget);
    expect(find.text('Books.xlsx · VAT sheet'), findsOneWidget);
    expect(
        find.text('numbers by code · explanation by Muse Spark · 1.2 s'),
        findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
