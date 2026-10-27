import 'package:accnomos_mobile/screens/contacts_screen.dart';
import 'package:accnomos_mobile/widgets/vat_status.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The VAT status control: the segmented control saves the tapped wire
/// value, the format check matches the web, and nothing wraps at 360 dp.
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

  test('contact VRN check matches the web: GB plus 9 or 12 digits', () {
    expect(isValidContactVrn('GB 123 4567 89'), isTrue);
    expect(isValidContactVrn('gb123456789'), isTrue);
    expect(isValidContactVrn('GB 1234 5678 9012'), isTrue);
    expect(isValidContactVrn('123456789'), isFalse);
    expect(isValidContactVrn('GB 123'), isFalse);
    expect(isValidContactVrn('GB 1234567890123'), isFalse);
    expect(isValidContactVrn(''), isFalse);
  });

  testWidgets('segmented control saves the tapped value', (tester) async {
    String? saved;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: VatStatusSegmented(
            value: vatStatusUnknown,
            onChanged: (value) => saved = value,
          ),
        ),
      ),
    );
    await tester.tap(find.text('Registered'));
    await tester.pump();
    expect(saved, vatStatusRegistered);

    saved = null;
    await tester.tap(find.text('Not registered'));
    await tester.pump();
    expect(saved, vatStatusNotRegistered);
  });

  testWidgets('segmented control marks the current value', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: VatStatusSegmented(
            value: vatStatusNotRegistered,
            onChanged: _ignore,
          ),
        ),
      ),
    );
    final button = tester.widget<SegmentedButton<String>>(
        find.byType(SegmentedButton<String>));
    expect(button.selected, {vatStatusNotRegistered});
  });

  testWidgets('unknown status shows no chip', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: Column(
            children: [
              VatStatusChip(status: vatStatusUnknown),
              VatStatusChip(status: vatStatusRegistered),
              VatStatusChip(status: vatStatusNotRegistered),
            ],
          ),
        ),
      ),
    );
    expect(find.text('VAT-registered'), findsOneWidget);
    expect(find.text('Not VAT-registered'), findsOneWidget);
  });

  testWidgets('segmented control does not overflow at 360 dp',
      (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Padding(
            padding: const EdgeInsets.all(16),
            child: VatStatusSegmented(
              value: vatStatusUnknown,
              onChanged: _ignore,
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Not registered'), findsOneWidget);
    // Any RenderFlex overflow throws during pumpAndSettle above.
  });

  testWidgets('signed out shows labelled samples with VAT chips',
      (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await _pumpContacts(tester);
    expect(
        find.text('SAMPLE — FICTIONAL CONTACTS · demo data only'),
        findsOneWidget);
    expect(find.text('Brixton Timber Co'), findsOneWidget);
    expect(find.text('VAT-registered'), findsOneWidget);
    expect(find.text('Not VAT-registered'), findsOneWidget);
    expect(find.text('VAT GB 440 1234 55'), findsOneWidget);
    expect(find.text('Sign in to see your contacts'), findsOneWidget);
    // Unknown suppliers show no chip.
    expect(find.text('Dave Oddjobs'), findsOneWidget);
    // Any RenderFlex overflow throws during pumpAndSettle above.
  });

  testWidgets('sample detail shows VAT control, ranges and aged bars',
      (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await _pumpContacts(tester);
    await tester.tap(find.text('Brixton Timber Co'));
    await tester.pumpAndSettle();
    expect(find.text('This quarter'), findsOneWidget);
    expect(find.text('Last quarter'), findsOneWidget);
    expect(find.text('Custom'), findsOneWidget);
    expect(find.text('Save VAT number'), findsOneWidget);
    expect(
        find.text('Over £250 with no VAT number, Accnomos asks about '
            'unknown suppliers; this setting answers it for good.'),
        findsOneWidget);
    await tester.tap(find.text('Not registered'));
    await tester.pump();
    expect(find.text('Sample contact — sign in to save.'),
        findsOneWidget);
    // Below the fold: the ListView only builds it once scrolled to.
    await tester.drag(find.byType(ListView), const Offset(0, -900));
    await tester.pumpAndSettle();
    expect(find.text('Unpaid by age'), findsOneWidget);
    expect(find.text('0-30'), findsOneWidget);
    expect(find.text('90+'), findsOneWidget);
  });
}

void _ignore(String _) {}

/// Signed-out contacts: labelled samples with VAT chips, and a sample
/// detail with the VAT control, statement ranges and aged bars.
Future<void> _pumpContacts(WidgetTester tester) async {
  await tester.pumpWidget(
      const MaterialApp(home: ContactsScreen()));
  await tester.pumpAndSettle();
}
