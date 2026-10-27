# Review: `claude/loose-ends-1`

Second-agent review of the loose-ends branch (brief: `TASK_BRIEF.md`).

## What was checked

- `pytest -q` in `services/runtime`: 638 passed, 1 skipped (637 before the added test). `services/hmrc-relay`: 102 passed.
  Both were run with an absolute `-o pythonpath` pointing at this checkout, because the shared venv's editable installs can
  point at another lane. `packages/*` were not touched by the branch and were not re-run.
- `apps/web`: `pnpm run build` passes, and `pnpm run lint` shows 0 errors. Its one warning is in `AskThread.tsx`, which this
  branch does not touch.
- Read the whole diff against the brief:
  - `/vat`: the sample is wrapped in `SignedOutOnly`, which renders nothing until the page knows you are signed out, so there
    is no flash for someone signed in. It is labelled "SAMPLE — FICTIONAL COMPANY".
  - Job hours → `INVOICE_DRAFT_KEY` → `/invoices/new?from=job`: lines and customer are prefilled and editable.
  - `invoicing.mark_hours` runs on send, before the sale is posted, and a retried send is safe.
  - The relay takes the last `X-Forwarded-For` hop and never reads `CF-Connecting-IP`.
  - `docs/HONESTY.md` and `docs/REMAINING.md` ticks.
- Money stays in integer pence and the runtime prices the invoice. No secrets or user data are written server-side. The new
  audit rows hold invoice numbers and entry ids only.

## What I fixed

- `ed881c3`: **double billing.** Two drafts made from the same hours (for example, pressing *Invoice these hours* twice)
  could both be emailed. `mark_hours` only skipped the already-billed entries after the second email had gone. Now
  `send_invoice` refuses, before emailing, a draft whose hours are already on another invoice. Test:
  `test_a_second_draft_of_the_same_hours_is_refused_before_it_is_emailed`.
- `927e338`: `docs/DEMO.md` relay test count corrected (100 → 102). The README "Jobs and timesheets" row now names the
  `test_invoicing.py` tests that cover hours → invoice.

## What remains

- **Deliverable 4 not done: `uv.lock` is still stale.** The `accnomos-runtime` entry lists none of numpy, fpdf2 or pillow,
  and the lock has no numpy or fpdf2 package. Running `uv lock` needed approval that was not available here. `docs/HONESTY.md`
  and `docs/REMAINING.md` already say so, accurately. Also, `deploy/Dockerfile.runtime` and `Dockerfile.relay` use plain
  `pip install` and ignore `uv.lock` completely: the brief's "still build from it" assumes something that is not true. Run
  `uv lock` with network access and commit it.
- An invoice made from hours marks every entry on a line even if the user edited that line's hours or rate. Voiding a sent
  invoice does not unmark its hours. Both are documented in HONESTY/REMAINING and not changed here.
- The web side of hours → invoice (sessionStorage hand-off, form prefill, contact lookup) has no automated test. It is
  covered by the build only.
- The "duplicate review items" in the brief's title has no matching deliverable. Nothing was done for it.
- `TASK_BRIEF.md` is committed on the branch (`3abe631`, "wip: checkpoint"). Drop it or squash it before merging if it
  should not ship.

## How to verify by hand

Signed out, open `/vat`: the "SAMPLE — FICTIONAL COMPANY" mock-up shows. Sign in and reload: only the live card with its
period picker and the HMRC connect card show, with no sample flash.

On `/jobs/job?id=…` for a job with unbilled billable hours, press *Invoice these hours*. `/invoices/new?from=job` should open
with the job's customer, one line per person (hours × charge rate) and the teal "Hours from …" note. Change something, save,
then preview and send it to yourself (tick the confirmation). Back on the job, the timesheet shows those entries invoiced
with the new number, and *Invoice these hours* is disabled.

Then repeat with two drafts made from the same hours. Sending the second should fail with "already on invoice INV-…", and
no email should go.

For the relay, `curl` a fraud-header-carrying endpoint through nginx with a forged `X-Forwarded-For: 6.6.6.6` and a
`CF-Connecting-IP`. `Gov-Client-Public-IP` should be your real address.
