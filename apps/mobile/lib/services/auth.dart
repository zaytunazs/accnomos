import 'package:msal_auth/msal_auth.dart';

/// Which kind of Microsoft account is signed in. Personal accounts keep the
/// books in the OneDrive app folder; work accounts use `/Accnomos` instead,
/// and need the broader `Files.ReadWrite` scope (AppFolder is MSA-only).
enum AccountKind { personal, work }

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

  /// Account kind of the last authentication result (personal by default).
  AccountKind get kind => _kind;

  Future<SingleAccountPca> _pcaAsync() async {
    final existing = _pca;
    if (existing != null) return existing;
    final pca = await SingleAccountPca.create(
      clientId: clientId,
      androidConfig: AndroidConfig(
        configFilePath: 'assets/msal_config.json',
        redirectUri: redirectUri,
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
    final pca = await _pcaAsync();
    final result = await pca.acquireToken(scopes: personalScopes);
    _record(result);
    return result.account;
  }

  /// Extra scopes for sending an invoice from the user's Outlook. Asked for
  /// only when the user first taps Send in the confirmation dialog, mirroring
  /// the web's `mailSendScopesFor` — never at sign-in.
  static const mailSendScopes = ['Mail.Send'];

  /// Extra scope for reading the inbox on the Home tab. Asked for only when
  /// the user first taps "Check inbox" — never at sign-in.
  static const mailReadScopes = ['Mail.Read'];

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

  /// Package name used in the MSAL redirect URI.
  static String get packageName => _packageName;

  Future<void> signOut() async {
    final pca = await _pcaAsync();
    await pca.signOut();
    _lastResult = null;
    _kind = AccountKind.personal;
  }
}
