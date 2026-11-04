import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:accnomos_mobile/models/calendar.dart';
import 'package:accnomos_mobile/screens/calendar_screen.dart';
import 'package:accnomos_mobile/screens/more_screen.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:accnomos_mobile/widgets/calendar_sync.dart';

/// Calendar on Android, against a fake runtime with the web's contract
/// (services/runtime/app/routes_calendar.py): the two-week list, the clash
/// prompt, remove with confirm, the automatic switch and the per-deadline
/// "Add to calendar".
class FakeCalendarRuntime {
  final requests = <http.Request>[];
  final events = <Map<String, Object?>>[
    {
      'id': 'e1',
      'subject': 'Site meeting, Harbour Lane kitchen',
      'start': '2026-10-29T09:00:00+00:00',
      'end': '2026-10-29T10:00:00+00:00',
      'all_day': false,
      'location': '12 Harbour Lane',
      'accnomos': false,
    },
  ];
  final deadlines = <Map<String, Object?>>[
    {'key': 'deadline:vat:abc', 'kind': 'vat', 'title': 'VAT return Jul–Sep 2026 due', 'day': '2026-11-07'},
    {'key': 'invoice:INV-0042', 'kind': 'invoice', 'title': 'Invoice INV-0042 due', 'day': '2026-11-12'},
  ];
  final inCalendar = <String>{};
  bool keep = false;
  String? lastSync;

  http.Response _ok(Object? body, [int code = 200]) =>
      http.Response(json.encode(body), code, headers: {'content-type': 'application/json'});

  Map<String, Object?> _status() => {
        'synced': lastSync != null,
        'keep': keep,
        'last_sync': lastSync,
        'count': inCalendar.length,
      };

  Map<String, Object?> _ev(Map<String, Object?> d) => {
        'id': 'dl-${d['key']}',
        'subject': d['title'],
        'start': '${d['day']}T00:00:00+00:00',
        'end': '${d['day']}T00:00:00+00:00',
        'all_day': true,
        'accnomos': true,
      };

  late final client = MockClient((r) async {
    requests.add(r);
    final path = r.url.path;
    final body = r.body.isEmpty ? <String, dynamic>{} : json.decode(r.body) as Map<String, dynamic>;
    if (path == '/calendar/events' && r.method == 'GET') return _ok(events);
    if (path == '/calendar/conflicts') return _ok(<Object>[]);
    if (path == '/calendar/events' && r.method == 'POST') {
      final clash = events.where((e) => e['all_day'] == false && (body['start'] as String).startsWith('2026-10-29T09')).toList();
      if (body['check_only'] == true) {
        return _ok({
          'conflicts': [
            for (final e in clash)
              {'id': e['id'], 'subject': e['subject'], 'start': e['start'], 'end': e['end'], 'all_day': false},
          ],
        });
      }
      if (clash.isNotEmpty && body['allow_conflict'] != true) return _ok({'detail': 'clash'}, 409);
      final made = {
        'id': 'e${events.length + 1}',
        'subject': body['subject'],
        'start': '${body['start']}:00+00:00',
        'end': '${body['end']}:00+00:00',
        'all_day': body['all_day'] == true,
        'accnomos': true,
      };
      events.add(made);
      return _ok(made, 201);
    }
    if (path.startsWith('/calendar/events/') && r.method == 'DELETE') {
      if (body['confirm'] != true) return _ok({'detail': 'confirm'}, 400);
      events.removeWhere((e) => e['id'] == path.split('/').last);
      return http.Response('', 204);
    }
    if (path == '/calendar/deadlines') {
      return _ok({
        'items': [for (final d in deadlines) {...d, 'in_calendar': inCalendar.contains(d['key'])}],
        ..._status(),
      });
    }
    if (path == '/calendar/deadlines/status') return _ok(_status());
    if (path == '/calendar/deadlines/preference') {
      keep = body['keep'] == true;
      return _ok(_status());
    }
    if (path == '/calendar/deadlines/sync') {
      final keys = (body['keys'] as List?)?.cast<String>();
      final wanted = [for (final d in deadlines) if (keys == null || keys.contains(d['key'])) d];
      var added = 0;
      for (final d in wanted) {
        if (inCalendar.add(d['key']! as String)) {
          added++;
          events.add(_ev(d));
        }
      }
      lastSync = '2026-10-27T09:15:00+00:00';
      return _ok({
        'added': added,
        'updated': 0,
        'unchanged': wanted.length - added,
        'removed': 0,
        'events': [for (final d in wanted) _ev(d)],
        'conflicts': <Object>[],
      });
    }
    return _ok({'detail': 'not found'}, 404);
  });

  RuntimeClient runtime() => RuntimeClient(
        AppSettings(runtimeUrl: 'http://reader'),
        books: BooksAuth(graphToken: 'tok', accountKind: 'personal', user: 'sam@example.co.uk'),
        httpClient: client,
      );

  Future<RuntimeClient> clientFor() async => runtime();

  Iterable<http.Request> to(String method, String path) =>
      requests.where((r) => r.method == method && r.url.path == path);
}

Widget _app(Widget child) => MaterialApp(home: child);

void main() {
  late FakeCalendarRuntime fake;
  setUp(() => fake = FakeCalendarRuntime());

  Future<void> phone(WidgetTester tester) async {
    tester.view.physicalSize = const Size(360 * 3, 800 * 3);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
  }

  testWidgets('two weeks by day, a clash asked about before anything is written, Add anyway, Remove with confirm',
      (tester) async {
    await phone(tester);
    await tester.pumpWidget(_app(CalendarScreen(
        read: fake.clientFor, write: fake.clientFor, today: DateTime(2026, 10, 29))));
    await tester.pumpAndSettle();

    expect(find.text('Thu 29 Oct'), findsOneWidget);
    expect(find.text('Site meeting, Harbour Lane kitchen'), findsOneWidget);
    expect(find.text('09:00–10:00'), findsOneWidget);
    expect(find.text('12 Harbour Lane'), findsOneWidget);
    expect(find.text('Added by Accnomos'), findsNothing);
    final events = fake.to('GET', '/calendar/events').first.url.queryParameters;
    expect(events['start'], '2026-10-29');
    expect(events['end'], '2026-11-11');

    // + Add an event on the first day shown (Thu 29 Oct), 09:00: the clash is said first; Cancel writes nothing.
    await tester.tap(find.byKey(const Key('calendar-add')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('event-title')), 'Call with the accountant');
    await tester.tap(find.byKey(const Key('event-submit')));
    await tester.pumpAndSettle();
    expect(find.text("Clashes with 'Site meeting, Harbour Lane kitchen' 09:00–10:00"), findsOneWidget);
    expect(find.text('Add anyway'), findsOneWidget);
    expect(fake.to('POST', '/calendar/events').length, 1); // the check only
    await tester.tap(find.byKey(const Key('event-cancel')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('event-clash')), findsNothing);
    expect(fake.events.length, 1);

    await tester.tap(find.byKey(const Key('event-submit')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('event-add-anyway')));
    await tester.pumpAndSettle();
    final added = json.decode(fake.to('POST', '/calendar/events').last.body) as Map<String, dynamic>;
    expect(added['allow_conflict'], true);
    expect(added['subject'], 'Call with the accountant');
    expect(added['start'], '2026-10-29T09:00');
    expect(find.text("Added 'Call with the accountant' to your calendar."), findsOneWidget);
    expect(find.text('Call with the accountant'), findsOneWidget);
    expect(find.text('Added by Accnomos'), findsOneWidget);

    // Remove: asked first; Keep changes nothing, Yes removes it.
    await tester.tap(find.byKey(const Key('remove-e2')));
    await tester.pumpAndSettle();
    expect(find.text('Remove it?'), findsOneWidget);
    await tester.tap(find.text('Keep'));
    await tester.pumpAndSettle();
    expect(fake.to('DELETE', '/calendar/events/e2'), isEmpty);
    await tester.tap(find.byKey(const Key('remove-e2')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('confirm-remove')));
    await tester.pumpAndSettle();
    final del = fake.to('DELETE', '/calendar/events/e2').single;
    expect(json.decode(del.body), {'confirm': true});
    expect(find.text('Call with the accountant'), findsNothing);
    expect(find.text("Removed 'Call with the accountant'."), findsOneWidget);
  });

  testWidgets('the switch saves at once and adds every deadline; the status says how many and when', (tester) async {
    await phone(tester);
    final sync = DeadlineSync(read: fake.clientFor, write: fake.clientFor);
    addTearDown(sync.dispose);
    await tester.pumpWidget(_app(Scaffold(body: SingleChildScrollView(child: CalendarSyncPanel(sync: sync)))));
    await sync.load();
    await tester.pumpAndSettle();
    expect(find.text('No deadlines in your calendar yet.'), findsOneWidget);
    expect(find.textContaining('Outlook'), findsOneWidget); // small print only

    await tester.tap(find.byKey(const Key('calendar-keep-switch')));
    await tester.pumpAndSettle();
    expect(json.decode(fake.to('PUT', '/calendar/deadlines/preference').single.body), {'keep': true});
    final all = json.decode(fake.to('POST', '/calendar/deadlines/sync').single.body) as Map<String, dynamic>;
    expect(all, {'confirm': true});
    expect(find.text('Done: 2 added.'), findsOneWidget);
    expect(sync.status!.line(now: DateTime(2026, 10, 27, 12)), '2 deadlines in your calendar · updated 09:15');
    final on = tester.widget<SwitchListTile>(find.byKey(const Key('calendar-keep-switch')));
    expect(on.value, isTrue);

    // twice: nothing new
    await tester.tap(find.byKey(const Key('calendar-sync-all')));
    await tester.pumpAndSettle();
    expect(find.text('Your calendar already has every deadline.'), findsOneWidget);
    expect(fake.events.where((e) => e['accnomos'] == true).length, 2);
  });

  testWidgets('Home deadlines: one deadline goes into the calendar and then says so', (tester) async {
    await phone(tester);
    final sync = DeadlineSync(read: fake.clientFor, write: fake.clientFor);
    addTearDown(sync.dispose);
    await tester.pumpWidget(_app(Scaffold(body: HomeDeadlinesCard(sync: sync))));
    await tester.pumpAndSettle();
    expect(find.text('VAT return Jul–Sep 2026 due'), findsOneWidget);
    expect(find.text('7 Nov 2026'), findsOneWidget);
    expect(find.text('Add to calendar'), findsNWidgets(2));
    final semantics = tester.ensureSemantics();
    expect(find.bySemanticsLabel('Add to calendar: VAT return Jul–Sep 2026 due'), findsOneWidget);
    semantics.dispose();

    await tester.tap(find.byKey(const Key('add-deadline-deadline:vat:abc')));
    await tester.pumpAndSettle();
    final one = json.decode(fake.to('POST', '/calendar/deadlines/sync').single.body) as Map<String, dynamic>;
    expect(one, {
      'confirm': true,
      'keys': ['deadline:vat:abc'],
    });
    expect(find.text('In your calendar ✓'), findsOneWidget);
    expect(find.text('Add to calendar'), findsOneWidget); // the invoice is still to add
    expect(find.text('Added to your calendar: VAT return Jul–Sep 2026 due.'), findsOneWidget);
    expect(fake.inCalendar, {'deadline:vat:abc'});
  });

  testWidgets('Home refreshes the calendar when the switch is on and the last update is old', (tester) async {
    fake
      ..keep = true
      ..lastSync = '2026-10-26T08:00:00+00:00';
    final sync = DeadlineSync(read: fake.clientFor, write: fake.clientFor);
    addTearDown(sync.dispose);
    await tester.pumpWidget(_app(Scaffold(body: HomeDeadlinesCard(sync: sync, now: DateTime(2026, 10, 27, 12)))));
    await tester.pumpAndSettle();
    expect(fake.to('POST', '/calendar/deadlines/sync'), hasLength(1));
    expect(find.text('In your calendar ✓'), findsNWidgets(2));
  });

  testWidgets('the VAT due line has its own Add to calendar', (tester) async {
    final sync = DeadlineSync(read: fake.clientFor, write: fake.clientFor);
    addTearDown(sync.dispose);
    await tester.pumpWidget(_app(Scaffold(body: VatDueCalendarLine(sync: sync))));
    await tester.pumpAndSettle();
    expect(find.text('VAT return Jul–Sep 2026 due · 7 Nov 2026'), findsOneWidget);
    await tester.tap(find.text('Add to calendar'));
    await tester.pumpAndSettle();
    expect(find.text('In your calendar ✓'), findsOneWidget);
  });

  test('More lists Calendar for every set of business books', () {
    final titles = [for (final e in moreEntries(const ['invoices'])) e.title];
    expect(titles, contains('Calendar'));
    expect(CalendarScreen.route, '/calendar');
  });

  test('the client sends the VAT period with a sync, and the labels read as on the web', () async {
    final client = RuntimeClient(
      AppSettings(runtimeUrl: 'http://reader', vatStagger: 2),
      books: BooksAuth(graphToken: 'tok', accountKind: 'personal'),
      httpClient: fake.client,
    );
    await client.syncDeadlines(keys: ['invoice:INV-0042']);
    final r = fake.to('POST', '/calendar/deadlines/sync').single;
    expect(r.url.queryParameters['stagger'], '2');
    expect(json.decode(r.body)['keys'], ['invoice:INV-0042']);

    expect(updatedLabel('2026-10-27T09:15:00+00:00', now: DateTime(2026, 10, 27, 20)), 'updated 09:15');
    expect(updatedLabel('2026-10-26T09:15:00+00:00', now: DateTime(2026, 10, 27)), 'updated 26 Oct');
    expect(dayHeading('2026-10-29'), 'Thu 29 Oct');
    expect(
      const CalendarClash(subject: 'Site meeting', start: '2026-10-29T09:00:00+00:00', end: '2026-10-29T10:00:00+00:00', allDay: false)
          .sentence,
      "Clashes with 'Site meeting' 09:00–10:00",
    );
  });
}
