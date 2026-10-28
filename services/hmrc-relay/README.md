# hmrc-relay

Stateless relay between the Accnomos PWA / Android app and HMRC's MTD VAT APIs. It exists because HMRC
needs the OAuth **client secret at code exchange and at refresh**. The relay holds that secret, returns tokens to
the client, and stores nothing. It also builds the mandatory **fraud-prevention headers (spec v3.3)** from facts
the client collected plus facts the relay saw itself.

User access tokens come in with every request in `X-HMRC-Access-Token`. Tokens are never written to disk or logs.
The only in-memory copies are the application-restricted token cache (until 60 s before expiry) and a 30 s cache
of each refresh result, so two racing refreshes of the same single-use refresh token share one HMRC call. The relay
also remembers spent OAuth `state` nonces (never tokens) until they expire, so run **one worker**.

Request limits match the runtime (`relay/security.py`, see `docs/SECURITY.md`): `X-HMRC-Access-Token` over 8 KB → 431,
credentials over plain HTTP behind a proxy → 400, 256 KB bodies → 413, per-IP rate limit → 429 with `Retry-After`,
unknown body fields → 422, unexpected errors → 500 `{detail, correlation_id}` with no stack trace.

## Environment

| Variable | Purpose | Default |
|---|---|---|
| `HMRC_CLIENT_ID` | HMRC application client ID | — |
| `HMRC_CLIENT_SECRET` | HMRC client secret (code exchange, refresh, client_credentials) | — |
| `HMRC_BASE` | API base. `https://test-…` means sandbox | `https://test-api.service.hmrc.gov.uk` |
| `HMRC_AUTH_BASE` | Consent UI base (`/oauth/authorize`) | `https://test-www.tax.service.gov.uk` |
| `HMRC_REDIRECT_URI` | Must be the relay's `/hmrc/callback`, registered with HMRC | — |
| `HMRC_VENDOR_PRODUCT_NAME` | `Gov-Vendor-Product-Name` (percent-encoded on send) | `Accnomos` |
| `HMRC_VENDOR_VERSION` | Relay version in `Gov-Vendor-Version` | `0.1.0` |
| `RELAY_PUBLIC_IP` | Relay's public IP (`Gov-Vendor-Public-IP`, `Gov-Vendor-Forwarded by=`) | — |
| `RELAY_LICENCE_HASH` | Optional. Sent as `Gov-Vendor-License-IDs` | — |
| `RELAY_ALLOWED_REDIRECTS` | Comma-separated origins `/hmrc/callback` may redirect tokens to, e.g. `https://app.accnomos.co.uk,accnomos://hmrc`. `http://localhost` and `http://127.0.0.1` are always allowed. The same `http(s)` origins get CORS, since the PWA calls the relay straight from the browser | — |
| `RELAY_ITSA_PRODUCTION` | `1` lets the MTD Income Tax routes run against a production `HMRC_BASE`. Off by default; nothing here sets it | off |
| `RATE_LIMIT_PER_MIN` | Requests per minute per client IP (in memory); `0` turns the limit off | `60` |

The relay reads the process environment only. It never reads a `.env` file.

## Endpoints

| Method & path | Notes |
|---|---|
| `GET /health` | `{ok, service, version, sandbox, configured, uptime_s}` |
| `GET /hmrc/authorize?redirect_to=&code_challenge=&scope=` | `scope` from `read:vat write:vat read:self-assessment write:self-assessment`, VAT's two by default. → `{url, state}`. `state` is HMAC-signed, expires after 10 min, and is accepted once by the callback and once by the exchange |
| `GET /hmrc/callback?code&state` | HMRC redirects here. 303 to `redirect_to#access_token=…&refresh_token=…&expires_in=…&scope=…&token_type=…&state=…` |
| `POST /hmrc/exchange {code, state, code_verifier}` | PKCE only (see below) → token JSON |
| `POST /hmrc/refresh {refresh_token}` | → token JSON. Serialised per refresh token |
| `POST /vat/{vrn}/obligations {from, to, status?, client_facts, method, gov_test_scenario?}` | |
| `POST /vat/{vrn}/returns {return, client_facts, method, gov_test_scenario?}` | 201. `return` holds the 11 HMRC fields, validated before sending (see below) |
| `POST /vat/{vrn}/returns/{periodKey}/view {client_facts, method}` | Encode `#` as `%23` |
| `POST /vat/{vrn}/liabilities` / `POST /vat/{vrn}/payments {from, to, client_facts, method}` | |
| `GET /vat/check/{vrn}` / `GET /vat/check/{vrn}/{requesterVrn}` | Check a UK VAT number v2.0 (app-restricted, `read:vat` token); HMRC's raw answer |
| `GET /hmrc/vat-check/{vrn}?requester=` | What the app uses: `vrn` as `GB` + 9 or 12 digits (spaces allowed) → `{vrn, registered, name, address, consultation_number, checked_at, checksum_ok, source}`; `source` is `hmrc-sandbox` or `hmrc` from `HMRC_BASE`. HMRC's 404 → `registered: false`; a bad format → 400 without calling HMRC. `checksum_ok` (mod-97) is informational only: HMRC's own sandbox numbers fail it |
| `POST /hmrc/test-user` | Sandbox only: creates an `mtd-vat` organisation test user |
| `POST /hmrc/test-user/individual` | Sandbox only: an individual enrolled for `national-insurance`, `self-assessment`, `mtd-income-tax` (→ `userId`, `password`, `nino`, `mtdItId`, …) |
| `POST /itsa/{nino}/businesses {client_facts, method}` | MTD Income Tax (sandbox only, see `relay/itsa.py`): Business Details 2.0 list |
| `POST /itsa/{nino}/obligations {from?, to?, status? open/fulfilled, business_id?, …}` | Obligations 3.0, income and expenditure, self-employment |
| `POST /itsa/{nino}/final-declaration-obligations {tax_year?, status?, …}` | Obligations 3.0, final declaration |
| `POST /itsa/{nino}/self-employment/{businessId}/cumulative/{taxYear} {summary, confirmed: true, …}` | Self-Employment Business 5.0 cumulative period summary (PUT; `hmrc: null` on HMRC's 204). `summary` is validated against HMRC's schema first; 422 otherwise |
| `POST …/cumulative/{taxYear}/view` | Read it back |
| `POST /itsa/{nino}/calculations/{taxYear}/trigger {calculation_type}` | Individual Calculations 8.0 → 202 `{calculationId}` |
| `POST /itsa/{nino}/calculations/{taxYear}/list {calculation_type?}` / `POST …/{calculationId}/view` | List / retrieve (HMRC answers 404 while it is still calculating) |
| `POST /itsa/{nino}/calculations/{taxYear}/{calculationId}/final-declaration {declaration, confirmed: true}` | `declaration` must be HMRC's text word for word |
| `POST /itsa/{nino}/test-business {tax_year}` | Sandbox only: Self Assessment Test Support 1.0, a self-employment test business |
| `POST /hmrc/validate-headers {client_facts, method}` | Sandbox only: HMRC fraud-header validator |
| `GET /hmrc/validation-feedback?method=` | Sandbox only: HMRC validation feedback for VAT MTD |

The VAT endpoints and `validate-headers` return:

```json
{"hmrc": {...}, "sent_headers": {"accept": "...", "gov-client-...": "..."}, "fraud_headers_missing": [],
 "correlation_id": "...", "receipt_id": "...", "receipt_timestamp": "..."}
```

`sent_headers` never includes `Authorization`. Store it in the audit log next to the submission. HMRC errors come
back with HMRC's status code as `{code, message, errors, hmrc_status}`. A network failure reaching HMRC returns 502.

**Return validation.** The relay returns 422 without calling HMRC when any of these fail:
- `periodKey` is 4 characters (`#` allowed).
- Money boxes have at most 2 dp.
- The four value boxes are whole pounds.
- `netVatDue ≥ 0`.
- box 3 = box 1 + box 2.
- box 5 = |box 3 − box 4|.

**PKCE.** If `/hmrc/authorize` gets a `code_challenge` (S256), only the client holds the verifier. The callback
therefore cannot exchange the code. It redirects with `#code=…&state=…`, and the client calls `/hmrc/exchange` with
its `code_verifier`. Without a challenge, the callback exchanges the code itself and puts the tokens in the fragment.
In both cases the client must check that the returned `state` matches the one `/hmrc/authorize` gave it.

## Fraud-prevention header sources

| Header | Source | Web | Mobile |
|---|---|---|---|
| Gov-Client-Connection-Method | relay (`method`) | ✓ | ✓ |
| Gov-Client-Browser-JS-User-Agent | client `browser_js_user_agent` (`navigator.userAgent`) | ✓ | |
| Gov-Client-Device-ID | client `device_id`, a UUID generated once and persisted on the device | ✓ | ✓ |
| Gov-Client-Multi-Factor | client `multi_factor[]`. `[]` sends an empty header (no MFA used) | ✓ | ✓ |
| Gov-Client-Screens | client `screens[]` | ✓ | ✓ |
| Gov-Client-Timezone | client `timezone` (`UTC±hh:mm`) | ✓ | ✓ |
| Gov-Client-User-IDs | client `user_ids` (`{"accnomos": "<id>"}`) | ✓ | ✓ |
| Gov-Client-Window-Size | client `window_size` | ✓ | ✓ |
| Gov-Client-User-Agent | client `user_agent` | | ✓ |
| Gov-Client-Local-IPs / -Timestamp | client `local_ips[]`, `local_ips_timestamp` | | ✓ |
| Gov-Client-Public-IP | relay: the last `X-Forwarded-For` hop (never `CF-Connecting-IP`), else the socket peer | ✓ | ✓ |
| Gov-Client-Public-IP-Timestamp | relay: time the request arrived | ✓ | ✓ |
| Gov-Client-Public-Port | relay: socket port, or the `X-Client-Port` / `X-Real-Port` header when behind a proxy | ✓ | ✓ |
| Gov-Vendor-Forwarded | relay: `by=RELAY_PUBLIC_IP&for=<client IP>` | ✓ | ✓ |
| Gov-Vendor-License-IDs | `RELAY_LICENCE_HASH`, if set | opt | opt |
| Gov-Vendor-Product-Name | `HMRC_VENDOR_PRODUCT_NAME` | ✓ | ✓ |
| Gov-Vendor-Public-IP | `RELAY_PUBLIC_IP` | ✓ | ✓ |
| Gov-Vendor-Version | client `vendor_versions` + `<product>-relay=HMRC_VENDOR_VERSION`. Mobile needs both | ✓ | ✓ |

The relay percent-encodes values where the spec requires it, so clients send raw values. If a fact is
unavailable, omit the field. The relay then omits the header, logs a warning and lists it in
`fraud_headers_missing`. It never sends `null` or other placeholders.

**Proxies.** The relay takes the last `X-Forwarded-For` hop (the one your proxy appended) and ignores
`CF-Connecting-IP`, so it must only be reachable through your proxy. Behind a proxy the socket port belongs to the proxy, so set the client port explicitly, for example nginx
`proxy_set_header X-Client-Port $remote_port;`. Otherwise `Gov-Client-Public-Port` is omitted and logged.

### PWA (`WEB_APP_VIA_SERVER`)

```js
const client_facts = {
  device_id: localStorage.deviceId ??= crypto.randomUUID(),
  multi_factor: [],                                   // or [{type: "TOTP", timestamp: "2026-10-27T09:00Z", unique_reference: sha256(factorId)}]
  screens: [{width: screen.width, height: screen.height, scaling_factor: devicePixelRatio, colour_depth: screen.colorDepth}],
  timezone: utcOffset(),                              // e.g. "UTC+01:00" from -new Date().getTimezoneOffset()
  user_ids: {accnomos: userId},
  window_size: {width: innerWidth, height: innerHeight},
  browser_js_user_agent: navigator.userAgent,
  vendor_versions: {"accnomos-pwa": APP_VERSION},
};
```

```json
{"method": "WEB_APP_VIA_SERVER", "client_facts": {
  "device_id": "beec798b-b366-47fa-b1f8-92cede14a1ce", "multi_factor": [],
  "screens": [{"width": 1920, "height": 1080, "scaling_factor": 1, "colour_depth": 24}],
  "timezone": "UTC+00:00", "user_ids": {"accnomos": "user-42"}, "window_size": {"width": 1256, "height": 803},
  "browser_js_user_agent": "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
  "vendor_versions": {"accnomos-pwa": "0.4.0"}}}
```

### Android (`MOBILE_APP_VIA_SERVER`)

- `device_id`: a UUID generated on first launch and kept in app storage.
- `screens`: from `WindowMetrics` / `DisplayMetrics` (`density` → `scaling_factor`, 24 → `colour_depth`).
- `window_size`: the current window bounds.
- `user_agent`: `"Android"`, `Build.VERSION.RELEASE`, `Build.MANUFACTURER`, `Build.MODEL`.
- `local_ips`: from `ConnectivityManager.getLinkProperties(activeNetwork).linkAddresses`, stamped with the time they
  were read.
- `timezone`: from `ZoneId.systemDefault()`'s current offset.

```json
{"method": "MOBILE_APP_VIA_SERVER", "client_facts": {
  "device_id": "a1b2c3d4-0000-4000-8000-000000000001",
  "multi_factor": [{"type": "TOTP", "timestamp": "2026-10-27T09:00Z", "unique_reference": "c6f1e2…"}],
  "screens": [{"width": 1080, "height": 2400, "scaling_factor": 2.75, "colour_depth": 24}],
  "timezone": "UTC+01:00", "user_ids": {"accnomos": "user-42"}, "window_size": {"width": 1080, "height": 2200},
  "user_agent": {"os_family": "Android", "os_version": "15", "device_manufacturer": "Google", "device_model": "Pixel 9"},
  "local_ips": ["10.0.0.12", "fe80::1"], "local_ips_timestamp": "2026-10-27T09:01:02.345Z",
  "vendor_versions": {"accnomos-android": "1.4.0"}}}
```

## Run and test

```sh
~/spark/accnomos/.venv/bin/pip install -e 'services/hmrc-relay[dev]'
cd services/hmrc-relay
HMRC_CLIENT_ID=… HMRC_CLIENT_SECRET=… HMRC_REDIRECT_URI=http://localhost:8790/hmrc/callback RELAY_PUBLIC_IP=… \
  ~/spark/accnomos/.venv/bin/uvicorn relay.main:app --port 8790
~/spark/accnomos/.venv/bin/pytest -q   # HMRC is mocked with httpx.MockTransport; no network
```

Sandbox check: `POST /hmrc/test-user`, sign in at the `/hmrc/authorize` URL with the returned `userId` / `password`,
then `POST /hmrc/validate-headers` with real client facts.
