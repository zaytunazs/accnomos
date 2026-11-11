import 'package:flutter/foundation.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:msal_auth/msal_auth.dart' show Account;
import 'package:shared_preferences/shared_preferences.dart';

/// Google sign-in for Android and iOS ("Continue with Google").
///
/// The runtime receives the Google access token as `Authorization: Bearer`
/// with `X-Account-Kind: google` (see [AuthService.accountKindHeader]). The
/// button is shown only when the build is given the web (server) OAuth client
/// id: `--dart-define=GOOGLE_SERVER_CLIENT_ID=<id>.apps.googleusercontent.com`.
/// It is public configuration, not a secret. See docs/GOOGLE_ANDROID_SETUP.md.
///
/// Access tokens last about an hour and are never stored: [token] asks Google
/// Play services for a current one each time, silently.
class GoogleAuth {
  GoogleAuth._();
  static final GoogleAuth instance = GoogleAuth._();

  /// Web application OAuth client id (the "server client id").
  static const serverClientId = String.fromEnvironment('GOOGLE_SERVER_CLIENT_ID');

  /// iOS OAuth client id (`--dart-define=GOOGLE_IOS_CLIENT_ID=<id>.apps.googleusercontent.com`).
  /// iOS needs its own client as well as [serverClientId]; Android does not use it.
  /// Public configuration, like the server id. See docs/IOS_APP_STORE.md.
  static const iosClientId = String.fromEnvironment('GOOGLE_IOS_CLIENT_ID');

  /// False unless the build was given [serverClientId]: the Google buttons stay hidden.
  static bool get configured => serverClientId.trim().isNotEmpty;

  /// Whether "Continue with Google" can work on [platform]: Android with the
  /// server client id; iOS with the iOS client id too; nowhere else.
  static bool supportedOn(TargetPlatform platform) => switch (platform) {
        TargetPlatform.android => configured,
        TargetPlatform.iOS => configured && iosClientId.trim().isNotEmpty,
        _ => false,
      };

  /// [supportedOn] for this phone.
  static bool get available => supportedOn(defaultTargetPlatform);

  /// The scopes the runtime's Google backend needs, asked for together at sign-in.
  static const scopes = <String>[
    'openid',
    'email',
    'profile',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/contacts.readonly',
  ];

  static const _kId = 'auth.google.id';
  static const _kEmail = 'auth.google.email';
  static const _kName = 'auth.google.name';

  bool _initialised = false;
  GoogleSignInAccount? _user;

  Future<void> _init() async {
    if (_initialised) return;
    final ios = defaultTargetPlatform == TargetPlatform.iOS && iosClientId.trim().isNotEmpty;
    await GoogleSignIn.instance.initialize(
      clientId: ios ? iosClientId.trim() : null,
      serverClientId: serverClientId.trim(),
    );
    _initialised = true;
  }

  /// Interactive sign-in: account picker, then one consent for every scope.
  Future<Account> signIn() async {
    await _init();
    final user = await GoogleSignIn.instance.authenticate(scopeHint: scopes);
    // Authorization is a separate step in google_sign_in 7: it returns the
    // access token and shows the consent screen when scopes are missing.
    await user.authorizationClient.authorizeScopes(scopes);
    _user = user;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kId, user.id);
    await prefs.setString(_kEmail, user.email);
    await prefs.setString(_kName, user.displayName ?? '');
    return Account(id: user.id, username: user.email, name: user.displayName);
  }

  /// The signed-in Google account as the app's account type, read from what
  /// was saved at sign-in (works offline); null when nobody is signed in.
  Future<Account?> account() async {
    final prefs = await SharedPreferences.getInstance();
    final id = prefs.getString(_kId);
    final email = prefs.getString(_kEmail);
    if (id == null || email == null) return null;
    final name = prefs.getString(_kName);
    return Account(
      id: id,
      username: email,
      name: (name == null || name.isEmpty) ? null : name,
    );
  }

  /// A current access token with every scope. Silent: when Google needs the
  /// user (access withdrawn, scopes missing) this throws so the caller can
  /// send them back to sign in, instead of a consent screen opening mid-request.
  Future<String> token() async {
    final tokenOrNull = await _silentToken();
    if (tokenOrNull == null) {
      throw StateError('Google sign-in has expired. Sign in with Google again.');
    }
    return tokenOrNull;
  }

  /// A fresh access token after the runtime answered 401, or null when Google
  /// needs the user to sign in again. [rejected] is the token that was refused;
  /// it is dropped from Play services' cache so the same one is not returned.
  Future<String?> refresh(String? rejected) async {
    try {
      await _init();
      if (rejected != null && rejected.isNotEmpty) {
        await GoogleSignIn.instance.authorizationClient
            .clearAuthorizationToken(accessToken: rejected);
      }
      return await _silentToken();
    } catch (_) {
      return null;
    }
  }

  Future<String?> _silentToken() async {
    await _init();
    var user = _user;
    if (user == null) {
      // After a restart: reconnect to the account Google remembers.
      user = await GoogleSignIn.instance.attemptLightweightAuthentication();
      if (user == null) return null;
      _user = user;
    }
    final authz = await user.authorizationClient.authorizationForScopes(scopes);
    return authz?.accessToken;
  }

  /// Sign out of Google on this phone and forget the saved account. Never throws.
  Future<void> signOut() async {
    _user = null;
    try {
      await _init();
      await GoogleSignIn.instance.signOut();
    } catch (_) {
      // Already signed out, or Play services unavailable: nothing to undo.
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_kId);
    await prefs.remove(_kEmail);
    await prefs.remove(_kName);
  }
}
