import 'dart:convert';

import 'package:accnomos_mobile/main.dart';
import 'package:accnomos_mobile/screens/welcome_screen.dart';
import 'package:accnomos_mobile/services/app_mode.dart';
import 'package:accnomos_mobile/services/demo.dart';
import 'package:accnomos_mobile/services/graph.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:accnomos_mobile/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Launch: signed out opens on Welcome (the website's landing in short), signed
/// in or in a live demo opens the tabs; a demo carries its session instead of a
/// Graph token, and Exit demo goes back to Welcome.
void main() {
  const channel = MethodChannel('msal_auth');
  const demo = DemoInfo(
    session: 'sess-1',
    kind: 'personal',
    runtimeUrl: 'https://api.example',
    business: 'The Harrison household (fictional)',
    user: 'demo@accnomos.example',
  );

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      throw PlatformException(code: 'NO_CURRENT_ACCOUNT', message: 'no account');
    });
    Demo.debugSet(null);
    Demo.httpOverride = null;
    AppMode.reset();
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
    Demo.debugSet(null);
    Demo.httpOverride = null;
    AppMode.reset();
  });

  void phone(WidgetTester tester) {
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 2.75;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
  }

  Widget app() => MaterialApp(
      theme: accnomosTheme(),
      builder: demoFrameBuilder,
      home: const LaunchGate(restore: false));

  group('launch', () {
    testWidgets('signed out opens on Welcome, not on half-empty books',
        (tester) async {
      phone(tester);
      AppMode.reset(const ModeState(signedIn: false));
      await tester.pumpWidget(app());
      await tester.pump();
      expect(find.byType(WelcomeScreen), findsOneWidget);
      expect(find.text('Bookkeeping you only have to check'), findsOneWidget);
      expect(find.text('Sign in with Microsoft'), findsOneWidget);
      expect(find.text('Try the company demo'), findsOneWidget);
      expect(find.text('Try the personal demo'), findsOneWidget);
      expect(find.byType(NavigationBar), findsNothing);
      expect(find.text('Connect to see'), findsNothing);
      expect(find.text('Company sample'), findsNothing);
    });

    testWidgets('until the first check answers, the brand splash',
        (tester) async {
      AppMode.reset(const ModeState(loaded: false));
      await tester.pumpWidget(app());
      expect(find.byType(BrandSplash), findsOneWidget);
      expect(find.text('Accnomos'), findsOneWidget);
    });

    testWidgets('signed in opens the tabs, with the brand in the app bar',
        (tester) async {
      phone(tester);
      AppMode.reset(const ModeState(signedIn: true, kind: 'company'));
      await tester.pumpWidget(app());
      expect(find.byType(Shell), findsOneWidget);
      expect(find.byType(NavigationBar), findsOneWidget);
      expect(find.text('Accnomos'), findsWidgets);
      expect(find.byKey(const Key('demo-banner')), findsNothing);
    });

    testWidgets('a demo opens the household tabs with its banner; Exit goes back to Welcome',
        (tester) async {
      phone(tester);
      final deleted = <String>[];
      Demo.httpOverride = MockClient((req) async {
        if (req.method == 'DELETE') deleted.add(req.headers['X-Demo-Session'] ?? '');
        return http.Response('', 204);
      });
      Demo.debugSet(demo);
      AppMode.reset(const ModeState(signedIn: true, kind: 'personal'));
      await tester.pumpWidget(app());
      await tester.pump();
      expect(find.byKey(const Key('demo-banner')), findsOneWidget);
      expect(find.text('SAMPLE — FICTIONAL HOUSEHOLD · demo data only'),
          findsOneWidget);
      final labels = [
        for (final d in tester
            .widgetList<NavigationDestination>(find.byType(NavigationDestination)))
          d.label
      ];
      expect(labels, ['Home', 'Review', 'Budget', 'Goals', 'More']);

      await tester.tap(find.byKey(const Key('demo-exit')));
      for (var i = 0; i < 10; i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }
      expect(Demo.active, isFalse);
      expect(deleted, ['sess-1']);
      expect(find.byType(WelcomeScreen), findsOneWidget);
    });
  });

  group('Welcome', () {
    testWidgets('the demo buttons start that demo; a refusal shows plainly',
        (tester) async {
      phone(tester);
      final started = <String>[];
      await tester.pumpWidget(MaterialApp(
        theme: accnomosTheme(),
        home: WelcomeScreen(startDemo: (kind) async {
          started.add(kind);
          if (kind == 'company') {
            throw DemoException('The demo could not be prepared just now. Try again in a minute.');
          }
        }),
      ));
      await tester.tap(find.byKey(const Key('welcome-demo-personal')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      await tester.tap(find.byKey(const Key('welcome-demo-company')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(started, ['personal', 'company']);
      expect(find.byKey(const Key('welcome-error')), findsOneWidget);
      expect(find.textContaining('could not be prepared'), findsOneWidget);
    });

    testWidgets('no launch or pre-release words', (tester) async {
      phone(tester);
      await tester.pumpWidget(
          MaterialApp(theme: accnomosTheme(), home: const WelcomeScreen()));
      final text = [
        for (final t in tester.widgetList<Text>(find.byType(Text)))
          t.data ?? t.textSpan?.toPlainText() ?? ''
      ].join(' ').toLowerCase();
      for (final banned in [
        'coming soon',
        'beta',
        'early access',
        'launching',
        'testers',
      ]) {
        expect(text.contains(banned), isFalse, reason: banned);
      }
      expect(text, contains('step 1'));
      expect(text, contains('a meta model reads the document'));
    });
  });

  group('demo transport', () {
    test('runtime calls carry the demo session, not a Graph token or AI headers',
        () {
      Demo.debugSet(demo);
      final client = RuntimeClient(
        AppSettings(runtimeUrl: 'https://api.example'),
        books: BooksAuth(graphToken: 'sess-1', accountKind: 'personal'),
      );
      final h = client.debugHeaders;
      expect(h['X-Demo-Session'], 'sess-1');
      expect(h.containsKey('X-Graph-Token'), isFalse);
      expect(h.containsKey('X-AI-Mode'), isFalse);
      expect(h['X-User'], 'demo@accnomos.example');
    });

    test('signed in, the Graph token; AI headers only for an AI of your own',
        () {
      final client = RuntimeClient(
        AppSettings(runtimeUrl: 'https://api.example'),
        books: BooksAuth(graphToken: 'tok', accountKind: 'personal'),
      );
      final h = client.debugHeaders;
      expect(h['X-Graph-Token'], 'tok');
      expect(h.containsKey('X-Demo-Session'), isFalse);
      // The default is the reader service's own model chain, as on the web.
      expect(h.containsKey('X-AI-Mode'), isFalse);
      final own = RuntimeClient(
        AppSettings(
            runtimeUrl: 'https://api.example',
            aiMode: 'local',
            aiBaseUrl: 'http://10.0.0.5:11434'),
        books: BooksAuth(graphToken: 'tok', accountKind: 'personal'),
      ).debugHeaders;
      expect(own['X-AI-Mode'], 'local');
    });

    test('OneDrive calls go to the runtime look-alike during a demo', () {
      expect(GraphService.authHeaders('tok'), {'Authorization': 'Bearer tok'});
      Demo.debugSet(demo);
      expect(GraphService.authHeaders('sess-1'), {'X-Demo-Session': 'sess-1'});
      expect(demo.graphBase, 'https://api.example/demo/graph/v1.0');
    });

    test('Demo.start asks for the kind and keeps the session', () async {
      Uri? asked;
      Demo.httpOverride = MockClient((req) async {
        asked = req.url;
        return http.Response(
            json.encode({
              'session': 'new-1',
              'kind': 'company',
              'business': 'Bramblewood Joinery Ltd',
              'user': 'demo@accnomos.example',
            }),
            200);
      });
      final info = await Demo.start('https://api.example', 'company');
      expect(asked.toString(), 'https://api.example/demo/session?kind=company');
      expect(info.session, 'new-1');
      expect(info.household, isFalse);
      expect(Demo.current?.business, 'Bramblewood Joinery Ltd');
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('accnomos.demo.kind'), 'company');
    });

    test('Demo.start: too many starts reads as a plain sentence', () async {
      Demo.httpOverride = MockClient((_) async => http.Response('', 429));
      await expectLater(
          Demo.start('https://api.example', 'personal'),
          throwsA(isA<DemoException>().having(
              (e) => e.message, 'message', contains('Too many demos'))));
    });

    test('Demo.restore replaces a forgotten session with a fresh one', () async {
      SharedPreferences.setMockInitialValues({
        'accnomos.demo.session': 'old',
        'accnomos.demo.kind': 'personal',
        'accnomos.demo.runtime': 'https://api.example',
      });
      Demo.httpOverride = MockClient((req) async {
        if (req.method == 'GET') return http.Response('{"detail":"gone"}', 401);
        return http.Response(
            json.encode({'session': 'fresh', 'kind': 'personal'}), 200);
      });
      final info = await Demo.restore();
      expect(info?.session, 'fresh');
      expect(info?.household, isTrue);
    });
  });
}
