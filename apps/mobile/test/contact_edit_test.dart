import 'package:accnomos_mobile/screens/contact_edit_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// The contact edit sheet: Companies House fills name, number and address;
/// nothing is saved until Save.
void main() {
  Map<String, dynamic> match() => {
        'company_number': 'ZZ000001',
        'name': 'NOVEX OFFICE SUPPLIES LIMITED',
        'status': 'active',
        'address': '14 Industrial Park, Leeds, LS10 1AB',
      };

  Widget sheet({
    bool companiesHouse = true,
    Future<List<Map<String, dynamic>>> Function(String q)? onSearch,
  }) {
    return MaterialApp(
      home: Scaffold(
        body: ContactEditSheet(
          initialName: 'Novex',
          initialCompanyNumber: '',
          initialAddress: '',
          companiesHouse: companiesHouse,
          onSearch: onSearch ?? (_) async => [match()],
        ),
      ),
    );
  }

  testWidgets('fields start from the contact', (tester) async {
    await tester.pumpWidget(sheet(companiesHouse: false));
    expect(find.text('Novex'), findsOneWidget);
    expect(find.text('Look up on Companies House'), findsNothing);
  });

  testWidgets('look-up pick fills name, number and address', (tester) async {
    await tester.pumpWidget(sheet());
    await tester.tap(find.text('Look up on Companies House'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Look up'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('NOVEX OFFICE SUPPLIES LIMITED'));
    await tester.pumpAndSettle();
    expect(find.text('NOVEX OFFICE SUPPLIES LIMITED'), findsWidgets);
    expect(find.text('ZZ000001'), findsOneWidget);
    expect(find.text('14 Industrial Park, Leeds, LS10 1AB'), findsOneWidget);
  });

  testWidgets('Save returns the edits, Cancel returns null', (tester) async {
    Map<String, dynamic>? saved;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => FilledButton(
              onPressed: () async {
                saved = await showModalBottomSheet<Map<String, dynamic>>(
                  context: context,
                  isScrollControlled: true,
                  builder: (_) => ContactEditSheet(
                    initialName: 'Novex',
                    initialCompanyNumber: '',
                    initialAddress: '',
                    companiesHouse: false,
                    onSearch: (_) async => const [],
                  ),
                );
              },
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(saved?['name'], 'Novex');
    expect(saved?.containsKey('company_number'), isTrue);

    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(saved, isNull);
  });

  testWidgets('an empty name explains itself', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: ContactEditSheet(
          initialName: '',
          initialCompanyNumber: '',
          initialAddress: '',
          companiesHouse: false,
          onSearch: (_) async => const [],
        ),
      ),
    ));
    await tester.tap(find.text('Save'));
    await tester.pump();
    expect(find.text('Give the contact a name.'), findsOneWidget);
  });

  testWidgets('sheet does not overflow at 360 dp', (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(sheet());
    await tester.tap(find.text('Look up on Companies House'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Look up'));
    await tester.pumpAndSettle();
    await tester.pump();
    expect(tester.takeException(), isNull);
  });
}
