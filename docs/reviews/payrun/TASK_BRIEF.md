# Task: Pay runs prepared for the user's payroll provider (estimates only, clearly labelled — not RTI filing)

Accnomos monorepo (public; UK English; no secrets; stateless runtime; files in the user's OneDrive). Read first: the jobs/timesheets
work (`services/runtime/app/jobs.py`, `_System/Staff/staff.json`), `projection.py`, `apps/web/src/lib/runtime.ts`.

## What this is (and is not)
Accnomos does **not** run payroll or file RTI. It prepares a pay run from timesheets so the owner can hand clean numbers to their payroll
provider (or HMRC Basic PAYE Tools), and records staff costs in the books once the owner confirms what was actually paid.
Every screen and file must say "Estimate — your payroll provider calculates the actual tax and NI".

## Data (user's folder)
- `_System/Payroll/runs/<yyyy-mm>.json`: `{ period_start, period_end, pay_date, lines: [{ staff_id, hours, rate_pence, gross_pence,
  est_paye_pence, est_ee_ni_pence, est_er_ni_pence, est_net_pence, notes }], status: draft|confirmed, confirmed_gross_pence|null }`.
- Rates table in code (`payroll_rates.py`) for the current UK tax year with the source URL in a comment: personal allowance, basic/higher
  thresholds, NI primary threshold and rates, secondary threshold and employer rate. Monthly pro-rating; no tax codes other than the
  standard one (state this limit). Student loans, pensions, statutory pay: out of scope (state it).

## Runtime (`routes_payroll.py`, `payroll.py`)
- `POST /payroll/runs/prepare {period}` from timesheets × staff rates; `GET /payroll/runs`; `PUT /payroll/runs/{period}` (edit lines);
  `POST /payroll/runs/{period}/export` → CSV (one row per employee: name, hours, gross, est. deductions) saved to `04 Payroll/<period>.csv`;
  `POST /payroll/runs/{period}/confirm {actual_gross_pence, actual_er_ni_pence}` → posts staff-cost ledger events (gross wages, employer NI)
  and marks confirmed. Books.xlsx: `Payroll` sheet.
- Tests: pro-rating, thresholds, export shape, confirm posts balanced events, estimates flagged.

## Web
- `/payroll`: period picker, prepared lines table with editable hours/rate, estimate badge everywhere, Export CSV, Confirm (with the actual
  figures typed in). Nav entry; README row stating the limits plainly; `pnpm run build` passes.

Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
