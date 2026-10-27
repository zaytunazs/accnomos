# Review: `claude/e2e-stability`

Second-agent review of the e2e stability and speed task (`TASK_BRIEF.md`), 27 Oct 2026.

## What was checked

- `services/runtime`: `pytest -q`: 675 passed, 1 skipped (no other Python package or service is touched by this branch).
- `apps/web`: `pnpm run build` passes; `eslint` clean on `ReviewQueue.tsx`.
- Full Playwright suite, own ports (3150/8831/8839, so no other checkout's servers are reused), fresh test-mode export:
  **56 passed** three runs in a row (38.6 s, 38.5 s, 38.5 s, cold start included), and once with `CI=1`
  (3 workers, 1 retry, no server reuse): 56 passed in 45.2 s, no retries used.
- Read the whole diff: per-tenant fakes (`TenantMiddleware` + `ContextVar`, header sanitised, CORS header only in
  test mode, every former `STATE` use outside the unit tests now goes through `current()`/`state()`), gold-hash warm-up
  before `/health`, fixture tenant header on both the page and `request`, the queued-U fix, the CI workflow, docs.
  No secrets or user data written server-side; test mode is still off in the Docker image.

## What I fixed

- `82d61e6` fix(review): a U pressed while an approve was in flight stayed queued even if that approve then **failed**,
  so it undid the decision *before* it (or said "Nothing to undo yet."). The queue is now dropped when what was busy
  fails. New e2e test covers both sides (U held behind an approve undoes it once it lands; behind a failing approve,
  nothing is undone). I checked that the test fails without the fix.
- `4261300` test(runtime/testmode): the `X-Test-Tenant` value is sanitised and capped at 64 characters, and an
  all-invalid header gets the default fakes.
- `2fa883e` docs: README (two rows) and `docs/DEV.md` said 55 tests in about 27 s. It is now 56 tests (31 desktop,
  25 phone), about 40 s locally from a cold start, 45 s with the CI settings.

## What remains

- **CI not verified.** `gh run list` / `gh run view --log-failed` were not permitted in this session, so the last failed
  run's log was not read and the workflow changes (uv/pnpm/Chromium/Next caches, `--only-shell`, `install-deps` on a
  cache hit, `packageManager`-pinned pnpm, 8-minute job / 4-minute test step) have never run on GitHub. Watch the first
  push to main.
- **Shared default ports across checkouts.** With `reuseExistingServer` locally, a run in one checkout picked up
  another checkout's runtime on :8781, which then shut down mid-run (4 ECONNREFUSED failures in this review). `docs/DEV.md`
  warns about it; a per-checkout default port or `reuseExistingServer: false` would remove the trap.
- Test mode only: `STATES` grows by one set of fakes per worker process and is never pruned. Each reset also refills
  the one process-wide rate limiter for every tenant. Both are harmless while Playwright runs with `RATE_LIMIT_PER_MIN=0`.
- `a271998` ("wip: checkpoint") only adds `TASK_BRIEF.md` at the repo root. Drop or squash it before merge if the
  brief should not land on main.
- The flake list the brief asked for (3× runs before the fix, causes) is in the implementing agent's report, not in the
  repo. I only confirmed the suite is green now.

## How to verify by hand

From `apps/web`, after `uv sync --all-packages --all-extras` and `pnpm install && pnpm exec playwright install chromium`:
put `E2E_WEB_PORT`, `E2E_RUNTIME_PORT` and `E2E_RELAY_PORT` set to free ports in an env file. Then run
`node --env-file=<file> e2e/build.mjs` followed by `node --env-file=<file> node_modules/@playwright/test/cli.js test`
three times. Expect 56 passed each time in about 40 s. Then open `/review` in the test-mode export (or run
`e2e/review.spec.ts:164 --ui`), scan the gold receipt, press J, A, then U straight away: the approval is undone once
it lands ("a reversing entry was added"). Finally run `pytest -q` in `services/runtime`.
