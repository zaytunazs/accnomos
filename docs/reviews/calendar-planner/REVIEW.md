# Review: `claude/calendar-planner` (day planner)

Second-agent review of the day planner described in `TASK_BRIEF.md`: CalendarProvider on Graph, `POST /plan/day`,
`POST /plan/day/apply`, "Plan my Thursday" in Ask, and the web pieces (Home *Plan today*, plan card, `/jobs`, Settings).

## What was checked

- **Tests**, run against this checkout: `packages/connectors` 24 passed, `packages/ledger` 15 passed,
  `services/runtime` 289 passed, `services/hmrc-relay` 39 passed. `apps/web` `pnpm run build` passes.
  Note: the shared venv (`~/spark/accnomos/.venv`) has editable installs pointing at `repo-lane-e`, so before the
  fix below `pytest` in `packages/connectors` imported lane-e's code and failed on the new `CalendarEvent`.
- **The diff, read in full**: the planner (code-only ordering and times, quarter-hour slots, no overlaps with busy
  events, lunch/admin rules, Europe/London times including BST), the apply path (re-reads the calendar, 409 on a
  clash, 400 for items off the day or overlapping, idempotent by plan hash, reuses events after a half-finished
  apply, audit line with no personal data), the Graph calendar calls (`/me/calendarView` with UTC `Prefer`,
  paging, cancelled events skipped; `/me/events` with UTC times), the model's rationale (shown only the computed
  plan; any time or figure not in the plan falls back to a code-written rationale), Ask (the model can never emit
  `plan_day`; only code does), web scopes (`Calendars.Read` on first plan, `Calendars.ReadWrite` only on Apply).
- **Product rules**: no user database (applied hashes live in the user's OneDrive `_System/Planner/applied.json`,
  working hours in the browser); AI proposes, user approves (nothing written until Apply); code calculates.
  No secrets, no pence/decimal maths in this feature. UK English in copy and docs.

## What I fixed

| Commit | Fix |
|---|---|
| `a9f06c4` | `packages/connectors` and `packages/ledger` get a `conftest.py` (like `services/runtime`'s) so `pytest` imports this checkout, not another editable install. |
| `66655a4` | **Ask hijacked books questions**: any text with *plan/schedule/organise* and a weekday or *today/tomorrow* became a day plan, e.g. "Should I schedule the supplier payment on Friday?" or "I plan to pay HMRC tomorrow, can I afford it?". Now the verb must lead straight to the day ("plan my Thursday", "schedule tomorrow"). Tests for both directions. |
| `cb8bb5f` | `apply_plan` returned 500 if `applied.json` was hand-edited/damaged (not a JSON object); now treated as empty. New route tests: missing calendar scope (Graph 403) → 401 on both endpoints with nothing created; apply without `X-User` → 400. |
| `38ce502` | `runtime.ts`: the "Jobs, staff and timesheets" doc comment had been left orphaned above the planner types. |
| `10e4cd6` | `docs/PLANNER.md`: the stricter intent rule, how scope errors surface (MSAL consent first; a Graph refusal → 401 shown on the card), working hours kept on the device. |

The README "What works today" row was already accurate (it says "not yet run against a real Outlook calendar"
and "Mileage proposals appear only if vehicles exist (none yet)"), so it is unchanged.

## What remains

- **Not run against a real Outlook calendar or Graph token.** Request shapes are tested against a mock transport only.
- **First-time consent loses the plan.** When `Calendars.Read`/`Calendars.ReadWrite` is not yet granted, MSAL
  redirects to Microsoft (`acquireTokenRedirect`); on return the plan card is gone, so the user has to plan the day
  again and tap Apply a second time. Fixing it needs the pending plan kept in `sessionStorage` across the redirect.
- **Two Applies at the same moment can both create events.** The applied-hash check and the write to
  `applied.json` are not atomic (no lock in a stateless runtime); the double-tap is guarded only by the disabled
  button.
- **Mileage** is a response-only proposal using the first active vehicle; vehicles (`_System/Vehicles`) do not
  exist yet, so this path is exercised only by a test.
- **The rationale model sees calendar event subjects** (the `existing` items' titles) as well as job names. It goes
  only to the user's own configured AI, but it is more than the books Ask sends.
- "Plan a day with these jobs" on `/jobs` sends every open job shown; there is no per-job picker (the runtime
  supports `job_ids`).
- Europe/London only; travel times are rules of thumb by postcode district; only VAT returns count as "due".
- The *Visit length* input caps at 12 h in the web while the runtime accepts up to 24 h (harmless).

## How to verify by hand

Run the runtime and the web app, sign in with a Microsoft account that has a test calendar, and add three open
jobs on `/jobs` with site addresses in two postcode districts (e.g. two in `LS6 …`, one in `LS7 …`, one with a
*Visit length* of 3) and put a busy event at 10:00–11:00 on tomorrow's date in Outlook. On Home tap **Plan today**
(or type "Plan tomorrow" in Ask and follow the *Plan …* button): consent to *Read your calendars* when asked, then
check the timeline groups the LS6 visits together before LS7, has 30/60-minute travel blocks, a lunch between
12:00 and 14:00, never overlaps the 10:00 event, and stays within Settings › Business · working hours. Tap
**Apply**, consent to *Have full access to your calendars*, re-plan and Apply again (see "what remains"), and check
in Outlook that only the new items appear, each titled `[Accnomos] …`, visits carrying the site address and
"Accnomos job <id>" in the body, and that the 10:00 event is untouched. Plan the same day again and confirm the booked
jobs are not proposed a second time (the `[Accnomos]` events show as *In your calendar*); then ask "Should I schedule the supplier payment on
Friday?" in Ask and confirm it answers as a books question, not a plan.
