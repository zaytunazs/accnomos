import 'package:accnomos_mobile/services/ai_route.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:accnomos_mobile/widgets/ai_route_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// "Which AI answers first" (lib/services/ai_route.dart): the saved choice
/// goes to the runtime as `X-AI-Route`, and only once one is saved.
void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('runtime client', () {
    test('no saved choice: no X-AI-Route header', () {
      expect(RuntimeClient(AppSettings()).debugHeaders.containsKey(kAiRouteHeader),
          isFalse);
    });

    test('each saved choice is sent as X-AI-Route', () {
      for (final route in kAiRoutes) {
        final headers = RuntimeClient(AppSettings(aiRoute: route)).debugHeaders;
        expect(headers['X-AI-Route'], route);
      }
    });

    test('sent alongside the books headers and the own-AI headers', () {
      final headers = RuntimeClient(
        AppSettings(
            aiMode: 'local',
            aiBaseUrl: 'http://10.0.0.5:11434',
            aiRoute: 'local_first'),
        books: BooksAuth(graphToken: 't', accountKind: 'personal'),
      ).debugHeaders;
      expect(headers['X-AI-Route'], 'local_first');
      expect(headers['X-AI-Mode'], 'local');
      expect(headers['X-Graph-Token'], 't');
    });

    test('an unknown value is never sent', () {
      expect(
          RuntimeClient(AppSettings(aiRoute: 'cloud_only'))
              .debugHeaders
              .containsKey(kAiRouteHeader),
          isFalse);
    });
  });

  group('settings', () {
    test('saved under accnomos.ai.route and loaded back', () async {
      await AppSettings(aiRoute: 'local_only').save();
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('accnomos.ai.route'), 'local_only');
      expect((await AppSettings.load()).aiRoute, 'local_only');
    });

    test('saving other settings keeps the saved choice', () async {
      SharedPreferences.setMockInitialValues({'accnomos.ai.route': 'local_first'});
      await AppSettings(autopilotLevel: 'L2').save();
      expect((await AppSettings.load()).aiRoute, 'local_first');
    });

    test('a stored value that is not an option loads as no choice', () async {
      SharedPreferences.setMockInitialValues({'accnomos.ai.route': 'bogus'});
      expect((await AppSettings.load()).aiRoute, isNull);
    });
  });

  group('picker', () {
    Future<List<String>> pump(WidgetTester tester, String value) async {
      final picked = <String>[];
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: AiRoutePicker(value: value, onChanged: picked.add),
          ),
        ),
      ));
      return picked;
    }

    testWidgets('three options with the web wording; warning under local only',
        (tester) async {
      final picked = await pump(tester, kDefaultAiRoute);
      expect(find.byType(RadioListTile<String>), findsNWidgets(3));
      for (final opt in kAiRouteOptions) {
        expect(find.text(opt.label), findsOneWidget);
        expect(find.text(opt.description), findsOneWidget);
      }
      for (final line in kLocalOnlyWarnings) {
        expect(find.text(line), findsOneWidget);
      }
      expect(find.byKey(const Key('aiRouteWarning')), findsOneWidget);
      expect(find.byKey(const Key('aiRouteWarningSelected')), findsNothing);

      await tester.tap(find.text('Local model only'));
      await tester.pump();
      expect(picked, ['local_only']);
    });

    testWidgets('the warning stands out when local only is chosen',
        (tester) async {
      await pump(tester, 'local_only');
      expect(find.byKey(const Key('aiRouteWarningSelected')), findsOneWidget);
    });

    testWidgets('disabled: taps do nothing', (tester) async {
      final picked = <String>[];
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: AiRoutePicker(
                value: kDefaultAiRoute, onChanged: picked.add, enabled: false),
          ),
        ),
      ));
      await tester.tap(find.text('Local model only'), warnIfMissed: false);
      await tester.pump();
      expect(picked, isEmpty);
    });
  });
}
