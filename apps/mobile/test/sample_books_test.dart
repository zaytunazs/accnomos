import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:accnomos_mobile/models/sample_books.dart';
import 'package:accnomos_mobile/screens/sample_books_card.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';

/// Load sample books on Home: the three runtime calls, and the card at
/// 360 dp (button when the folder is empty, progress while it loads,
/// nothing/banner when done, the runtime's sentence on a 409).
void main() {
  late List<http.Request> requested;

  /// What the fake reader answers: GET returns [status]; a POST returns
  /// [postStatus] (and its body), or [postCode] with a `detail` sentence.
  late Map<String, dynamic> status;
  late Map<String, dynamic> postStatus;
  int postCode = 200;
  String postDetail = '';

  Map<String, dynamic> running(int done, {String state = 'running'}) => {
        'state': state,
        'step': 'Step name $done',
        'done': done,
        'total': 11,
        'steps': [for (var i = 0; i < 11; i++) 'Step name $i'],
        'business': 'Bramblewood Joinery Ltd',
      };

  RuntimeClient client() => RuntimeClient(
        AppSettings(runtimeUrl: 'http://reader'),
        books: BooksAuth(graphToken: 'tok', accountKind: 'personal'),
        httpClient: MockClient((request) async {
          requested.add(request);
          Map<String, dynamic> body = status;
          var code = 200;
          if (request.method == 'POST') {
            if (postCode != 200) {
              code = postCode;
              body = {'detail': postDetail};
            } else {
              body = postStatus;
              status = postStatus;
            }
          }
          return http.Response(json.encode(body), code,
              headers: {'content-type': 'application/json'});
        }),
      );

  setUp(() {
    requested = [];
    status = {'state': 'none', 'empty': true, 'done': 0, 'total': 0};
    postStatus = running(0);
    postCode = 200;
    postDetail = '';
  });

  Future<void> narrow(WidgetTester tester) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
  }

  Widget host({VoidCallback? onLoaded}) => MaterialApp(
        home: Scaffold(
          body: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              SampleBooksCard(
                clientFor: () async => client(),
                onLoaded: onLoaded,
              ),
            ],
          ),
        ),
      );

  Future<void> end(WidgetTester tester) async {
    await tester.pumpWidget(const SizedBox());
  }

  group('client', () {
    test('GET, POST and POST continue hit the web paths with books headers',
        () async {
      final c = client();
      final got = await c.sampleBooksStatus();
      expect(got.state, 'none');
      expect(got.empty, isTrue);
      await c.loadSampleBooks();
      await c.loadSampleBooks(carryOn: true);
      expect([for (final r in requested) '${r.method} ${r.url.path}'], [
        'GET /books/sample',
        'POST /books/sample',
        'POST /books/sample/continue',
      ]);
      expect(requested.first.headers['X-Graph-Token'], 'tok');
      expect(requested.first.headers['X-Account-Kind'], 'personal');
    });

    test('a 409 with a sentence is a SampleNote, not a failure', () async {
      postCode = 409;
      postDetail = 'Your Accnomos folder already has books in it.';
      await expectLater(
        client().loadSampleBooks(),
        throwsA(isA<SampleNote>().having(
            (n) => n.message, 'message', postDetail)),
      );
    });

    test('other refusals stay RuntimeException', () async {
      postCode = 500;
      postDetail = 'boom';
      await expectLater(
          client().loadSampleBooks(), throwsA(isA<RuntimeException>()));
    });

    test('status parses progress', () {
      final s = SampleStatus.fromJson(running(4));
      expect(s.running, isTrue);
      expect(s.done, 4);
      expect(s.total, 11);
      expect(s.steps, hasLength(11));
    });
  });

  group('card', () {
    testWidgets('empty folder: button shows, fits 360 dp', (tester) async {
      await narrow(tester);
      await tester.pumpWidget(host());
      await tester.pump();
      expect(find.text('Load sample books'), findsOneWidget);
      expect(find.text('Try it with sample books'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await end(tester);
    });

    testWidgets('folder with books: nothing is offered', (tester) async {
      status = {'state': 'none', 'empty': false};
      await tester.pumpWidget(host());
      await tester.pump();
      expect(find.text('Load sample books'), findsNothing);
      expect(find.text('Try it with sample books'), findsNothing);
      await end(tester);
    });

    testWidgets('tapping the button posts and shows progress', (tester) async {
      await narrow(tester);
      postStatus = running(2);
      await tester.pumpWidget(host());
      await tester.pump();
      await tester.tap(find.text('Load sample books'));
      await tester.pump();
      await tester.pump();
      expect(requested.where((r) => r.method == 'POST').single.url.path,
          '/books/sample');
      expect(find.text('Step 3 of 11'), findsOneWidget);
      expect(find.text('Step name 2'), findsOneWidget);
      expect(find.text('Load sample books'), findsNothing);
      expect(find.byType(LinearProgressIndicator), findsOneWidget);
      expect(
          find.byWidgetPredicate((w) =>
              w is Semantics &&
              w.properties.label ==
                  'Loading sample books, step 3 of 11: Step name 2'),
          findsOneWidget);
      expect(tester.takeException(), isNull);
      await end(tester);
    });

    testWidgets('running: polls every 3 s and moves the bar', (tester) async {
      await narrow(tester);
      status = running(1);
      await tester.pumpWidget(host());
      await tester.pump();
      expect(find.text('Step 2 of 11'), findsOneWidget);
      status = running(5);
      await tester.pump(sampleBooksPollInterval);
      await tester.pump();
      expect(find.text('Step 6 of 11'), findsOneWidget);
      expect(find.text('Step name 5'), findsOneWidget);
      expect(requested.where((r) => r.method == 'GET').length, greaterThan(1));
      await end(tester);
    });

    testWidgets('needs_token: posts /continue on the next poll',
        (tester) async {
      status = running(3, state: 'needs_token');
      postStatus = running(3);
      await tester.pumpWidget(host());
      await tester.pump();
      expect(find.text('Waiting for your sign-in to renew…'), findsOneWidget);
      await tester.pump(sampleBooksPollInterval);
      await tester.pump();
      expect(
          requested.any((r) =>
              r.method == 'POST' && r.url.path == '/books/sample/continue'),
          isTrue);
      await end(tester);
    });

    testWidgets('running: a fresh token is handed over every 4 minutes',
        (tester) async {
      status = running(3);
      postStatus = running(3);
      await tester.pumpWidget(host());
      await tester.pump();
      await tester.pump(sampleBooksContinueInterval);
      await tester.pump();
      final posts = requested.where((r) => r.method == 'POST').toList();
      expect(posts, isNotEmpty);
      expect(posts.first.url.path, '/books/sample/continue');
      await end(tester);
    });

    testWidgets('done after a load: card goes, banner shows, Home refreshes',
        (tester) async {
      await narrow(tester);
      var loaded = 0;
      status = running(10);
      await tester.pumpWidget(host(onLoaded: () => loaded++));
      await tester.pump();
      status = {
        'state': 'done',
        'done': 11,
        'total': 11,
        'business': 'Bramblewood Joinery Ltd',
      };
      await tester.pump(sampleBooksPollInterval);
      await tester.pump();
      expect(find.byType(LinearProgressIndicator), findsNothing);
      expect(find.text('Load sample books'), findsNothing);
      expect(find.text('SAMPLE — FICTIONAL COMPANY'), findsOneWidget);
      expect(find.textContaining('Bramblewood Joinery Ltd'), findsOneWidget);
      expect(loaded, 1);
      // No further polling once it is done.
      final before = requested.length;
      await tester.pump(sampleBooksPollInterval * 3);
      expect(requested.length, before);
      expect(tester.takeException(), isNull);
      await end(tester);
    });

    testWidgets('already done on arrival: banner, no refresh call',
        (tester) async {
      var loaded = 0;
      status = {'state': 'done', 'done': 11, 'total': 11};
      await tester.pumpWidget(host(onLoaded: () => loaded++));
      await tester.pump();
      expect(find.text('SAMPLE — FICTIONAL COMPANY'), findsOneWidget);
      expect(find.text('Load sample books'), findsNothing);
      expect(loaded, 0);
      await end(tester);
    });

    testWidgets('409: the runtime sentence shows as a note', (tester) async {
      await narrow(tester);
      postCode = 409;
      postDetail =
          'Your Accnomos folder already has books in it (entries, receipts '
          'waiting in Review or contacts). Sample books only go into an '
          'empty folder, so nothing was changed.';
      await tester.pumpWidget(host());
      await tester.pump();
      await tester.tap(find.text('Load sample books'));
      await tester.pump();
      await tester.pump();
      expect(find.byKey(const Key('sample-note')), findsOneWidget);
      expect(find.textContaining('nothing was changed'), findsOneWidget);
      expect(find.text('Load sample books'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await end(tester);
    });

    testWidgets('failed: sentence and a carry-on button, no overflow',
        (tester) async {
      await narrow(tester);
      status = {
        ...running(4),
        'state': 'failed',
        'error': 'Loading stopped at “Step name 4”. Press Load sample books '
            'to carry on from there.',
      };
      await tester.pumpWidget(host());
      await tester.pump();
      expect(find.textContaining('Loading stopped at'), findsOneWidget);
      expect(find.text('Carry on loading sample books'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await end(tester);
    });

    testWidgets('a long step name wraps at 360 dp', (tester) async {
      await narrow(tester);
      status = {
        ...running(6),
        'step': 'Post six months of sales invoices, credit notes, payments '
            'and bank lines for the fictional joinery company',
      };
      await tester.pumpWidget(host());
      await tester.pump();
      expect(find.text('Step 7 of 11'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await end(tester);
    });
  });
}
