import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../services/auth.dart';
import '../services/books.dart' show booksClient;
import '../services/demo.dart';
import '../services/navigation.dart';
import '../services/plan_limit.dart' show planBillingUrl;
import '../widgets/web_only.dart' show webAppBase;
import '../services/region.dart';
import '../services/store_policy.dart';
import '../services/settings.dart';
import '../theme.dart';
import '../widgets/brand.dart';
import 'accountant_screen.dart';
import 'audit_screen.dart';
import 'bank_screen.dart';
import 'bill_pay_screen.dart';
import 'calendar_screen.dart';
import 'contacts_screen.dart';
import 'ask_screen.dart';
import 'files_screen.dart';
import 'goals_screen.dart';
import 'invoices_screen.dart';
import 'jobs_screen.dart';
import 'month_end_screen.dart';
import 'notes_screen.dart';
import 'payroll_screen.dart';
import 'report_problem_sheet.dart';
import 'personal_screen.dart';
import 'reports_screen.dart';
import 'vehicles_screen.dart';

/// One row of the More tab. [needs] is the profile feature it depends on
/// (services/runtime/app/profile.py `features`), or null for every set of
/// books.
class MoreEntry {
  const MoreEntry(this.icon, this.title, this.note, this.screen,
      {this.needs, this.action});

  final IconData icon;
  final String title;
  final String note;

  /// The screen to open; null for a row that does something else ([action]).
  final Widget? screen;
  final String? needs;

  /// What the row does instead of opening a screen (Plan & billing opens the
  /// web page in the browser; Report a problem opens its sheet).
  final Future<void> Function(BuildContext context)? action;
}

Future<void> _openPlanBilling(BuildContext context) async {
  // No buying in the app (Google Play billing fees): the plan is managed on the web.
  await launchUrl(Uri.parse(planBillingUrl),
      mode: LaunchMode.externalApplication);
}

Future<void> _openReport(BuildContext context) => showReportProblem(context);

/// The help centre and the Support page (assistant, tickets) live on the web: opened in the browser.
const helpCentreUrl = '$webAppBase/help';
const supportUrl = '$webAppBase/support';

Future<void> _openHelp(BuildContext context) =>
    launchUrl(Uri.parse(helpCentreUrl), mode: LaunchMode.externalApplication);

Future<void> _openSupport(BuildContext context) =>
    launchUrl(Uri.parse(supportUrl), mode: LaunchMode.externalApplication);

/// The last rows of every More, business and household books alike. Plan &
/// billing opens the web, so it is left out where the store does not allow a
/// purchase link ([StorePolicy.purchaseLinksAllowed]: iOS).
List<MoreEntry> get _accountEntries => accountEntries(StorePolicy.purchaseLinksAllowed);

/// [_accountEntries] for a store that does, or does not, allow purchase links.
List<MoreEntry> accountEntries(bool purchaseLinksAllowed) => [
      if (purchaseLinksAllowed)
        const MoreEntry(Icons.workspace_premium_outlined, 'Plan & billing',
            'Your plan, usage and invoices, on the web', null,
            action: _openPlanBilling),
      const MoreEntry(Icons.help_outline, 'Help',
          'Step-by-step guides, on the web', null,
          action: _openHelp),
      const MoreEntry(Icons.support_agent_outlined, 'Contact support',
          'Ask the support assistant or raise a ticket, on the web', null,
          action: _openSupport),
      const MoreEntry(Icons.flag_circle_outlined, 'Report a problem',
          'Tell us what went wrong', null,
          action: _openReport),
    ];

/// The More rows for a profile's [features], as the web's menu hides them:
/// personal books have no invoices or payroll, and Reports mentions VAT only
/// for a VAT-registered business. Null features (not known yet, signed out,
/// or an older runtime without `GET /profile`) show everything. Personal
/// shows only while Settings › Personal has "Show personal finances" on.
List<MoreEntry> moreEntries(List<String>? features,
    {bool showPersonal = false, bool household = false}) {
  if (household) return [...householdMoreEntries, ..._accountEntries];
  final vat = features == null || features.contains('vat');
  final all = [
    const MoreEntry(Icons.folder_outlined, 'Files',
        'Your Accnomos folder in OneDrive', FilesScreen()),
    const MoreEntry(Icons.people_outline, 'Contacts',
        'Balances and statements', ContactsScreen()),
    const MoreEntry(Icons.description_outlined, 'Invoices',
        'Raise, preview and send', InvoicesScreen(),
        needs: 'invoices'),
    const MoreEntry(
        Icons.work_outline, 'Jobs', 'Jobs, timesheets, staff and invoicing hours', JobsScreen()),
    const MoreEntry(Icons.directions_car_outlined, 'Vehicles',
        'Mileage and allowance', VehiclesScreen()),
    const MoreEntry(Icons.account_balance_outlined, 'Bank',
        'Statements, unmatched lines and rules', BankScreen()),
    const MoreEntry(Icons.payments_outlined, 'Payroll',
        'Pay runs: prepare, export and confirm', PayrollScreen(),
        needs: 'payroll'),
    // Business books only (the web's /purchases): suppliers' bills paid from
    // PayPal on their due date, each one approved by the owner.
    const MoreEntry(Icons.outbox_outlined, 'Bill pay',
        'Pay suppliers\' bills with PayPal on their due date', BillPayScreen(),
        needs: 'invoices'),
    const MoreEntry(Icons.event_available_outlined, 'Month-end',
        'Run the close and approve its cards', MonthEndScreen()),
    if (showPersonal)
      const MoreEntry(Icons.savings_outlined, 'Personal',
          'Budgets, bills and savings goals', PersonalScreen()),
    MoreEntry(
        Icons.bar_chart_outlined,
        'Reports',
        vat
            ? 'Profit and loss, aged balances, VAT and trend'
            : 'Profit and loss, aged balances and trend',
        const ReportsScreen()),
    const MoreEntry(Icons.flag_outlined, 'Goals',
        'Targets tracked against your books', GoalsScreen()),
    const MoreEntry(Icons.calendar_month_outlined, 'Calendar',
        'Your plan: the next two weeks and your deadlines', CalendarScreen()),
    const MoreEntry(Icons.sticky_note_2_outlined, 'Notes',
        'Typed, or said to the assistant', NotesScreen()),
    const MoreEntry(Icons.handshake_outlined, 'Your accountant',
        'Invite, remove access, answer queries', AccountantScreen()),
    const MoreEntry(Icons.history_outlined, 'Audit trail',
        'Who did what in your books, with CSV export', AuditScreen()),
    ..._accountEntries,
  ];
  return [
    for (final e in all)
      if (features == null || e.needs == null || features.contains(e.needs))
        e,
  ];
}

/// The More rows for personal books (the household app): Budget and Goals
/// are tabs, Ask moves here, and nothing business-only (invoices, jobs,
/// vehicles, payroll, month-end, business reports, accountant) shows.
const householdMoreEntries = [
  MoreEntry(Icons.chat_bubble_outline, 'Ask',
      'Questions about your money, answered from your books', AskScreen()),
  MoreEntry(Icons.account_balance_outlined, 'Bank',
      'Statements, unmatched lines and rules', BankScreen()),
  MoreEntry(Icons.folder_outlined, 'Files',
      'Your Accnomos folder in OneDrive', FilesScreen()),
  MoreEntry(Icons.people_outline, 'Contacts', 'People and payees',
      ContactsScreen()),
  MoreEntry(Icons.sticky_note_2_outlined, 'Notes',
      'Typed, or said to the assistant', NotesScreen()),
  MoreEntry(Icons.history_outlined, 'Audit trail',
      'Who did what in your books, with CSV export', AuditScreen()),
];

/// "More" tab: keeps the bottom bar at five items while the new thin
/// clients live one tap away. Signed in, it reads the books' profile
/// (`GET /profile`) and leaves out what those books do not have. The Personal
/// entry only shows while Settings › Personal has "Show personal finances" on.
class MoreScreen extends StatefulWidget {
  const MoreScreen({super.key, this.features, this.household = false});

  /// The household app's More (personal books, or the household sample).
  final bool household;

  /// The profile's features, for tests; null reads them from the runtime.
  final List<String>? features;

  @override
  State<MoreScreen> createState() => _MoreScreenState();
}

class _MoreScreenState extends State<MoreScreen> {
  List<String>? _features;
  bool _showPersonal = false;

  @override
  void initState() {
    super.initState();
    _features = widget.features;
    AppSettings.load().then((settings) {
      if (!mounted) return;
      setState(() => _showPersonal = settings.showPersonalFinances);
      if (widget.features == null) _loadFeatures(settings);
    });
  }

  Future<void> _loadFeatures(AppSettings settings) async {
    try {
      final auth = AuthService();
      final account = await auth.account();
      if (account == null) return;
      final profile =
          await (await booksClient(settings, auth, account)).booksProfile();
      final features = profile['features'];
      BooksRegion.current.value = BooksRegion.fromJson(profile['region']);
      if (!mounted || features is! List) return;
      setState(() => _features = [for (final f in features) f.toString()]);
    } catch (_) {
      // Signed out, offline or an older runtime: every entry stays.
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        leading: const BrandLeading(),
        title: Text(
          'More',
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 96), // clear of the Talk button
        children: [
          ValueListenableBuilder<DemoInfo?>(
            valueListenable: Demo.state,
            builder: (context, demo, _) =>
                demo == null ? const SizedBox.shrink() : DemoCard(demo: demo),
          ),
          for (final e in moreEntries(_features,
              showPersonal: _showPersonal, household: widget.household))
            _Entry(entry: e),
        ],
      ),
    );
  }
}

class _Entry extends StatelessWidget {
  const _Entry({required this.entry});

  final MoreEntry entry;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        minVerticalPadding: 10,
        leading: Icon(entry.icon, color: AccnomosColors.tealDark),
        title: Text(entry.title,
            style:
                const TextStyle(fontWeight: FontWeight.w700)),
        subtitle: Text(entry.note,
            style:
                const TextStyle(color: AccnomosColors.muted)),
        trailing: const Icon(Icons.chevron_right_outlined),
        onTap: () {
          final action = entry.action;
          if (action != null) {
            action(context);
            return;
          }
          Navigator.of(context).push(
            MaterialPageRoute(builder: (_) => entry.screen!),
          );
        },
      ),
    );
  }
}

/// During a demo, at the top of More: which demo this is, a switch to the
/// other one, and the way out (back to Welcome).
class DemoCard extends StatefulWidget {
  const DemoCard({super.key, required this.demo});

  final DemoInfo demo;

  @override
  State<DemoCard> createState() => _DemoCardState();
}

class _DemoCardState extends State<DemoCard> {
  bool _busy = false;
  String? _error;

  Future<void> _switch() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await Demo.start(
          widget.demo.runtimeUrl, widget.demo.household ? 'company' : 'personal');
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final demo = widget.demo;
    final other = demo.household ? 'company' : 'personal';
    return Container(
      key: const Key('more-demo-card'),
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AccnomosColors.tealTint,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFB9DCD5)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(demo.household ? 'Personal demo' : 'Company demo',
              style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: AccnomosColors.ink)),
          const SizedBox(height: 4),
          Text(
            '${demo.business.isEmpty ? 'Fictional sample books' : demo.business}. '
            'Changes reset after two hours; VAT returns go to HMRC\'s sandbox, never live HMRC, and no email is sent.',
            style: const TextStyle(color: AccnomosColors.muted, height: 1.4),
          ),
          if (_error != null) ...[
            const SizedBox(height: 8),
            Text(_error!, style: const TextStyle(color: AccnomosColors.negText)),
          ],
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              OutlinedButton(
                key: const Key('more-demo-switch'),
                onPressed: _busy ? null : _switch,
                child: Text(_busy ? 'Starting…' : 'Switch to the $other demo'),
              ),
              TextButton(
                key: const Key('more-demo-exit'),
                onPressed: _busy ? null : AppNav.exitDemo,
                child: const Text('Exit demo'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
