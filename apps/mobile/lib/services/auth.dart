import 'package:msal_auth/msal_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'demo.dart';
import 'google_auth.dart';

/// Which kind of Microsoft account is signed in. Personal accounts keep the
/// books in the OneDrive app folder; work accounts use `/Accnomos` instead,
/// and need the broader `Files.ReadWrite` scope (AppFolder is MSA-only).
///
/// `google` is a Google account (Android "Continue with Google"): its books
/// live in the user's Google Drive and the runtime reads it from the
/// `X-Account-Kind: google` header.
enum AccountKind { personal, work, google }

/// Which sign-in the phone is using. Saved so it survives a restart; nothing
/// saved means Microsoft, so existing installs behave exactly as before.
enum AuthProvider { microsoft, google }

/// Microsoft sign-in via MSAL (public client, PKCE, no secret).
///
/// The client id is public configuration, not a secret: it ships as a
/// `--dart-define=MS_CLIENT_ID=...` default so release builds can override it.
/// Nothing is persisted here beyond what MSAL caches itself.
class AuthService {
  AuthService();

  /// Public client id of the Accnomos app registration.
  static const defaultClientId = 'f88eccde-6ec2-4302-b47b-e1844deba2e1';
  static const clientId = String.fromEnvironment(
    'MS_CLIENT_ID',
    defaultValue: defaultClientId,
  );

  /// Tenant id carried by personal Microsoft accounts (mirrors the web's
  /// `MSA_TENANT` in `apps/web/src/lib/msal.ts`).
  static const msaTenantId = '9188040d-6c67-4c5b-b112-36a304b66dad';

  /// Signature hash of the debug signing key. Release keys differ, so pass
  /// the real hash with `--dart-define=MSAL_SIG_HASH=...` (and the same value
  /// to Gradle with `-PmsalSignatureHash=...`).
  static const debugSigHash = '3NuO8lO3x1Q9/IdBwhH5qMZmiIU=';
  static const sigHash = String.fromEnvironment(
    'MSAL_SIG_HASH',
    defaultValue: debugSigHash,
  );

  /// `msauth://com.accnomos.app/<hash>`, with `/` and `=` URL-encoded.
  static String get redirectUri {
    final encoded =
        sigHash.replaceAll('/', '%2F').replaceAll('=', '%3D');
    return 'msauth://com.accnomos.app/$encoded';
  }

  /// iOS redirect URI: `msauth.<bundle id>://auth` (Info.plist registers the
  /// `msauth.com.accnomos.app` scheme).
  static const appleRedirectUri = 'msauth.$_packageName://auth';

  /// Work and personal Microsoft accounts, as `assets/msal_config.json`'s
  /// `AzureADandPersonalMicrosoftAccount` audience does on Android.
  static const appleAuthority = 'https://login.microsoftonline.com/common';

  /// Scopes for personal accounts (same plain names the web uses).
  static const personalScopes = [
    'User.Read',
    'Files.ReadWrite.AppFolder',
    'offline_access',
  ];

  /// Scopes for work accounts (AppFolder is MSA-only).
  static const workScopes = [
    'User.Read',
    'Files.ReadWrite',
    'offline_access',
  ];

  static List<String> scopesFor(AccountKind kind) =>
      kind == AccountKind.work ? workScopes : personalScopes;

  static const _packageName = 'com.accnomos.app';

  SingleAccountPca? _pca;
  AccountKind _kind = AccountKind.personal;
  AuthenticationResult? _lastResult;

  static const _providerKey = 'auth.provider';

  /// The signed-in provider, shared by every [AuthService] (screens each hold
  /// their own). Filled from storage by [_loadProvider] on first use.
  static AuthProvider _provider = AuthProvider.microsoft;
  static bool _providerLoaded = false;

  /// The saved provider (Microsoft until a Google sign-in).
  static AuthProvider get provider => _provider;

  static Future<void> _loadProvider() async {
    if (_providerLoaded) return;
    try {
      final prefs = await SharedPreferences.getInstance();
      _provider = prefs.getString(_providerKey) == 'google'
          ? AuthProvider.google
          : AuthProvider.microsoft;
      _providerLoaded = true;
    } catch (_) {
      // No storage on this platform (some tests): stay on Microsoft, retry next time.
    }
  }

  static Future<void> _saveProvider(AuthProvider value) async {
    _provider = value;
    _providerLoaded = true;
    try {
      final prefs = await SharedPreferences.getInstance();
      if (value == AuthProvider.google) {
        await prefs.setString(_providerKey, 'google');
      } else {
        await prefs.remove(_providerKey);
      }
    } catch (_) {}
  }

  /// Tests only: forget the loaded provider.
  static void resetProviderForTest([AuthProvider value = AuthProvider.microsoft]) {
    _provider = value;
    _providerLoaded = true;
  }

  /// Account kind of the last authentication result (personal by default).
  /// A demo's books sit where a personal account's would (the app folder).
  AccountKind get kind => Demo.active
      ? AccountKind.personal
      : _provider == AuthProvider.google
          ? AccountKind.google
          : _kind;

  /// The runtime's `X-Account-Kind` value: `personal`, `work` or `google`.
  String get accountKindHeader => switch (kind) {
        AccountKind.work => 'work',
        AccountKind.google => 'google',
        AccountKind.personal => 'personal',
      };

  /// The demo's stand-in account: every screen treats a running demo as
  /// signed in, and the session id goes where the Graph token would.
  static Account demoAccount(DemoInfo d) => Account(
        id: 'demo',
        username: d.user,
        name: d.business.isEmpty ? 'Demo' : d.business,
      );

  Future<SingleAccountPca> _pcaAsync() async {
    final existing = _pca;
    if (existing != null) return existing;
    final pca = await SingleAccountPca.create(
      clientId: clientId,
      androidConfig: AndroidConfig(
        configFilePath: 'assets/msal_config.json',
        redirectUri: redirectUri,
      ),
      // iOS reads no JSON: the authority and redirect are given here. The
      // redirect must be registered in Azure (iOS/macOS platform, bundle id
      // com.accnomos.app) — docs/IOS_APP_STORE.md. Microsoft Authenticator
      // brokers the sign-in when installed, Safari otherwise.
      appleConfig: AppleConfig(
        authority: appleAuthority,
        broker: Broker.msAuthenticator,
        redirectUri: appleRedirectUri,
      ),
    );
    _pca = pca;
    return pca;
  }

  void _record(AuthenticationResult result) {
    _lastResult = result;
    _kind = result.tenantId == msaTenantId
        ? AccountKind.personal
        : AccountKind.work;
  }

  /// Interactive sign-in. Returns the signed-in account.
  Future<Account> signIn() async {
    if (Demo.active) await Demo.end(); // a real sign-in ends the demo
    await _loadProvider();
    if (_provider == AuthProvider.google) await GoogleAuth.instance.signOut();
    final pca = await _pcaAsync();
    final result = await pca.acquireToken(scopes: personalScopes);
    _record(result);
    await _saveProvider(AuthProvider.microsoft);
    return result.account;
  }

  /// Interactive Google sign-in ("Continue with Google", Android). Returns the
  /// signed-in account, and remembers that Google is the provider.
  Future<Account> signInWithGoogle() async {
    if (Demo.active) await Demo.end();
    await _loadProvider();
    if (_provider == AuthProvider.microsoft && await _hasMicrosoftAccount()) {
      // One provider at a time on the phone.
      await (await _pcaAsync()).signOut();
      _lastResult = null;
      _kind = AccountKind.personal;
    }
    final account = await GoogleAuth.instance.signIn();
    await _saveProvider(AuthProvider.google);
    return account;
  }

  Future<bool> _hasMicrosoftAccount() async {
    try {
      await (await _pcaAsync()).currentAccount; // throws when nobody is signed in
      return true;
    } catch (_) {
      return false;
    }
  }

  /// A new Google access token after the runtime refused one with 401, or
  /// null when Google needs the user to sign in again. Silent.
  Future<String?> refreshGoogleToken(String? rejected) =>
      GoogleAuth.instance.refresh(rejected);

  /// Extra scopes for sending an invoice from the user's Outlook. Asked for
  /// only when the user first taps Send in the confirmation dialog, mirroring
  /// the web's `mailSendScopesFor` — never at sign-in.
  static const mailSendScopes = ['Mail.Send'];

  /// Extra scope for reading the inbox on the Home tab. Asked for only when
  /// the user first taps "Check inbox" — never at sign-in.
  static const mailReadScopes = ['Mail.Read'];

  /// Extra scope for listing Outlook contacts in Import contacts. Asked for
  /// only when the user opens that list — never at sign-in.
  static const contactsReadScopes = ['Contacts.Read'];

  /// Extra scope for saving a reply as an Outlook draft. Asked for only when
  /// the user first taps "Save draft in Outlook" — never at sign-in.
  static const mailReadWriteScopes = ['Mail.ReadWrite'];

  /// Extra scope for proposing a day plan. Asked for the first time the
  /// user plans a day — never at sign-in. Mirrors `CALENDAR_READ_SCOPES`.
  static const calendarReadScopes = ['Calendars.Read'];

  /// Extra scopes for applying a day plan to Outlook. Asked for only when
  /// the user confirms Apply — never at sign-in. Mirrors `CALENDAR_SCOPES`.
  static const calendarScopes = ['Calendars.ReadWrite'];

  /// Graph access token: silent first, interactive on `MsalUiRequiredException`.
  Future<String> token() async {
    final demo = Demo.current;
    if (demo != null) return demo.session;
    await _loadProvider();
    if (_provider == AuthProvider.google) return GoogleAuth.instance.token();
    final pca = await _pcaAsync();
    try {
      final result =
          await pca.acquireTokenSilent(scopes: scopesFor(_kind));
      _record(result);
      return result.accessToken;
    } on MsalUiRequiredException {
      final result = await pca.acquireToken(scopes: scopesFor(_kind));
      _record(result);
      return result.accessToken;
    } on MsalNoCurrentAccountException {
      final result = await pca.acquireToken(scopes: scopesFor(_kind));
      _record(result);
      return result.accessToken;
    }
  }

  /// Access token for extra [scopes] (e.g. [mailSendScopes]): silent first,
  /// interactive when consent is needed.
  Future<String> tokenFor(List<String> scopes) async {
    final demo = Demo.current;
    if (demo != null) return demo.session;
    await _loadProvider();
    // Google asks for every scope at sign-in, so the Microsoft scope names
    // here do not apply: the one Google token covers them.
    if (_provider == AuthProvider.google) return GoogleAuth.instance.token();
    final pca = await _pcaAsync();
    try {
      final result = await pca.acquireTokenSilent(scopes: scopes);
      _record(result);
      return result.accessToken;
    } on MsalUiRequiredException {
      final result = await pca.acquireToken(scopes: scopes);
      _record(result);
      return result.accessToken;
    } on MsalNoCurrentAccountException {
      final result = await pca.acquireToken(scopes: scopes);
      _record(result);
      return result.accessToken;
    }
  }

  /// The cached account, or null when nobody is signed in.
  Future<Account?> account() async {
    final demo = Demo.current;
    if (demo != null) return demoAccount(demo);
    await _loadProvider();
    if (_provider == AuthProvider.google) return GoogleAuth.instance.account();
    try {
      final pca = await _pcaAsync();
      return await pca.currentAccount;
    } on MsalException {
      return _lastResult?.account;
    }
  }

  /// Display name for the signed-in account (name, falling back to username).
  static String displayName(Account account) {
    final name = (account.name ?? '').trim();
    if (name.isNotEmpty) return name;
    return (account.username ?? '').trim();
  }

  /// The name in Home's "Hello, …": the first name, or during a demo the
  /// fictional household ("Harrison household") or business ("Bramblewood").
  static String greetingName(Account account) {
    final full = displayName(account);
    if (account.id != 'demo') return full.split(' ').first;
    final name = full
        .replaceAll(RegExp(r'\s*\(fictional\)\s*', caseSensitive: false), '')
        .replaceFirst(RegExp(r'^the\s+', caseSensitive: false), '')
        .trim();
    return (Demo.current?.household ?? false) ? name : name.split(' ').first;
  }

  /// Package name used in the MSAL redirect URI.
  static String get packageName => _packageName;

  Future<void> signOut() async {
    if (Demo.active) {
      await Demo.end();
      return;
    }
    await _loadProvider();
    if (_provider == AuthProvider.google) {
      await GoogleAuth.instance.signOut();
      await _saveProvider(AuthProvider.microsoft);
      return;
    }
    final pca = await _pcaAsync();
    await pca.signOut();
    _lastResult = null;
    _kind = AccountKind.personal;
  }
}
