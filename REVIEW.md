# Review: `claude/integration-review`

Second-agent review of the integration pass over `main` (brief: `TASK_BRIEF.md`). 27 Oct 2026.

## What was checked

- **Tests**: `pytest -q` in `services/runtime` (271 passed), `services/hmrc-relay` (39), `packages/ledger` (31),
  `packages/connectors` (19). `apps/web`: `pnpm run build` passes, all 17 routes generated.
  `flutter analyze` **not run**: Flutter is not installed on this machine.
- **Diff, read in full** (`git diff origin/main...HEAD`, 40 files):
  - VAT fix: `reverses_sale` now looks for a *debit* to Sales, which is what `approve.reversal_of` actually posts
    (every line swapped). No other module still uses the old `credit and Sales` test (checked by grep);
    `facts.side` uses the shared helper.
  - Audit format: every `books.audit(...)` call site now passes `user:<email>` or `agent:<name>`. Nothing reads the
    old flat Autopilot audit keys or the old `actor == "autopilot"`. The web Review page keys on
    `proposal.decided_by == "autopilot"`, which did not change.
  - Settings headers: `X-User` and `X-Business-Name` are read only through `require_user`, `optional_user` and
    `business_name`.
  - Route coverage: every runtime route (`@router.*`, `/health`, `/ai/test`) has a call in `runtime.ts` and in
    `runtime_client.dart`. Each new web call (`proposal`, `deleteJob`, `deleteStaff`, `updateTimesheet`,
    `updateMileage`) hits an existing route with the right verb. The Dart query names match the FastAPI parameters
    (`as_of`, `from`/`to`, `month`, `stagger`/`start_month`/`months`/`today`, `tax_year`/`period`).
  - Bank "Confirm all exact": the new penny check compares `events[].amount_pence` with `line.amount_pence`.
    The runtime sends both as signed bank movements (`routes_bank.EventBrief`), so the comparison is right.
  - Mobile navigation: 4 `IndexedStack` children match 4 destinations now that the placeholder Files tab is gone.
    Web `AppNav` links only to pages that exist.
  - `POST /mileage` now forces `source: "manual"`; there is a test for it.
  - No secrets, tokens or user data are written server-side. Sample labels are unchanged.
- **Docs**: `docs/ARCHITECTURE.md` (layout table, header table, audit actors) checked against the code, and
  `docs/AUTOPILOT.md` against the new audit shape. Every row in the README "What works today" table is backed
  by `docs/REMAINING.md` and the tests.

## What I fixed

- `0086824` test: Ask's facts count an undone sale against sales, and an undone purchase against purchases,
  using `approve.reversal_of`. Until now the shared reversal rule was tested only with a reversal built by hand
  in the ledger package.
- `f4d4a2f` runtime: when the Books.xlsx rebuild after an Autopilot approval failed, it was audited as
  `user:autopilot`, which breaks the documented `user:`/`agent:` format. `rebuild_safely` now takes the actor,
  like `audit()`. The test covers both actors.
- `8572384` docs: updated the README test count (271). `REMAINING.md` no longer gives a call count ("43")
  that does not match the code (52 calls in the new Dart section). Recorded the fix above.

## What remains

- `flutter analyze` has not been run on `apps/mobile`, including the ~370 new lines in `runtime_client.dart`.
  I read them and found no type errors, but that is no substitute for the analyser. Run it before merging if you can.
- The web bank "Confirm all exact" penny check has no automated test (the web app has no unit tests).
  It was checked by reading the code only.
- In key mode, `AiConfig` still falls back to the server's `META_API_KEY` when the user sends no key
  (Medium in `docs/REMAINING.md`). This is a product decision (operator key vs user key), so I did not change it.
- Everything else open is in `docs/REMAINING.md`. Above all: most features have run only on fakes, not on a
  real OneDrive.

## How to verify by hand

Run `pytest -q` in `services/runtime`, `services/hmrc-relay`, `packages/ledger` and `packages/connectors`; all should
pass (271/39/31/19). Then run `cd apps/web && pnpm run build`. Next, start the runtime and the web app, sign in, and
upload a sample sales invoice and a receipt to `00 Inbox`. Scan, approve both, then use Undo on the sale. `/vat`
should show Box 1 and Box 6 back at their earlier values, with Box 4 unchanged. Open `_System/audit/<yyyy-mm>.jsonl`
in OneDrive: every line should have `ts`, `actor` (`user:…` or `agent:…`), `action` and `refs`. On `/bank`,
import `evals/gold/bank/barclays.csv`. *Confirm all exact matches* should skip any suggestion whose amounts differ
by a penny.
