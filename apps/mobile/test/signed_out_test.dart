import 'package:accnomos_mobile/screens/capture_screen.dart';
import 'package:accnomos_mobile/screens/home_screen.dart';
import 'package:accnomos_mobile/screens/review_screen.dart';
import 'package:accnomos_mobile/screens/settings_screen.dart';
import 'package:accnomos_mobile/screens/vat_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Signed-out fallback: with no cached Microsoft account, every screen must
/// render its demo/sign-in prompt instead of hanging on MSAL.
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

  testWidgets('review shows labelled samples when signed out',
      (tester) async {
    await tester.pumpWidget(shell(const ReviewScreen()));
    await tester.pumpAndSettle();
    expect(
        find.text(
            'SAMPLE — FICTIONAL COMPANY · sign in to see your books'),
        findsOneWidget);
    expect(find.text('Screwfix'), findsOneWidget);
  });

  testWidgets('settings shows the Microsoft account card', (tester) async {
    await tester.pumpWidget(shell(const SettingsScreen()));
    await tester.pumpAndSettle();
    expect(find.text('Microsoft account'), findsOneWidget);
    expect(find.text('Sign in with Microsoft'), findsOneWidget);
    expect(find.text('Business name'), findsOneWidget);
  });

  testWidgets('vat prompts for sign-in when signed out', (tester) async {
    await tester.pumpWidget(shell(const VatScreen()));
    await tester.pumpAndSettle();
    expect(find.text('Your VAT return lives in your books'),
        findsOneWidget);
  });

  testWidgets('home tiles say "Connect to see" when signed out',
      (tester) async {
    await tester.pumpWidget(shell(const Scaffold(body: HomeScreen())));
    await tester.pumpAndSettle();
    expect(find.text('CASH IN BANK'), findsOneWidget);
    expect(find.text('Connect to see'), findsNWidgets(3));
    expect(find.text('Connect your cloud'), findsOneWidget);
  });

  testWidgets('capture offers photo buttons when signed out',
      (tester) async {
    await tester.pumpWidget(shell(const CaptureScreen()));
    await tester.pumpAndSettle();
    expect(find.text('Take a photo'), findsOneWidget);
    expect(find.text('Choose from gallery'), findsOneWidget);
  });
}
