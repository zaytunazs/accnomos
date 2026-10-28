# What UK small businesses, sole traders and their accountants actually need from bookkeeping software

Research for Accnomos, October 2026. Sources: Reddit (r/smallbusinessuk, r/UKPersonalFinance, r/accounting), Trustpilot/Capterra/SoftwareAdvice reviews, vendor community forums (QuickBooks Community, Xero Central), accountant blogs, AccountingWEB, and gov.uk/HMRC guidance. Focus is 2025–2026.

Method note: this is a synthesis of public web sources, not a statistically sampled survey. "How often it comes up" is a qualitative judgement (pervasive / recurrent / occasional) from how frequently each theme repeats across independent sources. Where evidence is thin I say so.

What Accnomos already does (from README.md, docs/HONESTY.md, docs/REMAINING.md on `main`): receipt photo → Meta-model reading → code checks + independent Verifier → approve → immutable ledger events → deterministic VAT 9-box → HMRC **sandbox** submission; CSV bank import with matching; sales invoices (PDF, Outlook send, payments, credit notes); contacts with AI-assisted duplicates and ageing; jobs/timesheets; mileage at HMRC AMAP rates; payroll **estimates only** (no RTI); Ask, inbox triage, day planner, chat actions, Android app. Almost everything beyond sign-in/scan/approve/VAT-boxes is tested on fakes only, never against a real OneDrive, model key, mailbox or HMRC sandbox.

## 1. Top 20 pain points / feature requests

### 1. MTD for Income Tax: quarterly updates + final declaration
- **Who:** sole traders and landlords (the Accnomos target audience).
- **Frequency:** pervasive. Mandatory from 6 April 2026 for income over £50,000, £30k from 2027, £20k from 2028; ~1 in 3 sole traders had never heard of MTD, and half feel unprepared ([IRIS research via PR Newswire](https://www.prnewswire.co.uk/news-releases/half-of-sole-traders-unprepared-for-looming-tax-reporting-changes-new-iris-software-group-research-shows-302453007.html), [Accountancy Age](https://accountancyage.com/2025/05/13/mtd-unawareness-opens-new-client-opportunities-for-accountants/?amp=1), [Sage landlord guide](https://www.sage.com/en-gb/blog/self-assessment-making-tax-digital-income-tax-landlords/)). Quarterly deadlines are 7 Aug / 7 Nov / 7 Feb / 7 May ([bookkeepertools.uk](https://bookkeepertools.uk/quickbooks-simple-start-review-uk-2026/)).
- **Accnomos: no.** VAT MTD (sandbox) only. No quarterly ITSA updates, no final declaration, no property/self-employment income segregation.

### 2. Subscription cost and repeated price rises
- **Who:** sole traders, micro-companies.
- **Frequency:** pervasive. "Pricing creep" and "expensive for a small business" recur across Capterra/SoftwareAdvice Xero reviews ([Capterra UK](https://www.capterra.co.uk/software/169561/xero?page=2), [SoftwareAdvice](https://www.softwareadvice.co.uk/software/160510/xero)); Xero plan prices reach £65/mo at the top tier ([Medium/ThriveOnz](https://medium.com/@thriveonzgroupuk/best-accounting-software-uk-2026-top-10-for-smes-mtd-ready-ed508509436b)); CIS alone costs extra on lower Xero tiers ([Planyard](https://planyard.com/blog/best-construction-accounting-software)). Free-with-bank-account FreeAgent and £3–10/mo Coconut exist precisely because of this gap ([Medium/ThriveOnz top 10](https://medium.com/@thriveonzgroupuk/best-accounting-software-uk-2026-top-10-for-smes-mtd-ready-ed508509436b)).
- **Accnomos: partly.** No subscription (user's own OneDrive + own model key), but there is no stated pricing/hosting story either — self-hosting a runtime + relay is itself a cost/complexity users would notice.

### 3. Bank feeds that break, disconnect, or don't cover my bank
- **Who:** everyone; acute for Sage users and HSBC customers.
- **Frequency:** pervasive. HSBC has no native direct feed for Xero/QuickBooks/Sage — CSV export and manual reconciliation ([businessexpert.co.uk](https://www.businessexpert.co.uk/business-banking/hsbc-bank-account-review/)); Sage users effectively only get Tide as a direct feed ([businessexpert.co.uk](https://www.businessexpert.co.uk/business-banking/best-bank-accounts-for-ecommerce-uk-2026/)); Starling "rarely disconnects" is cited as a differentiator, implying others do ([SmartSMSSolutions](https://smartsmssolutions.com/resources/blog/uk/business-banking-switch-startup-accounts)); feed problems and duplicate lines recur in Xero payroll/feedback reviews ([businessfinancing.co.uk](https://businessfinancing.co.uk/payroll-software/xero-payroll-reviews/)).
- **Accnomos: partly.** CSV import (Barclays/Starling/Tide/Monzo/HSBC-Lloyds layouts) with dedupe and match suggestions exists (`packages/ledger`, `/bank`), but there are **no live bank feeds at all** — every statement is a manual upload. This is the single biggest day-to-day gap versus incumbents.

### 4. Receipt/invoice capture that misreads totals, VAT and dates
- **Who:** small companies with purchase volume; accountants coding client documents.
- **Frequency:** recurrent. Dext claims ~99% extraction but "accuracy depends on receipt quality" and faded till slips still need checking ([businessexpert.co.uk](https://www.businessexpert.co.uk/ai/best-ai-tools-for-bookkeeping-and-financial-admin/), [businesstechafrica.co.za](https://www.businesstechafrica.co.za/article/can-small-businesses-cut-the-time-spent-on-bookkeeping)); Hubdoc (bundled with Xero) scores 3.5/5 with "lack of development since acquisition" complaints ([Tofu blog](https://www.gotofu.com/blog/best-ai-bookkeeping-software)); independent capture-accuracy tests exist because buyers don't trust vendor claims ([YouTube: Xero vs Hubdoc vs Dext](https://www.youtube.com/watch?v=Y0MlRsxq_K8)).
- **Accnomos: partly.** Glimmer 30B reads 80–85% of messy documents fully right with repairs + re-read + Verifier (`evals/REPORT_glimmer_messy_200_2026-10-27.md`, `docs/HONESTY.md`), but all on **synthetic renderings** — real phone photos will score lower, mixed-rate receipts cause false alarms, and multi-page PDFs read page 1 only.

### 5. Chasing late payment takes hours; reminders should be automatic
- **Who:** freelancers, trades, small companies.
- **Frequency:** pervasive. £26bn owed in late payments at any time; owners spend ~86 hours/year chasing ([jobbit.uk citing DBT/Small Business Commissioner](https://jobbit.uk/en/blog/do-you-need-invoicing-software-2026)); QuickBooks launched a whole Payments feature around the £2.5bn late-invoice gap ([ecommercenews.uk](https://ecommercenews.uk/story/quickbooks-payments-aims-to-tackle-gbp-2-5-billion-late-invoice-gap)); Tide ships an Invoice Assistant with automatic chasing ([Finextra](https://www.finextra.com/pressarticle/87491/tide-to-tackle-late-payments-with-automated-invoice-assistant)); Satago/Chaser/Equisettle exist as paid add-ons for automated reminders, credit reports and statutory-interest calculation ([chaserhq.com](https://www.chaserhq.com/blog/best-credit-management-software), [equisettle.co.uk](https://equisettle.co.uk/feature/late-payment-invoices)).
- **Accnomos: partly.** "Draft a reminder" (model-written, code-checked, user-confirmed) exists in invoicing, but there are no automatic sequences, no scheduling, no late-payment interest/compensation calculation, no credit-risk data.

### 6. CIS for contractors and subcontractors
- **Who:** trades/construction (contractors and subcontractors).
- **Frequency:** recurrent. CIS handling is a standard comparison axis; Xero gates contractor filing behind a £5/mo add-on or top plan, QuickBooks includes it from Essentials (£28/mo), Sage from Standard — choosing wrong means filing on HMRC's portal by hand ([Planyard](https://planyard.com/blog/best-construction-accounting-software), [capitalise.com](https://capitalise.com/gb/insights/business-banking/accounting-software-for-builders), [ThriveOnz360](https://thriveonz360.com/best-accounting-software-uk-2026-top-10-for-smes-including-mtd-compatible-options/)). Trades-specific roundups treat CIS as must-have ([kitd.co.uk](https://www.kitd.co.uk/best-accounting-software-uk-tradespeople-2026/)).
- **Accnomos: no.** No CIS deductions, verification, statements, CIS300, reverse-charge VAT, or retention tracking — despite trades being a named audience (jobs/planner/mileage features).

### 7. Payroll that actually files RTI, handles pensions and statutory pay
- **Who:** any small employer (including one-director companies paying themselves).
- **Frequency:** recurrent. Xero includes payroll only from Grow (£37/mo); Sage payroll "scales fast" and is "complex for micro-businesses" ([Medium/ThriveOnz](https://medium.com/@thriveonzgroupuk/best-accounting-software-uk-2026-top-10-for-smes-mtd-ready-ed508509436b), [kelio.co.uk](https://kelio.co.uk/resources/blog/best-uk-payroll-software-our-2026-comparison.html)); cheapest credible HMRC-recognised route is BrightPay ([startupnetworks.co.uk](https://www.startupnetworks.co.uk/blogs/entry/27-best-payroll-software-for-small-businesses-uk-2026-a-no-fuss-guide/)); FreeAgent is praised specifically for bundling RTI + P60s for one-person businesses ([serverman.co.uk](https://www.serverman.co.uk/software/accounting-software/best-accounting-software-uk-2026/)).
- **Accnomos: no (by design).** `/payroll` produces explicitly-labelled estimates (monthly, 1257L month-1, England/NI, no pensions/statutory pay) for handoff to a provider. Honest, but anyone with staff still needs another product.

### 8. File Self Assessment / Corporation Tax without leaving the product
- **Who:** sole traders, landlords, micro-companies.
- **Frequency:** recurrent. FreeAgent's in-platform Self Assessment + Corporation Tax is a repeated differentiator over Xero, which "requires a workaround for sole traders" ([Medium/ThriveOnz](https://medium.com/@thriveonzgroupuk/xero-vs-freeagent-uk-2026-which-should-you-use-last-updated-on-april-13-2026-by-james-hartley-341e3b3a29d0d0)); Zoho Books lists SA100/CT600/CIS as compliance checkboxes ([zoho.com](https://www.zoho.com/blog/books/uk-tax-compliance-with-zoho-books.html)).
- **Accnomos: no.** No SA100, no CT600, no final declaration (see #1).

### 9. Year-end handover without the shoebox (accountant collaboration)
- **Who:** accountants (and their clients).
- **Frequency:** pervasive. The "shoebox in January" is the industry's defining complaint ([Xero accountant guide](https://Www.Xero.com/uk/accountant-bookkeeper-guides/getting-clients-to-use-accounting-software/), [iakaccountants.co.uk](https://iakaccountants.co.uk/insights/what-is-bookkeeping), [bluebelladmin.co.uk](https://bluebelladmin.co.uk/why-receipts-in-a-carrier-bag-just-wont-cut-it/)); tools like SubReady sell purely on "cleaner client records, less chasing" via WhatsApp submission ([subready.co.uk](https://subready.co.uk/for-accountants)); 70% of SME clients wouldn't recommend their accountant, partly a collaboration gap ([Accountancy Daily](https://www.accountancydaily.co/majority-smes-unhappy-their-accountant)); mis-coded VAT/income doubling is what accountants find when clients DIY ([LinkedIn/Natasha Everard](https://www.linkedin.com/posts/natasha-everard_bookkeeping-smallbusinessuk-knowyournumbers-activity-7449676179533529089-K3eY)).
- **Accnomos: partly.** The OneDrive folder layout + Books.xlsx + audit trail is a tidy handover artefact, but there is no accountant role, no client-query workflow ("what is this £312?"), no multi-client practice view, and WhatsApp-style low-friction capture doesn't exist.

### 10. VAT edge cases: flat rate, reverse charge, mixed rates, EC/imports
- **Who:** small companies (flat rate, construction reverse charge, importers).
- **Frequency:** recurrent. Reverse-charge VAT is bundled into every trades/CIS comparison ([capitalise.com](https://capitalise.com/gb/insights/business-banking/accounting-software-for-builders)); flat-rate and annual accounting are standard competitor checkboxes; mixed-rate receipts are exactly where capture tools fail (Accnomos's own Verifier false-alarms on them — `docs/HONESTY.md`).
- **Accnomos: partly.** Standard 9-box by code: yes (sandbox). Flat-rate scheme, annual accounting, reverse charge, fuel scale charge: explicitly not done (`docs/HONESTY.md`, `docs/REMAINING.md`).

### 11. Multi-currency invoicing and accounting
- **Who:** exporters, freelancers with overseas clients, Amazon/ecommerce sellers.
- **Frequency:** recurrent. Multi-currency is the feature that forces Xero Comprehensive (£50/mo); Wise feeds multi-currency balances into Xero directly ([globalsolo.global](https://www.globalsolo.global/blog/xero-vs-quickbooks-international-llc-accounting-comparison-2026)); Revolut/Airwallex/Wise feed choice matters for international businesses ([businessexpert.co.uk](https://www.businessexpert.co.uk/business-banking/best-bank-accounts-for-ecommerce-uk-2026/)).
- **Accnomos: no.** Single-currency (£, pence maths) throughout; no foreign-currency invoices, bills, or feeds.

### 12. "It's too complicated" — onboarding and support for non-accountants
- **Who:** sole traders doing their own books.
- **Frequency:** recurrent. Xero "has a steeper initial curve" ([zmartly.co.uk](https://zmartly.co.uk/news-insights/xero-vs-quickbooks-vs-freeagent)); beginners find it "overwhelming" ([businessfinancing.co.uk](https://businessfinancing.co.uk/payroll-software/xero-payroll-reviews/)); Trustpilot complaints cite "awkward navigation" and "delays getting technical help" ([briefcase.so](https://briefcase.so/blog/best-accounting-software-small-business-uk)); accountants report user satisfaction dropping >25% since 2023 ([LinkedIn/Eamonn Conaghan](https://www.linkedin.com/pulse/why-xeros-enshittifying-itself-eammon-conaghan-qeppe)) — evidence thin, single-authored, treat with scepticism.
- **Accnomos: partly (unproven).** Setup checklist, staggered onboarding and sample books exist, but nothing has been watched with a real first-time user; jargon-heavy surfaces (see §4) cut the other way.

### 13. Duplicate transactions: feed vs manual entry double-counting
- **Who:** small companies; accountants cleaning up.
- **Frequency:** recurrent. Bank-feed duplicates cost "countless hours" ([businessfinancing.co.uk](https://businessfinancing.co.uk/payroll-software/xero-payroll-reviews/)); double-claimed input VAT from coding both invoice and feed is a real accountant find ([LinkedIn/Natasha Everard](https://www.linkedin.com/posts/natasha-everard_bookkeeping-smallbusinessuk-knowyournumbers-activity-7449676179533529089-K3eY)); Dext→Xero practices still spend ~25 hrs/month checking ([sinnergy.io](http://www.sinnergy.io)).
- **Accnomos: partly.** Same-file CSV re-import is a no-op (sha256), statement lines matched to postings, double-settle refused (409), reversals instead of deletes. But with no live feed, the feed-vs-manual collision that causes most duplicates hasn't been exercised.

### 14. Repeat/recur
...[truncated 6151 chars]