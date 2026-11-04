import 'dart:io';

import 'package:accnomos_mobile/main.dart';
import 'package:accnomos_mobile/models/proposal.dart';
import 'package:accnomos_mobile/screens/ask_screen.dart';
import 'package:accnomos_mobile/screens/invoice_send.dart';
import 'package:accnomos_mobile/screens/review_screen.dart';
import 'package:accnomos_mobile/screens/settings_screen.dart';
import 'package:accnomos_mobile/services/app_mode.dart';
import 'package:accnomos_mobile/services/demo.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:accnomos_mobile/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Fixes from the 0.3.10 audit: the Approved bar, Ask's model and household
/// wording, demo sends and settings, the AI default, Review wording.
void main() {
  const channel = MethodChannel('msal_auth');
  const demo = DemoInfo(
    session: 'sess-1',
    kind: 'company',
    runtimeUrl: 'https://api.example',
    business: 'Bramblewood Joinery Ltd',
    user: 'demo@accnomos.example',
  );
  const health = {
    'ai': {
      'providers': [
        {'name': 'meta', 'model': 'muse-spark-1.3-contributor', 'configured': true},
        {'name': 'spark', 'model': 'muse-glimmer:30b', 'configured': true},
      ],
    },
  };

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
    Demo.debugSet(null);
    AppMode.reset();
  });

  group('AI default', () {
    test('no home-network address is shipped; the reader chain is the default',
        () async {
      final s = await AppSettings.load();
      expect(s.aiMode, 'auto');
      expect(s.aiBaseUrl, '');
      final source = File('lib/services/settings.dart').readAsStringSync();
      expect(source.contains('192.168.1.176'), isFalse);
      expect(File('lib/screens/settings_screen.dart')
          .readAsStringSync()
          .contains('192.168.1.176'), isFalse);
    });

    test('auto sends no X-AI headers; an own local address still does',
        () async {
      final seen = <Map<String, String>>[];
      final mock = MockClient((req) async {
        seen.add(req.headers);
        return http.Response('{"ok":true}', 200);
      });
      await RuntimeClient(AppSettings(runtimeUrl: 'https://r.example'),
              httpClient: mock)
          .health();
      final auto = RuntimeClient(AppSettings(runtimeUrl: 'https://r.example'),
          books: BooksAuth(graphToken: 't', accountKind: 'personal'),
          httpClient: mock);
      await auto.dashboard().catchError((_) => <String, dynamic>{});
      expect(seen.last.keys.any((k) => k.toLowerCase().startsWith('x-ai-')),
          isFalse);
      final local = RuntimeClient(
          AppSettings(
              runtimeUrl: 'https://r.example',
              aiMode: 'local',
              aiBaseUrl: 'http://10.0.0.5:11434'),
          books: BooksAuth(graphToken: 't', accountKind: 'personal'),
          httpClient: mock);
      await local.dashboard().catchError((_) => <String, dynamic>{});
      expect(seen.last['X-AI-Base-Url'], 'http://10.0.0.5:11434');
    });

    test('the server model is the first configured provider', () {
      expect(RuntimeClient.serverModel(health), 'muse-spark-1.3-contributor');
      expect(RuntimeClient.serverModel(null), isNull);
    });
  });

  group('Ask', () {
    test('names the model that answers, and a household asks about its money',
        () {
      expect(askModelLabel(AppSettings(), health, demo: true), 'Muse Spark');
      expect(askModelLabel(AppSettings(), health, demo: false), 'Muse Spark');
      expect(
          askModelLabel(
              AppSettings(aiMode: 'local', aiBaseUrl: 'http://10.0.0.5:11434'),
              health,
              demo: false),
          'Glimmer 30B');
      final home = askIntro(household: true, model: 'm');
      expect(home, isNot(contains('VAT')));
      expect(home, contains('your own money'));
      expect(householdAskQuestions.any((q) => q.contains('VAT')), isFalse);
      expect(askIntro(household: false, model: 'm'), contains('VAT quarter'));
    });

    test('a refused voice question reads as the runtime\'s sentence', () {
      expect(
          voiceErrorText(RuntimeException(
              'The reader refused that request (status 422). '
              '{"detail":"Didn\'t catch any words in that recording"}')),
          "Didn't catch any words in that recording.");
      expect(voiceErrorText(RuntimeException('Offline.')), 'Offline.');
    });
  });

  group('demo', () {
    test('a demo send says it was not actually sent', () {
      expect(sentMessage('INV-7', 'a@b.example', demo: true),
          'Sent (demo — not actually sent) · Invoice INV-7 sent to a@b.example.');
      expect(sentMessage('INV-7', 'a@b.example', demo: false),
          'Invoice INV-7 sent to a@b.example.');
    });

    testWidgets('demo settings: no sign-out or AI address, Exit demo instead',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 6000);
      tester.view.devicePixelRatio = 2.75;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      Demo.debugSet(demo);
      await tester.pumpWidget(MaterialApp(
        theme: accnomosTheme(),
        home: SettingsScreen(
          testAccountReady: true,
          clientFactory: (s, b) => RuntimeClient(s,
              books: b,
              httpClient: MockClient((_) async => http.Response('{}', 200))),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('demoSettingsSection')), findsOneWidget);
      expect(find.byKey(const Key('demoAiNote')), findsOneWidget);
      expect(find.text('Sign out'), findsNothing);
      expect(find.text('Switch account'), findsNothing);
      expect(find.text('Disconnect Accnomos'), findsNothing);
      expect(find.text('Local AI address'), findsNothing);
      expect(find.text('Exit demo'), findsOneWidget);
    });

    testWidgets('household settings have no Business group', (tester) async {
      AppMode.reset(const ModeState(signedIn: true, kind: 'personal'));
      await tester.pumpWidget(MaterialApp(
        theme: accnomosTheme(),
        home: SettingsScreen(
          testAccountReady: true,
          clientFactory: (s, b) => RuntimeClient(s,
              books: b,
              httpClient: MockClient((_) async => http.Response('{}', 200))),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Business'), findsNothing);
      expect(find.text('Show personal finances'), findsNothing);
      expect(find.text('AI'), findsOneWidget);
    });
  });

  group('Review wording', () {
    test('payment methods read as words', () {
      expect(paymentMethodWords('bank_transfer'), 'Bank transfer');
      expect(paymentMethodWords('paypal'), 'PayPal');
      expect(paymentMethodWords('voucher_code'), 'Voucher code');
    });

    test('the Why note is not repeated under the second reading', () {
      expect(
          showWhyNote('Checks: 11 of 11 passed',
              'Second reading not run · Checks run by code: 11 of 11 passed'),
          isFalse);
      expect(showWhyNote('Rule: Screwfix → Materials', 'Second reading not run'),
          isTrue);
      expect(showWhyNote(null, 'x'), isFalse);
    });
  });

  group('shell', () {
    testWidgets(
        'a bar with Undo goes on a tab change; Back goes Home before leaving',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2340);
      tester.view.devicePixelRatio = 2.75;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      AppMode.reset(const ModeState(signedIn: true, kind: 'company'));
      await tester.pumpWidget(MaterialApp(
        theme: accnomosTheme(),
        builder: demoFrameBuilder,
        home: const Shell(),
      ));
      await tester.pump();
      final ctx = tester.element(find.byType(NavigationBar));
      ScaffoldMessenger.of(ctx).showSnackBar(SnackBar(
        content: const Text('Approved · posted to your books'),
        persist: false,
        action: SnackBarAction(label: 'Undo', onPressed: () {}),
      ));
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.text('Approved · posted to your books'), findsOneWidget);

      await tester.tap(find.text('VAT'));
      await tester.pump(const Duration(milliseconds: 600));
      expect(find.text('Approved · posted to your books'), findsNothing);

      // Back on VAT goes to Home, not out of the app.
      final nav = tester.state<NavigatorState>(find.byType(Navigator).first);
      await nav.maybePop();
      await tester.pump(const Duration(milliseconds: 300));
      final bar = tester.widget<NavigationBar>(find.byType(NavigationBar));
      expect(bar.selectedIndex, 0);
      await nav.maybePop();
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('Press Back again to leave Accnomos'), findsOneWidget);
    });
  });
}
