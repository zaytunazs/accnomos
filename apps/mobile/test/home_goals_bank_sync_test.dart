import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:accnomos_mobile/widgets/bank_sync.dart';
import 'package:accnomos_mobile/widgets/home_goals.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _Fake extends RuntimeClient {
  _Fake({this.connections = const [], this.available = true})
      : super(AppSettings(runtimeUrl: 'http://reader:8780'));

  final List<Map<String, dynamic>> connections;
  final bool available;
  int syncs = 0;

  @override
  Future<Map<String, dynamic>> bankFeeds() async => {
        'available': available,
        'sandbox': true,
        'connections': connections,
      };

  @override
  Future<Map<String, dynamic>> syncBankFeeds() async {
    syncs++;
    return {'new_lines': 3};
  }

  @override
  Future<Map<String, dynamic>> goals({String? today, bool noteAi = true}) async => {
        'goals': [
          {
            'goal': {'id': 'g1', 'name': 'Save £5,000 for the van', 'kind': 'save'},
            'kind_label': 'Save',
            'status': 'on_track',
            'status_label': 'On track',
            'tone': 'positive',
            'period_label': 'Nov 2026 – Apr 2027',
            'current_pence': 120000,
            'target_pence': 500000,
            'target_label': '£5,000.00',
            'variance_text': '£1,200.00 saved of £5,000.00',
            'source_text': 'Savings line',
            'measure': 'saved',
            'saved_pence': 120000,
            'drivers': [],
            'suggestions': [],
          }
        ],
        'note': {
          'note_md': noteAi ? 'AI: you are on track for the van.' : 'Code: on track.',
          'model': noteAi ? 'muse-spark-1.3' : 'code',
        },
      };
}

Widget _app(Widget child) => MaterialApp(home: Scaffold(body: ListView(children: [child])));

void main() {
  testWidgets('Home goals card shows the goal and the AI note', (tester) async {
    final c = _Fake();
    await tester.pumpWidget(_app(HomeGoalsCard(client: c, today: '2026-11-04')));
    await tester.pumpAndSettle();
    expect(find.text('Goals & progress'), findsOneWidget);
    expect(find.text('Save £5,000 for the van'), findsOneWidget);
    expect(find.text('On track'), findsOneWidget);
    expect(find.text('AI: you are on track for the van.'), findsOneWidget);
    expect(find.text('All goals'), findsOneWidget);
  });

  testWidgets('Bank sync: no bank connected offers set-up on the web', (tester) async {
    Uri? opened;
    await tester.pumpWidget(_app(BankSyncCard(
      clientFor: () async => _Fake(),
      onSynced: () {},
      openUrl: (u) async => opened = u,
    )));
    await tester.pumpAndSettle();
    expect(find.text('Automatic bank sync'), findsOneWidget);
    await tester.tap(find.byKey(const Key('bank-sync-setup')));
    await tester.pumpAndSettle();
    expect(opened, BankSyncCard.setupUrl);
  });

  testWidgets('Bank sync: a connected bank syncs now', (tester) async {
    final c = _Fake(connections: [
      {'bank': 'Starling', 'last_synced_at': '2026-11-03T08:00:00Z', 'message': ''}
    ]);
    var synced = 0;
    await tester.pumpWidget(_app(BankSyncCard(clientFor: () async => c, onSynced: () => synced++)));
    await tester.pumpAndSettle();
    expect(find.textContaining('Starling · last synced 3 Nov 2026'), findsOneWidget);
    await tester.tap(find.byKey(const Key('bank-sync-now')));
    await tester.pumpAndSettle();
    expect(c.syncs, 1);
    expect(synced, 1);
    expect(find.text('Bank synced: 3 new lines.'), findsOneWidget);
  });

  testWidgets('Bank sync hidden where feeds are not offered', (tester) async {
    await tester.pumpWidget(_app(BankSyncCard(clientFor: () async => _Fake(available: false), onSynced: () {})));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('bank-sync')), findsNothing);
  });
}
