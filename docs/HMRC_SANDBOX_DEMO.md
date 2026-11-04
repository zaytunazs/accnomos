# The demo files to HMRC's sandbox

In a demo session ("Try the demo", web and Android), the VAT card's **Connect to HMRC** talks to **HMRC's sandbox**, HMRC's
own test service, instead of simulating it. The badge says **"HMRC sandbox — real test service, no real tax filed"**, and
the card says that live filing needs HMRC's approval of Accnomos.

## The flow (web `apps/web/src/components/vat/ConnectHmrc.tsx` + `src/lib/hmrc.ts`; Android `lib/widgets/hmrc_filing.dart` + `lib/services/hmrc.dart`)

1. **Make an HMRC sandbox test user**: the app calls the relay's `POST /hmrc/test-user` (HMRC's Create Test User API,
   application-restricted, sandbox only). HMRC returns a fresh VAT-registered test organisation. The card shows its
   **User ID, password and VAT number**, each with a Copy button, as "HMRC sandbox test user — made just now for this demo".
   Web keeps it in this tab's sessionStorage (`accnomos.hmrc.demo-sandbox`); Android keeps it in memory for this demo
   session. Both drop it when the demo is reset or left. The password is never written to the books.
2. **Connect to HMRC sandbox**: the usual PKCE flow (`/hmrc/authorize` → HMRC's sandbox pages → `/hmrc/callback` →
   `/hmrc/exchange`). On HMRC's pages: *Continue* → *Sign in to the HMRC online service* → User ID and password →
   *Give permission*. Nothing else is asked.
3. **Show obligations / Get VAT periods from HMRC**: the test VRN's obligations from the sandbox. HMRC's default test data is
   two 2017 quarters (`18A1` fulfilled, `18A2` open), never the sample books' quarters, so the card says the return shown
   is sent under HMRC's period key and that for a real return the dates must match (web: the existing warning; Android: a
   notice, and only in this mode is a date mismatch allowed).
4. **Declaration tick, then Submit to HMRC sandbox** (a tap, never voice): the nine boxes computed by code from the demo
   ledger go to `POST /vat/{vrn}/returns` with the fraud-prevention headers (`WEB_APP_VIA_SERVER` on the web,
   `MOBILE_APP_VIA_SERVER` on Android). HMRC's receipt (processing date, form bundle number, payment indicator, charge
   reference, correlation ID) is shown as "Submitted to HMRC sandbox" and saved to the demo's books under
   `06 VAT returns/<period key>/` with `environment: "HMRC sandbox (demo, test user …)"`.

**Fallback.** If the relay can't make a test user (no sandbox credentials: 503; not pointed at the sandbox: 403; HMRC or the
relay unreachable; rate limited), the demo uses the old simulated flow, with its "Demo · HMRC simulated" badge and
"Demo — submission simulated" receipt, and the card says why. If HMRC's sign-in fails after a test user was made, the
card offers "Use the simulated flow instead". A simulated demo never calls the relay; the card never says "sandbox" then.

The runtime is unchanged apart from wording: it never calls HMRC (`GET /demo/session` now reports `simulated: ["mail"]`,
`hmrc: "sandbox"`). The relay is unchanged.

## Live check, 4 Nov 2026 (05:53 UTC)

Run once from the build container against the public relay (`https://api.accnomos.com`) and HMRC's sandbox, with a
headless browser on HMRC's real sandbox sign-in pages and the demo books' own Jul–Sep 2026 boxes (net VAT £3,807.33):

| Step | Result |
| --- | --- |
| `POST /hmrc/test-user` | 201, a test organisation (User ID `678648456871`, VRN `486438504`) |
| `/hmrc/authorize` (redirect to `http://127.0.0.1:5999/vat`, PKCE) | HMRC sandbox consent URL on `test-www.tax.service.gov.uk` |
| HMRC pages | `/oauth/start` (Continue) → `/oauth/whatYouWillNeed` (Sign in to the HMRC online service) → `/api-test-login/sign-in` (User ID, password only) → `/oauth/grantscope` (Give permission) |
| `/hmrc/callback` → `/hmrc/exchange` | 303 back with the code; exchange 200, scope `read:vat write:vat`, 4 h token |
| `POST /vat/486438504/obligations` | 200: `18A1` (2017-01-01 – 2017-03-31, fulfilled), `18A2` (2017-04-01 – 2017-06-30, open); `fraud_headers_missing: []` |
| `POST /vat/486438504/returns` (period `18A2`, finalised) | **201**: processingDate `2026-11-04T05:53:37.493Z`, formBundleNumber **`409715423288`**, paymentIndicator `DD`, chargeRefNumber `mzeEeAVbErCFvD3H`, correlation ID `ad2e5631-9d8e-481d-aa35-85fc471e7e07` |

What this proves: the live relay has sandbox credentials, makes test users, and carries the exact calls the new demo flow
makes, through HMRC's real sandbox sign-in, to a real sandbox receipt. What it does not: the new card itself on
`accnomos.com` or the phone, which runs only once this branch is deployed (the card is covered by
`apps/web/e2e/sandbox.spec.ts` and `apps/mobile/test/hmrc_vat_test.dart` against a stand-in relay with these shapes).

The check script lived outside the repository; it printed no password or token.
