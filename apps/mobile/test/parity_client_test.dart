import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';

/// The parity-audit calls hit the same paths and bodies as the web's
/// `runtime` in `apps/web/src/lib/runtime.ts`: bank rules CRUD, the
/// Your-data export and the audit filters. A recording mock stands in
/// for the reader; each test asserts the wire shape and the decoded answer.
void main() {
  RuntimeClient client() => RuntimeClient(
        AppSettings(runtimeUrl: 'http://reader'),
        books: BooksAuth(
          graphToken: 'tok',
          accountKind: 'personal',
          user: 'user@example.com',
        ),
      );

  final captured = <http.BaseRequest>[];
  String? lastBody(http.BaseRequest request) =>
      request is http.Request ? request.body : null;

  MockClient mock(Object jsonBody, {int status = 200}) {
    captured.clear();
    return MockClient((request) async {
      captured.add(request);
      final body = jsonBody is String ? jsonBody : json.encode(jsonBody);
      return http.Response(body, status,
          headers: {'content-type': 'application/json'});
    });
  }

  Map<String, dynamic> ruleBody() => {
        'name': 'Tesco',
        'match': {'op': 'contains', 'value': 'TESCO'},
        'amount_min_pence': null,
        'amount_max_pence': null,
        'direction': 'out',
        'action': {
          'account': '6000 Groceries',
          'vat_code': 'S',
          'contact': null,
          'job_id': null,
        },
      };

  test('createBankRule posts the web-shaped rule', () async {
    final created = await http.runWithClient(
      () => client().createBankRule(ruleBody()),
      () => mock({'id': 'abc123', 'name': 'Tesco'}),
    );
    expect(created['id'], 'abc123');
    final request = captured.single;
    expect(request.method, 'POST');
    expect(request.url.path, '/books/bank/rules');
    expect(json.decode(lastBody(request)!), ruleBody());
  });

  test('updateBankRule puts the rule by id', () async {
    final updated = await http.runWithClient(
      () => client().updateBankRule('abc123', ruleBody()),
      () => mock({'id': 'abc123', 'name': 'Tesco'}),
    );
    expect(updated['name'], 'Tesco');
    final request = captured.single;
    expect(request.method, 'PUT');
    expect(request.url.path, '/books/bank/rules/abc123');
    expect(json.decode(lastBody(request)!), ruleBody());
  });

  test('deleteBankRule deletes the rule by id', () async {
    final gone = await http.runWithClient(
      () => client().deleteBankRule('abc123'),
      () => mock({'id': 'abc123'}),
    );
    expect(gone['id'], 'abc123');
    final request = captured.single;
    expect(request.method, 'DELETE');
    expect(request.url.path, '/books/bank/rules/abc123');
  });

  test('a rule refusal carries the runtime sentence', () async {
    final api = client();
    try {
      await http.runWithClient(
        () => api.createBankRule(ruleBody()),
        () => mock('The minimum amount is above the maximum amount',
            status: 400),
      );
      fail('expected a RuntimeException');
    } on RuntimeException catch (e) {
      expect(e.message, contains('minimum amount'));
      expect(e.message, contains('status 400'));
    }
  });

  test('booksExport posts the data export', () async {
    final result = await http.runWithClient(
      () => client().booksExport(),
      () => mock({
        'path': '07 Reports/Exports/accnomos-export-2026-10-27.zip',
        'name': 'accnomos-export-2026-10-27.zip',
        'size': 1024,
        'files': 12,
        'web_url': null,
      }),
    );
    expect(result['files'], 12);
    final request = captured.single;
    expect(request.method, 'POST');
    expect(request.url.path, '/books/export');
  });

  test('audit sends who, what and the date range', () async {
    await http.runWithClient(
      () => client().audit(
        from: '2026-09-26',
        to: '2026-10-27',
        actor: 'autopilot',
        kind: 'invoice',
      ),
      () => mock({'entries': [], 'truncated': false}),
    );
    final request = captured.single;
    expect(request.method, 'GET');
    expect(request.url.path, '/audit');
    expect(request.url.queryParameters['from'], '2026-09-26');
    expect(request.url.queryParameters['to'], '2026-10-27');
    expect(request.url.queryParameters['actor'], 'autopilot');
    expect(request.url.queryParameters['kind'], 'invoice');
  });

  test('audit omits filters that were not picked', () async {
    await http.runWithClient(
      () => client().audit(),
      () => mock({'entries': [], 'truncated': false}),
    );
    final params = captured.single.url.queryParameters;
    expect(params.containsKey('actor'), isFalse);
    expect(params.containsKey('kind'), isFalse);
    expect(params.containsKey('from'), isFalse);
    expect(params.containsKey('to'), isFalse);
    expect(params['limit'], '200');
  });
}
