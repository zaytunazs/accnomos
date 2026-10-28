import 'package:flutter/material.dart';

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

/// "More" tab: keeps the bottom bar at five items while the new thin
/// clients live one tap away. The Personal entry only shows while
/// Settings › Personal has "Show personal finances" on.
class MoreScreen extends StatefulWidget {
  const MoreScreen({super.key});

  @override
  State<MoreScreen> createState() => _MoreScreenState();
}

class _MoreScreenState extends State<MoreScreen> {
  bool _showPersonal = false;

  @override
  void initState() {
    super.initState();
    AppSettings.load().then((settings) {
      if (!mounted) return;
      setState(() => _showPersonal = settings.showPersonalFinances);
    });
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
          const _Entry(
            icon: Icons.folder_outlined,
            title: 'Files',
            note: 'Your Accnomos folder in OneDrive',
            screen: FilesScreen(),
          ),
          const _Entry(
            icon: Icons.people_outline,
            title: 'Contacts',
            note: 'Balances and statements',
            screen: ContactsScreen(),
          ),
          const _Entry(
            icon: Icons.description_outlined,
            title: 'Invoices',
            note: 'Raise, preview and send',
            screen: InvoicesScreen(),
          ),
          const _Entry(
            icon: Icons.work_outline,
            title: 'Jobs',
            note: 'Jobs and timesheets',
            screen: JobsScreen(),
          ),
          const _Entry(
            icon: Icons.directions_car_outlined,
            title: 'Vehicles',
            note: 'Mileage and allowance',
            screen: VehiclesScreen(),
          ),
          const _Entry(
            icon: Icons.account_balance_outlined,
            title: 'Bank',
            note: 'Statements, unmatched lines and rules',
            screen: BankScreen(),
          ),
          const _Entry(
            icon: Icons.payments_outlined,
            title: 'Payroll',
            note: 'Pay runs — estimates, read only',
            screen: PayrollScreen(),
          ),
          const _Entry(
            icon: Icons.event_available_outlined,
            title: 'Month-end',
            note: 'The close checklist — read only; run it on the web',
            screen: MonthEndScreen(),
          ),
          if (_showPersonal)
            const _Entry(
              icon: Icons.savings_outlined,
              title: 'Personal',
              note: 'Budgets, bills and savings goals',
              screen: PersonalScreen(),
            ),
          const _Entry(
            icon: Icons.bar_chart_outlined,
            title: 'Reports',
            note: 'Profit and loss, aged balances, VAT and trend',
            screen: ReportsScreen(),
          ),
          const _Entry(
            icon: Icons.handshake_outlined,
            title: 'Your accountant',
            note: 'Who can see your books, and their queries — read only',
            screen: AccountantScreen(),
          ),
          const _Entry(
            icon: Icons.history_outlined,
            title: 'Audit trail',
            note: 'Who did what in your books — read only',
            screen: AuditScreen(),
          ),
        ],
      ),
    );
  }
}

class _Entry extends StatelessWidget {
  const _Entry({
    required this.icon,
    required this.title,
    required this.note,
    required this.screen,
  });

  final IconData icon;
  final String title;
  final String note;
  final Widget screen;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        minVerticalPadding: 10,
        leading: Icon(icon, color: AccnomosColors.tealDark),
        title: Text(title,
            style:
                const TextStyle(fontWeight: FontWeight.w700)),
        subtitle: Text(note,
            style:
                const TextStyle(color: AccnomosColors.muted)),
        trailing: const Icon(Icons.chevron_right_outlined),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute(builder: (_) => screen),
        ),
      ),
    );
  }
}
