import 'package:flutter/material.dart';

import 'app_mode.dart';
import 'demo.dart';

/// The app's one navigator, so the demo bar (above every route), sign-out
/// and the logo can close pushed screens.
final GlobalKey<NavigatorState> appNavigatorKey = GlobalKey<NavigatorState>();

/// Where the logo and sign-out take you, as on the website: the logo goes
/// Home; signing out goes to the Welcome page with nothing left behind it.
class AppNav {
  AppNav._();

  /// Bumped when the shell should show its Home tab ([goHome]).
  static final ValueNotifier<int> homeRequests = ValueNotifier(0);

  /// A tab the shell should show by name ("review", "ask", "vat", "budget",
  /// "goals"); a new request object each time, so asking twice still fires.
  static final ValueNotifier<TabRequest?> tabRequests = ValueNotifier(null);

  /// Show one of the shell's tabs (a summary line's action): pushed screens
  /// close first, as for the logo.
  static void openTab(String name) {
    appNavigatorKey.currentState?.popUntil((r) => r.isFirst);
    tabRequests.value = TabRequest(name);
  }

  /// The logo: close every pushed screen and show the Home tab. Signed out,
  /// the root is already the Welcome page.
  static void goHome() {
    appNavigatorKey.currentState?.popUntil((r) => r.isFirst);
    homeRequests.value++;
  }

  /// After a sign-out, switch account or disconnect: close every pushed
  /// screen (none is left saying "sign in to view") and show the Welcome
  /// page at once; then read the sign-in again in case another account is
  /// still there.
  static Future<void> signedOut() async {
    appNavigatorKey.currentState?.popUntil((r) => r.isFirst);
    AppMode.state.value = AppMode.state.value.copyWith(signedIn: false);
    await AppMode.refresh();
  }

  /// Exit demo, from the demo bar, More or Settings: close every pushed
  /// screen and end the demo; the launch gate then shows the Welcome page.
  static Future<void> exitDemo() async {
    appNavigatorKey.currentState?.popUntil((r) => r.isFirst);
    await Demo.end();
  }
}

/// One request to show a tab by name ([AppNav.openTab]).
class TabRequest {
  TabRequest(this.name);
  final String name;
}
