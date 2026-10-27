# HMRC (sandbox): connect and submit a VAT return from the web app

Sandbox only. The `/vat` page shows the live 9-box return, calculated by code from the ledger events you approved
(`GET /books/vat` on the runtime). Under it, **Connect to HMRC (sandbox)** lets you submit that return. AI proposes the
entries, you approve them, code calculates the boxes, and nothing is sent until you tick the legal declaration and press Submit.

Code: `apps/web/src/lib/hmrc.ts`, `apps/web/src/components/vat/ConnectHmrc.tsx`, relay in `services/hmrc-relay`.

## Flow

1. **Connect.** The browser makes a PKCE verifier (64 chars) and its S256 challenge, then calls
   `GET {RELAY}/hmrc/authorize?redirect_to=<origin>/vat&code_challenge=…` → `{url, state}`. `verifier` and `state` go into
   `sessionStorage["accnomos.hmrc.pending"]`, and the browser goes to HMRC's consent page (`url`).
2. **Consent.** You sign in on HMRC's site with a sandbox test user and grant `read:vat write:vat`. HMRC redirects to the
   relay's `/hmrc/callback`. The relay sends a 303 back to `/vat#code=…&state=…`. The code travels in the URL fragment, so it
   never reaches a server log.
3. **Exchange.** On load, `/vat` reads the fragment and immediately removes it with `history.replaceState`. It checks that
   `state` matches the pending one, then calls `POST /hmrc/exchange {code, state, code_verifier}`. The relay adds the client
   secret, and the tokens come back to the browser. They are stored in `sessionStorage["accnomos.hmrc"]` with `expires_at`.
4. **Obligations.** You enter the VRN. It is prefilled from `localStorage["accnomos.business.vrn"]`, or else from the
   onboarding VAT number. The page then calls `POST /vat/{vrn}/obligations` for the last 12 months. If an open obligation
   has the same dates as the live return, it is preselected. Otherwise you pick one.
5. **Confirm.** The confirmation card shows the 11-field body that will be sent. It is the runtime's `hmrc_body` under the
   obligation's `periodKey`, with `finalised: true`. Boxes 1–5 are pence and 6–9 whole pounds. The card also shows HMRC's
   declaration text and a checkbox that must be ticked.
6. **Submit.** `POST /vat/{vrn}/returns`. The relay checks box 3 = 1 + 2 and box 5 = |3 − 4| before calling HMRC, and
   returns 422 if they don't add up. The receipt card shows `processingDate`, `formBundleNumber`, `paymentIndicator`,
   `chargeRefNumber` (when present) and HMRC's correlation ID.
7. **Keep a copy.** `return.json` (body, period, ledger event IDs, declaration time) and `receipt.json` (HMRC response,
   correlation/receipt IDs, the fraud-prevention headers actually sent) are written to
   `06 VAT returns/<periodKey>/` in your OneDrive books folder through Microsoft Graph.

Tokens are refreshed through `POST /hmrc/refresh` a minute before `expires_at`. If refresh fails, the page forgets the
session and asks you to connect again. **Disconnect** clears `sessionStorage`.

The **Advanced: sandbox test scenario** box sets `Gov-Test-Scenario` (for example `QUARTERLY_NONE_MET`) on obligations
and submission calls. Leave it empty for HMRC's default sandbox response.

## Who holds what

| Where | Holds | Lifetime |
|---|---|---|
| Relay (`api.accnomos.com/hmrc`, `/vat`) | HMRC client ID and **client secret** only. Short in-memory caches: the app-restricted token, and 30 s of refresh results so racing refreshes share one HMRC call | Process memory; never on disk or in logs |
| Browser `sessionStorage` | HMRC access + refresh token, `expires_at`; PKCE verifier + state while the redirect is in flight | Until the tab closes or you press Disconnect |
| Browser `localStorage` | `accnomos.device_id` (random UUID for Gov-Client-Device-ID), `accnomos.business.vrn` | Until you clear site data |
| Your OneDrive | `06 VAT returns/<periodKey>/return.json` and `receipt.json` | Yours |

User tokens reach the relay only in the `X-HMRC-Access-Token` header of each request. The relay accepts browser calls
(CORS) only from the origins in `RELAY_ALLOWED_REDIRECTS`, plus `http://localhost` for development.

## Fraud-prevention headers (`WEB_APP_VIA_SERVER`, spec v3.3)

Each VAT call sends a JSON envelope `{client_facts, method: "WEB_APP_VIA_SERVER", gov_test_scenario?, …}`. The relay turns
the facts into `Gov-*` headers. The full table is in `services/hmrc-relay/README.md`.

| Header | Collected by | Source |
|---|---|---|
| Gov-Client-Device-ID | browser | UUID made once, `localStorage["accnomos.device_id"]` |
| Gov-Client-Multi-Factor | browser | `[]` (HMRC sign-in MFA isn't visible to us; Microsoft MFA isn't reported) |
| Gov-Client-Screens | browser | `screen.width/height`, `devicePixelRatio`, `screen.colorDepth` |
| Gov-Client-Timezone | browser | `UTC±HH:MM` from `getTimezoneOffset()` |
| Gov-Client-User-IDs | browser | `accnomos=` SHA-256 hex of the MSAL `homeAccountId` (never the raw ID or e-mail) |
| Gov-Client-Window-Size | browser | `innerWidth` × `innerHeight`, read at each call |
| Gov-Client-Browser-JS-User-Agent | browser | `navigator.userAgent` |
| Gov-Vendor-Version | browser + relay | `accnomos-web=0.1.0` plus `accnomos-relay=<HMRC_VENDOR_VERSION>` |
| Gov-Client-Public-IP / -Timestamp / -Port | relay | `X-Forwarded-For` / `X-Client-Port` set by the edge nginx (`deploy/nginx.conf`) |
| Gov-Vendor-Public-IP / -Forwarded / -Product-Name / Connection-Method | relay | settings and `method` |

A fact is omitted when the browser genuinely can't provide it; the app never sends placeholders. If anything is missing,
the relay lists it in `fraud_headers_missing`, and the page shows a quiet note under the card.

## Trying it

```sh
# relay on :8787 (HMRC_* in the environment, sandbox), runtime on :8780, web on :3000
curl -X POST http://localhost:8787/hmrc/test-user        # → userId, password, vrn
```

Open `http://localhost:3000/vat` while signed in with Microsoft and press **Connect to HMRC (sandbox)**. Sign in with the
test user's `userId` / `password`, then enter its `vrn`.
