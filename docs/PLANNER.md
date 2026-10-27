# Day planner

"Plan my Thursday" — typed or spoken in Ask, the Home **Plan today** button, or **Plan a day with these jobs** on
`/jobs` — proposes a working day from the user's Outlook calendar, their open jobs and any VAT return that is due.
**The ordering and the times are computed by code.** The model only writes the plain-English rationale, and code
checks that too. Nothing is written to the calendar until the user taps **Apply**.

## Flow

1. **Ask** (`POST /books/ask`, and `/books/ask/voice` after transcription): code spots a plan request
   (`app/planner.py` `plan_intent`: *today*, *tomorrow*, a weekday, *next* + weekday, or `YYYY-MM-DD`) and answers
   with a `plan_day` action for that date, without calling the model. The app links it to `/?plan=YYYY-MM-DD`, and
   Home opens the plan.
2. **Propose** (`POST /plan/day`): the runtime reads the day from `/me/calendarView` (`Calendars.Read`, asked for
   the first time the user plans a day) and `_System/Jobs/jobs.json`, then builds the plan. It **never writes**.
3. **Apply** (`POST /plan/day/apply`): the app asks for `Calendars.ReadWrite` only now. Each new item becomes an
   event via `/me/events`.

## The rules (all in `services/runtime/app/planner.py`)

| What | Rule |
|---|---|
| Which jobs | Open jobs (or only `job_ids` when sent) whose site address has a UK postcode. No postcode → a warning, not planned. Jobs that already have an `[Accnomos]` event that day (found by `Accnomos job <id>` in the event body) are left out. |
| Grouping | By postcode district: the outward code (`LS6` of `LS6 2AB`). There is no maps API, so the district stands in for distance. |
| Choosing | Whole districts first, biggest first, up to `max_visits` (default 5, at most 12). The rest → a warning. |
| Order | Districts in order of area letters, then number (`LS1`, `LS6`, `LS7`, `LS12`, `M1`), so the route sweeps instead of zig-zagging; within a district, by job name. |
| Visit length | The job's *Visit length* (`estimate_hours`), else 2 h. |
| Travel | 30 min before the first visit and between visits in the same district; 60 min when the district changes. |
| Lunch | 30 min starting 12:00–13:30. It goes before the first visit that would otherwise push it past 14:00, or in the first free slot once the visits are placed. If a long visit only fits without lunch, the visit wins and there is a warning. |
| Admin | 60 min for a VAT return due within 7 days (`vat` in the request, from Settings › VAT periods), after the last visit if it fits, otherwise the first free hour. |
| Existing events | Shown as `existing` and never moved. Visits, travel, lunch and admin never overlap them, unless the event is shown as *free* or *working elsewhere*. If there is an all-day *out of office* event, nothing is planned. Other all-day events only produce a warning. |
| Times | Europe/London, on the quarter hour, inside the working hours (`constraints.start`/`end`, default 08:00–17:30; Settings › Business · working hours). |

## API

```
POST /plan/day        {date, constraints?: {start, end, max_visits}, vat?: {stagger | start_month, months}, job_ids?}
  -> {date, plan: [{kind: visit|travel|lunch|admin|existing, start, end, job_id|null, title, location|null}],
      rationale_md, warnings[], plan_hash, model, fallback_reason}
POST /plan/day/apply  {date, plan}   (needs X-User)
  -> {date, plan_hash, event_ids[], created[{title, start, event_id, reused}], already_applied, mileage_proposals[]}
```

Headers are the same as `/books/*` (`X-Graph-Token`, `X-Account-Kind`). The AI headers are optional on
`/plan/day`.

## Rationale

`app/ai/plan.py` shows the model only the computed plan: local times, titles, districts, the travel rules and the
warnings. It asks for `{"rationale_md"}` through the same backends as Ask. Code rejects the reply if it quotes a
clock time that is not in the plan, or any other figure that is not in the facts (for example a guessed mileage).
In that case, or with no AI set up, or if the model fails, code writes the rationale itself and
`fallback_reason` says why.

## Apply: what gets written

- **Events**: every non-`existing` item, including travel and lunch, so the time shows as busy. The subject is
  `[Accnomos] <title>` and the location is the site address. The body is `Accnomos job <id>` (visits only) plus
  `Planned with Accnomos for <date> (plan <hash>)`. Reminders are off.
- **Idempotency**: `plan_hash` is a SHA-256 of the date and the items, ignoring order and how the UTC offset is
  written. Applied hashes are kept in `_System/Planner/applied.json` in the user's OneDrive (the last 60). Sending
  the same plan again returns the same event ids and touches nothing. If an earlier apply stopped halfway, the
  retry reuses events with the same subject and times instead of creating duplicates.
- **Safety**: the runtime reads the calendar again first. If a busy event now overlaps a new item, it answers 409
  ("Your calendar has changed … Plan the day again") and creates nothing. Items must fall on the date and must not
  overlap each other (400).
- **Audit**: one `plan_applied` line in `_System/audit/<yyyy-mm>.jsonl`.
- **Mileage**: only when `_System/Vehicles/vehicles.json` lists vehicles. Vehicles are a later feature, so this
  is a feature check. Each visit then gets a mileage *proposal* in the response (vehicle, job, from/to district,
  `miles: null` for the user to fill in, because there is no maps API). Nothing is saved for mileage.

## Limits

- Travel times are rules of thumb, not routing. Two districts with neighbouring numbers are not always neighbours.
- The trip to the first visit is assumed to take 30 min, because no base address is stored.
- Only the default calendar is read and written. Recurring events are read as their occurrences on that day.
- Only VAT returns count as "due"; other filing deadlines are not tracked yet.

Tests: `services/runtime/tests/test_planner.py` (grouping, order, travel, no overlaps, constraints, lunch, admin,
intent, rationale checks, routes, apply idempotency, retry, conflict, mileage) and
`packages/connectors/tests/test_calendar.py` (Graph request shapes against a mock transport, and the fake).
