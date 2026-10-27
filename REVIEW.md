# Review: `claude/e2e-tests`

Task: end-to-end tests (`TASK_BRIEF.md`). Runtime test mode with fakes and a stub AI, a fake sign-in for test-mode web
builds only, a Playwright suite, and a CI job.

## What was checked

- **Runtime** `services/runtime`: `pytest -q` passes, **285 passed** (276 before this review). Run with this branch's
  `packages/*/src` first on `sys.path`. The shared `.venv` currently points `accnomos_connectors`/`accnomos_ledger` at
  another checkout (`repo-lane-f`), so a bare `pytest` here can test the wrong packages.
- **Connectors** `packages/connectors`: **21 passed** (19 + 2 new). **Ledger** `packages/ledger`: **30 passed**
  (not changed by this branch). `services/hmrc-relay` is not changed by this branch and was not run.
- **Web** `apps/web`: `pnpm run build` (normal mode) passes; `pnpm run lint` has 0 errors and 2 warnings, both already
  on main (`AskThread.tsx`, `LiveReview.tsx`); `tsc --noEmit` is clean. The normal `out/` has no `__test/`,
  `test-token`, `accnomos-test` or fake-account strings; the test-mode `out-e2e/` does.
- **E2E** `pnpm run e2e`: **23 passed, 0 failed, about 36 s** (7 desktop flows and 16 phone-width pages). Run three
  times, the last with the runtime loading this branch's packages.
- **Diff read for:** whether test mode can switch on in production, or whether any request can leave the machine in
  test mode. All AI configs, including `/ai/test`, are forced to the stub. SAM crop and Muse Voice need `mode=key`,
  so they cannot run. Graph mail, contacts and storage are swapped for the fakes, and a token is still required.
  Also checked: nothing written server-side beyond in-memory fakes; the sample calendar entry is labelled
  "SAMPLE — FICTIONAL COMPANY"; pence (the stub returns the gold figures, and code computes the VAT boxes); and
  UK English.

## What I fixed

| Commit | Fix |
|---|---|
| `cace485` | Unit tests for `FakeCalendarProvider` (it had none). |
| `67ca679` | The Graph look-alike returned 500 for a bad item id, a missing `name` or a missing parent. A malformed id even decoded silently to the root, because non-strict base64 skips bad characters. It now answers Graph-shaped 404/400, with strict id decoding. New tests: only exactly `ACCNOMOS_TEST_MODE=1` turns test mode on; `deploy/Dockerfile.runtime` pins it to 0 and copies no `evals`; test-mode dependencies still give 401 without a token; the contacts dependency uses the fake; the seeded sample calendar; error paths of the look-alike and gold routes. |
| `8a3d6e8` | `deploy-web.yml` pins `NEXT_PUBLIC_TEST_MODE` empty and refuses to publish an `out/` containing the fake sign-in or `/__test` URLs. Checked against both exports. |
| `2345b77` | README "What works today" row for the e2e suite, saying what it does and does not prove. `docs/DEV.md` now says the fake calendar is not used by any route and the stub AI does not test models. The `msal-test.ts` comment no longer claims other runtimes refuse the test token. |

## What remains

- **The CI job `.github/workflows/e2e.yml` has never run on GitHub.** `uv sync --frozen --package accnomos-runtime`,
  the pnpm/Node versions and `playwright install --with-deps` are untested there. Check the first PR run.
- **Fake calendar:** seeded but not used. No runtime route uses a `CalendarProvider` (there is no Graph calendar
  connector), so the brief's "fake calendar" is in place but no e2e flow covers it.
- **What the suite does not prove:** real MSAL sign-in, the real Graph API, the HMRC relay (Playwright stands in for
  it) and model accuracy (the stub answers only for gold PNGs it rendered itself). The README row says so.
- **Local environment:** the shared `.venv` resolves the workspace packages to `repo-lane-f`. Run lane-e tests with
  this lane's `packages/*/src` first on `sys.path` (or re-sync a per-lane venv), or results may mix lanes.
- **History:** `966f0b1 wip: checkpoint after implement pass` only adds `TASK_BRIEF.md`. Squash or drop it (and the
  brief) at merge if the brief should not land on main.
- **`apps/web/package.json`** was reformatted (whitespace only) along with the new scripts and `@playwright/test`, so
  the diff is noisier than the change.
- **Already on main, not touched:** README "What works today" has duplicate rows (Books.xlsx, Files, VAT deadlines)
  and blank lines that split the table. The two lint warnings above.

## How to verify by hand

From the repo root, install the workspace (`uv sync --all-packages --all-extras`), then
`cd apps/web && pnpm install && pnpm exec playwright install chromium && pnpm run e2e`. You should see 23 passed in
under a minute. To look around yourself, start the runtime with
`ACCNOMOS_TEST_MODE=1 PORT=8781 CORS_ORIGINS=http://127.0.0.1:3100 python -m uvicorn app.main:app --app-dir services/runtime --port 8781`
and `node e2e/serve.mjs` in `apps/web`, then open http://127.0.0.1:3100/connect. *Sign in with Microsoft* signs you
in as "Sam Builder (test)" without any network call. Create the folder, then on Review upload
`http://127.0.0.1:8781/__test/gold/001_standard.png` (saved locally). Scan, approve, and check that /vat shows Box 4
£8.65 for 26A3. Finally, `pnpm run build` and confirm that `grep -r "__test/" out/` finds nothing.
