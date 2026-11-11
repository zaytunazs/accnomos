# Accnomos on the Apple App Store

The Flutter app (`apps/mobile`) now has an iOS project. This page is the owner's checklist to get it signed, into
TestFlight and through App Review, plus the reasoning behind each choice. Researched and written 11 Nov 2026.

**What is and is not proven.** Everything here was written on Linux: **nothing has been compiled for iOS yet.**
`flutter analyze` and `flutter test` pass (Android untouched); the plists parse; the Xcode project was edited by hand
and checked for balance only. The first real proof is the unsigned CI job (`.github/workflows/ios.yml`, *build*) going
green on a Mac, then a TestFlight install on a real iPhone. Treat the Swift in `ios/Runner/AccnomosChannels.swift` as
unreviewed by a compiler until then.

## 1. What is in the iOS project

| Item | Value / file |
| --- | --- |
| Bundle id | `com.accnomos.app` (same as Android's applicationId) |
| Display name | Accnomos |
| Minimum iOS | **16.0**: msal_auth 3.5.3 needs iOS 16 (its podspec and Package.swift); google_sign_in_ios 6.4 needs 15, image_picker_ios 15, url_launcher_ios and shared_preferences_foundation 13, record_ios 12 |
| Devices | iPhone only (`TARGETED_DEVICE_FAMILY = 1`), portrait. iPad would need its own 13-inch screenshots and layout review; it can be added later |
| Plugins | Swift Package Manager (the Flutter 3.47 default; every plugin here ships a `Package.swift`), no Podfile |
| Icons | `ios/Runner/Assets.xcassets/AppIcon.appiconset`, generated from `apps/web/public/brand/zaytuna/icon.svg` (the Android/Play mark) by `tools/make_ios_icons.py`: full-bleed, no alpha. Launch screen: the mark on the deep brown, as Android |
| Info.plist | `ios/Runner/Info.plist`: usage strings for camera (receipt photos), photo library (choose a receipt), microphone (voice notes / spoken questions), contacts (Import contacts › Phone). No Face ID: the app does not use it. `ITSAppUsesNonExemptEncryption = false` (only the OS's HTTPS) |
| Entitlements | `ios/Runner/Runner.entitlements`: keychain group `$(AppIdentifierPrefix)com.microsoft.adalcache` (msal_auth requirement) |
| Privacy manifest | `ios/Runner/PrivacyInfo.xcprivacy` (section 6) |
| Google ids | `ios/Flutter/GoogleSignIn.xcconfig` (placeholders; section 3.2) |
| Platform channels | `ios/Runner/AccnomosChannels.swift`: the iOS twin of `MainActivity.kt`, same channel and method names |

**Platform channels on iOS.** The Android app talks to six channels of its own. On iOS:

| Channel | iOS behaviour |
| --- | --- |
| `accnomos/hmrc` takeCallback | Implemented: the `com.accnomos.app://hmrc/callback` URL from accnomos.com/auth/hmrc-app.html is caught by the scene/app URL callbacks (only that URL is claimed, so MSAL and Google still get theirs) |
| `accnomos/device` facts | Implemented: os_family `iOS`, os_version, manufacturer `Apple`, model identifier (e.g. `iPhone16,2`), colour depth 24, app version. HMRC's `Gov-Vendor-Version` product becomes `accnomos-ios` |
| `accnomos/tts` speak/stop | Implemented with AVSpeechSynthesizer, en-GB voice; `speak` completes when finished, as on Android |
| `accnomos/share` shareText | Implemented with the system share sheet. `getSharedFiles` returns an empty list: "share into Accnomos" needs an iOS Share Extension (follow-up task) |
| `accnomos/files` pickFile | Implemented with the document picker (copy, 6 MB cap, same errors as Android) |
| `accnomos/phone-contacts` listContacts | Implemented with the Contacts framework after the system prompt. `pickContact` is not implemented (no screen uses it) |

## 2. Owner steps, in order

1. **Apple Developer Program.** Enrol as the organisation (Zaytuna Business Services Ltd), not as an individual, so
   the seller name on the store is the company. Fee: **USD 99 per membership year, or local currency where
   available** ([Apple: membership details](https://developer.apple.com/programs/whats-included/)). Organisation
   enrolment asks for the company's legal identity (Apple verifies it; allow a few days).
2. **App ID** (Certificates, Identifiers & Profiles › Identifiers): explicit App ID `com.accnomos.app`.
   * Keychain Sharing needs no portal capability: team-prefixed keychain groups are allowed by any profile for the
     App ID, and the entitlement is already in the project.
   * **Sign in with Apple: not now.** See section 5 (Guideline 4.8) for why and for when it would be needed.
   * No push notifications, no associated domains (the HMRC callback uses a custom URL scheme).
3. **Certificates and profile** (for CI): create an **Apple Distribution** certificate (export it with its private
   key as a `.p12` from Keychain Access on any Mac, or create the CSR with `openssl` on Linux), and an **App Store**
   provisioning profile for `com.accnomos.app` using it.
4. **App Store Connect API key** (Users and Access › Integrations › App Store Connect API): role **App Manager**.
   Download the `.p8` once; note the key id and issuer id.
5. **GitHub secrets** (section 7): `IOS_DIST_CERT_P12_BASE64`, `IOS_DIST_CERT_PASSWORD`, `IOS_PROFILE_BASE64`,
   `APPLE_TEAM_ID`, `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_P8_BASE64` (base64 each file with `base64 -w0 file`).
6. **Azure (Microsoft Entra) redirect for iOS** (section 3.1).
7. **Google iOS OAuth client** (section 3.2), then the three GitHub *variables*.
8. **App Store Connect record** (section 8), privacy answers (section 6), age rating, review notes (section 9).
9. Push a tag `ios-0.3.19` (or run the workflow with *upload* ticked) → the build lands in **TestFlight**. Add
   yourself as an internal tester, install on a real iPhone and run the checks in section 10.
10. Submit for review.

## 3. Sign-in and callbacks

### 3.1 Microsoft (msal_auth)

* Redirect URI: **`msauth.com.accnomos.app://auth`**. In the Entra app registration
  `f88eccde-6ec2-4302-b47b-e1844deba2e1` (the same one Android and the web use): *Authentication › Add a platform ›
  iOS / macOS*, bundle id `com.accnomos.app`. Entra generates exactly that URI (msal_auth README, "iOS/macOS Setup -
  Azure portal"). **Owner step: not done yet.** Until it is, Microsoft sign-in on iOS fails with a redirect error.
* Code: `lib/services/auth.dart` passes `AppleConfig(authority: https://login.microsoftonline.com/common, broker:
  Broker.msAuthenticator, redirectUri: msauth.com.accnomos.app://auth)`. iOS reads no JSON;
  `assets/msal_config.json` stays Android-only. `common` matches the JSON's `AzureADandPersonalMicrosoftAccount`.
* Info.plist: URL scheme `msauth.$(PRODUCT_BUNDLE_IDENTIFIER)`; `LSApplicationQueriesSchemes` `msauthv2`, `msauthv3`
  (brokered sign-in through Microsoft Authenticator when installed, Safari otherwise).
* msal_auth 3.4+ handles the callback URL itself: no AppDelegate code is needed (README, "Handle callback").

### 3.2 Google (google_sign_in 7)

* **Owner step:** in Google Cloud project **`accnomos-514413`** (signed in as admin@zaytunauk.co.uk), *APIs &
  Services › Credentials › Create credentials › OAuth client ID › iOS*, bundle id `com.accnomos.app`. Google shows the
  client id `<n>-<hash>.apps.googleusercontent.com` and its reversed form `com.googleusercontent.apps.<n>-<hash>`.
  The consent screen and scopes are the ones already set up for Android (docs/GOOGLE_ANDROID_SETUP.md); the Web
  ("server") client stays the one the runtime trusts.
* Put the ids in `ios/Flutter/GoogleSignIn.xcconfig` (they are public, so committing them is fine), or set GitHub
  variables `GOOGLE_IOS_CLIENT_ID`, `GOOGLE_IOS_REVERSED_CLIENT_ID`, `GOOGLE_SERVER_CLIENT_ID` and let CI write the
  file. They feed `GIDClientID`, `GIDServerClientID` and the reversed-id URL scheme in Info.plist (google_sign_in_ios
  README, "iOS integration").
* The Dart side also needs `--dart-define=GOOGLE_IOS_CLIENT_ID=…` and `--dart-define=GOOGLE_SERVER_CLIENT_ID=…` (CI
  passes both when the variables exist). `GoogleAuth.available` shows "Continue with Google" on iOS only when both
  are present; otherwise the button stays hidden, exactly as an unconfigured Android build.

### 3.3 HMRC (VAT)

The relay's callback page hands the PKCE code to `com.accnomos.app://hmrc/callback`; Info.plist registers the
`com.accnomos.app` scheme and `AccnomosChannels.swift` keeps the URL for `takeCallback`. Safari asks "Open in
Accnomos?" the first time; that is expected. Nothing to configure at HMRC: the redirect registered there is the
relay's own HTTPS URL, unchanged.

## 4. Payments: the iOS app sells nothing (Guidelines 3.1.1 / 3.1.3)

**Today.** Accnomos has no published price, plan or subscription (the runtime's own knowledge base says so), and the
app has no purchase, price or upgrade link. There is nothing for 3.1.1 to catch. No billing or pricing link exists in
this branch, so nothing had to be hidden. `lib/services/store_policy.dart` adds `StorePolicy.purchaseLinksAllowed`
(false on iOS) for the "Plan & billing" entry another branch adds: **on iOS that entry must show plan status only:
no price, no button, no link, no "upgrade on our website" wording.** Merge note for that branch:
`if (StorePolicy.purchaseLinksAllowed) …link… else …status text…`.

**What the guidelines say** ([App Store Review Guidelines](https://developer.apple.com/app-store/review/guidelines/),
read 11 Nov 2026):

* 3.1.1: unlocking features or functionality within the app (e.g. subscriptions) must use in-app purchase.
* 3.1.3 intro: apps in 3.1.3 "cannot, within the app, encourage users to use a purchasing method other than in-app
  purchase, except for apps on the United States storefront".
* 3.1.3(b) Multiplatform Services: an app may give access to subscriptions bought on your website "provided those
  items are also available as in-app purchases within the app".
* 3.1.3(c) Enterprise Services: only if the app is sold directly "to organizations or groups for their employees or
  students"; "Consumer, single user, or family sales must use in-app purchase."
* 3.1.3(f) Free Stand-alone Apps: free companions to a paid web tool need no in-app purchase "provided there is no
  purchasing inside the app, or calls to action for purchase outside of the app", but the clause names only VoIP,
  cloud storage, email services and web hosting.
* 3.1.1(a): outside the US storefront, apps "may not include buttons, external links, or other calls to action that
  direct customers to purchasing mechanisms other than in-app purchase" unless they hold a regional StoreKit External
  Purchase Link entitlement.

**Honest reading for when Accnomos starts charging.** A bookkeeping app sold to sole traders and households is not
named in 3.1.3(f) and is not purely "enterprise" under 3.1.3(c) (personal books are consumer sales). Strictly,
3.1.3(b) lets the app honour a web subscription only if the same plan is also on sale in the app through in-app
purchase. Many business SaaS apps ship a free, purchase-free iOS companion and pass review, but that is reviewer
practice, not a rule we can cite. So, when a paid plan exists, choose one:

1. **Purchase-free companion (lowest effort, some risk).** Keep the iOS app free; no price, plan names with prices,
   links or "subscribe on the web" text anywhere in the app or its metadata; plan status only. Defensible as 3.1.3(f)
   in spirit (the books live in the customer's own OneDrive/Google Drive), but a reviewer can cite 3.1.3(b).
2. **Also offer in-app purchase** of the same plans (StoreKit, Apple's commission). Fully compliant under 3.1.3(b).
3. **Business-only plans** sold to firms for their staff/clients could rely on 3.1.3(c); personal plans could not.

**UK storefront (checked 11 Nov 2026).** No UK exception exists yet. The CMA designated Apple with strategic market
status in 2025 and on 30 June 2026 consulted on a steering conduct requirement that would let UK developers link to
payment options outside the App Store, with any Apple fee "fair and reasonable" and expected to be lower than current
App Store charges; the consultation closed 28 July 2026 and the CMA said it would decide "later this year"
([gov.uk, 30 Jun 2026](https://www.gov.uk/government/news/cma-consults-on-new-requirements-for-apple-and-googles-mobile-platforms);
[CMA consultation page](https://connect.cma.gov.uk/consultations/proposed-steering-cr-apple)). Apple called the
proposal "highly intrusive" ([MacRumors, 29 Jul 2026](https://www.macrumors.com/2026/07/29/app-store-uk-rules-highly-intrusive/)).
The commitments Apple did give the CMA (due to take effect from 1 April 2026) cover app review, ranking, developer data and
interoperability, not steering ([CMA blog, 10 Feb 2026](https://competitionandmarkets.blog.gov.uk/2026/02/10/improving-the-way-apple-and-google-deliver-app-store-services-and-enhancing-ios-interoperability-in-the-uk)).
No final decision was found on 11 Nov 2026. **Until Apple changes the UK guidelines, treat the UK like every
non-US storefront: no purchase links.** Re-check before adding any.

## 5. Login Services (Guideline 4.8) and account deletion (5.1.1(v))

4.8: apps that use a third-party login "to set up or authenticate the user's primary account with the app must also
offer as an equivalent option another login service" that limits data to name and email, lets the user hide their
email and does not track. Exempt, among others, when:

* "Your app is a client for a specific third-party service and users are required to sign in to their mail, social
  media, or other third-party account directly to access their content."
* "Your app is an education, enterprise, or business app that requires the user to sign in with an existing
  education or enterprise account."

**Assessment.** Accnomos has no account of its own. Signing in with Microsoft or Google *is* the connection to the
user's own OneDrive / Google Drive (where the books are kept), Outlook / Gmail, calendar and contacts; the runtime
keeps nothing server-side. That is the first exemption: an equivalent "privacy" login could not reach the user's
books at all. Work (Entra) accounts additionally fit the business/enterprise exemption. **Decision: no Sign in with
Apple now.** Put this reasoning in the review notes (section 9). **Risk:** Google is on Apple's list of example
social logins, so a reviewer may still raise 4.8. If that happens, reply with the exemption and the storage argument
first; only if Apple insists, the task is: add Sign in with Apple *plus* a storage option it can actually use
(e.g. books in the app's iCloud Drive container), which is a product change, not a button.

5.1.1(v) (in-app account deletion) applies when an app "supports account creation". Accnomos creates no account:
Settings › *Disconnect Accnomos* signs out and removes the device's sign-in, and the privacy page states nothing from
the books is stored server-side. Say so in the review notes too.

## 6. Privacy manifest and App Store privacy ("nutrition label")

**Manifests.** Flutter's engine and each plugin ship their own `PrivacyInfo.xcprivacy` (checked in the pub cache for
msal_auth, google_sign_in_ios, image_picker_ios, record_ios, url_launcher_ios and shared_preferences_foundation; the
last declares UserDefaults). The app's own manifest declares:

* `NSPrivacyTracking` false, no tracking domains.
* Required-reason APIs: UserDefaults `CA92.1` (the app's own settings), file timestamps `C617.1` (files inside the
  app's container). Declared conservatively: over-declaring is harmless; missing one gets an upload warning e-mail.
* Collected data (linked to the user, not tracking, purpose App Functionality): Other Financial Info, Photos,
  Emails, Other User Content, User ID, Device ID.

**App Store Connect answers (App Privacy).** Apple counts data as "collected" when it leaves the device and is kept
longer than needed to serve the request. The runtime keeps nothing, but (per accnomos.com/privacy) documents and
questions go to Meta's Model API, which may use them in Contributor mode, and HMRC's fraud-prevention headers carry
a device id and a hashed user id. Answer:

| Data type | Collected | Linked to user | Tracking | Purpose |
| --- | --- | --- | --- | --- |
| Financial Info › Other Financial Info | Yes | Yes | No | App Functionality |
| User Content › Photos or Videos (receipts) | Yes | Yes | No | App Functionality |
| User Content › Emails or Text Messages (inbox triage) | Yes | Yes | No | App Functionality |
| User Content › Other User Content (questions, notes) | Yes | Yes | No | App Functionality |
| Identifiers › User ID, Device ID (HMRC headers) | Yes | Yes | No | App Functionality |
| Contact Info, Contacts, Audio, Location, Usage, Diagnostics | No | | | |

Owner check: if the live server's AI is switched out of Meta's Contributor mode, or HMRC is not offered, revisit
the rows above and the manifest. Contacts and audio are processed but not kept (contacts go to the user's own books;
spoken questions are "converted then discarded"), so they are not "collected" in Apple's sense.

## 7. CI (`.github/workflows/ios.yml`)

* **build (unsigned):** every PR touching `apps/mobile/**` (and on demand): `flutter build ios --release
  --no-codesign` on `macos-latest` with the latest stable Xcode. No secrets.
* **testflight (signed):** a pushed tag `ios-*`, or *Run workflow* with *upload* ticked. Signing route: **manual
  `.p12` + provisioning profile imported into a temporary keychain** (GitHub's documented recipe), chosen over
  `fastlane match` because it needs no Ruby, no extra certificates repository and only GitHub secrets. A git-ignored
  `ios/Flutter/Signing.xcconfig` switches the Release build to manual signing; local Xcode builds keep automatic
  signing. `flutter build ipa` then `xcrun altool --upload-app` with the API key (Apple still documents altool and
  Transporter as upload tools: [Upload tools](https://developer.apple.com/help/app-store-connect/reference/upload-tools)).
  Build number = 1000 + workflow run number (App Store build numbers only go up). The IPA is kept 14 days as an
  artifact.
* **Xcode:** since 28 April 2026 uploads must be built with Xcode 26+ and the iOS 26 SDK
  ([Apple: upcoming requirements](https://developer.apple.com/news/upcoming-requirements/)); the workflow selects the
  latest stable Xcode on the runner.
* **Cost.** GitHub bills a private repository's macOS minutes at **$0.062/min against $0.006/min for Linux** (about
  10×), from included usage of $12 (Free) or $18 (Pro/Team) a month; standard runners on a public repository are free
  ([GitHub: Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)). One unsigned
  build is roughly 10–15 minutes, so each PR costs about $0.60–$0.90 on a private repo.
* **Alternative: Codemagic.** Personal accounts get **500 free macOS M2 build minutes a month** (reset on the 1st;
  not available to Teams; $0.095/min beyond) ([Codemagic pricing](https://docs.codemagic.io/billing/pricing/)).
  Codemagic has Flutter-native iOS signing and App Store Connect publishing built in; to switch, connect the repo,
  add the same certificate/profile/API key in its UI and use a `codemagic.yaml` with `flutter build ipa`. Keep the
  GitHub unsigned job or move it too.

## 8. App Store Connect listing

* **Name:** Accnomos. **Subtitle** (≤ 30 characters), e.g. "Bookkeeping & VAT, your cloud".
* **Primary category:** Finance; **secondary:** Business.
* **Privacy policy URL:** https://accnomos.com/privacy. **Support URL:** https://accnomos.com/help (or a contact
  page; it must work at submission, Guideline 2.1). **Marketing URL** (optional): https://accnomos.com.
* **Screenshots:** iPhone only. Required: at least one for **iPhone with Dynamic Island (medium)**, 1179 × 2556 or
  1206 × 2622 portrait, unless you supply the large sizes; providing **6.9-inch** (1320 × 2868, 1290 × 2796 or
  1260 × 2736) lets App Store Connect scale down for smaller iPhones. No alpha channel. iPad screenshots (13-inch,
  2064 × 2752 or 2048 × 2732) are needed only if iPad support is added
  ([Screenshot specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/)).
  Take them from the company demo in the iOS Simulator (iPhone 17 Pro Max) on a Mac.
* **Age rating:** answer Apple's updated questionnaire (all apps had to answer it by 31 Jan 2026,
  [upcoming requirements](https://developer.apple.com/news/upcoming-requirements/)). No violence, gambling, public
  user-generated content, messaging or open web browsing, so the lowest band is expected; where it asks about
  AI-generated content, answer truthfully (an assistant that answers questions about the user's own books).
* **Pricing:** Free. **Availability:** United Kingdom to start (the product is UK bookkeeping and MTD VAT).
* **Export compliance:** answered by `ITSAppUsesNonExemptEncryption = false`.

## 9. App Review notes and demo access

Guideline 2.1 asks for "an active demo account or fully-featured demo mode". Accnomos has a built-in demo that needs
no sign-in. Paste into *App Review Information › Notes*:

> Accnomos is bookkeeping and MTD VAT for UK small businesses and households. To review without an account, open the
> app and tap **Try the company demo** (a fictional joinery company) or **Try the personal demo** (a fictional
> household). Every screen then works on fictional sample books, marked "SAMPLE — FICTIONAL … demo data only" at the
> top; **Exit demo** returns to the start. The VAT screen can file to HMRC's *sandbox* test service, not the live
> one. Accnomos has no account of its own: "Sign in with Microsoft / Continue with Google" connects the user's own
> OneDrive or Google Drive, where their books are stored, and their Outlook/Gmail and calendar (Guideline 4.8: a
> client for a third-party service whose content the user signs in to reach; work accounts are also business
> accounts). Nothing from the books is stored on our servers, so there is no account to delete; Settings ›
> Disconnect Accnomos signs out and removes the sign-in from the device. The app sells nothing and has no paid plan.

* The demo needs the live runtime (`https://api.accnomos.com`) to be up during review, with `DEMO_MODE=1`
  (docs/DEMO.md). Check `curl https://api.accnomos.com/health` before submitting and keep it up until approval.
* If you also want to give a sign-in, create a throwaway personal Microsoft account with OneDrive opened once and put
  its email and password in *Sign-in information*. Not required when the demo covers everything.

## 10. First TestFlight checks (on a real iPhone)

1. App opens on the Welcome screen with the brand launch screen and icon.
2. Company demo and personal demo load; Exit demo works.
3. Capture: camera prompt shows the usage text; a photo is taken and read. Choose from library works.
4. Ask by voice: microphone prompt; spoken answer plays (TTS).
5. Bank › import a statement CSV/PDF through the document picker.
6. Contacts › Import contacts › Phone: contacts prompt, list appears.
7. Sign in with Microsoft (after section 3.1): Authenticator or Safari, back in the app; sign out works (proves the
   keychain group).
8. Continue with Google (after section 3.2).
9. VAT › connect HMRC sandbox: Safari, "Open in Accnomos?", back and connected.
10. Any CSV export opens the share sheet.

## 11. Known gaps and follow-ups

* Not compiled: Swift (`AccnomosChannels.swift`, `AppDelegate.swift`), the hand-edited `project.pbxproj`, and the
  SPM resolution of msal_auth/GoogleSignIn on a Mac. First green unsigned CI run settles these.
* Sharing files *into* Accnomos from other apps needs an iOS Share Extension (Android has an intent filter).
* iPad layout and screenshots (iPhone-only for now).
* `pickContact` (single contact picker) is not implemented on iOS; nothing calls it today.
* Revisit section 4 before introducing any paid plan, and section 6 if the AI provider or retention changes.
