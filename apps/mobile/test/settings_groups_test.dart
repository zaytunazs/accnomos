import 'package:accnomos_mobile/screens/settings_screen.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:msal_auth/msal_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Settings groups, mirroring the web's Connection / AI / Automation /
/// Business panels. The fakes answer without network; MSAL is bypassed
/// with [SettingsScreen.testAccountReady].
class FakeSettingsClient extends RuntimeClient {
  FakeSettingsClient({
    this.aiResult,
    this.aiError,
    List<Map<String, dynamic>>? rulesData,
    Map<String, dynamic>? profileData,
    this.mailData,
    this.mailError,
    this.mailboxesData = const [],
  })  : rulesData = rulesData ?? [],
        profileData =
            profileData ?? Map<String, dynamic>.from(defaultProfile),
        super(AppSettings(runtimeUrl: 'http://reader:8780'));

  static const defaultProfile = {
    'name': 'Acme Ltd',
    'address': '1 High Street',
    'email': null,
    'phone': null,
    'vrn': null,
    'vat_registered': true,
    'company_number': null,
    'bank': {
      'account_name': 'Acme',
      'sort_code': '12-34-56',
      'account_number': '12345678',
      'iban': null,
    },
    'logo_path': null,
    'terms_days': 30,
    'footer_note': null,
  };

  final Map<String, dynamic>? aiResult;
  final String? aiError;
  final List<Map<String, dynamic>> rulesData;
  Map<String, dynamic>? profileData;
  final Map<String, dynamic>? mailData;
  final String? mailError;
  final List<Map<String, dynamic>> mailboxesData;

  Map<String, dynamic>? savedProfileBody;
  final removedKeys = <String>[];

  @override
  Future<Map<String, dynamic>> aiTest() async {
    if (aiError != null) throw RuntimeException(aiError!);
    return aiResult ??
        {'ok': true, 'mode': 'local', 'detail': 'answered'};
  }

  @override
  Future<List<Map<String, dynamic>>> rules() async =>
      List<Map<String, dynamic>>.of(rulesData);

  @override
  Future<Map<String, dynamic>> removeRule(String supplierKey) async {
    removedKeys.add(supplierKey);
    rulesData.removeWhere((r) => r['supplier_key'] == supplierKey);
    return {};
  }

  @override
  Future<Map<String, dynamic>> invoiceProfile() async =>
      Map<String, dynamic>.from(profileData!);

  @override
  Future<Map<String, dynamic>> saveInvoiceProfile(
      Map<String, dynamic> profile) async {
    savedProfileBody = Map<String, dynamic>.from(profile);
    profileData = Map<String, dynamic>.from(profile);
    return Map<String, dynamic>.from(profile);
  }

  @override
  Future<List<Map<String, dynamic>>> mailboxes() async =>
      [for (final m in mailboxesData) Map<String, dynamic>.from(m)];

  @override
  Future<Map<String, dynamic>> mailScan(
      {int sinceDays = 14, bool dryRun = false}) async {
    if (mailError != null) throw RuntimeException(mailError!);
    return mailData ??
        {
          'saved': [],
          'scanned': 0,
          'skipped_duplicates': 0,
          'items': [],
          'errors': [],
          'dry_run': false,
        };
  }
}

final testAccount =
    Account(id: '1', username: 'user@example.com', name: 'Test User');

/// What `GET /mail/mailboxes` answers once a second account and a shared
/// mailbox are linked on the web (app/mailboxes.py).
const _mailboxes = [
  {
    'id': 'primary',
    'address': 'user@example.com',
    'kind': 'primary',
    'folder': 'all',
    'allow_senders': <String>[],
    'deny_senders': <String>[],
    'last_scan_at': null,
    'last_scan_saved': null,
  },
  {
    'id': 'a1b2c3d4e5f6',
    'address':
        'receipts.and.invoices.for.the.business@a-rather-long-domain.example',
    'kind': 'microsoft',
    'folder': 'archive',
    'allow_senders': ['screwfix.com'],
    'deny_senders': <String>[],
    'last_scan_at': '2026-10-27T09:30:00+00:00',
    'last_scan_saved': 2,
  },
  {
    'id': 'f6e5d4c3b2a1',
    'address': 'accounts@example.com',
    'kind': 'shared',
    'folder': 'inbox',
    'allow_senders': <String>[],
    'deny_senders': <String>[],
    'last_scan_at': '2026-10-26T16:05:00+00:00',
    'last_scan_saved': 1,
    'last_scan_error': 'no access (sign in again, or ask for access)',
  },
];

Map<String, dynamic> _rule() => {
      'supplier_key': 'acme',
      'supplier_name': 'Acme Ltd',
      'category': 'Materials',
      'account': null,
      'vat_code': 'S',
      'side': 'purchase',
      'typical_gross_pence': 1200,
      'vrn': null,
      'created_at': '2026-01-01',
      'created_from_proposal_id': 'p1',
      'hits': 3,
    };

void main() {
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

  /// Tall surface so every group builds: ListView only builds visible
  /// tiles, and the expanded groups are taller than 600 dp.
  void useTallSurface(WidgetTester tester) {
    tester.view.physicalSize = const Size(800, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
  }

  Future<void> pumpSignedIn(WidgetTester tester, FakeSettingsClient fake) async {
    useTallSurface(tester);
    await tester.pumpWidget(MaterialApp(
      home: SettingsScreen(
        testAccount: testAccount,
        testAccountReady: true,
        clientFactory: (settings, books) => fake,
      ),
    ));
    await tester.pumpAndSettle();
  }

  Future<void> scrollTo(WidgetTester tester, Finder finder) async {
    // Drag the page itself: the generic scrollable lookup is ambiguous
    // because every TextField carries an inner Scrollable.
    await tester.dragUntilVisible(finder,
        find.byType(SingleChildScrollView), const Offset(0, -300));
    await tester.pumpAndSettle();
  }

  testWidgets('signed out: sign-in card plus disabled reasons', (tester) async {
    useTallSurface(tester);
    await tester.pumpWidget(const MaterialApp(home: SettingsScreen()));
    await tester.pumpAndSettle();

    for (final group in ['Connection', 'AI', 'Automation', 'Business']) {
      expect(find.text(group), findsOneWidget);
    }
    expect(find.text('Microsoft account'), findsOneWidget);
    expect(find.text('Sign in with Microsoft'), findsOneWidget);
    expect(find.text('Disconnect Accnomos'), findsOneWidget);
    // The reason shows in the tile subtitle and again above the fields.
    expect(
        find.text('Sign in with Microsoft to change the AI settings.'),
        findsNWidgets(2));
    expect(
        find.text(
            'Sign in with Microsoft to use Autopilot and inbox checks.'),
        findsNWidgets(2));
    expect(
        find.text(
            'Sign in with Microsoft to edit business and invoice details.'),
        findsNWidgets(2));
    // Disabled fields still render their labels.
    expect(find.text('Business name'), findsOneWidget);
    // The AI test cannot run signed out.
    final testButton = tester.widget<OutlinedButton>(
        find.widgetWithText(OutlinedButton, 'Test connection'));
    expect(testButton.onPressed, isNull);
  });

  testWidgets('connection save shows a snackbar', (tester) async {
    useTallSurface(tester);
    await tester.pumpWidget(const MaterialApp(home: SettingsScreen()));
    await tester.pumpAndSettle();

    await scrollTo(tester, find.text('Save connection'));
    await tester.tap(find.text('Save connection'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.text('Connection saved'), findsOneWidget);
  });

  testWidgets('AI test shows the connected result line', (tester) async {
    await pumpSignedIn(
      tester,
      FakeSettingsClient(aiResult: {
        'ok': true,
        'mode': 'local',
        'model': 'muse-glimmer:30b',
        'detail': 'answered in 1.2 s',
      }),
    );

    await scrollTo(tester, find.text('Test connection'));
    await tester.tap(find.text('Test connection'));
    await tester.pumpAndSettle();
    expect(
        find.text(
            'Connected \u00b7 muse-glimmer:30b \u00b7 answered in 1.2 s'),
        findsOneWidget);
  });

  testWidgets('AI test failure shows the not-connected line', (tester) async {
    await pumpSignedIn(
      tester,
      FakeSettingsClient(
          aiError: 'Could not reach the reader at http://reader:8780.'),
    );

    await scrollTo(tester, find.text('Test connection'));
    await tester.tap(find.text('Test connection'));
    await tester.pumpAndSettle();
    expect(
        find.text(
            'Not connected \u00b7 Could not reach the reader at http://reader:8780.'),
        findsOneWidget);
  });

  testWidgets('bad VRN blocks the business save inline', (tester) async {
    await pumpSignedIn(tester, FakeSettingsClient());

    await scrollTo(tester, find.byKey(const Key('vrnField')));
    await tester.enterText(find.byKey(const Key('vrnField')), 'abc');
    await scrollTo(tester, find.text('Save business settings'));
    await tester.tap(find.text('Save business settings'));
    await tester.pumpAndSettle();
    expect(
        find.text(
            'That does not look like a UK VAT number \u2014 9 digits, e.g. 123456789.'),
        findsOneWidget);
    expect(find.text('Business settings saved'), findsNothing);
  });

  testWidgets('autopilot wording matches the web, rules remove',
      (tester) async {
    final fake = FakeSettingsClient(rulesData: [_rule()]);
    await pumpSignedIn(tester, fake);

    expect(find.text('L1 Assist'), findsOneWidget);
    expect(
        find.text(
            'Imports, extracts, files and proposes; never posts or sends (default)'),
        findsOneWidget);
    expect(find.text('L2 Autopilot'), findsOneWidget);
    expect(
        find.text(
            'Also posts receipts that match a rule you saved (same supplier, VAT and treatment, \u2264 2\u00d7 the usual) \u2014 each one listed with Undo'),
        findsOneWidget);
    expect(find.text('Acme Ltd'), findsWidgets);
    expect(find.text('Materials \u00b7 S \u00b7 usually \u00a312.00 \u00b7 used 3\u00d7'),
        findsOneWidget);

    await scrollTo(tester, find.text('Remove'));
    await tester.tap(find.text('Remove'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
    expect(fake.removedKeys, ['acme']);
    expect(
        find.text(
            "Rule removed. Autopilot won't post for that supplier again."),
        findsOneWidget);
    expect(find.text('Rule removed.'), findsOneWidget);
  });

  testWidgets('autopilot level is stored and sent as X-Autopilot',
      (tester) async {
    await pumpSignedIn(tester, FakeSettingsClient());

    // Default (L1): every scan/approve call carries X-Autopilot: off, like
    // the web, so a phone scan never posts without the user.
    expect(
        RuntimeClient(AppSettings()).debugHeaders['X-Autopilot'], 'off');

    await scrollTo(tester, find.text('L2 Autopilot'));
    await tester.tap(find.text('L2 Autopilot'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.text('Autopilot level saved'), findsOneWidget);

    // Stored with the other settings; at L2 the header goes away and the
    // runtime may post matching rules.
    final saved = await AppSettings.load();
    expect(saved.autopilotLevel, 'L2');
    expect(RuntimeClient(saved).debugHeaders.containsKey('X-Autopilot'),
        isFalse);
  });

  testWidgets('business save writes the profile shape the web sends',
      (tester) async {
    final fake = FakeSettingsClient();
    await pumpSignedIn(tester, fake);

    await scrollTo(tester, find.byKey(const Key('profileAddressField')));
    await tester.enterText(
        find.byKey(const Key('profileAddressField')), '2 Bond Street');
    await scrollTo(tester, find.text('Save business settings'));
    await tester.tap(find.text('Save business settings'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.text('Business settings saved'), findsOneWidget);

    final body = fake.savedProfileBody!;
    // Same keys as loaded: nothing extra goes to the runtime.
    expect(Set.of(body.keys), Set.of(FakeSettingsClient.defaultProfile.keys));
    expect(body['address'], '2 Bond Street');
    expect(body['terms_days'], 30);
    expect((body['bank'] as Map)['account_name'], 'Acme');
  });

  testWidgets('inbox check reports what was imported', (tester) async {
    await pumpSignedIn(
      tester,
      FakeSettingsClient(mailData: {
        'saved': [
          {'name': 'receipt.pdf'}
        ],
        'scanned': 4,
        'skipped_duplicates': 1,
        'items': [
          {'name': 'receipt.pdf', 'subject': 'Your receipt'}
        ],
        'errors': [],
        'dry_run': false,
      }),
    );

    await scrollTo(tester, find.text('Check my inbox now'));
    await tester.tap(find.text('Check my inbox now'));
    await tester.pumpAndSettle();
    expect(find.textContaining('1 file imported'), findsOneWidget);
    expect(find.textContaining('4 emails with attachments'),
        findsOneWidget);
  });

  testWidgets('linked mailboxes are listed read-only, as on the web',
      (tester) async {
    await pumpSignedIn(tester, FakeSettingsClient(mailboxesData: _mailboxes));

    final list = find.byKey(const Key('linked-mailboxes'));
    await scrollTo(tester, list);
    expect(find.descendant(of: list, matching: find.text('Email intake')),
        findsOneWidget);
    expect(find.text('user@example.com'), findsOneWidget);
    expect(find.text('Signed-in account \u00b7 Not checked yet'),
        findsOneWidget);
    expect(
        find.textContaining('Microsoft account \u00b7 Last checked 27 Oct'),
        findsOneWidget);
    expect(find.textContaining('\u00b7 2 files'), findsOneWidget);
    expect(find.textContaining('Shared mailbox \u00b7 Last checked 26 Oct'),
        findsOneWidget);
    expect(find.textContaining('\u00b7 1 file'), findsOneWidget);
    expect(find.text('no access (sign in again, or ask for access)'),
        findsOneWidget);
    expect(find.bySemanticsLabel(RegExp(r'^accounts@example\.com')),
        findsOneWidget);
    expect(
        find.textContaining(
            'Add, change or remove mailboxes in Settings on the web'),
        findsOneWidget);
    // Read-only: nothing to add, edit or remove here.
    for (final label in [
      'Add Microsoft mailbox',
      'Add shared mailbox',
      'Remove',
      'Save',
    ]) {
      expect(find.descendant(of: list, matching: find.text(label)),
          findsNothing);
    }
    expect(find.descendant(of: list, matching: find.byType(TextField)),
        findsNothing);
  });

  testWidgets('no mailboxes list when the runtime has none to show',
      (tester) async {
    await pumpSignedIn(tester, FakeSettingsClient());
    await scrollTo(tester, find.text('Check my inbox now'));
    expect(find.byKey(const Key('linked-mailboxes')), findsNothing);
  });

  testWidgets('nothing overflows at 360 dp', (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await pumpSignedIn(tester,
        FakeSettingsClient(rulesData: [_rule()], mailboxesData: _mailboxes));
    final page = find.byType(SingleChildScrollView);
    for (var i = 0; i < 8; i++) {
      await tester.drag(page, const Offset(0, -400));
      await tester.pumpAndSettle();
    }
    expect(tester.takeException(), isNull);
  });
}
