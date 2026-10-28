import 'package:accnomos_mobile/models/month_end.dart';
import 'package:accnomos_mobile/screens/month_end_screen.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:msal_auth/msal_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The month-end checklist on the phone: read only, from `GET /close/{month}`
/// and `GET /close` (services/runtime/app/month_end.py). Fakes answer without
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

  testWidgets('shows the last run read only, at 360 dp', (tester) async {
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
    expect(find.text('1  INBOX'), findsOneWidget);
    expect(find.text('Needs you'), findsOneWidget);
    expect(find.text('Blocks the close: 1 document in 00 Inbox not read yet.'), findsOneWidget);
    expect(find.textContaining('approve its cards on the web'), findsOneWidget);
    expect(find.byType(FilledButton), findsNothing); // nothing to approve on the phone
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
    expect(find.text('CHANGED SINCE THE CLOSE'), findsOneWidget);
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
    expect(find.text('MONTH-END'), findsOneWidget);
    expect(find.textContaining('October was closed on 3 Nov; 1 change since'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

final _account = Account(id: '1', username: 'user@example.com', name: 'Test User');

Map<String, dynamic> _detail({bool changed = false}) => {
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
  _Fake({this.changed = false}) : super(AppSettings(runtimeUrl: 'http://reader:8780'));

  final bool changed;
  final List<String> months = [];

  @override
  Future<Map<String, dynamic>> closeMonth(String month, {String? today}) async {
    months.add(month);
    return _detail(changed: changed);
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
