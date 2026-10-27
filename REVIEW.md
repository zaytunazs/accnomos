# Review: `claude/jobs-timesheets`

Task: jobs, staff and timesheets → invoice lines (`TASK_BRIEF.md`).

## What was checked

- `services/runtime`: `pytest -q`: 160 passed before the review, 162 after (2 tests added). This is the only Python package the branch touches.
- `apps/web`: `pnpm run build` passed before and after the changes.
- Read the whole diff. Runtime: `jobs.py`, `routes_jobs.py`, the `job_id` approve edit, the Books.xlsx `Jobs` sheet, `Proposal.job_id`. Web: `/jobs`, job page, Staff editor, Review job picker, runtime client.
- Money: all integer pence. Hours are worked on whole quarters, and `pence_for` rounds half-up in integers. Costs are per person (total quarters × rate), so per-entry rounding cannot drift. The Staff editor converts £ to pence with a 2-decimal regex and `Math.round`.
- Product rules: files live only in the user's folder (`_System/Jobs`, `_System/Staff`, `_System/Timesheets`) and nothing is kept server-side. Staff records hold name and role only. Invoice lines are a proposal that marks nothing. Entries become invoiced only on an explicit, confirmed "Invoice sent" action. No AI is involved in this feature, so the Meta runtime rule does not apply. No synthetic data was added, so no SAMPLE label is needed.
- Wording is UK English throughout ("colour", dd/mm/yyyy, "ex VAT").
- README row against the code: the button labels, routes, file paths and the "not yet run against a real OneDrive" caveat are accurate.

## What was fixed

- `6a660ed` runtime:
  - `POST /jobs/{id}/mark-invoiced` with an empty `entry_ids` used to write an audit line and rebuild Books.xlsx for nothing. It now returns 422.
  - With a hand-edited or broken `jobs.json`, approving with a `job_id` used to give a 500. It now returns an `ApprovalError` (400), and approving without a tag still works.
  - Job `customer_id` and `site_address` now have length limits.
  - Tests added for the empty list, for refusing another job's entries (nothing gets marked), for the site-address limit and for the broken jobs file on approve.
- `69e18fb` web: the job page cleared nothing when hours were added or deleted, so the proposed invoice lines went stale. They are now cleared on add and delete. The server already refused deleted entry ids; this keeps the screen honest.
- (this commit) README: says that "Invoiced" and margin use each person's current charge rate. REVIEW.md added.

## What remains

- **No sales invoicing on main.** Nothing on main sends invoices, so the hook is still a TODO:
  - `routes_jobs.py` `mark_invoiced`: invoicing's send step should call `jobs.mark_invoiced(books, entry_ids, invoice.id)` and the web should stop calling the route itself.
  - `JobDetail.tsx`: link to `/invoices/new`, which should read `INVOICE_DRAFT_KEY` from sessionStorage.
  - Until then, "Create invoice from unbilled hours" only shows the lines (and stashes them in sessionStorage). The user marks hours invoiced by typing an invoice number.
- **Mark-invoiced does not check amounts.** It checks entry ids, billable and not-already-invoiced, but not that hours or rates still match the lines the user saw. An entry edited in another tab between proposing and marking is marked at its new hours.
- **"Invoiced" uses today's rates.** Invoiced value and margin use current charge rates. Rates are not snapshotted on the entry or the invoice, so editing a rate restates past jobs. This is now documented in the README.
- **Closed jobs can still be tagged.** Approve will tag a purchase to a closed job (the web picker only offers open jobs). This was kept on purpose, because a late receipt for a finished job is legitimate.
- **Edits don't rebuild Books.xlsx.** Plain timesheet edits do not rebuild it; marking invoiced, approve and `/books/rebuild` do. This is documented in the `routes_jobs.py` docstring.
- **Timesheet writes are not atomic across files.** A timesheet whose date changes month is written to the new file before it is removed from the old one. A failure in between leaves a duplicate line (never a lost one), and nothing de-duplicates it.
- **No web tests.** The web has no test runner in this repo, so the job page, Staff editor and Review picker were only build-checked, not exercised.
- **Not tried on real data.** Nothing has been run against a real OneDrive or opened in Excel.
- **`TASK_BRIEF.md` is committed** (`0b48188`, "wip: checkpoint"). Drop it or keep it before merging, as the repo convention dictates.

## How to verify by hand

1. Start the runtime and the web app and sign in with a test OneDrive.
2. In Settings › Staff, add "Sam, Carpenter, £18.00 cost, £40.00 charge" and a second person with no charge rate.
3. On /jobs, use *Add job*. On the job page, add 7.6 h for Sam (it should store 7.5), 1 h non-billable, and 2.5 h for the second person.
4. Check the tiles:
   - labour = 7.5×£18 + 1×£18 + 2.5×cost
   - billable value = 7.5×£40 + 2.5×cost (with an "at cost" warning)
5. Click *Create invoice from unbilled hours*. Expect one line per person, and confirm `_System/Timesheets/<yyyy-mm>.jsonl` still shows `invoiced_in: null`.
6. Enter an invoice number and click *Invoice sent: mark these hours invoiced*. Those rows should lose their Delete button, and a second *Create invoice* should say there are no unbilled hours.
7. In Review, approve a receipt with the *Job* picker set. The job's Materials should go up by the receipt's ex-VAT net.
8. Open Books.xlsx and check the `Jobs` sheet matches the job page.
