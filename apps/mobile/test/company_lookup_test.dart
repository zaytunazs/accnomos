import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/widgets/lookups.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// The Companies House look-up: search by name or number, pick a match to
/// fill the form. Callbacks stand in for the reader; nothing is saved here.
void main() {
  Map<String, dynamic> match() => {
        'company_number': 'ZZ000001',
        'name': 'NOVEX OFFICE SUPPLIES LIMITED',
        'status': 'active',
        'type': 'ltd',
        'address': '14 Industrial Park, Leeds, LS10 1AB',
        'date_of_creation': '2019-04-02',
        'source': 'sample',
        'sample': true,
      };

  Future<Widget> section({
    List<Map<String, dynamic>> items = const [],
    Future<List<Map<String, dynamic>>> Function(String q)? onSearch,
    ValueChanged<Map<String, dynamic>>? onPick,
    VoidCallback? onNotConfigured,
  }) async {
    String? picked;
    return MaterialApp(
      home: Scaffold(
        body: CompanyLookupSection(
          initialQuery: 'Novex',
          onSearch: onSearch ?? (_) async => items,
          onPick: onPick ?? (_) {},
          onNotConfigured: onNotConfigured,
        ),
      ),
    );
  }

  Future<void> open(WidgetTester tester) async {
    await tester.tap(find.text('Look up on Companies House'));
    await tester.pumpAndSettle();
  }

  testWidgets('closed shows only the look-up button', (tester) async {
    await tester.pumpWidget(await section());
    expect(find.text('Look up on Companies House'), findsOneWidget);
    expect(find.text('Company name or number'), findsNothing);
  });

  testWidgets('search lists matches and picking fills the form',
      (tester) async {
    Map<String, dynamic>? picked;
    String? asked;
    await tester.pumpWidget(await section(
      onSearch: (q) async {
        asked = q;
        return [match()];
      },
      onPick: (m) => picked = m,
    ));
    await open(tester);
    expect(
        (tester.widget(find.byType(TextField)) as TextField)
            .controller
            ?.text,
        'Novex');
    await tester.tap(find.text('Look up'));
    await tester.pumpAndSettle();
    expect(asked, 'Novex');
    expect(
        find.textContaining(
            'nothing is saved until you press Save'),
        findsOneWidget);
    await tester.tap(find.text('NOVEX OFFICE SUPPLIES LIMITED'));
    await tester.pumpAndSettle();
    expect(picked?['company_number'], 'ZZ000001');
    expect(find.text('Company name or number'), findsNothing);
  });

  testWidgets('a short query explains itself', (tester) async {
    await tester.pumpWidget(await section());
    await open(tester);
    final field = find.byType(TextField);
    await tester.enterText(field, 'N');
    await tester.tap(find.text('Look up'));
    await tester.pump();
    expect(find.textContaining('at least 2 characters'), findsOneWidget);
  });

  testWidgets('503 hides the look-up instead of erroring', (tester) async {
    var hidden = false;
    await tester.pumpWidget(await section(
      onSearch: (_) async {
        throw RuntimeException(
            'The reader refused that request (status 503). '
            '{"error": "companies_house_not_configured", "detail": "x"}');
      },
      onNotConfigured: () => hidden = true,
    ));
    await open(tester);
    await tester.tap(find.text('Look up'));
    await tester.pumpAndSettle();
    expect(hidden, isTrue);
  });

  testWidgets('other failures show, and the look-up closes', (tester) async {
    await tester.pumpWidget(await section(
      onSearch: (_) async {
        throw RuntimeException('Could not look up that company. boom');
      },
    ));
    await open(tester);
    await tester.tap(find.text('Look up'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Could not look up'), findsOneWidget);
    await tester.tap(find.text('Close look-up'));
    await tester.pumpAndSettle();
    expect(find.text('Look up on Companies House'), findsOneWidget);
  });

  testWidgets('results do not overflow at 360 dp', (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(await section(items: [match(), match()]));
    await open(tester);
    await tester.tap(find.text('Look up'));
    await tester.pumpAndSettle();
    await tester.pump();
    expect(tester.takeException(), isNull);
  });
}
