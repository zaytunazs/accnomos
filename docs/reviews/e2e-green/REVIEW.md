# Review: `claude/e2e-green`

Second-agent review of the "make the Playwright suite green again" task (`TASK_BRIEF.md`).

## What was checked

- **E2E:** `cd apps/web && CI=1 pnpm run e2e` → **54 passed (1.3 min)**, well under the 4-minute budget. `.venv` is not
  in this checkout and `uv sync` was not allowed here, so the runtime ran on the parent workspace's Python (`python3`
  with the runtime deps installed). CI uses `uv sync --frozen` and should behave the same.
- **Web build:** `cd apps/web && pnpm run build` passes.
- **Python:** this branch changes no Python. `services/runtime` `pytest -q` → 648 passed, 1 skipped, as a check that
  test mode still works. The other packages were not re-run because nothing in them changed.
- **Diff read** against the brief and the product rules:
  - `5791ae5` (app fix, `LiveBank.tsx`): the bank uploader used to sit inside the empty state, which unmounted after
    the first import and lost the result message. It is now always mounted. This is a real app regression, and the fix
    is correct.
  - `07ce6a2` (review-vat): it removes duplicated steps left by a bad merge. The spec now opens on the current period
    and picks Jul–Sep for the gold receipt, so it follows the new default.
  - `dcba3fe`, `78bab13`, `f26d5e7`, `153023a`: these specs follow new UI (the key-numbers table, the EmptyState
    headings, the `?from=job` hand-off), not regressions. The jobs spec says "sending that invoice marks the hours".
    That is true in the code (`services/runtime/app/jobs.py` `mark_invoiced`), but the spec does not test it.
  - `b80c0d7`: the Setup checklist row "Try a receipt" no longer says "in Settings" in its aria-label. The new home
    spec covers the row links, opening on the right tab and Dismiss being remembered.
  - Brief items 2 and 3 (Settings tabs; the Review J/K/A/E/R/U flow and *Approve all N rule matches*) were already on
    main in `settings.spec.ts`, `outlook.spec.ts` and `review.spec.ts`, and they pass.
  - `.github/workflows/e2e.yml` is unchanged. No secrets, no user data stored server-side, UK English throughout.

## What I fixed

- `7a59187` README: the e2e row said "44 tests … about 50 s" and the status note said the suite "did not re-run".
  Both now give 54 tests, about 1.3 min, re-run on this branch, and list the setup checklist, the Review keyboard flow
  and the jobs → invoice hand-off.

## What remains

- **The README has the same "End-to-end tests (Playwright)" row twice** (once in the main table and again after the
  Bank row, in a second table without a header). This predates the branch. I updated both copies; one should be removed.
- **`0474f59 wip: checkpoint after implement pass` only adds `TASK_BRIEF.md`.** Squash or drop it (and this
  `REVIEW.md`, if you wish) before merging to main.
- **No e2e test sends a job invoice and checks that the hours are then billed** (unbilled goes to 0, and the entries
  can no longer be edited). Runtime unit tests cover `mark_invoiced`; the browser path does not.
- **The CI job has still never run on GitHub.** The local run used Python from outside the repo, not `uv sync --frozen`.
- Older items in `docs/reviews/e2e-all-pages/REVIEW.md` "What remains" are unchanged: serial suite with a single shared
  fake OneDrive, Review badge cache, bank seed VAT codes, folder-name mismatch.

## How to verify by hand

Run `uv sync --all-packages`, then `cd apps/web && pnpm install && E2E_PYTHON=../../.venv/bin/python pnpm run e2e`.
Expect 54 passed in under 2 minutes. To check the one app fix, run the runtime in test mode and the web export
(`pnpm run e2e:build && node e2e/serve.mjs`). Sign in with the fake account, create the books folder, and open `/bank`
with no statements. Drop `evals/gold/bank/barclays.csv`: the message "barclays.csv: 6 new lines · saved as …" should
stay on screen while the statement list replaces the "No statements yet" empty state. Then open Home: the "Get set up"
card should list seven rows. *VAT period* should open Settings on the Business tab, scrolled to VAT periods.
*Dismiss* should keep the card hidden after a reload.
