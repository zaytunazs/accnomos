import 'package:flutter/material.dart';

import 'screens/ask_screen.dart';
import 'screens/more_screen.dart';
import 'screens/home_screen.dart';
import 'screens/review_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/vat_screen.dart';
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
                        onPressed: () =>
                            Navigator.of(context).push(
                          MaterialPageRoute(
                              builder: (_) =>
                                  const SettingsScreen()),
                        ),
                      ),
                    ]
                  : null,
            ),
      body: Column(
        children: [
          const _SampleBanner(),
          Expanded(
            child: IndexedStack(
              index: _tab,
              children: const [
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
        destinations: const [
          NavigationDestination(icon: Icon(Icons.home_outlined), label: 'Home'),
          NavigationDestination(
              icon: Icon(Icons.checklist_outlined), label: 'Review'),
          NavigationDestination(
              icon: Icon(Icons.chat_bubble_outline), label: 'Ask'),
          NavigationDestination(
              icon: Icon(Icons.receipt_long_outlined), label: 'VAT'),
          NavigationDestination(
              icon: Icon(Icons.more_horiz_outlined), label: 'More'),
        ],
      ),
    );
  }
}

class _SampleBanner extends StatelessWidget {
  const _SampleBanner();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: AccnomosColors.ink,
      padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 12),
      child: const Text(
        'SAMPLE — FICTIONAL COMPANY · demo data only',
        textAlign: TextAlign.center,
        style: TextStyle(
            color: AccnomosColors.ground,
            fontSize: 11,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.6),
      ),
    );
  }
}
