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
import 'screens/welcome_screen.dart';
import 'services/app_mode.dart';
import 'services/demo.dart';
import 'theme.dart';
import 'widgets/brand.dart';

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
      theme: accnomosTheme(),
      home: const LaunchGate(),
    );
  }
}

/// What the app opens on. Signed in with Microsoft, or in a live demo: the
/// tabs ([Shell]). Otherwise the Welcome page, as the website opens on its
/// landing page rather than on half-empty books. Until the first check has
/// answered, the brand splash.
class LaunchGate extends StatefulWidget {
  const LaunchGate({super.key, this.restore = true});

  /// Tests: skip reading the saved demo and MSAL at launch.
  final bool restore;

  @override
  State<LaunchGate> createState() => _LaunchGateState();
}

class _LaunchGateState extends State<LaunchGate> {
  String? _notice;
  bool _hadDemo = Demo.active;

  @override
  void initState() {
    super.initState();
    AppMode.state.addListener(_changed);
    Demo.state.addListener(_demoChanged);
    if (widget.restore) _start();
  }

  Future<void> _start() async {
    try {
      await Demo.restore();
    } catch (_) {
      // No saved demo, or storage unavailable.
    }
    _hadDemo = Demo.active;
    await AppMode.refresh();
  }

  @override
  void dispose() {
    AppMode.state.removeListener(_changed);
    Demo.state.removeListener(_demoChanged);
    super.dispose();
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  /// A demo started, switched, timed out or ended: read the treatment again.
  void _demoChanged() {
    final now = Demo.active;
    if (_hadDemo && !now) {
      _notice = null; // left on purpose, or could not be renewed
    }
    _hadDemo = now;
    AppMode.refresh();
  }

  @override
  Widget build(BuildContext context) {
    final mode = AppMode.state.value;
    if (!mode.loaded) return const BrandSplash();
    if (mode.signedIn) return const Shell();
    return WelcomeScreen(notice: _notice);
  }
}

/// The first frame while the app checks the sign-in: the same dark-teal and
/// mark as the Android launch screen.
class BrandSplash extends StatelessWidget {
  const BrandSplash({super.key});

  @override
  Widget build(BuildContext context) => const Scaffold(
        backgroundColor: AccnomosColors.ledger,
        body: Center(child: BrandLockup(onDark: true, size: 44)),
      );
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
              titleSpacing: 16,
              title: const BrandLockup(size: 30),
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
          // A demo says so above every tab, with the way out. Tabs with their
          // own app bar have no AppBar above it, so keep it below the status bar.
          ValueListenableBuilder<DemoInfo?>(
            valueListenable: Demo.state,
            builder: (context, demo, _) {
              if (demo == null) return const SizedBox.shrink();
              final banner = DemoBanner(demo: demo);
              return _hasOwnAppBar
                  ? SafeArea(bottom: false, child: banner)
                  : banner;
            },
          ),
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

/// The slim bar above every tab during a demo: the web demo bar's label and
/// Exit demo (back to Welcome; the runtime drops the session).
class DemoBanner extends StatelessWidget {
  const DemoBanner({super.key, required this.demo});

  final DemoInfo demo;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('demo-banner'),
      width: double.infinity,
      color: AccnomosColors.sidebar,
      padding: const EdgeInsets.only(left: 14, right: 4),
      child: Row(
        children: [
          Container(width: 3, height: 18, color: AccnomosColors.brass),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              '${demo.label} · demo data only',
              style: const TextStyle(
                  color: AccnomosColors.markLight,
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.3),
            ),
          ),
          TextButton(
            key: const Key('demo-exit'),
            onPressed: Demo.end,
            style: TextButton.styleFrom(
                foregroundColor: AccnomosColors.markLight,
                minimumSize: const Size(44, 44)),
            child: const Text('Exit demo'),
          ),
        ],
      ),
    );
  }
}
