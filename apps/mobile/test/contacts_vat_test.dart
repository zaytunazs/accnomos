import 'package:accnomos_mobile/widgets/vat_status.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// The VAT status control: the segmented control saves the tapped wire
/// value, the format check matches the web, and nothing wraps at 360 dp.
void main() {
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
}

void _ignore(String _) {}
