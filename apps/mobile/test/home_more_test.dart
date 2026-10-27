import 'package:accnomos_mobile/screens/audit_screen.dart';
import 'package:accnomos_mobile/screens/bank_screen.dart';
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

  testWidgets('compact 360 dp layouts do not overflow', (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    for (final screen in [
      const MoreScreen(),
      const PayrollScreen(),
      const BankScreen(),
      const AuditScreen(),
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
    await tester.scrollUntilVisible(find.text('Audit trail'), 100);
    expect(find.text('Audit trail'), findsOneWidget);
  });

  testWidgets('audit trail prompts for sign-in when signed out', (tester) async {
    await tester.pumpWidget(shell(const AuditScreen()));
    await tester.pumpAndSettle();
    expect(find.text('Sign in with Microsoft to see your audit trail.'), findsOneWidget);
  });

  test('audit lines group by day, newest day first, with UK headings', () {
    AuditLine at(String ts, String label) => AuditLine.fromJson({
          'ts': ts,
          'actor_label': label,
          'actor_kind': label == 'You' ? 'user' : 'agent',
          'event': 'approved',
          'summary': 'Posted Screwfix £12.00 to the ledger',
        })!;
    final days = auditDays([
      at('2026-10-14T16:00:00', 'You'),
      at('2026-10-14T08:00:00', 'Autopilot'),
      at('2026-10-13T09:00:00', 'Intake'),
    ]);
    expect(days.map((d) => auditDayHeading(d.key)),
        ['Wednesday 14 October 2026', 'Tuesday 13 October 2026']);
    expect(days.first.value.map((l) => l.actorLabel), ['You', 'Autopilot']);
    expect(days.first.value.first.byPerson, isTrue);
    expect(AuditLine.fromJson({'ts': 'yesterday'}), isNull);
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
}
