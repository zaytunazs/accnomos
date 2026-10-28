# Integration review: 28 Oct 2026

The integrator merged the reviewed feature branches into `integration` one at a time. Each merge was followed by every
gate, and `main` was fast-forwarded only when the gates passed locally **and** GitHub Actions CI (10 jobs, Flutter
included) was green on the same commit. Pushing `main` deploys the website (`deploy-web.yml`, only when `apps/web/**`
changes); every deploy below succeeded.

## Reached `main`

| # | Branch | `main` after | CI run | Site deploy |
|---|---|---|---|---|
| 0 | `integration` as handed over (main + security-3, property-tests, ci, submission-3, mailboxes, files-archive, early-adopters) | with payment-links, below | | |
| 1 | `claude/payment-links` | `9674a64` | 40643452100 | 40644026907 ✓ |
| 2 | `claude/demo-sandbox` | `0cabb4e` | 40647463065 | ✓ |
| 3 | `claude/ai-providers` (with the sample-books race fix) | `8e2426f` | 40658181296 | 40659125334 ✓ |
| 4 | `claude/profiles` | `c41a931` | 40665658673 | 40666779195 ✓ |
| 5 | `claude/month-end` | `10dd43f` | 40669063247 | 40670116710 ✓ |
| 6 | `claude/spend-ai` | `971cacc` | 40676711451 | 40677841377 ✓ |
| 7 | `claude/self-employment` | `935520b` | 40685000936 | 40686135507 ✓ |
| 8 | `muse/bank-ai-travel` | `418c93f` | 40695798305 | no web change |
| 9 | `muse/android-personal` | `29baf0c` | 40697276232 | no web change |
| 10 | `claude/research-design` (code/CSS and docs) | `8c2e945` | 40701428438 | 40702837606 ✓ |
| 11 | `claude/teaser` | `38aed93` | 40703260850 | no web change |

Every merged branch's `REVIEW.md` / `HANDOVER.md` from the repo root is now in `docs/reviews/<branch>/`. Four branches
arrived without a review; the integrator reviewed them and wrote one: `bank-ai-travel`, `android-personal`,
`research-design` and `teaser`. `submission-3` (docs only, merged before this pass) has no review folder.

## Not merged, and why

Rule: a branch whose own tests fail, or that is clearly unfinished, is listed here, not merged. Each was merged on
`integration` locally, gated, and the merge was dropped (nothing was pushed).

| Branch | Why |
|---|---|
| `claude/marketing` | First pass: its HANDOVER listed a known submission-mode failure. **Merged in the second pass** inside `claude/known-fixes`, which fixes it. |
| `claude/exports` | Runtime green (1581), but its own page fails: `exports.spec.ts` (the Xero manual-journals preview never shows its `*Narration` column), axe **critical** `aria-valid-attr-value` on `/reports/exports` (12× signed out, 69× signed in: `aria-controls="report-preview"` names no element) and a disabled *This VAT period* button that gives no reason. Its HANDOVER says its e2e was never green. |
| `claude/payroll-rti` | Superseded by `claude/payroll-finish`, which reached `main` inside `claude/batch-tax`. First-pass finding, for the record: its never-run `paye.spec.ts` failed (the settings panel closed while typing; `£3000.00` vs `£3,000.00`). |
| `claude/sales-purchases` | Runtime green (1698), but 2 of 4 tests in its own `sales-purchases.spec.ts` fail, **identically on the branch alone** (checked in a separate worktree): a purchase order converted to a bill lands in *needs a look*, not *proposed*; the statement's *Customer* picker never becomes selectable. When it lands, `profiles.spec`'s menu test needs *Sales overview* before *Invoices*. |
| `claude/accounting-tools` | First pass: its own `accounting.spec.ts` failed (ambiguous locators; `/accounting/chart` 248 px sideways at 360 px). **Merged in the second pass** inside `claude/known-fixes`, which fixes both. |
| `muse/property-reader-2` | Not queued, and not finished for merging: it changes the property reader's prompt and code checks *after* the Spark run its `report.md` shows, so the published numbers would not describe the code. It should merge after its own Spark re-run. Its merges of older `main` also left a duplicate import and a stray `);` in `TopBar.tsx`. |

None of these branches changed on origin after it was evaluated (checked at the end).

## Gates (local, Linux, Python 3.13, `uv sync --all-packages --all-extras`)

Commands as in the brief: `pytest -q` in `services/runtime`, `packages/ledger`, `packages/connectors`,
`services/hmrc-relay`, `evals tests`; `ruff check` + `ruff format --check` (ruff **0.17.3**, the version CI and
`docs/DEV.md` pin; the container's own ruff 0.16.9 reports one extra isort finding in `tools/seed_demo.py` that 0.17.3
does not); pyright 1.1.414; `apps/web`: `pnpm install --frozen-lockfile`, `eslint .`, `next typegen` + `tsc --noEmit`,
`pnpm run build`, `e2e:build`, `e2e:test` with `CI=1` (3 workers, one retry). Final green run per merge:

| After | runtime | ledger | connectors | relay | evals | ruff / pyright | e2e passed (58 skipped each time) | flaky |
|---|---|---|---|---|---|---|---|---|
| payment-links | 1401 | 49 | 49 | 130 | 324 | clean / 0 | 245 | 0 |
| demo-sandbox | 1430 | 49 | 49 | 130 | 324 | clean / 0 | 251 | 1 |
| ai-providers | 1464 | 49 | 49 | 130 | 324 | clean / 0 | 260 | 0 |
| profiles | 1483 | 49 | 49 | 130 | 324 | clean / 0 | 264 | 0 |
| month-end | 1502 | 49 | 49 | 130 | 324 | clean / 0 | 272 | 0 |
| spend-ai | 1566 | 49 | 49 | 130 | 324 | clean / 0 | 296 | 0 |
| self-employment | 1612 | 49 | 49 | 172 | 324 | clean / 0 | 298 | 0 |
| bank-ai-travel | 1633 | 49 | 49 | 172 | 324 | clean / 0 | 297 | 1 |
| research-design | 1633 | 49 | 49 | 172 | 324 | clean / 0 | 298 | 0 |

Runtime skips 2 every time (the slow Hypothesis profile; the seed against a real Graph token). Flutter has no SDK in
the container: it ran in CI's `flutter (analyze, test)` job before every `main` push (291 tests on the final commit).
`android-personal` and `teaser` change no Python runtime or web code: their gate was the full CI run (all 10 jobs) on
the integration commit, plus local ruff and pyright. The local e2e used the preinstalled Chromium 1243 through a
symlinked `PLAYWRIGHT_BROWSERS_PATH` (Playwright 1.64.1 asks for 1248), as `docs/reviews/ci/REVIEW.md` describes.

**Flaky, retried once and passed:** `contact-duplicates.spec.ts` (after demo-sandbox) and `payroll.spec.ts` (after
bank-ai-travel), both `socket hang up (ECONNRESET)` on a fixture's API request to the test runtime. Most likely Node
reuses a keep-alive connection just as uvicorn's 5 s keep-alive timeout closes it; starting the e2e runtime with
`--timeout-keep-alive 75` in `playwright.config.ts` should end it (not done here).

## Fixed while integrating

Conflicts were resolved keeping both sides' features; each merge commit lists them. Beyond that:

- **Leftover conflict markers on the handed-over `integration`** (from the ci and early-adopters merges) in
  `docs/submission/JUDGING.md` and `services/runtime/tests/test_security_routes.py`; JUDGING keeps main's restructured
  version, and it and `REMAINING.md` now say the e2e suite runs in `ci.yml`.
- **security-3's guard tests vs later branches.** Public routes listed with reasons (early-access sign-up, Stripe and
  PayPal browser callbacks, `/ai/health|calls|warm`, the PAYE starter-code lookup); new HTTP modules (`ai/chain.py`,
  `ai/config.py`, `routes_ai.py`) and the chain's `c.base_url` checked to be server-env bases only.
- **`/files` date filters** (files-archive): Chromium tabs into a date field's calendar button, where the field is not
  `:focus-visible` and only a 1 px box shows. The field is ringed on `:focus-within`; the keyboard spec allows a date
  field's four stops.
- **Demo sandbox vs linked mailboxes:** a demo session with `X-Mailbox-Token` would have built a real Graph client; now
  a 403 (test in `test_demo.py`).
- **The sample-books race** (`test_a_second_press_while_running_or_after_is_the_same_run`, intermittent on every
  branch under load), fixed with the ai-providers merge. The verdict depended on the background seed finishing within
  2000 polls of 10 ms. `_settle` now waits on the run's own task, and the test holds the run's writes on an event until
  the second press has been answered, instead of sleeping 1 ms per write, so "still running" is certain. No assertion
  changed; a 600 s guard stops only a real hang. It could not be reproduced here even CPU-starved (polls and seed slow
  down together on one loop); the branches that saw it reported "20 s poll" on machines at load 30–50 with OOM kills.
- **`/ai/warm` refused its first ping on a young host** (found by CI): the once-a-minute gate counted from
  `_last_warm = 0.0`, so a runner whose monotonic clock read under 60 s answered "already on its way". Now `None`;
  regression test with a 12 s clock.
- **Concurrent folder renames:** two requests at once (two tabs, or the menu bar's `/profile` beside the Files page) both
  moved `03 Bank statements` and one failed, so `GET /books/layout` was a 500 and Files lost its "side by side" card.
  `layout.migrate` now treats a vanished source as another request's rename (interleaving test).
- **Profiles × mailboxes:** a mailbox linked in Settings shares MSAL's cache, so the profile switcher listed it as a set
  of books. Mailbox-only accounts are recorded and left out unless also a profile (e2e test). The test MSAL fake now
  has both sides' accounts.
- **Profiles' menu bar × device switches:** Personal (any kind of books, while Settings' switch is on) and
  Self-employment (only with "I am self-employed" or a known profile that has the feature) show as the sidebar shows
  them. personal, self-employment, connect and demo specs follow the menu bar; DEMO.md step 1 points at the Account
  menu for the AI line.
- **Self-employment × demo:** `relay()` stays refused in the demo sandbox; the Income Tax connect stores the demo
  stand-in token for its own session kind.
- **Ask intents from three branches** (spend-ai's shopping list, month-end's cards, and the quote kinds tried with
  sales-purchases) unioned in kinds, prompt, word filter, model output, Intent and executors.
- Smaller: `/judges` added to the page sweeps and its text no longer repeats the sample label; `/models` scroll table
  focusable and named; the footer keeps Settings last; `PRODUCTION.md` sections renumbered (AI chain 7, price search
  3b); an ARCHITECTURE table row rejoined; android-personal's version **0.3.7+12** (it claimed 0.3.6+11, already used
  by the mailboxes list); teaser's build script brought under the repo's ruff.

My own slips, caught before `main`: three merges dropped a closing line where both sides' additions met (fixed in
the next commit each time); one e2e run tested a stale build after the web build failed (the gate script now skips
e2e when the build fails); one commit went in with a ruff format issue, which CI caught and the next push fixed.

## Second pass (afternoon of 28 Oct)

The same rules applied: merge one branch at a time, run every gate, and push `main` only when CI was green on the same
commit. Before each merge that changes a page visible to the submission, the built site was searched with
`NEXT_PUBLIC_SUBMISSION_MODE=1` (its default) for "coming soon", "beta", "early access" and "launching". After
`known-fixes` that search finds 0 hits in HTML and 0 in JS, and it stayed at 0/0 for every later merge. `briefs` holds
task text only and was never merged.

| # | Branch | `main` after | CI run | Site deploy |
|---|---|---|---|---|
| 12 | `claude/accountant` | `90cddb55` | 40710331980 | 40711658296 ✓ |
| 13 | `claude/import-history` | `dbe7ec6f` | 40715387956 | 40717096113 ✓ |
| 14 | `claude/bank-feeds` | `9257f42f` | 40721540777 | 40722991866 ✓ |
| 15 | `claude/known-fixes` (brings `claude/marketing` and `claude/accounting-tools`, which it fixes) | `2f3f95eb` | 40727214647 | 40728969165 ✓ |
| 16 | `claude/batch-tax`, as one branch (cash-basis, vat-schemes, cis, spark/cis-gold, landlords, spark/landlord-gold, payroll-finish in place of payroll-rti, muse/mileage-rate, muse/private-split, muse/payment-chasing, muse/bank-ai-travel-2) | `43f6e10d` | green after one fix (below) | 40740211764 ✓ |
| 17 | `muse/cis-eval` | `9272c8b6` | 40744420233 | no web change |
| 18 | `spark/cis-eval-runs` (plus the /cis label fix below) | `f3a8db81` | 40747808603 | 40749547420 ✓ |
| 19 | `muse/property-reader` with `spark/property-eval-runs` (its Spark run) | see the last row of the gates table | | no web change |

The integrator wrote a review wherever a branch arrived without one: `docs/reviews/cis-eval/`, `cis-eval-runs/` and
`property-reader/`. The Spark figures were **recounted from `results.jsonl`**, not copied from the summaries. The CIS
reader is fully exact on 111 of 120 documents (92.5%), with 0 refusals; checks are exactly right on 112 of 120. The
property reader is fully exact on 89 of 108 (82.4%) against a 1.9% generic baseline, but scores 0 of 6 on insurance
schedules and 0 of 6 on mortgage statements.

| After | runtime | ledger | connectors | relay | evals | e2e passed | flaky (passed on retry) |
|---|---|---|---|---|---|---|---|
| accountant | 1664 | 49 | 63 | 172 | 324 | 308 | 0 |
| import-history | 1728 | 49 | 63 | 172 | 324 | 315 | 0 |
| bank-feeds | 1757 | 49 | 63 | 172 | 324 | 317 | 1 |
| known-fixes | 1835 | 65 | 63 | 172 | 324 | 386 | 0 |
| batch-tax | 2161 | 101 | 63 | 181 | 338 | 409 | 3 |
| cis-eval | 2161 | 101 | 63 | 181 | 352 | 411 | 1 |
| property-reader | 2167 | 101 | 63 | 181 | 353 | 411 | 1 |

ruff 0.17.3 and pyright stayed clean throughout. The flaky tests were: on bank-feeds, the signed-out `/` *Speak*
button was briefly disabled without a reason; on batch-tax, `files-manage` hit `ECONNRESET`, the PAYE RTI table was
slow, and the signed-out `/cis` label count was wrong (that last one turned out to be real, see below). On
cis-eval, `paye.spec.ts` (the long PAYE flow) failed once. On property-reader, and on CI for cis-eval-runs, a
`marketing.spec.ts` test sometimes did not find the *Ask about Accnomos* dialog right after the click.

### Fixed while integrating (second pass)

- **Demo sandbox vs new outside providers.** The new `demo.refuse_external(what)` dependency answers 403 when
  `X-Demo-Session` is present. It covers Stripe/PayPal connect, online-payment start and bank-feed start/connect
  (parametrised test). Sharing with an accountant is also refused in a demo, and `runtimeHeaders` sends the demo
  headers before any client context.
- **The known-fixes merge** dropped `POST /public/chat` from the public-route allow-list; it is back.
- **batch-tax:**
  - The VAT return is now one code path for both schemes. Reverse-charge VAT counts on both sides, and VAT journals
    (adjustments with a box) count under every scheme, including cash accounting (two new ledger tests).
  - Approving keeps `tracking`, and a payroll run is never Autopilot's.
  - At 360 px, `/payroll` scrolled 8 px sideways on CI's fonts (the report picker); it now fits.
- **Signed-out `/cis` showed the sample label twice** (CI run 40745987742, and flaky locally). The sample card
  repeated the banner's "SAMPLE — FICTIONAL COMPANY" and rendered after the signed-in check, so the sweep counted 1 or
  2 depending on timing. The card no longer repeats it, so the banner is the one label, as the rule says. No test
  changed.

## What remains

- `claude/exports` and `claude/sales-purchases`, for their authors; `muse/property-reader-2` after its Spark re-run.
- The keep-alive `ECONNRESET` flake (cause and suggested fix above).
- The public *Ask about Accnomos* dialog sometimes opens too late for `marketing.spec.ts` (two different tests, local
  and CI). It passed on retry each time; the cause has not been looked into.
- `submission-3` has no `docs/reviews/` folder.
- The counts quoted in `docs/HONESTY.md` and `docs/submission/JUDGING.md` (runtime 1260, Playwright 208…) predate this
  pass; the table above has the current figures.
