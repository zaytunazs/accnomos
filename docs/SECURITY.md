# Security

Accnomos is a hackathon project. This page says what the public API protects, what it deliberately does not,
and how to report a problem. Deployment hardening is in [`deploy/README.md`](../deploy/README.md).

## Threat model

- Public API on `api.accnomos.com`: front proxy (TLS) → tunnel → edge nginx → two stateless services.
- **No server state and no accounts** (one opt-in exception: the operator's early-adopter list, below).
  Every request carries the caller's own credentials in headers:
  `X-Graph-Token` (Microsoft Graph, the user's OneDrive/Outlook), `X-Meta-Api-Key` (bring-your-own AI key),
  `X-HMRC-Access-Token` (HMRC MTD). The books live in the user's own cloud folder.
- The **relay** is the one component with a secret (the HMRC client secret, from the environment).
- Attackers we design for: anonymous internet clients, malicious documents (receipts, mail attachments, bank CSVs)
  that reach the model, and a hostile web page in the user's browser.

## What is protected, and where it is checked

| Area | Protection | Code | Test |
|---|---|---|---|
| Secrets in logs | Every log record is scrubbed as it is created (any logger, exception text included): credential header values, `Bearer …`, JWTs, `access_token`/`refresh_token`/`client_secret`/`code_verifier` fields, the OAuth `?code=` in the relay's access log, the exact credential values of the request being served, and the server's own keys by value (`META_API_KEY`, `MODEL_API_KEY`, `BASETEN_API_KEY`, `COMPANIES_HOUSE_API_KEY`, `ACTIONS_SIGNING_KEY`; relay `HMRC_CLIENT_SECRET`). Records keep their shape where possible, so uvicorn's access log still formats | `app/security.py`, `relay/security.py` | `test_security.py`, `test_hardening.py`, `test_scrub_removes_the_servers_own_keys` |
| Secrets in responses | Unhandled errors → `500 {"detail", "correlation_id"}`, no stack trace or exception text; Graph, HMRC and model-provider error messages (`/extract` 502) are scrubbed | same, `main.py` handlers, `routes_extract.py` | same, `test_extract_502_never_quotes_the_callers_key` |
| Token size | Credential headers over 8 KB → 431 | security middleware | same |
| Transport | When a proxy sends `X-Forwarded-Proto`, credentials over anything but `https` → 400; HSTS at the edge and on the static site | middleware, `deploy/nginx.conf`, `.htaccess` | same, `test_deploy_hardening.py` |
| Abuse | Per-IP token bucket, 60/min by default (`RATE_LIMIT_PER_MIN`), 429 + `Retry-After`; `/health` and preflights exempt | middleware | same |
| Body size | 25 MB on `/extract`, `/books/ask/voice`, `/books/bank/import`; 2 MB on `/invoices/profile/logo`; 256 KB everywhere else (relay: 256 KB); by `Content-Length` and by counting streamed bytes; nginx has a location for every route allowed more than 256 KB | middleware, nginx | same, `test_edge_nginx_lets_every_upload_route_through_at_the_runtimes_cap` |
| Documents | Every file is typed from its bytes and checked before decoding: 25 MB, 50 million pixels (from the image header: image bombs cost nothing), 20 PDF pages, a rendered PDF page at most 2,400 px a side whatever size the page claims; text with NUL bytes refused; document and email text goes to a model between markers as data, the markers stripped from the text. A refused file becomes a needs-a-look card (Inbox), a 422 (`/extract`), or is not copied (Outlook intake, over 25 MB); a file over 25 MB in the Inbox is never downloaded | `app/formats.py`, `inbox.py`, `intake.py`, `routes_extract.py` | `test_security_formats.py` |
| Outbound calls | Every httpx client (Graph, Meta, Ollama, SAM, HMRC) has an explicit timeout | each client | `test_every_outbound_http_client_has_a_timeout` |
| SSRF | A browser can only point the runtime at AI base URLs the server already knows (`OLLAMA_BASE`, `MODEL_API_BASE`, `AI_ALLOWED_BASE_URLS`); no AI client follows redirects. The only hosts called are Graph, those AI base URLs, Baseten (`BASETEN_BASE`, verifier in key mode) and, from the browser, the relay. Every request URL is built from one of those bases: nothing in a document, email, to-do or model reply is ever fetched. The Graph token is only sent to `https://graph.microsoft.com/` (a `nextLink`, `deltaLink` or cursor elsewhere is refused) | `app/ai/config.py`, `main.py`, `msgraph.py` | `test_unknown_ai_base_url_refused`, `test_only_known_modules_can_make_http_calls`, `test_every_runtime_http_call_goes_to_an_allow_listed_base_and_follows_no_redirects`, `test_the_token_never_follows_a_link_off_graph` |
| CORS | Exact origins from `CORS_ORIGINS` / `RELAY_ALLOWED_REDIRECTS`; wildcards refused at start-up; explicit methods (exactly those the routes use) and headers; preflight cached 10 min; no cookies | `main.py`, `relay/main.py` | `test_cors_*` |
| File names | Uploaded and model-derived names cannot escape the user's folder: `.`/`..`, separators, absolute and drive paths, control characters refused (`check_name`); `Books.free_path` and the Graph provider refuse unsafe segments as a backstop | `app/validation.py`, `books.py`, `msgraph.py`, `pipeline.py` | `test_validation.py` |
| Request bodies | Every JSON body forbids unknown fields (runtime and relay, including HMRC client facts) and every free-text string in it has a length cap, checked over every registered route. HMRC client facts: every string and list is capped, and the two sent to HMRC unencoded (device id, browser user agent) must be printable ASCII. Dates are `YYYY-MM-DD` only (`Day`: no timestamps or datetimes); money is whole pence as an integer (`Pence`: no `12.0`, `"12"` or `true`). Totals a client sends for an invoice are refused, not ignored. Files read back from the user's folder are parsed leniently, so a hand-edited file still opens | `app/validation.py`, route models | `test_every_request_body_forbids_unknown_fields`, `test_every_free_text_field_in_a_body_has_a_length_cap`, `test_dates_and_money_are_parsed_strictly`, relay `test_unknown_or_malformed_fields_rejected`, `test_client_facts_are_capped_and_header_safe` |
| Identity | Every route that writes takes `X-User` (`require_user`), except a short list where the write is an agent's or derived (scan, rebuild, a rendered PDF), each with its reason in the test. Audit lines say `user:<email>` or `agent:<name>`, never a bare address. The Graph token is the only authority: storage is the token's own OneDrive and no route takes an id that selects another one. Every route answers 401 without `X-Graph-Token` except five, each listed with its reason (`/health`, `/ai/test`, `/extract`, `/lookup/status`, `/books/bank/coding-options`) | `routes_*.py`, `books.py` | `test_every_write_route_needs_x_user_or_is_listed_with_a_reason`, `test_every_audit_actor_is_user_or_agent`, `test_every_route_but_the_public_ones_needs_a_graph_token` |
| Signed actions | Chat and voice actions are HMAC-signed over every field with a key from `ACTIONS_SIGNING_KEY` and the caller's Graph token (plus `X-Test-Tenant` in test mode), compared in constant time, expire after 15 min. An action id executes once: the claim is an If-Match (or, for a new month's log, create-only) write, so two approvals at once run once and a replay returns the first result. A run that died leaves an `approving` line that is never re-run; after 10 min rejecting the card clears it (`docs/ACTIONS.md`) | `app/actions.py`, `books.py` | `test_replaying_a_card_with_any_signed_field_changed_is_refused`, `test_two_approvals_at_once_execute_once`, `test_a_stale_approving_lock_is_never_rerun_and_rejecting_clears_it`, `test_in_test_mode_a_card_is_bound_to_its_tenant` |
| Outgoing mail and calendar | Invoices, reminders and calendar events are sent as plain text; a draft reply's text is HTML-escaped before it goes above Outlook's quoted thread; nothing is sent without `confirm: true` from the app's dialog, and a draft reply is only ever saved as a draft | `msgraph.py`, `routes_invoices.py`, `routes_mail.py` | `test_send_mail.py`, `test_mail.py`, `test_calendar.py` |
| Invoice logo and PDF | The logo must be a PNG or JPEG by its magic bytes (matching the declared type), at most 1 MB and 4000 px a side, and decode; it is saved under a name chosen from the bytes, and only `_System/Invoicing/logo.png` or `logo.jpg` is ever read back, whatever `profile.json` says. PDF text is Latin-1 with control characters removed, and fpdf's page-count alias cannot be typed | `routes_invoices.py`, `invoicing.py`, `pdf.py` | `test_logo_is_sniffed_decoded_and_size_checked`, `test_a_hand_edited_logo_path_is_not_read`, `test_pdf_text_cannot_use_fpdfs_page_count_alias` |
| Test mode | `ACCNOMOS_TEST_MODE=1` exactly turns on the fakes, the stub AI, `/__test/*`, `X-Test-Tenant` and its rate-limit exemption; with it unset, `0`, empty or anything else none of them exists. The Docker image pins it to `0`, and test mode refuses to start under `ACCNOMOS_IMAGE=1` or where the image's marker file `/etc/accnomos-image` exists (so `docker run -e` cannot turn it on); the e2e build writes `out-e2e/`, and the deploy workflow refuses an `out/` with test-mode code in it | `app/testmode.py`, `main.py`, `deploy/Dockerfile.runtime`, workflows | `test_without_the_flag_no_test_route_header_or_middleware_exists`, `test_docker_image_pins_it_off`, `test_test_mode_is_refused_where_the_image_marker_exists`, `test_the_test_mode_web_build_is_never_published` |
| Identifiers | VRNs: 9 digits on the relay; GB/XI + 9 or 12 digits, GD/HA on contacts. Period keys `^[A-Za-z0-9#]{4}$`. Proposal, event, bank-line, contact, job, mileage and action ids are hex-only, invoice numbers `[A-Z0-9-]` and pay-run periods `YYYY-MM`, before they touch a path | routes, `books.py`, `contacts.py`, `jobs.py` | `test_vrn_format`, `test_period_key_format`, `test_vat_period_key_format`, `test_contacts.py` |
| OAuth (relay) | `state` is HMAC-SHA256-signed with a key derived from the client secret, compared in constant time, expires after 10 min and is accepted once per step (callback, exchange); PKCE (S256) supported; tokens go back in the URL fragment with `Cache-Control: no-store` and `Referrer-Policy: no-referrer` | `relay/oauth.py`, `relay/routes.py` | `test_state_and_redirects.py` |
| Redirects (relay) | `redirect_to` must be an exact allowed origin (plus plain-http localhost for development); userinfo, backslashes, whitespace/control characters, other ports, scheme downgrades and look-alike hosts are refused | `relay/settings.py` | `test_redirect_bypass_attempts_refused` |
| Spreadsheets | Text that a spreadsheet would run as a formula (leading `=`, `+`, `-`, `@`, tab or carriage return; a number stored as text excepted) gets a leading apostrophe in `Books.xlsx`, the Reports export, the data-export CSVs and the payroll CSV | `projection.py` `_safe_text`, `data_export.py`, `payroll.py` | `test_books_xlsx_never_writes_text_as_a_formula`, `test_report_xlsx_writes_a_contact_name_as_text` |
| Static site | HSTS, `nosniff`, `Referrer-Policy`, `Permissions-Policy` (camera and microphone for the app itself only), `X-Frame-Options: DENY`, an enforced CSP (`frame-ancestors 'none'; base-uri 'self'; object-src 'none'`) and a full CSP in report-only mode whose `connect-src` lists the runtime/relay, Graph and its download hosts, and Microsoft sign-in | `apps/web/public/.htaccess` | `test_static_site_sends_security_headers`, `test_static_site_has_a_full_csp_in_report_only_mode` |
| Android | Camera, microphone, internet and network state only; no cloud backup (`allowBackup="false"`: settings hold the Meta key); only the launcher activity is exported by the app | `apps/mobile/android/app/src/main/AndroidManifest.xml` | `test_android_manifest_asks_for_little_and_is_not_backed_up` |
| Secrets in git | Every commit scanned with gitleaks and trufflehog before submission (third pass): no real secret. `.gitleaks.toml` allow-lists the three test fixtures, so `gitleaks git .` is clean | `.gitleaks.toml` | `docs/reviews/security-3/REVIEW.md` |
| Containers | Pinned bases, non-root, read-only root filesystem, no capabilities, healthchecks, loopback-only ports | `deploy/` | `test_deploy_hardening.py` |
| Correlation | Every response carries `X-Correlation-Id`; the same id is in the error body and the server log line | middleware | `test_every_response_has_a_correlation_id` |
| Early-adopter list | `POST /public/early-access` (no sign-in) answers 503 and creates no file unless `EARLY_ACCESS_ENABLED=1`; email shape-checked and lower-cased, every field length-capped, unknown fields refused; consent must be `true` with the exact stored wording; honeypot field answers success and keeps nothing; its own per-IP bucket (`EARLY_ACCESS_PER_MIN`, 5) on top of the global one; same answer for new and repeat addresses (no enumeration); file `0600` on the `runtime-data` volume, never in git or the image; CSV export defuses formula cells | `app/early_access.py`, `deploy/` | `test_early_access.py`, `test_early_access_list_lives_on_the_data_volume_only` |

## Early-adopter list (personal data the operator keeps)

People who sign up before the public launch (November 2026) get 3 months free and one email at launch. This is
marketing data held by the operator, separate from anyone's books, and handled under UK GDPR and PECR:

- **Controller:** Zaytuna Business Services Ltd (admin@zaytunauk.co.uk). No DPO is required at this size.
- **Collected:** email; optional name; business type (company / sole trader / personal / accountant); optional "how
  did you hear about us"; the consent flag and its exact wording (*"Email me once Accnomos launches, with my 3 months
  free. I can unsubscribe any time."*); the source page; the UTC time. No IP address is stored.
- **Why:** one launch email with the offer, and a count by business type. Nothing else, no sharing, no sale.
- **Lawful basis:** consent (UK GDPR Art. 6(1)(a)), by an unticked checkbox, separate from anything else. PECR
  reg. 22 needs consent for marketing email to individuals and to sole traders and non-limited partnerships; the
  same consent covers limited-company addresses, where PECR does not require it.
- **Retention:** deleted 12 months after launch (end of November 2027) unless the person became a customer.
- **Unsubscribe / erasure:** reply to the email or write to admin@zaytunauk.co.uk; the owner runs
  `python -m app.early_access delete --email …` (`docs/PRODUCTION.md` § 6), which removes every line for that address.
- **Where:** one JSON-lines file on the server's `runtime-data` volume, owner-only permissions; no web admin.
  The privacy page (`/privacy#early-access`) says all of the above, including the right to complain to the ICO.

## Out of scope for the hackathon

- **Authentication of callers.** There are no accounts: whoever holds a valid Graph/HMRC token can use it, as with
  the providers' own APIs. The runtime does not verify that `X-User` matches the Graph token's user; it is an audit
  label in the user's own files.
- **Distributed rate limiting.** The buckets are in memory, per process; a restart clears them, and several replicas
  would each allow the full rate. Same for the relay's spent-state set (hence one relay worker).
- **Prompt injection beyond file names.** A crafted document can still mislead the model's reading of amounts or
  suppliers. Every figure is checked by code and nothing is posted without the user's approval (or an Autopilot rule
  the user created), but the extraction itself is not adversarially robust.
- **Content-Security-Policy for the web app.** Enforced: frame, object and base restrictions only. The full policy
  (scripts, styles, `connect-src`) is sent in report-only mode until a release has run clean with it; scripts still
  need `'unsafe-inline'` because a static export has no nonces for Next.js inline scripts.
- **Data at rest.** The books are files in the user's OneDrive; their protection is Microsoft's and the user's.
- **Browser storage.** The AI key and HMRC tokens live in the user's browser storage (local / session); an XSS on the
  web origin could read them.
- Availability against volumetric attacks (left to the front proxy / Cloudflare), dependency scanning in CI
  (`pnpm audit` and `pip-audit` were run by hand in the third pass, both clean), and secret rotation automation.

## Accepted after the second pass

Each of these was looked at in the second review (invoices, actions, planner, triage, to-dos, payroll, folder
migration, test mode) and left as it is, for the reason given.

- **Test-mode tenants are picked by a header, whatever the token.** That is what lets parallel Playwright workers
  share one runtime. It exists only with `ACCNOMOS_TEST_MODE=1`, which the image never sets; signed actions include
  the tenant, so a card cannot cross tenants even there.
- **Graph downloads follow Graph's redirect.** Reading a file or an attachment answers with a 302 to a
  pre-authenticated download URL on another Microsoft host. httpx drops the `Authorization` header on that
  cross-origin hop, so the token stays with Graph. Upload-session URLs are pre-authenticated and called without it.
- **One rate limit for every route, the logo upload included.** The per-IP bucket (60 a minute) applies to it; at
  2 MB a request that is at most 120 MB a minute from one address, which the front proxy is there to absorb.
- **A stuck `approving` action is not cleared automatically.** The run may have emailed before it died, so running it
  again could send twice. After 10 minutes the user is told to check, and rejecting the card clears it; the card
  does not yet explain that in the app.
- **A to-do's link is whatever https link the app sends.** It is the user's own list in their own folder, the runtime
  never fetches it, and the web opens it with `noopener noreferrer`; `javascript:` and other schemes are refused.
- **Triage and reminders put email text in front of a model.** A crafted email can steer a suggested reply or to-do.
  Replies are only saved as Outlook drafts for the user to read and send; reminders are checked by code against the
  invoice (figures, number, no links) and sent only after the user confirms; to-dos are added only when the user taps
  *Add*.
- **`ProposedAction.preview` is free-form JSON.** It is covered by the signature and bounded by the 256 KB body cap;
  the executors read only the keys they wrote.
- **Without `ACTIONS_SIGNING_KEY` the signing key is random per process.** Cards then stop working after a restart
  (the user asks again), and several replicas would refuse each other's cards. Set it whenever there is more than
  one process.
- **`POST /invoices/{number}/pdf` writes without `X-User`.** It saves the render of an invoice the user already
  wrote; there is no new fact to attribute. `/health` reports folder-rename counts summed over all users (no names,
  no paths).

## Open after the third pass

Found in the pre-submission review (`docs/reviews/security-3/REVIEW.md`) and left for a product decision.

- **`/extract` and `/ai/test` need no Graph token** (Android reads a receipt before sign-in). With no `X-AI-*`
  headers they run on the server's default model: `AI_MODE=local` means the operator's `OLLAMA_BASE`, key mode the
  operator's `META_API_KEY` if set. Anyone can use that model at the per-IP rate limit.
- **`/lookup/*` checks only that `X-Graph-Token` is present**, not that it is valid, so the Companies House key and
  the relay's VAT check are reachable with any string (rate-limited).
- **The relay's VAT-number check is public** on `api.accnomos.com` and spends the relay's application token.
- **`/extract`'s duplicate memory is shared by every caller** of the process: a file someone else uploaded is
  flagged as a duplicate.
- **Android allows cleartext HTTP to any host** (`usesCleartextTraffic`), for a runtime on the user's LAN; a user
  who types an `http://` address elsewhere sends the Graph token and Meta key unencrypted. The Meta key is in
  shared preferences, not encrypted storage.
- **Android release builds fall back to the debug key** when `android/key.properties` is missing.

## Reporting a vulnerability

Please do not open a public issue with details. Use GitHub's private vulnerability reporting on
[zaytunazs/accnomos](https://github.com/zaytunazs/accnomos/security) (*Security → Report a vulnerability*). If that
option is not available, open an issue that says only that you have a security report and how to reach you, and we
will set up a private channel.

Include what you found, how to reproduce it, and the `X-Correlation-Id` of any request involved. Never include real
tokens or anyone's financial data; HMRC sandbox test users are fine. This is a hackathon project, so there is no
bug bounty.
