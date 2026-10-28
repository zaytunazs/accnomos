import 'package:accnomos_mobile/models/accountant.dart';
import 'package:accnomos_mobile/screens/accountant_screen.dart';
import 'package:accnomos_mobile/screens/more_screen.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:msal_auth/msal_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Your accountant on the phone: read-only, from `GET /accountant` and
/// `GET /queries` (services/runtime/app/routes_accountant.py), at 360 dp.
void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  void usePhoneSurface(WidgetTester tester) {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
  }

  Widget screen(_Fake fake) => MaterialApp(
    home: AccountantScreen(
      testAccount: _account,
      testAccountReady: true,
      clientFactory: (settings, books) => fake,
    ),
  );

  testWidgets('shows who has access and the queries, with nothing to edit', (
    tester,
  ) async {
    usePhoneSurface(tester);
    await tester.pumpWidget(screen(_Fake()));
    await tester.pumpAndSettle();

    expect(find.text('Ana Okafor (ana@firm.example)'), findsOneWidget);
    expect(
      find.textContaining('View only · since 20 Oct 2026'),
      findsOneWidget,
    );
    expect(find.text('Accnomos accountants'), findsOneWidget);
    expect(find.text('old@firm.example'), findsNothing); // revoked
    expect(find.text('Queries · 1 waiting on you'), findsOneWidget);
    expect(find.text('A document: October rent receipt'), findsOneWidget);
    expect(find.text('Is this rent for Flat 2?'), findsOneWidget);
    expect(find.text('Waiting on you'), findsOneWidget);
    expect(
      find.text('Old question'),
      findsNothing,
    ); // resolved, hidden until asked
    expect(find.byType(TextField), findsNothing); // read-only: no reply box
    expect(find.byType(FilledButton), findsNothing);

    await tester.scrollUntilVisible(find.text('Show resolved (1)'), 200);
    await tester.tap(find.text('Show resolved (1)'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Old question'), 200);
    expect(find.text('Old question'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('nobody invited and no queries', (tester) async {
    usePhoneSurface(tester);
    await tester.pumpWidget(screen(_Fake(empty: true)));
    await tester.pumpAndSettle();
    expect(find.text('Nobody: your books are not shared.'), findsOneWidget);
    expect(find.text('No open queries.'), findsOneWidget);
  });

  testWidgets('an error is shown, not a crash', (tester) async {
    usePhoneSurface(tester);
    await tester.pumpWidget(screen(_Fake(fail: true)));
    await tester.pumpAndSettle();
    expect(
      find.textContaining('Could not load your accountant'),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('More lists Your accountant', (tester) async {
    usePhoneSurface(tester);
    await tester.pumpWidget(const MaterialApp(home: MoreScreen()));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.text('Your accountant'), 200);
    expect(find.text('Your accountant'), findsOneWidget);
  });

  test('parsing keeps active invitations and labels queries', () {
    final access = AccountantAccess.activeFrom(_settings);
    expect(access.map((a) => a.email), [
      'ana@firm.example',
      'reviews@accnomos.example',
    ]);
    expect(access.first.access, 'View only');
    expect(access.last.team, isTrue);
    final q = ClientQuery.fromJson(_queries.first)!;
    expect(q.waitingOnYou, isTrue);
    expect(q.messages.single.fromAccountant, isTrue);
    expect(ClientQuery.fromJson({'id': ''}), isNull);
  });
}

final _account = Account(
  id: '1',
  username: 'sam@sambuilds.example',
  name: 'Sam',
);

final _settings = <String, dynamic>{
  'invitations': [
    {
      'id': 'a',
      'kind': 'own',
      'email': 'ana@firm.example',
      'name': 'Ana Okafor',
      'role': 'read',
      'method': 'graph',
      'invited_at': '2026-10-20T09:00:00Z',
      'revoked_at': null,
    },
    {
      'id': 'b',
      'kind': 'team',
      'email': 'reviews@accnomos.example',
      'name': 'Accnomos accountants',
      'role': 'edit',
      'method': 'graph',
      'invited_at': '2026-10-21T09:00:00Z',
      'revoked_at': null,
    },
    {
      'id': 'c',
      'kind': 'own',
      'email': 'old@firm.example',
      'name': '',
      'role': 'edit',
      'method': 'graph',
      'invited_at': '2026-01-01T09:00:00Z',
      'revoked_at': '2026-02-01T09:00:00Z',
    },
  ],
};

final _queries = <Map<String, dynamic>>[
  {
    'id': 'a1b2c3d4e5f6',
    'subject': {
      'kind': 'document',
      'ref': '01 Receipts/2026-10/rent.pdf',
      'label': 'October rent receipt',
    },
    'status': 'open',
    'waiting_on': 'client',
    'messages': [
      {
        'ts': '2026-10-20T09:00:00Z',
        'author': 'ana@firm.example',
        'role': 'accountant',
        'text': 'Is this rent for Flat 2?',
      },
    ],
  },
  {
    'id': 'b1b2c3d4e5f6',
    'subject': {'kind': 'general', 'ref': '', 'label': ''},
    'status': 'resolved',
    'waiting_on': null,
    'messages': [
      {
        'ts': '2026-09-01T09:00:00Z',
        'author': 'ana@firm.example',
        'role': 'accountant',
        'text': 'Old question',
      },
    ],
  },
];

class _Fake extends RuntimeClient {
  _Fake({this.empty = false, this.fail = false})
    : super(AppSettings(runtimeUrl: 'http://reader:8780'));

  final bool empty;
  final bool fail;

  @override
  Future<Map<String, dynamic>> accountant() async {
    if (fail) throw Exception('Could not load your accountant (502).');
    return empty ? {'invitations': []} : _settings;
  }

  @override
  Future<List<Map<String, dynamic>>> queries({String? status}) async =>
      empty ? [] : _queries;
}
