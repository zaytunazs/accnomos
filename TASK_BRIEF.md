# Task: Calendar & day planner — read the calendar and jobs, propose an efficient day, create events on approval

Accnomos monorepo (public; UK English; no secrets; stateless runtime). Read first: `packages/connectors/.../base.py` (CalendarProvider
interface exists), `msgraph.py`, `services/runtime/app/jobs.py` (jobs with site addresses; if not merged yet, read
`~/spark/accnomos/jobs/jobs_timesheets_task.md` and code against it behind a feature check), `ai/ask.py`, `apps/web/src/components/home/Deadlines.tsx`.

## Goal
"Plan my Thursday" (typed, spoken, or the Home *Plan today* button) → the runtime reads the user's calendar for that day
(`Calendars.Read`, incremental), the open jobs (site postcode/address), VAT/filing deadlines, and proposes a schedule:
ordered visits grouped by postcode district (first half of the UK postcode — no maps API), realistic blocks (job estimate or default 2 h),
travel gaps (30 min same district / 60 min otherwise), lunch, admin time for anything due. The model only writes the plain-English
rationale; the ordering and times are computed by code. On approval, events are created (`Calendars.ReadWrite`, requested then) with
`[Accnomos]` in the subject and the job id in the body; mileage entries are pre-filled as *proposals* if vehicles exist.

## Runtime
- CalendarProvider: `list_events(day)`, `create_event(subject, start, end, location, body)` on Graph `/me/calendarView` and `/me/events`;
  fake implementation for tests.
- `POST /plan/day {date, constraints?: {start, end, max_visits}}` → `{ plan: [{kind: visit|travel|lunch|admin|existing, start, end, job_id|null,
  title, location|null}], rationale_md, warnings[] }` (never writes).
- `POST /plan/day/apply {date, plan}` → creates the non-existing items as events; returns ids; audit line. Idempotent per date+plan hash.
- Tests: grouping by district, no overlaps with existing events, constraints respected, apply creates only new items.

## Web
- Home: *Plan today* button → plan card (timeline list, rationale, Apply / Discard). `/jobs` page: "Plan a day with these jobs". Settings
  (Business): default working hours. `pnpm run build` passes; README row; `docs/PLANNER.md`.
Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify with a real calendar.
