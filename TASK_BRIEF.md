# Task: Vehicles, mileage log and HMRC approved mileage — computed by code

Accnomos monorepo (public; UK English; no secrets; stateless runtime; files in the user's OneDrive). Read first: `routes_books.py`,
`approve.py`, `pipeline.py` (where proposals get categories), `packages/ledger/.../events.py`, `apps/web/src/lib/runtime.ts`,
the jobs task brief (`~/spark/accnomos/jobs/jobs_timesheets_task.md`) for the `job_id` tagging convention.

## Data (user's folder)
- `_System/Vehicles/vehicles.json`: `[{ id, name, registration (optional, user-entered), kind: car|van|motorcycle|bicycle, owned_by: business|personal, active }]`
- `_System/Mileage/<tax-year>.jsonl`: `{ id, vehicle_id, date, from, to, miles (0.1 steps), purpose, job_id|null, source: manual|proposal }`

## Rules (code, with tests; cite the HMRC approved mileage rates page in a comment and keep rates in one table):
- Personal vehicle used for business: approved mileage allowance — cars/vans 45p first 10,000 business miles in the tax year then 25p;
  motorcycles 24p; bicycles 20p. Tax year 6 April–5 April. The allowance is an expense proposal (category "Motor — mileage allowance",
  VAT code N) that the user approves like any other; never posted automatically.
- Business-owned vehicle: fuel/parking/repairs receipts are tagged to the vehicle; no mileage allowance (actual costs instead); show
  a running cost-per-vehicle summary. Fuel VAT: keep the existing VAT code from the document; show (not compute) the HMRC fuel-scale-charge
  note as "ask your accountant" text — do not implement scale charges.
- Extraction tagging: when a proposal's category is fuel/parking/tolls/repairs and the user has exactly one active business vehicle, the
  code pre-fills `vehicle_id`; otherwise the Review card offers a picker (web: `review/*`; add `vehicle_id` to approve edits).

## Runtime (`routes_vehicles.py`, `mileage.py`)
- CRUD vehicles; CRUD mileage entries; `GET /mileage/summary?tax_year=` (miles by vehicle, allowance so far, threshold crossing date);
  `POST /mileage/propose-allowance?tax_year=&period=` → creates an expense proposal for the period's allowance (idempotent per period).
- Books.xlsx: `Vehicles` sheet. Tests: thresholds across the 10,000-mile boundary, tax-year boundaries, idempotent proposals.

## Web
- `/vehicles` page: vehicles list, mileage log with quick-add, summary tiles, "Claim this quarter's mileage" button → appears in Review.
- Nav entry; README row; `pnpm run build` passes.

Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
