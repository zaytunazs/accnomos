import 'dart:convert';

import 'package:accnomos_mobile/screens/more_screen.dart';
import 'package:accnomos_mobile/screens/personal_screen.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:msal_auth/msal_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Personal finances cover: the `/personal/*` calls hit the same paths
/// and bodies as the web's `personal` in `apps/web/src/lib/runtime.ts`,
/// and the screen renders the month summary, budget states, recurring
/// bills and goals at 360 dp with no overflow. A recording mock stands
/// in for the reader; a fake client answers the screen without network
/// or MSAL.
void main() {
  RuntimeClient client() => RuntimeClient(
        AppSettings(runtimeUrl: 'http://reader'),
        books: BooksAuth(
          graphToken: 'tok',
          accountKind: 'personal',
          user: 'user@example.com',
        ),
      );

  final captured = <http.BaseRequest>[];
  String? lastBody(http.BaseRequest request) =>
      request is http.Request ? request.body : null;

  MockClient mock(Object jsonBody, {int status = 200}) {
    captured.clear();
    return MockClient((request) async {
      captured.add(request);
      final body = jsonBody is String ? jsonBody : json.encode(jsonBody);
      return http.Response(body, status,
          headers: {'content-type': 'application/json'});
    });
  }

  test('personalSummary gets this month by category against budget', () async {
    final summary = await http.runWithClient(
      () => client().personalSummary(month: '2026-10'),
      () => mock({
        'month': '2026-10',
        'income_pence': 250000,
        'spent_pence': 180000,
        'left_pence': 70000,
        'categories': [],
      }),
    );
    expect(summary['left_pence'], 70000);
    final request = captured.single;
    expect(request.method, 'GET');
    expect(request.url.path, '/personal/summary');
    expect(request.url.queryParameters['month'], '2026-10');
  });

  test('personalSummary omits the month when not picked', () async {
    await http.runWithClient(
      () => client().personalSummary(),
      () => mock({'month': '2026-10'}),
    );
    expect(
        captured.single.url.queryParameters.containsKey('month'), isFalse);
  });

  test('personalBudgets reads the category budgets', () async {
    final budgets = await http.runWithClient(
      () => client().personalBudgets(),
      () => mock({'groceries': 30000}),
    );
    expect(budgets['groceries'], 30000);
    final request = captured.single;
    expect(request.method, 'GET');
    expect(request.url.path, '/personal/budgets');
  });

  test('savePersonalBudgets puts the whole web-shaped map', () async {
    final saved = await http.runWithClient(
      () => client().savePersonalBudgets({'groceries': 25000}),
      () => mock({'groceries': 25000}),
    );
    expect(saved['groceries'], 25000);
    final request = captured.single;
    expect(request.method, 'PUT');
    expect(request.url.path, '/personal/budgets');
    expect(json.decode(lastBody(request)!), {
      'budgets': {'groceries': 25000}
    });
  });

  test('personalRecurring reads the bills and their note', () async {
    final recurring = await http.runWithClient(
      () => client().personalRecurring(),
      () => mock({
        'items': [],
        'monthly_total_pence': 0,
        'note': 'Estimates from your imported statements.',
      }),
    );
    expect(recurring['monthly_total_pence'], 0);
    final request = captured.single;
    expect(request.method, 'GET');
    expect(request.url.path, '/personal/recurring');
  });

  test('personalGoals reads the goal plans as a list', () async {
    final goals = await http.runWithClient(
      () => client().personalGoals(),
      () => mock([
        {'goal': {'name': 'Holiday'}, 'monthly_needed_pence': 11250},
      ]),
    );
    expect(goals.single['monthly_needed_pence'], 11250);
    final request = captured.single;
    expect(request.method, 'GET');
    expect(request.url.path, '/personal/goals');
  });

  group('PersonalScreen', () {
    final account =
        Account(id: '1', username: 'user@example.com', name: 'Test User');

    setUp(() {
      SharedPreferences.setMockInitialValues({});
    });

    void usePhoneSurface(WidgetTester tester) {
      tester.view.physicalSize = const Size(360, 740);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
    }

    Future<void> pumpScreen(WidgetTester tester, _PersonalFake fake) async {
      usePhoneSurface(tester);
      await tester.pumpWidget(MaterialApp(
        home: PersonalScreen(
          testAccount: account,
          testAccountReady: true,
          clientFactory: (settings, books) => fake,
        ),
      ));
      await tester.pumpAndSettle();
    }

    /// Bring [target] on screen, dragging the page itself: rows below
    /// the fold are not built until the list scrolls near them.
    Future<void> reveal(WidgetTester tester, Finder target) async {
      await tester.dragUntilVisible(
          target, find.byType(ListView), const Offset(0, -300));
      await tester.pumpAndSettle();
    }

    testWidgets('summary renders money in, out and left over', (tester) async {
      await pumpScreen(tester, _PersonalFake());
      expect(find.text('October 2026'), findsOneWidget);
      expect(find.text('Money in'), findsOneWidget);
      expect(find.text('Money out'), findsOneWidget);
      expect(find.text('Left over'), findsOneWidget);
      expect(find.text('£2500.00'), findsOneWidget);
      expect(find.text('£1800.00'), findsOneWidget);
      expect(find.text('£700.00'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('budget rows carry state semantics labels', (tester) async {
      await pumpScreen(tester, _PersonalFake());
      // The row is one tappable tile, so the screen reader hears the
      // title, figures and bar label together: assert on the Semantics
      // widget the progress bar carries.
      Finder barLabel(String label) => find.byWidgetPredicate(
            (widget) =>
                widget is Semantics && widget.properties.label == label,
          );
      expect(barLabel('Groceries budget 80 per cent spent'), findsOneWidget);
      expect(barLabel('Transport budget 95 per cent spent'), findsOneWidget);
      expect(
          barLabel('Eating out budget 120 per cent spent'), findsOneWidget);
      expect(barLabel('Subscriptions, no budget set, £15.99 spent'),
          findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('bills show the next due date', (tester) async {
      await pumpScreen(tester, _PersonalFake());
      await reveal(tester, find.text('Recurring bills'));
      expect(find.text('Netflix'), findsOneWidget);
      expect(find.text('next due 12 Nov 2026'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('goals show the monthly amount needed', (tester) async {
      await pumpScreen(tester, _PersonalFake());
      await reveal(tester, find.text('Savings goals'));
      expect(find.text('Holiday'), findsOneWidget);
      expect(find.text('£112.50 a month needed'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('setting a budget puts the whole map', (tester) async {
      final fake = _PersonalFake();
      await pumpScreen(tester, fake);
      await reveal(tester, find.text('Groceries'));
      await tester.tap(find.text('Groceries'));
      await tester.pumpAndSettle();
      await tester.enterText(
          find.byKey(const Key('budgetAmountField')), '250');
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();
      expect(fake.savedBudgets?['groceries'], 25000);
      // The other category keeps its budget: the whole map goes back.
      expect(fake.savedBudgets?['transport'], 20000);
      expect(tester.takeException(), isNull);
    });
  });

  group('MoreScreen Personal entry', () {
    void usePhoneSurface(WidgetTester tester) {
      tester.view.physicalSize = const Size(360, 740);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
    }

    testWidgets('hidden while the setting is off', (tester) async {
      SharedPreferences.setMockInitialValues({});
      usePhoneSurface(tester);
      await tester.pumpWidget(const MaterialApp(home: MoreScreen()));
      await tester.pumpAndSettle();
      expect(find.text('Personal'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('shown while the setting is on', (tester) async {
      SharedPreferences.setMockInitialValues(
          {'accnomos.showPersonal': true});
      usePhoneSurface(tester);
      await tester.pumpWidget(const MaterialApp(home: MoreScreen()));
      await tester.pumpAndSettle();
      // The entry sits below the fold: scroll before asserting.
      await tester.dragUntilVisible(
        find.text('Audit trail'),
        find.byType(ListView),
        const Offset(0, -300),
      );
      await tester.pumpAndSettle();
      expect(find.text('Personal'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });
}

/// Screen fake: a month summary with one budget per state, one bill and
/// one goal. Saving a budget keeps the rest, like the real screen does.
class _PersonalFake extends RuntimeClient {
  _PersonalFake() : super(AppSettings(runtimeUrl: 'http://reader:8780'));

  Map<String, int>? savedBudgets;

  @override
  Future<Map<String, dynamic>> personalSummary({String? month}) async => {
        'month': '2026-10',
        'lines': 42,
        'income_pence': 250000,
        'spent_pence': 180000,
        'left_pence': 70000,
        'budget_total_pence': 70000,
        'categories': [
          {
            'id': 'groceries',
            'name': 'Groceries',
            'spent_pence': 24000,
            'budget_pence': 30000,
            'remaining_pence': 6000,
            'percent': 80,
            'state': 'ok',
          },
          {
            'id': 'transport',
            'name': 'Transport',
            'spent_pence': 19000,
            'budget_pence': 20000,
            'remaining_pence': 1000,
            'percent': 95,
            'state': 'near',
          },
          {
            'id': 'eating_out',
            'name': 'Eating out',
            'spent_pence': 12000,
            'budget_pence': 10000,
            'remaining_pence': -2000,
            'percent': 120,
            'state': 'over',
          },
          {
            'id': 'subscriptions',
            'name': 'Subscriptions',
            'spent_pence': 1599,
            'budget_pence': null,
            'remaining_pence': null,
            'percent': null,
            'state': 'none',
          },
        ],
        'uncategorised_count': 1,
        'uncategorised_pence': 500,
        'notes': [],
      };

  @override
  Future<Map<String, dynamic>> personalBudgets() async =>
      savedBudgets ?? {'groceries': 30000, 'transport': 20000};

  @override
  Future<Map<String, dynamic>> savePersonalBudgets(
      Map<String, int> budgets) async {
    savedBudgets = Map<String, int>.from(budgets);
    return savedBudgets!;
  }

  @override
  Future<Map<String, dynamic>> personalRecurring() async => {
        'items': [
          {
            'key': 'netflix',
            'label': 'Netflix',
            'category_name': 'Subscriptions',
            'cadence': 'monthly',
            'amount_pence': 1599,
            'amount_varies': false,
            'occurrences': 6,
            'last_date': '2026-10-12',
            'next_due': '2026-11-12',
            'days_until': 15,
            'status': 'upcoming',
            'monthly_equivalent_pence': 1599,
          },
        ],
        'monthly_total_pence': 1599,
        'note': 'Estimates from your imported statements.',
      };

  @override
  Future<List<Map<String, dynamic>>> personalGoals() async => [
        {
          'goal': {
            'id': 'goal1',
            'name': 'Holiday',
            'target_pence': 120000,
            'target_date': '2027-06-01',
            'saved_pence': 30000,
          },
          'remaining_pence': 90000,
          'percent': 25,
          'months_left': 8,
          'monthly_needed_pence': 11250,
          'status': 'on_track',
          'projected_date': null,
          'estimate': true,
        },
      ];
}
