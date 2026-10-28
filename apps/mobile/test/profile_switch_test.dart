import 'package:accnomos_mobile/screens/settings_screen.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:msal_auth/msal_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Profiles on the phone: one Microsoft account (one set of books) at a
/// time. Settings shows which books these are (`GET /profile`) and offers
/// "Switch account", which signs out, forgets this phone's business details
/// and signs in again. MSAL is bypassed with [SettingsScreen.testAccountReady].
class FakeProfileClient extends RuntimeClient {
  FakeProfileClient(this.profile)
      : super(AppSettings(runtimeUrl: 'http://reader:8780'));

  final Map<String, dynamic>? profile;

  @override
  Future<List<Map<String, dynamic>>> rules() async => [];

  @override
  Future<Map<String, dynamic>> booksProfile() async {
    if (profile == null) throw RuntimeException('not found');
    return Map<String, dynamic>.from(profile!);
  }

  @override
  Future<Map<String, dynamic>> invoiceProfile() async => {
        'name': 'Acme Ltd',
        'address': '',
        'bank': <String, dynamic>{},
        'terms_days': 30,
      };
}

final testAccount =
    Account(id: '1', username: 'sam@sambuilds.example', name: 'Sam');

void main() {
  const channel = MethodChannel('msal_auth');

  setUp(() {
    SharedPreferences.setMockInitialValues({
      'accnomos.businessName': 'Sam Builds Ltd',
      'accnomos.vatNumber': 'GB123456789',
      'accnomos.vatStagger': 2,
    });
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

  Future<void> pump(WidgetTester tester, FakeProfileClient fake) async {
    tester.view.physicalSize = const Size(800, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(
      home: SettingsScreen(
        testAccount: testAccount,
        testAccountReady: true,
        clientFactory: (settings, books) => fake,
      ),
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('shows which books these are and offers Switch account',
      (tester) async {
    await pump(
        tester,
        FakeProfileClient({
          'name': 'Jo at home',
          'kind': 'personal',
          'exists': true,
          'features': ['review', 'ask'],
        }));
    expect(find.text('Profile: Jo at home · Personal'), findsOneWidget);
    expect(find.text('Switch account'), findsOneWidget);
    expect(find.text('Sign out'), findsOneWidget);
    final button = tester.widget<TextButton>(
        find.widgetWithText(TextButton, 'Switch account'));
    expect(button.onPressed, isNotNull);
  });

  testWidgets('no profile saved yet: just the account line', (tester) async {
    await pump(
        tester,
        FakeProfileClient({
          'name': 'My books',
          'kind': 'company',
          'exists': false,
          'features': <String>[],
        }));
    expect(find.textContaining('Profile:'), findsNothing);
    expect(find.text('Switch account'), findsOneWidget);
  });

  testWidgets('an older reader without /profile still shows Settings',
      (tester) async {
    await pump(tester, FakeProfileClient(null));
    expect(find.textContaining('Profile:'), findsNothing);
    expect(find.text('Switch account'), findsOneWidget);
  });

  test('clearBusiness forgets the business details, keeps the rest',
      () async {
    SharedPreferences.setMockInitialValues({
      'accnomos.businessName': 'Sam Builds Ltd',
      'accnomos.vatNumber': 'GB123456789',
      'accnomos.vatStagger': 2,
      'accnomos.vatStartMonth': 5,
      'accnomos.aiMode': 'key',
    });
    await AppSettings.clearBusiness();
    final s = await AppSettings.load();
    expect(s.businessName, isNull);
    expect(s.vatNumber, isNull);
    expect(s.vatStagger, isNull);
    expect(s.vatStartMonth, isNull);
    expect(s.aiMode, 'key');
  });
}
