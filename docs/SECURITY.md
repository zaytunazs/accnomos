# Security

Accnomos is a hackathon project. This page says what the public API protects, what it deliberately does not,
and how to report a problem. Deployment hardening is in [`deploy/README.md`](../deploy/README.md).

## Threat model

- Public API on `api.accnomos.com`: front proxy (TLS) → tunnel → edge nginx → two stateless services.
- **No server state and no accounts.** Every request carries the caller's own credentials in headers:
  `X-Graph-Token` (Microsoft Graph, the user's OneDrive/Outlook), `X-Meta-Api-Key` (bring-your-own AI key),
  `X-HMRC-Access-Token` (HMRC MTD). The books live in the user's own cloud folder.
- The **relay** is the one component with a secret (the HMRC client secret, from the environment).
- Attackers we design for: anonymous internet clients, malicious documents (receipts, mail attachments, bank CSVs)
  that reach the model, and a hostile web page in the user's browser.

## What is protected, and where it is checked

| Area | Protection | Code | Test |
|---|---|---|---|
| Secrets in logs | Every log record is scrubbed as it is created (any logger, exception text included): credential header values, `Bearer …`, JWTs, `access_token`/`refresh_token`/`client_secret`/`code_verifier` fields, the OAuth `?code=` in the relay's access log, and the exact credential values of the request being served. Records keep their shape where possible, so uvicorn's access log still formats | `app/security.py`, `relay/security.py` | `test_security.py`, `test_hardening.py` |
| Secrets in responses | Unhandled errors → `500 {"detail", "correlation_id"}`, no stack trace or exception text; Graph and HMRC error messages are scrubbed | same, `main.py` handlers | same |
| Token size | Credential headers over 8 KB → 431 | security middleware | same |
| Transport | When a proxy sends `X-Forwarded-Proto`, credentials over anything but `https` → 400; HSTS at the edge and on the static site | middleware, `deploy/nginx.conf`, `.htaccess` | same, `test_deploy_hardening.py` |
| Abuse | Per-IP token bucket, 60/min by default (`RATE_LIMIT_PER_MIN`), 429 + `Retry-After`; `/health` and preflights exempt | middleware | same |
| Body size | 25 MB on `/extract`, `/books/ask/voice`, `/books/bank/import`; 256 KB everywhere else (relay: 256 KB); by `Content-Length` and by counting streamed bytes; nginx enforces the same | middleware, nginx | same |
| Outbound calls | Every httpx client (Graph, Meta, Ollama, SAM, HMRC) has an explicit timeout | each client | `test_every_outbound_http_client_has_a_timeout` |
| SSRF | A browser can only point the runtime at AI base URLs the server already knows (`OLLAMA_BASE`, `MODEL_API_BASE`, `AI_ALLOWED_BASE_URLS`); `/ai/test` follows no redirects | `app/ai/config.py`, `main.py` | `test_unknown_ai_base_url_refused` |
| CORS | Exact origins from `CORS_ORIGINS` / `RELAY_ALLOWED_REDIRECTS`; wildcards refused at start-up; explicit methods and headers; preflight cached 10 min; no cookies | `main.py`, `relay/main.py` | `test_cors_*` |
| File names | Uploaded and model-derived names cannot escape the user's folder: `.`/`..`, separators, absolute and drive paths, control characters refused (`check_name`); `Books.free_path` and the Graph provider refuse unsafe segments as a backstop | `app/validation.py`, `books.py`, `msgraph.py`, `pipeline.py` | `test_validation.py` |
| Request bodies | Every JSON body forbids unknown fields (runtime and relay, including HMRC client facts); free text is length-capped | route models | `test_unknown_fields_are_rejected`, relay `test_unknown_or_malformed_fields_rejected` |
| Identifiers | VRNs: 9 digits on the relay; GB/XI + 9 or 12 digits, GD/HA on contacts. Period keys `^[A-Za-z0-9#]{4}$`. Proposal, event, bank-line, contact and job ids are hex-only before they touch a path | routes, `books.py`, `contacts.py`, `jobs.py` | `test_vrn_format`, `test_period_key_format`, `test_vat_period_key_format`, `test_contacts.py` |
| OAuth (relay) | `state` is HMAC-SHA256-signed with a key derived from the client secret, compared in constant time, expires after 10 min and is accepted once per step (callback, exchange); PKCE (S256) supported; tokens go back in the URL fragment with `Cache-Control: no-store` and `Referrer-Policy: no-referrer` | `relay/oauth.py`, `relay/routes.py` | `test_state_and_redirects.py` |
| Redirects (relay) | `redirect_to` must be an exact allowed origin (plus plain-http localhost for development); userinfo, backslashes, whitespace/control characters, other ports, scheme downgrades and look-alike hosts are refused | `relay/settings.py` | `test_redirect_bypass_attempts_refused` |
| Containers | Pinned bases, non-root, read-only root filesystem, no capabilities, healthchecks, loopback-only ports | `deploy/` | `test_deploy_hardening.py` |
| Correlation | Every response carries `X-Correlation-Id`; the same id is in the error body and the server log line | middleware | `test_every_response_has_a_correlation_id` |

## Out of scope for the hackathon

- **Authentication of callers.** There are no accounts: whoever holds a valid Graph/HMRC token can use it, as with
  the providers' own APIs. The runtime does not verify that `X-User` matches the Graph token's user; it is an audit
  label in the user's own files.
- **Distributed rate limiting.** The buckets are in memory, per process; a restart clears them, and several replicas
  would each allow the full rate. Same for the relay's spent-state set (hence one relay worker).
- **Prompt injection beyond file names.** A crafted document can still mislead the model's reading of amounts or
  suppliers. Every figure is checked by code and nothing is posted without the user's approval (or an Autopilot rule
  the user created), but the extraction itself is not adversarially robust.
- **Content-Security-Policy for the web app.** The static site sends frame and object restrictions only; a full
  script CSP needs nonces for Next.js inline scripts.
- **Data at rest.** The books are files in the user's OneDrive; their protection is Microsoft's and the user's.
- **Browser storage.** The AI key and HMRC tokens live in the user's browser storage (local / session); an XSS on the
  web origin could read them.
- Availability against volumetric attacks (left to the front proxy / Cloudflare), dependency scanning, and secret
  rotation automation.

## Reporting a vulnerability

Please do not open a public issue with details. Use GitHub's private vulnerability reporting on
[zaytunazs/accnomos](https://github.com/zaytunazs/accnomos/security) (*Security → Report a vulnerability*). If that
option is not available, open an issue that says only that you have a security report and how to reach you, and we
will set up a private channel.

Include what you found, how to reproduce it, and the `X-Correlation-Id` of any request involved. Never include real
tokens or anyone's financial data; HMRC sandbox test users are fine. This is a hackathon project, so there is no
bug bounty.
