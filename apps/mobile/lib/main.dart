import 'package:flutter/material.dart';

import 'screens/ask_screen.dart';
import 'screens/more_screen.dart';
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

  /// Review, Ask and VAT bring their own app bars, so the shell only
  /// titles the tabs that do not.
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
                _HomeTab(),
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

class _HomeTab extends StatelessWidget {
  const _HomeTab();

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text('Your books. Your cloud. Meta AI on your terms.',
            style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 6),
        const Text(
          'Accnomos keeps your bookkeeping in a folder you own (OneDrive first), '
          'reads receipts and invoices with Meta AI, and files VAT returns to HMRC '
          'only when you say so.',
          style: TextStyle(color: AccnomosColors.muted, height: 1.4),
        ),
        const SizedBox(height: 20),
        GridView.count(
          crossAxisCount: 2,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 12,
          crossAxisSpacing: 12,
          childAspectRatio: 1.35,
          children: const [
            _Tile(label: 'Cash in bank', value: '—', note: 'Connect to see'),
            _Tile(label: 'Owed to you', value: '—', note: 'Connect to see'),
            _Tile(label: 'VAT estimate', value: '—', note: 'Calculated by code'),
            _Tile(label: 'Needs a look', value: '0', note: 'Nothing waiting'),
          ],
        ),
        const SizedBox(height: 20),
        FilledButton(
          style: FilledButton.styleFrom(
              backgroundColor: AccnomosColors.teal,
              minimumSize: const Size.fromHeight(52),
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14))),
          onPressed: () => Navigator.of(context).push(
            MaterialPageRoute(builder: (_) => const SettingsScreen()),
          ),
          child: const Text('Connect your cloud',
              style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
        ),
        const SizedBox(height: 10),
        const Text(
          'Accnomos never stores your data on its own servers.',
          textAlign: TextAlign.center,
          style: TextStyle(color: AccnomosColors.muted, fontSize: 12),
        ),
      ],
    );
  }
}

class _Tile extends StatelessWidget {
  const _Tile({required this.label, required this.value, required this.note});
  final String label;
  final String value;
  final String note;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE3E1D8)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label.toUpperCase(),
              style: const TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: AccnomosColors.muted,
                  letterSpacing: 0.6)),
          const Spacer(),
          Text(value,
              style: const TextStyle(
                  fontSize: 26,
                  fontWeight: FontWeight.w800,
                  color: AccnomosColors.ink)),
          Text(note,
              style: const TextStyle(
                  fontSize: 12, color: AccnomosColors.muted)),
        ],
      ),
    );
  }
}
