import 'package:accnomos_mobile/screens/import_contacts_screen.dart';
import 'package:accnomos_mobile/services/phone_contacts.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// Contacts › Import contacts: all or a chosen few, from the phone, Outlook
/// or the people who email you. Rows already in the books start unticked.
void main() {
  const channel = MethodChannel('accnomos/phone-contacts');

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  final phone = [
    PickedPhoneContact(name: 'Lucy Bennett', company: 'Bennett Kitchens Ltd', emails: const ['lucy@bk.example']),
    PickedPhoneContact(name: 'George Palmer', phones: const ['07700 900303']),
    PickedPhoneContact(name: 'Tom Bradley', company: 'Sterling & Co. Architects'),
  ];

  Map<String, dynamic> cand(String name, {String? person, bool existing = false, String kind = 'customer'}) => {
        'ref': name,
        'source': 'phone',
        'name': name,
        'person': person,
        'existing_id': existing ? 'c1' : null,
        'existing_name': existing ? name : null,
        'match': existing ? 'same name' : null,
        'kind': kind,
      };

  test('phone rows use the company as the name and keep the person', () {
    final rows = phoneRows(phone);
    expect(rows[0], {'name': 'Bennett Kitchens Ltd', 'person': 'Lucy Bennett', 'email': 'lucy@bk.example'});
    expect(rows[1], {'name': 'George Palmer', 'phone': '07700 900303'});
  });

  test('listAll reads every contact from the channel', () async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(channel, (call) async {
      expect(call.method, 'listContacts');
      return [
        {'name': 'Lucy Bennett', 'company': 'Bennett Kitchens Ltd', 'emails': ['lucy@bk.example'], 'phones': []},
        {'name': '', 'emails': [], 'phones': []},
      ];
    });
    final all = await PhoneContacts().listAll();
    expect(all, hasLength(1));
    expect(all.single.company, 'Bennett Kitchens Ltd');
    expect(all.single.email, 'lucy@bk.example');
  });

  testWidgets('phone list: existing rows unticked, select all, clear, kinds, import summary', (tester) async {
    List<Map<String, dynamic>>? checked;
    List<Map<String, dynamic>>? saved;
    String? savedSource;
    final api = ImportContactsApi(
      listPhone: () async => phone,
      check: (rows) async {
        checked = rows;
        return {
          'note': "From this phone's address book. Nothing is written back to the phone.",
          'candidates': [
            cand('Bennett Kitchens Ltd', person: 'Lucy Bennett'),
            cand('George Palmer'),
            cand('Sterling & Co. Architects', person: 'Tom Bradley', existing: true),
          ],
        };
      },
      preview: (_) async => {'candidates': const []},
      save: (source, rows) async {
        savedSource = source.id;
        saved = rows;
        return {'message': 'Imported ${rows.length}.'};
      },
    );
    await tester.pumpWidget(MaterialApp(home: ImportContactsScreen(api: api)));
    await tester.pumpAndSettle();

    expect(checked, hasLength(3));
    expect(find.textContaining('Already in your books'), findsOneWidget);
    expect(find.text('2 new · 1 already in your books · 2 ticked'), findsOneWidget);
    expect(find.text('Import 2'), findsOneWidget);

    await tester.tap(find.text('Select all'));
    await tester.pump();
    expect(find.text('Import 3'), findsOneWidget);
    await tester.tap(find.text('Clear'));
    await tester.pump();
    final button = tester.widget<FilledButton>(find.byKey(const Key('import-save')));
    expect(button.onPressed, isNull);
    expect(find.text('Import 0'), findsOneWidget);

    // Tick George only and make him a supplier.
    await tester.tap(find.byType(Checkbox).at(1));
    await tester.pump();
    await tester.tap(find.text('Customer').at(1));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Supplier').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Import 1'));
    await tester.pumpAndSettle();

    expect(savedSource, 'phone');
    expect(saved, [
      {'name': 'George Palmer', 'kind': 'supplier'},
    ]);
    expect(find.text('Contacts imported'), findsOneWidget);
    expect(find.text('Imported 1.'), findsOneWidget);
  });

  testWidgets('Outlook and email sources load from the runtime; permission refusal says why', (tester) async {
    final asked = <String>[];
    final api = ImportContactsApi(
      listPhone: () async => throw PlatformException(code: 'DENIED'),
      check: (_) async => {'candidates': const []},
      preview: (source) async {
        asked.add(source.id);
        return {
          'note': source == ImportSource.email ? 'People who emailed you in the last 180 days.' : 'Outlook.',
          'candidates': [
            {...cand('Jo Plumb'), 'email': 'jo@plumb.example', 'messages': 3},
          ],
        };
      },
      save: (_, rows) async => {'message': 'Imported ${rows.length}.'},
    );
    await tester.pumpWidget(MaterialApp(home: ImportContactsScreen(api: api)));
    await tester.pumpAndSettle();
    expect(find.textContaining('permission to read your contacts'), findsOneWidget);

    await tester.tap(find.text('Email'));
    await tester.pumpAndSettle();
    expect(asked, ['email']);
    expect(find.text('jo@plumb.example · 3 emails'), findsOneWidget);
    expect(find.text('Import 1'), findsOneWidget);

    await tester.tap(find.text('Outlook'));
    await tester.pumpAndSettle();
    expect(asked, ['email', 'outlook']);
  });
}
