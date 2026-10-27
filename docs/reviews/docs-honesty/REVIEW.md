# Review: `claude/docs-honesty`

Second-agent review of the honesty pass over the judge-facing docs (`TASK_BRIEF.md`). Reviewed 27 Oct 2026.

## What was checked

- **Tests:** `pytest -q` passes in `services/runtime` (607, including 7 new docs tests), `packages/ledger` (32),
  `packages/connectors` (34) and `services/hmrc-relay` (100). `cd apps/web && pnpm run build` passes after the two web edits.
  The Playwright suite was not run. Flutter was not built, analysed or tested (no SDK here).
- **README "What works today":** one contiguous table, 22 rows with no duplicates, and 9 lines of intro. Every file it cites exists (a script
  checked this, and `test_docs.py` now does too). Spot-checked: e2e count (7 flows + 16 phone pages = 23), 12 sheets
  (`projection.SHEETS`), Android version `0.2.0+2`, 8 Dart test files, every UI label quoted in README and DEMO exists in
  `apps/web/src` or `apps/mobile/lib`.
- **DEMO.md:** the Oct–Dec 2026 numbers match `test_vat_periods.py::test_vat_defaults_to_the_current_period_by_settings`
  (Box 4 `8.65`, Box 7 `43`). The live card text ("Verifier agrees · all N fields match", "Read by Glimmer 30B on your machine") matches `LiveReview.tsx`.
- **ARCHITECTURE.md:** headers and `_System` path constants spot-checked against `services/runtime/app/*.py` and `apps/web/src/lib/runtime.ts`.
- **HONESTY.md:** every bullet was re-checked against the code by three read-only passes, one per group of sections, and I verified each finding before editing.
  Several bullets were copied from older REVIEW.md "What remains" sections and had since been fixed on main.
- **Code diff:** two docstrings (`routes_jobs.mark_invoiced`, `plan_apply`) are accurate. No secrets and no server-side user data.

## What I fixed

| Commit | Fix |
|---|---|
| `65dd596` | New `services/runtime/tests/test_docs.py`. It checks that the README feature table is one table with one row per feature, that every file cited in README/ARCHITECTURE/HONESTY/DEMO/REMAINING exists, and that the ARCHITECTURE sheet list equals `projection.SHEETS`. The brief said docs tests existed; there were none. |
| `30c0d7c` | **Product rule:** `/vat` always renders a static mock-up return (Howdens, "Reviewer's note (Muse Spark)"), even when signed in, and there the global banner is hidden, so fictional data showed with no label. It now carries "SAMPLE — FICTIONAL COMPANY". |
| `a4d0a16` | Removed two "gaps" that were already fixed on main. Books.xlsx text starting `=` is already escaped (`projection._safe_text`, tested), and the SAMPLE banner is already hidden when signed in (`DemoBanner.tsx`), in README, HONESTY, REMAINING and DEMO. The e2e phone list covers 16 pages, not "every page". |
| `6918195` | **Deploy bug:** `deploy/Dockerfile.runtime` had a leftover second `FROM python:3.12-slim`, so the image was built on a floating tag, not the pinned one. Removed it. The hardening test checked only the first `FROM` and now requires exactly one. |
| `2d7ef8c` | The Jobs page told users "Sales invoicing is not in this build yet". It now says invoices don't pick up the hours yet. The TODO now says that `/invoices/new` exists but does not read the draft. |
| `35f4896` | 16 more claims corrected against the code. `deploy/nginx.conf` already strips `CF-Connecting-IP`. The `uv.lock` runtime entry lacks pillow as well. Annual VAT shows "—" tiles, not the sample. Dashboard failures give 401/502/500. A crop note is shown. `/plan/day` can fall back to the server's model. The payroll rates were checked by hand on 27 Oct 2026. `MAX_INLINE` is 3 MB. Ageing ignores due dates rather than "no payment terms". VAT routes use `books.today()`. Triage, reminders and the planner also use models. The SAM fixture path is now correct. Test counts are updated. |
| `aa474a7` | Android Settings said Home uses the saved stagger, but nothing sends it. Only the string changed; it was not built. |

## What remains

- The Playwright e2e suite was not run for this review. The `/vat` label and the Jobs text change are covered only by `pnpm run build`.
- The Android string change (`settings_screen.dart`) has not been compiled: no Flutter SDK here.
- `/vat`'s static mock-up (Howdens figures, "Reviewer's note (Muse Spark)", a "Q3 2026" page subtitle from `sample-vat.ts`) still renders under the live card when signed in. It is now labelled, but it should be shown only when signed out.
- `/invoices/new` does not read `INVOICE_DRAFT_KEY`, so job hours cannot become an invoice in one step, and hours are still marked invoiced by typing the number.
- The Android app still sends no VAT stagger (`RuntimeClient.deadlines(stagger:)` exists but nothing calls it).
- `uv.lock` is stale (no `numpy`/`fpdf2`; the runtime entry lacks `pillow`). Run `uv lock`; not done here, as it needs network access and is outside a docs branch.
- The relay still prefers `CF-Connecting-IP`; it is only safe behind `deploy/nginx.conf`.
- Process claims the repo cannot prove either way, all stated as the maintainers' word: the hand runs on 26–27 Oct, the Play signing hash in Entra, the CI job never having run, and the payroll rates check.
- The implement pass left a commit titled `wip: checkpoint after implement pass` (it only adds `TASK_BRIEF.md`). Squash it or rename it when merging. `TASK_BRIEF.md` at the root can move to `docs/reviews/docs-honesty/` like the others.

## How to verify by hand

Run `pytest -q` in `services/runtime`, `services/hmrc-relay`, `packages/ledger` and `packages/connectors` (607/100/32/34).
`test_docs.py` fails if the README table is split or duplicated, or a doc cites a missing file. Run `cd apps/web && pnpm run build`.
Then `pnpm dev`, sign in, and open `/vat`: the lower mock-up should start with "Below: a mock-up of a finished return, not
your books. SAMPLE — FICTIONAL COMPANY". Open a job with unbilled hours and press *Create invoice from unbilled hours*: the note should no longer
say invoicing is missing. Signed out, `/` should show the dark SAMPLE banner; signed in, it should not, as HONESTY.md now
says. Finally, `grep -c '^FROM' deploy/Dockerfile.runtime` should print `1`.
