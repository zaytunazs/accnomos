# HMRC production credentials: draft answers (VAT MTD)

Draft answers to HMRC's Developer Hub questions for production credentials, question by question, in the order of
HMRC's "Terms of use" page (https://www.tax.service.gov.uk/api-documentation/docs/terms-of-use, read 11 Nov 2026).
HMRC asks the same questions in the production-credentials request on the Developer Hub; re-read that page on the
day you apply, because HMRC changes it. The request must be finished within 6 months of starting it or HMRC deletes
the progress.

**Scope of this application: VAT (MTD) only.** MTD for Income Tax is not applied for: HMRC stopped accepting
production-credential requests for new 2026-27 quarterly-update products (Developer Hub notice, 15 Sep 2026). The
relay keeps Income Tax sandbox only whatever `HMRC_ENV` says, and the app offers the "File it yourself" files.

Legend: **Ready** = true of the product today, with the evidence named. **Owner** = something the owner must do or
decide before the answer is true. Do not submit an answer marked Owner until it is done. Answer from the product as it
is; do not claim anything it doesn't meet.

APIs to subscribe on the production application: VAT (MTD) 1.0 (obligations, submit, view, liabilities, payments;
`read:vat write:vat`) and, if wanted, Check a UK VAT number 2.0 (application-restricted, `read:vat`).

---

## About your organisation

### Organisation details

| Question | Draft answer | Status |
|---|---|---|
| Responsible individual (name, email) | The director of Zaytuna Business Services Ltd, who owns Accnomos. Name and email: *owner to fill* | **Owner** |
| Organisation URL | https://accnomos.com | Ready |
| Evidence of official registration (UK: UTR, VAT number, PAYE reference, Corporation Tax UTR or Companies House number) | Zaytuna Business Services Ltd: Companies House number and VAT registration number, *owner to fill from the company's records* | **Owner** |

### Marketing your software

| Question | Draft answer | Status |
|---|---|---|
| Do you use HMRC logos in your software, marketing or website? | No. The app and site name HMRC in words only (for example "Connect to HMRC"); no HMRC logo or crown is used. Check before submitting: `grep -ri "hmrc" apps/web/public` finds no logo files | Ready (re-check) |
| Do adverts in your software (including third-party adverts) meet UK advertising standards? | The software shows no adverts, its own or third-party | Ready |
| Do you only describe the software as "HMRC recognised", never "accredited" or "approved"? | Yes. Until HMRC lists it, Accnomos is not described as recognised either. Check the site and docs for "accredited"/"approved" before submitting; the landing page and `services/runtime/app/public_kb.md` must not say either about HMRC | **Owner** (one search before submitting) |
| Do you get customer consent before sharing personal data for marketing (ICO direct marketing guidance)? | Accnomos shares no customer data for marketing. The only marketing list is the operator's own early-adopter list, collected with an explicit consent tick whose wording is stored with each record (`docs/PRODUCTION.md` § 6, `/privacy`) | Ready |

## About your processes

### Development practices

| Question | Draft answer | Status |
|---|---|---|
| Do you follow HMRC's development practices guidance? | Yes: sandbox first; OAuth 2.0 authorisation code with PKCE; tokens never stored server-side; one relay holding the client secret; versioned `Accept` headers; fraud-prevention headers on every call; `Gov-Test-Scenario` only in the sandbox. `docs/HMRC.md`, `services/hmrc-relay/README.md` | Ready |
| Do you meet HMRC's error-handling specification? | The relay passes HMRC's status and `{code, message, errors}` back unchanged; 401/expired tokens trigger one refresh then a reconnect prompt; network failures are 502 with no retry storm; validation happens before sending (box 3 = 1 + 2, box 5 = abs(3 − 4), decimals). Tests: `services/hmrc-relay/tests/test_routes.py`, `test_hardening.py` | Ready (owner to read HMRC's current error-handling page once and confirm) |
| Web software meets WCAG 2.1 AA? | The web app is tested with axe-core in the Playwright suite (`apps/web/e2e`, `@axe-core/playwright`). An automated check is not a full WCAG audit | **Owner**: run a manual WCAG 2.1 AA check of `/vat` (keyboard only, screen reader, zoom 200 %) and note the result here |

### Service management practices

| Question | Draft answer | Status |
|---|---|---|
| How can customers or third parties report security risks or incidents? | GitHub private vulnerability reporting on the repository (`docs/SECURITY.md` § Reporting a vulnerability) and the contact address on the site footer | **Owner**: add a `security.txt` (`apps/web/public/.well-known/security.txt`) with a monitored address and a "Report a security problem" line on `/privacy` |
| Do you have a process to notify HMRC immediately of security issues affecting customer data? | *Draft process:* whoever finds the issue tells the owner at once; the owner contains it (rotate `HMRC_PROD_CLIENT_SECRET`, `docker compose up -d relay`; take the relay down if tokens may be exposed); the owner emails HMRC's Software Developer Support Team (SDST) the same day with what happened, when, which APIs and how many users; then the ICO step below | **Owner**: write this as a one-page breach procedure (`docs/BREACH.md`), confirm HMRC's current contact address for security incidents on the Developer Hub, and keep it where it can be found in an emergency |
| Do you notify the ICO of personal data breaches within 72 hours? | Yes, as part of the same procedure: assess within 24 hours whether it is reportable; report to the ICO within 72 hours of becoming aware; tell affected users without undue delay when the risk is high | **Owner** (part of `docs/BREACH.md`; the company's ICO registration must be current) |

## About your software

### Handling personal data

| Question | Draft answer | Status |
|---|---|---|
| Do you comply with UK GDPR (what you process, why, your responsibility, lawful basis)? | `/privacy` says what is processed and why. The books are kept in the user's own OneDrive; the runtime and relay are stateless and store nothing about the user | Ready (owner to check `/privacy` names the lawful basis for HMRC filing: contract) |
| Are access tokens and personal data encrypted at rest and in transit? | In transit: HTTPS only (the relay refuses credentials over plain HTTP behind a proxy, `relay/security.py`). At rest: the relay stores no tokens; the user's HMRC tokens live only in the browser tab's `sessionStorage` and go when the tab closes; the books are in the user's OneDrive (encrypted at rest by Microsoft). **Gap:** `sessionStorage` is not itself encrypted | **Owner**: decide whether to accept and explain this (tokens never at rest on our side, tab-scoped, gone on close) or to encrypt them in the browser (Web Crypto, a non-extractable key per tab) before applying |
| Can each customer's data be reached only by that customer? | Yes: each request carries the user's own Microsoft token and HMRC token; there is no shared database and no cross-customer store. The demo is a separate in-memory sandbox per session | Ready |
| Employee access control (personnel security policy, role-based access)? | One operator (the owner). Server access is by SSH key; secrets only in the server's `.env` | **Owner**: write a short personnel security and access policy (who has server access, how keys are issued and removed, least privilege) |
| Can customers change, export or delete their data? | Yes: the books are files in their own OneDrive; Data export and Back up now in Settings; disconnecting HMRC clears the tab's tokens | Ready |
| Do you store customers' HMRC sign-in details? | No. OAuth 2.0: the user signs in on HMRC's own page; Accnomos never sees the password | Ready |

### Software security (SaaS only)

| Question | Draft answer | Status |
|---|---|---|
| Penetration testing (tools or an independent tester; NCSC guidance) | Not done yet | **Owner**: at least an OWASP ZAP baseline scan of `https://accnomos.com` and the relay (`docker run -t ghcr.io/zaproxy/zaproxy:stable zap-baseline.py -t https://api.accnomos.com -r zap-relay.html`, and the same for the web app), fix what it finds, save the reports in `docs/hmrc/`. An independent test is stronger evidence |
| Audit of security controls against the ICO information security checklist | Not done yet | **Owner**: work through the ICO checklist and save the answers in `docs/hmrc/` |

### Fraud prevention data (VAT MTD)

| Question | Draft answer | Status |
|---|---|---|
| Do you send fraud-prevention headers in line with the specification? | Yes, connection method `WEB_APP_VIA_SERVER` (web app via the relay; `MOBILE_APP_VIA_SERVER` is built for Android but the app does not file). Headers and their sources: `docs/HMRC.md`, `services/hmrc-relay/relay/fraud_headers.py` | Ready |
| Have you checked them with the Test Fraud Prevention Headers API? | Run `python tools/hmrc/fph_validate.py --relay https://api.accnomos.com` after a sandbox submission from the web app (the demo's VAT submit is one). It saves `docs/hmrc/fph-validation-YYYY-MM-DD.json` and `.md` | **Owner**: run it (it needs the live relay with sandbox credentials), fix any errors, commit the report |

### Customers authorising your software

| Question | Draft answer | Status |
|---|---|---|
| Where are the servers that process customer information? | *owner to fill*: the country (and provider) of the server behind `api.accnomos.com` (runtime and relay), and of the static site host. Customer books are in the customer's own Microsoft OneDrive (Microsoft's region for that account) | **Owner** |
| Privacy policy URL | https://accnomos.com/privacy | Ready (check it covers HMRC filing in production mode) |
| Terms and conditions URL | https://accnomos.com/terms | **Owner**: the page exists; have it reviewed so it covers live VAT filing (responsibility for the figures, the declaration, availability) before applying |

---

## Owner checklist (in order)

1. Fill the organisation details (responsible individual, Companies House number, VAT number).
2. Penetration test: OWASP ZAP baseline (web app and relay), reports into `docs/hmrc/`.
3. ICO information security checklist, answers into `docs/hmrc/`.
4. Breach notification process (`docs/BREACH.md`): HMRC immediately, ICO within 72 hours.
5. Security contact: `security.txt` and a line on `/privacy`.
6. Terms and conditions reviewed for live filing; privacy policy checked.
7. Decide on the browser token encryption gap.
8. Personnel security and access policy.
9. Manual WCAG 2.1 AA check of `/vat`.
10. Run `tools/hmrc/fph_validate.py` and commit the report.
11. Request production credentials (VAT MTD), then set `HMRC_ENV=production` and the `HMRC_PROD_*` variables on the
    relay (`docs/PRODUCTION.md` § 2).
