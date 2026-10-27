# Task: e2e stability and speed — kill the flakes, isolate workers, parallelise, keep CI under 4 minutes

Accnomos monorepo (public; UK English; no secrets). The suite is green when run alone but `review.spec.ts:130` ("signed in: edit sends only
changed fields, U undoes…") failed once in a full run: after pressing U the status stayed "Approved · posted to your books · U to undo"
(the undo keystroke arrived while `busy !== null` or before focus settled). Read first `apps/web/e2e/*`, `playwright.config.ts`,
`apps/web/src/components/review/ReviewQueue.tsx` (keys handler), `services/runtime/app/testmode.py` (one shared fake OneDrive).
CI: `.github/workflows/e2e.yml` runs on every push to main; see the latest runs with `gh run list --workflow "End-to-end tests (Playwright, test mode)"`.

## Deliverables
1. Run the full suite 3× locally; list every test that fails or is flaky in any run. Fix the app where the app is racy (e.g. the U
   handler should queue the undo until `busy` clears, or the status note should be awaited), fix the spec where the spec is racy
   (wait for the enabled state, not a timeout). No `test.fixme`, no increased timeouts as the fix.
2. Per-worker isolation: give the test-mode runtime a per-request "fake OneDrive" keyed by a header the fixture sets
   (`X-Test-Tenant`), so specs can run in parallel; keep `reset` per tenant. Then enable `fullyParallel`/workers 2–4 and keep every
   spec green 3×.
3. CI: cache pnpm and Playwright browsers, `uv sync --frozen` (lockfile is current), time budget under 4 minutes; the workflow must
   pass on the first push after merge — verify by reading the last failed run's log (`gh run view --log-failed`) for environment errors.
4. README e2e row and `docs/DEV.md` updated (test count, time, how to run one spec, how to run with `--ui`).
Commit in small steps; do not push. Finish with `git log --oneline -8`, the 3× pass lines, and the flakes you fixed with their causes.
