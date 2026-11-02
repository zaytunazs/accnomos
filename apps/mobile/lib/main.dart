import 'package:flutter/material.dart';

import 'screens/ask_screen.dart';
import 'screens/goals_screen.dart';
import 'screens/household_home_screen.dart';
import 'screens/more_screen.dart';
import 'screens/home_screen.dart';
import 'screens/personal_screen.dart';
import 'screens/review_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/vat_screen.dart';
import 'services/app_mode.dart';
import 'theme.dart';

/// Accnomos — bookkeeping and VAT for UK small businesses.
/// Your books stay in your own cloud. Meta AI does the work.
///
/// v0.1.0: app shell (Home · Review · Ask · VAT return). Bank and Files stay
/// web-only; Jobs, Contacts, Vehicles (under More) and Invoices are thin
/// clients over the runtime.
void main() => runApp(const AccnomosApp());

class AccnomosApp extends StatelessWidget {
  const AccnomosApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Accnomos',
      debugShowCheckedModeBanner: false,
      // No dark theme: stay on the light theme even when the system is
      // dark, so text is always readable.
      themeMode: ThemeMode.light,
      theme: ThemeData(
        useMaterial3: true,
        scaffoldBackgroundColor: AccnomosColors.ground,
        colorScheme: ColorScheme.fromSeed(
          seedColor: AccnomosColors.teal,
          primary: AccnomosColors.teal,
          surface: Colors.white,
        ),
        textTheme: const TextTheme(
          headlineSmall: TextStyle(
              fontWeight: FontWeight.w800, color: AccnomosColors.ink),
          titleMedium: TextStyle(
              fontWeight: FontWeight.w700, color: AccnomosColors.ink),
          bodyMedium: TextStyle(color: AccnomosColors.ink),
        ),
      ),
      home: const Shell(),
    );
  }
}

class Shell extends StatefulWidget {
  const Shell({super.key});

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int _tab = 0;

  @override
  void initState() {
    super.initState();
    AppMode.state.addListener(_modeChanged);
    AppMode.refresh();
  }

  @override
  void dispose() {
    AppMode.state.removeListener(_modeChanged);
    super.dispose();
  }

  bool _household = AppMode.household;

  /// Personal books (or the household sample) get the household tabs; a
  /// change of treatment starts again on Home.
  void _modeChanged() {
    if (!mounted || AppMode.household == _household) return;
    setState(() {
      _household = AppMode.household;
      _tab = 0;
    });
  }

  /// Review, Ask, VAT and More bring their own app bars, so the shell
  /// only titles Home.
  bool get _hasOwnAppBar => _tab != 0;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: _hasOwnAppBar
          ? null
          : AppBar(
              backgroundColor: AccnomosColors.ground,
              elevation: 0,
              title: Text('Home',
                  style: Theme.of(context).textTheme.headlineSmall),
              actions: _tab == 0
                  ? [
                      IconButton(
                        icon: const Icon(Icons.settings_outlined),
                        tooltip: 'Settings',
                        constraints: const BoxConstraints(
                            minWidth: 48, minHeight: 48),
                        onPressed: () => Navigator.of(context)
                            .push(
                              MaterialPageRoute(
                                  builder: (_) => const SettingsScreen()),
                            )
                            .then((_) => AppMode.refresh()),
                      ),
                    ]
                  : null,
            ),
      body: Column(
        children: [
          // Tabs with their own app bar have no AppBar above this banner, so keep it below the status bar.
          if (_hasOwnAppBar)
            SafeArea(
                bottom: false, child: _SampleBanner(household: _household))
          else
            _SampleBanner(household: _household),
          Expanded(
            child: IndexedStack(
              key: ValueKey(_household),
              index: _tab,
              children: _household
                  ? const [
                      HouseholdHomeScreen(),
                      ReviewScreen(),
                      PersonalScreen(title: 'Budget'),
                      GoalsScreen(),
                      MoreScreen(household: true),
                    ]
                  : const [
                      HomeScreen(),
                      ReviewScreen(),
                      AskScreen(),
                      VatScreen(),
                      MoreScreen(),
                    ],
            ),
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        indicatorColor: AccnomosColors.tealTint,
        destinations: shellDestinations(household: _household),
      ),
    );
  }
}

/// The bottom tabs: the household app (personal books) has Budget and Goals
/// where a business has Ask and VAT; there is no VAT tab for a household.
List<NavigationDestination> shellDestinations({required bool household}) =>
    household
        ? const [
            NavigationDestination(
                icon: Icon(Icons.home_outlined), label: 'Home'),
            NavigationDestination(
                icon: Icon(Icons.checklist_outlined), label: 'Review'),
            NavigationDestination(
                icon: Icon(Icons.pie_chart_outline), label: 'Budget'),
            NavigationDestination(
                icon: Icon(Icons.flag_outlined), label: 'Goals'),
            NavigationDestination(
                icon: Icon(Icons.more_horiz_outlined), label: 'More'),
          ]
        : const [
            NavigationDestination(
                icon: Icon(Icons.home_outlined), label: 'Home'),
            NavigationDestination(
                icon: Icon(Icons.checklist_outlined), label: 'Review'),
            NavigationDestination(
                icon: Icon(Icons.chat_bubble_outline), label: 'Ask'),
            NavigationDestination(
                icon: Icon(Icons.receipt_long_outlined), label: 'VAT'),
            NavigationDestination(
                icon: Icon(Icons.more_horiz_outlined), label: 'More'),
          ];

/// The sample label above every tab.
String sampleBannerText({required bool household}) => household
    ? 'SAMPLE — FICTIONAL HOUSEHOLD · demo data only'
    : 'SAMPLE — FICTIONAL COMPANY · demo data only';

class _SampleBanner extends StatelessWidget {
  const _SampleBanner({required this.household});

  final bool household;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: AccnomosColors.ink,
      padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 12),
      child: Text(
        sampleBannerText(household: household),
        textAlign: TextAlign.center,
        style: const TextStyle(
            color: AccnomosColors.ground,
            fontSize: 11,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.6),
      ),
    );
  }
}
