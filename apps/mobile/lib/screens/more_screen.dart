import 'package:flutter/material.dart';

import '../theme.dart';
import 'bank_screen.dart';
import 'files_screen.dart';
import 'payroll_screen.dart';

/// Second-level screens that do not need a bottom-bar tab of their own:
/// the books files, pay runs and bank matching.
class MoreScreen extends StatelessWidget {
  const MoreScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AccnomosColors.ground,
      appBar: AppBar(
        backgroundColor: AccnomosColors.ground,
        elevation: 0,
        title:
            Text('More', style: Theme.of(context).textTheme.headlineSmall),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _row(
            context,
            icon: Icons.folder_outlined,
            title: 'Files',
            subtitle: 'Your books folder in OneDrive',
            screen: const FilesScreen(),
          ),
          _row(
            context,
            icon: Icons.payments_outlined,
            title: 'Payroll',
            subtitle: 'Pay runs, read-only on the phone',
            screen: const PayrollScreen(),
          ),
          _row(
            context,
            icon: Icons.account_balance_outlined,
            title: 'Bank',
            subtitle: 'Statements and lines to match',
            screen: const BankScreen(),
          ),
        ],
      ),
    );
  }

  Widget _row(
    BuildContext context, {
    required IconData icon,
    required String title,
    required String subtitle,
    required Widget screen,
  }) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Material(
        type: MaterialType.transparency,
        borderRadius: BorderRadius.circular(14),
        child: ListTile(
          leading: Container(
            width: 40,
            height: 40,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: AccnomosColors.tealTint,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(icon, color: AccnomosColors.tealDark),
          ),
          title: Text(title,
              style: const TextStyle(fontWeight: FontWeight.w800)),
          subtitle: Text(subtitle,
              style: const TextStyle(
                  color: AccnomosColors.muted, fontSize: 12)),
          trailing: const Icon(Icons.chevron_right_outlined),
          onTap: () => Navigator.of(context).push(
            MaterialPageRoute(builder: (_) => screen),
          ),
        ),
      ),
    );
  }
}
