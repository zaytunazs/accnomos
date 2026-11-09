# Google sign-in and Google Drive: owner set-up

Accnomos can keep a user's books in **their own Google Drive** instead of OneDrive. Nothing about the user is stored
by Accnomos: the web app (and the Android app) hold the Google access token, and every runtime call carries it.
This page is what the owner of the Google Cloud project has to do once. It needs no secret in the repo: both client
ids are public.

## What the app asks for

One scope list, shared by the web app, the Android app and the runtime:

| Scope | Google's class | Used for |
|---|---|---|
| `openid`, `email`, `profile` | non-sensitive | who is signed in (runtime: `https://openidconnect.googleapis.com/v1/userinfo`) |
| `https://www.googleapis.com/auth/drive.file` | non-sensitive | the `Accnomos` folder in My Drive; only files the app made. The full `drive` scope is never requested |
| `https://www.googleapis.com/auth/gmail.readonly` | **restricted** | intake of bills from Gmail, inbox triage, "people who email you" |
| `https://www.googleapis.com/auth/gmail.compose` | **restricted** | reply drafts; sending invoices and reminders the user confirmed |
| `https://www.googleapis.com/auth/calendar.events` | sensitive | day planner, deadlines as events |
| `https://www.googleapis.com/auth/contacts.readonly` | sensitive | import contacts |

Check each scope's class again in the console (*Google Auth Platform › Data Access*) when you add it: Google shows
the class next to it, and that is what verification is judged on.

## 1. Google Cloud project

1. <https://console.cloud.google.com> › create a project (e.g. `accnomos`), owned by the Zaytuna Business Services
   Ltd Google account rather than a personal one.
2. *APIs & Services › Library*: enable **Google Drive API**, **Gmail API**, **Google Calendar API** and
   **People API** (contacts).

## 2. OAuth consent screen (Google Auth Platform)

1. *Branding*: app name **Accnomos**, support email, logo (optional until verification), app home page
   `https://accnomos.com`, privacy policy `https://accnomos.com/privacy`, terms `https://accnomos.com/terms`,
   authorised domain `accnomos.com` (verify it in Search Console if asked).
2. *Audience*: user type **External**; publishing status **Testing**.
   * Testing allows **up to 100 test users**, each added by email under *Test users*. Only they can sign in.
   * A test user's authorisation **expires 7 days after consent** (for anything beyond name/email/profile), so
     testers sign in again weekly. Google also shows a "this app is in testing" warning before consent.
3. *Data Access*: add the scopes in the table above.

### Before a public launch (publishing status: In production)

* **Sensitive scopes** (`calendar.events`, `contacts.readonly`) need **Google's app verification** (brand, domain,
  privacy policy, a demo video of each scope in use, a written justification per scope).
* **Restricted scopes** (`gmail.readonly`, `gmail.compose`) need that verification **plus a CASA security
  assessment** by a Google-approved assessor, and both are **renewed every year**. Google emails about 90 days
  before the due date; put your own reminder in the calendar too. Budget weeks, not days, for the first one.
* Until verified, an app in production with these scopes shows the "unverified app" screen and is capped at
  100 users in total, a cap that cannot be reset.
* The privacy page (`apps/web/src/app/privacy/page.tsx`) already carries the Limited Use statement Google requires
  for restricted scopes; keep it in step with what the app does.
* Cheaper path if the CASA cost is not worth it at launch: ship Google sign-in with Drive only (non-sensitive, no
  verification needed beyond branding) and add Gmail/Calendar/Contacts later. That means dropping the restricted
  and sensitive scopes from the shared list in the web app (`apps/web/src/lib/google.ts`) and the Android app.

## 3. Web client id

*Clients › Create client › Web application*, name `Accnomos web`:

* **Authorised JavaScript origins**: `https://accnomos.com`, `http://localhost:3000` (and `http://127.0.0.1:3000`
  if you use it). The web app uses the Google Identity Services token client (pop-up), so **no redirect URI** is
  needed.
* Copy the client id (`…apps.googleusercontent.com`). It is public.
* GitHub › repo › *Settings › Secrets and variables › Actions › Variables*: add **`GOOGLE_CLIENT_ID`** with it.
  `.github/workflows/deploy-web.yml` passes it to the build as `NEXT_PUBLIC_GOOGLE_CLIENT_ID`; while the variable is
  empty, the site shows no "Continue with Google" button.
* Local development: `NEXT_PUBLIC_GOOGLE_CLIENT_ID=… pnpm dev` in `apps/web`.

The site's CSP (`apps/web/public/.htaccess`) already allows `accounts.google.com` (script, frame, connect),
`www.googleapis.com` and `openidconnect.googleapis.com` (connect).

## 4. Android client id

*Clients › Create client › Android*, name `Accnomos Android`:

* **Package name**: `com.accnomos.app` (`applicationId` in `apps/mobile/android/app/build.gradle.kts`).
* **SHA-1 certificate fingerprint**: one client per signing key. For the debug key:
  `keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android -keypass android`.
  For release, the **Play App Signing** key's SHA-1 from Play Console › *Setup › App signing* (not your upload key),
  plus the upload key's if you install release builds outside Play.
* The Android app also needs the **web** client id (as the server client id) for some sign-in flows; use the one
  from step 3.

## 5. Runtime

Nothing to configure. The runtime accepts the Google token in `X-Graph-Token` (or `Authorization: Bearer`) with
`X-Account-Kind: google` (`services/runtime/app/accounts.py`), uses Google Drive for the books
(`packages/connectors/src/accnomos_connectors/google_drive.py`) and Google's userinfo for identity. CORS already
allows the `Authorization` header.

Not available for Google accounts yet (clear 400 messages): sharing books with an accountant, and linked or shared
Microsoft mailboxes. Gmail, Calendar and Contacts answer 501 until `accnomos_connectors.google_workspace` is merged.

## Known limits

* **Concurrency on Drive is emulated**: Drive v3 has no reliable If-Match on content updates, so a write that must
  not overwrite another's checks the file's version first; a second writer landing in that one round trip wins.
  Two devices creating the same new file at the same instant can leave two files with one name; every reader then
  uses the oldest. See the docstring of `google_drive.py`.
* **Web sessions last an hour at a time**: the token model gives no refresh token. The web app renews silently
  (`prompt: "none"`) shortly before expiry; when Google or the browser will not allow that, the user is asked to
  sign in with Google again.
