# Review: `claude/batch-tax` (pre-merge batch of the tax, payroll and small Muse branches)

A pre-merge helper branch so the integrator gets one merge instead of twelve. Made from `origin/main` at `10dd43f`
(28 Oct 2026), each branch merged in the order below with `--no-ff`, conflicts resolved keeping both features and every
test, the branch's targeted tests run after each merge, then all gates from the cloud brief. Nothing here is new
product work except where a merge needed glue (listed per branch). No branch was still moving: after the last merge
every source branch head was re-fetched and was already in this branch (no session was still pushing).

## Branches merged

| # | Branch | Head merged | Conflicts | Targeted tests after the merge |
|---|---|---|---|---|
| 1 | `claude/cash-basis` (carries `claude/self-employment`: it is built on it) | `4fbdf6552244556232ee136e3f89845c5c417590` | `AppNav.tsx`, `lib/hmrc.ts`, `app/paths.py` | runtime `test_cash_basis` + `test_itsa` + paths/profile 94 passed; relay 172 passed |
| 2 | `claude/vat-schemes` | `e864546b325012a78694629ea1c7dd4b99e73890` | `HomeData.tsx`, `SettingsPanels.tsx`, `app/main.py`, `app/routes_reports.py` | ledger 76 → 77 (with the new test); runtime VAT/schemes/reports/dashboard/ask/cash basis 178 passed |
| 3 | `claude/cis` | `dd9355d6e07a0c92061b3d7969fe9f33ac12a7e7` | `e2e/pages.ts`, `AppNav.tsx`, `app/audit_view.py`, `tests/test_security_routes.py` | runtime `test_cis` + security + VAT schemes 91 passed; ledger 83; evals 332 |
| 4 | `spark/cis-gold` (on top of `claude/cis`) | `5674552bea01807bd2001e6912b849d0e8e47038` | none | evals 332 passed |
| 5 | `claude/landlords` | `f5286125b37e4d2295b20912d3c525bf3b49e608` | `e2e/pages.ts`, `AppNav.tsx`, `lib/hmrc.ts`, `docs/ARCHITECTURE.md`, `docs/HMRC.md`, `relay/main.py`, `app/paths.py` | relay 181; runtime property + security + ITSA + paths 124; evals 338 |
| 6 | `spark/landlord-gold` (on top of `claude/landlords`) | `40d1520d2b667db0fbfa7e644e606e6330469343` | none | evals 338 passed |
| 7 | `claude/payroll-finish` (contains all of `claude/payroll-rti` `3cbcbc48a2c977ba64c070b4b8c8ee7b0faa31b7`, which it supersedes; not merged separately) | `ef35d2d6bb255d25594cb43e77035df2beb92849` | `README.md`, `ActionCard.tsx`, `lib/runtime.ts`, `docs/ARCHITECTURE.md`, `app/actions.py`, `app/schemas.py` | payroll/PAYE/RTI/pension/overtime + actions/ask/month-end/security 420 passed + 1 fixed (below); then 263 with profiles |
| 8 | `muse/mileage-rate` | `cff1337cc1fa1456159a7f0be7f1d19ae4737448` | none | run with #9 |
| 9 | `muse/private-split` | `0bf776b9fb2a353bcbafa2820aa0703849f2da6e` | `app/approve.py` | mileage/approve/private/business use/bank/payroll/audit/seed 243 passed, 1 skipped; `test_integration` 1 |
| 10 | `muse/payment-chasing` | `179f17b6dde1eb818b9b6e7a194d13870399706f` | `app/routes_invoices.py` | chasing/contacts/invoicing/security/audit/payments 269 passed |
| 11 | `muse/bank-ai-travel-2` | `1a5086ea6a0cd4a89f1dca15edb3294d4cb3a164` | none | bank/AI 119 passed |

## How each conflict was resolved

1. **cash-basis.** Menu: main's profile feature filter and Personal entry kept, the self-employment filter added
   (`withBadges(review, features, personal, selfEmployed)`); `/self-employment` sits in *Money* before `/month-end`.
   `lib/hmrc.ts`: `relay` stays exported (self-employment calls it) **and** keeps main's demo guard; `startConnect(kind)`
   keeps the demo stand-in token, now saved under the session's own key. `paths.py`: `ITSA` added beside main's
   archive, backups and trash constants.
2. **vat-schemes.** Both settings panels (`SelfEmployedSetting`, `VatSchemeSettings`) and both hash anchors; both
   routers in `main.py`; `routes_reports.py` imports both `cash_basis` and `LedgerEvent`; Home keeps the AI warm-up and
   takes the scheme branch's comment. **Duplication removed (as asked):** VAT cash accounting built its own list of
   payments per document from the settlement; it now reads `cash_basis.document_money`, the money the income tax cash
   basis already counts (payments, matched bank lines, overpayments applied, dated when the money moved). This also
   fixes a difference between the two: the scheme's list counted a *credit note's* credit applied to an invoice as a
   payment (dated when applied), although no money moved and the engine already folds the credit note into the
   invoice. New test `test_document_money_is_money_only_and_dated_when_it_moved`. Also fixed: the ledger property test
   `test_property_standard_spans_change_nothing` could draw a purchase with net 0, which `Line` refuses (failed
   intermittently); it now skips that draw.
3. **cis.** Page lists and menus keep everything (`/cis` under *Work*); audit labels keep `close` and `cis-reader`;
   the security allow-lists keep main's AI-provider-chain wording plus `ai/cis_read.py` and both sets of public routes.
   **Glue:** the CIS branch added `reverse_charge_vat` to the standard VAT engine, but the VAT schemes engine
   (merged just before) ignored it, so a reverse-charge bill disappeared from boxes 1 and 4 whenever any scheme was
   saved. The schemes engine now carries it: standard accounting gives exactly `compute_vat_return`'s boxes (tested);
   cash accounting and the flat rate count it on the invoice date (box 1; box 4 only outside the flat rate) and the
   return carries a warning to check it against HMRC's reverse charge guide. That treatment could not be re-read on
   gov.uk from this session (the host is not reachable), so it is listed in `docs/HONESTY.md`. Three new ledger tests.
5. **landlords.** Menu: profile features, Personal, self-employment and the landlord *Property* entry all kept;
   `useLandlordOn` moved into `lib/property.ts` next to `landlordOn`, mirroring main's `usePersonalOn` in
   `lib/personal.ts` (the landlord branch had its own copy of `usePersonalOn` in the menu). `lib/hmrc.ts`: the third
   `property` session (sharing the Income Tax tokens) plus main's demo guards. Relay: both routers
   (`itsa`, `itsa_property`); the landlords branch carried the same self-employment scope plumbing in `oauth.py`,
   `routes.py` and `settings.py`, which merged identically. `paths.py`: `ITSA` and `PROPERTY`. Docs: both sections.
7. **payroll-finish.** Action kinds: Ask's `pay_overtime` beside the month-end close's `match_bank_line` and
   `close_month` (schemas, executors, web types, action card details and titles). README and ARCHITECTURE rows
   kept from both. **Glue:** main's security sweep found `GET /payroll/paye/starter-code` answering without a Graph
   token; the whole `/payroll/paye` router is now gated on the profile's `payroll` feature like `/payroll` (personal
   books get a 404 with the sentence), which also requires books. `test_profile` checks `/payroll/paye/setup` too.
9. **private-split.** `final_journal` is async (the business-use split reads the invoice profile) and still returns
   a pay run's own journal unchanged; a pay run refuses edits, so it is never split.
10. **payment-chasing.** `routes_invoices.py` imports `require_feature` (main) and the to-do helpers (chasing).

**Main's menu bar.** Signed in, `main` navigates with the menu bar in `lib/nav.ts` (`TopBar.tsx`), which none of
the branches knew about, so their pages were unreachable from it and the property and self-employment specs failed.
The Tax group now has *Self-employment (MTD Income Tax)* (sole traders, or anyone with Settings › I am self-employed
on), *Property (landlords)* (while landlord mode is on) and *CIS (construction)* (business books); `NavItem` gained
`deviceSwitch`. The two specs open the Tax menu. `e2e/vehicles.spec.ts` expects 55p a mile (`muse/mileage-rate`
changed the rate but not the spec).

Also added: `/self-employment` to the e2e page sweep list (`e2e/pages.ts`), which no branch had done, and
`e2e/submission-wording.spec.ts` (below).

12. **origin/main again** (`971cacc`, `claude/spend-ai` merged meanwhile): conflicts in `e2e/pages.ts`, `AppNav.tsx`,
    `ActionCard.tsx`, `lib/runtime.ts`, `app/actions.py`, `app/routes_ask.py`, `app/schemas.py`. Ask now has both
    `pay_overtime` and `add_to_shopping_list` (intent kinds, action words, prompt, model output fields, intents,
    executors, cards, web types); Buying pages and the batch's pages are all in the lists; Ask's default period stays
    the VAT scheme's current period (`default_period` no longer imported). Targeted Ask/actions/shopping/spending/
    overtime/month-end/security/VAT schemes tests: 306 passed. Then `ruff format` on three merged files.

## Gates (28 Oct 2026, Linux, this branch)

| Gate | Result |
|---|---|
| `services/runtime` `pytest -q` | 1959 passed, 2 skipped (1895 before the second main merge) |
| `packages/ledger` | 83 passed |
| `packages/connectors` | 49 passed |
| `services/hmrc-relay` | 181 passed |
| `evals` | 338 passed |
| `ruff check .` / `ruff format --check .` (0.17.3, as CI) | clean |
| `pyright` 1.1.414 (`services/runtime/app`, ledger, connectors) | 0 errors |
| `pnpm exec eslint .`, `tsc --noEmit` | clean |
| `pnpm run e2e:build` | built (test mode, submission mode 1) |
| `pnpm run e2e:test` (`CI=1`, 3 workers, one retry) | 324 passed, 58 skipped, 0 failed, 0 flaky (11.4 min) |

E2E was run with a local, uncommitted config override pointing Playwright at the session's preinstalled Chromium
headless shell (build 1243): the lockfile's Playwright 1.64.1 wants build 1248, which this container does not have.
(The full Chromium binary instead loads its PDF viewer extension, which the specs' "no request leaves 127.0.0.1"
check rightly flags; the headless shell does not.)

**Submission mode.** The e2e build is a submission build (`NEXT_PUBLIC_SUBMISSION_MODE` unset = 1). No source file
the batch changed in `apps/web/src`, `services/runtime/app` or the relay contains "coming soon", "beta", "early access"
or "launching" in user-facing text (the one hit is a relay docstring quoting HMRC's API status); the static HTML of
`/cis`, `/property`, `/self-employment`, `/payroll` and `/month-end` has none; and the new
`e2e/submission-wording.spec.ts` (2 tests, passing in the run above) loads `/self-employment`, `/cis`, `/property`, `/payroll`, `/vat`, `/settings`,
`/contacts` and `/bank` signed out and signed in with books (landlord and personal switched on) and finds none.

## Risks and what is not checked

- **Reverse charge under a VAT scheme** (cash accounting, flat rate): code's treatment is not verified against gov.uk
  from here; each such return warns. Standard accounting is unchanged and tested.
- **`muse/mileage-rate`** moves cars and vans to 55p a mile from 2026-27, citing ACCA (checked 28 Oct 2026). That was
  not re-checked here against HMRC's own rates page (gov.uk unreachable); the integrator should confirm it before
  `main`, because it changes every mileage claim and the demo seed's figures.
- `claude/cash-basis` brings all of `claude/self-employment` with it; if the integrator merges `claude/self-employment`
  separately it is already here.
- The ITSA, property and payroll features are sandbox / file-only as each branch's own review states; nothing in the
  merge changes that.
