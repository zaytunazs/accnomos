import 'dart:convert';

import 'package:accnomos_mobile/models/ask_answer.dart';
import 'package:accnomos_mobile/models/paypal.dart';
import 'package:accnomos_mobile/screens/bill_pay_screen.dart';
import 'package:accnomos_mobile/screens/paypal_disputes_screen.dart';
import 'package:accnomos_mobile/screens/paypal_sync_screen.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:accnomos_mobile/services/voice_approval.dart';
import 'package:accnomos_mobile/widgets/action_card.dart';
import 'package:accnomos_mobile/widgets/upcoming_payments.dart';
import 'package:accnomos_mobile/services/share.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// PayPal on the phone: the models parse what the runtime sends (and survive
/// what it leaves out), the client hits the web's routes with the web's
/// bodies, and each screen gates the owner's approval the same way the web
/// does: a sale with no invoice needs its VAT chosen before Approve, evidence
/// and payments go only after the owner's tap.

/// A recording fake reader: [routes] maps "METHOD /path" to a JSON body.
class FakeReader {
  FakeReader(this.routes);

  final Map<String, Object? Function(http.Request r)> routes;
  final List<http.Request> calls = [];

  http.Client get client => MockClient((request) async {
        calls.add(request);
        final key = '${request.method} ${request.url.path}';
        final handler = routes[key];
        if (handler == null) {
          return http.Response('{"detail":"Not Found"}', 404,
              headers: {'content-type': 'application/json'});
        }
        final body = handler(request);
        return http.Response(body == null ? '' : body is String ? body : json.encode(body), body == null ? 204 : 200,
            headers: {'content-type': 'application/json'});
      });

  RuntimeClient runtime() => RuntimeClient(
        AppSettings(runtimeUrl: 'http://reader'),
        books: BooksAuth(
            graphToken: 'tok', accountKind: 'personal', user: 'owner@example.com'),
        httpClient: client,
      );

  List<http.Request> where(String method, String path) => [
        for (final c in calls)
          if (c.method == method && c.url.path == path) c,
      ];
}

Map<String, dynamic> saleNeedingVat() => {
      'transaction_id': 'T1',
      'date': '2026-11-10',
      'kind': 'sale',
      'status': 'proposed',
      'event_code': 'T0006',
      'name': 'Ada Lovelace',
      'items': ['Oak shelf'],
      'currency': 'GBP',
      'gross_pence': 12000,
      'fee_pence': 378,
      'net_pence': 11622,
      'invoice': null,
      'account': '4000 Sales',
      'vat_code': null,
      'coded_by': 'code: money in with no invoice of yours named, so a sale',
      'notes': ['A sale with no invoice in your books: choose its VAT before you approve it (no VAT is assumed).'],
      'journal': [
        {'account': '1240 PayPal clearing', 'debit_pence': 11622, 'credit_pence': 0},
        {'account': '7900 Bank charges', 'debit_pence': 378, 'credit_pence': 0, 'vat_code': 'E'},
        {'account': '4000 Sales', 'debit_pence': 0, 'credit_pence': 12000},
      ],
      'event_ids': [],
      'found_at': '2026-11-11T09:00:00Z',
    };

Map<String, dynamic> invoicePayment() => {
      'transaction_id': 'T2',
      'date': '2026-11-09',
      'kind': 'invoice',
      'status': 'proposed',
      'name': 'Bramble Ltd',
      'gross_pence': 48000,
      'fee_pence': 0,
      'net_pence': 48000,
      'invoice': 'INV-0007',
      'vat_code': 'S',
      'journal': [],
      'notes': [],
    };

Map<String, dynamic> upcoming({bool empty = false}) => {
      'today': '2026-11-11',
      'clearing_pence': 5000,
      'clearing_label': '1240 PayPal clearing by your books (not your live PayPal balance)',
      'next_7_pence': 21050,
      'next_30_pence': 31050,
      'shortfall_7_pence': 16050,
      'shortfall_30_pence': 26050,
      'warning': empty ? null : 'Your books show £50.00 in PayPal; £210.50 leaves it in the next 7 days.',
      'items': empty
          ? []
          : [
              {
                'event_id': 'cdef1234',
                'contact_id': '0123456789abcdef',
                'supplier': 'Glue Ltd',
                'date': '2026-11-14',
                'amount_pence': 10000,
                'payee_email': 'pay@glue.example',
                'status': 'scheduled',
                'approved': true,
                'calendar_uid': 'u1',
                'in_calendar': false,
                'title': 'Pay Glue Ltd',
                'description': '',
              },
              {
                'event_id': 'abcdef12',
                'supplier': 'Timber Co',
                'date': '2026-11-11',
                'amount_pence': 21050,
                'status': 'due_today',
                'approved': false,
                'in_calendar': true,
              },
            ],
      'calendar_stale': empty ? [] : ['deadbeef'],
      'note': 'Paid the next time Accnomos is open on or after each date.',
    };

void usePhone(WidgetTester tester, {double height = 2400}) {
  tester.view.physicalSize = Size(360, height);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('models', () {
    test('a sale with no invoice and no VAT needs the owner to choose', () {
      final i = PayPalSyncItem.fromJson(saleNeedingVat());
      expect(i.needsVatChoice, isTrue);
      expect(i.grossPence, 12000);
      expect(i.feePence, 378);
      expect(i.journal, hasLength(3));
      expect(i.journal[1].vatCode, 'E');
      expect(i.journal.first.debitPence, 11622);
      expect(i.kindLabel, 'Sale');
      final coded = PayPalSyncItem.fromJson({...saleNeedingVat(), 'vat_code': 'S'});
      expect(coded.needsVatChoice, isFalse);
      final decided = PayPalSyncItem.fromJson({...saleNeedingVat(), 'status': 'approved'});
      expect(decided.needsVatChoice, isFalse);
    });

    test('sync item and view survive missing fields', () {
      final i = PayPalSyncItem.fromJson(const {});
      expect(i.transactionId, '');
      expect(i.kind, 'other');
      expect(i.status, 'info');
      expect(i.currency, 'GBP');
      expect(i.grossPence, 0);
      expect(i.items, isEmpty);
      expect(i.journal, isEmpty);
      expect(i.needsVatChoice, isFalse);
      final v = PayPalSyncView.fromJson(const {'items': 'nonsense'});
      expect(v.available, isFalse);
      expect(v.items, isEmpty);
      final r = PayPalSyncResult.fromJson({
        'new': 2,
        'pending': 1,
        'items': [saleNeedingVat(), {...invoicePayment(), 'status': 'approved'}],
      });
      expect(r.summary, '2 new from PayPal · 1 waiting for you · 1 still pending at PayPal');
      expect(PayPalSyncResult.fromJson(const {}).summary,
          'Nothing new from PayPal · 0 waiting for you');
    });

    test('tie-out parses, and stays hidden without PayPal\'s figure', () {
      final t = PayPalTieOut.fromJson({
        'available': true,
        'paypal_pence': 25000,
        'paypal_as_of': '2026-11-11T14:29:59Z',
        'books_pence': 13378,
        'difference_pence': 11622,
        'waiting_pence': 11622,
        'not_posted_pence': 0,
        'unexplained_pence': 0,
        'notes': ['Your books match PayPal to the penny once the items waiting are approved.'],
      });
      expect(t.shown, isTrue);
      expect(t.ties, isTrue);
      expect(t.differencePence, 11622);
      final empty = PayPalTieOut.fromJson(const {'available': false, 'reason': 'Not connected'});
      expect(empty.shown, isFalse);
      expect(empty.booksPence, 0);
      expect(empty.unexplainedPence, isNull);
      expect(empty.ties, isFalse);
    });

    test('providers find PayPal; fees default to zero', () {
      final all = [
        PayProviderStatus.fromJson(const {'provider': 'stripe', 'label': 'Stripe'}),
        PayProviderStatus.fromJson(const {
          'provider': 'paypal', 'label': 'PayPal', 'connected': true, 'account': 'shop@example.com',
        }),
      ];
      expect(PayProviderStatus.paypal(all)?.connected, isTrue);
      expect(PayProviderStatus.paypal(const []), isNull);
      expect(PayProviderStatus.fromJson(const {'provider': 'paypal'}).label, 'paypal');
      final f = PayPalFees.fromJson(const {});
      expect((f.feesPence, f.transactions, f.feesInBooksPence), (0, 0, 0));
    });

    test('disputes parse with and without the evidence and reversal', () {
      final list = PayPalDisputeList.fromJson({
        'connected': true,
        'problem': null,
        'disputes': [
          {
            'dispute_id': 'PP-D-1',
            'sample': true,
            'reason': 'MERCHANDISE_OR_SERVICE_NOT_RECEIVED',
            'reason_text': 'says the work was not done',
            'status': 'WAITING_FOR_SELLER_RESPONSE',
            'amount_pence': 48000,
            'respond_by': '2026-11-20',
            'invoice': 'INV-0007',
            'customer': 'Bramble Ltd',
            'can_send_evidence': true,
            'proposal': {'dispute_id': 'PP-D-1', 'notes': 'Invoice INV-0007 was sent…', 'status': 'proposed'},
          },
          {
            'dispute_id': 'PP-D-2',
            'lost': true,
            'reversal': {
              'payment_record': 'p1',
              'amount_pence': 9000,
              'can_post': true,
              'journal': [
                {'account': '1100 Debtors', 'debit_pence': 9000},
                {'account': '1240 PayPal clearing', 'credit_pence': 9000},
              ],
            },
          },
        ],
      });
      expect(list.disputes, hasLength(2));
      final a = list.disputes.first;
      expect(a.statusLabel, 'Waiting for your answer');
      expect(a.waitingForYou, isTrue);
      expect(a.proposal?.sent, isFalse);
      expect(a.amountPence, 48000);
      final b = list.disputes.last;
      expect(b.amountPence, isNull);
      expect(b.invoice, isNull);
      expect(b.status, 'OPEN');
      expect(b.reversal?.journal.last.creditPence, 9000);
      expect(PayPalDisputeList.fromJson(const {}).disputes, isEmpty);
      expect(DisputeEvidence.fromJson(const {}).status, 'proposed');
    });

    test('bill pay overview parses, and an empty one is safe', () {
      final o = BillPayOverview.fromJson({
        'today': '2026-11-11',
        'available': true,
        'connected': true,
        'clearing_pence': 50000,
        'due': [
          {
            'event_id': 'abcdef12',
            'contact_id': '0123456789abcdef',
            'supplier': 'Timber Co',
            'due_date': '2026-11-11',
            'days_overdue': 0,
            'owed_pence': 21050,
            'payee_email': 'pay@timber.example',
            'due_now': true,
            'can_pay': true,
            'payout': {'id': 'acc-1', 'status': 'failed', 'amount_pence': 21050},
          },
        ],
        'upcoming': [
          {'event_id': 'bcdef123', 'supplier': 'Glue Ltd', 'due_date': '2026-11-20', 'days_overdue': -9, 'owed_pence': 1000, 'plan': 'not_paypal'},
        ],
        'autopilot': {
          'enabled': true,
          'rules': [
            {'contact_id': '0123456789abcdef', 'enabled': true},
            {'contact_id': 'fedcba9876543210', 'enabled': false},
          ],
        },
        'notices': [
          {'id': 'n1', 'text': 'Paid Timber Co', 'kind': 'paid'},
          {'id': 'n2', 'text': 'Details changed', 'kind': 'flag'},
        ],
      });
      expect(o.due.single.payWithPayPal, isTrue);
      expect(o.due.single.payout?.statusLabel, 'Not paid');
      expect(o.upcoming.single.payWithPayPal, isFalse);
      expect(dueLine(o.due.single), 'due today');
      expect(dueLine(o.upcoming.single), 'due 20 Nov 2026');
      expect(o.autopilot.label, 'On');
      expect(o.autopilot.suppliers, 1);
      expect(o.notices.last.loud, isTrue);
      final empty = BillPayOverview.fromJson(const {});
      expect(empty.due, isEmpty);
      expect(empty.autopilot.enabled, isFalse);
      expect(empty.autopilot.label, 'Off');
      expect(BillPayBill.fromJson(const {}).payWithPayPal, isFalse);
      expect(BillPayRunResult.fromJson(const {'problems': ['x']}).problems, ['x']);
    });
  });

  group('client', () {
    test('approve sends confirm and only the fields given', () async {
      final fake = FakeReader({
        'POST /payments/paypal/sync/T1/approve': (_) => {...saleNeedingVat(), 'status': 'approved', 'vat_code': 'Z'},
      });
      final out = await fake.runtime().paypalSyncApprove('T1', vatCode: 'Z');
      expect(out.status, 'approved');
      expect(json.decode(fake.calls.single.body), {'vat_code': 'Z', 'confirm': true});
    });

    test('sync, reject, tie-out and fees use the web\'s routes', () async {
      final fake = FakeReader({
        'POST /payments/paypal/sync': (_) => {'new': 0, 'items': []},
        'POST /payments/paypal/sync/T2/reject': (_) => {...invoicePayment(), 'status': 'rejected'},
        'GET /payments/paypal/tieout': (_) => {'available': false},
        'GET /payments/paypal/fees': (_) => {'fees_pence': 378, 'transactions': 1},
      });
      final c = fake.runtime();
      await c.paypalSync();
      expect(json.decode(fake.calls.last.body), {'ai': true});
      await c.paypalSyncReject('T2');
      expect(json.decode(fake.calls.last.body), <String, dynamic>{});
      await c.paypalTieOut();
      final fees = await c.paypalFees('2026-11-01', '2026-11-11');
      expect(fees.feesPence, 378);
      expect(fake.calls.last.url.queryParameters, {'start': '2026-11-01', 'end': '2026-11-11'});
    });

    test('disputes: send and reversal carry confirm', () async {
      final fake = FakeReader({
        'POST /payments/online/paypal/disputes/PP-D-1/evidence/send': (_) => {'dispute_id': 'PP-D-1', 'status': 'sent'},
        'POST /payments/online/paypal/disputes/PP-D-1/reversal': (_) => {'amount_pence': 1, 'can_post': true},
      });
      final c = fake.runtime();
      expect((await c.sendDisputeEvidence('PP-D-1')).sent, isTrue);
      expect(json.decode(fake.calls.last.body), {'confirm': true});
      await c.postDisputeReversal('PP-D-1');
      expect(json.decode(fake.calls.last.body), {'confirm': true});
    });

    test('bill pay: pay, plan, stop and notices', () async {
      final fake = FakeReader({
        'POST /billpay/bills/abcdef12/pay': (_) => {'id': 'acc-1', 'status': 'sending', 'amount_pence': 21050},
        'PUT /billpay/bills/abcdef12/plan': (_) => {'plan': 'paypal'},
        'POST /billpay/autopilot/stop': (_) => {'enabled': false},
        'POST /billpay/notices/seen': (_) => null,
      });
      final c = fake.runtime();
      final p = await c.billPayPay('abcdef12', 21050);
      expect(p.statusLabel, 'Sending to PayPal');
      expect(json.decode(fake.calls.last.body),
          {'amount_pence': 21050, 'confirm': true, 'acknowledge_changed_details': false});
      await c.billPayPlan('abcdef12', 'paypal');
      expect(json.decode(fake.calls.last.body), {'plan': 'paypal'});
      await c.billPayStopAutopilot();
      await c.billPayNoticesSeen(['n1']);
      expect(json.decode(fake.calls.last.body), {'ids': ['n1']});
    });
  });

  group('Sync PayPal screen', () {
    FakeReader reader({Map<String, dynamic>? tie}) => FakeReader({
          'GET /payments/paypal/sync': (_) => {
                'available': true,
                'source': 'paypal',
                'last_synced_at': '2026-11-11T09:00:00Z',
                'items': [saleNeedingVat(), invoicePayment()],
              },
          'GET /payments/online/providers': (_) => [
                {'provider': 'paypal', 'label': 'PayPal', 'connected': true, 'account': 'shop@example.com'},
              ],
          'GET /payments/paypal/tieout': (_) => tie ?? {
                'available': true,
                'paypal_pence': 70000,
                'paypal_as_of': '2026-11-11T14:29:59Z',
                'books_pence': 10378,
                'difference_pence': 59622,
                'waiting_pence': 59622,
                'not_posted_pence': 0,
                'unexplained_pence': 0,
                'notes': [],
              },
          'GET /payments/paypal/fees': (_) => {'fees_pence': 0, 'transactions': 0},
          'POST /payments/paypal/sync/T1/approve': (r) =>
              {...saleNeedingVat(), 'status': 'approved', 'vat_code': json.decode(r.body)['vat_code']},
          'POST /payments/paypal/sync/T2/approve': (_) => {...invoicePayment(), 'status': 'approved'},
        });

    Future<void> pump(WidgetTester tester, FakeReader fake) async {
      usePhone(tester);
      await tester.pumpWidget(MaterialApp(
          home: PayPalSyncScreen(clientFactory: () async => fake.runtime())));
      await tester.pumpAndSettle();
    }

    testWidgets('Approve is off until the sale\'s VAT is chosen, then posts it', (tester) async {
      final fake = reader();
      await pump(tester, fake);
      expect(find.text('PayPal connected'), findsOneWidget);
      expect(find.text('VAT on this sale (choose before approving)'), findsOneWidget);
      final approve = find.byKey(const Key('approve-T1'));
      expect(tester.widget<FilledButton>(approve).onPressed, isNull);
      // The invoice payment needs no choice.
      expect(tester.widget<FilledButton>(find.byKey(const Key('approve-T2'))).onPressed, isNotNull);

      await tester.tap(find.byKey(const Key('vat-choice-T1')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Zero rated').last);
      await tester.pumpAndSettle();
      expect(tester.widget<FilledButton>(approve).onPressed, isNotNull);
      expect(find.text('Approve £120.00'), findsOneWidget);

      await tester.tap(approve);
      await tester.pumpAndSettle();
      final posted = fake.where('POST', '/payments/paypal/sync/T1/approve');
      expect(posted, hasLength(1));
      expect(json.decode(posted.single.body), {'vat_code': 'Z', 'confirm': true});
      expect(find.text('Sale of £120.00 (Ada Lovelace) is in your books.'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('an invoice payment approves with no body but confirm', (tester) async {
      final fake = reader();
      await pump(tester, fake);
      await tester.tap(find.byKey(const Key('approve-T2')));
      await tester.pumpAndSettle();
      expect(json.decode(fake.where('POST', '/payments/paypal/sync/T2/approve').single.body),
          {'confirm': true});
    });

    testWidgets('the tie-out shows PayPal, the books and PayPal\'s refresh time', (tester) async {
      await pump(tester, reader());
      expect(find.text('PayPal and your books'), findsOneWidget);
      expect(find.text('£700.00'), findsOneWidget);
      expect(find.text('£103.78'), findsOneWidget);
      expect(find.text('Waiting for your approval'), findsOneWidget);
      expect(find.byKey(const Key('tie-as-of')), findsOneWidget);
      expect(find.text('Unexplained'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('an unexplained gap is shown', (tester) async {
      await pump(tester, reader(tie: {
        'available': true,
        'paypal_pence': 70000,
        'books_pence': 0,
        'difference_pence': 70000,
        'waiting_pence': 60000,
        'not_posted_pence': 0,
        'unexplained_pence': 10000,
      }));
      expect(find.text('Unexplained'), findsOneWidget);
      expect(find.text('£100.00'), findsOneWidget);
    });

    testWidgets('not connected: says so and links to the web', (tester) async {
      final fake = FakeReader({
        'GET /payments/paypal/sync': (_) => {'available': false, 'reason': 'Connect PayPal first.', 'items': []},
        'GET /payments/online/providers': (_) => [
              {'provider': 'paypal', 'label': 'PayPal', 'available': true, 'connected': false},
            ],
        'GET /payments/paypal/tieout': (_) => {'available': false},
      });
      await pump(tester, fake);
      expect(find.text('PayPal is not connected'), findsOneWidget);
      expect(find.text('Connect PayPal first.'), findsOneWidget);
      expect(find.text('Do this on the web'), findsOneWidget);
      expect(find.byKey(const Key('paypal-sync-button')), findsNothing);
    });

    testWidgets('Sync PayPal posts the sync and reports what came in', (tester) async {
      final fake = reader();
      fake.routes['POST /payments/paypal/sync'] = (_) => {
            'new': 1,
            'pending': 0,
            'items': [saleNeedingVat()],
          };
      await pump(tester, fake);
      await tester.tap(find.byKey(const Key('paypal-sync-button')));
      await tester.pumpAndSettle();
      expect(find.text('1 new from PayPal · 1 waiting for you'), findsOneWidget);
      expect(fake.where('POST', '/payments/paypal/sync'), hasLength(1));
    });

    testWidgets('signed out: a plain prompt', (tester) async {
      await tester.pumpWidget(MaterialApp(home: PayPalSyncScreen(clientFactory: () async => null)));
      await tester.pumpAndSettle();
      expect(find.text('Sign in, or try the demo, to sync PayPal into your books.'), findsOneWidget);
    });
  });

  group('Disputes screen', () {
    FakeReader reader() => FakeReader({
          'GET /payments/online/paypal/disputes': (_) => {
                'connected': true,
                'disputes': [
                  {
                    'dispute_id': 'PP-D-1',
                    'sample': true,
                    'reason_text': 'says the work was not done',
                    'status': 'WAITING_FOR_SELLER_RESPONSE',
                    'amount_pence': 48000,
                    'respond_by': '2026-11-20',
                    'invoice': 'INV-0007',
                    'customer': 'Bramble Ltd',
                    'can_send_evidence': true,
                  },
                ],
              },
          'POST /payments/online/paypal/disputes/PP-D-1/evidence': (_) => {
                'dispute_id': 'PP-D-1',
                'invoice': 'INV-0007',
                'notes': 'Invoice INV-0007 was emailed on 1 Oct 2026 and paid on 3 Oct 2026.',
                'status': 'proposed',
              },
          'POST /payments/online/paypal/disputes/PP-D-1/evidence/send': (_) => {
                'dispute_id': 'PP-D-1',
                'notes': 'Invoice INV-0007 was emailed on 1 Oct 2026 and paid on 3 Oct 2026.',
                'status': 'sent',
                'sent_at': '2026-11-11T10:00:00Z',
                'sent_by': 'owner@example.com',
                'demo': true,
              },
        });

    testWidgets('build, preview, then send only after the owner says yes', (tester) async {
      usePhone(tester);
      final fake = reader();
      await tester.pumpWidget(MaterialApp(
          home: PayPalDisputesScreen(clientFactory: () async => fake.runtime())));
      await tester.pumpAndSettle();
      expect(find.textContaining('INV-0007 · Bramble Ltd · £480.00 disputed'), findsOneWidget);
      expect(find.text('SAMPLE (DEMO)'), findsOneWidget);

      await tester.tap(find.byKey(const Key('build-PP-D-1')));
      await tester.pumpAndSettle();
      expect(find.text('Response for PayPal (preview)'), findsOneWidget);
      expect(find.byKey(const Key('evidence-PP-D-1')), findsOneWidget);
      expect(find.text('Drafted by the AI; every figure and date checked against your books.'), findsOneWidget);

      // Cancel sends nothing.
      await tester.tap(find.byKey(const Key('send-PP-D-1')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(fake.where('POST', '/payments/online/paypal/disputes/PP-D-1/evidence/send'), isEmpty);

      await tester.tap(find.byKey(const Key('send-PP-D-1')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-yes')));
      await tester.pumpAndSettle();
      final sent = fake.where('POST', '/payments/online/paypal/disputes/PP-D-1/evidence/send');
      expect(sent, hasLength(1));
      expect(json.decode(sent.single.body), {'confirm': true});
      expect(find.text('Demo: recorded as sent. Nothing was sent to PayPal.'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('no disputes says so', (tester) async {
      final fake = FakeReader({
        'GET /payments/online/paypal/disputes': (_) => {'connected': true, 'disputes': []},
      });
      await tester.pumpWidget(MaterialApp(
          home: PayPalDisputesScreen(clientFactory: () async => fake.runtime())));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('disputes-empty')), findsOneWidget);
    });
  });

  group('Bill pay screen', () {
    Map<String, dynamic> bill({bool changed = false}) => {
          'event_id': 'abcdef12',
          'contact_id': '0123456789abcdef',
          'supplier': 'Timber Co',
          'reference': 'TC-88',
          'due_date': '2026-11-11',
          'days_overdue': 0,
          'owed_pence': 21050,
          'payee_email': 'pay@timber.example',
          'due_now': true,
          'can_pay': true,
          if (changed) 'changed_details': ['The bill shows a different bank account'],
        };

    FakeReader reader({bool changed = false, bool autopilot = false}) => FakeReader({
          'POST /billpay/run': (_) => {'problems': []},
          'GET /billpay': (_) => {
                'today': '2026-11-11',
                'available': true,
                'connected': true,
                'clearing_pence': 50000,
                'due': [bill(changed: changed)],
                'upcoming': [],
                'payees': [
                  {'contact_id': '0123456789abcdef', 'name': 'Timber Co', 'paypal_email': 'pay@timber.example'},
                ],
                'payouts': [],
                'flags': [],
                'notices': [],
                'autopilot': {'enabled': autopilot, 'rules': []},
                'autopilot_note': 'Pays when Accnomos is next open.',
              },
          'POST /billpay/bills/abcdef12/pay': (_) => {'id': 'acc-1', 'status': 'sending', 'amount_pence': 21050},
          'POST /billpay/autopilot/stop': (_) => {'enabled': false},
          'GET /billpay/upcoming': (_) => upcoming(),
        });

    Future<void> pump(WidgetTester tester, FakeReader fake) async {
      usePhone(tester, height: 4000);
      await tester.pumpWidget(MaterialApp(
          home: BillPayScreen(clientFactory: () async => fake.runtime())));
      await tester.pumpAndSettle();
    }

    testWidgets('approve and pay posts the owed amount with confirm', (tester) async {
      final fake = reader();
      await pump(tester, fake);
      expect(fake.where('POST', '/billpay/run'), hasLength(1));
      expect(find.text('Due today'), findsWidgets);
      expect(find.text('£210.50'), findsWidgets);
      await tester.tap(find.byKey(const Key('approve-pay-abcdef12')));
      await tester.pumpAndSettle();
      expect(fake.where('POST', '/billpay/bills/abcdef12/pay'), isEmpty);
      await tester.tap(find.byKey(const Key('pay-abcdef12')));
      await tester.pumpAndSettle();
      final paid = fake.where('POST', '/billpay/bills/abcdef12/pay');
      expect(paid, hasLength(1));
      expect(json.decode(paid.single.body),
          {'amount_pence': 21050, 'confirm': true, 'acknowledge_changed_details': false});
      expect(tester.takeException(), isNull);
    });

    testWidgets('changed details: Pay stays off until the owner ticks the check', (tester) async {
      final fake = reader(changed: true);
      await pump(tester, fake);
      await tester.tap(find.byKey(const Key('approve-pay-abcdef12')));
      await tester.pumpAndSettle();
      final pay = find.byKey(const Key('pay-abcdef12'));
      expect(tester.widget<FilledButton>(pay).onPressed, isNull);
      await tester.tap(find.byKey(const Key('ack-abcdef12')));
      await tester.pumpAndSettle();
      await tester.tap(pay);
      await tester.pumpAndSettle();
      expect(json.decode(fake.where('POST', '/billpay/bills/abcdef12/pay').single.body)
          ['acknowledge_changed_details'], isTrue);
    });

    testWidgets('the kill switch stops Autopilot after a yes; settings stay on the web', (tester) async {
      final fake = reader(autopilot: true);
      await pump(tester, fake);
      expect(find.byKey(const Key('billpay-autopilot-state')), findsOneWidget);
      await tester.ensureVisible(find.byKey(const Key('billpay-stop')));
      await tester.tap(find.byKey(const Key('billpay-stop')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-yes')));
      await tester.pumpAndSettle();
      expect(fake.where('POST', '/billpay/autopilot/stop'), hasLength(1));
      expect(find.text('Do this on the web'), findsWidgets);
    });
  });

  group('Upcoming PayPal payments', () {
    test('models parse, and missing fields are safe', () {
      final u = UpcomingPayments.fromJson(upcoming());
      expect(u.items, hasLength(2));
      expect(u.items.first.cancellable, isTrue);
      expect(u.items.first.statusLabel, 'Approved, waiting for its date');
      expect(u.items.last.cancellable, isFalse);
      expect(u.open, hasLength(2));
      expect(u.calendarStale, ['deadbeef']);
      final empty = UpcomingPayments.fromJson(const {});
      expect(empty.items, isEmpty);
      expect(empty.clearingLabel, '1240 PayPal clearing by your books');
      expect(UpcomingPayment.fromJson(const {}).status, 'planned');
      expect(const CalendarSyncResult().addedSummary, 'nothing to add');
      expect(CalendarSyncResult.fromJson(const {'added': 1, 'unchanged': 2}).addedSummary,
          '1 added, 2 already there');
      final bill = BillPayBill.fromJson(const {
        'event_id': 'x', 'due_now': false, 'payee_email': 'a@b.example',
        'approval': {'status': 'scheduled', 'amount_pence': 100, 'payee_email': 'a@b.example', 'due_date': '2026-11-20'},
      });
      expect(bill.approvedAhead, isTrue);
      expect(bill.canApproveAhead, isFalse);
      expect(BillPayBill.fromJson(const {'event_id': 'x', 'payee_email': 'a@b.example'}).canApproveAhead, isTrue);
    });

    test('client: schedule, cancel, calendar and .ics', () async {
      final fake = FakeReader({
        'POST /billpay/bills/cdef1234/schedule': (_) => {'status': 'scheduled'},
        'POST /billpay/bills/cdef1234/schedule/cancel': (_) => {'status': 'cancelled'},
        'POST /billpay/calendar': (_) => {'added': 1},
        'POST /billpay/calendar/remove': (_) => {'removed': 1},
        'GET /billpay/calendar.ics': (_) => 'BEGIN:VCALENDAR',
      });
      final c = fake.runtime();
      await c.billPaySchedule('cdef1234', 10000, 'pay@glue.example');
      expect(json.decode(fake.calls.last.body), {
        'amount_pence': 10000, 'payee_email': 'pay@glue.example', 'confirm': true,
        'acknowledge_changed_details': false,
      });
      await c.billPayCancelSchedule('cdef1234');
      expect(json.decode(fake.calls.last.body), {'confirm': true});
      expect((await c.billPayAddToCalendar(eventIds: ['cdef1234'])).added, 1);
      expect(json.decode(fake.calls.last.body), {'confirm': true, 'event_ids': ['cdef1234']});
      await c.billPayRemoveFromCalendar();
      expect(json.decode(fake.calls.last.body), {'confirm': true});
      expect(await c.billPayIcs(eventId: 'cdef1234'), contains('VCALENDAR'));
      expect(fake.calls.last.url.queryParameters, {'event_id': 'cdef1234'});
    });

    FakeReader reader() => FakeReader({
          'POST /billpay/run': (_) => {'problems': []},
          'GET /billpay': (_) => {
                'available': true,
                'connected': true,
                'due': [],
                'upcoming': [
                  {
                    'event_id': 'cdef5678',
                    'contact_id': '0123456789abcdef',
                    'supplier': 'Nails Ltd',
                    'due_date': '2026-11-25',
                    'days_overdue': -14,
                    'owed_pence': 4520,
                    'payee_email': 'pay@nails.example',
                    'due_now': false,
                    'can_pay': false,
                  },
                ],
                'autopilot': {'enabled': false},
              },
          'GET /billpay/upcoming': (_) => upcoming(),
          'POST /billpay/bills/cdef5678/schedule': (_) => {'status': 'scheduled'},
          'POST /billpay/bills/cdef1234/schedule/cancel': (_) => {'status': 'cancelled'},
          'POST /billpay/calendar': (_) => {'added': 1},
          'GET /billpay/calendar.ics': (_) => 'BEGIN:VCALENDAR',
        });

    testWidgets('approve ahead, cancel, add to calendar and share .ics', (tester) async {
      usePhone(tester, height: 3200);
      final fake = reader();
      String? shared;
      ShareText.testHook = (text, subject, mime) async {
        shared = '$mime:$text';
        return true;
      };
      addTearDown(() => ShareText.testHook = null);
      await tester.pumpWidget(MaterialApp(
          home: BillPayScreen(clientFactory: () async => fake.runtime())));
      await tester.pumpAndSettle();
      expect(find.text('Upcoming PayPal payments'), findsOneWidget);
      expect(find.byKey(const Key('upcoming-warning')), findsOneWidget);
      expect(find.text('£310.50'), findsOneWidget);

      await tester.tap(find.byKey(const Key('ahead-cdef5678')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('ahead-approve-cdef5678')));
      await tester.pumpAndSettle();
      expect(json.decode(fake.where('POST', '/billpay/bills/cdef5678/schedule').single.body), {
        'amount_pence': 4520, 'payee_email': 'pay@nails.example', 'confirm': true,
        'acknowledge_changed_details': false,
      });

      await tester.tap(find.byKey(const Key('cancel-cdef1234')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-yes')));
      await tester.pumpAndSettle();
      expect(fake.where('POST', '/billpay/bills/cdef1234/schedule/cancel'), hasLength(1));

      await tester.tap(find.byKey(const Key('cal-cdef1234')));
      await tester.pumpAndSettle();
      expect(json.decode(fake.where('POST', '/billpay/calendar').single.body),
          {'confirm': true, 'event_ids': ['cdef1234']});
      expect(find.text('Your calendar: 1 added.'), findsOneWidget);

      await tester.tap(find.byKey(const Key('ics-cdef1234')));
      await tester.pumpAndSettle();
      expect(shared, 'text/calendar:BEGIN:VCALENDAR');
      expect(tester.takeException(), isNull);
    });

    testWidgets('Home card: runs bill pay first, shows the next payments, hidden when none', (tester) async {
      usePhone(tester);
      final fake = FakeReader({
        'POST /billpay/run': (_) => {'problems': []},
        'GET /billpay/upcoming': (_) => upcoming(),
      });
      var opened = false;
      await tester.pumpWidget(MaterialApp(
          home: Scaffold(
              body: ListView(children: [
        UpcomingPaymentsHomeCard(client: fake.runtime(), onOpen: () => opened = true),
      ]))));
      await tester.pumpAndSettle();
      expect(fake.calls.first.url.path, '/billpay/run');
      expect(find.byKey(const Key('home-upcoming-paypal')), findsOneWidget);
      expect(find.text('Glue Ltd · 14 Nov 2026'), findsOneWidget);
      expect(find.text('£310.50'), findsOneWidget);
      await tester.tap(find.byKey(const Key('home-open-billpay')));
      expect(opened, isTrue);

      final none = FakeReader({'GET /billpay/upcoming': (_) => upcoming(empty: true)});
      await tester.pumpWidget(MaterialApp(
          home: Scaffold(body: UpcomingPaymentsHomeCard(client: none.runtime(), onOpen: () {}))));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('home-upcoming-paypal')), findsNothing);
    });
  });

  group('PayPal assistant cards', () {
    ProposedAction card(String kind, {bool tapOnly = false}) => ProposedAction({
          'id': 'a1',
          'kind': kind,
          'summary_md': '**Send 1 payment reminder** for **£480.00** in all through PayPal:',
          'preview': {
            'rows': [
              {'label': 'INV-0007', 'value': 'Bramble Ltd · £480.00 · 12 days overdue · PayPal reminder'},
              {'label': 'Total', 'value': '£480.00'},
            ],
          },
          'confirm_text': 'Send this reminder',
          'expires_at': DateTime.now().add(const Duration(minutes: 10)).toIso8601String(),
          if (tapOnly) 'tap_only': true,
        });

    test('remind_unpaid is tap-only: the read-back asks for a tap', () {
      final said = cardReadBack(card('remind_unpaid', tapOnly: true));
      expect(said, contains('needs you to tap'));
      expect(cardReadBack(card('payment_link_message')), contains('Say yes or no'));
    });

    testWidgets('both kinds render with their names', (tester) async {
      for (final (kind, label) in [
        ('remind_unpaid', 'Payment reminders · needs your OK'),
        ('payment_link_message', 'Payment message · needs your OK'),
      ]) {
        await tester.pumpWidget(MaterialApp(
          home: Scaffold(
            body: ProposedActionCard(
              action: card(kind),
              clientFor: () async => FakeReader(const {}).runtime(),
            ),
          ),
        ));
        expect(find.text(label), findsOneWidget);
        expect(find.text('Send this reminder?'), findsOneWidget);
      }
    });
  });
}
