# Review: `claude/payrun`, pay runs from timesheets (estimates only)

## What was checked
- `TASK_BRIEF.md` against the five implement commits (75685d8, d2efe7f, c9ab10e, bcfcdcb; 74b801f only adds the brief).
- `services/runtime`: `pytest -q` passed (286 before the review, 288 after). No `packages/*` or `services/hmrc-relay` files were changed, so those suites were not run.
- `apps/web`: `pnpm run build` passed before and after the review; `/payroll` is prerendered.
- I read the whole diff: `payroll.py`, `payroll_rates.py`, `routes_payroll.py`, the `books.py`/`projection.py` hooks, `LivePayroll.tsx`, `runtime.ts`, the nav entry and the README row.
- Product rules:
  - Nothing is stored server-side; everything is written to the user's OneDrive.
  - Code calculates the estimates; no AI is involved.
  - Only an explicit confirm with the provider's actual figures posts to the ledger.
  - The estimate label appears in the JSON, the CSV, Books.xlsx and every web figure.
  - Money is integer pence throughout, and periods are checked against a regex before they reach a path.
- I checked the worked examples by hand: £2,000 gives £190.40 PAYE, £76.20 employee NI and £237.50 employer NI on the pro-rated basis.

## What I fixed
- **44231d7**:
  - **Double posting:** `confirm` used to post its ledger entries and then save the run. If the save failed, the entries stayed in the books while the run was still a draft, so a retry posted them twice. Now every posted entry is undone if anything after posting fails. Tested.
  - **CSV formula injection:** names, roles and notes beginning with `= + - @` are now prefixed with an apostrophe in the export.
  - **Hour totals:** they were printed with `:g`, which rounds to 6 significant figures (12345.25 → `12345.2`). They are now printed exactly. Tested.
- **a84b0d5**: the rates comment said estimates differ from the provider's by "a few pence". HMRC's 1257L tables give £1,048.25 free pay a month, not £1,047.50, so the estimated tax is about 20p a month high. The comment now says so, and the test that claimed to "match HMRC tables" is renamed and explains the gap.
- **3825aee**: the web limits list and the README row now say the same thing, and no longer suggest that salaries or bonuses are "typed in as edits". The only edits are hours and rate.

## What remains
- The estimate pro-rates annual thresholds ÷ 12 (as the brief asked) instead of using HMRC's code-based free pay and rounded monthly NI thresholds. Tax runs about 20p a month high and NI a few pence off. This is stated everywhere, but it is not fixed.
- Rates for 2026–27 in `payroll_rates.py` have not been re-checked against the GOV.UK page from this environment (no network check done).
- Books.xlsx: openpyxl writes any text starting with `=` as a formula. This affects every sheet (supplier names, notes and so on), not just Payroll. It was there before this branch and needs one fix in `projection._table`.
- If someone undoes a payroll ledger entry from outside the Payroll page, the run still shows "confirmed" until it is reopened. Reopen tolerates entries that are already undone.
- No staff on salary: gross is always hours × hourly rate.
- `ruff` was not run (the command needed approval that wasn't available here).
- Not yet run against a real OneDrive or a real payroll provider's import.

## How to verify by hand
1. Start the runtime and the web app. Sign in, and on Jobs add a staff member with an hourly rate and some timesheet hours this month.
2. Open `/payroll` and prepare this month. Check that every figure carries the "Estimate — your payroll provider calculates the actual tax and NI" badge or label.
3. Change the hours to 160 at £12.50 and save. The line should show £2,000.00 gross, £190.40 estimated PAYE, £76.20 employee NI and £237.50 employer NI.
4. Export the CSV. Check that `04 Payroll/<yyyy-mm>.csv` appears in OneDrive, opens cleanly in Excel with £ signs, and has the label and limits above one row per person plus a totals row.
5. Confirm with different "actual" figures. Check the ledger and Books.xlsx: there should be Dr 7000 / Cr 2210 for gross and Dr 7010 / Cr 2210 for employer NI on the pay date, and a Payroll sheet with the actual figures.
6. Reopen the run. Check that two reversals appear and the run is back to draft.
