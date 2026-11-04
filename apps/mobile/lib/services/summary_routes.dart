import 'package:flutter/material.dart';

import '../screens/bank_screen.dart';
import '../screens/contacts_screen.dart';
import '../screens/goals_screen.dart';
import '../screens/invoices_screen.dart';
import '../screens/month_end_screen.dart';
import '../screens/payroll_screen.dart';
import '../screens/personal_screen.dart';
import '../screens/reports_screen.dart';
import 'navigation.dart';

/// Where a summary line's action goes. The server names pages by their web
/// path ("/review", "/invoices?filter=overdue"); the app opens its own tab or
/// screen for the same page. A path the app has no page for gives no button.
sealed class SummaryTarget {
  const SummaryTarget();
}

/// One of the shell's tabs, by name (main.dart `shellTabIndex`).
class TabTarget extends SummaryTarget {
  const TabTarget(this.tab);
  final String tab;
}

/// A screen pushed over the current tab.
class ScreenTarget extends SummaryTarget {
  const ScreenTarget(this.name, this.builder);

  /// For tests and the button's semantics.
  final String name;
  final WidgetBuilder builder;
}

/// The target for [route] in the household or business app; null when the app
/// has no page for it (no button is shown).
SummaryTarget? summaryTarget(String route, {required bool household}) {
  final path = Uri.tryParse(route)?.path ?? route;
  switch (path) {
    case '/review':
      return const TabTarget('review');
    case '/vat':
      return household ? null : const TabTarget('vat');
    case '/ask':
      return household ? null : const TabTarget('ask');
    case '/personal':
      return household
          ? const TabTarget('budget')
          : ScreenTarget('budget', (_) => const PersonalScreen());
    case '/goals':
      return household
          ? const TabTarget('goals')
          : ScreenTarget('goals', (_) => const GoalsScreen());
    case '/invoices':
      return ScreenTarget('invoices', (_) => const InvoicesScreen());
    case '/bank':
    case '/bank/reconcile':
      return ScreenTarget('bank', (_) => const BankScreen());
    case '/month-end':
      return ScreenTarget('month-end', (_) => const MonthEndScreen());
    case '/contacts':
      return ScreenTarget('contacts', (_) => const ContactsScreen());
    case '/reports':
    case '/reports/cashflow':
      return ScreenTarget('reports', (_) => const ReportsScreen());
    case '/payroll':
      return household
          ? null
          : ScreenTarget('payroll', (_) => const PayrollScreen());
    default:
      return null; // e.g. /self-employment: no screen in the app
  }
}

/// Opens [target]: switches tab, or pushes the screen.
void openSummaryTarget(BuildContext context, SummaryTarget target) {
  switch (target) {
    case TabTarget(:final tab):
      AppNav.openTab(tab);
    case ScreenTarget(:final builder):
      Navigator.of(context).push(MaterialPageRoute(builder: builder));
  }
}
