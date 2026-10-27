# Review: `claude/vehicles-mileage`

Second-agent review of the vehicles, mileage log and HMRC approved mileage allowance work (brief: `TASK_BRIEF.md`).

## What was checked

- `cd services/runtime && pytest -q`: 155 passed before review, 157 after. No other package or service was touched
  (`packages/*` and `services/hmrc-relay` have no changes on this branch), so they were not re-run.
- `cd apps/web && pnpm run build`: passes; `/vehicles` is prerendered.
- Read the whole diff against `origin/main`: `mileage.py`, `routes_vehicles.py`, the approve/inbox/journal/projection/
  schemas/books changes, the web page, the Review picker and the runtime client.
  - Rates live in one table (`RATES` in `mileage.py`) with the gov.uk approved mileage rates page cited; 45p/25p over
    10,000 miles (cars and vans together), 24p motorcycles, 20p bicycles; tax year 6 April–5 April.
  - Money is whole pence: each journey's allowance is rounded half-up once, after a journey crossing 10,000 miles is split.
  - Claims are ordinary proposals (VAT code N, debit 7310, credit 2300 Owner / director loan). They are never posted
    automatically. Edits to them are refused, and `always` (Autopilot) is forced off for them.
  - `vehicle_id` on approve is checked against the vehicles file and must be a business vehicle. A broken vehicles file
    gives a clear `ApprovalError`, skips pre-filling at scan, and leaves the Books.xlsx Vehicles sheet empty.
  - Fuel VAT is kept from the receipt. The fuel scale charge is "ask your accountant" text only.
  - Nothing is stored server-side. Vehicles and journeys go to `_System/Vehicles` and `_System/Mileage` in the user's folder.
  - README row matches the code (it says what is tested and that it hasn't been run against a real OneDrive).

## What I fixed

- `1af830e`: `ExtractedDoc` now accepts the code-only category "Motor — mileage allowance". Without a guard, a model reply
  using it would have been accepted and booked as owed to the owner (credit 2300) rather than paid. `extract_document`
  now turns it into "Sundry" before validation. Test added (fake Ollama call). I also added a test that a rejected claim
  is replaced by a new proposal with a fresh id.

## What remains

- `POST /mileage` accepts `source: "proposal"` from the client. Nothing creates journeys from proposals yet, so the field is
  only a label, but the route could force `manual`.
- The web mileage log can only add and delete journeys. Editing works through `PATCH /mileage/{id}`, but the page has no
  edit control. Vehicles can be added and marked inactive, not renamed or deleted, from the page.
- The Review vehicle picker only shows for purchases when there is at least one active business vehicle (or one is
  pre-filled). It is not shown on the sample (signed-out) Review.
- Pre-filling a vehicle at scan uses the category plus a keyword list (`_VEHICLE_WORDS`). Repairs are only caught through
  "Motor expenses" or MOT/tyre wording.
- `TASK_BRIEF.md` is committed at the repo root (`7e6b5bc wip: checkpoint`). Decide whether it should go to main.
- Not run against a real OneDrive or a real model. Not opened in Excel. `ruff` was not run (the command needed approval
  in this session).

## How to verify by hand

Start the runtime and the web app signed in to a test OneDrive. On **Vehicles**, add a personal car and a business van.
Log a few journeys for the car in the current quarter, including one past 5 April into the next tax year, and check it
moves to the other tax year in the selector. Check the tiles: miles, allowance at 45p, and miles left to 10,000. Press
*Claim this quarter's mileage*. It should say the claim is waiting in Review. In **Review** the card should read
"Calculated by code from your mileage log" with "Owed to you". Press it again and the same claim comes back, brought up
to date, not a second one. Approve it, then try to delete a journey dated before the claim: it should show *Locked*, and
the API should return 409. Undo the claim and the journey can be deleted again. Drop a fuel receipt in the inbox with only
the van active: after scanning, the proposal should already be tagged to the van. Approve it and check that the van's cost
appears on Vehicles and on the `Vehicles` sheet of Books.xlsx after *Rebuild Books.xlsx*.
