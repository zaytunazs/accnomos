# Review: landlords and UK property income (branch `claude/landlords`)

Built 28 Oct 2026 from `main` at 9674a64. One cloud session, Linux. UK English.

## What it does

* **A property sub-ledger, not a new profile kind.** Profiles (`claude/profiles`) are not on `main`, so landlord books
  live inside the existing books: a register of let properties, a tag per ledger entry, and settings, all under
  `_System/Property/` (`services/runtime/app/property.py`). Ledger events stay immutable; the tag sits beside them and an
  undo follows the tag of the event it reverses. When profiles merge, a `landlord` kind can switch the same Property
  page on instead of the Settings switch.
* **Per-property tags and HMRC's categories.** Quick entries post to dedicated accounts (4700–4740 income,
  8500–8580 costs) as the user's own approved journals; an approved receipt on an ordinary account (7700 Insurance,
  5000 Materials, 7600 Professional fees …) reaches a property only when tagged, optionally with a category override.
  Categories are exactly the Property Business API 6.0 fields with their SA105 boxes (HMRC's mapping file).
* **Joint ownership.** Owners with shares in basis points; spouses and civil partners are taxed 50:50 unless a Form 17
  declaration is ticked (ITA 2007 s836–837); other joint owners use their shares. Every figure is split by the
  largest-remainder rule, so the owners' parts add up to the penny (property test).
* **Mortgage interest restriction.** Residential finance costs never reduce profit; the estimated tax reduction is
  20 % (22 % from 2027-28, the property basic rate) of the lowest of costs + brought forward, property profit and, if
  given, income above the personal allowance; the rest carries forward. Commercial finance costs stay an expense.
* **Replacement of domestic items:** residential lets only, refused for a first purchase or Rent a Room; sent in the
  annual submission (`costOfReplacingDomesticItems`), not the quarterly expenses.
* **Furnished holiday lettings:** abolished from 6 April 2025. A holiday let is taxed as residential from 2025-26 (with a
  warning); tax years before 2025-26 are refused.
* **Rent a Room** (£7,500 / £3,750 shared) replaces the expenses of those rooms; **property allowance** (£1,000) is shown
  as a comparison only; **consolidated expenses** allowed under £90,000.
* **MTD Income Tax property updates** through the relay, reusing the self-employment design (`claude/self-employment`
  `relay/itsa.py`): same envelope, fraud headers, `confirmed: true`, sandbox-only guard and `RELAY_ITSA_PRODUCTION`
  switch. The scope plumbing (`ALLOWED_SCOPES`, `/hmrc/authorize?scope=`, `relay_itsa_production`) and the web's HMRC
  sessions (`hmrc.ts`) are ported **verbatim** from that branch so the two merge without conflict in those hunks; the
  property routes live in their own module under `/itsa/{nino}/property/…`. Production use: the runtime saves the
  exact bodies as a JSON file in `07 Reports`.
* **Landlord mode** (Settings › Business › *I let property*, saved in the books and mirrored on the device for the
  menu): one simple `/property` page for one or two properties: add a property, record rent or a cost, the year with
  your share, entries (tag untagged ones), and the quarterly update (SA105 boxes, the body, *Save file ready to
  submit*, HMRC sandbox connect and send).
* **Gold generator** `evals/gold/gen_gold_landlord.py`: Qwen names a fictional landlord's world; code fixes every figure
  of six months of agent statements and seven bills; expectations by category, per owner and the API bodies; every
  file carries `SAMPLE — FICTIONAL COMPANY` (em dash). Not run on the Spark yet.

## Sources (checked 28 Oct 2026)

gov.uk, developer.service.hmrc.gov.uk and assets.publishing.service.gov.uk could not be opened from this session
(the proxy refused them). HMRC's API definitions were read from HMRC's own GitHub repositories, the source of the
developer hub; the tax rules from gov.uk **search results** (titles and quoted passages of the pages below).

| Rule | Source |
| --- | --- |
| Property Business API 6.0 paths, schemas, examples, BETA + released in production | github.com/hmrc/property-business-api `resources/public/api/conf/6.0/` (commit e57db0b, 20 Oct 2026), `conf/application.conf` |
| SA105 box for each field | github.com/hmrc/income-tax-mtd-changelog `mapping/csv/sa105_mapping_v1.csv` |
| Obligations `uk-property`; test business | github.com/hmrc/obligations-api conf/3.0; github.com/hmrc/mtd-sa-test-support-api conf/1.0 |
| Finance cost restriction, basic-rate reduction, three limits, carry forward | gov.uk/guidance/changes-to-tax-relief-for-residential-landlords-how-its-worked-out-including-case-studies |
| 22 % property basic rate from 2027-28 | gov.uk/government/publications/changes-to-tax-rates-for-property-savings-and-dividend-income (technical note) |
| Replacement of domestic items relief | gov.uk/guidance/income-tax-when-you-rent-out-a-property-working-out-your-rental-income; Finance Act 2016 s73 |
| FHL abolished 6 April 2025 (1 April for CT) | gov.uk/guidance/letting-out-a-self-catering-holiday-home-in-england-rules-and-regulations; HMRC PIM4170–PIM4185 |
| Spouses 50:50, Form 17 | HMRC manual TSEM9812, TSEM9842–TSEM9864 |
| Rent a Room £7,500 / £3,750 | HS223 Rent a Room Scheme (2026) |
| Property allowance £1,000 | gov.uk/guidance/tax-free-allowances-on-property-and-trading-income |
| Consolidated expenses under £90,000; boxes 44/45 | SA105 notes 2026 |
| Cash basis default up to £150,000 | HMRC PIM1092 |
| MTD thresholds (£50,000 from April 2026, £30,000 April 2027, £20,000 April 2028) | gov.uk MTD for Income Tax collection and news, 5 Oct 2026 (context only, not enforced in code) |

## Tests

| Suite | Result |
| --- | --- |
| `services/runtime` pytest (whole) | 1419 passed, 2 skipped (new: `tests/test_property.py`, 18) |
| `services/hmrc-relay` pytest | 139 passed (new: `tests/test_itsa_property.py`, 9, on HMRC's example bodies) |
| `evals/tests` | 330 passed (new: `test_gen_gold_landlord.py`, 6, including the same answers from `app/property.py`) |
| ruff check, ruff format --check | clean |
| pyright `services/runtime/app` | 0 errors |
| `apps/web`: eslint, tsc | clean |
| e2e | `property.spec.ts` 2 passed; the whole suite: see below |

The runtime tests cover the split (Hypothesis: parts always add up and each is within a penny), spouses vs Form 17 vs
others, register validation, the category mapping and finance costs by use, quarters and the 20/22 % rate, the finance
credit limits, two properties end to end through the routes into the API body and SA105 boxes, consolidated expenses
and brought forward, Rent a Room cap, domestic items refusals, commercial finance costs, tagging a receipt, a category
override and an undo following its tag, untagged entries, pre-2025-26 refusal and holiday-let warning, the property
allowance comparison, the export file in `07 Reports` and the submission record with `matched_books`.

**e2e environment:** this container's Playwright 1.64.1 wanted a browser build that is not installed, so the suite ran
with `executablePath` pointed at the preinstalled Chromium through an uncommitted local config. Full (not headless-shell)
Chromium loads its PDF viewer extension, which the suite's "nothing leaves 127.0.0.1" guard counts as an escaped
request: `invoices.spec.ts` and `invoice-payments.spec.ts` (which preview a PDF) fail for that reason here, unrelated to
this branch. The results of the whole run are listed in the summary of the session; CI (with its own browser) is the
judge.

## Risks and what remains

* Never sent to HMRC's sandbox; the relay is tested only against HMRC's example bodies.
* Tax rules verified through search results, not by reading gov.uk pages in full (see HONESTY).
* Merge with `claude/self-employment`: `relay/main.py` (both add an `include_router` line), `apps/web/src/lib/hmrc.ts`
  (this branch adds a third `property` session to the ported code) and `services/runtime/app/paths.py` will need a
  hand merge of a line or two. Its `itsa.py` maps 4000–4899 to turnover and 8000–8099 to depreciation and would count
  the property accounts (4700–4740, 8500–8580) in self-employment too: skip accounts in `property.BY_ACCOUNT` there.
* Merge with `claude/profiles`: a `landlord` kind (or a `property` feature) should drive the menu instead of the
  device flag; `_System/Property/` stays as it is.
* Cash basis not modelled; no capital allowances, losses, non-resident landlord tax, foreign property; the third
  limit of the finance credit needs the user's other income.
* Android: not done (the brief's Android parts are for other tasks; this one has none).
