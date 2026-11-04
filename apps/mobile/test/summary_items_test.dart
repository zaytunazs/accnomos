import 'package:accnomos_mobile/main.dart' show shellTabIndex;
import 'package:accnomos_mobile/models/home_summary.dart';
import 'package:accnomos_mobile/screens/home_screen.dart'
    show SummaryCard, SummaryItemRow;
import 'package:accnomos_mobile/services/navigation.dart';
import 'package:accnomos_mobile/services/summary_routes.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> home(List<Object?> items, {String md = ''}) => {
      'summary': {
        'summary_md': md,
        'model': 'muse-spark-1.3-contributor',
        'fallback_reason': null,
        'items': items,
      },
    };

final items = [
  {
    'id': 'review',
    'priority': 1,
    'tone': 'warning',
    'title': '6 items waiting in Review',
    'detail': 'Receipts read and checked by code; nothing posts until you approve.',
    'action': {'label': 'Review', 'route': '/review'},
  },
  {
    'id': 'background',
    'priority': 3,
    'tone': 'positive',
    'title': 'Turnover down 11% on last year',
    'detail': null,
    'action': null,
  },
  {
    'id': 'vat',
    'priority': 2,
    'tone': 'warning',
    'title': 'VAT return Jul–Sep due 7 Nov',
    'detail': 'In 3 days.',
    'action': {'label': 'File VAT', 'route': '/vat'},
  },
  {
    'id': 'self',
    'priority': 2,
    'tone': 'neutral',
    'title': 'Income Tax update due 7 Nov',
    'action': {'label': 'Open', 'route': '/self-employment'},
  },
];

Widget card(HomeSummary s, {bool household = false}) => MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
            child: SummaryCard(summary: s, household: household)),
      ),
    );

void main() {
  test('items parse leniently; a line without a title is skipped', () {
    final s = HomeSummary.fromHomeJson(home([
      ...items,
      {'id': 'x', 'priority': 'high'},
      'not a map',
      {'title': '  Odd but fine  ', 'tone': 'loud', 'priority': 9, 'action': {'label': 'Go'}},
    ]))!;
    expect(s.items.map((i) => i.id), ['review', 'background', 'vat', 'self', 'Odd but fine']);
    final odd = s.items.last;
    expect(odd.tone, SummaryTone.neutral);
    expect(odd.priority, 3);
    expect(odd.action, isNull); // no route: no button
    expect(HomeSummary.fromHomeJson({'summary': {'summary_md': '', 'items': []}}), isNull);
  });

  testWidgets('renders the lines in order, background ones last, with their actions',
      (tester) async {
    await tester.pumpWidget(card(HomeSummary.fromHomeJson(home(items))!));
    final ys = ['review', 'vat', 'self', 'background']
        .map((id) => tester.getTopLeft(find.byKey(Key('summary-item-$id'))).dy)
        .toList();
    expect(ys, orderedEquals([...ys]..sort()));
    expect(find.text('Review →'), findsOneWidget);
    expect(find.text('File VAT →'), findsOneWidget);
    // The app has no self-employment screen: no button.
    expect(find.byKey(const Key('summary-action-self')), findsNothing);
    expect(find.text('Receipts read and checked by code; nothing posts until you approve.'),
        findsOneWidget);
  });

  testWidgets('falls back to the paragraph when the server sends no items', (tester) async {
    await tester.pumpWidget(
        card(HomeSummary.fromHomeJson(home(const [], md: 'You had £18,166.11 in the bank.'))!));
    expect(find.text('You had £18,166.11 in the bank.'), findsOneWidget);
    expect(find.byType(SummaryItemRow), findsNothing);
  });

  testWidgets('an action that is a tab asks the shell for that tab', (tester) async {
    AppNav.tabRequests.value = null;
    await tester.pumpWidget(card(HomeSummary.fromHomeJson(home(items))!));
    await tester.tap(find.text('Review →'));
    expect(AppNav.tabRequests.value?.name, 'review');
    await tester.tap(find.text('File VAT →'));
    expect(AppNav.tabRequests.value?.name, 'vat');
  });

  testWidgets('a household gets no VAT button', (tester) async {
    await tester.pumpWidget(card(HomeSummary.fromHomeJson(home(items))!, household: true));
    expect(find.text('File VAT →'), findsNothing);
    expect(find.text('Review →'), findsOneWidget);
  });

  testWidgets('long lines wrap at large text sizes without overflow', (tester) async {
    tester.view.physicalSize = const Size(360 * 3, 800 * 3);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MediaQuery(
      data: const MediaQueryData(textScaler: TextScaler.linear(1.6)),
      child: card(HomeSummary.fromHomeJson(home(items))!),
    ));
    expect(tester.takeException(), isNull);
  });

  test('routes map to the app\'s tabs and screens', () {
    String? name(String r, {bool household = false}) =>
        switch (summaryTarget(r, household: household)) {
          TabTarget(:final tab) => 'tab:$tab',
          ScreenTarget(:final name) => 'screen:$name',
          null => null,
        };
    expect(name('/review'), 'tab:review');
    expect(name('/vat'), 'tab:vat');
    expect(name('/vat', household: true), isNull);
    expect(name('/invoices?filter=overdue'), 'screen:invoices');
    expect(name('/bank/reconcile'), 'screen:bank');
    expect(name('/personal', household: true), 'tab:budget');
    expect(name('/personal'), 'screen:budget');
    expect(name('/goals', household: true), 'tab:goals');
    expect(name('/goals'), 'screen:goals');
    expect(name('/month-end'), 'screen:month-end');
    expect(name('/contacts'), 'screen:contacts');
    expect(name('/reports/cashflow'), 'screen:reports');
    expect(name('/payroll'), 'screen:payroll');
    expect(name('/self-employment'), isNull);
    expect(name('/nowhere'), isNull);
    expect(shellTabIndex('vat', household: false), 3);
    expect(shellTabIndex('budget', household: true), 2);
    expect(shellTabIndex('vat', household: true), isNull);
  });
}

