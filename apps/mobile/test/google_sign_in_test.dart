import 'dart:convert';

import 'package:accnomos_mobile/screens/welcome_screen.dart';
import 'package:accnomos_mobile/services/auth.dart';
import 'package:accnomos_mobile/services/google_auth.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    AuthService.resetProviderForTest();
  });

  test('Google scopes are exactly the contract', () {
    expect(GoogleAuth.scopes, [
      'openid',
      'email',
      'profile',
      'https://www.googleapis.com/auth/drive.file',
      'https://www.googleapis.com/auth/gmail.readonly',
      'https://www.googleapis.com/auth/gmail.compose',
      'https://www.googleapis.com/auth/calendar.events',
      'https://www.googleapis.com/auth/contacts.readonly',
    ]);
  });

  test('not configured by default, so the button stays hidden', () {
    expect(GoogleAuth.configured, isFalse);
  });

  test('the saved provider decides the kind header', () {
    expect(AuthService().accountKindHeader, 'personal');
    AuthService.resetProviderForTest(AuthProvider.google);
    expect(AuthService().kind, AccountKind.google);
    expect(AuthService().accountKindHeader, 'google');
  });

  RuntimeClient client(String kind, http.Client inner) => RuntimeClient(
    AppSettings(
      runtimeUrl: 'http://runtime.test',
      aiMode: 'auto',
      aiBaseUrl: '',
      aiModel: '',
      vatStagger: 1,
      autopilotLevel: 'L1',
    ),
    books: BooksAuth(graphToken: 'tok-1', accountKind: kind),
    httpClient: inner,
  );

  test('Google calls send a bearer token and X-Account-Kind: google', () {
    final headers = client(
      'google',
      MockClient((_) async => http.Response('{}', 200)),
    ).debugHeaders;
    expect(headers['Authorization'], 'Bearer tok-1');
    expect(headers['X-Account-Kind'], 'google');
  });

  test('Microsoft calls are unchanged: no Authorization header', () {
    final headers = client(
      'work',
      MockClient((_) async => http.Response('{}', 200)),
    ).debugHeaders;
    expect(headers.containsKey('Authorization'), isFalse);
    expect(headers['X-Graph-Token'], 'tok-1');
    expect(headers['X-Account-Kind'], 'work');
  });

  test('a 401 refreshes the token once and retries the call', () async {
    final seen = <String>[];
    final inner = MockClient((req) async {
      seen.add(req.headers['Authorization'] ?? '');
      expect(req.body, jsonEncode({'a': 1}));
      return req.headers['Authorization'] == 'Bearer tok-2'
          ? http.Response('{}', 200)
          : http.Response('no', 401);
    });
    String? rejected;
    final retrying = GoogleRetryClient(
      inner,
      refresh: (r) async {
        rejected = r;
        return 'tok-2';
      },
    );
    final res = await retrying.post(
      Uri.parse('http://runtime.test/x'),
      headers: {'Authorization': 'Bearer tok-1', 'X-Graph-Token': 'tok-1'},
      body: jsonEncode({'a': 1}),
    );
    expect(res.statusCode, 200);
    expect(rejected, 'tok-1');
    expect(seen, ['Bearer tok-1', 'Bearer tok-2']);
  });

  test('a 401 with no new token is returned as it is', () async {
    final retrying = GoogleRetryClient(
      MockClient((_) async => http.Response('no', 401)),
      refresh: (_) async => null,
    );
    final res = await retrying.get(
      Uri.parse('http://runtime.test/x'),
      headers: {'Authorization': 'Bearer tok-1'},
    );
    expect(res.statusCode, 401);
  });

  group('Welcome', () {
    Future<void> pump(
      WidgetTester tester, {
      bool? show,
      Future<void> Function()? google,
    }) => tester.pumpWidget(
      MaterialApp(
        home: WelcomeScreen(showGoogle: show, signInWithGoogle: google),
      ),
    );

    testWidgets('no Google button unless configured', (tester) async {
      await pump(tester);
      expect(find.byKey(const Key('welcome-sign-in-google')), findsNothing);
      expect(find.byKey(const Key('welcome-sign-in')), findsOneWidget);
    });

    testWidgets('Continue with Google sits beside Microsoft and runs', (
      tester,
    ) async {
      var called = false;
      await pump(tester, show: true, google: () async => called = true);
      final button = find.byKey(const Key('welcome-sign-in-google'));
      expect(button, findsOneWidget);
      expect(find.text('Continue with Google'), findsOneWidget);
      await tester.ensureVisible(button);
      await tester.tap(button);
      await tester.pump();
      expect(called, isTrue);
    });
  });
}
