import 'package:accnomos_mobile/screens/bank_screen.dart';
import 'package:accnomos_mobile/screens/home_tab.dart';
import 'package:accnomos_mobile/screens/invoices_screen.dart';
import 'package:accnomos_mobile/screens/more_screen.dart';
import 'package:accnomos_mobile/screens/payroll_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// New tabs keep the signed-out contract: labelled samples or a sign-in
/// prompt, never a hang on MSAL.
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

  testWidgets('home keeps labelled sample tiles when signed out',
      (tester) async {
    // Tall surface: the connect button sits below the fold otherwise,
    // and ListView only builds visible children.
    tester.view.physicalSize = const Size(800, 2000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(shell(const Scaffold(body: HomeTab())));
    await tester.pumpAndSettle();
    expect(find.text('CASH IN BANK'), findsOneWidget);
    expect(find.text('Connect your cloud'), findsOneWidget);
  });

  testWidgets('compact 360 dp layouts do not overflow', (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    for (final screen in [
      const Scaffold(body: HomeTab()),
      const MoreScreen(),
      const PayrollScreen(),
      const BankScreen(),
      const InvoicesScreen(),
    ]) {
      await tester.pumpWidget(shell(screen));
      await tester.pumpAndSettle();
    }
    // Any RenderFlex overflow throws during pumpAndSettle above.
  });

  testWidgets('more lists files, payroll and bank', (tester) async {
    await tester.pumpWidget(shell(const MoreScreen()));
    await tester.pumpAndSettle();
    expect(find.text('Files'), findsOneWidget);
    expect(find.text('Payroll'), findsOneWidget);
    expect(find.text('Bank'), findsOneWidget);
  });

  testWidgets('payroll prompts for sign-in when signed out',
      (tester) async {
    await tester.pumpWidget(shell(const PayrollScreen()));
    await tester.pumpAndSettle();
    expect(find.text('Sign in with Microsoft to see your pay runs.'),
        findsOneWidget);
    expect(find.text('Estimates only — confirm from the web app.'),
        findsNothing);
  });

  testWidgets('bank prompts for sign-in when signed out', (tester) async {
    await tester.pumpWidget(shell(const BankScreen()));
    await tester.pumpAndSettle();
    expect(find.text('Sign in with Microsoft to see your bank statements.'),
        findsOneWidget);
  });

  testWidgets('invoices prompt for sign-in when signed out',
      (tester) async {
    await tester.pumpWidget(shell(const InvoicesScreen()));
    await tester.pumpAndSettle();
    expect(find.text('Sign in with Microsoft to see your sales invoices.'),
        findsOneWidget);
  });
}
