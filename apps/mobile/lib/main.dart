import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter/services.dart';

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
      navigatorKey: appNavigatorKey,
      builder: demoFrameBuilder,
      home: const LaunchGate(),
    );
  }
}

/// The app's one navigator, so the demo bar (above every route) can close
/// pushed screens when the demo ends.
final GlobalKey<NavigatorState> appNavigatorKey = GlobalKey<NavigatorState>();

/// `MaterialApp.builder`: during a demo the demo bar sits above every route
/// (tabs and pushed screens alike), like the website's demo bar; the route
/// below it no longer pads for the status bar.
Widget demoFrameBuilder(BuildContext context, Widget? child) =>
    DemoFrame(child: child ?? const SizedBox.shrink());

class DemoFrame extends StatelessWidget {
  const DemoFrame({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<DemoInfo?>(
      valueListenable: Demo.state,
      builder: (context, demo, _) {
        if (demo == null) return child;
        return Column(
          children: [
            Material(
              color: AccnomosColors.sidebar,
              child: SafeArea(bottom: false, child: DemoBanner(demo: demo)),
            ),
            Expanded(
              child: MediaQuery.removePadding(
                context: context,
                removeTop: true,
                child: child,
              ),
            ),
          ],
        );
      },
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
    if (!mounted) return;
    if (SchedulerBinding.instance.schedulerPhase ==
        SchedulerPhase.persistentCallbacks) {
      SchedulerBinding.instance.addPostFrameCallback((_) {
        if (mounted) setState(() {});
      });
    } else {
      setState(() {});
    }
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
    Demo.state.addListener(_demoChanged);
    AppMode.refresh();
  }

  void _demoChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    AppMode.state.removeListener(_modeChanged);
    Demo.state.removeListener(_demoChanged);
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

  /// A message from one tab (an "Approved · Undo" bar) never follows the
  /// user to another tab.
  void _selectTab(int i) {
    ScaffoldMessenger.of(context).hideCurrentSnackBar();
    setState(() => _tab = i);
  }

  DateTime? _backAt;

  /// Back on a tab other than Home goes to Home; on Home a second Back
  /// within two seconds leaves the app, so one stray Back never closes it.
  void _onBack(bool didPop, Object? result) {
    if (didPop) return;
    final messenger = ScaffoldMessenger.of(context);
    if (_tab != 0) {
      _selectTab(0);
      return;
    }
    final now = DateTime.now();
    if (_backAt != null && now.difference(_backAt!) < const Duration(seconds: 2)) {
      SystemNavigator.pop();
      return;
    }
    _backAt = now;
    messenger
      ..hideCurrentSnackBar()
      ..showSnackBar(const SnackBar(
        content: Text('Press Back again to leave Accnomos'),
        duration: Duration(seconds: 2),
      ));
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: _onBack,
      child: _scaffold(context),
    );
  }

  Widget _scaffold(BuildContext context) {
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
      // The demo bar is drawn above every route by [DemoFrame].
      body: IndexedStack(
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
      // "Talk to Accnomos" (the Ask screen as a full-screen sheet, with
      // hands-free). Not on Review, where Approve/Edit/Reject sit at the
      // bottom, nor on a business's Ask tab, which is the same screen.
      floatingActionButton: showAssistantButton(household: _household, tab: _tab)
          ? const AssistantButton()
          : null,
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: _selectTab,
        destinations: shellDestinations(household: _household),
      ),
    );
  }
}

/// Whether the tab shows the "Talk to Accnomos" button: every tab but Review
/// (index 1) and a business's own Ask tab (index 2).
bool showAssistantButton({required bool household, required int tab}) =>
    tab != 1 && (household || tab != 2);

/// Opens the assistant: Ask with hands-free, as a full-screen sheet.
class AssistantButton extends StatelessWidget {
  const AssistantButton({super.key});

  @override
  Widget build(BuildContext context) => FloatingActionButton.extended(
        heroTag: 'assistant',
        tooltip: 'Talk to Accnomos — ask by voice or chat',
        backgroundColor: AccnomosColors.teal,
        foregroundColor: Colors.white,
        onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
          fullscreenDialog: true,
          builder: (_) => const AskScreen(asSheet: true),
        )),
        icon: const Icon(Icons.record_voice_over_outlined),
        label: const Text('Talk'),
      );
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
            onPressed: () {
              appNavigatorKey.currentState?.popUntil((r) => r.isFirst);
              Demo.end();
            },
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
