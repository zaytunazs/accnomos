# Review: `claude/security`

Second-agent review of the security and robustness pass (`TASK_BRIEF.md`) on the runtime, relay and deploy files.

## What was checked

- **Tests**, each suite run against this checkout's code with an explicit absolute `pythonpath`, because the shared
  `.venv` has editable installs that point at another checkout:
  - `services/runtime`: 334 passed (was 330 before this review)
  - `services/hmrc-relay`: 100 passed (was 99)
  - `packages/connectors`: 19 passed
  - `apps/web`: `pnpm run build` passes (`public/.htaccess` changed)
- **The diff, read line by line** against the brief's seven deliverables: the security middleware (token size, HTTPS
  check, token bucket, body caps, safe 500s), log scrubbing, CORS, the AI base-URL allow-list, `check_name` and its
  backstops (`Books.free_path`, the Graph provider), strict bodies, VRN and period-key formats, one-time OAuth state
  with a 10-minute TTL and constant-time compare, redirect bypass tests, Dockerfiles, compose, edge nginx,
  `.htaccess`, `docs/SECURITY.md`, `deploy/README.md`, `docs/DEV.md`.
- **Cross-checks**: the runtime's CORS `allow_headers` cover every header the web app sends
  (`apps/web/src/lib/runtime.ts`, `ai-config.ts`); the web app's default AI base URLs are on the compose allow-list;
  mail-intake attachment names cannot carry a path (date and domain prefix, `safe_component`); the web app does no
  polling, so 60 requests a minute per IP is enough for normal use; no secrets or user data are written server-side.

## What I fixed

| Commit | Fix |
|---|---|
| `6e2c5aa` | **Bug: the log scrubber broke uvicorn's access log.** It set `record.args = None` on every record, and uvicorn's `AccessFormatter` unpacks `record.args`, so every request would have logged a `TypeError` traceback instead of an access line. Records with nothing to hide are now left alone. Records with a secret are scrubbed argument by argument and only flattened when the secret is split between the format string and its arguments. Same fix in the relay's copy. The relay also now redacts `?code=` so the authorisation code from `/hmrc/callback` never reaches the access log. Tests: `test_uvicorn_access_log_still_formats_after_scrubbing`, `test_secret_split_between_format_and_args_is_scrubbed`, `test_clean_records_are_left_untouched`, relay `test_access_log_hides_the_oauth_code_and_still_formats` |
| `f1a5baa` | An unsafe `suggested_filename` in a proposal someone edited by hand in their own folder used to reach the user as an opaque 500. It now gets a 400 that says what is wrong (`UnsafeName` exception handler). Test: `test_hand_edited_proposal_with_a_path_name_is_a_400_not_a_500` |
| `f323c96` | README "What works today" now has a row for the security pass that says it is tested but not deployed. `docs/SECURITY.md` mentions the access-log behaviour. `deploy/README.md` and `nginx.conf` explain that a front proxy other than Cloudflare must strip a client-sent `CF-Connecting-IP` |

## What remains

- **`CF-Connecting-IP` is trusted whenever it is present** (`deploy/nginx.conf`). On the Plesk path, a client can send
  it and choose its own address for the rate limit and the HMRC `Gov-Client-Public-IP`. This is documented as a manual
  front-proxy step, not fixed in code: the edge cannot tell which front proxy a request came through. The fix is either
  to strip the header at Plesk or to keep one edge config per front proxy.
- **The Graph provider's `_safe_path` raises a plain `ValueError`.** A hand-edited path in the user's books (for example
  a proposal's `file_path`) therefore still gets a 500 with a correlation id, not a 400. Nothing can escape the folder
  either way.
- **Deploy files are checked by config tests only.** The images were not built, `docker compose up` was not run,
  `nginx -t` was not run, and the `.htaccess` was not tried on Apache/Plesk. Base images are pinned by tag, not by
  digest (`deploy/README.md` lists digests as a manual step).
- The in-memory rate limit and the relay's spent-state set are per process (documented as out of scope; the relay runs
  one worker).
- `Permissions-Policy` still lists the deprecated `interest-cohort`. It is harmless, but browsers log a console warning.
- `MarkInvoicedBody.entry_ids` has no item limit. Only the 256 KB body cap bounds it.
- `TASK_BRIEF.md` was committed in `271afc2` ("wip: checkpoint"). Drop it before merging if briefs should not land on `main`.
- Nothing was tried against the live `api.accnomos.com`.

## How to verify by hand

Start the runtime locally with `CORS_ORIGINS=http://localhost:3000 RATE_LIMIT_PER_MIN=5 uvicorn app.main:app --port 8780`
from `services/runtime`. Then:
- `curl -i localhost:8780/health`: shows an `X-Correlation-Id`, and the uvicorn console prints a normal access line, not a "Logging error" traceback.
- Request `/books/summary` six times in a row: the sixth answers 429 with `Retry-After`.
- `curl -i -H 'X-Graph-Token: abc12345678' -H 'X-Forwarded-Proto: http' localhost:8780/books/summary`: answers 400 "Credentials must be sent over HTTPS".
- A token of 9,000 characters answers 431.
- `curl -i -X POST localhost:8780/ai/test -H 'Content-Type: application/json' -d '{"mode":"local","base_url":"http://169.254.169.254"}'`: answers 400 (not on the allow-list).
- Posting 300 KB to `/ai/test` answers 413.
- A preflight (`curl -i -X OPTIONS localhost:8780/books/summary -H 'Origin: http://localhost:3000' -H 'Access-Control-Request-Method: GET'`) returns `access-control-max-age: 600`, and from any other origin returns no `access-control-allow-origin`.

For the relay (`services/hmrc-relay`, `uvicorn relay.main:app --port 8787` with sandbox credentials), request
`/hmrc/callback?state=bad&code=secret123` and check that the console shows `code=[redacted]`.
