# Feature research: Claude and Muse compared

Compares `docs/research/FEATURES_CLAUDE.md` (this branch, `claude/research-features`) with
`docs/research/FEATURES_MUSE.md` (branch `muse/research-features`, commit `1066b4f`, read 28 Oct 2026). Claude's file
was written before Muse's was read, so the two are independent.

## Read this first: Muse's file is incomplete

The committed `FEATURES_MUSE.md` (14,872 bytes, 77 lines) stops in the middle of pain point 14 ("Repeat/recur") with
the literal text `...[truncated 6151 chars]`. What is there: a method note, a summary of Accnomos on `main`, and pain
points 1–13. What is missing: points 14–20, and every section after them (presumably its gaps, confusing features and
pricing). So this comparison covers **pain points only**. Where this file says "Muse did not find X", read "Muse's
first 13 points do not mention X". If a complete version is pushed, re-run the comparison.

## How the two were made

| | Claude | Muse (as committed) |
|---|---|---|
| Points | 25 pain points, 8 gaps with specs, 12 confusing features, pricing | 13 of a stated 20 pain points |
| Sources | Forums where users post (AccountingWEB Any Answers, Xero Ideas, QuickBooks and Sage communities, OpenRent, LandlordZONE, trade forums), Trustpilot, vendor pricing pages, GOV.UK and HMRC Developer Hub | Mostly comparison and review blogs (Medium/ThriveOnz, businessexpert.co.uk, capitalise.com, Planyard, gotofu.com), Capterra/SoftwareAdvice, some press releases and LinkedIn; gov.uk named but rarely linked |
| Reddit | Not reachable; says so | Listed as a source in the header, but **no Reddit link is cited** in the 13 points |
| Coverage checked against | `main` **and** the unmerged feature branches | `main` only (README, HONESTY, REMAINING) |
| Frequency | Count of independent sources seen, with dates | Qualitative: pervasive / recurrent / occasional |

Evidence quality differs. Muse leans on SEO-style "best software 2026" roundups, several written by vendors or
affiliates, which say what products have rather than what users complain of. Claude's forum sources carry dates and
first-hand complaints but are accountant-heavy. Neither has a real sample of sole traders.

## Agreements

Both found these, with similar weight:

1. **MTD for Income Tax quarterly updates** are the defining need of 2026–2028 (Muse 1; Claude 2).
2. **Price rises and tier gating** (Muse 2; Claude 1). Both note that Accnomos has no pricing story yet.
3. **Bank feeds**: incumbents' feeds break, and Accnomos has none, only CSV (Muse 3, "the single biggest day-to-day
   gap"; Claude 17 and gap 8).
4. **Receipt capture is mistrusted**, and Accnomos's reading is measured on synthetic documents only (Muse 4; Claude 13).
5. **CIS** for trades, a named Accnomos audience with no CIS at all (Muse 6; Claude 7–9, gap 3).
6. **VAT edge cases**: flat rate, cash or annual accounting, domestic reverse charge are all missing (Muse 10; Claude 10–11,
   gaps 4 and 6).
7. **Payroll that files RTI and posts to the books** (Muse 7; Claude 25).
8. **Year-end handover and accountant collaboration** ("the shoebox"); Accnomos's folder, Books.xlsx and audit
   trail help, but there is no accountant role (Muse 9; Claude 19–20, gap 7).
9. **Too complicated for non-accountants** (Muse 12; Claude §3 item 9 on the Xero-shaped menu).
10. **Duplicates from overlapping feeds and imports**, with Accnomos's overlap handling noted (Muse 13; Claude 18).

## Disagreements

| Topic | Claude | Muse | Which is right |
|---|---|---|---|
| Does Accnomos have MTD Income Tax? | Yes on branch `claude/self-employment`: cumulative updates, calculation and final declaration, sandbox only | "No. VAT MTD (sandbox) only. No quarterly ITSA updates, no final declaration" | Both, for different scopes. Muse checked `main` only; the branch exists (`git show origin/claude/self-employment:REVIEW.md`). Neither is production-ready: HMRC is not granting production access to new 2026-27 products |
| Payroll | Main: estimates; branch `claude/payroll-rti`: PAYE engine, payslips, FPS/EPS files | "No (by design)" | Same cause: the branch was not checked |
| Mileage | **45p on `main` is wrong**: GOV.UK raised cars and vans to 55p from 6 Apr 2026 (checked on gov.uk, 28 Oct 2026) | Lists "mileage at HMRC AMAP rates" as working | Claude. `services/runtime/app/mileage.py:63-64` hard-codes 45p |
| QuickBooks prices | Essentials £38, Plus £56; treats the £28 figure from one competitor's blog as unreliable | "QuickBooks includes it from Essentials (£28/mo)" | Claude, on the balance of three sources (Intuit's own comparison page, Amlink, Whito) against one |
| Xero prices | Ignite £18, Grow £39, top tier £70 (from 1 Sep 2026) | "Xero plan prices reach £65/mo at the top tier"; "Xero includes payroll only from Grow (£37/mo)" | Claude: Muse's figures predate the September 2026 rise. Xero also now sells payroll on any plan at £1.50 a person (AccountingWEB thread, Feb 2025, in Claude's notes) |
| Capture coverage | "Main" (it exists and is measured) | "Partly" (accuracy on synthetic data only) | Both fair; Muse's wording is the more cautious. Both say real photos will score lower |
| MTD awareness statistic | Not used | "~1 in 3 sole traders had never heard of MTD" (IRIS, 2025) | Pre-launch figure. By Aug 2026 HMRC reported 436,000 first updates and 570,000 sign-ups, so it is stale for positioning |

## Found by only one

**Only Claude (in the part of Muse that exists):**
- The **55p mileage rate** change and the wrong figure on `main`.
- **Cash basis** as the sole-trader default, and that the self-employment branch's figures are accruals, which its own
  review says would be wrong for most real sole traders.
- **Landlords and joint-owned property** (split records by share and file for each owner): the most repeated MTD
  complaint Claude found (6+ sources). Muse mentions "property income segregation" only in passing, under point 1.
- **Spreadsheet plus bridging** demand from small landlords.
- **Mixed personal and business accounts** (a *Private* action and business-use percentages).
- **CIS details**: CIS on quotes (Xero's seven-year-old request), CIS after retentions, grossing up net receipts.
- **Context the AI cannot know** (subsistence or entertaining), and accountants' wariness of AI that posts confidently,
  which matches Accnomos's propose–approve design.
- **Data lock-in and vendor exit** (Bokio left the UK in June 2026), a strength of books-in-your-OneDrive.
- **Importing history** from Sage, Xero or QuickBooks.
- **Support you can reach**, and the open-banking 90-day reconsent cycle as the cause of feeds stopping.
- **HMRC production access** closed for new 2026-27 products, which sets the launch window at the April 2027 cohort.
- Coverage on the feature branches (`self-employment`, `payroll-rti`, `exports`, `sales-purchases`, `month-end`,
  `profiles`, `mailboxes`).

**Only Muse:**
- **Automatic payment chasing** (Muse 5): scheduled reminder sequences, late-payment interest and compensation,
  credit-risk data; with figures on late payment (about £26bn owed, about 86 hours a year chasing, cited second-hand
  through a vendor blog). Claude saw only auto-emailed statements (a 1,164-vote Xero idea). Muse also missed that branch
  `claude/payment-links` adds Stripe and PayPal payment links on invoices, which is half of this.
- **Multi-currency** (Muse 11). Claude saw it only as a feature locked to Xero's higher tier. The owner dropped
  multi-currency from `claude/accounting-tools` on 28 Oct 2026, so this is a known, decided gap.
- **Corporation Tax (CT600) and Self Assessment in the product** (Muse 8). Claude covered Self Assessment through MTD
  Income Tax but not company tax.
- **Low-friction capture by WhatsApp** (in Muse 9), as an alternative to an app for clients who won't install one.

## Merged, prioritised list

Ordered by evidence × impact for the target users (VAT-registered trades, sole traders, and the April 2027 MTD
cohort) × how close Accnomos already is. "Deadline" is the hackathon (4 Nov 2026).

| # | Item | Found by | Size | When | Notes |
|---|---|---|---|---|---|
| 1 | **Fix the mileage rate: 55p from 2026-27** (rates per tax year) | Claude | S | Before the deadline | A wrong figure on `main` today; check Budget 2026 for later years |
| 2 | **Cash-basis figures** for sole traders (self-employment summary and P&L) | Claude | M | Before the deadline if `claude/self-employment` merges; else with it | Without it the MTD figures are wrong for most sole traders |
| 3 | **MTD Income Tax**: merge `claude/self-employment`, run it in HMRC's sandbox, aim production at the April 2027 cohort; add consolidated expenses and the annual adjustments | Both | M (merge and sandbox run) → L (annual submission) | Merge and sandbox before; the rest after | Muse thought it absent; it is on a branch |
| 4 | **Private / business split** on bank lines and bills | Claude | S | Before the deadline | Cheap, and the problem grows as MTD reaches £20k earners |
| 5 | **CIS for subcontractors** (deductions on invoices and quotes, net receipts settling in full, statements read from the inbox, year totals), then **domestic reverse charge** | Both | M + S–M | After launch, first | Trades are the demo audience; contractor-side CIS300 later (L) |
| 6 | **Accountant collaboration**: merge `claude/exports` (Accountant pack), then a read-only invitation through OneDrive sharing and client queries as to-dos | Both | S (merge) → M | Merge before; invitation after | Accountants choose their clients' software |
| 7 | **Bank feeds through an Open Banking provider**, with reconsent dates shown and CSV top-up | Both | L | After launch | Both rank it the biggest day-to-day gap; partner fees and token storage to solve in a stateless design |
| 8 | **Landlords**: UK property income, per-property tags, ownership shares, property updates to HMRC, a light mode | Claude (Muse in passing) | L | After launch | The most repeated MTD complaint |
| 9 | **Getting paid**: merge `claude/payment-links`, then user-approved reminder sequences and late-payment interest calculated by code | Muse (plus the branch) | S (merge) → M | Merge after a test against Stripe's test mode; sequences after | Reminders stay drafts the user approves, in line with "nothing is sent without a tap" |
| 10 | **VAT flat rate and cash accounting schemes** | Both | M | After launch | Cash accounting reuses item 2 |
| 11 | **Payroll with RTI**: finish and review `claude/payroll-rti`, submit FPS/EPS to HMRC | Both | L (submission and recognition) | After launch | Files exist on the branch; nothing is sent |
| 12 | **Import history and opening balances** (Xero, QuickBooks, Sage, spreadsheet), also the bridging route for landlords | Claude | M | After launch | The switching cost people name |
| 13 | **Multi-currency** | Muse | L | Later, or not at all | The owner dropped it on 28 Oct; keep it dropped unless exporters become a target |
| 14 | **Corporation Tax / CT600** | Muse | L | Later | Accountants usually file it; the Accountant pack may be enough |

Both reports agree on the positioning: "AI proposes, you approve, code calculates" and "your books stay in your
OneDrive" answer real worries (confident AI, lock-in, vendor exit). They also agree on what weakens it: no bank feeds,
no CIS, no MTD Income Tax on `main`, and almost nothing yet run against real services.
