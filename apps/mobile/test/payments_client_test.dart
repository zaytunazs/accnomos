import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';

/// The payments/credits calls hit the same paths and bodies as the web's
/// `runtime` in `apps/web/src/lib/runtime.ts`. A recording mock stands in
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

  test('recordInvoicePayment posts amount, date, account and reference',
      () async {
    final updated = await http.runWithClient(
      () => client().recordInvoicePayment(
        'INV-2041',
        amountPence: 12050,
        paidOn: '2026-10-27',
        account: '1210 Cash',
        paymentRef: 'transfer 1',
      ),
      () => mock({'number': 'INV-2041'}),
    );
    expect(updated['number'], 'INV-2041');
    final request = captured.single;
    expect(request.method, 'POST');
    expect(request.url.path, '/invoices/INV-2041/payments');
    expect(
      json.decode(lastBody(request)!),
      {
        'amount_pence': 12050,
        'paid_on': '2026-10-27',
        'account': '1210 Cash',
        'payment_ref': 'transfer 1',
      },
    );
  });

  test('recordInvoicePayment omits what was not typed', () async {
    await http.runWithClient(
      () => client().recordInvoicePayment('INV-1'),
      () => mock({'number': 'INV-1'}),
    );
    expect(
      json.decode(lastBody(captured.single)!),
      {'account': '1200 Bank'},
    );
  });

  test('removeInvoicePayment deletes the payment on the invoice', () async {
    await http.runWithClient(
      () => client().removeInvoicePayment('INV-1', 'abc123'),
      () => mock({'number': 'INV-1'}),
    );
    final request = captured.single;
    expect(request.method, 'DELETE');
    expect(request.url.path, '/invoices/INV-1/payments/abc123');
  });

  test('createCreditNote confirms and credits the whole invoice', () async {
    final created = await http.runWithClient(
      () => client().createCreditNote(
        'INV-1',
        reason: 'Returned goods',
        issueDate: '2026-10-27',
      ),
      () => mock({'number': 'CN-0001'}),
    );
    expect(created['number'], 'CN-0001');
    final request = captured.single;
    expect(request.method, 'POST');
    expect(request.url.path, '/invoices/INV-1/credit-notes');
    expect(
      json.decode(lastBody(request)!),
      {
        'confirm': true,
        'reason': 'Returned goods',
        'issue_date': '2026-10-27',
      },
    );
  });

  test('createCreditNote sends chosen lines and quantities', () async {
    await http.runWithClient(
      () => client().createCreditNote(
        'INV-1',
        reason: 'Short delivery',
        lines: [
          {'line': '2', 'quantity': '1'}
        ],
      ),
      () => mock({'number': 'CN-0002'}),
    );
    final body = json.decode(lastBody(captured.single)!)
        as Map<String, dynamic>;
    expect(body['confirm'], isTrue);
    expect(body['lines'], [
      {'line': '2', 'quantity': '1'}
    ]);
  });

  test('voidInvoice posts the reason', () async {
    await http.runWithClient(
      () => client().voidInvoice('INV-1', 'Raised by mistake'),
      () => mock({'number': 'INV-1', 'status': 'void'}),
    );
    final request = captured.single;
    expect(request.method, 'POST');
    expect(request.url.path, '/invoices/INV-1/void');
    expect(json.decode(lastBody(request)!),
        {'reason': 'Raised by mistake'});
  });

  test('a refusal carries the runtime sentence', () async {
    final api = client();
    final mockClient = mock({'detail': 'INV-1 is paid'}, status: 409);
    try {
      await http.runWithClient(
        () => api.voidInvoice('INV-1', 'x'),
        () => mockClient,
      );
      fail('expected a RuntimeException');
    } on RuntimeException catch (e) {
      expect(e.message, contains('INV-1 is paid'));
      expect(e.message, contains('status 409'));
    }
  });

  test('recordPayment posts the bill split to /payments', () async {
    final body = {
      'side': 'purchase',
      'date': '2026-10-27',
      'amount_pence': 48210,
      'account': '1200 Bank',
      'allocations': [
        {'event_id': 'abcdef01', 'amount_pence': 48210}
      ],
    };
    final recorded = await http.runWithClient(
      () => client().recordPayment(body),
      () => mock({'id': 'pay1'}),
    );
    expect(recorded['id'], 'pay1');
    final request = captured.single;
    expect(request.method, 'POST');
    expect(request.url.path, '/payments');
    expect(json.decode(lastBody(request)!), body);
  });

  test('removePayment deletes the recorded payment', () async {
    await http.runWithClient(
      () => client().removePayment('pay1'),
      () => mock({'documents': ['INV-1']}),
    );
    final request = captured.single;
    expect(request.method, 'DELETE');
    expect(request.url.path, '/payments/pay1');
  });

  test('openDocuments asks for purchase bills', () async {
    final docs = await http.runWithClient(
      () => client().openDocuments(side: 'purchase'),
      () => mock([
        {'event_id': 'abcdef01', 'outstanding_pence': 100}
      ]),
    );
    expect(docs.single['event_id'], 'abcdef01');
    final request = captured.single;
    expect(request.url.path, '/payments/open');
    expect(request.url.queryParameters['side'], 'purchase');
  });

  test('credits lists one side of the book', () async {
    final rows = await http.runWithClient(
      () => client().credits(side: 'sale'),
      () => mock([
        {'id': 'payment:abc', 'amount_pence': 500}
      ]),
    );
    expect(rows.single['id'], 'payment:abc');
    final request = captured.single;
    expect(request.url.path, '/credits');
    expect(request.url.queryParameters['side'], 'sale');
  });

  test('applyCredit posts the credit and the open document', () async {
    final used = await http.runWithClient(
      () => client().applyCredit(
        credit: 'payment:abc',
        eventId: 'abcdef01',
        date: '2026-10-27',
      ),
      () => mock({'id': 'use1', 'kind': 'apply'}),
    );
    expect(used['kind'], 'apply');
    final request = captured.single;
    expect(request.url.path, '/credits/apply');
    expect(
      json.decode(lastBody(request)!),
      {
        'credit': 'payment:abc',
        'event_id': 'abcdef01',
        'date': '2026-10-27',
      },
    );
  });

  test('refundCredit posts amount, date and account', () async {
    await http.runWithClient(
      () => client().refundCredit(
        credit: 'credit_note:def',
        amountPence: 2500,
        date: '2026-10-27',
        account: '1210 Cash',
        reference: 'bank ref',
      ),
      () => mock({'id': 'use2', 'kind': 'refund'}),
    );
    final request = captured.single;
    expect(request.url.path, '/credits/refund');
    expect(
      json.decode(lastBody(request)!),
      {
        'credit': 'credit_note:def',
        'amount_pence': 2500,
        'date': '2026-10-27',
        'account': '1210 Cash',
        'reference': 'bank ref',
      },
    );
  });

  test('removeCreditUse deletes the apply or refund', () async {
    await http.runWithClient(
      () => client().removeCreditUse('use1'),
      () => mock({'id': 'use1'}),
    );
    final request = captured.single;
    expect(request.method, 'DELETE');
    expect(request.url.path, '/credits/uses/use1');
  });

  test('editContact sends payment terms as a number', () async {
    final updated = await http.runWithClient(
      () => client().editContact('contact-1', {'terms_days': 14}),
      () => mock({'id': 'contact-1', 'terms_days': 14}),
    );
    expect(updated['terms_days'], 14);
    final request = captured.single;
    expect(request.method, 'PUT');
    expect(request.url.path, '/contacts/contact-1');
    expect(json.decode(lastBody(request)!), {'terms_days': 14});
  });

  test('creditNotes lists the notes for one invoice', () async {
    final notes = await http.runWithClient(
      () => client().creditNotes(invoice: 'INV-1'),
      () => mock([
        {'number': 'CN-0001'}
      ]),
    );
    expect(notes.single['number'], 'CN-0001');
    final request = captured.single;
    expect(request.url.path, '/credit-notes');
    expect(request.url.queryParameters['invoice'], 'INV-1');
  });
}
