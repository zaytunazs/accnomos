# Review: `claude/e2e-all-pages`

Task: click through every web page in test mode, fix what breaks, extend the Playwright suite (`TASK_BRIEF.md`).

## What was checked

- **pytest**: `services/runtime` 604 passed, `services/hmrc-relay` 100, `packages/connectors` 34, `packages/ledger` 32.
- **Web**: `pnpm run build` passes (all pages static).
- **E2E** `pnpm run e2e`: when this review started, 31 passed and 1 failed (payroll) in 37 s. After the fixes below: **44 passed, 0 failed, 49.5 s**
  locally (one worker; 20 desktop flows, 24 phone tests).
- **Diff read for**: test-mode bypasses reaching production paths (the sender, calendar, AI base-URL and rate-limit
  bypasses are all behind `is_test_mode()` or `testmode.enable()`). The relay's `UNLIMITED_PREFIXES` is always empty, but
  `test_security.py` needs the two `security.py` copies to stay identical, so it stays. Also read for: seed data out of
  production paths (it lives only in `testmode.reset`), pence and wording, and app fixes that were really test
  workarounds (none found).

## What I fixed

| Commit | Fix |
|---|---|
| `7d7d8ac` | Removed `e2e/zz-explore.spec.ts`, a "temporary, not committed" page dump that was committed. It ran in CI and wrote to `/tmp`. |
| `c2cc22c` | The payroll spec was red: it looked for a lowercase "payroll" path, but the export is `04 Payroll/2026-10.csv`. |
| `93321c7` | The specs the brief asked for that were missing: **Invoices** (create → preview → Send stays disabled until the confirmation tick → the fake sender records one mail with `INV-0001.pdf` → the sale event is posted), **Bank** (gold Barclays CSV with the opt-in `?seed=bank` entries → confirm a match → transfer and expense proposal → Done tab), **Contacts** (list from the books, statement, edit kept after a reload), **Vehicles** (vehicle + journey → £45.00 claim waits in Review). `Runtime.reset(seed)` added to the fixture. |
| `d550834` | Phone: the brief's **390 px** run of Home, Review, Ask, VAT and Settings. It checks there is no sideways scroll and no button is cut off at the edge (the existing smoke test used Pixel 7, 412 px, and checked only scroll). `/invoices`, `/invoices/new` and `/payroll` added to the smoke list. |
| `8e30de2` | Import order in `testmode.py` and its test. The bank-seed test now also checks that a plain reset drops the seeded entries again (the seed is opt-in). |
| `fb587f5` | `docs/DEV.md` described test mode as it was before (calendar unused, VAT defaulting to the gold quarter, no sender or seeds). It now matches the code. README "What works today" e2e row updated to 44 tests. Stale `DEFAULT_TODAY` comment fixed. |

## What remains

- **The CI job has still never run on GitHub.** I read `.github/workflows/e2e.yml` twice against `playwright.config.ts`,
  and it should pick up the new specs unchanged (`act` is not available here). Check the first PR run, including how
  long the job takes.
- **`test.describe.configure({ mode: 'parallel' })` is not used.** Every test resets the runtime's single shared fake
  OneDrive, so tests cannot run in parallel without a separate fake per worker. At about 50 s locally the suite is
  well under the 6-minute budget, so I left it serial.
- **The Review badge in the nav is cached per page path.** Approving a proposal on `/review` does not update the badge
  until you change page, and the cache is not keyed by account. This is minor and I did not change it.
- **The bank seed's events copy `tests/test_bank_gold.py`.** They have a STANDARD VAT code with `vat=0` and net = gross,
  so the VAT boxes are meaningless while the seed is on. Only the Bank spec uses it. The ledger events carry no SAMPLE
  label (there is no field for one); the label is in `evals/gold/bank/expected.json`.
- **Folder names disagree** (this predates the branch): the onboarding tree and Files show `02 Sales invoices` and
  `04 Needs a look`, but invoicing writes to `03 Sales/invoices/` and payroll to `04 Payroll/`. This needs a product
  decision.
- **`/invoices/new` does not read the job's draft lines yet.** The Jobs page now links there, and the user retypes the
  lines (there is a TODO in `JobDetail.tsx`).
- **Ruff could not be run in this session** (it needed approval). I fixed import order by hand.
- **The implementer's `TASK_BRIEF.md` is committed at the repo root.** Move it to `docs/reviews/e2e-all-pages/` with
  this file when merging, as earlier branches did.

## How to verify by hand

Run `uv sync --all-packages`, then `cd apps/web && pnpm install && pnpm exec playwright install chromium && pnpm run e2e`.
Expect 44 passed in about a minute. To click through yourself, start the runtime with
`ACCNOMOS_TEST_MODE=1 PORT=8781 CORS_ORIGINS=http://127.0.0.1:3100 python -m uvicorn app.main:app --app-dir services/runtime --port 8781`
and run `node e2e/serve.mjs` in `apps/web` (after `pnpm run e2e:build`). Open http://127.0.0.1:3100/connect, sign in
(fake account) and create the folder. Then:
- On `/invoices/new`, write an invoice and check that *Send via Outlook* stays disabled until you tick the box.
  After sending, `GET http://127.0.0.1:8781/__test/state` lists it under `sent`.
- Ask "Plan my Thursday" and check the plan shows the 09:00 Harbour Lane meeting.
- Check the phone layout of Home and Settings in a real browser at 390 px wide.
