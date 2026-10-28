# Review: claude/known-fixes

Five known defects, fixed where they live. `claude/marketing`, `claude/profiles` and `claude/accounting-tools` were
not merged to `main`, so each is merged into this branch from `origin` first (merge commits) and fixed on top;
`claude/payment-links` was already in `main`, so its fix is on `main`'s code. One commit per fix; merge fallout has
its own `integration:` commits so the fixes stay readable.

| # | Defect | Commit |
|---|---|---|
| 1 | "Early access / testers" and other pre-launch words in the submission build | `69d9f07` |
| 2 | Home VAT tile shown for personal and non-VAT books; Android More not gated | `aa854b1` |
| 3 | Manual journals with VAT missing from the VAT page | `bf3e6d8` |
| 4 | Stripe/PayPal receipts counted twice through 1200 Bank | `9fd5167` |
| 5 | `test_a_second_press_while_running_or_after_is_the_same_run` flaky | `cbed5a3` |

## 1. Pre-launch wording in the submission build (marketing)

**Cause.** The handover named one leak, "Early access / testers" in `PublicHeader.tsx`'s client chunk: the flag was a
shared constant (`SUBMISSION_MODE` from `lib/public-site.ts`), which the bundler did not fold across modules. Sweeping
for the words found more: `Gmail (coming soon)` rendered in Settings › Automation, the early-adopter form (main's
`EarlyAccessForm`, hidden at run time but shipped in the bundle), the privacy page's early-adopter sections ("before
launch", "launch email"), and the "Notify me at launch" `mailto:` in a JS chunk.

**Design.** Client components test `process.env.NEXT_PUBLIC_SUBMISSION_MODE === "0"` written out in place, which
`next.config.ts` inlines and the bundler folds, so a submission build carries neither the element nor its words.
`EarlyAccessForm` returns before rendering its inner form unless the build is pre-launch or a test build (test builds
keep it: `e2e/early-access.spec.ts` flips the mode per page). Server components use `PRELAUNCH_IN_BUILD` (pre-launch
or test build) around a client `<Prelaunch>` wrapper (`components/Prelaunch.tsx`, hidden unless the page is in
pre-launch mode), so the submission build has the words in neither its HTML nor its RSC payload. The early-adopter
form now sits on the landing page (main had it on the signed-out Home, which the landing replaced).

**Checks.** `e2e/submission-mode.spec.ts` now sweeps every page in `e2e/pages.ts` (signed out and signed in, and the
phone menu opened) over the whole DOM text with scripts removed, the title, meta description and the label
attributes (`aria-label`, `title`, `alt`, `placeholder`). The words are in one list, `scripts/prelaunch-words.mjs`:
`coming soon`, `beta`, `launch`/`launching`/`launches`, `early access`, `early adopter`, `early list`, `testers`. Run
as a script it scans every file of a production export, and CI's `web` job now runs it on `out/`. Before the fix it
found 26 hits in 185 files; after, 0. A `NEXT_PUBLIC_SUBMISSION_MODE=0` build still has them (16 "Early access /
testers", the Gmail button, the sign-up form), so the pre-launch site is unchanged.

## 2. VAT tile and Android More by profile (profiles)

**Runtime.** `GET /books/dashboard` reads `_System/profile.json` with the other reads and answers `vat_applies`
(`"vat" in features`: false for personal books and for a company or sole trader that is not VAT-registered). When it is
false the VAT block is not computed and `vat` is null; it is not listed in `unavailable`. An unreadable profile is the
default profile (a VAT-registered company), the same rule as the gated routes; a 401/403 still propagates.

**Web.** `useVatApplies()` (`components/home/HomeData.tsx`): the dashboard's answer once it has arrived, before that
the profile last read on this device (`lib/profiles.ts`), so a personal profile never shows a VAT skeleton. Today
drops the VAT tile (and its skeleton); the Deadlines card, whose dates are all VAT dates, is not rendered. Signed out,
the sample is a VAT-registered company and keeps both.

**Android.** `Dashboard.vatApplies` (absent from an older runtime = true); Home drops the VAT tile. More is built from
`moreEntries(features)`: Invoices and Payroll need their features, Reports mentions VAT only with `vat`; the features
come from `GET /profile` when the tab opens (null = show everything, as the web does before it knows).

## 3. Journals with VAT on the VAT page (accounting-tools)

**Cause.** The nine box amounts were already right: `compute_vat_return` special-cased adjustments with `vat_box`.
But `accnomos_ledger.vat_side()` returned None for adjustments, and the VAT page counted the entries behind each box by
event kind (`sale` or reversal for boxes 1/6, `purchase` or other reversals for 4/7). A journal moved box 1 by £20
and the page said "0 entries"; box 5 counted every event in the period. Ask's facts (`app/facts.py`) used `vat_side`
too, so its per-side totals left journals out while its box figures included them.

**Fix.** `vat_side` places an adjustment with `vat_box` on that side (+1: its net and VAT are already signed), and
`compute_vat_return` uses it for every event and records `sales_event_ids` / `purchase_event_ids`. The VAT page counts
entries from those (box 5: the entries in the boxes) and lists the journals and adjustments counted
(`adjustments`: name, date, narration, side, signed net and VAT), shown under the boxes with "Box 1 £20.00 · Box 6
£100.00" and a link to Manual journals. A void (dated like the journal while the period is open) shows as the
opposite entry; an automatic reversal into the next period counts there, with the opposite sign.

## 4. Stripe/PayPal through clearing accounts (payment-links, on main)

**Cause.** An approved link payment posted Dr 1200 Bank / Cr 1100 Debtors and the fee Cr 1200 Bank. The provider pays
out later, net and often batched; that statement line is the same money, so matching it as income counted it twice,
and 1200 Bank ran ahead of the statement. HONESTY told users to "mark the bank line as a transfer".

**Design.** Two clearing accounts in the standard chart (current assets, system accounts): **1230 Stripe clearing**
and **1240 PayPal clearing**. The brief suggested 1210/1220; 1210 is already *Cash* in this chart, so the next free
pair is used. Receipts post Dr clearing / Cr Debtors, fees Dr 7900 / Cr clearing. A money-in bank line is matched
as **Payout from Stripe** or **Payout from PayPal** (`POST /books/bank/lines/{id}/payout`): Dr 1200 Bank / Cr clearing
for the line's amount, recorded in `_System/Payments/payouts.json`, audited, and the line matched to that entry.
Unmatching the line posts the entry's reversal. A payout bigger than the clearing balance is refused ("1230 Stripe
clearing holds £0.00 … approve the Stripe payments first"). Unmatched lines whose words name Stripe or PayPal carry a
`payout` hint, and the Bank page offers (and suggests) the action. A recorded clearing payment is never offered as the
payout's match (`check_match` names the payout action instead).

**HONESTY.** PayPal is marked untested against PayPal's real API, sandbox included; the clearing paragraph lists what
it does not cover (other currencies, refunds or disputes paid from the provider balance, reserves, fees on payments
approved before this change).

## 5. The flaky sample-books test (runtime)

**Cause.** Every test in `test_sample_books.py` waited for the background run with `_settle`: at most 2000 GETs 10 ms
apart. The run makes about 11,000 storage calls; on a loaded machine (the reviews record load 30–50 on 2 CPUs) it was
still going when the budget ran out, and the test failed with `still {state: running …}`. That is a race between the
test's clock and the run, not between the app's steps (the app-side race, "done" shown before the file was written,
was fixed earlier, `docs/reviews/ci/REVIEW.md`).

**Reproduced** deterministically by making the fake's writes take 50 ms (so the run outlasts the budget): the old
test fails at step 44 of 54 with exactly that message; the new one passes (53 s). In isolation the old test passed
15/15, and 8/8 with all four cores busy, which is why it only failed in full, loaded runs.

**Fix.** `_Run.stopped` (an `asyncio.Event`) is set whenever the run stops: done, failed, or waiting for a token; a
fresh token clears it before the run goes on. `_settle` waits on that event (and reports a stop in a state it was not
asked for, such as `needs_token`, instead of spinning). The only time limit left is a 900 s guard against a hang.
No sleep was added; the whole module passes (27 tests).

## Integration fallout fixed on the way

- Marketing: `/` is the landing page signed out, so specs that expected the sample Home there moved; `/public/chat`
  joins the public routes list; the docker-compose chat variables had landed after `volumes:` (invalid YAML).
- Profiles: `lib/routes.server.ts` (node:fs) was reached from the client `SiteShell` after both merges and broke the
  build; the root layout reads the page list and passes it down. The test sign-in keeps profiles' accounts and main's
  popup-linked mailboxes. The menu bar shows Personal when Settings › Show personal finances is on (main's switch),
  and specs whose locators met the new menu bar's duplicates (Search, account name) are scoped.
- Accounting tools: `accounting.spec.ts` had never run; its locators are scoped, and the tool tables' scroll boxes
  are `relative` so the sr-only caption no longer widens the page at 360 px.
- The landing page shows main's "Try the demo — no sign-in" (sandbox) button when the runtime runs demos.

## Tests and gates (28 Oct 2026, this container: 4 CPUs, Python 3.13, Node 22, Flutter 3.47.8)

- **Runtime** `cd services/runtime && python -m pytest -q`: **1525 passed, 2 skipped** (4 min 22 s), after every fix
  (the run before the last two integration fixes found 3 failures, all mine: invalid compose YAML from the marketing
  merge and two payout audit sentences, fixed in `e7ced4d`). `tests/test_layout.py` 13 passed after the last commit.
- **Other Python suites**: ledger 65, connectors 49, hmrc-relay 130, evals 324, all passed.
- **ruff** 0.17.3 `check` and `format --check`: clean. **pyright** 1.1.414 on `services/runtime/app`: 0 errors.
- **Web**: `pnpm install --frozen-lockfile`, `eslint .` (0 errors), `tsc --noEmit` clean. Production `pnpm build`
  and `node scripts/prelaunch-words.mjs out`: 228 files, 0 pre-launch phrases; no test-mode code in `out/`.
- **e2e** (`pnpm run e2e:build && pnpm run e2e:test`, `CI=1`, 3 workers, one retry): **320 passed, 0 failed,
  58 skipped (deliberate), 3 flaky** (passed on retry). Of the three, `files.spec` was the layout race below
  (fixed in `9a3b5d4`), the accounting 360 px sweep ran out of its 30 s (now `test.slow()`), and
  `signed-out.spec` `/try` at 1280 px passed on retry with no saved trace. After those commits, `files`,
  `accounting` and `signed-out` ran twice over with retries off: **152 passed**.
  Browser: this container has Chromium 1243 while `@playwright/test` 1.64.1 expects 1248, so the run used a local,
  git-excluded config pointing at the preinstalled headless shell (`/opt/pw-browsers/chromium_headless_shell-1243`).
  With the full Chromium build instead, three invoice specs saw `chrome-extension://…/pdf_embedder.css` requests
  (its PDF viewer) and `keyboard.spec`'s Tab sweep wrapped focus on `/vat`; neither happens with the headless shell
  CI uses.
- **Flutter** 3.47.8 (installed for this run): `flutter analyze` no issues; `flutter test` **279 passed** (includes the
  profiles branch's untested `profile_switch_test.dart` and the new `more_gating_test.dart`).
- **Flaky test**: before, 15/15 alone and 8/8 under CPU load (it only failed in long loaded runs); reproduced
  deterministically with 50 ms writes (old fails at step 44 of 54, new passes); `test_sample_books.py` 27 passed.

**Also found and fixed:** `app/layout.py` raced with itself. The first requests after sign-in (Home, the menu bar's
`GET /profile`, Files) each run the old-folder rename; the loser's move raised `FileNotFoundError`, so
`GET /books/layout` answered 500 and the Files page lost its "old and new side by side" warning. The loser now
re-lists past the request memo and carries on (`180589b`, `9a3b5d4`, with a test that fails without it).

## Sources

- Next.js inlines `env` from `next.config.ts` at build time (the repo's own comment there, and
  `node_modules/next/dist/docs`); the folding was checked by building both modes and scanning the output.
- HMRC VAT (MTD) box rules as already cited in `packages/ledger/src/accnomos_ledger/vat.py` (checked 26 Oct 2026);
  not re-fetched here (developer.service.gov.uk is not reachable from this container).
- No other tax or legal rule was added: the clearing accounts and payouts are bookkeeping, not tax treatment (the
  provider fee stays an exempt expense, as before).

## Risks

- The submission sweep reads DOM text and labels, not the pixels of the landing page's screenshots.
- Android More reads the profile once per app start; a switch takes effect on the next start.
- Negative box 4/1 after a reversal into a later period: HMRC's acceptance of negative values was not re-checked
  (developer.service.gov.uk unreachable from here).
- Clearing accounts cover payouts in GBP only; anything paid from a provider balance needs a journal.
- `keyboard.spec.ts`'s Tab sweep and the chrome-extension request check depend on the browser build; see the gates.
- The three source branches carried work-in-progress handovers; only the five defects and the merge fallout the
  gates exposed were fixed here. Their other open items (e.g. accounting's `ToolsNav` once the menu links settle,
  Contacts' customer/supplier filter) are unchanged.
