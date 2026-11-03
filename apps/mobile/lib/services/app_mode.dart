import 'package:flutter/foundation.dart';

import 'auth.dart';
import 'books.dart' show booksClient;
import 'demo.dart';
import 'settings.dart';

/// Which treatment the app shows: the business app or the household one.
///
/// Signed in, it follows the books' profile (`GET /profile` `kind`,
/// services/runtime/app/profile.py), the same way the More tab already
/// follows its `features`: personal books get the household tabs (Home ·
/// Review · Budget · Goals · More) and a household Home; every business kind
/// keeps the business app unchanged. Signed out, the app opens on Welcome
/// (screens/welcome_screen.dart); a live demo counts as signed in, with the
/// demo books' own profile deciding the treatment.
@immutable
class ModeState {
  const ModeState({
    this.signedIn = false,
    this.kind,
    this.sample = 'company',
    this.loaded = true,
  });

  final bool signedIn;

  /// False only until the first [AppMode.refresh] at launch has answered:
  /// the app shows its brand splash instead of guessing signed in or out.
  final bool loaded;

  /// `company`, `sole_trader`, `personal`, … from `GET /profile`; null while
  /// unknown (signed out, offline or an older runtime).
  final String? kind;

  /// Signed out only, for the screens' own signed-out fallbacks:
  /// `company` or `household`.
  final String sample;

  bool get household => signedIn ? kind == 'personal' : sample == 'household';

  ModeState copyWith({bool? signedIn, String? kind, String? sample}) =>
      ModeState(
        signedIn: signedIn ?? this.signedIn,
        kind: signedIn == false ? null : (kind ?? this.kind),
        sample: sample ?? this.sample,
      );
}

class AppMode {
  AppMode._();

  static final ValueNotifier<ModeState> state =
      ValueNotifier(const ModeState(loaded: false));

  static bool get household => state.value.household;

  /// Signed out: show the company or the household sample.
  static void setSample(String sample) =>
      state.value = state.value.copyWith(sample: sample);

  /// Reads the account and the books' profile again (after sign-in, a
  /// profile switch, or a pull to refresh). Never throws: on any failure the
  /// app keeps what it knew, as the More tab does.
  static Future<void> refresh() async {
    // Never notify during the caller's build (the shell calls this from
    // initState): the first change lands after the current frame's work.
    await Future<void>.value();
    final auth = AuthService();
    try {
      final demo = Demo.current;
      if (demo != null) {
        // The demo's kind is known before the profile answers.
        state.value = ModeState(
            signedIn: true,
            kind: demo.household ? 'personal' : (state.value.kind ?? 'company'),
            sample: state.value.sample);
      }
      final account = await auth.account();
      if (account == null) {
        state.value = state.value.copyWith(signedIn: false);
        return;
      }
      final settings = await AppSettings.load();
      String? kind;
      try {
        final profile =
            await (await booksClient(settings, auth, account)).booksProfile();
        kind = profile['kind']?.toString();
      } catch (_) {
        kind = state.value.kind;
      }
      state.value = ModeState(
          signedIn: true, kind: kind, sample: state.value.sample);
    } catch (_) {
      // No MSAL on this platform, or no account: signed out.
      state.value = state.value.copyWith(signedIn: false);
    }
  }

  /// Tests only.
  @visibleForTesting
  static void reset([ModeState value = const ModeState()]) =>
      state.value = value;
}
