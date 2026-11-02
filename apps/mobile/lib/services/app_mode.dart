import 'package:flutter/foundation.dart';

import 'auth.dart';
import 'books.dart' show booksClient;
import 'settings.dart';

/// Which treatment the app shows: the business app or the household one.
///
/// Signed in, it follows the books' profile (`GET /profile` `kind`,
/// services/runtime/app/profile.py), the same way the More tab already
/// follows its `features`: personal books get the household tabs (Home ·
/// Review · Budget · Goals · More) and a household Home; every business kind
/// keeps the business app unchanged. Signed out, the visitor picks which
/// fictional sample to look at (Company sample / Household sample).
@immutable
class ModeState {
  const ModeState({this.signedIn = false, this.kind, this.sample = 'company'});

  final bool signedIn;

  /// `company`, `sole_trader`, `personal`, … from `GET /profile`; null while
  /// unknown (signed out, offline or an older runtime).
  final String? kind;

  /// Signed out only: `company` or `household`.
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
      ValueNotifier(const ModeState());

  static bool get household => state.value.household;

  /// Signed out: show the company or the household sample.
  static void setSample(String sample) =>
      state.value = state.value.copyWith(sample: sample);

  /// Reads the account and the books' profile again (after sign-in, a
  /// profile switch, or a pull to refresh). Never throws: on any failure the
  /// app keeps what it knew, as the More tab does.
  static Future<void> refresh() async {
    final auth = AuthService();
    try {
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
