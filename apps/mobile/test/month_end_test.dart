import 'package:accnomos_mobile/models/ask_answer.dart';
import 'package:accnomos_mobile/models/month_end.dart';
import 'package:accnomos_mobile/screens/month_end_screen.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:msal_auth/msal_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The month-end close on the phone, as on the web: `GET /close/{month}`,
/// `POST /close/{month}/run` and its signed cards (services/runtime/app/month_end.py). Fakes answer without
/// network or MSAL; every case runs at 360 dp with no overflow.
void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  void phone(WidgetTester tester) {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
  }

  test('months and labels', () {
    expect(recentMonths(DateTime(2026, 1, 15)).take(2), ['2025-12', '2025-11']);
    expect(recentMonths(DateTime(2026, 11, 4)).first, '2026-10');
    expect(monthLabel('2026-10'), 'October 2026');
    expect(monthLabel('nonsense'), 'nonsense');
  });

  test('parses a month with a run and changes since the close', () {
    final m = MonthClose.fromJson(_detail(changed: true));
    expect(m.label, 'October 2026');
    expect(m.steps.length, 2);
    expect(m.steps.first.statusLabel, 'Needs you');
    expect(m.steps.first.found.first.blocking, isTrue);
    expect(m.changes, ['A purchase from Wickes for £24.00 dated 20 Oct was approved on 5 Nov']);
    expect(m.figures.single, ('Net profit', '-£100.00', '-£120.00'));
    expect(m.summaryByCode, isTrue);
  });

  testWidgets('shows the last run and a Close button, at 360 dp', (tester) async {
    phone(tester);
    final fake = _Fake();
    await tester.pumpWidget(MaterialApp(
      home: MonthEndScreen(
        testAccount: _account,
        testAccountReady: true,
        today: DateTime(2026, 11, 4),
        clientFactory: (settings, books) => fake,
      ),
    ));
    await tester.pumpAndSettle();
    expect(fake.months, ['2026-10']);
    expect(find.text('October: 1 thing needs you before close.'), findsOneWidget);
    expect(find.text('1  Inbox'), findsOneWidget);
    expect(find.text('Needs you'), findsOneWidget);
    expect(find.text('Blocks the close: 1 document in 00 Inbox not read yet.'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Close October'), findsOneWidget);
    expect(find.textContaining('on the web'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('runs the close and approves its card', (tester) async {
    phone(tester);
    final fake = _Fake();
    await tester.pumpWidget(MaterialApp(
      home: MonthEndScreen(
        testAccount: _account,
        testAccountReady: true,
        today: DateTime(2026, 11, 4),
        clientFactory: (settings, books) => fake,
      ),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Close October'));
    await tester.pumpAndSettle();
    expect(fake.runs, ['2026-10']);
    expect(find.text('Close the month · needs your OK'), findsOneWidget);
    expect(find.text('Mark October 2026 closed?'), findsOneWidget);
    await tester.ensureVisible(find.widgetWithText(FilledButton, 'Approve'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Approve'));
    await tester.pumpAndSettle();
    expect(fake.approved, ['card-1']);
    expect(find.text('✓ October 2026 is closed.'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('warns about entries stored twice', (tester) async {
    phone(tester);
    final fake = _Fake(withDuplicates: true);
    await tester.pumpWidget(MaterialApp(
      home: MonthEndScreen(
        testAccount: _account,
        testAccountReady: true,
        today: DateTime(2026, 11, 4),
        clientFactory: (settings, books) => fake,
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.text('1 ledger entry is stored twice'), findsOneWidget);
    expect(find.textContaining('Wickes · £24.00 · 1 extra file'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('says what changed since the close', (tester) async {
    phone(tester);
    final fake = _Fake(changed: true);
    await tester.pumpWidget(MaterialApp(
      home: MonthEndScreen(
        testAccount: _account,
        testAccountReady: true,
        today: DateTime(2026, 11, 4),
        clientFactory: (settings, books) => fake,
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Changed since the close'), findsOneWidget);
    expect(find.text('Net profit: -£100.00 → -£120.00'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Home card shows the headline from GET /close', (tester) async {
    phone(tester);
    final fake = _Fake(changed: true);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: MonthEndCard(clientFor: () async => fake, today: DateTime(2026, 11, 4)),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Month-end'), findsOneWidget);
    expect(find.textContaining('October was closed on 3 Nov; 1 change since'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

final _account = Account(id: '1', username: 'user@example.com', name: 'Test User');

Map<String, dynamic> _detail({bool changed = false, bool duplicates = false}) => {
      if (duplicates)
        'duplicates': [
          {
            'id': 'ev-1',
            'date': '2026-10-20',
            'kind': 'purchase',
            'counterparty': 'Wickes',
            'net_pence': 2400,
            'extra_files': ['_System/Ledger/x.json'],
          },
        ],
      'month': '2026-10',
      'label': 'October 2026',
      'ended': true,
      'closed': false,
      'last_run_at': '2026-11-04T09:00:00Z',
      'headline': changed
          ? 'October was closed on 3 Nov; 1 change since: a purchase from Wickes — re-close?'
          : 'October: 1 thing needs you before close.',
      'changes': changed
          ? {
              'closed_at': '2026-11-03T09:00:00Z',
              'closed_by': 'user@example.com',
              'count': 1,
              'items': ['A purchase from Wickes for £24.00 dated 20 Oct was approved on 5 Nov'],
              'figures': [
                {'label': 'Net profit', 'before': '-£100.00', 'after': '-£120.00'},
              ],
              'vat_note': null,
              'headline': 'October was closed on 3 Nov; 1 change since — re-close?',
            }
          : null,
      'run': {
        'summary_md': 'October 2026: 1 thing needs you before the month can be closed.',
        'summary_model': 'code',
        'summary_fallback_reason': 'No AI is set up, so code wrote this.',
        'steps': [
          {
            'n': 1,
            'title': 'Inbox',
            'status': 'needs_you',
            'reason': 'Scan the inbox.',
            'checked': ['00 Inbox: 1 file'],
            'found': [
              {'text': '1 document in 00 Inbox not read yet.', 'level': 'blocking'},
            ],
          },
          {
            'n': 2,
            'title': 'Bank',
            'status': 'ok',
            'reason': 'Statements cover October.',
            'checked': [],
            'found': [],
          },
        ],
      },
      'closes': [],
    };

class _Fake extends RuntimeClient {
  _Fake({this.changed = false, this.withDuplicates = false})
      : super(AppSettings(runtimeUrl: 'http://reader:8780'));

  final bool changed;
  final bool withDuplicates;
  final List<String> months = [];
  final List<String> runs = [];
  final List<String> approved = [];

  @override
  Future<Map<String, dynamic>> closeMonth(String month, {String? today}) async {
    months.add(month);
    return _detail(changed: changed, duplicates: withDuplicates);
  }

  @override
  Future<Map<String, dynamic>> runClose(String month, {String? today}) async {
    runs.add(month);
    return {
      'summary_md': 'October 2026 is ready to close.',
      'steps': [
        {
          'id': 'lock',
          'n': 9,
          'title': 'Close',
          'status': 'needs_you',
          'reason': 'Approve the card to mark October closed.',
          'checked': [],
          'found': [],
          'proposes': ['card-1'],
        },
      ],
      'actions': [
        {
          'id': 'card-1',
          'kind': 'close_month',
          'summary_md': 'Mark **October 2026** closed with a snapshot of its figures.',
          'confirm_text': 'Mark October 2026 closed',
          'expires_at': DateTime.now().add(const Duration(minutes: 15)).toUtc().toIso8601String(),
          'preview': {'warnings': []},
        },
      ],
    };
  }

  @override
  Future<String> approveAction(ProposedAction action, {String? heard}) async {
    approved.add(action.id);
    return 'October 2026 is closed.';
  }

  @override
  Future<Map<String, dynamic>> closeOverview({String? today}) async => {
        'today': today,
        'target': {
          'month': '2026-10',
          'headline': changed
              ? 'October was closed on 3 Nov; 1 change since: a purchase from Wickes — re-close?'
              : 'October: 1 thing needs you before close.',
          'changes': changed ? {'count': 1} : null,
        },
        'changed': [],
      };
}
