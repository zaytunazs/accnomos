import 'dart:convert';

import 'package:accnomos_mobile/main.dart' show sampleBannerText, shellDestinations;
import 'package:accnomos_mobile/models/goals.dart';
import 'package:accnomos_mobile/models/household.dart';
import 'package:accnomos_mobile/screens/goals_screen.dart';
import 'package:accnomos_mobile/screens/household_home_screen.dart';
import 'package:accnomos_mobile/screens/more_screen.dart';
import 'package:accnomos_mobile/services/app_mode.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:msal_auth/msal_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The household treatment (personal books get their own tabs, More and
/// Home, as the web does) and Goals (`/books/goals`, the same paths and
/// bodies as the web's lib/goals.ts).

Map<String, dynamic> goalJson({
  String id = 'g1',
  String name = 'School fees',
  String kind = 'save',
  String status = 'off_track',
  String label = 'Off track',
  String tone = 'negative',
  int current = 9000,
  int? target = 100000,
  int? plan = 17000,
}) =>
    {
      'goal': {
        'id': id,
        'name': name,
        'kind': kind,
        'start': '2026-09-01',
        'end': '2027-09-01',
        'measure': 'manual',
        'saved_pence': current,
      },
      'kind_label': 'Savings goal',
      'status': status,
      'status_label': label,
      'tone': tone,
      'period_label': '1 Sep 2026 – 1 Sep 2027',
      'current_pence': current,
      'target_pence': target,
      'target_label': '£1,000.00 target',
      'plan_to_date_pence': plan,
      'percent': 9,
      'variance_text': '£80.00 behind plan to date.',
      'needed_text': '£910.00 still to go: about £91.00 a month.',
      'run_rate_pence': null,
      'days_left': 300,
      'source_text': 'The amount you have recorded as put aside',
      'drivers': [
        {
          'name': 'Caffe Nero',
          'kind': 'supplier',
          'this_pence': 12975,
          'before_pence': 4835,
          'change_pence': 8140,
        }
      ],
      'suggestions': ['Record what you put aside as you go.'],
    };

Map<String, dynamic> goalsJson(List<Map<String, dynamic>> goals) => {
      'today': '2026-11-10',
      'household': true,
      'goals': goals,
      'note': {
        'note_md': 'School fees is off track.',
        'model': 'muse-spark-1.3',
        'fallback_reason': null,
      },
      'facts': {},
    };

void main() {
  const channel = MethodChannel('msal_auth');

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    AppMode.reset();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      throw PlatformException(code: 'NO_CURRENT_ACCOUNT', message: 'no');
    });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
    AppMode.reset();
  });

  group('treatment', () {
    test('personal books are the household app; business kinds are not', () {
      expect(const ModeState(signedIn: true, kind: 'personal').household, isTrue);
      expect(const ModeState(signedIn: true, kind: 'company').household, isFalse);
      expect(const ModeState(signedIn: true, kind: 'sole_trader').household, isFalse);
      expect(const ModeState(signedIn: true).household, isFalse);
      expect(const ModeState(sample: 'household').household, isTrue);
      expect(const ModeState().household, isFalse);
      // Signed in, the profile decides, not a sample left switched on.
      expect(
          const ModeState(signedIn: true, kind: 'company', sample: 'household')
              .household,
          isFalse);
    });

    test('household tabs: Budget and Goals, and no VAT tab', () {
      final household = [
        for (final d in shellDestinations(household: true)) d.label
      ];
      final business = [
        for (final d in shellDestinations(household: false)) d.label
      ];
      expect(household, ['Home', 'Review', 'Budget', 'Goals', 'More']);
      expect(business, ['Home', 'Review', 'Ask', 'VAT', 'More']);
    });

    test('the banner follows the sample', () {
      expect(sampleBannerText(household: true), contains('FICTIONAL HOUSEHOLD'));
      expect(sampleBannerText(household: false), contains('FICTIONAL COMPANY'));
    });

    test('household More: Ask moves here, nothing business-only', () {
      final titles = [
        for (final e in moreEntries(null, household: true)) e.title
      ];
      expect(titles, containsAll(['Ask', 'Bank', 'Files', 'Contacts', 'Audit trail']));
      for (final business in [
        'Invoices', 'Jobs', 'Vehicles', 'Payroll', 'Month-end', 'Reports',
        'Your accountant', 'Personal',
      ]) {
        expect(titles, isNot(contains(business)));
      }
    });

    test('business More gains Goals and keeps everything else', () {
      final titles = [for (final e in moreEntries(null)) e.title];
      expect(titles, contains('Goals'));
      expect(titles, contains('Invoices'));
    });
  });

  group('goals data', () {
    test('parses the runtime view and orders the most urgent first', () {
      final data = GoalsData.fromJson(goalsJson([
        goalJson(id: 'a', name: 'On track one', status: 'on_track', label: 'On track', tone: 'positive'),
        goalJson(id: 'b', name: 'At risk one', status: 'at_risk', label: 'At risk', tone: 'warning'),
        goalJson(id: 'c', name: 'Over one', status: 'over_limit', label: 'Over limit'),
      ]));
      expect(data.household, isTrue);
      expect([for (final g in data.mostUrgentFirst) g.name],
          ['Over one', 'At risk one', 'On track one']);
      final g = data.goals.first;
      expect(g.id, 'a');
      expect(g.currentPence, 9000);
      expect(g.planToDatePence, 17000);
      expect(g.runRatePence, isNull);
      expect(g.drivers.single.changePence, 8140);
      expect(data.note.byLine, contains('every number checked'));
    });

    test('money and the refused-request sentence', () {
      expect(money(123456), '£1,234.56');
      expect(money(-50), '−£0.50');
      expect(moneyShort(9000), '£90');
      expect(moneyShort(9050), '£90.50');
      expect(
          goalError(RuntimeException(
              'The reader refused that request (status 422). {"detail":"the end date is before the start date"}')),
          'the end date is before the start date');
      expect(
          goalError(RuntimeException(
              'The reader refused that request (status 422). {"detail":[{"msg":"Value error, give the target amount"}]}')),
          'give the target amount');
      expect(parsePounds('£1,200.50'), 120050);
      expect(parsePounds('abc'), isNull);
    });

    test('sample goals are labelled fictional for both samples', () {
      final household = sampleGoals(household: true);
      final company = sampleGoals(household: false);
      expect(household.sample && company.sample, isTrue);
      expect(household.goals.map((g) => g.name), contains('School fees'));
      expect(company.goals.map((g) => g.kind), contains('earn'));
    });
  });

  group('goals client', () {
    RuntimeClient client() => RuntimeClient(
          AppSettings(runtimeUrl: 'http://reader'),
          books: BooksAuth(
              graphToken: 'tok', accountKind: 'personal', user: 'u@x.com'),
        );
    final captured = <http.Request>[];
    MockClient mock(Object body, {int status = 200}) {
      captured.clear();
      return MockClient((request) async {
        captured.add(request);
        return http.Response(json.encode(body), status,
            headers: {'content-type': 'application/json'});
      });
    }

    test('goals, add, patch and delete use the web paths', () async {
      await http.runWithClient(
          () => client().goals(today: '2026-11-10'), () => mock(goalsJson([])));
      expect(captured.single.url.path, '/books/goals');
      expect(captured.single.url.queryParameters['today'], '2026-11-10');

      await http.runWithClient(
          () => client().addGoal({'name': 'X', 'kind': 'save'}),
          () => mock({'id': 'g1'}));
      expect(captured.single.method, 'POST');
      expect(json.decode(captured.single.body), {'name': 'X', 'kind': 'save'});

      await http.runWithClient(() => client().patchGoal('g1', {'saved_pence': 500}),
          () => mock({'id': 'g1'}));
      expect(captured.single.method, 'PATCH');
      expect(captured.single.url.path, '/books/goals/g1');

      await http.runWithClient(() => client().deleteGoal('g1'), () => mock(''));
      expect(captured.single.method, 'DELETE');
    });
  });

  group('screens', () {
    final account = Account(id: '1', username: 'sam@example.com', name: 'Sam Patel');

    void phone(WidgetTester tester) {
      tester.view.physicalSize = const Size(360, 2600);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
    }

    testWidgets('household Home: tiles, this month, budgets, goals, bills',
        (tester) async {
      phone(tester);
      final fake = _HouseholdFake();
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: HouseholdHomeScreen(
            testAccount: account,
            testAccountReady: true,
            today: DateTime(2026, 11, 10),
            clientFactory: (_) => fake,
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(fake.months, containsAll(['2026-11', '2026-10']));
      expect(find.text('Hello, Sam'), findsOneWidget);
      expect(find.text('Receipts to review'), findsOneWidget);
      expect(find.text('Budgets over'), findsOneWidget);
      expect(find.text('This month'), findsOneWidget);
      expect(find.text('Money in'), findsOneWidget);
      expect(find.text('Up £100.00 on last month'), findsOneWidget);
      expect(find.text('Coffee'), findsWidgets);
      expect(find.text('£10.00 over budget'), findsOneWidget);
      expect(find.text('School fees'), findsOneWidget);
      expect(find.text('What your goals are telling you'), findsOneWidget);
      expect(find.text('NETFLIX'), findsOneWidget);
      // A stopped bill and one past 30 days are left out.
      expect(find.text('OLD GYM'), findsNothing);
      expect(find.text('CAR INSURANCE'), findsNothing);
      // Nothing about VAT or turnover in a household Home.
      expect(find.textContaining('VAT'), findsNothing);
      expect(find.textContaining('urnover'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('household Home signed out shows the fictional sample',
        (tester) async {
      phone(tester);
      AppMode.reset(const ModeState(sample: 'household'));
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(
          body: HouseholdHomeScreen(testAccountReady: true),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Your household at a glance'), findsOneWidget);
      expect(find.text('Household sample'), findsOneWidget);
      expect(find.text('This month'), findsOneWidget);
      expect(find.text('Spend less on coffee'), findsOneWidget);
      // Switching to the company sample changes the treatment.
      await tester.tap(find.text('Company sample'));
      await tester.pumpAndSettle();
      expect(AppMode.household, isFalse);
      expect(tester.takeException(), isNull);
    });

    testWidgets('Goals: list, add a goal (refusal shown), record money put aside',
        (tester) async {
      phone(tester);
      final fake = _HouseholdFake();
      await tester.pumpWidget(MaterialApp(
        home: GoalsScreen(
          testAccount: account,
          testAccountReady: true,
          today: DateTime(2026, 11, 10),
          clientFactory: (_) => fake,
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Goals & progress'), findsOneWidget);
      expect(find.text('School fees'), findsOneWidget);
      expect(find.text('Off track'), findsOneWidget);
      expect(find.text('£90'), findsOneWidget);
      expect(find.text('Plan to date: £170.00'), findsOneWidget);

      // Add: the runtime refuses once, and its sentence shows in the sheet.
      await tester.tap(find.text('Add a goal'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('goal-name')), 'Holiday');
      await tester.enterText(find.byKey(const Key('goal-amount')), '600');
      fake.refuseNextAdd = true;
      await tester.tap(find.byKey(const Key('goal-save')));
      await tester.pumpAndSettle();
      expect(find.text('a goal can run for at most three years'), findsOneWidget);
      await tester.tap(find.byKey(const Key('goal-save')));
      await tester.pumpAndSettle();
      expect(fake.added?['name'], 'Holiday');
      expect(fake.added?['kind'], 'save');
      expect(fake.added?['target_pence'], 60000);
      expect(fake.added?['measure'], 'manual');

      // Details: record £50 more put aside.
      await tester.tap(find.text('View details →'));
      await tester.pumpAndSettle();
      expect(find.text('Biggest movers'), findsOneWidget);
      await tester.enterText(find.byKey(const Key('goal-put-aside')), '50');
      await tester.tap(find.text('Record it'));
      await tester.pumpAndSettle();
      expect(fake.patched, {'saved_pence': 14000});
      expect(tester.takeException(), isNull);
    });

    testWidgets('Goals signed out: sample goals, labelled, no add button',
        (tester) async {
      phone(tester);
      AppMode.reset(const ModeState(sample: 'company'));
      await tester.pumpWidget(const MaterialApp(
        home: GoalsScreen(testAccountReady: true),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Sample — fictional company figures'), findsOneWidget);
      expect(find.text('November sales'), findsOneWidget);
      expect(find.text('Add a goal'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  });
}

class _HouseholdFake extends RuntimeClient {
  _HouseholdFake() : super(AppSettings(runtimeUrl: 'http://reader:8780'));

  final months = <String?>[];
  Map<String, dynamic>? added;
  Map<String, dynamic>? patched;
  bool refuseNextAdd = false;

  @override
  Future<Map<String, dynamic>> personalSummary({String? month}) async {
    months.add(month);
    final last = month == '2026-10';
    return {
      'month': month,
      'lines': 40,
      'income_pence': last ? 200000 : 210000,
      'spent_pence': last ? 150000 : 120000,
      'left_pence': last ? 50000 : 90000,
      'uncategorised_count': 2,
      'categories': [
        {'id': 'groceries', 'name': 'Groceries', 'spent_pence': 24000, 'budget_pence': 30000, 'remaining_pence': 6000, 'percent': 80, 'state': 'near'},
        {'id': 'coffee', 'name': 'Coffee', 'spent_pence': 5000, 'budget_pence': 4000, 'remaining_pence': -1000, 'percent': 125, 'state': 'over'},
        {'id': 'other', 'name': 'Other', 'spent_pence': 3000, 'budget_pence': null, 'remaining_pence': null, 'percent': null, 'state': 'none'},
      ],
    };
  }

  @override
  Future<Map<String, dynamic>> personalRecurring() async => {
        'items': [
          {'label': 'NETFLIX', 'category_name': 'Subscriptions', 'amount_pence': 1099, 'next_due': '2026-11-14', 'days_until': 4, 'cadence': 'monthly', 'status': 'active'},
          {'label': 'OLD GYM', 'category_name': 'Health', 'amount_pence': 2000, 'next_due': '2026-11-12', 'days_until': 2, 'cadence': 'monthly', 'status': 'stopped'},
          {'label': 'CAR INSURANCE', 'category_name': 'Insurance', 'amount_pence': 40000, 'next_due': '2027-03-01', 'days_until': 111, 'cadence': 'annual', 'status': 'active'},
        ],
        'note': 'Estimates from your imported statements.',
      };

  @override
  Future<Map<String, dynamic>> goals({String? today}) async =>
      goalsJson([goalJson()]);

  @override
  Future<Map<String, dynamic>> addGoal(Map<String, dynamic> goal) async {
    if (refuseNextAdd) {
      refuseNextAdd = false;
      throw RuntimeException(
          'The reader refused that request (status 422). {"detail":"a goal can run for at most three years"}');
    }
    added = goal;
    return {'id': 'g2', ...goal};
  }

  @override
  Future<Map<String, dynamic>> patchGoal(
      String id, Map<String, dynamic> changes) async {
    patched = changes;
    return {'id': id};
  }

  @override
  Future<Map<String, dynamic>> dashboard({String? today}) async => {
        'attention': {'total': 3, 'proposed': 2, 'needs_a_look': 1},
      };

  @override
  Future<Map<String, dynamic>> home({String? today}) async => {};
}
