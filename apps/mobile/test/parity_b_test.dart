import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:accnomos_mobile/models/storage.dart';
import 'package:accnomos_mobile/screens/business_setup_screen.dart';
import 'package:accnomos_mobile/screens/household_rules_screen.dart';
import 'package:accnomos_mobile/screens/storage_card.dart';
import 'package:accnomos_mobile/screens/vehicles_screen.dart';
import 'package:accnomos_mobile/services/business_prefs.dart';
import 'package:accnomos_mobile/services/file_picker.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:accnomos_mobile/widgets/statement_import.dart';

/// Parity with the web for Vehicles, the household Budget's categories and
/// rules, Bank statement import, Business setup and Files › Clean up: the
/// same routes and bodies as apps/web/src/lib/runtime.ts.
void main() {
  late List<http.Request> requested;
  late Map<String, Object? Function(http.Request)> routes;

  http.Response jsonResponse(Object? body, [int status = 200]) => http.Response(
        body == null ? '' : json.encode(body),
        body == null ? 204 : status,
        headers: {'content-type': 'application/json'},
      );

  RuntimeClient client() => RuntimeClient(
        AppSettings(runtimeUrl: 'http://reader'),
        books: BooksAuth(graphToken: 'tok', accountKind: 'personal', user: 'sam@example.co.uk'),
        httpClient: MockClient((request) async {
          requested.add(request);
          final key = '${request.method} ${request.url.path}';
          final handler = routes[key];
          if (handler == null) return http.Response('{"detail":"not found $key"}', 404);
          final out = handler(request);
          if (out is http.Response) return out;
          return jsonResponse(out);
        }),
      );

  setUp(() {
    requested = [];
    routes = {};
    SharedPreferences.setMockInitialValues({});
  });

  Future<void> pumpAt360(WidgetTester tester, Widget child) async {
    tester.view.physicalSize = const Size(360 * 3, 780 * 3);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(home: child));
    await tester.pumpAndSettle();
  }

  group('household categories and rules', () {
    final cats = [
      {'id': 'groceries', 'name': 'Groceries'},
      {'id': 'eating_out', 'name': 'Eating out'},
      {'id': 'other', 'name': 'Other'},
    ];
    final rules = [
      {'id': 'r1', 'match': {'op': 'contains', 'value': 'tesco'}, 'category_id': 'groceries'},
      {'id': 'r2', 'match': {'op': 'contains', 'value': 'costa'}, 'category_id': 'eating_out'},
    ];

    setUp(() {
      routes['GET /personal/categories'] = (_) => cats;
      routes['GET /personal/rules'] = (_) => rules;
      routes['GET /books/bank/lines'] = (_) => [
            {
              'id': 'l1',
              'date': '2026-11-02',
              'description': 'SCHOOL UNIFORM SHOP',
              'amount_pence': -4599,
              'household_sorted': false,
            },
          ];
    });

    testWidgets('adding a category sends the whole list with the new name and no id', (tester) async {
      routes['PUT /personal/categories'] = (r) => (json.decode(r.body) as Map)['categories'];
      await pumpAt360(tester, HouseholdRulesScreen(clientFor: () async => client()));
      expect(find.text('Groceries'), findsOneWidget);
      // "Other" cannot be removed: two categories have a delete button.
      expect(find.byTooltip('Remove'), findsNWidgets(2));
      await tester.tap(find.byKey(const Key('add-category')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'School');
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();
      final put = requested.lastWhere((r) => r.method == 'PUT');
      final sent = (json.decode(put.body) as Map)['categories'] as List;
      expect(sent.length, 4);
      expect(sent.last, {'name': 'School'});
      expect(find.text('Added the category School.'), findsOneWidget);
    });

    testWidgets('rules show in order and a line can be put in a category by hand', (tester) async {
      routes['POST /personal/lines/l1/category'] = (_) => null;
      await pumpAt360(tester, HouseholdRulesScreen(clientFor: () async => client(), initialTab: 2));
      expect(find.text('SCHOOL UNIFORM SHOP'), findsOneWidget);
      expect(find.textContaining('No category yet'), findsOneWidget);
      await tester.tap(find.text('SCHOOL UNIFORM SHOP'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Groceries').last);
      await tester.pumpAndSettle();
      final post = requested.lastWhere((r) => r.method == 'POST');
      expect(post.url.path, '/personal/lines/l1/category');
      expect(json.decode(post.body), {'category_id': 'groceries'});
    });

    testWidgets('a new rule posts match and category', (tester) async {
      routes['POST /personal/rules'] = (r) => {...(json.decode(r.body) as Map), 'id': 'r3'};
      await pumpAt360(tester, HouseholdRulesScreen(clientFor: () async => client(), initialTab: 1));
      expect(find.text('Description contains "tesco"'), findsOneWidget);
      await tester.tap(find.byKey(const Key('add-rule')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'Pret');
      await tester.tap(find.text('Save rule'));
      await tester.pumpAndSettle();
      final post = requested.lastWhere((r) => r.method == 'POST');
      expect(post.url.path, '/personal/rules');
      expect(json.decode(post.body), {
        'match': {'op': 'contains', 'value': 'Pret'},
        'category_id': 'groceries',
      });
    });
  });

  group('statement import', () {
    test('result sentence', () {
      expect(statementImportResult({'lines': 42, 'new_lines': 40}, 'march.csv'),
          'Imported 42 lines (40 new) from march.csv.');
      expect(statementImportResult({'duplicate_file': true}, 'x.csv'),
          'That statement was already imported — nothing changed.');
    });

    test('picked CSV is uploaded as multipart "file"', () async {
      const channel = MethodChannel('test/files');
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(channel, (call) async {
        expect(call.method, 'pickFile');
        return {'name': 'march.csv', 'bytes': Uint8List.fromList(utf8.encode('Date,Amount\n'))};
      });
      routes['POST /books/bank/import'] = (_) => {'lines': 3, 'new_lines': 3, 'sha256': 'x', 'filed_path': null};
      final note = await pickAndImportStatement(client(), picker: FilePicker(channel: channel));
      expect(note, 'Imported 3 lines (3 new) from march.csv.');
      expect(requested.single.url.path, '/books/bank/import');
      expect(requested.single.headers['content-type'], startsWith('multipart/form-data'));
    });

    test('a non-CSV file is refused before upload', () async {
      const channel = MethodChannel('test/files2');
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(channel, (call) async {
        return {'name': 'statement.pdf', 'bytes': Uint8List(4)};
      });
      final note = await pickAndImportStatement(client(), picker: FilePicker(channel: channel));
      expect(note, contains('CSV'));
      expect(requested, isEmpty);
    });
  });

  group('business setup', () {
    test('working hours must end after they start', () {
      expect(BusinessPrefs.problem('09:00', '08:00'), isNotNull);
      expect(BusinessPrefs.problem('8am', '17:00'), isNotNull);
      expect(BusinessPrefs.problem('08:00', '17:30'), isNull);
      expect(const BusinessPrefs().constraints, {'start': '08:00', 'end': '17:30', 'max_visits': 5});
    });

    testWidgets('staff add posts name and rates in pence; logo uploads', (tester) async {
      routes['GET /staff'] = (_) => <Object>[];
      routes['GET /mail/mailboxes'] = (_) => {'mailboxes': <Object>[]};
      routes['GET /invoices/profile'] = (_) => {'logo_path': null};
      routes['POST /staff'] = (r) => {...(json.decode(r.body) as Map), 'id': 's1'};
      routes['POST /invoices/profile/logo'] = (_) => {'logo_path': '_System/Invoicing/logo.png'};
      await pumpAt360(
        tester,
        BusinessSetupScreen(
          clientFor: () async => client(),
          pickImage: () async => ('logo.png', Uint8List.fromList([0x89, 0x50, 0x4e, 0x47])),
        ),
      );
      await tester.tap(find.byKey(const Key('add-staff')));
      await tester.pumpAndSettle();
      final fields = find.byType(TextField);
      await tester.enterText(fields.at(0), 'Jo Carter');
      await tester.enterText(fields.at(2), '18.50');
      await tester.enterText(fields.at(3), '45');
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();
      final post = requested.firstWhere((r) => r.method == 'POST' && r.url.path == '/staff');
      expect(json.decode(post.body), {
        'name': 'Jo Carter',
        'role': '',
        'hourly_rate_pence': 1850,
        'charge_rate_pence': 4500,
        'active': true,
      });
      await tester.ensureVisible(find.byKey(const Key('choose-logo')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('choose-logo')));
      await tester.pumpAndSettle();
      expect(requested.any((r) => r.url.path == '/invoices/profile/logo'), isTrue);
      expect(find.text('Logo saved. It prints on your invoices.'), findsOneWidget);
    });

    testWidgets('a work account can link a shared mailbox', (tester) async {
      routes['GET /staff'] = (_) => <Object>[];
      routes['GET /mail/mailboxes'] = (_) => {'mailboxes': <Object>[]};
      routes['GET /invoices/profile'] = (_) => <String, Object>{};
      routes['POST /mail/mailboxes'] = (r) => {...(json.decode(r.body) as Map), 'id': 'm1'};
      await pumpAt360(tester, BusinessSetupScreen(clientFor: () async => client(), workAccount: true));
      await tester.ensureVisible(find.byKey(const Key('add-mailbox')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('add-mailbox')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField).first, 'invoices@firm.co.uk');
      await tester.tap(find.text('Link mailbox'));
      await tester.pumpAndSettle();
      final post = requested.lastWhere((r) => r.method == 'POST');
      expect(json.decode(post.body), {
        'address': 'invoices@firm.co.uk',
        'folder': 'all',
        'allow_senders': <String>[],
        'deny_senders': <String>[],
        'kind': 'shared',
      });
    });
  });

  group('files clean up', () {
    final overview = {
      'total_files': 3,
      'total_bytes': 3000,
      'folders': <Object>[],
      'years': <Object>[],
      'largest': <Object>[],
      'duplicates': [
        {
          'hash': 'h',
          'size': 1000,
          'files': [
            {'path': '01 Receipts/a.pdf', 'size': 1000, 'keep': true, 'linked': false, 'protected': false},
            {'path': '01 Receipts/a (1).pdf', 'size': 1000, 'keep': false, 'linked': false, 'protected': false},
            {'path': '01 Receipts/a (2).pdf', 'size': 1000, 'keep': false, 'linked': true, 'protected': false},
          ],
        },
      ],
      'duplicate_bytes': 1000,
      'truncated': false,
    };

    test('only unlinked extra copies are cleaned up', () {
      expect(StorageOverview.fromJson(overview).cleanUpPaths, ['01 Receipts/a (1).pdf']);
    });

    testWidgets('Clean up moves the copies to _Trash', (tester) async {
      routes['GET /files/overview'] = (_) => overview;
      routes['POST /files/trash'] = (r) => {
            'moved': [
              {'from': '01 Receipts/a (1).pdf', 'to': '_Trash/x'},
            ],
          };
      await pumpAt360(tester, Scaffold(body: SingleChildScrollView(child: StorageCard(clientFor: () async => client()))));
      await tester.tap(find.byKey(const Key('storage-clean-up')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Move to _Trash'));
      await tester.pumpAndSettle();
      final post = requested.firstWhere((r) => r.method == 'POST');
      expect(json.decode(post.body), {
        'paths': ['01 Receipts/a (1).pdf'],
      });
      expect(find.text('Moved 1 copy to _Trash.'), findsOneWidget);
    });
  });

  group('vehicles', () {
    testWidgets('the vehicle sheet sends kind and owner; delete is offered when editing', (tester) async {
      Map<String, dynamic>? saved;
      await pumpAt360(
        tester,
        Scaffold(
          body: VehicleSheet(
            vehicle: const {'id': 'v1', 'name': 'Van', 'kind': 'van', 'owned_by': 'business', 'active': true},
            save: (b) async => saved = b,
            delete: () async {},
          ),
        ),
      );
      expect(find.text('Delete vehicle'), findsOneWidget);
      await tester.enterText(find.byType(TextField).at(1), 'ab12 cde');
      await tester.tap(find.text('Save vehicle'));
      await tester.pumpAndSettle();
      expect(saved, {
        'name': 'Van',
        'registration': 'AB12 CDE',
        'kind': 'van',
        'owned_by': 'business',
        'active': true,
      });
    });

    test('miles text', () {
      expect(milesText(12.0), '12');
      expect(milesText(12.5), '12.5');
    });
  });
}
