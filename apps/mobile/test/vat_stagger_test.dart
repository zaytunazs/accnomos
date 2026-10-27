import 'dart:convert';

import 'package:accnomos_mobile/models/dashboard.dart';
import 'package:accnomos_mobile/screens/home_screen.dart';
import 'package:accnomos_mobile/screens/settings_screen.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The phone sends the saved VAT stagger on every call the web sends it on
/// (VAT return, VAT periods, deadlines, dashboard, reports, Ask and scan),
/// like the web's `vatQuery()`. Nothing is sent when nothing is saved.
void main() {
  final books =
      BooksAuth(graphToken: 'test-token', accountKind: 'personal');

  /// Every request the client makes, in order.
  late List<Uri> requested;

  RuntimeClient clientFor(AppSettings settings) => RuntimeClient(
        settings,
        books: books,
        httpClient: MockClient((request) async {
          requested.add(request.url);
          return http.Response(json.encode({}), 200);
        }),
      );

  AppSettings settingsWith({int? stagger, int? startMonth}) =>
      AppSettings(
          runtimeUrl: 'http://reader:8780',
          vatStagger: stagger,
          vatStartMonth: startMonth);

  /// Every VAT-cycle call the web sends its query on.
  Future<void> exercise(RuntimeClient client) async {
    await client.vat(period: '2026-Q3');
    await client.vatPeriods();
    await client.deadlines();
    await client.dashboard(today: '2026-10-27');
    await client.reportsPl();
    await client.reportsVat();
    await client.reportExport(report: 'all');
    await client.ask('What do I owe?');
    await client.askVoice([0, 1, 2, 3]);
    await client.scan();
  }

  setUp(() {
    requested = [];
  });

  test('vatQuery mirrors the web: stagger, custom start month, or empty',
      () {
    expect(clientFor(settingsWith(stagger: 2)).vatQuery(),
        {'stagger': '2'});
    expect(
        clientFor(settingsWith(stagger: 2, startMonth: 5)).vatQuery(),
        {'start_month': '5'});
    expect(clientFor(settingsWith()).vatQuery(), isEmpty);
  });

  for (final stagger in [1, 2, 3]) {
    test('stagger $stagger rides on every VAT-cycle call', () async {
      await exercise(clientFor(settingsWith(stagger: stagger)));
      expect(requested, isNotEmpty);
      for (final uri in requested) {
        expect(uri.queryParameters['stagger'], '$stagger',
            reason: '${uri.path} should carry stagger=$stagger');
        expect(uri.queryParameters, isNot(contains('start_month')),
            reason: '${uri.path} should not carry start_month');
      }
    });
  }

  test('a custom start month wins over the stagger group', () async {
    await exercise(clientFor(settingsWith(stagger: 2, startMonth: 5)));
    expect(requested, isNotEmpty);
    for (final uri in requested) {
      expect(uri.queryParameters['start_month'], '5',
          reason: '${uri.path} should carry start_month=5');
      expect(uri.queryParameters, isNot(contains('stagger')),
          reason: '${uri.path} should not carry stagger');
    }
  });

  test('nothing is sent when no VAT period is saved', () async {
    await exercise(clientFor(settingsWith()));
    expect(requested, isNotEmpty);
    for (final uri in requested) {
      expect(uri.queryParameters, isNot(contains('stagger')),
          reason: '${uri.path} should not carry stagger');
      expect(uri.queryParameters, isNot(contains('start_month')),
          reason: '${uri.path} should not carry start_month');
    }
  });

  group('assumed-quarters note', () {
    const channel = MethodChannel('msal_auth');

    setUp(() {
      SharedPreferences.setMockInitialValues({});
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async {
        throw PlatformException(
            code: 'NO_CURRENT_ACCOUNT', message: 'no account');
      });
    });

    tearDown(() {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, null);
    });

    test('Dashboard parses vat.assumed', () {
      expect(
          Dashboard.fromJson({
            'vat': {
              'current': {'label': 'Jul-Sep 2026'},
              'assumed': true,
            }
          }).vatAssumed,
          isTrue);
      expect(Dashboard.fromJson({}).vatAssumed, isFalse);
    });

    testWidgets('shows the web note and opens Settings on tap',
        (tester) async {
      await tester.pumpWidget(
          const MaterialApp(home: Scaffold(body: AssumedStaggerNote())));
      expect(find.text('Assuming Mar/Jun/Sep/Dec quarters —'),
          findsOneWidget);
      await tester.tap(find.text('set yours in Settings'));
      await tester.pumpAndSettle();
      expect(find.byType(SettingsScreen), findsOneWidget);
    });
  });

  test('calls keep their own parameters beside the stagger', () async {
    final client = clientFor(settingsWith(stagger: 2));
    await client.vat(period: '2026-Q3');
    await client.dashboard(today: '2026-10-27');
    final vat = requested
        .firstWhere((uri) => uri.path.endsWith('/books/vat'))
        .queryParameters;
    expect(vat['period'], '2026-Q3');
    expect(vat['stagger'], '2');
    final dashboard = requested
        .firstWhere((uri) => uri.path.endsWith('/books/dashboard'))
        .queryParameters;
    expect(dashboard['today'], '2026-10-27');
    expect(dashboard['stagger'], '2');
  });
}
