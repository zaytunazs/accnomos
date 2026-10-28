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
| `claude/marketing` | Its HANDOVER lists a known failure (`e2e/submission-mode.spec.ts`: the client bundle still contains "Early access / testers") and fixes never re-run; not attempted. |
| `claude/exports` | Runtime green (1581), but its own page fails: `exports.spec.ts` (the Xero manual-journals preview never shows its `*Narration` column), axe **critical** `aria-valid-attr-value` on `/reports/exports` (12× signed out, 69× signed in: `aria-controls="report-preview"` names no element) and a disabled *This VAT period* button that gives no reason. Its HANDOVER says its e2e was never green. |
| `claude/payroll-rti` | Runtime green (1730), but its own never-run `paye.spec.ts` fails. First, the Payroll settings panel (`LivePaye.tsx`, `<details open={!employer.paye_reference}>`) is keyed on the form's draft, so it closes as soon as a PAYE reference is typed (a one-line fix was tried). Then the spec expects `£3,000.00` where the page's `gbp()` prints `£3000.00`, and nothing after that step has ever run. Payroll figures are money: left for its author. |
| `claude/sales-purchases` | Runtime green (1698), but 2 of 4 tests in its own `sales-purchases.spec.ts` fail, **identically on the branch alone** (checked in a separate worktree): a purchase order converted to a bill lands in *needs a look*, not *proposed*; the statement's *Customer* picker never becomes selectable. When it lands, `profiles.spec`'s menu test needs *Sales overview* before *Invoices*. |
| `claude/accounting-tools` | Python green (runtime 1633, ledger 64), but 4 tests in its own never-run `accounting.spec.ts` fail, **identically on the branch alone**: ambiguous locators (two *Sign in* links, three alerts, two *Search* buttons) and a real phone bug, `/accounting/chart` scrolls 248 px sideways at 360 px. |

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

## What remains

- The five branches above, for their authors.
- The keep-alive `ECONNRESET` flake (cause and suggested fix above).
- `submission-3` has no `docs/reviews/` folder.
- The counts quoted in `docs/HONESTY.md` and `docs/submission/JUDGING.md` (runtime 1260, Playwright 208…) predate this
  pass; the table above has the current figures.
