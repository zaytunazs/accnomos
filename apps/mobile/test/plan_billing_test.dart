import 'package:accnomos_mobile/screens/more_screen.dart';
import 'package:accnomos_mobile/screens/report_problem_sheet.dart';
import 'package:accnomos_mobile/services/plan_limit.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('402 plan_limit and read_only', () {
    const limitBody =
        '{"code":"plan_limit","counter":"docs","limit":50,"used":50,"upgrade_url":"https://accnomos.com/settings/billing","detail":"You have used 50 of 50."}';
    const readOnlyBody =
        '{"code":"read_only","status":"trial_ended","upgrade_url":"https://accnomos.com/settings/billing","detail":"Your free trial has ended."}';

    test('the runtime\'s bodies are read, top level or under detail, and only for 402', () {
      final a = PlanLimitInfo.parse(402, limitBody)!;
      expect([a.code, a.counter, a.limit, a.used, a.detail],
          ['plan_limit', 'docs', 50, 50, 'You have used 50 of 50.']);
      expect(
          PlanLimitInfo.parse(402, '{"detail":{"code":"plan_limit","counter":"ask","limit":100,"used":100}}')
              ?.counter,
          'ask');
      final r = PlanLimitInfo.parse(402, readOnlyBody)!;
      expect([r.readOnly, r.status], [true, 'trial_ended']);
      expect(PlanLimitInfo.parse(500, limitBody), isNull);
      expect(PlanLimitInfo.parse(402, '{"code":"other"}'), isNull);
      expect(PlanLimitInfo.parse(402, '{"detail":"Payment required"}'), isNull);
      expect(PlanLimitInfo.parse(402, 'not json'), isNull);
    });

    test('the sentences are friendly, name the limit and say nothing is locked', () {
      final docs = PlanLimitInfo.parse(402, limitBody)!;
      expect(docs.sentence, contains("all 50 of this month's AI-read documents"));
      expect(docs.sentence, contains('approve, edit and export'));
      expect(const PlanLimitInfo(counter: 'marketplaces', limit: 0).sentence,
          contains('does not include marketplace connections'));
      expect(const PlanLimitInfo(counter: 'bank_feeds', limit: 3).sentence,
          contains('allows 3 live bank feeds'));
      final ro = PlanLimitInfo.parse(402, readOnlyBody)!;
      expect(ro.title, 'Your free trial has ended');
      expect(ro.sentence, contains('read-only'));
      expect(const PlanLimitInfo(code: 'read_only', status: 'cancelled').title,
          'Your plan has been cancelled');
      for (final i in [docs, ro]) {
        expect(i.sentence, isNot(contains('web')));
        expect(i.sentence, isNot(contains('£')));
      }
    });

    Future<void> openDialog(WidgetTester tester, PlanLimitInfo info,
        {required bool links, void Function(Uri)? opened}) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              onPressed: () => showDialog<void>(
                context: context,
                builder: (_) => PlanLimitDialog(
                  info: info,
                  purchaseLinksAllowed: links,
                  open: (u) async => opened?.call(u),
                ),
              ),
              child: const Text('go'),
            ),
          ),
        ),
      ));
      await tester.tap(find.text('go'));
      await tester.pumpAndSettle();
    }

    testWidgets('Android: the limit dialog opens the web plan page, not an in-app purchase',
        (tester) async {
      Uri? opened;
      await openDialog(tester, PlanLimitInfo.parse(402, limitBody)!,
          links: true, opened: (u) => opened = u);
      expect(find.byKey(const Key('plan-limit-dialog')), findsOneWidget);
      await tester.tap(find.byKey(const Key('plan-limit-open-web')));
      await tester.pumpAndSettle();
      expect(opened.toString(), 'https://accnomos.com/settings#plan-billing');
      expect(find.byKey(const Key('plan-limit-dialog')), findsNothing);
    });

    testWidgets('Android: read-only says the trial ended and links to choose a plan',
        (tester) async {
      Uri? opened;
      await openDialog(tester, PlanLimitInfo.parse(402, readOnlyBody)!,
          links: true, opened: (u) => opened = u);
      expect(find.text('Your free trial has ended'), findsOneWidget);
      expect(find.text('Choose a plan on the web'), findsOneWidget);
      await tester.tap(find.byKey(const Key('plan-limit-open-web')));
      await tester.pumpAndSettle();
      expect(opened.toString(), 'https://accnomos.com/settings#plan-billing');
    });

    for (final body in [limitBody, readOnlyBody]) {
      testWidgets('iOS: no link, no price, no "on the web" (${body.substring(9, 18)})',
          (tester) async {
        await openDialog(tester, PlanLimitInfo.parse(402, body)!, links: false);
        expect(find.byKey(const Key('plan-limit-dialog')), findsOneWidget);
        expect(find.byKey(const Key('plan-limit-open-web')), findsNothing);
        expect(find.textContaining('web'), findsNothing);
        expect(find.textContaining('buy'), findsNothing);
        expect(find.textContaining('£'), findsNothing);
        expect(find.textContaining('Choose a plan'), findsNothing);
        await tester.tap(find.text('OK'));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('plan-limit-dialog')), findsNothing);
      });
    }
  });

  test('Plan & billing is left out where the store allows no purchase links', () {
    expect(accountEntries(true).map((e) => e.title), ['Plan & billing', 'Report a problem']);
    expect(accountEntries(false).map((e) => e.title), ['Report a problem']);
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
