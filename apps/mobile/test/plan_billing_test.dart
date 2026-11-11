import 'package:accnomos_mobile/screens/more_screen.dart';
import 'package:accnomos_mobile/screens/report_problem_sheet.dart';
import 'package:accnomos_mobile/services/plan_limit.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('402 plan_limit', () {
    test('is read from the top level or from detail, and only for 402', () {
      final a = PlanLimitInfo.parse(
          402, '{"code":"plan_limit","limit":"docs","message":"50 of 50"}');
      expect(a?.limitKey, 'docs');
      expect(a?.message, '50 of 50');
      expect(
          PlanLimitInfo.parse(402, '{"detail":{"code":"plan_limit","limit_key":"ask"}}')
              ?.limitKey,
          'ask');
      expect(PlanLimitInfo.parse(500, '{"code":"plan_limit"}'), isNull);
      expect(PlanLimitInfo.parse(402, '{"code":"other"}'), isNull);
      expect(PlanLimitInfo.parse(402, 'not json'), isNull);
    });

    test('the sentence is friendly and says nothing is locked', () {
      const info = PlanLimitInfo(limitKey: 'docs');
      expect(info.sentence, contains('AI-read documents'));
      expect(info.sentence, contains('approve, edit and export'));
    });

    testWidgets('the dialog opens the web plan page, not an in-app purchase',
        (tester) async {
      Uri? opened;
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              onPressed: () => showDialog<void>(
                context: context,
                builder: (_) => PlanLimitDialog(
                  info: const PlanLimitInfo(limitKey: 'docs'),
                  open: (u) async => opened = u,
                ),
              ),
              child: const Text('go'),
            ),
          ),
        ),
      ));
      await tester.tap(find.text('go'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('plan-limit-dialog')), findsOneWidget);
      await tester.tap(find.byKey(const Key('plan-limit-open-web')));
      await tester.pumpAndSettle();
      expect(opened.toString(), 'https://accnomos.com/settings#plan-billing');
      expect(find.byKey(const Key('plan-limit-dialog')), findsNothing);
    });
  });

  test('More ends with Plan & billing and Report a problem, for every kind of books', () {
    for (final entries in [moreEntries(null), moreEntries(null, household: true)]) {
      final titles = entries.map((e) => e.title).toList();
      expect(titles.sublist(titles.length - 2), ['Plan & billing', 'Report a problem']);
      expect(entries.last.action, isNotNull);
    }
  });

  testWidgets('Report a problem sends the message', (tester) async {
    String? sent;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: ReportProblemSheet(send: (m) async {
          sent = m;
          return 'b-1';
        }),
      ),
    ));
    await tester.tap(find.byKey(const Key('report-send')));
    await tester.pump();
    expect(find.byKey(const Key('report-error')), findsOneWidget); // too short
    await tester.enterText(find.byKey(const Key('report-message')), 'The camera freezes on Review.');
    await tester.tap(find.byKey(const Key('report-send')));
    await tester.pumpAndSettle();
    expect(sent, 'The camera freezes on Review.');
    expect(find.byKey(const Key('report-sent')), findsOneWidget);
  });
}
