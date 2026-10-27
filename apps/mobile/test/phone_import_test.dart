import 'package:accnomos_mobile/screens/phone_import_sheet.dart';
import 'package:accnomos_mobile/services/phone_contacts.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// "Add from phone": the picker is mocked at the method channel, and the
/// review sheet marks each pick Customer / Supplier / Skip before import.
void main() {
  const channel = MethodChannel('accnomos/phone-contacts');

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  void mockPicker(Map<String, Object?>? pick) {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      expect(call.method, 'pickContact');
      return pick;
    });
  }

  final mum = PickedPhoneContact(
    name: 'Mum',
    emails: const ['mum@example.com'],
    phones: const ['07700 900000'],
    address: '1 High St, Leeds',
  );
  final sam = PickedPhoneContact(
    name: 'Sam Patel',
    emails: const ['sam@acme.example'],
  );

  test('picker parses the native map; cancel returns null', () async {
    mockPicker({
      'name': 'Mum',
      'emails': ['mum@example.com'],
      'phones': ['07700 900000'],
      'address': '1 High St',
    });
    final pick = await PhoneContacts().pickContact();
    expect(pick?.name, 'Mum');
    expect(pick?.email, 'mum@example.com');
    expect(pick?.phone, '07700 900000');
    expect(pick?.address, '1 High St');

    mockPicker(null);
    expect(await PhoneContacts().pickContact(), isNull);
  });

  test('blank names from the picker are dropped', () async {
    mockPicker({'name': '  ', 'emails': <String>[]});
    expect(await PhoneContacts().pickContact(), isNull);
  });

  test('import body keeps kind and only the fields the picker gave', () {
    expect(
      mum.toImportJson('supplier'),
      {
        'name': 'Mum',
        'kind': 'supplier',
        'email': 'mum@example.com',
        'phone': '07700 900000',
        'address': '1 High St, Leeds',
      },
    );
    expect(
      PickedPhoneContact(name: 'No Details').toImportJson('customer'),
      {'name': 'No Details', 'kind': 'customer'},
    );
  });

  testWidgets('sheet shows the privacy note and one row per pick',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PhoneImportSheet(
            initialPicks: [mum, sam],
            onPickAnother: () async => null,
            onImport: (_) async => const {},
          ),
        ),
      ),
    );
    expect(find.text('Add from phone'), findsOneWidget);
    expect(
      find.text(PhoneImportSheet.privacyNote),
      findsOneWidget,
    );
    expect(find.text('Mum'), findsOneWidget);
    expect(find.text('Sam Patel'), findsOneWidget);
    expect(find.textContaining('mum@example.com'), findsOneWidget);
    expect(find.textContaining('07700 900000'), findsOneWidget);
    expect(find.text('Import 2'), findsOneWidget);
  });

  testWidgets('kinds flow into the import body; Skip is left out',
      (tester) async {
    List<Map<String, String?>>? sent;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PhoneImportSheet(
            initialPicks: [mum, sam],
            onPickAnother: () async => null,
            onImport: (body) async {
              sent = body;
              return {
                'read': 1,
                'matched': 0,
                'updated': 0,
                'added': 1,
                'skipped': 1,
              };
            },
          ),
        ),
      ),
    );
    // Sam becomes a supplier; Mum is skipped.
    await tester.tap(find.text('Supplier').last);
    await tester.pump();
    await tester.tap(find.text('Skip').first);
    await tester.pump();
    expect(find.text('Import 1'), findsOneWidget);
    await tester.tap(find.text('Import 1'));
    await tester.pumpAndSettle();
    expect(sent, [
      {'name': 'Sam Patel', 'kind': 'supplier', 'email': 'sam@acme.example'},
    ]);
    expect(find.text('Imported 1 contact (0 contacts updated).'),
        findsOneWidget);
    expect(find.text('Done'), findsOneWidget);
  });

  testWidgets('import-all-skipped disables Import', (tester) async {
    var called = false;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PhoneImportSheet(
            initialPicks: [mum],
            onPickAnother: () async => null,
            onImport: (_) async {
              called = true;
              return const {};
            },
          ),
        ),
      ),
    );
    await tester.tap(find.text('Skip'));
    await tester.pump();
    final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Import 0'));
    expect(button.onPressed, isNull);
    expect(called, isFalse);
  });

  testWidgets('Pick another appends; a duplicate is refused', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PhoneImportSheet(
            initialPicks: [mum],
            onPickAnother: () async => sam,
            onImport: (_) async => const {},
          ),
        ),
      ),
    );
    await tester.tap(find.text('Pick another'));
    await tester.pumpAndSettle();
    expect(find.text('Sam Patel'), findsOneWidget);
    expect(find.text('Import 2'), findsOneWidget);
  });

  testWidgets('a repeated pick shows already-in-the-list', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PhoneImportSheet(
            initialPicks: [mum],
            onPickAnother: () async =>
                PickedPhoneContact(name: ' mum '),
            onImport: (_) async => const {},
          ),
        ),
      ),
    );
    await tester.tap(find.text('Pick another'));
    await tester.pumpAndSettle();
    expect(find.text(' mum  is already in the list.'), findsOneWidget);
    expect(find.text('Import 1'), findsOneWidget);
  });

  testWidgets('import failure shows the message and keeps the sheet',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PhoneImportSheet(
            initialPicks: [mum],
            onPickAnother: () async => null,
            onImport: (_) async =>
                throw Exception('Could not reach the reader.'),
          ),
        ),
      ),
    );
    await tester.tap(find.text('Import 1'));
    await tester.pumpAndSettle();
    expect(find.text('Could not reach the reader.'), findsOneWidget);
    expect(find.text('Import 1'), findsOneWidget);
  });

  testWidgets('sheet does not overflow at 360 dp', (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PhoneImportSheet(
            initialPicks: [
              mum,
              PickedPhoneContact(
                name: 'Alexandra Constantinou-Williams',
                emails: const ['alexandra@very-long-company-name.example'],
                phones: const ['+44 7700 900123'],
                address:
                    'Flat 12, 345 Very Long Street Name, London E1 6AN',
              ),
            ],
            onPickAnother: () async => null,
            onImport: (_) async => const {},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Add from phone'), findsOneWidget);
    expect(find.text('Pick another'), findsOneWidget);
    // Any RenderFlex overflow throws during pumpAndSettle above.
  });
}
