# Review: `claude/audit-trail`

Second-agent review of the audit trail task (`TASK_BRIEF.md`): `GET /audit`, web `/audit`, Android *Audit trail* in More, docs.

## What was checked

- `services/runtime`: `pytest -q`, 823 passed and 1 skipped, before and after the fixes (the range cap is two new assertions in an existing test). No other
  Python package or service was touched by the branch.
- `apps/web`: `pnpm run build` is clean (`/audit` prerendered); eslint on the changed files is clean; the full Playwright suite
  (`e2e:build` + `playwright test`) gives **170 passed**, including `audit.spec.ts` (three actions, then who-chips, the What filter,
  CSV export, signed-out sample), the phone smoke and axe on `/audit`.
- Read the whole diff. `audit_view.py` covers every `books.audit(` kind in `app/` (a test enforces this), and every refs key it
  reads matches the writer's key. Pence go through `money()`. It reads only, never writes: one test compares storage before and
  after. A missing token gives 401. Unparseable lines are skipped. `audit/autopilot/` is not read, so there are no duplicates
  (approve.py writes the main log for Autopilot postings too). The signed-out sample is covered by the global
  "SAMPLE — FICTIONAL COMPANY" `DemoBanner`, and a sample CSV carries the label as its first line. UK English throughout.
- Android: read `audit_screen.dart`, the `RuntimeClient.audit` call and the tests. It is a thin client: one GET, errors caught,
  lines grouped by local day.

## What I fixed

- `55b2a84` runtime: `GET /audit` refused nothing on range length. `from=0001-01-01` meant ~24,000 storage reads per request.
  It now returns 422 above 366 days (`audit_view.MAX_DAYS`), with a test.
- `ac7c6f5` web: `/audit` now says "Choose at most a year" instead of sending a range the runtime refuses.
- `e8c4789` docs: the e2e counts in the README and `docs/DEV.md` were stale (114, 38/74). They are now 170 (88 desktop, 80 phone,
  2 demo), as measured today.
- `6c6bc3c` docs: `ARCHITECTURE.md` now states the 366-day cap. It no longer claims that `/audit` and the dashboard are the only
  readers of the log (`actions.py` reads its own log so an action never runs twice).

## What remains

- **Android not built or tested**: there is no Flutter SDK here, so `flutter analyze` / `flutter test` (including the new
  `home_more_test.dart` cases) have never run. The README already says so.
- **UTC day boundaries**: the runtime filters `from`/`to` by UTC day, while the web and Android apps group by London/local day.
  In British Summer Time, a line written between 00:00 and 01:00 on the first day of the range is left out. Documented in the
  README row; not fixed.
- **"Planner" is not an actor**: no `agent:planner` writer exists. The Planner chip filters `plan_*` lines, which are the user's
  own *Apply plan* actions (shown as *You* with a Planner badge). This is documented in ARCHITECTURE; when a real planner agent
  writes lines, the chip should switch to `actor=planner`.
- **Ledger event refs have no page to link to**: rows link to the Review card, the invoice or the Files folder only. `/files?path=`
  opens the folder that holds the file, not the file itself.
- **Proposal names**: the "Screwfix £12.00" wording needs `list_proposals()` (one extra read of every proposal file whenever a line
  in range names a proposal). Fine at today's sizes, but it does not scale.
- **Real OneDrive never exercised**: only fake storage and the e2e look-alike Graph have been used.
- `TASK_BRIEF.md` was committed to the repo root in `2d59434` ("wip: checkpoint"). Drop it before merging if briefs should not live
  in the tree.

## How to verify by hand

Start the runtime and the web app in test mode (`docs/DEV.md`), sign in, and create the books folder. Add a vehicle and a journey on
`/vehicles`, then approve a receipt on `/review`. In Settings, under *Audit log*, click *Open the audit trail*. Today should show
"Added a vehicle", "Logged a journey: … miles" and "Posted <supplier> £… to the ledger" with a *You* chip, and "Read … and
proposed an entry" with a *Reader* chip. *Review card* should go to that card. Click *Autopilot* (expect nothing in this range).
Set What to *Mileage* (only the journey shows), then press *Export CSV* and open the file: no SAMPLE line, the columns start
`ts,actor,actor_kind,who,event,summary`. Set From to more than a year before To and check the warning appears and no request is
sent. Sign out and reload `/audit`: you should see the black "SAMPLE — FICTIONAL COMPANY" banner and the sample day of Wednesday
14 October 2026. Check that no row has an edit control.
