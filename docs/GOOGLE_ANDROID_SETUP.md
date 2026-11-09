# Continue with Google on Android

The Android app (`apps/mobile`) can sign in with Google as well as Microsoft. The button is hidden unless the build is given a Google client id, so builds without it behave exactly as before.

## What the app sends

For a Google account every runtime call carries:

- `Authorization: Bearer <Google access token>` (also sent as `X-Graph-Token`, which the existing routes read)
- `X-Account-Kind: google`

Scopes, all asked for once at sign-in: `openid`, `email`, `profile`, `drive.file`, `gmail.readonly`, `gmail.compose`, `calendar.events`, `contacts.readonly` (full URLs in `apps/mobile/lib/services/google_auth.dart`).

The phone remembers the provider (`auth.provider` in app storage; nothing saved means Microsoft). Access tokens are not stored: the app asks Google Play services for a current one each time. On a 401 from the runtime it drops the refused token, gets a new one silently and retries once. If Google needs the user again (access withdrawn), the call fails and the user signs in again. Sign out (and Disconnect) signs out of Google and clears the saved provider. One provider at a time: signing in with one signs out of the other.

## 1. Google Cloud project

1. Create or pick a project in the [Google Cloud console](https://console.cloud.google.com/).
2. Enable the Drive, Gmail, Google Calendar and People APIs.
3. OAuth consent screen: add the scopes above. `gmail.readonly` and `gmail.compose` are restricted scopes: the app needs Google verification (and, for restricted scopes, a security assessment) before public release. Until then keep it in Testing with named test users.

## 2. Android OAuth clients (one per signing key)

Create an OAuth client of type **Android** for each key that signs a build users install. The package name is the same for all of them.

- **Package name:** `com.accnomos.app` (`applicationId` in `apps/mobile/android/app/build.gradle.kts`; the Kotlin `namespace` `com.accnomos.accnomos_mobile` is not what Google checks)

| Client | SHA-1 |
|---|---|
| Debug key (local `flutter run` / debug APK) | Print it with the command below. The shared dev key used for the Microsoft debug hash is `DC:DB:8E:F2:53:B7:C7:54:3D:FC:87:41:C2:11:F9:A8:C6:66:88:85`; confirm it matches your machine. |
| Upload key (a release build installed straight from the file) | Print it from `apps/mobile/android/upload-keystore.jks` (created by `tools/make_upload_key.ps1`). |
| Play app signing key (what users get from Google Play) | Play Console, Test and release, App integrity, App signing key certificate. It is `54:C9:BB:EE:D0:00:0D:EF:3F:51:9C:56:22:FA:9F:46:63:22:42:B0` (public; the same value `tools/build_release.ps1` converts to the MSAL hash). |

Print SHA-1s:

```powershell
# debug
keytool -list -v -alias androiddebugkey -keystore $env:USERPROFILE\.android\debug.keystore -storepass android -keypass android
# upload / release
keytool -list -v -alias upload -keystore apps\mobile\android\upload-keystore.jks
```

Google Play installs are re-signed by Play, so the Play app signing SHA-1 is the one that matters for the public release; without it sign-in fails with a configuration error ("This build's signature is not registered with Google yet").

## 3. Web client id (the server client id)

Create one more OAuth client of type **Web application** in the same project. Its client id (`<number>-<hash>.apps.googleusercontent.com`) is the `serverClientId` the Android sign-in needs; no secret is put in the app. The runtime's Google backend should use the same project. Client ids are public configuration.

## 4. Build with the client id

```powershell
# debug run
flutter run --dart-define=GOOGLE_SERVER_CLIENT_ID=<web-client-id>

# release bundle: the build script takes it as a parameter or from the environment
$env:GOOGLE_SERVER_CLIENT_ID = '<web-client-id>'
.\tools\build_release.ps1 -Tag 0.3.20-25
# or: .\tools\build_release.ps1 -Tag 0.3.20-25 -GoogleServerClientId <web-client-id>
```

`tools/build_release.ps1` adds `--dart-define=GOOGLE_SERVER_CLIENT_ID=...` only when a value is given and prints whether the Google button is in the build. Without it the button is hidden: the choice is deliberate, so a build with no Google registration cannot show a button that fails.

## 5. Check

1. Install the build on an Android phone with Google Play services and a Google account.
2. Welcome (and Settings, Sign in) shows **Continue with Google** beside **Sign in with Microsoft**.
3. Tap it, pick an account, accept the consent screen. The app opens on that account's books.
4. Kill and reopen the app: still signed in as Google, with no prompt.
5. Settings, Sign out: back to Welcome; Microsoft sign-in still works.

## Known gaps

- Screens that read or write books through Microsoft Graph directly on the phone (Files, Calendar view, photo upload from Capture) are Microsoft-only for now; they need Drive/Calendar equivalents or runtime endpoints before they work for a Google account. Runtime calls (`/books/*`, Ask, Review and the rest) go through the runtime with the contract above.
- Not tested on a device or emulator: needs a real OAuth client registration.
