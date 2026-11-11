import 'dart:async';

import 'package:accnomos_mobile/main.dart';
import 'package:accnomos_mobile/models/home_summary.dart';
import 'package:accnomos_mobile/screens/goals_screen.dart';
import 'package:accnomos_mobile/screens/home_screen.dart' show SummaryCard;
import 'package:accnomos_mobile/screens/welcome_screen.dart';
import 'package:accnomos_mobile/services/app_mode.dart';
import 'package:accnomos_mobile/services/demo.dart';
import 'package:accnomos_mobile/services/navigation.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:accnomos_mobile/theme.dart';
import 'package:accnomos_mobile/widgets/brand.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:msal_auth/msal_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Sign-out and the logo go where the website's do (Welcome, Home), and the
/// slow AI words never hold the page up: code's summary and goals note show
/// first, with a thin "The AI is writing…" bar until the AI's arrive.
void main() {
  const channel = MethodChannel('msal_auth');

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      throw PlatformException(code: 'NO_CURRENT_ACCOUNT', message: 'no account');
    });
    Demo.debugSet(null);
    AppMode.reset();
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
    AppMode.reset();
  });

  void phone(WidgetTester tester) {
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
  }

  testWidgets('signing out closes every screen and shows the Welcome page',
      (tester) async {
    phone(tester);
    AppMode.reset(const ModeState(signedIn: true, kind: 'company'));
    await tester.pumpWidget(MaterialApp(
        navigatorKey: appNavigatorKey,
        theme: accnomosTheme(),
        home: const LaunchGate(restore: false)));
    expect(find.byType(Shell), findsOneWidget);
    appNavigatorKey.currentState!.push(MaterialPageRoute(
        builder: (_) => const Scaffold(body: Text('Sign in to view'))));
    await tester.pumpAndSettle();
    expect(find.text('Sign in to view'), findsOneWidget);

    await AppNav.signedOut();
    await tester.pumpAndSettle();
    expect(find.text('Sign in to view'), findsNothing);
    expect(find.byType(WelcomeScreen), findsOneWidget);
  });

  testWidgets('the logo goes Home: pushed screens close and the Home tab shows',
      (tester) async {
    final before = AppNav.homeRequests.value;
    await tester.pumpWidget(MaterialApp(
      navigatorKey: appNavigatorKey,
      home: Scaffold(appBar: AppBar(leading: const BrandLeading())),
    ));
    appNavigatorKey.currentState!.push(MaterialPageRoute(
        builder: (_) => const Scaffold(body: Text('Contacts'))));
    await tester.pumpAndSettle();
    expect(find.text('Contacts'), findsOneWidget);
    AppNav.goHome();
    await tester.pumpAndSettle();
    expect(find.text('Contacts'), findsNothing);
    expect(AppNav.homeRequests.value, before + 1);

    // On a root screen the logo itself is the button.
    await tester.tap(find.byKey(const Key('logo-home')));
    await tester.pump();
    expect(AppNav.homeRequests.value, before + 2);
  });

  testWidgets('summary card: thin bar and "writing" line, then the byline',
      (tester) async {
    const code = HomeSummary(
        text: 'You had £18,166.11 in the bank.',
        model: 'code',
        fallbackReason: 'No AI is set up, so code wrote this.');
    await tester.pumpWidget(const MaterialApp(
        home: Scaffold(body: SummaryCard(summary: code, pending: true))));
    expect(find.byKey(const Key('summary-progress')), findsOneWidget);
    expect(find.text('The AI is writing your summary…'), findsOneWidget);
    expect(find.text('You had £18,166.11 in the bank.'), findsOneWidget);

    const ai = HomeSummary(
        text: 'Cash is £18,166.11; 6 receipts wait in Review.',
        model: 'muse-spark-1.3-contributor');
    await tester.pumpWidget(const MaterialApp(
        home: Scaffold(body: SummaryCard(summary: ai))));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('summary-progress')), findsNothing);
    expect(find.textContaining('worded by your AI'), findsOneWidget);
  });

  testWidgets('Goals: the goals show at once with code\'s note; the AI note follows',
      (tester) async {
    phone(tester);
    final fake = _GoalsFake();
    await tester.pumpWidget(MaterialApp(
      home: GoalsScreen(
        testAccount: Account(id: '1', username: 'sam@example.com', name: 'Sam'),
        testAccountReady: true,
        today: DateTime(2026, 11, 10),
        clientFactory: (_) => fake,
      ),
    ));
    await tester.pump();
    await tester.pump();
    expect(fake.calls, [false, true]);
    expect(find.text('Rainy-day fund'), findsOneWidget);
    expect(find.text('Code: your goals are mostly on track.'), findsOneWidget);
    expect(find.text('The AI is reading your goals…'), findsOneWidget);

    fake.ai.complete(_goals('AI: put £20 more aside this month.', 'muse-spark-1.3'));
    await tester.pumpAndSettle();
    expect(find.text('AI: put £20 more aside this month.'), findsOneWidget);
    expect(find.text('The AI is reading your goals…'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}

Map<String, dynamic> _goals(String note, String model) => {
      'today': '2026-11-10',
      'household': true,
      'goals': [
        {
          'goal': {
            'id': 'g1',
            'name': 'Rainy-day fund',
            'kind': 'save',
            'start': '2026-01-01',
            'end': '2026-12-31',
            'target_pence': 100000,
          },
          'kind_label': 'Savings goal',
          'status': 'on_track',
          'status_label': 'On track',
          'tone': 'positive',
          'period_label': '1 Jan 2026 – 31 Dec 2026',
          'current_pence': 90000,
          'target_pence': 100000,
          'target_label': '£1,000.00 target',
          'plan_to_date_pence': 85000,
          'percent': 90,
          'variance_pence': 5000,
          'variance_text': '£50.00 ahead of plan to date.',
          'days_left': 51,
          'source_text': 'The amount you have recorded as put aside',
          'drivers': [],
          'suggestions': [],
        }
      ],
      'note': {
        'note_md': note,
        'model': model,
        'fallback_reason': model == 'code' ? 'No AI is set up, so code wrote this.' : null,
      },
      'facts': {},
    };

class _GoalsFake extends RuntimeClient {
  _GoalsFake() : super(AppSettings(runtimeUrl: 'http://reader:8780'));

  final calls = <bool>[];
  final ai = Completer<Map<String, dynamic>>();

  @override
  Future<Map<String, dynamic>> goals({String? today, bool noteAi = true}) {
    calls.add(noteAi);
    if (!noteAi) {
      return Future.value(_goals('Code: your goals are mostly on track.', 'code'));
    }
    return ai.future;
  }
}
