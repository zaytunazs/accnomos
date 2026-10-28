# What UK small businesses ask of bookkeeping software (2025–2026), and where Accnomos stands

Desk research, 28 Oct 2026, by Claude (a parallel run by Muse is in `FEATURES_MUSE.md` on `muse/research-features`;
the comparison is `FEATURES_COMPARISON.md`). Research only: no product code was changed.

## How this was done, and what it cannot show

- **Sources:** AccountingWEB *Any Answers* threads, the Xero Product Ideas board, QuickBooks UK and Sage community
  forums, OpenRent, LandlordZONE, UK Business Forums, Electricians Forums, MoneySavingExpert, Trustpilot and App Store
  pages, vendor pricing pages, GOV.UK and the HMRC Developer Hub. Three research passes (forums; reviews and prices;
  HMRC rules) were merged here and the coverage column checked against the code on `main` and the feature branches.
- **No Reddit.** The search tools refuse reddit.com, and no UK Reddit thread could be read. Nothing here quotes Reddit;
  someone should check r/smallbusinessuk, r/UKPersonalFinance, r/UKAccounting and r/LandlordUK by hand before
  quoting "what Reddit says".
- **Most pages were read through a cached copy** (Exa), because direct fetches to gov.uk, xero.com, quickbooks.intuit.com,
  freeagent.com and sage.com were blocked from this session. Links marked *(snippet)* were seen only as a search
  excerpt, not read in full. Prices and Trustpilot scores move; each carries the date it was seen.
- **"Frequency" is not prevalence.** It is the number of independent threads or sources that turned up in a limited
  search. A request seen in eight places is better evidenced than one seen once, but neither number says how many
  users have the problem.
- **Forum bias.** AccountingWEB is accountants talking about clients; Xero Ideas is Xero users; Trustpilot's positive
  reviews are mostly invited and praise named support staff. Sole traders who never post are under-represented.
- **Budget 2026 was delivered today (28 Oct 2026).** Any MTD, mileage or penalty change announced in it is not in
  this file. Re-check §1 rows 1–6 and the MTD notes before quoting them.

## A finding to fix first (a wrong figure on `main`, not a feature)

**HMRC raised the car and van mileage rate from 45p to 55p a mile for the first 10,000 business miles, backdated
to 6 April 2026** (25p after 10,000 is unchanged; motorcycles 24p, bicycles 20p). Sources: GOV.UK *Increasing
mileage rates* (published 17 Jun 2026),
https://www.gov.uk/government/publications/increase-to-approved-mileage-allowance-payments-amaps-and-self-employed-simplified-mileage-rates/increasing-mileage-rates;
*Simplified expenses: vehicles*, https://www.gov.uk/simpler-income-tax-simplified-expenses/vehicles (table "Flat rate per mile for 2026-2027 tax
year: 55p"). Both read on 28 Oct 2026.

Accnomos still uses 45p for every tax year: `services/runtime/app/mileage.py:63-64` (`Rate(45, 25, 10_000)`), and the
copy on `apps/web/src/components/vehicles/LiveVehicles.tsx:145,220`, `apps/web/src/app/vehicles/page.tsx:16` and
`apps/web/src/app/how-it-works/page.tsx:135`. Every 2026-27 claim it proposes is about 18 % low on the first 10,000
miles. No branch has changed it. **Size S; before the deadline.** The rate table needs a per-tax-year key (45p up to
2025-26, 55p from 2026-27), and HMRC said rates after 2026-27 would be set at Budget 2026, so check that too.

---

## 1. Top 25 pain points and requests

Coverage key: **main** = on `main`; **branch** = built on a branch not yet merged (named); **partly**; **no**.
Who: ST = sole trader, LL = landlord, TR = trades (builders, joiners, electricians), MB = micro-business / limited
company, AC = accountant or bookkeeper.

| # | Pain point or request | Who | Frequency signal | Sources (1–3) | Accnomos coverage |
|---|---|---|---|---|---|
| 1 | **Yearly price rises and features locked to higher tiers.** Xero up every September (Ignite £16→£18, Grow £37→£39, Comprehensive £50→£55 from 1 Sep 2026, multi-organisation discount removed); QuickBooks £26 (2022) → £47 (2025) on one user's plan; invoice caps, payroll and multi-currency gated by tier; introductory 90 %-off periods that cliff-edge | AC, MB, ST | High: 6+ sources, 2024–26, both vendors | [QuickBooks community "Insulting increase"](https://quickbooks.intuit.com/learn-support/en-uk/other-questions/insulting-increase/00/1516553) (Dec 2024); [AccountingWEB, QuickBooks rises](https://www.accountingweb.co.uk/node/227559) (Nov 2025); [1Office, Xero UK 2026 rise](https://1office.co/blog/xero-uk-price-increase-2026/) (Aug 2026, snippet) | **No pricing exists yet.** Structurally the cost base is low: no Accnomos database, books in the user's OneDrive, models on the user's key or local hardware (`docs/ARCHITECTURE.md`). See §4 |
| 2 | **MTD for Income Tax quarterly updates that just work.** Submission failures, "re-authorise with HMRC" loops and API outages around the first deadline (7 Aug 2026) and the second (7 Nov) | ST, LL, AC | High: 5 sources, Jul–Oct 2026 | [AccountingWEB, QuickBooks MTD error](https://www.accountingweb.co.uk/any-answers/quickbooks-mtd-submission-error) (Jul 2026, snippet); [AccountingWEB, TaxCalc on the day](https://www.accountingweb.co.uk/any-answers/mtd-filing-and-taxcalc-today) (Aug 2026, snippet); [ICAEW, how the first submission went](https://www.icaew.com/insights/tax-news/2026/aug-2026/first-mtd-income-tax-submission-how-did-it-go) (Aug 2026) | **Branch `claude/self-employment`**: cumulative updates, obligations, HMRC calculation and final declaration through the relay, **sandbox only, never run against HMRC**. HMRC is not granting production access to new 2026-27 quarterly-update products (Developer Hub banner, quoted in that branch's `REVIEW.md`), so the realistic target is the April 2027 cohort |
| 3 | **Sole traders' figures on the cash basis.** Cash basis is HMRC's default for sole traders from 2024-25, so quarterly figures should count money when it moves | ST, TR | Requirement, not a complaint: GOV.UK | [GOV.UK cash basis](https://www.gov.uk/simpler-income-tax-cash-basis) | **No.** Reports and the self-employment summary are "as approved" (accruals-like); the branch's own `REVIEW.md` says "for most real sole traders the numbers would be wrong to send until a cash-basis view exists" |
| 4 | **Mapping ledger accounts to HMRC's SA103/SA105 boxes is confusing**; defaults dump everything in "other expenses" (Box 29) or show turnover as zero | ST, LL, AC | Medium: 2 threads, Aug 2026 | [AccountingWEB, mapping Xero codes for MTD](https://www.accountingweb.co.uk/any-answers/problems-mapping-xero-acc-codes-to-hmrc-for-mtd) (Aug 2026, snippet); [QuickBooks community, turnover zero](https://quickbooks.intuit.com/community/making-tax-digital-29/my-client-has-added-various-sales-invoices-and-paid-them-off-when-he-has-received-the-payment-they-are-not-showing-on-the-mtd-for-itsa-submission-dates-are-correct-375548) (Aug 2026, snippet) | **Partly, branch `claude/self-employment`**: each figure shows its SA103F box with drill-down to every ledger line; the mapping is a heuristic on account codes and names, not reviewed by an accountant (its `REVIEW.md`) |
| 5 | **Joint-owned property: split one set of records 50/50 (or by any share) and file for each owner** | LL, AC | High: 6+ sources | [AccountingWEB, MTD for landlords with joint banks](https://www.accountingweb.co.uk/any-answers/mtd-for-landlords-with-joint-banks) (Oct 2025); [Xero Ideas, multiple MTD returns from one org](https://productideas.xero.com/forums/967127-practice-tools/suggestions/46020607-uk-tax-support-for-multiple-mtd-returns-from-one) (marked done Mar 2026); [Sage community, jointly owned properties](https://communityhub.sage.com/gb/sage-accounting-and-individual/f/making-tax-digital/265565/mtd---jointly-owned-properties) (snippet) | **No.** No property income at all (the self-employment branch says "no property income"); no ownership share anywhere |
| 6 | **Landlords want something lighter than a full ledger**: a spreadsheet plus bridging software; "£12 to £30 per month feels quite a lot for four submissions a year" | LL, AC | High: 5+ sources | [OpenRent community, MTD preparation](https://community.openrent.co.uk/t/making-tax-digital-from-april-2026-how-are-you-preparing/89638) (May 2026, snippet); [LandlordZONE, MTD software](https://forums.landlordzone.co.uk/c/general-discussions/recommendations-for-mtd-software) (Jan 2026, snippet); [AccountingWEB, free/cheap bridging](https://www.accountingweb.co.uk/any-answers/mtd-free-cheap-bridging-software-recommendation) (Feb 2026, snippet) | **No.** Books.xlsx is an output (generated, do not edit); nothing imports a user's own spreadsheet |
| 7 | **CIS for subcontractors**: invoices show gross, materials and the deduction; the bank shows only the net, so income has to be grossed up by hand; cheap plans omit CIS | TR, AC | Medium: 2–3 sources, 2026 | [AccountingWEB, CIS subcontractors in Xero for MTD](https://www.accountingweb.co.uk/any-answers/processing-cis-subcontractors-in-xero-for-mtd-itsa) (Jul 2026); [QuickBooks, fixing MTD errors (CIS not in summaries)](https://quickbooks.intuit.com/learn-support/en-uk/help-article/website/fixing-errors-making-tax-digital-income-tax/L4ozbNPWI_GB_en_GB) (snippet); [GOV.UK, CIS subcontractor](https://www.gov.uk/what-you-must-do-as-a-cis-subcontractor) | **No** (no CIS anywhere; the self-employment branch lists "no CIS") |
| 8 | **CIS on quotes, and CIS after retentions** (Xero: requested since 2019, "It's why I switched over to QuickBooks"; CIS worked out before the retention, needing journals) | TR, AC | Medium: one board thread with 8+ commenters in 2025–26, plus 2 retention ideas | [Xero Ideas, quotes add CIS](https://productideas.xero.com/forums/967115-invoices-quotes/suggestions/45162304-quotes-add-cis?page=1); [Xero Ideas, CIS after retention](https://productideas.xero.com/forums/939198-for-small-businesses/suggestions/46612057-cis-deduction-after-retention-subcontractor-invo) | **No.** Quotes exist on **branch `claude/sales-purchases`** (QU-0001…, convert to invoice) but without CIS or retentions |
| 9 | **Contractor-side CIS**: verify subcontractors, deduction statements, monthly CIS300 incl. nil returns, bulk entry | TR (contractors), AC | Low–medium: 3 sources, main thread from 2022 | [AccountingWEB, QBO CIS for 70–80 subbies](https://www.accountingweb.co.uk/node/199344) (2022); [GOV.UK, CIS contractor monthly returns](https://www.gov.uk/what-you-must-do-as-a-cis-contractor/file-your-monthly-returns) | **No** |
| 10 | **VAT domestic reverse charge for construction**: the right VAT code, and the invoice wording added automatically | TR (VAT-registered), AC | Low–medium: 3 sources, mostly 2022; the gap still shows in QuickBooks help (2025) | [QuickBooks community, DRC message on invoices](https://quickbooks.intuit.com/community/vat-30/drc-vat-message-on-invoices-124381) (2022, snippet); [QuickBooks help, DRC](https://quickbooks.intuit.com/learn-support/en-uk/help-article/value-added-tax/vat-domestic-reverse-charge-building-construction/L3Rfb0VuN_GB_en_GB) (snippet); [GOV.UK, reverse charge](https://www.gov.uk/guidance/vat-domestic-reverse-charge-for-building-and-construction-services) | **No.** `VatCode` is S/R/Z/E/O/N only (`packages/ledger/src/accnomos_ledger/events.py:13-21`); the gold set has reverse-charge receipts (`evals/gold/gen_gold_v2.py`) but the engine has no code for them |
| 11 | **VAT Flat Rate Scheme and cash accounting** handled properly | MB, TR | Low: 3 sources, all before 2025 (thin) | [QuickBooks, FRS incorrect](https://quickbooks.intuit.com/learn-support/en-uk/vat/re-flat-rate-scheme-incorrect/01/1309777/highlight/true) (2021, snippet); [GOV.UK, flat rate](https://www.gov.uk/vat-flat-rate-scheme); [GOV.UK, cash accounting](https://www.gov.uk/vat-cash-accounting-scheme) | **No.** `docs/HONESTY.md` ("No flat-rate scheme, no annual accounting scheme") |
| 12 | **Trades juggle three or four apps** (enquiry, quote, job, invoice, accounts) with double entry and no live profit per job | TR | Medium: 4–5 sources | [Landscape Juice, job software](https://landscapejuicenetwork.com/forum/topics/job-management-software-1) (Apr 2026, snippet); [Grafterlab, Tradify/Fergus review](https://grafterlab.com/articles/i-tried-tradify-fergus-timekeeper.html) (Sep 2026, snippet); [Electricians Forums, invoicing apps](https://www.electriciansforums.net/threads/what-invoicing-apps-softwares-do-you-guys-use.212033/page-2) (2024, snippet) | **Partly.** On `main`: jobs, timesheets, purchases tagged to a job, margin, invoice from hours (`/jobs`, `services/runtime/app/jobs.py`), day planner. **Branch `claude/sales-purchases`**: quotes, items, purchase orders. No retentions, no enquiries |
| 13 | **Snap receipts "in the van"** with a phone app that reads the VAT and line items, not just a photo | TR, ST, AC | Medium–high: 3 trade sources + 4 on Hubdoc ("a glorified camera") | [Electricians Forums, MTD prep](https://www.electriciansforums.net/threads/making-tax-digital-prep-sorting-my-system.222053/) (Jan 2026, snippet); [Xero Ideas, Hubdoc extract tax amount](https://productideas.xero.com/forums/967130-contacts-documents/suggestions/45162577-hubdoc-extract-tax-amount-from-the-invoice) (snippet); [Xero Ideas, Hubdoc line items](https://productideas.xero.com/forums/967130-contacts-files/suggestions/45007846-hubdoc-extract-all-line-item-details-including-i) (Jul 2025, snippet) | **Main.** Android capture → Muse reads supplier, VAT number, net/VAT/gross and lines → code checks → Review (`services/runtime/app/pipeline.py`, `apps/mobile`). Measured on synthetic documents only; no real phone run |
| 14 | **AI that posts confidently and wrongly**; accountants want a list of best guesses to confirm, not auto-posting (Xero auto-match picking the wrong one of two equal invoices; a capture tool's guess leading to a £3k overpayment) | AC | Medium: 4 sources, plus a 1-thread "AI-native vs no-AI" split | [AccountingWEB, OCR and auto-categorisation errors](https://www.accountingweb.co.uk/any-answers/ocr-and-auto-categorization-errors) (Feb 2026, snippet); [Financial Accountant, AI ledger promise vs reality](https://financialaccountant.co.uk/features/ai-accounting-ledgerbot-promise-reality/) (Sep 2025, snippet); [AccountingWEB, clients' AI use](https://www.accountingweb.co.uk/practice/general-practice/accountants-count-the-cost-of-clients-ai-use) (Aug 2026, snippet) | **Main, by design.** The model proposes, code checks, a person approves; a second independent reading; Autopilot only on saved rules and undoable (`docs/AUTOPILOT.md`, `services/runtime/app/checks.py`, `ai/verify.py`). This is Accnomos's strongest answer to a real worry |
| 15 | **Context the AI cannot know**: subsistence (VAT reclaimable) or client entertaining (not); business or private | AC, ST | Low: 1 thread with several replies | [AccountingWEB, OCR and auto-categorisation errors](https://www.accountingweb.co.uk/any-answers/ocr-and-auto-categorization-errors) (Feb 2026, snippet) | **Partly.** Review lets the user change category and VAT; no question is asked for meals, and the self-employment branch splits entertainment only by account name |
| 16 | **Mixed personal and business bank accounts**: every line is a business-or-private decision; expected to get worse as MTD reaches £30k and £20k | ST, TR, AC | Medium: 4 sources | [AccountingWEB, client ignoring bank-feed requests](https://www.accountingweb.co.uk/any-answers/client-ignoring-requests-to-set-up-bank-feed-mtd-0) (Aug 2026, snippet); [AccountingWEB, side business](https://www.accountingweb.co.uk/node/228499) (Jan 2026); [Kreston Reeves, separate accounts](https://www.krestonreeves.com/news/making-tax-digital-separate-bank-accounts-for-buy-to-let-and-self-employed/) (snippet) | **Partly.** `/bank` has *Mark as transfer* and *Ignore* for unmatched lines, but no "private / drawings" posting and no business-use percentage on a bill; personal finances are a separate hidden page (`apps/web/src/app/personal`) |
| 17 | **Bank feeds that keep working**: Open Banking consent lapses about every 90 days and feeds stop silently; named banks break (Lloyds, Co-op, Unity Trust); some banks have no feed | All, AC | High: 6+ sources | [QuickBooks community, the 90-day rule](https://quickbooks.intuit.com/community/banking-27/why-does-my-bank-keep-disconnecting-understanding-open-banking-consent-and-the-90-day-rule-298977) (May 2026); [AccountingWEB, Unity Trust feed gap](https://www.accountingweb.co.uk/node/230533) (May 2026); [QuickBooks community, Lloyds connection](https://quickbooks.intuit.com/community/banking-27/after-an-update-on-case-ref-removed-it-s-been-over-2-weeks-now-and-no-further-forward-with-banking-connections-replies-to-email-are-just-ai-generated-apologies-298620) (Apr 2025, snippet) | **No feeds.** CSV import only (`/bank`, five bank layouts modelled from public formats, never checked against real exports) |
| 18 | **CSV import that doesn't break**: swapped columns breaking rules, duplicates when feeds and imports overlap | AC | Low: 1 thread, 2 commenters | [AccountingWEB, Unity Trust thread](https://www.accountingweb.co.uk/node/230533) (May 2026) | **Main.** Header sniffing; overlap de-duplicated by date, amount, normalised description and balance (`services/runtime/app/bank_rules.py`, README "Bank statements") |
| 19 | **Getting records out of clients**: clients ignore requests, send everything in the last week, or crumpled photos | AC | Medium: 3 sources; ICAEW survey: 67 % of practices name it the biggest obstacle | [ICAEW, first MTD submission](https://www.icaew.com/insights/tax-news/2026/aug-2026/first-mtd-income-tax-submission-how-did-it-go) (Aug 2026); [AccountingWEB, biggest frustration with client records](https://www.accountingweb.co.uk/any-answers/biggest-frustration-with-how-clients-send-records) (Jun 2026) | **Partly.** Outlook intake pulls receipts from the mailbox (`services/runtime/app/intake.py`), the phone captures, Home shows what needs attention; **branch `claude/mailboxes`** adds more mailboxes. Nothing nudges the client on a schedule, and the accountant has no view of their own |
| 20 | **Accountant collaboration**: an accountant pack, read access, one place for accountant and client | AC | Medium (implicit across items 2, 19, 21) | [AccountingWEB, QuickBooks rises (accountants as unpaid support)](https://www.accountingweb.co.uk/node/227559) (Nov 2025); [AccountingWEB, Starling partner portal](https://www.accountingweb.co.uk/tech/accounting-software/starling-adds-partner-portal-to-accounting-tool) | **Partly.** **Branch `claude/exports`**: Accountant pack zip (TB, GL, P&L, balance sheet, aged, journal, audit trail, bank rec, VAT with digital links) and import files for Xero, QuickBooks, Sage and FreeAgent. No invitation or accountant login; sharing the OneDrive folder is possible outside the app but not guided |
| 21 | **Support you can reach** (Xero has no inbound phone line; QuickBooks "impossible to speak to unless it's them … upsell"; AI chatbots disliked) | All | High: 5+ sources | [Xero Ideas, phone support](https://productideas.xero.com/forums/939198-for-small-businesses/suggestions/47493815-xero-support-provide-phone-support); [QuickBooks community, can't reach support](https://quickbooks.intuit.com/community/other-questions-36/any-other-accountants-who-find-it-impossible-to-speak-to-quickbooks-unless-its-them-contacting-you-to-upsell-tried-phone-chat-and-email-but-nobody-replies-376084) (Sep 2026, snippet); [Trustpilot, QuickBooks UK](https://uk.trustpilot.com/review/quickbooks.intuit.com) | **No** (no support model; **branch `claude/marketing`** has an "Ask about Accnomos" chat grounded on public docs, which is the kind of support users say they dislike unless a human is behind it) |
| 22 | **Leaving without losing your history**: a read-only archive after cancelling; vendor exits (Bokio UK closed 30 Jun 2026) stranding data | All, AC | Medium–high: 5 + 3 sources | [Xero Ideas, tax access lost on cancel](https://productideas.xero.com/forums/967127-practice-tools/suggestions/49046462-uk-company-tax-access-lost-to-all-xero-tax-rep); [AccountingWEB, Bokio leaving](https://www.accountingweb.co.uk/node/230445) (May 2026) | **Main, by design.** The books are files in the user's own OneDrive; *Export your data* zip and Books.xlsx (`services/runtime/app/data_export.py`); nothing is lost on disconnect. A real strength to say out loud |
| 23 | **Moving years of history in from Sage, Xero or QuickBooks** is the real switching cost | MB, AC | Low: 2 sources | [MoneySavingExpert, Sage Line 50 alternatives](https://forums.moneysavingexpert.com/discussion/6686718/suggestions-for-alternative-to-sage-line-50-accounts-package) (Oct 2026, snippet) | **No import of history or opening balances** (exports branch writes *out* to those packages; `claude/sales-purchases` imports items with Xero headers only) |
| 24 | **Mobile apps missing core tasks** (bulk reconcile, balance sheet, receive money; all Xero ideas) and **automatic mileage tracking** | ST, TR | Medium: 5 Xero ideas + 2 mileage | [Xero Ideas, bulk reconcile in app](https://productideas.xero.com/forums/967136-banking-chart-of-accounts/suggestions/51585296-xero-accounting-app-bulk-transaction-reconciliat) (snippet); [Xero Ideas, automatic mileage](https://productideas.xero.com/forums/939198-for-small-businesses/suggestions/45687376-expenses-automatic-mileage-tracking) (snippet) | **Partly.** Android has capture, Review, Ask, VAT and thin clients for most pages (`apps/mobile/PARITY.md`); the balance sheet is on **branch `claude/month-end`**. Mileage is a typed log, no GPS, and at the wrong 2026-27 rate (see the top of this file) |
| 25 | **Payroll that is both proper and posts to the books** (built-in payroll "too basic"; standalone payroll doesn't post journals) | MB, AC | Medium: 4 sources | [AccountingWEB, Xero payroll](https://www.accountingweb.co.uk/any-answers/xero-payroll-3) (Feb 2026, snippet); [AccountingWEB, BrightPay vs others](https://www.accountingweb.co.uk/any-answers/brightpay-vs-other-payroll-software) (Jun 2025, snippet) | **Main: estimates only** (`/payroll`, "not payroll, not RTI"). **Branch `claude/payroll-rti`**: PAYE engine, payslips, FPS/EPS files, pensions, posting through Review; files built, not submitted to HMRC |

Also seen, with less evidence: a dispute/query flag on bills (Xero's most-voted idea, 1,258 votes) and
auto-emailed customer statements (1,164, in discovery) — [Xero Ideas, bills top](https://productideas.xero.com/forums/967139-purchase-orders-bills-inventory/filters/top),
[invoices top](https://productideas.xero.com/forums/967115-invoices-quotes/filters/top); Accnomos has customer
statements on `claude/sales-purchases` (sent on a tap, not scheduled) and an audit trail on `main` (`/audit`,
Xero's 585-vote "audit trail report" is "not in pipeline" there). A sole trader with a side business or a let
being made to pay for a second subscription (Sage, FreeAgent, QuickBooks one income source per account) —
[AccountingWEB, side business](https://www.accountingweb.co.uk/node/228499) (Jan 2026); on **branch `claude/profiles`**
each profile is a separate Microsoft account, which repeats that pain.

---

## 2. The eight highest-impact gaps

Ranked by (how often and how sharply people ask) × (how close Accnomos already is) × (what it does for the target
users: VAT-registered trades and sole traders, and the MTD Income Tax cohorts from April 2027). Sizes: **S** = a day or
less on top of what exists, **M** = a few days, **L** = a week or more, or a partner integration.
"Before the deadline" means worth starting before 4 Nov 2026 without risking the submission; everything else is
after launch. The 55p mileage fix above comes before all of these.

### Gap 1. Cash-basis figures for sole traders — M — before the deadline (if `claude/self-employment` is merged)

Why: HMRC's default for sole traders; without it the self-employment figures are wrong for most real users (pain 3),
and its own review says so. Also the VAT cash accounting scheme shares the same idea (gap 6).
Spec:
- A `basis` switch (`accruals` | `cash`) on the profile (sole traders default to cash; companies to accruals).
- Cash view built by code from existing events: card/cash purchases count on their own date; invoices and bills on
  account count only as payments are recorded (`settlement.py` already knows each payment's date and amount),
  part payments pro rata across the invoice's lines and accounts; credit notes and refunds on the date the money moves.
- `GET /books/self-employment/summary?basis=cash` and the P&L (`/reports/pl?basis=cash`); the page says which basis.
- Tests: an invoice raised in Q1 and paid in Q2 lands in Q2 on cash, Q1 on accruals; a part payment splits by line.
- Not in scope: VAT-inclusive cash recording (record ex-VAT, as now).

### Gap 2. "Private" and part-business lines for mixed accounts — S — before the deadline

Why: pain 16, four sources, and it grows as MTD reaches £20k earners who use one account for everything.
Spec:
- On an unmatched bank line, *Private* posts nothing to income or expenses and records owner's drawings or
  introduced capital (Dr/Cr `2300 Owner / director loan`, or a `3xxx Drawings` account for sole traders), undoable,
  audited. Bank rules can apply it ("TESCO STORES → private").
- On Review, *Business use %* on a purchase (phone, broadband, fuel): code splits the net and VAT; only the business
  share reaches expenses and Box 4; the private share goes to drawings. The self-employment branch keeps the private
  share out of SA103 totals.
- No model judgement beyond suggesting *Private* for obvious supermarket or personal lines, labelled as a suggestion.

### Gap 3. CIS for subcontractors (and CIS on quotes and invoices) — M — after launch, first

Why: pains 7–8; the demo business is a joinery firm; Xero's CIS-on-quotes request is seven years old and pushing
users away; CIS deductions are pre-filled on the MTD return, so the books must match them.
Spec:
- Contact flag: *contractor deducts CIS* with rate (20 % / 30 % / 0 % gross).
- Invoice and quote lines marked labour or materials; code works out the deduction on labour only (gross less VAT and
  materials) and prints the CIS box ("Less CIS at 20 %: £x; amount due £y"). Posting: Dr Debtors (net due), Dr
  `CIS suffered` (an asset or a tax-paid account), Cr Sales (gross), Cr VAT.
- Bank match: a receipt of the net due settles the invoice in full (no gross-up by hand).
- Read contractors' monthly CIS payment and deduction statements from the inbox (the model reads; code checks the
  sum against the invoices) and reconcile them.
- Year totals for the Self Assessment / MTD return (`taxTakenOffTradingIncome` / CIS deductions) and, for a
  limited company, the EPS figure (with `claude/payroll-rti`).
- Contractor side (verification, CIS300) is a separate, later piece (L), probably not for the first trades users.

### Gap 4. Domestic reverse charge VAT code — S–M — after launch, with gap 3

Why: pain 10; every VAT-registered subcontractor supplying a VAT-registered contractor needs it; the gold set already
contains reverse-charge receipts the engine cannot post.
Spec:
- New `VatCode.REVERSE_CHARGE_CIS` (`RC`) at 20 % or 5 %. As supplier: net in Box 6, no output VAT, invoice prints
  "Reverse charge: customer to account to HMRC for the VAT (VAT Act 1994 s55A)". As customer: code posts output VAT in
  Box 1 and the same amount in Box 4, net in Box 7.
- Contact flags *VAT-registered* and *end user / intermediary* (end users are excluded), so the invoice form chooses
  the code; Review offers `RC` when a bill says "reverse charge".
- Property tests that RC never changes Box 5 for a fully taxable business. Needs an accountant's read of the box rules
  before going live.

### Gap 5. Landlords: UK property income, per-property tags and joint ownership — L — after launch

Why: pains 5–6; landlords are a large part of the MTD cohorts and the most vocal on cost; joint ownership is the
single most repeated MTD complaint found.
Spec:
- Profile kinds gain *landlord* (and *sole trader + landlord* in one profile, avoiding a second account).
- SA105 categories as accounts (rent; repairs; finance costs split residential / non-residential; legal and
  management; services; other) and a *property* tag on lines (like job tags).
- *Ownership share* per property per person (default 100 %); quarterly figures multiply by the share in code, and a
  joint property can be left out of quarterly expenses (HMRC's easement) and added at year end.
- MTD UK property updates through the relay (Property Business API), same receipt and audit pattern as self-employment.
- A *light mode* for small landlords: rent in, a handful of bills, four updates a year; no chart of accounts on screen.

### Gap 6. VAT Flat Rate Scheme and cash accounting — M — after launch

Why: pain 11 (thin, older evidence, but both schemes are common among small trades and consultancies and the README
already admits the gap).
Spec:
- VAT settings: scheme = standard | flat rate (sector percentage, 1 % first-year discount, 16.5 % limited-cost test
  worked out by code each period) | cash accounting.
- Flat rate: Box 1 = percentage × VAT-inclusive turnover; Box 4 only for capital purchases over £2,000; the P&L shows
  the flat-rate VAT as a cost. Warn when the joining or leaving thresholds are crossed.
- Cash accounting: boxes from payment dates (reuses gap 1's cash view); refuses with flat rate.
- Tests against HMRC's worked examples.

### Gap 7. Accountant access — M — merge `claude/exports` before the deadline; the invitation after launch

Why: pains 19–20; accountants decide which software clients use, and they are the ones complaining about chasing
records. The Accountant pack already exists on a branch.
Spec:
- Before the deadline: merge the exports branch (Accountant pack, package import files).
- After: *Invite your accountant* shares the Accnomos folder read-only through OneDrive sharing (the user's own Graph
  call; no Accnomos database), and the accountant opens the same app in a read-only "accountant view" on their own
  Microsoft account (profiles branch), with the pack, queries back to the client as to-dos, and a per-period
  "ready for review" mark. Later: write access for journals with every accountant change audited.

### Gap 8. Bank feeds through Open Banking — L — after launch

Why: pain 17 is the most repeated operational complaint, and feeds are what users expect; CSV-only intake is the
weakest link between "snap a receipt" and reconciled books. The complaints also say what to do differently.
Spec:
- An account-information provider (a regulated aggregator; Accnomos would not hold the licence) behind a
  `BankFeedProvider` interface next to the CSV parser, writing the same statement lines into `04 Bank statements`.
- Consent expiry handled in the open: the date shown on Home and Bank, a reminder a week before, a plain "your feed
  stopped on …" banner, and a CSV top-up path that de-duplicates against the feed (already built for overlaps).
- Cost: aggregator fees per connection; check whether the stateless runtime can hold consent tokens (it cannot today:
  they would have to live in the user's OneDrive, encrypted, or with the aggregator).

**Runners-up:** importing history and opening balances from Xero, QuickBooks, Sage or a spreadsheet (pain 23; also
the bridging route for landlords, pain 6); a scheduled, user-approved client nudge ("3 receipts missing for
October"); GPS mileage on Android.

---

## 3. Features Accnomos has that users may find confusing

Grounded in the forum signals above where possible; otherwise a reading of the product and `docs/HONESTY.md`.

1. **"Your books are files in your OneDrive."** A strength for lock-in (pain 22), but users will open `_System`,
   rename folders or edit `Books.xlsx` (which is regenerated and says "do not edit"). Accountants on AccountingWEB
   distrust spreadsheets as records. Explain once, plainly, on Files: which files are the books and which are copies.
2. **Proposed, approved, posted, paid.** A receipt is a proposal until Approve; *Mark paid* and a Bank-page match post
   nothing until *Post as payment*; Autopilot posts on its own only at L2. Users coming from Xero expect "reconciled"
   to mean posted (`docs/HONESTY.md`, "Invoicing"; README "Invoicing").
3. **"Needs a look" from the Verifier when the reading was right.** Glimmer checking Glimmer raised 44 false alarms over
   400 documents (`docs/submission/META_MODELS.md`). Accountants want best guesses to confirm (pain 14), but repeated
   false alarms train users to approve without looking. Say why on the card in one line.
4. **Accruals figures for a sole trader.** P&L and the self-employment summary are "as approved"; a sole trader on the
   cash basis will see income they have not been paid (gap 1).
5. **Two AI modes, and "on your own machine".** "Local" means the machine running the runtime (our DGX Spark), not the
   user's laptop (`docs/HONESTY.md`, "Models"). Users will read it as their own computer.
6. **Settings that live on this device.** VAT stagger, Autopilot level and some business details are in the browser;
   a second browser or the phone can show different periods (`docs/HONESTY.md`, "Files, Books.xlsx, dashboard";
   "Android").
7. **Two payroll pages.** `main` has a timesheet *estimate* ("not payroll"); `claude/payroll-rti` adds real PAYE and
   keeps the estimate below it. Users complain payroll is either too basic or not linked (pain 25); having both on one
   page needs a clear label of which one HMRC sees.
8. **Profiles are separate Microsoft accounts** (`claude/profiles`). A sole trader with a let wants one login with two
   income sources (pain 1 "also seen"); two accounts and a switcher may read as "pay twice".
9. **The Xero-shaped menu for a one-van joiner.** The branches add chart of accounts, manual journals, fixed assets,
   tracking, budgets, month-end close, 40+ reports (`claude/accounting-tools`, `claude/exports`, `claude/month-end`).
   Landlords and small sole traders say a full ledger is overkill for four submissions a year (pain 6). Hide by
   profile kind; keep the default to Home, Review, Ask, Invoices, Bank, VAT or Self-employment.
10. **Sandbox labels on HMRC features.** "(HMRC sandbox)" on VAT checks and submissions is honest, but a user may not
    know whether a return was filed. Before production, make "this was not sent to HMRC" impossible to miss.
11. **Chat action cards expire after 15 minutes** and a "send" can end as a draft when `Mail.Send` was never granted
    (`docs/ACTIONS.md`, `docs/HONESTY.md`).
12. **Job margins change when a staff rate changes** (past jobs are restated at the current rate; `docs/HONESTY.md`).

---

## 4. Pricing and positioning expectations

### What competitors charge (ex VAT, per month unless stated; seen 28 Oct 2026, mostly through cached pages)

| Product | Price | Source |
|---|---|---|
| Xero (from 1 Sep 2026) | Simple £7 (non-VAT, 10 invoices); Ignite £18; Grow £39; Comprehensive £55; Ultimate £70; 90 % off for 6 months | [xero.com/uk/pricing-plans](https://www.xero.com/uk/pricing-plans/); [1Office](https://1office.co/blog/xero-uk-price-increase-2026/) |
| QuickBooks UK | Sole Trader Plus £10; Simple Start £16; Essentials £38; Plus £56; Advanced £123 (secondary sources agree; one competitor's blog disagrees) | [marcandrews.com, QuickBooks pricing 2026](https://marcandrews.com/quickbooks-pricing-uk-2026/) (Aug 2026); [Whito MTD price tracker](https://whito.co.uk/research/mtd-software-price-tracker/) (Oct 2026) |
| FreeAgent | Sole trader £19, landlord £10, limited company £33; **free** with NatWest, RBS, Ulster or Mettle | [freeagent.com/pricing](https://www.freeagent.com/pricing/) |
| Sage | Sole Trader Free £0 (5 invoices, 1 bank account); Sole Trader £7; Accounting £20 / £43 / £59 | [Sage MTD](https://www.sage.com/en-gb/making-tax-digital/) |
| Pandle | Free; Pro £5 | [pandle.com/pricing](https://pandle.com/pricing/) |
| Coconut | MTD bridging £49.99 a year; MTD filing £12.99 a month or £129.99 a year | [getcoconut.com/pricing](https://www.getcoconut.com/pricing) |
| ANNA | £0 / £12.90 / £22.90; MTD Income Tax filing free on all plans | [anna.money/pricing](https://anna.money/pricing) |
| Countingup | £5 / £12 / £20 by monthly deposits | [countingup.com/pricing](https://www.countingup.com/pricing) |
| Tide | MTD tools free for sole traders; Accounting £13.99 (sole trader) / £19.99 (Ltd) | [tide.co/accounting](https://www.tide.co/accounting/) |
| Starling | Accounting Essentials free (quarterly updates); Plus £7 until Apr 2027, then £14 | [starlingbank.com/business/accounting](https://www.starlingbank.com/business/accounting/) |
| Dext Business | £24.17 a month billed yearly (£290), or £30 monthly | [dext.com/uk/business/pricing](https://dext.com/uk/business/pricing) |

HMRC's software finder listed **159 MTD Income Tax products on 20 Oct 2026; 33 free and covering sole-trader income,
9 of which do quarterly updates only** (Whito's count of the finder, linked above). HMRC makes no software of its own
([GOV.UK software finder](https://www.gov.uk/guidance/find-software-that-works-with-making-tax-digital-for-income-tax)).
Accountants get partner prices (Sage publishes them: Start £13.50 against £20 —
[sage.com/en-gb/accountants/pricing](https://www.sage.com/en-gb/accountants/pricing/)); Xero partners pass on about
20 %; ledger-only practice seats are about £3 per client.

### What people say is fair

- **£0 is the anchor for a non-VAT sole trader or landlord** (FreeAgent through a bank, Sage Free, Starling, Tide,
  ANNA). "If clients complain about price, they can always get Mettle/FreeAgent for free" —
  [AccountingWEB, MTD software advice](https://www.accountingweb.co.uk/any-answers/mtd-for-income-tax-software-advice-please) (Jul 2025).
- **About £7–10 a month is the next step**; bridging tools sit at **£20–50 a year**; landlords call £12–30 a month
  "quite a lot for four submissions a year" ([OpenRent](https://community.openrent.co.uk/t/making-tax-digital-from-april-2026-how-are-you-preparing/89638), snippet).
- **About £15–20 a month is what practitioners think a micro client will tolerate**, and £30–40 is "full accounting
  package" territory: "you really don't need a full accounting package like Xero or QuickBooks — they're £30–40/month"
  ([MoneySavingExpert](https://forums.moneysavingexpert.com/discussion/6669531/software-advice-for-hmrc-mtd-for-landlord), May 2026; the poster sells a rival tool).
- **The anger is about value, rises and gating more than the number**: "the frustration isn't really about a few
  pounds a month. It's about value" ([AccountingWEB opinion](https://www.accountingweb.co.uk/community/industry-insights/i-vibe-coded-my-way-out-of-premium-accounting-software), Jun 2026);
  "I have more a problem with the value in the packages than I do with the price increase in itself"
  ([LinkedIn](https://www.linkedin.com/posts/nicola-donnelly1981_accountingandaccountants-xero-freeagent-activity-7201497991772262401-Qoit), May 2024);
  Sage "increased our monthly fees to £108 from £74.40" ([Trustpilot](https://www.trustpilot.com/review/sage.com), Oct 2026).
- **Counterview:** "£59 a month … wouldn't that be a reasonable price for financial software?"
  ([LinkedIn](https://www.linkedin.com/posts/will-pepper-05737b208_xero-freeagent-quickbooks-activity-7354063168962207744-zWDV), Jul 2025). Thin.

### What that suggests for Accnomos (a recommendation, not evidence)

- **Positioning that the evidence supports:** "AI proposes, you approve, code calculates" answers the accountants'
  worry about confident AI (pain 14), and "your books stay in your OneDrive" answers lock-in and vendor exits (pain 22).
  Both are already true on `main`. Accountants are split between wanting an "AI-native" ledger and wanting no AI in
  the ledger ([AccountingWEB, another Xero price increase](https://www.accountingweb.co.uk/any-answers/another-xero-price-increase),
  Jun 2026, snippet; one thread): lead with the approval and the code, not the model.
- **Price under the anchors, with no tier cliffs:** free for a non-VAT sole trader's MTD records and updates once
  production access exists; one flat price around **£8–12 a month** for VAT, invoices, jobs and Ask, with nothing
  essential (VAT, CIS, payroll for 1–2) behind a higher tier; publish a promise about yearly rises. Local or
  own-key models keep marginal cost low, which is what makes this plausible.
- **Go to market through accountants carefully.** AccountingWEB regulars are openly hostile to founders pitching new
  MTD apps ([AccountingWEB thread](https://www.accountingweb.co.uk/any-answers/biggest-frustration-with-how-clients-send-records), Jun 2026).
  Lead with trades and landlords directly, and give accountants the pack and a free seat.
- **Timing:** new 2026-27 MTD Income Tax products cannot get production access; the next cohort (over £30k, about
  1.08 million people) starts on 6 Apr 2027
  ([GOV.UK press release](https://www.gov.uk/government/news/sole-traders-and-landlords-earning-more-than-30000-urged-to-act-now), Oct 2026).
  That is the launch window for gaps 1, 3, 5.

---

## Thin evidence and open questions

- No Reddit, Google Play or G2 data. Starling and Tide Trustpilot scores are for the whole bank, not their accounting
  tools. Hubdoc's Trustpilot has 16 reviews.
- VAT flat rate and reverse-charge complaints are mostly 2015–2022; the gaps look current from vendor help pages, but
  2025–26 users were not found saying so.
- Contractor-side CIS (bulk entry, nil returns) rests on a 2022 thread and vendor blogs.
- "AI-native versus no-AI ledger", "QuickBooks AI posting to retained earnings" and the "£3k overpayment" each rest on
  one post.
- MTD statistics beyond HMRC's 12 Aug 2026 press release (436,000 first updates, 570,000 sign-ups) are third-party
  (Bright via AccountingWEB, NRLA, Azets) and disagree with each other.
- Budget 2026 (today) may change MTD timing, penalties and mileage rates after 2026-27.
- Accnomos coverage was read from code and review files, not run; branch features are unmerged and several branches
  say their full test gates did not finish.
