import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/widgets/lookups.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// The VAT check: tap only, HMRC's answer with its source, the name-mismatch
/// warning, and never a block. Callbacks stand in for the reader.
void main() {
  Map<String, dynamic> check({
    bool registered = true,
    String source = 'hmrc-sandbox',
  }) =>
      {
        'vrn': 'GB882431902',
        'registered': registered,
        'name': 'NOVEX OFFICE SUPPLIES LTD',
        'address': '14 Industrial Park, Leeds, LS10 1AB',
        'consultation_number': null,
        'checked_at': '2026-10-27T10:00:00',
        'source': source,
        'checksum_ok': null,
      };

  Widget section({
    required Future<Map<String, dynamic>> Function() onCheck,
    Map<String, dynamic>? initial,
    VoidCallback? onNotConfigured,
    bool hidden = false,
  }) {
    if (hidden) return const MaterialApp(home: Scaffold(body: Text('gone')));
    return MaterialApp(
      home: Scaffold(
        body: VatCheckSection(
          vrn: 'GB882431902',
          name: 'Novex Office Supplies Ltd',
          onCheck: onCheck,
          initial: initial,
          onNotConfigured: onNotConfigured,
        ),
      ),
    );
  }

  test('vatCheckText names HMRC and its source', () {
    expect(
        vatCheckText(check()),
        'Registered to NOVEX OFFICE SUPPLIES LTD, '
        '14 Industrial Park, Leeds, LS10 1AB (HMRC sandbox)');
    expect(vatCheckText(check(registered: false)),
        'Not VAT-registered (HMRC sandbox)');
    expect(vatCheckText(check(source: 'sample')).endsWith('(SAMPLE, test mode)'),
        isTrue);
  });

  testWidgets('tap shows who HMRC says it is registered to', (tester) async {
    await tester.pumpWidget(section(
        onCheck: () async =>
            {'check': check(), 'name_differs': false, 'cached': false}));
    await tester.tap(find.text('Check VAT number'));
    await tester.pumpAndSettle();
    expect(
        find.textContaining(
            'Registered to NOVEX OFFICE SUPPLIES LTD', findRichText: true),
        findsOneWidget);
    expect(find.textContaining('HMRC sandbox'), findsOneWidget);
    expect(find.textContaining('differs'), findsNothing);
  });

  testWidgets('an unregistered number says so plainly', (tester) async {
    await tester.pumpWidget(section(
        onCheck: () async => {
              'check': check(registered: false),
              'name_differs': false,
              'cached': false
            }));
    await tester.tap(find.text('Check VAT number'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Not VAT-registered'), findsOneWidget);
  });

  testWidgets('a different name warns but never blocks', (tester) async {
    await tester.pumpWidget(section(
        onCheck: () async =>
            {'check': check(), 'name_differs': true, 'cached': false}));
    await tester.tap(find.text('Check VAT number'));
    await tester.pumpAndSettle();
    expect(
        find.textContaining("HMRC's name differs", findRichText: true),
        findsOneWidget);
    // The answer stays on screen; there is no block, no Approve to wait on.
    expect(find.textContaining('Registered to'), findsOneWidget);
  });

  testWidgets('503 hides the check instead of erroring', (tester) async {
    var hidden = false;
    await tester.pumpWidget(section(
      onCheck: () async {
        throw RuntimeException(
            'The reader refused that request (status 503). '
            '{"error": "vat_check_not_configured", "detail": "x"}');
      },
      onNotConfigured: () => hidden = true,
    ));
    await tester.tap(find.text('Check VAT number'));
    await tester.pumpAndSettle();
    expect(hidden, isTrue);
    expect(find.text('Check VAT number'), findsOneWidget);
  });

  testWidgets('other failures show on the card', (tester) async {
    await tester.pumpWidget(section(onCheck: () async {
      throw RuntimeException('Could not check that VAT number. boom');
    }));
    await tester.tap(find.text('Check VAT number'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Could not check'), findsOneWidget);
  });

  testWidgets('result and warning do not overflow at 360 dp', (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(section(
        onCheck: () async =>
            {'check': check(), 'name_differs': true, 'cached': false}));
    await tester.tap(find.text('Check VAT number'));
    await tester.pumpAndSettle();
    await tester.pump();
    expect(tester.takeException(), isNull);
  });
}
