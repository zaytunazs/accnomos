import 'dart:convert';

import 'package:accnomos_mobile/models/vat_return.dart';
import 'package:accnomos_mobile/services/demo.dart';
import 'package:accnomos_mobile/services/device_facts.dart';
import 'package:accnomos_mobile/services/hmrc.dart';
import 'package:accnomos_mobile/services/sha256.dart';
import 'package:accnomos_mobile/widgets/hmrc_filing.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// VAT filing on the phone: PKCE, the MOBILE_APP_VIA_SERVER facts, HMRC's
/// obligations, the declaration gate, the demo's simulated submission and the
/// receipt, and money shown as the web shows it.
void main() {
  test('a return that has just gone in is received today, not on its due date', () {
    final o = Obligation(periodKey: '26A3', start: '2026-07-01', end: '2026-09-30', due: '2026-11-07', status: 'O');
    final f = o.fulfilled(now: DateTime(2026, 11, 4));
    expect(f.status, 'F');
    expect(f.received, '2026-11-04');
    final told = Obligation(
        periodKey: '26A2', start: '2026-04-01', end: '2026-06-30', due: '2026-08-07', status: 'O', received: '2026-08-01');
    expect(told.fulfilled(now: DateTime(2026, 11, 4)).received, '2026-08-01');
  });

  test('processing date reads as a day and a time', () {
    expect(ukDateTime('2026-11-04T03:36:36.039258Z'), startsWith('4 Nov 2026, '));
    expect(ukDateTime('not a date'), 'not a date');
  });

  const device = MethodChannel('accnomos/device');
  const hmrcChannel = MethodChannel('accnomos/hmrc');
  const demo = DemoInfo(
    session: 'sess-1',
    kind: 'company',
    runtimeUrl: 'https://api.example',
    business: 'Bramblewood Joinery Ltd',
  );
  String? pendingCallback;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    Hmrc.disconnect();
    Demo.debugSet(null);
    pendingCallback = null;
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(device, (call) async => {
          'os_family': 'Android',
          'os_version': '15',
          'device_manufacturer': 'Google',
          'device_model': 'Pixel 9',
          'colour_depth': 24,
          'app_version': '0.3.10',
        });
    messenger.setMockMethodCallHandler(hmrcChannel, (call) async {
      final v = pendingCallback;
      pendingCallback = null;
      return v;
    });
  });

  tearDown(() {
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(device, null);
    messenger.setMockMethodCallHandler(hmrcChannel, null);
    Demo.debugSet(null);
    Hmrc.disconnect();
  });

  group('helpers', () {
    test('SHA-256 and the RFC 7636 PKCE example', () {
      expect(sha256Hex('abc'), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
      expect(sha256Hex(''), 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
      expect(sha256Hex('a' * 1000).length, 64);
      expect(base64UrlNoPad(sha256(ascii.encode('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'))),
          'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM');
    });

    test('money is shown with thousands separators; boxes 6-9 in whole pounds', () {
      expect(formatPounds('3807.33'), '£3,807.33');
      expect(formatPounds('19288', whole: true), '£19,288');
      expect(formatPounds('1234567.5'), '£1,234,567.50');
      expect(formatPounds('-12.3'), '-£12.30');
      expect(formatPounds('0'), '£0.00');
      expect(VatBox(box: 6, label: '', amount: '19288.90', entries: 1).display, '£19,288');
      expect(VatBox(box: 5, label: '', amount: '3807.33', entries: 1).display, '£3,807.33');
    });

    test('timezone and timestamp formats', () {
      expect(utcOffset(const Duration(hours: 1)), 'UTC+01:00');
      expect(utcOffset(const Duration(hours: -5, minutes: -30)), 'UTC-05:30');
      expect(hmrcTimestamp(DateTime.utc(2026, 11, 3, 9, 5, 7, 42)), '2026-11-03T09:05:07.042Z');
      expect(RegExp(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$').hasMatch(uuid4()), isTrue);
    });

    test('obligations parse; demo quarters match the web', () {
      final list = Obligation.listFrom({
        'obligations': [
          {'periodKey': '26A3', 'start': '2026-07-01', 'end': '2026-09-30', 'due': '2026-11-07', 'status': 'O'},
          {'periodKey': '26A2', 'start': '2026-04-01', 'end': '2026-06-30', 'due': '2026-08-07', 'status': 'F', 'received': '2026-08-01'},
        ]
      });
      expect(list.map((o) => o.periodKey), ['26A3', '26A2']);
      expect(list.first.open, isTrue);
      expect(list.last.received, '2026-08-01');
      expect(Obligation.listFrom(null), isEmpty);

      final demoList = demoObligations(DateTime(2026, 11, 3));
      expect(demoList.map((o) => o.periodKey), ['25A4', '26A1', '26A2', '26A3', '26A4']);
      expect(demoList.where((o) => o.open).map((o) => o.periodKey), ['26A3', '26A4']);
      expect(demoList[3].start, '2026-07-01');
      expect(demoList[3].end, '2026-09-30');
      expect(demoList[3].due, '2026-11-07');
    });

    test('the return body: pence for boxes 1-5, whole pounds 6-9, box 5 positive', () {
      final body = toReturnBody({
        'vatDueSales': 3857.333,
        'vatDueAcquisitions': 0,
        'totalVatDue': 3857.33,
        'vatReclaimedCurrPeriod': 50,
        'netVatDue': -3807.33,
        'totalValueSalesExVAT': 19288.99,
        'totalValuePurchasesExVAT': '1698.4',
        'totalValueGoodsSuppliedExVAT': 0,
        'totalAcquisitionsExVAT': 0,
      }, '26A3');
      expect(body['periodKey'], '26A3');
      expect(body['vatDueSales'], 3857.33);
      expect(body['netVatDue'], 3807.33);
      expect(body['totalValueSalesExVAT'], 19288);
      expect(body['totalValuePurchasesExVAT'], 1698);
      expect(body['finalised'], isTrue);
    });
  });

  group('relay (signed in, not a demo)', () {
    testWidgets('PKCE connect, then obligations carry the MOBILE_APP_VIA_SERVER facts', (tester) async {
      final calls = <http.Request>[];
      Uri? opened;
      final client = MockClient((req) async {
        calls.add(req);
        if (req.url.path == '/hmrc/authorize') {
          return http.Response(json.encode({'url': 'https://test-www.tax.service.gov.uk/oauth/authorize?x=1', 'state': 'st-1'}), 200);
        }
        if (req.url.path == '/hmrc/exchange') {
          return http.Response(json.encode({'access_token': 'acc', 'refresh_token': 'ref', 'expires_in': 14400}), 200);
        }
        if (req.url.path == '/vat/123456789/obligations') {
          return http.Response(
              json.encode({
                'hmrc': {
                  'obligations': [
                    {'periodKey': '26A3', 'start': '2026-07-01', 'end': '2026-09-30', 'due': '2026-11-07', 'status': 'O'}
                  ]
                },
                'sent_headers': {'Gov-Client-Connection-Method': 'MOBILE_APP_VIA_SERVER'},
                'fraud_headers_missing': <String>[],
              }),
              200);
        }
        return http.Response('{"detail":"unexpected"}', 404);
      });
      final hmrc = Hmrc(
        relayUrl: 'https://api.example',
        client: client,
        facts: DeviceFacts(),
        openUrl: (u) async {
          opened = u;
          return true;
        },
      );

      await tester.runAsync(() async {
        await hmrc.startConnect();
      });
      expect(opened?.host, 'test-www.tax.service.gov.uk');
      final authorize = calls.single.url;
      expect(authorize.queryParameters['redirect_to'], 'https://accnomos.com/auth/hmrc-app.html');
      expect(authorize.queryParameters['code_challenge']!.length, 43);
      expect(hmrc.connected, isFalse);

      pendingCallback = 'com.accnomos.app://hmrc/callback?code=c-1&state=st-1';
      await tester.runAsync(() async {
        final cb = await hmrc.takeCallback();
        expect(cb, {'code': 'c-1', 'state': 'st-1'});
        expect(await hmrc.takeCallback(), isNull); // single use
        await hmrc.finishConnect(cb!);
      });
      expect(hmrc.connected, isTrue);
      final exchange = json.decode(calls[1].body) as Map<String, dynamic>;
      expect(exchange['code'], 'c-1');
      expect((exchange['code_verifier'] as String).length, 64);
      expect(base64UrlNoPad(sha256(ascii.encode(exchange['code_verifier'] as String))),
          authorize.queryParameters['code_challenge']);

      late RelayResult res;
      await tester.runAsync(() async {
        res = await hmrc.obligations('123456789',
            accountId: 'acct-1', from: DateTime(2025, 11, 3), to: DateTime(2026, 11, 3), scenario: ' QUARTERLY_ONE_MET ');
      });
      expect(Obligation.listFrom(res.hmrc).single.periodKey, '26A3');
      final req = calls.last;
      expect(req.headers['X-HMRC-Access-Token'], 'acc');
      final body = json.decode(req.body) as Map<String, dynamic>;
      expect(body['method'], 'MOBILE_APP_VIA_SERVER');
      expect(body['from'], '2025-11-03');
      expect(body['gov_test_scenario'], 'QUARTERLY_ONE_MET');
      final facts = body['client_facts'] as Map<String, dynamic>;
      expect(facts['multi_factor'], isEmpty);
      expect(facts['device_id'], isA<String>());
      expect(facts['timezone'], matches(RegExp(r'^UTC[+-]\d{2}:\d{2}$')));
      expect(facts['user_ids'], {'accnomos': sha256Hex('acct-1')});
      expect(facts['user_agent'],
          {'os_family': 'Android', 'os_version': '15', 'device_manufacturer': 'Google', 'device_model': 'Pixel 9'});
      expect((facts['screens'] as List).single['colour_depth'], 24);
      expect(facts['window_size'], isA<Map>());
      expect(facts['vendor_versions'], {'accnomos-android': '0.3.10'});
      expect(facts.containsKey('browser_js_user_agent'), isFalse);
      if (facts.containsKey('local_ips')) {
        expect(facts['local_ips_timestamp'], matches(RegExp(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$')));
      }
      // The same device id every call.
      expect((await tester.runAsync(() => hmrc.clientFacts('acct-1')))!['device_id'], facts['device_id']);
    });

    testWidgets('a state that does not match is refused; an HMRC error is shown', (tester) async {
      final hmrc = Hmrc(
          relayUrl: 'https://api.example',
          client: MockClient((req) async => http.Response(json.encode({'url': 'https://x.example', 'state': 'st-1'}), 200)),
          openUrl: (_) async => true);
      await tester.runAsync(() async {
        await hmrc.startConnect();
        await expectLater(hmrc.finishConnect({'code': 'c', 'state': 'other'}), throwsA(isA<HmrcAuthException>()));
        await expectLater(
            hmrc.finishConnect({'error': 'access_denied', 'error_description': 'User refused', 'state': 'st-1'}),
            throwsA(predicate((e) => e.toString().contains('User refused'))));
      });
      expect(hmrc.connected, isFalse);
    });
  });

  group('filing card in the demo', () {
    VatReturn demoVat() {
      final open = demoObligations(DateTime.now()).firstWhere((o) => o.open);
      return VatReturn(
        periodKey: '2026-Q3',
        period: '2026-Q3',
        start: open.start,
        end: open.end,
        label: 'Jul–Sep 2026',
        canSubmit: true,
        eventsInPeriod: 30,
        warnings: const [],
        boxes: [VatBox(box: 5, label: 'Net VAT', amount: '3807.33', entries: 30)],
        hmrcBody: const {
          'vatDueSales': 3857.33,
          'vatDueAcquisitions': 0,
          'totalVatDue': 3857.33,
          'vatReclaimedCurrPeriod': 50,
          'netVatDue': 3807.33,
          'totalValueSalesExVAT': 19288,
          'totalValuePurchasesExVAT': 1698,
          'totalValueGoodsSuppliedExVAT': 0,
          'totalAcquisitionsExVAT': 0,
        },
      );
    }

    testWidgets('connect, periods, declaration gate, simulated submit and receipt', (tester) async {
      Demo.debugSet(demo);
      final saved = <String, String>{};
      var posted = 0;
      final hmrc = Hmrc(
        relayUrl: 'https://api.example',
        client: MockClient((req) async => fail('a demo must never call the relay: ${req.url}')),
        openUrl: (_) async => fail('a demo opens no HMRC page'),
      );
      final deps = VatFilingDeps(
        hmrc: hmrc,
        accountId: 'demo',
        businessVat: null,
        postObligations: (_) async => posted++,
        saveFile: (path, text) async => saved[path] = text,
        listReceipts: () async => [for (final p in saved.keys.where((k) => k.endsWith('receipt.json'))) (p.split('/')[1], true)],
      );
      tester.view.physicalSize = const Size(1080, 4000);
      tester.view.devicePixelRatio = 2.5;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: HmrcFilingCard(vat: demoVat(), deps: deps, onPickPeriod: (_) {}),
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Demo — HMRC simulated'), findsOneWidget);

      await tester.tap(find.byKey(const Key('hmrc-connect')));
      await tester.pumpAndSettle();
      expect(find.text(demoVrn), findsOneWidget);

      await tester.tap(find.byKey(const Key('hmrc-obligations')));
      await tester.pumpAndSettle();
      expect(find.text("HMRC's VAT periods"), findsOneWidget);
      expect(find.text('Open'), findsNWidgets(2));
      expect(find.text('Fulfilled'), findsNWidgets(3));
      expect(posted, 0); // a demo's list is made up: never handed to the books as HMRC's

      FilledButton submit() => tester.widget<FilledButton>(find.byKey(const Key('hmrc-submit')));
      expect(submit().onPressed, isNull, reason: 'Submit stays off until the declaration is ticked');
      expect(find.text(vatDeclaration), findsOneWidget);
      expect(find.textContaining('box 5: £3,807.33'), findsOneWidget);

      await tester.tap(find.byKey(const Key('hmrc-declare')));
      await tester.pumpAndSettle();
      expect(submit().onPressed, isNotNull);

      await tester.tap(find.byKey(const Key('hmrc-submit')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('hmrc-receipt')), findsOneWidget);
      expect(find.text(demoSubmission), findsOneWidget);
      expect(find.textContaining('DEMO-000000000000'), findsOneWidget);
      expect(saved.keys.length, 2);
      final key = demoObligations(DateTime.now()).firstWhere((o) => o.open).periodKey;
      final receipt = json.decode(saved['06 VAT returns/$key/receipt.json']!) as Map<String, dynamic>;
      expect(receipt['environment'], contains('HMRC was not contacted'));
      final ret = json.decode(saved['06 VAT returns/$key/return.json']!) as Map<String, dynamic>;
      expect(ret['declaration'], vatDeclaration);
      expect((ret['return'] as Map)['netVatDue'], 3807.33);
      expect(find.textContaining('receipt saved'), findsOneWidget);
    });

    testWidgets('a period whose dates differ from the return cannot be submitted', (tester) async {
      Demo.debugSet(demo);
      final vat = demoVat();
      final other = VatReturn(
        periodKey: 'x',
        start: '2020-01-01',
        end: '2020-03-31',
        boxes: vat.boxes,
        warnings: const [],
        eventsInPeriod: 0,
        canSubmit: true,
        hmrcBody: vat.hmrcBody,
      );
      final deps = VatFilingDeps(
        hmrc: Hmrc(relayUrl: 'https://api.example'),
        accountId: 'demo',
        businessVat: null,
        postObligations: (_) async {},
        saveFile: (_, _) async {},
        listReceipts: () async => const [],
      );
      tester.view.physicalSize = const Size(1080, 4000);
      tester.view.devicePixelRatio = 2.5;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: SingleChildScrollView(child: HmrcFilingCard(vat: other, deps: deps, onPickPeriod: (_) {}))),
      ));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('hmrc-connect')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('hmrc-obligations')));
      await tester.pumpAndSettle();
      expect(find.textContaining('Pick the matching period at the top'), findsOneWidget);
      expect(find.byKey(const Key('hmrc-declare')), findsNothing);
      expect(tester.widget<FilledButton>(find.byKey(const Key('hmrc-submit'))).onPressed, isNull);
    });
  });
}
