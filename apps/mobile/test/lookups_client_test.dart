import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';

/// The look-up and duplicates calls hit the same paths and bodies as the
/// web's `runtime` in `apps/web/src/lib/runtime.ts`. A recording mock stands
/// in for the reader; each test asserts the wire shape and the decoded
/// answer.
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

  test('lookupStatus asks without sign-in and answers null when silent',
      () async {
    final status = await http.runWithClient(
      () => client().lookupStatus(),
      () => mock({
        'companies_house': true,
        'vat_check': false,
        'sample': true,
      }),
    );
    expect(status?['companies_house'], isTrue);
    expect(status?['vat_check'], isFalse);
    final request = captured.single;
    expect(request.method, 'GET');
    expect(request.url.path, '/lookup/status');

    final silent = await http.runWithClient(
      () => client().lookupStatus(),
      () => mock('nope', status: 500),
    );
    expect(silent, isNull);
  });

  test('lookupCompanies searches by name', () async {
    final found = await http.runWithClient(
      () => client().lookupCompanies('Novex'),
      () => mock({
        'query': 'Novex',
        'items': [
          {
            'company_number': 'ZZ000001',
            'name': 'NOVEX OFFICE SUPPLIES LIMITED',
            'status': 'active',
            'type': 'ltd',
            'address': '14 Industrial Park, Leeds, LS10 1AB',
            'date_of_creation': '2019-04-02',
            'source': 'sample',
            'sample': true,
          },
        ],
      }),
    );
    expect((found['items'] as List).single['company_number'], 'ZZ000001');
    final request = captured.single;
    expect(request.method, 'GET');
    expect(request.url.path, '/lookup/companies');
    expect(request.url.queryParameters['q'], 'Novex');
  });

  test('vatCheck posts the VRN, name and contact', () async {
    final result = await http.runWithClient(
      () => client().vatCheck(
        vrn: 'GB882431902',
        name: 'Novex Office Supplies Ltd',
        contactId: 'abc123',
      ),
      () => mock({
        'check': {'vrn': 'GB882431902', 'registered': true},
        'name_differs': false,
        'contact_id': 'abc123',
        'cached': false,
      }),
    );
    expect(result['cached'], isFalse);
    final request = captured.single;
    expect(request.method, 'POST');
    expect(request.url.path, '/contacts/vat-check');
    expect(
      json.decode(lastBody(request)!),
      {
        'vrn': 'GB882431902',
        'name': 'Novex Office Supplies Ltd',
        'contact_id': 'abc123',
      },
    );
  });

  test('vatCheck omits what was not passed', () async {
    await http.runWithClient(
      () => client().vatCheck(vrn: 'GB123456789'),
      () => mock({'cached': true}),
    );
    expect(
      json.decode(lastBody(captured.single)!),
      {'vrn': 'GB123456789'},
    );
  });

  test('duplicates lists the candidate groups', () async {
    final decode = await http.runWithClient(
      () => client().duplicates(),
      () => mock({
        'groups': [
          {
            'contact_ids': ['a1', 'b2'],
            'contacts': [],
            'evidence': ['same phone +447700900123'],
            'blocked': false,
            'ai': {
              'same': true,
              'confidence': 0.9,
              'keep_name': 'Novex',
              'reason': 'Same phone and name.',
            },
          },
        ],
      }),
    );
    expect((decode['groups'] as List).single['blocked'], isFalse);
    final request = captured.single;
    expect(request.method, 'GET');
    expect(request.url.path, '/contacts/duplicates');
  });

  test('dismissDuplicates posts the pair', () async {
    await http.runWithClient(
      () => client().dismissDuplicates(['a1', 'b2']),
      () => mock({'dismissed': ['a1', 'b2']}),
    );
    final request = captured.single;
    expect(request.method, 'POST');
    expect(request.url.path, '/contacts/duplicates/dismiss');
    expect(
      json.decode(lastBody(request)!),
      {
        'contact_ids': ['a1', 'b2'],
      },
    );
  });

  test('mergeContacts posts keep, merges and the chosen name', () async {
    final result = await http.runWithClient(
      () => client().mergeContacts(
        keepId: 'a1',
        mergeIds: ['b2'],
        name: 'Novex Office Supplies Ltd',
      ),
      () => mock({
        'contact': {'id': 'a1', 'name': 'Novex Office Supplies Ltd'},
        'merge_id': 'm1',
      }),
    );
    expect(result['merge_id'], 'm1');
    final request = captured.single;
    expect(request.method, 'POST');
    expect(request.url.path, '/contacts/merge');
    expect(
      json.decode(lastBody(request)!),
      {
        'keep_id': 'a1',
        'merge_ids': ['b2'],
        'name': 'Novex Office Supplies Ltd',
      },
    );
  });

  test('undoContactMerge posts to the merge id', () async {
    await http.runWithClient(
      () => client().undoContactMerge('m1'),
      () => mock({'contacts': []}),
    );
    final request = captured.single;
    expect(request.method, 'POST');
    expect(request.url.path, '/contacts/merge/m1/undo');
  });

  test('lookupNotConfigured spots the 503 codes only', () {
    RuntimeException refused(String code) => RuntimeException(
        'The reader refused that request (status 503). '
        '{"error": "$code", "detail": "not set up"}');
    expect(
        RuntimeClient.lookupNotConfigured(
            refused('vat_check_not_configured'), 'vat_check_not_configured'),
        isTrue);
    expect(
        RuntimeClient.lookupNotConfigured(refused('vat_check_not_configured'),
            'companies_house_not_configured'),
        isFalse);
    expect(
        RuntimeClient.lookupNotConfigured(
            RuntimeException('Could not load contacts. boom'), 'vat_check_not_configured'),
        isFalse);
    expect(
        RuntimeClient.lookupNotConfigured(
            StateError('nope'), 'vat_check_not_configured'),
        isFalse);
  });
}
