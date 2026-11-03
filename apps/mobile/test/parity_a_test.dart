import 'package:accnomos_mobile/screens/accountant_screen.dart';
import 'package:accnomos_mobile/screens/audit_screen.dart';
import 'package:accnomos_mobile/screens/job_detail_screen.dart';
import 'package:accnomos_mobile/screens/payroll_screen.dart';
import 'package:accnomos_mobile/services/runtime_client.dart';
import 'package:accnomos_mobile/services/settings.dart';
import 'package:accnomos_mobile/services/share.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:msal_auth/msal_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Web parity on the phone: pay runs (edit, export, confirm, reopen), jobs
/// (figures, invoice these hours, staff and rates), your accountant (invite,
/// remove, answer) and the audit trail's CSV. Fakes answer without network.
void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));
  tearDown(() => ShareText.testHook = null);

  void phone(WidgetTester tester) {
    tester.view.physicalSize = const Size(360, 780);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
  }

  Future<void> tapText(WidgetTester tester, String text) async {
    final f = find.text(text);
    await tester.ensureVisible(f.first);
    await tester.pumpAndSettle();
    await tester.tap(f.first);
    await tester.pumpAndSettle();
  }

  test('audit CSV has the web columns and quotes where needed', () {
    final csv = auditCsv([
      {
        'ts': '2026-10-27T10:00:00Z',
        'actor': 'user:a@b.com',
        'actor_kind': 'user',
        'actor_label': 'You',
        'event': 'invoice_paid',
        'summary': 'Paid INV-1, "in full", thanks',
        'refs': {'invoice': 'INV-1'},
      },
    ]);
    final rows = csv.split('\r\n');
    expect(rows.first, 'ts,actor,actor_kind,who,event,summary,proposal,ledger_event,invoice,action,file');
    expect(rows[1], '2026-10-27T10:00:00Z,user:a@b.com,user,You,invoice_paid,"Paid INV-1, ""in full"", thanks",,,INV-1,,');
  });

  group('pay run', () {
    testWidgets('edit hours, export the CSV, confirm with real figures', (tester) async {
      phone(tester);
      final fake = _Fake();
      String? shared;
      ShareText.testHook = (text, subject, mime) async {
        shared = text;
        return true;
      };
      await tester.pumpWidget(MaterialApp(
        home: PayrollDetailScreen(
          run: _run(),
          staffNames: const {'s1': 'Sam Builder'},
          clientFor: () async => fake,
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Sam Builder'), findsOneWidget);
      expect(find.textContaining('(estimate)'), findsOneWidget);
      await tester.enterText(find.widgetWithText(TextField, 'Hours'), '40');
      await tapText(tester, 'Save changes');
      expect(fake.edited.single['hours'], 40.0);
      expect(fake.edited.single['rate_pence'], 1850);

      await tapText(tester, 'Export CSV');
      expect(fake.exported, ['2026-10']);
      expect(shared, 'staff,hours\nSam Builder,40\n');
      expect(find.text('Saved to 05 Payroll/2026-10.csv in your books.'), findsOneWidget);

      await tapText(tester, 'Confirm with real figures');
      await tester.enterText(find.widgetWithText(TextField, 'Gross pay (£)'), '740.00');
      await tester.enterText(find.widgetWithText(TextField, 'Employer NI (£)'), '50.25');
      await tester.tap(find.widgetWithText(FilledButton, 'Confirm'));
      await tester.pumpAndSettle();
      expect(fake.confirmed, [(74000, 5025)]);
      expect(find.text('Reopen'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('jobs', () {
    testWidgets('job figures, entries and invoice these hours with nothing unbilled', (tester) async {
      phone(tester);
      final fake = _Fake(unbilledLines: false);
      await tester.pumpWidget(MaterialApp(
        home: JobDetailScreen(jobId: 'j1', clientFor: () async => fake),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Elm Road kitchen'), findsOneWidget);
      expect(find.text('£1,200.00'), findsOneWidget); // billable value
      expect(find.text('27 Oct 2026 · 7.5 h'), findsOneWidget);
      await tapText(tester, 'Invoice these hours');
      expect(fake.invoiceLinesFor, ['j1']);
      expect(find.text('No unbilled billable hours on this job.'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('staff and rates: add a person', (tester) async {
      phone(tester);
      final fake = _Fake();
      await tester.pumpWidget(MaterialApp(home: StaffScreen(clientFor: () async => fake)));
      await tester.pumpAndSettle();
      expect(find.textContaining('costs £18.50/h'), findsOneWidget);
      await tester.tap(find.text('Add a person'));
      await tester.pumpAndSettle();
      await tester.enterText(find.widgetWithText(TextField, 'Name'), 'Alex Rowe');
      await tester.enterText(find.widgetWithText(TextField, 'Cost per hour (£)'), '20');
      await tester.enterText(find.widgetWithText(TextField, 'Charge per hour (£, optional)'), '45');
      await tapText(tester, 'Add person');
      expect(fake.staffAdded.single, {
        'name': 'Alex Rowe',
        'role': '',
        'hourly_rate_pence': 2000,
        'charge_rate_pence': 4500,
        'active': true,
      });
      expect(tester.takeException(), isNull);
    });
  });

  group('accountant', () {
    testWidgets('answer a query and remove access', (tester) async {
      phone(tester);
      final fake = _Fake();
      await tester.pumpWidget(MaterialApp(
        home: AccountantScreen(
          testAccount: _account,
          testAccountReady: true,
          clientFactory: (settings, books) => fake,
        ),
      ));
      await tester.pumpAndSettle();
      expect(find.textContaining('on the web'), findsNothing);
      await tester.enterText(find.widgetWithText(TextField, 'Your answer'), 'It was fuel.');
      await tapText(tester, 'Send answer');
      expect(fake.replies, [('q1', 'It was fuel.')]);
      await tapText(tester, 'Remove');
      await tester.tap(find.widgetWithText(FilledButton, 'Remove access'));
      await tester.pumpAndSettle();
      expect(fake.revoked, ['inv1']);
      expect(find.text('Invite an accountant'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });
}

final _account = Account(id: '1', username: 'user@example.com', name: 'Test User');

Map<String, dynamic> _run({String status = 'draft'}) => {
      'period_start': '2026-10-01',
      'period_end': '2026-10-31',
      'pay_date': '2026-10-31',
      'status': status,
      'lines': [
        {
          'staff_id': 's1',
          'hours': 37.5,
          'rate_pence': 1850,
          'gross_pence': 69375,
          'est_paye_pence': 5000,
          'est_ee_ni_pence': 2000,
          'est_er_ni_pence': 3000,
          'est_net_pence': 62375,
          'notes': '',
        },
      ],
      'confirmed_gross_pence': status == 'confirmed' ? 74000 : null,
      'warnings': [],
      'estimate': 'Estimates only, not a payslip.',
    };

class _Fake extends RuntimeClient {
  _Fake({this.unbilledLines = true}) : super(AppSettings(runtimeUrl: 'http://reader:8780'));

  final bool unbilledLines;
  final List<Map<String, dynamic>> edited = [];
  final List<String> exported = [];
  final List<(int, int)> confirmed = [];
  final List<String> invoiceLinesFor = [];
  final List<Map<String, dynamic>> staffAdded = [];
  final List<(String, String)> replies = [];
  final List<String> revoked = [];

  @override
  Future<Map<String, dynamic>> editPayRun(String period, List<Map<String, dynamic>> lines,
      {String? payDate}) async {
    edited.addAll(lines);
    return _run();
  }

  @override
  Future<Map<String, dynamic>> exportPayRun(String period) async {
    exported.add(period);
    return {'path': '05 Payroll/$period.csv', 'csv': 'staff,hours\nSam Builder,40\n', 'estimate': ''};
  }

  @override
  Future<Map<String, dynamic>> confirmPayRun(String period, int gross, int erNi) async {
    confirmed.add((gross, erNi));
    return _run(status: 'confirmed');
  }

  @override
  Future<Map<String, dynamic>> jobSummary(String id) async => {
        'job': {'id': id, 'name': 'Elm Road kitchen', 'status': 'open', 'customer_id': null},
        'customer_name': 'Halloway Interiors',
        'hours': 7.5,
        'billable_hours': 7.5,
        'unbilled_hours': 7.5,
        'labour_cost_pence': 13875,
        'billable_value_pence': 120000,
        'invoiced_value_pence': 0,
        'unbilled_value_pence': 33750,
        'materials_pence': 0,
        'margin_pence': 106125,
        'by_staff': [],
        'warnings': [],
      };

  @override
  Future<List<Map<String, dynamic>>> timesheets({String? jobId, String? staffId, String? month}) async => [
        {'id': 't1', 'date': '2026-10-27', 'hours': 7.5, 'note': 'Fitting', 'billable': true, 'invoiced_in': null},
      ];

  @override
  Future<Map<String, dynamic>> jobInvoiceLines(String id) async {
    invoiceLinesFor.add(id);
    return {'job_id': id, 'customer_id': null, 'lines': unbilledLines ? [{}] : [], 'warnings': []};
  }

  @override
  Future<List<Map<String, dynamic>>> staff() async => [
        {'id': 's1', 'name': 'Sam Builder', 'role': 'Joiner', 'hourly_rate_pence': 1850, 'charge_rate_pence': null, 'active': true},
      ];

  @override
  Future<Map<String, dynamic>> createStaff(Map<String, dynamic> member) async {
    staffAdded.add(member);
    return {...member, 'id': 's2'};
  }

  @override
  Future<Map<String, dynamic>> accountant() async => {
        'invitations': [
          {
            'id': 'inv1',
            'kind': 'own',
            'email': 'acc@firm.example',
            'name': 'Pat',
            'role': 'read',
            'method': 'graph',
            'invited_at': '2026-10-01T09:00:00Z',
            'revoked_at': null,
          },
        ],
      };

  @override
  Future<List<Map<String, dynamic>>> queries({String? status}) async => [
        {
          'id': 'q1',
          'subject': {'kind': 'transaction', 'ref': 'e1', 'label': 'Shell £60.00'},
          'status': 'open',
          'waiting_on': 'client',
          'messages': [
            {'ts': '2026-10-28T09:00:00Z', 'author': 'acc@firm.example', 'role': 'accountant', 'text': 'What was this?'},
          ],
        },
      ];

  @override
  Future<Map<String, dynamic>> replyQuery(String id, String text) async {
    replies.add((id, text));
    return {};
  }

  @override
  Future<Map<String, dynamic>> revokeAccountant(String id) async {
    revoked.add(id);
    return {};
  }
}
