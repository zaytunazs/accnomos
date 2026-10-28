# Honesty: every known gap

A flat list, grouped by area, from the code on `main` and the "What remains" section of every `docs/reviews/*/REVIEW.md`
(duplicates merged). Severity-ordered tables are in `docs/REMAINING.md`; what each feature does and how it is tested is the
README table. We could not reach accnomos.com or api.accnomos.com from this session, so the live sites are unchecked.

Gates 28 Oct 2026 (Linux): runtime 1260 passed (all Python under `check.sh`: runtime, ledger and connectors); evals 258; relay 119; web e2e 208; `flutter analyze` clean and `flutter test` 248 passed. The Python counts match `pytest --collect-only`; the e2e and Flutter counts are the owner's gate figures and were not re-run for this edit. On Windows, set `PYTHONUTF8=1` first: four source-scanning test files read UTF-8 with the cp1252 default otherwise.
`pnpm run build` and `npx eslint src` pass in `apps/web`; `pnpm run e2e` passes whole (208 tests) with `E2E_PYTHON` pointed at the
project venv (no `python3` on this machine's PATH). `ruff` has not been run.

## What is real, and what is not

- **Real runs** are the maintainers' own, on 26–27 Oct: Microsoft sign-in on a personal account, folder creation, upload → scan →
  Glimmer on our DGX Spark → approve → ledger event → VAT boxes. No log is committed. The committed evidence is the eval reports in `evals/`.
- Everything else is **tested on fakes** (in-memory OneDrive, mailbox, calendar and address book; stubbed model; mocked HMRC and Meta).
- **Demo data is synthetic**: Bramblewood Joinery Ltd, the receipts, bank CSVs and the gold set are generated. Signed out, Home, Review, Ask, VAT return and Files show static mock-ups under a "SAMPLE — FICTIONAL COMPANY" banner (`DemoBanner.tsx`); other pages label their own sample fallbacks. Once signed in the banner is hidden. In the demo sandbox (*Try the demo — no sign-in*) every page instead carries "SAMPLE — FICTIONAL COMPANY · Demo sandbox with sample data" (`DemoBar.tsx`) over the live app on a per-visitor copy of the seeded books.
- **Evals are synthetic renderings**, so real phone photos will score lower. Extraction: 200 documents, every field right on 85 % clean / 80 % messy for Glimmer local and 91 % / 93 % for Spark Open on Baseten, all with repairs, re-read and Verifier on (27 Oct; the earlier Glimmer run without them scored 88 % messy, and the 60-document run 73 %). Verifier: 20 documents, 0 extra catches, 1 false alarm. The Claude judge agrees with the code score on only 79/200 documents (it grades line wording and category, which the code does not); the code score is the headline.
- **Repairs and the re-read are now measured live (27 Oct), together with the Verifier:** all fields 85 % clean / 80 % messy for Glimmer, 91 % / 93 % for Spark Open on Baseten, side 100 %; status falls from 98 % to 83–97 % with the Verifier on because its false alarms send right readings to *Needs a look* (`docs/submission/META_MODELS.md`). Glimmer's messy score is below the earlier 88 % run without them, mostly through status. Earlier note, kept for the record and superseded by the sentence above: **repairs and the re-read were not measured live.** Code now repairs VAT-inclusive totals and doubled quantities before the checks (the card says "Figures repaired by code from the receipt's own arithmetic") and re-reads unsure or non-adding documents once at higher resolution. At the time neither had had a live 200-document run. A replay of the stored readings through the repairs (`evals/harness/replay.py`, no model, so it cannot measure the re-read) gives all fields 88 % → 91 % and net 93 % → 97 %, but false passes 9 → 11: two receipts with no VAT number and no VAT, which the eval expects in *Needs a look*, used to fail only on bad arithmetic and now pass.
- **A missing VAT number with no VAT is now flagged only for suppliers the books don't know (owner's rule, 27 Oct).** Over £250, no VAT, no VAT number, unknown supplier: *Needs a look* with "Is &lt;supplier&gt; VAT-registered?"; ticking "isn't VAT-registered" on Approve records it in `contacts.json`, and a VAT number seen on an approved receipt records "registered", so later receipts are decided without asking. On perfect readings of the 200 gold documents false passes go 6 → 2 (`evals/runs/supplier_vat_replay/report.md`). **The replay of the stored Glimmer readings was not re-run** (the records were not in that checkout): the check only adds fails when the books are empty, so the 11 cannot rise except through gold 176/184, whose expectation moved to *Needs a look* (overseas SaaS suppliers over £250; the reading has no address, so code can't tell they are overseas, and the user is asked once per supplier). The two remaining false passes, 038 and 060, are under £250 with no VAT, which the rule passes and the older gold rule does not. Supplier lookup at scan time reads the saved `contacts.json` only: a supplier whose VAT number is in the ledger but who was never saved (approved before this change, Contacts never refreshed) counts as unknown until *Refresh from books*. Whether the business is VAT-registered is a new setting in the invoice profile (default yes; a VAT number always means yes).
- **Feature evals use the same synthetic data**, built from the gold documents rather than real exports or mailboxes: bank matching precision 83/83, recall 83/106; Outlook intake 12/17 documents kept, 11/11 decoys dropped; Ask numbers exact 32/32 for both Glimmer and Qwen (28/32 and 31/32 before the routed facts pack). Each has its report under `evals/runs/` and one command to reproduce it. The triage expectation was written for the run, not taken from the fixtures.
- Everything was written during the build period with coding assistants (Claude, Muse Code, a local Qwen); every merge was reviewed (`docs/reviews/`). The DGX Spark and Ollama setup predates the event.
- **Runtime speed numbers are on fakes with simulated latency.** `evals/harness/bench_runtime.py` seeds the full demo book onto an in-memory OneDrive and sleeps 120 ms per `list`/`read` to stand in for a Graph round trip. The before/after table in `evals/runs/bench_runtime/report.md` compares code paths (repeated reads, parallelism, caching), not the network: real OneDrive latency varies, and the seed's book is one size. Re-run with `--mode before` / `--mode after` to reproduce it.

## HMRC

- **Sandbox only.** The relay defaults to `test-api.service.hmrc.gov.uk`; no production credentials, no real filing.
- **Company and VAT look-ups are built and tested on fakes only.** Companies House (search, profile) and HMRC's Check a UK VAT number v2.0 (through the relay) have never been called for real from this code: the session that built them had no Companies House key and no HMRC sandbox credentials. The VAT check is sandbox-only like everything HMRC (answers say "(HMRC sandbox)"); untested live. HMRC's own sandbox test numbers (e.g. 553557881) fail the mod-97 check, so the checksum is shown as information and never blocks a check. Whether HMRC expects fraud-prevention headers on this application-restricted API was not verified; the relay sends none there. Switching to production is environment-only and written down in `docs/PRODUCTION.md`, not done.
- The browser flow (connect → obligations → declaration → submit → receipt in `06 VAT returns/`) is built and type-checked but has **not been run end to end** against HMRC's sandbox. Relay tests mock HMRC.
- **The runtime holds no HMRC token, so it learns obligations second-hand.** When connected, the web app fetches HMRC's obligations through the relay and posts them to `POST /books/vat/obligations` (stored in `_System/vat/obligations.json`). `/books/vat/periods` and `/books/vat` then mark a period submitted when HMRC says fulfilled (source `hmrc`, with HMRC's period key, due date and received date) or when our own receipt exists (source `accnomos`); a fulfilled period cannot be submitted again from the web. Dates that match none of our periods warn in plain English (our stagger differs from HMRC's). Until the web app has fetched the list, a return filed elsewhere still shows as open — and the whole round trip is **sandbox-only and untested against the live sandbox until the owner signs in** (built and type-checked against a faked relay; relay tests mock HMRC).
- The runtime's own period key (`26A4` style, saved as `calculated_for`) is still a placeholder; HMRC's key is used on `/books/vat` and `/books/vat/periods` when its dates match, and submission uses HMRC's key. For monthly returns all three months of a quarter get the same placeholder.
- `GET /books/vat` accepts `?today=`, so a client can move "current" and with it `can_submit`; the web gate is advisory and HMRC decides what can be filed.
- No flat-rate scheme, no annual accounting scheme, no fuel scale-charge calculation.
- The runtime's "today" is the **London date** (`books.today()`, Europe/London via `zoneinfo` + `tzdata`): `GET /audit` `from`/`to` filter by London day too. Both clients send `today` to the dashboard, so this mostly affects direct API callers and chat actions.

## Receipts, review and the ledger

- **No separate LLM Reviewer.** The card's "why" line is composed by code ("Checker, code"). Models write words only in *Ask*, inbox triage, reminder drafts and the planner rationale, each checked by code. The signed-out mock-up on `/vat` has a "Reviewer's note (Muse Spark)"; it is labelled sample but no such reviewer runs.
- Key-mode extraction (muse-spark-1.3) is unit-tested only.
- **Ledger files are not tamper-evident** (no signatures, no hash chain). An undo is a reversing entry dated like the original — unless that VAT period was already submitted, when the correction is dated today and lands in the current, open period instead (the undo response carries `dated_today`, `reason` and both period labels; `test_undo_submitted.py`).
- `/books/vat` entry counts put a reversal against the box it reverses, and the page header says how many of the period's entries are undone (e.g. "3 entries, 1 undone").
- **No real HEIC from a phone has been read, and no real supplier PDF.** HEIC → JPEG (`pillow-heif` 1.8.1) and PDF
  reading (`pypdfium2` 5.14.0, locked in `uv.lock`) are tested with the real libraries, but only on files the tests make
  (a HEIC written by `pillow-heif`, PDFs written by `fpdf2`). The Docker image has not been built with them.
- A multi-page PDF is read from page 1 only (a total printed only on page 2 is missed); a scanner batch of several
  receipts in one PDF is read as one document and not split.
- Receipts in an email body are found by a code rule tested on six fictional emails, not on real Uber, Amazon or SaaS
  mail, nor on Graph's HTML-to-text conversion of them.
- `POST /books/approve/{id}` is kept as an alias for web builds deployed before the integration review; remove it after the next deploy.
- `POST /reports/export` saves one spreadsheet in `07 Reports/` from the web and from Android More → Reports (a same-day file of the same name gets ` (2)`; it never posts), but only fake storage has been written in tests. The folder names now have one source (`services/runtime/app/paths.py`); existing users' old-named folders are renamed once on first contact (`app/layout.py`), which has only been tested on fake storage, not on a real OneDrive.
- `services/runtime/tests/test_integration.py` holds the runtime to the documented folder layout only for the features its scenario exercises (not invoicing, payroll, planner, to-dos, action audit).

## Models

- **Verifier needs a Baseten key.** Muse Spark Open runs only in key mode and only if the server owner sets `BASETEN_API_KEY`; the demo deployment now sets one. Without one, key mode verifies with the request's model (muse-spark-1.3 by default) and local mode with Glimmer. The server has a Baseten key since 27 Oct 2026, and a real call through `ai/verify.py` read a gold receipt correctly in 7 s; the eval over the 200 gold receipts has landed: all fields right 91 % clean (`evals/runs/spark_open_200`) and 93 % messy (`evals/runs/spark_open_messy_200`), about 13 s per document. No real Meta (muse-spark-1.3) verifier call has been made. The Baseten model id `meta-models/muse-spark-open` is the one Baseten's `/v1/models` lists (checked 27 Oct 2026).
- The verifier's catch rate is small and measured on synthetic documents only: over 200 clean plus 200 messy documents Spark Open caught 1 wrong reading, missed 6 (both readings agreed on a wrong figure) and raised 11 false alarms; Glimmer checking Glimmer caught 8, missed 4 and raised 44 (`docs/submission/META_MODELS.md`). The first run, Glimmer checking Glimmer on 20 documents, had 0 extra catches. Mixed-rate receipts give false alarms (it reads the standard-rated subtotal as net); the prompt needs a mixed-rate hint. All six fields are decisive, which is stricter than the original brief.
- The card cannot adopt the second reading: on a disagreement the user can approve the first reading or reject.
- **SAM 3.1 crop is off by default** (`SAM_CROP=1`); its wire format is unverified and has never run live; the default crop is plain code, measured on synthetic scenes only (mean IoU 0.88). No separate crop chip: the crop note is appended to the card's verifier line.
- **Muse Voice Transcribe:** the request (`/asr/transcribe`, multipart parts, response field) comes from research notes and has not been checked against dev.meta.ai. No live mic run in Chrome/Edge, Firefox, Safari/iOS or on Android. Key mode only. Meta has no text-to-speech model and Accnomos does not read answers aloud.
- In key mode with no `X-Meta-Api-Key` header, `AiConfig` falls back to the server's `META_API_KEY`, so typed and voice Ask would run on the operator's key.
- **"On my own machine" means the machine running the runtime.** Our demo runtime and Ollama are on our DGX Spark; a user's laptop is not reachable from `api.accnomos.com`.
- Harness gold issues: `015_zero` (VAT number not printed); `038` and `060` (`no_vat_number`, under £250, £0 VAT) still expected to need a look, which the owner's rule does not do.
- A bad `X-AI-*` configuration makes inbox triage silently run without a model ("No AI is set up") instead of naming the setting.
- The planner's rationale model sees calendar event subjects as well as job names, and with no `X-AI-*` headers `/plan/day` falls back to the server's default model (`AI_MODE`, or `META_API_KEY` in key mode), not only the user's own (`routes_plan.optional_ai`).

## Chat and voice actions, Autopilot

- Without `ACTIONS_SIGNING_KEY` (the deploy file passes it through, empty by default), each runtime process makes a random key: after a restart, or with several workers, a card can fail with 403.
- If the runtime dies between the `approving` and `executed` audit lines, that action is never re-run on its own (409). After 10 minutes, rejecting the card clears it; the user checks whether it happened and asks again.
- Invoice drafts for chat actions can end as drafts when `Mail.Send` has not been granted; the card cannot request consent.
- The Autopilot level lives in the browser's `localStorage` (`accnomos.autopilot`; only L2 turns posting on). The Android app stores its own level the same way and sends `X-Autopilot: off` on every runtime call below L2, so phone scans post nothing without the user.
- Autopilot only handles purchases that match a rule; it never makes rules itself.

## Invoicing, jobs, contacts

- **Part payments, overpayments and credit notes are modelled by code** (`app/settlement.py`), tested on fake storage only. *Record payment* / *Mark paid* posts Dr 1200 Bank (or 1210 Cash) / Cr 1100 Debtors; *Remove* reverses it; a paid invoice can be voided only after its payments and credit notes are removed. A credit note (CN-0001…) is posted as a reversal with the invoice's VAT codes on its own date — or, for a stand-alone credit note with its own customer, lines and descriptions, with its lines' VAT codes; with no invoice to reduce, the amount is left as a credit on the customer. *Mark paid* on a part-paid invoice records only the balance (a stale full total never overpays); a paid invoice's PDF carries a PAID stamp with the date, while the emailed copy in `sent/` stays as the customer got it. A credit left on a contact (overpayment, or a credit note over what was owed) can be applied to another of that contact's open documents (an allocation: nothing is posted) or refunded (posted Dr 1100 Debtors / Cr 1200 Bank, or Dr 1200 Bank / Cr 2100 Creditors for a supplier), web only; the payment or credit note behind a used credit cannot be removed until the use is. Credit note PDFs have not been opened in a real viewer or emailed from a real mailbox.
- A bank line matched straight to invoices on the Bank page still posts nothing until *Post as payment* turns it into a recorded payment. A statement line for money already recorded is suggested to that payment (same amount, 5 days before to 14 after) and a match to a settled document is refused, so the same money is not counted twice; outside those rules it is up to you. A supplier credit note is linked to its bill only when its printed "original invoice" number matches exactly one standing bill of that supplier; otherwise it is a credit on the supplier. Payment terms per contact are in the web *Edit*. The extraction eval was not re-run since `credit_note` and `original_invoice_number` were added.
- An invoice made from a job's hours marks only the entries whose hours and rate still match their sent line; voiding the invoice frees its entries again.
- "Invoiced" value and margin use each person's *current* charge rate; changing a rate restates past jobs.
- If saving the sent copy fails after the email has gone, the invoice is saved as sent but the sale is not posted until the user retries (the retry exists). `GraphMailSender` checks the encoded request against 4 MB and refuses larger ones with an error (about 3 MB of attachments); big attachments (draft plus upload session) are not supported. In the send dialogs the tick stays ticked if the user edits the message afterwards.
- Ageing counts what is still owed from the due date: the invoice's own, else the contact's terms, else 30 days from the document date (bills carry no due date from the reader). Customer VAT numbers are only set with *Edit*. Outlook contacts added with "also add" are always customers. Every `contacts.json` is rewritte re-reads and merges on an ETag conflict, so two tabs editing different contacts both win; two saves colliding twice over get a 409 asking for a reload. After *Edit* the side panel reloads the statement in place.
- **Possible duplicates are AI-assisted, not AI-decided.** Code finds the candidates and their evidence; your model (Glimmer local, Muse Spark key) gives `{same, confidence, keep_name, reason}` beside it, and only your tap merges. Judgement has run on the test stub only, never a real model. A merge across different VAT numbers is refused; after a merge the *Undo* button lasts until you reload the page (the record stays for the API). Merging is on the web and only, not Android (the phone is a thin client over the same routes; its sheets are new and have not been run on a real phone).
- Plain timesheet edits do not rebuild Books.xlsx. A timesheet whose date moves month is written to the new file before the old one is cleared; a failure between leaves a duplicate, never a loss. A purchase can be tagged to a closed job through the API (on purpose).
- The web mileage log can add, edit and delete journeys; vehicles can be renamed, deactivated or deleted from the page (deletion is refused, with the reason, while journeys or tagged receipts reference the vehicle). The Review vehicle picker offers *Add a vehicle* when no business vehicle is active. Vehicle pre-fill at scan uses a category plus keyword list.

## Online payments (payment links)

- **Never run against live Stripe or PayPal, and not against their test/sandbox APIs either.** Every provider call in the tests and in test mode goes to fakes (`services/runtime/app/online_fakes.py`) written from the documented request and response shapes (pages and dates in `app/payment_providers.py`). No Stripe test account or PayPal sandbox app was available to this branch.
- Stripe is connected with Connect OAuth (Standard accounts). Stripe says OAuth "isn't recommended for new Connect platforms" but is still the way for an application that needs access to an *existing* account; Accounts v2 onboarding would create a new account controlled by the platform instead of linking the user's own. Revisit before going live.
- PayPal partner onboarding and `PayPal-Auth-Assertion` need PayPal to approve the platform as a partner; not applied for. That a PayPal invoice payment's `payment_id` can be read with `GET /v2/payments/captures/{id}` (for the fee) is unverified: when it fails the user types the fee.
- PayPal.me links (`paypal.me/<name>/<amount>GBP`) are only checked by a redirect on 28 Oct 2026 (the decimal form kept its path); PayPal documents whole amounts in its example. Those payments are never found by code.
- Payments are found only when the user opens Invoices (no webhooks: the runtime holds no token to write to OneDrive). A customer's payment is invisible to the books until then, and is posted only when the user approves it. The gross is posted to 1200 Bank and the fee as a separate exempt expense, so the provider's later payout to the bank is the *same* money: mark that bank line as a transfer, or it would be counted again. There is no clearing account for the Stripe/PayPal balance.
- A link has a fixed amount. If the balance changes (a bank payment, a credit note) the old link still asks for the old amount until the user makes a new one; the list shows "Not the amount owed now". A payment that arrives on an invoice already paid another way is not proposed (paid invoices are not checked); it stays in Stripe/PayPal for the user to refund or record by hand.

## Payroll

- **Estimates only. Not payroll, not RTI.** No FPS/EPS, no payment to HMRC; your payroll provider does that.
- The estimate divides annual thresholds by 12 (tax about 20p a month high, NI a few pence off HMRC's tables), monthly pay only, tax code 1257L on a month-1 basis, England/NI rates, NI category A. No student loans, pensions, statutory pay, benefits, salary sacrifice or Employment Allowance; no salaried staff (gross is hours × rate).
- The 2026–27 rates in `payroll_rates.py` were checked against GOV.UK on 27 Oct 2026 by the payrun branch's author (a code comment and commit message, no other record); `tests/test_payroll_rates.py` now pins every constant to the GOV.UK figures (re-read 27 Oct 2026, all matched). Re-check each April.
- Undoing a payroll ledger entry from outside the Payroll page leaves the run "confirmed" until it is reopened.

## Accounting tools (chart, journals, fixed assets, recode, tracking, budgets, cash flow)

- **Tested on fakes only** (runtime unit and route tests, Playwright against the test-mode runtime); never run on a real
  OneDrive or reviewed by an accountant.
- **No multi-currency.** Dropped by the owner (28 Oct 2026): a non-GBP receipt still cannot be posted, there are no
  currency fields, no exchange rates and no FX gains or losses.
- **Fixed assets are book depreciation only.** Capital allowances (AIA, writing-down allowances) are not calculated; the
  page and the API say so. Disposals take catch-up depreciation for whole periods only (no part-month), proceeds go to a
  bank-type account, and output VAT on the sale is whatever the user types. Registering an asset posts nothing: if the
  purchase was coded to an expense it must be moved with Find and recode.
- **Find and recode** changes a VAT code only for a sale or purchase whose VAT is on one line, keeping the gross; mixed-rate
  entries must be undone and posted again. Credit notes, payments and journals can be recoded by account but not VAT.
  Lines on bank and control accounts are refused.
- **Chart names are fixed once used**: entries keep the "code name" they were posted with, so a used account can't be
  renamed (add a new one and recode). Account types must fit the code ranges the reports use; 9000–9999 is not allowed.
- **Cash flow** includes only open invoices and bills on account (overdue ones counted as due now). There are no repeating
  invoices or bills in Accnomos yet, and pay runs, VAT payments and card spending are not forecast.
- **Tracking** on bills is set on approval and applies to every cost line of the bill; credit notes, payments and recodes
  copy no tags from the user (a recode keeps the original line's tags).
- Manual journals attach a document by its path in the books folder (no upload from the journal form).

## Bank statements

- **Bank formats are modelled, not verified.** Barclays, Starling, Tide, Monzo and HSBC/Lloyds layouts follow public formats and have not been checked against real exports; unknown headers fall back to `bank`.
- A re-export that overlaps an earlier one gets a different sha256; if every line was already imported, the CSV is still filed but has no stored lines and does not appear under Statements.
- **Part payments are never suggested**: one entry paid by two bank lines finds no match (20 of 106 gold pairs), and *Confirm* refuses a second line for the same entry. Supplier refunds more than 5 days after the credit note are missed, because the Tide parser drops the `Transaction Type` column. Payments on terms (up to 60 days after the document) are suggested only when the counterparty's name is in the line, and never as `exact`.
- *Confirm all exact matches* skips matches a penny out (fixed in the integration review) but that rule has no web test. `suggested_filename` on bank-line proposals is the date and a filesystem-safe description with no extension; nothing reads it.

## Personal finances

- **Basic and estimated, not advice.** `/personal/*` (services/runtime/app/personal.py) gives household budgets, spend against budget, regular bills and subscriptions, savings goals and a monthly summary. It gives no investment advice, no tax advice and no credit score. Every figure is worked out by code in whole pence; no model is called.
- **Only what is in an imported statement is counted.** Cash, a card never imported and anything outside the CSVs are missing from every total, and the summary says so. Lines marked transfer or ignored on the Bank page are left out. Money in is all "income" (a refund is not netted against its category); only money out is categorised.
- **Categorisation is a separate rule set** in `_System/personal/rules.json` (contains / equals / safe regex, amount range, money out only), matched with the same code as the business bank rules but never mixed with them. The first matching rule wins; a payment no rule knows sits under Other and is counted as uncategorised. "Add common UK merchants" adds a fixed list of about two dozen shop and utility names: those are guesses at what the name means, not facts about your spending.
- **Recurring bills are a guess from patterns.** Same payee (a name cleaned of dates and reference digits), a regular gap (weekly, fortnightly, monthly, quarterly, yearly) and a similar amount; at least three payments (two for a yearly one). Monthly and quarterly bills that move up to 30% (energy) are kept and marked "about". "Next due" is the last payment plus one cycle, not a date from the provider, and ignores weekends and bank holidays. A payee the cleaning cuts differently on two statements (a changed merchant name) will be missed or split. "Looks stopped" means more than a cycle overdue; it does not mean cancelled. The monthly total is an estimate.
- **Goals:** the user enters the target, date, what is saved so far and optionally a planned monthly amount; code divides the rest by the monthly payments left (days to the date / 30.4375, a part month counting as one, rounded up to the penny). It ignores interest and inflation and does not read savings balances from the bank: "saved so far" is the user's own number.
- **Not run:** tests use fake storage and a hand-made statement; nothing here has been tried on a real OneDrive or against a real bank export, and the recurring detector has not been tuned on real statements. The web page is hidden behind Settings › Business › *Show personal finances* (off by default, stored on this device) until profiles decide where it lives. On a phone it is reached from that Settings link, not the tab bar.

## Inbox, calendar, planner

- Not run against a real mailbox, calendar or address book. Admin consent for `Contacts.Read` on work accounts is untested.
- Outlook intake drops photos forwarded by a colleague on the user's own domain: they get no sender point and score 0.3 against the 0.4 threshold (5 of 17 documents in the fixtures). Triage keeps mail from the user's own address on another domain (a phone, say) and from a second company domain.
- Ask on Glimmer takes about 16 s (median, slowest 50 s) with 0 timeouts in the 40-prompt eval (`evals/runs/ask_40/report.md`). On Glimmer the streamed words arrive in one piece (Ollama holds back a schema-constrained reply), so in practice the 90 s first-chunk wait is a whole-reply timeout there. Wrong-period grounding is a phrase and label match per sentence: a sentence that names the other period ("last quarter", "Apr–Jun 2026", "26A2") may quote its figures; a figure that exists in both periods cannot be told apart. The router is keywords only; a follow-up like "why?" is routed on its own words and treated as being about the current period.
- **More mailboxes (Settings › Email intake) are untested against real mailboxes.** Linking a second Microsoft account
  (MSAL popup, multi-account cache), reading a shared mailbox (`/users/{address}` with `Mail.Read.Shared`, work or school
  accounts only), folder lookup by display name and the per-mailbox token header ran only on fakes, the test-mode MSAL
  stand-in and a mocked Graph transport. Not checked live: that `loginPopup` works with our redirect bridge in every
  browser (popup blockers), that a second account in the cache never becomes the active one (the code re-sets the
  signed-in account after every popup, but older pages pick `getActiveAccount() ?? getAllAccounts()[0]`), whether
  tenants need admin consent for `Mail.Read.Shared` despite Microsoft listing none, and how Graph names folders in a
  shared mailbox the user can open only partly. Only top-level folders can be picked by name. A preview lists a receipt
  sent to two mailboxes twice (a real check copies it once). Android lists the mailboxes and checks only the signed-in
  one. Gmail is not built.
- A triage draft is two Graph calls; if the second fails an empty reply stays in Drafts (we do not delete mail). Sent Items are not read, so an answered thread can still show *Reply*.
- **First-time calendar consent loses the plan:** MSAL redirects to Microsoft and on return the plan card is gone; plan again and tap Apply again.
- Two Applies at the same moment can both create events (no lock in a stateless runtime). Planner: Europe/London only, travel times are rules of thumb by postcode district, only VAT returns count as "due", the *Visit length* input caps at 12 h in the web (runtime 24 h), *Plan a day with these jobs* sends every open job.
- Mileage proposals from the planner appear only when active vehicles exist, use the first active vehicle, and write nothing.

## Load sample books

- **Never run against a real OneDrive.** *Load sample books* (`POST /books/sample`) and the seed it runs have only run on the in-memory fake OneDrive (`test_sample_books.py`, the e2e spec). **How long it takes against Graph is unmeasured.** On the fake the whole seed makes about 11,300 storage calls (most of them folder listings and reads behind each approval), and each is roughly one Graph request, so at a few tenths of a second each it could take well over half an hour, more than a token lasts; throttling (429s are retried) is untested there. (`tools/seed_demo.md` said "several hundred Graph calls"; corrected.)
- The Graph token expires after about an hour and the runtime cannot refresh it. The page hands the runtime a fresh token every four minutes and whenever the run says it needs one; if the page is closed, the run waits ten minutes, then stops, and the next press (or visit to Home) carries on from the recorded step. Resuming was checked on the fake by refusing the token at, and right after, every one of the 710 writes of a run (1,420 runs, each compared with the books the CLI writes): the first pass found 11 failures in 6 kinds of two-write action, all now repaired and each kept as a named test (an approval posted but not saved, a filed document not yet recorded, an emailed receipt copied but not recorded, a sent invoice's PDF, a filed statement whose lines were not stored, a payment's entry without its record or its record without its line match, a rule coding posted but not saved). A refusal at a read or listing between writes, and a second stop in the same step, were not swept.
- The background run lives in the runtime process. Progress is in the user's own `_System/sample_seed.json` (the runtime still stores nothing); with more than one runtime process, a run that went quiet is taken over after three minutes without progress.
- The documents are drawn by the evals' renderer (`evals/harness/render.py`, DejaVu Sans Mono in the image); the Inbox documents are read for real by the account's AI only when someone presses *Scan*. The business name in Connect is not set for the user: set it to *Bramblewood Joinery Ltd* before scanning, or sales may be read as purchases.
- The runtime image now carries `tools/seed_demo.py`, `evals/gold` and the renderer (fictional data only). The Docker test used to keep `evals` out of the image so that test mode's stub AI could never read receipts there; instead `ACCNOMOS_IMAGE=1` is set in the image and test mode refuses to start under it. The image was not rebuilt in the session that changed it.

## Demo sandbox (no sign-in)

- **Built and tested on this branch only; never run on the production server.** `DEMO_MODE=1` (`services/runtime/app/demo.py`) is covered by `services/runtime/tests/test_demo.py` (a small stand-in snapshot) and by `apps/web/e2e/sandbox.spec.ts`, which runs the real seed: start from the landing, approve a receipt, the VAT return with a simulated submission, Reset demo, leave to sign-in, and `/judges`.
- **Seeding time, measured honestly:** the full seed plus the six pre-read documents took **125 s** on a 2-core machine shared with other builds (load average ~36), and the seed alone 68 s at a similar load. It was not measured on an idle machine, so the "about 4 s" figure in the brief is unverified here. That is why it runs once a day in a background thread, started by the first `/health` request and each session gets a copy (about 7 µs each: the file bytes are shared, only the dicts are copied). The first visitor after a restart or after midnight waits for it.
- **Six documents in Review were not read by a model.** They carry the seed's gold reading (model `seed:gold-reading`, as every seeded document does), so a judge can review and approve at once. Scanning the other 19 in `00 Inbox`, Ask and the planner use the AI the server is configured with, at the owner's cost; nothing stops a visitor using it within the rate limits.
- **HMRC in a demo is simulated by the web app**: the obligations are made-up calendar quarters and the receipt is labelled "Demo — submission simulated" (form bundle `DEMO-000000000000`); the relay is never called. Mail is recorded and never sent ("Sent (demo — not actually sent)"). Companies House and the VAT-number check are off.
- **Sessions are in one runtime process's memory.** A restart ends every demo, and with several runtime processes a session would exist in one only. The limits (200 sessions, 2 h idle, 20 MB per session, 512 MB in all) are per process.
- The demo's mailbox, Outlook address book and calendar are small fictional stand-ins (two messages, two contacts, one event), not the seed's.
- **Android has no *Try the demo* button yet.** The phone calls Graph itself (`apps/mobile/lib/services/graph.dart`) for capture, Review and Files, so a demo needs those calls pointed at `/demo/graph/` too; left for later. It can use the runtime's demo API as the web does.

## Files, Books.xlsx, dashboard

- Books.xlsx has never been opened in Excel from a real OneDrive.
- **`POST /books/export` has run on fake storage only** (unit tests plus one e2e export of a single posted receipt). The zip carries an *index* of the invoice PDFs, not the PDFs themselves, which stay filed under `03 Sales`; the 2,000-file / 25 MB caps are covered by a monkeypatched unit test, not a full-size export. The CSVs have never been opened in Excel from a real OneDrive. The `account.live.com/myapps` revoke link and the OneDrive-folder *Open* link have not been clicked through on a real account.
- **Archive, backups, Clean up, search and the storage overview are untested against a real OneDrive.** Everything in `services/runtime/app/files.py`, `archive.py` and `backups.py` has run only on `FakeStorageProvider` (`test_files_archive.py`) and the test-mode fake behind the e2e specs (`files-manage.spec.ts`). Not measured or tried on Graph: how long the overview's walk takes on a big folder (one listing per folder, at most 8 in flight; a book with years of monthly receipt folders and events is hundreds of listings per visit, and the Files page asks for the overview and the index together, so it walks twice); whether `quickXorHash`/`sha1Hash` are always present in listings (personal vs work accounts differ; without them only same-size files are read and hashed); how moves of hundreds of files behave under throttling (each is one PATCH, one at a time; a run that fails part way records the moves it made, so links follow and Undo puts them back, but if the runtime process itself dies mid-run those moves are not recorded); and large zips (a year's zip and a backup are built in memory, capped at 50 MB and 100 MB, and uploaded in one upload-session PUT, which Graph allows up to 60 MiB per fragment, so a backup between 60 and 100 MB would likely fail). The redirect map only covers moves the app makes; a file the user moves by hand in OneDrive still breaks its Review link, as before. Restore compares bytes, so it reads every `_System` file once to build the preview. The monthly backup runs only from the web app, only on a device where it was switched on, and only when the app is opened in a new month: a month nobody opens the app has no backup. `_Trash` is never emptied by the app and grows until the user empties it.
- With no business settings saved, Home *Deadlines* assumes stagger 1 and now says so (`assumed: true`); the phone sends its saved stagger (or nothing, when none is saved) and shows the same note, linking to Settings. With annual accounting the tiles show "—" and "Annual VAT returns are not worked out yet". `GET /books/deadlines` returns `start_month` normalised to 1–3.
- A provider-level read failure now marks only its tiles `{"error": ...}` (Graph 401/403 still fails the whole request, so the app signs in again); the Android app does not read that marker (not run). A failed pull-to-refresh on the phone keeps the old figures under a "Could not load your figures" line; the tiles are not marked stale.
- The web sidebar names the saved AI choice (Glimmer on your machine, Muse Spark on your key, or the stub in test mode). Ask uses the period picked on `/vat` but has no picker of its own.

## Profiles (linked accounts)

- **Never run with real Microsoft accounts.** Linking several accounts, switching and *Sign out of this one* have run
  only against the test sign-in (`apps/web/src/lib/msal-test.ts`) and the runtime's per-token fakes
  (`apps/web/e2e/profiles.spec.ts`, `services/runtime/tests/test_profile.py`). Real MSAL's multi-account cache, a
  personal and a work account side by side, `logoutRedirect({account})` with another account still signed in (it may
  end the Microsoft web session for the other too), and consent prompts per account are untested.
- Two real OneDrives with a profile each have not been tried; `_System/profile.json` has only been written to fakes.
- The business details this browser keeps are swapped per account in `localStorage`; a second tab open on the other
  profile during a switch is not handled (it keeps the old copy until it reloads). HMRC must be connected again after
  every switch, by design.
- The Home dashboard still shows its VAT tile for personal books and for books that are not VAT-registered (the menu
  hides VAT; the dashboard route is not gated). Customers and Suppliers in the menu open the same Contacts page (it has
  no filter yet).
- Several menu pages are being built elsewhere (`/sales`, `/purchases`, `/accounting/*`, `/self-employment`, `/personal`
  and others); the menu shows each only once its page is in the build, so today those groups are shorter.
- Android has one account at a time (*Switch account*); its More screen does not hide VAT, invoices or payroll for
  personal books yet, and the Flutter changes have not been run here (widget tests added, `flutter test` not run).

## Android

- `flutter analyze` is clean and `flutter test` passes (27 Oct 2026, incl. the payments sheets and Add from phone at 360 dp, now also the company look-up, VAT check, contact edit, review VAT gate and duplicates sheets at 360 dp); both now run on every Android merge; 0.3.4 adds the parity suite (bank-rule sheet, Your-data export, audit filters, web-link rows at 360 dp). Page-by-page parity: `apps/mobile/PARITY.md`. Nothing on the phone has been run on a real device.
- Bank rules can be added, edited and deleted on the phone (0.3.4); rule order, CSV upload, choosing between several matches, *Post as payment* and reconcile stay on the web behind "Do this on the web" rows. A Bank-page match still posts nothing until confirmed. No credit-note PDF/email/void, and no statement of which bill a supplier credit note will link to, on the phone.
- Settings › Your data exports everything (`POST /books/export`, fake storage only in tests) and the audit trail has the web's who/what/date filters; only the CSV download stays on the web.
- **Play signing hash → Entra: registered 27 Oct 2026.** Play re-signs with Google's app signing key (SHA-1 `54:C9:BB:EE:…:42:B0`), whose MSAL hash `VMm77tAADe8/UZxWIvqfRmMiQrA=` the owner added in Entra (Android platform, `com.accnomos.app`). Release builds from 0.3.1+4 carry it (`tools/build_release.ps1`; checked inside the 0.3.1+4 bundle). Builds up to 0.3.0+3 carried the debug hash and could not sign in from Play. Sign-in on a Play install has **not yet been tried on a real phone**. `broker_redirect_uri_registered` stays `false` (browser sign-in, no broker).
- The phone sends its saved VAT stagger (or custom start month) on every VAT call — VAT return, periods, dashboard, reports and Ask — and shows the assumed-quarters note on Home when none is saved. Covered by `apps/mobile/test/vat_stagger_test.dart` (mock transport); not yet run against a real runtime with a non-1 stagger.
- The Meta API key is not in secure storage (`flutter_secure_storage` is the TODO in `apps/mobile/lib/services/settings.dart`).
- On the phone, Payroll is read-only and Bank only confirms matches the runtime is sure about. Reports (More → Reports: P&L, aged, VAT, trend, *Save to 07 Reports*) is a thin client over `GET /reports/*` with no offline copy. No HMRC filing on the phone (the VAT check only reads, on a tap).
- Mic on Ask records WAV and calls `/books/ask/voice`; no run on a device is recorded.
- *Add from phone* (0.3.2) opens the system contact picker and reads name, emails, phones and postal address from each returned contact URI only: no `READ_CONTACTS` in the manifest, nothing written back to the phone. Covered by widget tests with a mocked picker and by runtime tests for `POST /contacts/import-phone`; the picker grant, repeated picks and the sheet have not been run on a real phone.

## Public website and "Ask about Accnomos"

- **Signed out, `/` is now the landing page** and the sample Home moved to `/try` ("Try the sample books"); signed in,
  `/` is Home as before. `/`, `/how-it-works` and `/privacy` use the public shell (top menu, footer, chat) until the
  device holds a Microsoft sign-in (the same `localStorage` test as `useSignedIn`, also run before first paint so an
  owner does not see the landing page flash). Every screenshot on the landing page is a crop or resize of a real one
  (`docs/submission/shots/`, `apps/mobile/screenshots/`; `apps/web/scripts/marketing-images.py`), from test mode with the
  fictional sample books: some show `accnomos-test-stub` as the model, and the captions say test mode. The Android
  screenshots are from an emulator, signed out, showing the app's labelled samples.
- **The chat (`POST /public/chat`) has run only against the test-mode stub and a fake model in unit tests; it has never
  been called against Glimmer on the live Spark.** Its answer quality, its latency there (Ask takes ~16 s median on
  Glimmer) and whether Glimmer honours the strict JSON schema for it are unmeasured. Load on the Spark is capped at two
  concurrent chat calls per runtime process, with a 60 s timeout; past that the visitor gets the matching note quoted as
  written.
- **Guards are code, but retrieval is keyword overlap**, not embeddings: `public_kb.md` sections carry a `Keywords:`
  line, and a question matching no keyword or title word gets the fixed reply (with `PUBLIC_CONTACT_EMAIL`) without a
  model call. A real question phrased in words the notes don't use is refused too; the remedy is adding keywords. The
  role-change filter is a regular expression over common phrasings ("ignore previous instructions", "you are now",
  "act as a", "system prompt" and similar); a novel phrasing reaches the model, which sees only the retrieved notes and a
  strict prompt, and an answer that mentions its instructions is dropped. Links and e-mail addresses other than
  `PUBLIC_SITE_HOSTS` and the contact address are stripped; answers are cut to 700 characters at a sentence.
- The chat logs nothing about questions (the module has no logger; the security middleware logs only the path of an
  unhandled error), but web-server access logs still record IP, path and time as for every request. Its rate limit
  (`PUBLIC_CHAT_PER_MIN`, default 6) is per process like the global one. One question at a time: no conversation
  history is sent, so follow-ups like "and on Android?" are answered on their own words.
- `public_kb.md` is curated by hand from the docs; nothing checks that it stays in step with `README.md` and this file.
- **Two builds of the public site** (`NEXT_PUBLIC_SUBMISSION_MODE`, default `1`, and the runtime's
  `PUBLIC_SUBMISSION_MODE` for the chat's notes). The judged build leaves out what is not built (iPhone app, more
  mailboxes) instead of tagging it "coming soon", and shows no launch date; the pre-launch build (`0`) says "Launching
  November 2026 — get notified" (a `mailto:`, no sign-up list) and tucks sign-in away. Only the default build is
  tested end to end; the `0` build has been type-checked, not run. "Available on Android" on the landing page means the
  app exists and builds; per `docs/submission/JUDGING.md` the Play production listing was still in review on 27 Oct
  and no real-phone sign-in is recorded. "Try the demo" links to `/judges` when that page is in the build (a parallel
  branch), otherwise to the sample books on `/try`.

## Security and deployment

- Single-worker limits: the **rate limit is per process** (in-memory buckets, cleared on restart; several replicas would each allow the full rate) and the relay's spent-state set is per process, hence one relay worker (`deploy/Dockerfile.relay`).
- The Graph provider's `_safe_path` raises a plain `ValueError`, so a hand-edited unsafe path in the user's books returns a 500 with a correlation id, not a 400 (nothing can escape the folder either way).
- Deploy files are checked by config tests only: images not built, `docker compose up` and `nginx -t` not run, `.htaccess` not tried on Apache/Plesk, base images pinned by tag not digest, nothing tried against live `api.accnomos.com`. `Permissions-Policy` lists the deprecated `interest-cohort`.
- No authentication of callers beyond holding a valid token; `X-User` is not checked against the token. No script CSP on the web app. The AI key and HMRC tokens live in browser storage, readable by an XSS on the web origin. Prompt injection beyond file names is only mitigated by checks and approval.
- The shared `.venv` on the Spark can hold editable installs from another checkout; run `uv sync --all-packages` in the checkout you serve from.

## Testing and process

- The web has no unit tests; pages are checked by `pnpm run build` and the Playwright suite. The e2e suite runs on GitHub as the `e2e` job of `.github/workflows/ci.yml` on every push and PR (first green run 28 Oct 2026, `docs/reviews/ci/REVIEW.md`); its fake calendar is seeded but no e2e flow uses it. The suite does not prove real MSAL, Graph, HMRC relay or model accuracy.
- The SAM response fixture `services/runtime/tests/fixtures/sam_response.json` is marked ILLUSTRATIVE and must be replaced with a captured real response before turning on `SAM_CROP`.
