import 'package:flutter/material.dart';

import '../services/auth.dart';
import '../services/books.dart' show booksClient;
import '../services/settings.dart';
import '../theme.dart';
import 'accountant_screen.dart';
import 'audit_screen.dart';
import 'bank_screen.dart';
import 'contacts_screen.dart';
import 'files_screen.dart';
import 'invoices_screen.dart';
import 'jobs_screen.dart';
import 'month_end_screen.dart';
import 'payroll_screen.dart';
import 'personal_screen.dart';
import 'reports_screen.dart';
import 'vehicles_screen.dart';

/// One row of the More tab. [needs] is the profile feature it depends on
/// (services/runtime/app/profile.py `features`), or null for every set of
/// books.
class MoreEntry {
  const MoreEntry(this.icon, this.title, this.note, this.screen, {this.needs});

  final IconData icon;
  final String title;
  final String note;
  final Widget screen;
  final String? needs;
}

/// The More rows for a profile's [features], as the web's menu hides them:
/// personal books have no invoices or payroll, and Reports mentions VAT only
/// for a VAT-registered business. Null features (not known yet, signed out,
/// or an older runtime without `GET /profile`) show everything. Personal
/// shows only while Settings › Personal has "Show personal finances" on.
List<MoreEntry> moreEntries(List<String>? features,
    {bool showPersonal = false}) {
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
        Icons.work_outline, 'Jobs', 'Jobs and timesheets', JobsScreen()),
    const MoreEntry(Icons.directions_car_outlined, 'Vehicles',
        'Mileage and allowance', VehiclesScreen()),
    const MoreEntry(Icons.account_balance_outlined, 'Bank',
        'Statements, unmatched lines and rules', BankScreen()),
    const MoreEntry(Icons.payments_outlined, 'Payroll',
        'Pay runs — estimates, read only', PayrollScreen(),
        needs: 'payroll'),
    const MoreEntry(Icons.event_available_outlined, 'Month-end',
        'The close checklist — read only; run it on the web', MonthEndScreen()),
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
    const MoreEntry(Icons.handshake_outlined, 'Your accountant',
        'Who can see your books, and their queries — read only', AccountantScreen()),
    const MoreEntry(Icons.history_outlined, 'Audit trail',
        'Who did what in your books — read only', AuditScreen()),
  ];
  return [
    for (final e in all)
      if (features == null || e.needs == null || features.contains(e.needs))
        e,
  ];
}

/// "More" tab: keeps the bottom bar at five items while the new thin
/// clients live one tap away. Signed in, it reads the books' profile
/// (`GET /profile`) and leaves out what those books do not have.
class MoreScreen extends StatefulWidget {
  const MoreScreen({super.key, this.features});

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
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title: Text(
          'More',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
        children: [
          for (final e in moreEntries(_features, showPersonal: _showPersonal))
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
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute(builder: (_) => entry.screen),
        ),
      ),
    );
  }
}
