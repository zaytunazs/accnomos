import 'package:accnomos_mobile/screens/audit_screen.dart';
import 'package:accnomos_mobile/screens/bank_rule_sheet.dart';
import 'package:accnomos_mobile/screens/settings_screen.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:accnomos_mobile/widgets/web_only.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:msal_auth/msal_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Widget cover for the parity-audit UI: the bank-rule sheet, the
/// Settings Your-data export, the audit filters and the shared
/// "Do this on the web" card. Every case runs at 360 dp wide with no
/// overflow; fakes answer without network or MSAL.
void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  void usePhoneSurface(WidgetTester tester) {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
  }

  /// Bring [target] on screen inside its nearest scrollable (the rule
  /// sheet and the filter chips both overflow 740x360 without scrolling).
  Future<void> reveal(WidgetTester tester, Finder target) async {
    final scrollable = find.ancestor(
      of: target,
      matching: find.byType(Scrollable),
    );
    await tester.scrollUntilVisible(target, 200, scrollable: scrollable.first);
    await tester.pumpAndSettle();
  }

  group('BankRuleSheet', () {
    Future<void> pumpSheet(
      WidgetTester tester, {
      Map<String, dynamic>? initial,
      required Future<String?> Function(Map<String, dynamic>) onSave,
    }) async {
      usePhoneSurface(tester);
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: BankRuleSheet(initial: initial, onSave: onSave),
        ),
      ));
      await tester.pumpAndSettle();
    }

    testWidgets('renders at 360 dp with no overflow', (tester) async {
      await pumpSheet(tester, onSave: (_) async => null);
      expect(find.text('New bank rule'), findsOneWidget);
      expect(find.text('Save rule'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('empty save explains what is missing', (tester) async {
      var saved = false;
      await pumpSheet(tester, onSave: (_) async {
        saved = true;
        return null;
      });
      await reveal(tester, find.text('Save rule'));
      await tester.tap(find.text('Save rule'));
      await tester.pumpAndSettle();
      expect(find.text('Type the text to match on.'), findsOneWidget);
      expect(saved, isFalse);
    });

    testWidgets('save posts the web-shaped rule body', (tester) async {
      Map<String, dynamic>? posted;
      await pumpSheet(tester, onSave: (body) async {
        posted = body;
        return null;
      });
      final fields = find.byType(TextField);
      // Name, match text, min, max, account, contact, job id.
      await tester.enterText(fields.at(0), 'Tesco');
      await tester.enterText(fields.at(1), 'TESCO');
      await tester.enterText(fields.at(4), '6000 Groceries');
      await reveal(tester, find.text('Save rule'));
      await tester.tap(find.text('Save rule'));
      await tester.pumpAndSettle();
      expect(posted, {
        'name': 'Tesco',
        'match': {'op': 'contains', 'value': 'TESCO'},
        'amount_min_pence': null,
        'amount_max_pence': null,
        'direction': 'out',
        'action': {
          'account': '6000 Groceries',
          'vat_code': null,
          'contact': null,
          'job_id': null,
        },
      });
    });

    testWidgets('a refusal stays on the sheet as its error', (tester) async {
      await pumpSheet(tester,
          onSave: (_) async => 'The minimum amount is above the maximum amount');
      final fields = find.byType(TextField);
      await tester.enterText(fields.at(1), 'TESCO');
      await tester.enterText(fields.at(4), '6000 Groceries');
      await reveal(tester, find.text('Save rule'));
      await tester.tap(find.text('Save rule'));
      await tester.pumpAndSettle();
      expect(find.text('The minimum amount is above the maximum amount'),
          findsOneWidget);
    });

    testWidgets('edit starts from the saved rule', (tester) async {
      await pumpSheet(
        tester,
        initial: {
          'id': 'abc123',
          'name': 'Tesco',
          'match': {'op': 'equals', 'value': 'TESCO STORES'},
          'amount_min_pence': null,
          'amount_max_pence': null,
          'direction': 'out',
          'action': {'account': '6000 Groceries', 'vat_code': 'S'},
        },
        onSave: (_) async => null,
      );
      expect(find.text('Edit bank rule'), findsOneWidget);
      final valueField =
          tester.widget<TextField>(find.byType(TextField).at(1));
      expect(valueField.controller!.text, 'TESCO STORES');
    });
  });

  group('WebOnlyCard', () {
    testWidgets('names the gap and links the exact page', (tester) async {
      usePhoneSurface(tester);
      await tester.pumpWidget(const MaterialApp(
        home: Scaffold(
          body: WebOnlyCard(
            message: 'Uploading a statement CSV happens on the web.',
            page: '/bank',
          ),
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('On the web'), findsOneWidget);
      expect(find.text('Uploading a statement CSV happens on the web.'),
          findsOneWidget);
      expect(find.text('Do this on the web'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('Settings Your data', () {
    testWidgets('export trigger saves the zip and says where',
        (tester) async {
      usePhoneSurface(tester);
      final fake = _ParityFake();
      await tester.pumpWidget(MaterialApp(
        home: SettingsScreen(
          testAccount: _account,
          testAccountReady: true,
          clientFactory: (settings, books) => fake,
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Your data'), findsOneWidget);

      await tester.dragUntilVisible(
        find.widgetWithText(OutlinedButton, 'Export your data'),
        find.byType(SingleChildScrollView),
        const Offset(0, -300),
      );
      await tester.tap(
          find.widgetWithText(OutlinedButton, 'Export your data'));
      await tester.pumpAndSettle();

      expect(fake.exported, isTrue);
      expect(
          find.text(
              'Saved accnomos-export-2026-10-27.zip (12 files) in your OneDrive, under 07 Reports/Exports.'),
          findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('a failed export shows the refusal', (tester) async {
      usePhoneSurface(tester);
      final fake = _ParityFake(exportError: 'The reader refused that request (status 413). Too big.');
      await tester.pumpWidget(MaterialApp(
        home: SettingsScreen(
          testAccount: _account,
          testAccountReady: true,
          clientFactory: (settings, books) => fake,
        ),
      ));
      await tester.pumpAndSettle();
      await tester.dragUntilVisible(
        find.widgetWithText(OutlinedButton, 'Export your data'),
        find.byType(SingleChildScrollView),
        const Offset(0, -300),
      );
      await tester.tap(
          find.widgetWithText(OutlinedButton, 'Export your data'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Too big'), findsOneWidget);
    });
  });

  group('AuditScreen filters', () {
    testWidgets('who and what narrow the trail at 360 dp', (tester) async {
      usePhoneSurface(tester);
      final fake = _AuditFake();
      await tester.pumpWidget(MaterialApp(
        home: AuditScreen(
          testAccount: _account,
          testAccountReady: true,
          clientFactory: (settings, books) => fake,
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Paid INV-2041.'), findsOneWidget);
      expect(
          find.text('Downloading the trail as a spreadsheet (CSV) happens on the web.'),
          findsOneWidget);

      await reveal(tester, find.text('Autopilot'));
      await tester.tap(find.text('Autopilot'));
      await tester.pumpAndSettle();
      expect(fake.lastActor, 'autopilot');

      await tester.tap(find.byType(DropdownButtonFormField<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Invoices').last);
      await tester.pumpAndSettle();
      expect(fake.lastKind, 'invoice');
      expect(tester.takeException(), isNull);
    });
  });
}

final _account =
    Account(id: '1', username: 'user@example.com', name: 'Test User');

/// Settings fake: rules, invoice profile and the data export only.
class _ParityFake extends RuntimeClient {
  _ParityFake({this.exportError})
      : super(AppSettings(runtimeUrl: 'http://reader:8780'));

  final String? exportError;
  bool exported = false;

  @override
  Future<List<Map<String, dynamic>>> rules() async => [];

  @override
  Future<Map<String, dynamic>> invoiceProfile() async =>
      {'terms_days': 30, 'bank': {}};

  @override
  Future<Map<String, dynamic>> booksExport() async {
    if (exportError != null) throw RuntimeException(exportError!);
    exported = true;
    return {
      'path': '07 Reports/Exports/accnomos-export-2026-10-27.zip',
      'name': 'accnomos-export-2026-10-27.zip',
      'size': 1024,
      'files': 12,
      'web_url': null,
    };
  }
}

/// Audit fake: one line per call, recording the filters it was read with.
class _AuditFake extends RuntimeClient {
  _AuditFake() : super(AppSettings(runtimeUrl: 'http://reader:8780'));

  String? lastActor;
  String? lastKind;

  @override
  Future<Map<String, dynamic>> audit({
    String? from,
    String? to,
    String? actor,
    String? kind,
    int limit = 200,
  }) async {
    lastActor = actor;
    lastKind = kind;
    return {
      'entries': [
        {
          'ts': '2026-10-27T10:00:00Z',
          'actor': 'user:user@example.com',
          'actor_kind': 'user',
          'actor_label': 'You',
          'event': 'invoice_paid',
          'summary': 'Paid INV-2041.',
          'refs': {},
        },
      ],
      'truncated': false,
    };
  }
}
