import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';

/// Before sign-in the phone reads receipts on a demo session: `POST
/// /demo/session`, then `X-Demo-Session` on `/extract` (the runtime refuses
/// `/extract` without a sign-in or a demo session). Signed in is unchanged.
void main() {
  late Directory dir;
  late File photo;
  final calls = <String>[];
  final extractHeaders = <Map<String, String>>[];

  setUp(() async {
    RuntimeClient.forgetDemoSession();
    calls.clear();
    extractHeaders.clear();
    dir = await Directory.systemTemp.createTemp('extract_demo');
    photo = File('${dir.path}/r.jpg')..writeAsBytesSync([1, 2, 3]);
  });

  tearDown(() => dir.delete(recursive: true));

  RuntimeClient signedOut(MockClient mock) =>
      RuntimeClient(AppSettings(runtimeUrl: 'http://reader'), httpClient: mock);

  http.Response ok(Object body) => http.Response(json.encode(body), 200,
      headers: {'content-type': 'application/json'});

  MockClient reader({int extractStatus = 200, int demoStatus = 200}) =>
      MockClient((request) async {
        calls.add('${request.method} ${request.url.path}');
        if (request.url.path == '/demo/session') {
          if (demoStatus != 200) {
            return http.Response('{"detail":"off"}', demoStatus);
          }
          return ok({'session': 'abc.def', 'business': 'Bramblewood'});
        }
        extractHeaders.add(request.headers);
        return extractStatus == 200
            ? ok({'doc_sha256': 'x', 'checks': []})
            : http.Response('{"detail":"sign in"}', extractStatus);
      });

  test('extract without a token starts a demo session first', () async {
    final client = signedOut(reader());
    final proposal = await client.extract(photo);
    expect(proposal['doc_sha256'], 'x');
    expect(calls, ['POST /demo/session', 'POST /extract']);
    expect(extractHeaders.single['X-Demo-Session'], 'abc.def');
    expect(extractHeaders.single.containsKey('X-Graph-Token'), isFalse);
  });

  test('a live demo session is reused', () async {
    final client = signedOut(reader());
    await client.extract(photo);
    calls.clear();
    await client.extract(photo);
    expect(calls, ['GET /demo/session', 'POST /extract']);
  });

  test('signed in sends the Graph token and no demo session', () async {
    final client = RuntimeClient(
      AppSettings(runtimeUrl: 'http://reader'),
      books: BooksAuth(graphToken: 'tok', accountKind: 'personal'),
      httpClient: reader(),
    );
    await client.extract(photo);
    expect(calls, ['POST /extract']);
    expect(extractHeaders.single['X-Graph-Token'], 'tok');
    expect(extractHeaders.single.containsKey('X-Demo-Session'), isFalse);
  });

  test('demo mode off says to sign in', () async {
    final client = signedOut(reader(demoStatus: 401));
    await expectLater(
      client.extract(photo),
      throwsA(isA<RuntimeException>()
          .having((e) => e.message, 'message', contains('Sign in'))),
    );
    expect(calls, ['POST /demo/session']);
  });

  test('a 401 from /extract surfaces the sign-in message', () async {
    final client = signedOut(reader(extractStatus: 401));
    await expectLater(
      client.extract(photo),
      throwsA(isA<RuntimeException>()
          .having((e) => e.message, 'message', contains('Sign in'))),
    );
  });
}
