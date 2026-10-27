import 'package:flutter/material.dart';

import 'screens/ask_screen.dart';
import 'screens/home_screen.dart';
import 'screens/review_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/vat_screen.dart';
import 'theme.dart';

/// Accnomos — bookkeeping and VAT for UK small businesses.
/// Your books stay in your own cloud. Meta AI does the work.
///
/// v0.1.0: app shell (Home · Review · Ask · Files). Features arrive day by day;
/// see CHANGELOG.md in the repo.
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

  /// Review, Ask and VAT bring their own app bars, so the shell only
  /// titles the tabs that do not.
  bool get _hasOwnAppBar => _tab == 1 || _tab == 2 || _tab == 3;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: _hasOwnAppBar
          ? null
          : AppBar(
              backgroundColor: AccnomosColors.ground,
              elevation: 0,
              title: Text(_tab == 4 ? 'Files' : 'Home',
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
                _Placeholder('Files',
                    'A live view of the Accnomos folder in your own cloud storage.'),
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
              icon: Icon(Icons.folder_outlined), label: 'Files'),
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

class _Placeholder extends StatelessWidget {
  const _Placeholder(this.title, this.body);
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Container(
            width: 56,
            height: 56,
            decoration: BoxDecoration(
                color: AccnomosColors.tealTint,
                borderRadius: BorderRadius.circular(16)),
            child: const Icon(Icons.hourglass_top,
                color: AccnomosColors.tealDark),
          ),
          const SizedBox(height: 14),
          Text(title, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 6),
          Text(body,
              textAlign: TextAlign.center,
              style: const TextStyle(
                  color: AccnomosColors.muted, height: 1.4)),
        ],
      ),
    );
  }
}
