# Task: Jobs, staff and timesheets → invoice lines

Accnomos monorepo (public; UK English; no secrets; stateless runtime; files in the user's OneDrive). Read first: the invoicing and contacts
task briefs in `~/spark/accnomos/jobs/{contacts_task.md,invoicing_task.md}` and whatever of them is already on main; `routes_books.py`,
`apps/web/src/lib/runtime.ts`.

## Data (user's folder)
- `_System/Jobs/jobs.json`: `[{ id, name, customer_id|null, site_address|null, status: open|closed, created_at }]`
- `_System/Staff/staff.json`: `[{ id, name, role, hourly_rate_pence, charge_rate_pence|null, active }]` (no personal identifiers beyond name/role).
- `_System/Timesheets/<yyyy-mm>.jsonl`: one line per entry `{ id, staff_id, job_id, date, hours (decimal, 0.25 steps), note, billable, invoiced_in: invoice_id|null }`.

## Runtime (`routes_jobs.py`, `jobs.py`)
- CRUD for jobs, staff, timesheet entries; `GET /jobs/{id}/summary` (hours, labour cost, billable value, costs from purchase documents tagged
  to the job — add an optional `job_id` to the approve edits so receipts can be tagged); `POST /jobs/{id}/invoice-lines` → returns proposed
  invoice lines (staff × hours × charge rate, grouped by staff/role) that the web passes into the invoice form; marks entries `invoiced_in`
  when the invoice is sent (hook into invoicing if present, otherwise leave a TODO that the review pass will see).
- Books.xlsx: `Jobs` sheet (job, customer, hours, labour cost, materials, invoiced, margin).
- Tests: hours rounding, cost/charge maths in pence, invoice-line grouping, job summary with and without purchases.

## Web
- `/jobs` list with summary tiles; job page with timesheet entry table (quick-add row: staff, date, hours, note, billable) and
  "Create invoice from unbilled hours"; `/settings` → Staff list editor. Nav entry. README row. `pnpm run build` passes.
- Mobile is out of scope here (a separate Muse task will add quick timesheet entry).

Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
