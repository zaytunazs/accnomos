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
- **Self-employment (MTD Income Tax) is sandbox only and has never been run against HMRC.** The relay routes (`services/hmrc-relay/relay/itsa.py`), the runtime figures (`services/runtime/app/itsa.py`) and the `/self-employment` page were built and tested on 28 Oct 2026 against fakes that answer with HMRC's own published example payloads; no call was made to HMRC's sandbox (or production) from this machine, and no sandbox credentials were present. Against a production `HMRC_BASE` every Income Tax route answers 403 unless `RELAY_ITSA_PRODUCTION=1` is also set; nothing sets it. HMRC has also stopped taking production credential requests for new 2026–27 quarterly-update products (warning on the Individual Calculations page, 28 Oct 2026).
- **Cash basis by default; built and tested on fakes only.** Self-employment figures use the accounting basis in Settings: cash (HMRC's default for sole traders from 6 April 2024, gov.uk/simpler-income-tax-cash-basis, checked 28 Oct 2026 through a fetcher because gov.uk is blocked on the build machine) or traditional. Cash figures are *derived* from the ledger and the payment allocations (`app/cash_basis.py`); switching basis never changes an entry. Limits: one basis per set of books (HMRC allows one per business); HMRC's own record of the method (Business Details 2.0 Accounting Type) is not read or updated, so the user must keep it the same; no transitional adjustments on a switch; VAT is always excluded (gov.uk allows either, consistently); an overpayment not applied to an invoice is listed, not counted; a bad debt written off and depreciation are not counted on the cash basis; equipment (asset accounts 0xxx) goes in box 30 by Accnomos's choice, and cars, land, buildings and intangibles are recognised only by the asset account's *name*, so a car posted to "0050 Motor vehicles" would be claimed as an expense (the page warns to check). Payroll journals and other adjustments count on their own dates on both bases (wages when paid is not modelled). The P&L's cash option leaves out assets bought, which the self-employment summary claims.
- **Receipts saved in the same second share a file name** (`update-to-{end}-{yyyymmddThhmmssZ}.json`), so the second overwrites the first; the index keeps both entries. Found while testing the cash basis; not fixed here.
- **Account-to-box mapping is by account code and a few name words** (`app/itsa.py`: entertainment, depreciation, subcontractors, bad debts, interest, repairs). There is no private-use split: disallowable means client entertainment and depreciation in full, plus accounts named "disallowable", "private" or "personal". Consolidated expenses (turnover under £90,000) are accepted by the relay but never produced; Accnomos always itemises. Other tax taken off trading income, CIS deductions, annual adjustments, allowances, losses and the end-of-period statement are not sent.
- **Tax and NI shown on the page are HMRC's, copied from its calculation response, never Accnomos's.** If HMRC leaves a figure out the page shows a dash. The calculation summary picks fields from Individual Calculations 8.0 by name; a version change could move them.
- Final declaration: built (HMRC's declaration text word for word, checked in relay, runtime and web by a test) but only exercised against a fake. The page does not check that every quarterly update and the annual submission are in before offering it; HMRC does.
- `GET /books/vat` accepts `?today=`, so a client can move "current" and with it `can_submit`; the web gate is advisory and HMRC decides what can be filed.
- **VAT schemes (flat rate, cash accounting, annual accounting) are worked out by code and tested only on fakes and HMRC's
  own worked examples** (`claude/vat-schemes`, rules read on gov.uk 28 Oct 2026; `docs/reviews/vat-schemes/REVIEW.md`).
  No return under a scheme has been filed, even in HMRC's sandbox, and no accountant has checked a real set of books
  under one. What is not done: the flat rate's retailer's turnover method, stock adjustments on leaving the flat rate
  (Notice 733 §12.8-12.9), flat rate bad debt relief (§14), capital goods sold later (§15.9), reverse charge and import
  VAT outside the flat rate (§6.4-6.5), and partial exemption. The 30-day "forward look" test for leaving the flat
  rate cannot be checked from past books and is shown as a reminder. Cash accounting: documents are taxed on the
  payments the app knows about (recorded payments, matched bank lines, credits applied); cheques, card vouchers and
  part exchange dates (Notice 731 §4.4, §5.9) are not told apart, a refund of an overpayment does not undo VAT
  already accounted for, and an undone (reversed) invoice that was partly paid in an earlier, already submitted
  period is dropped from the scheme rather than corrected. Capital goods for the flat rate are only those the user
  ticks in Settings; "relevant goods" for the limited cost test are guessed from account codes (5000 Materials,
  7200 Utilities, 7500 Office supplies) unless the business lists its own. Annual accounting instalments are
  worked out from the figure the user copies from HMRC's letter (rounded down to £5, HMRC internal manual
  VATAAS4100); HMRC's letter is what counts. The annual period's start must be a start of the saved VAT quarters,
  and the quarters after leaving must line up with the saved stagger. The eligibility tests use the last 12 months
  of sales in the books unless the user gives an estimate; capital asset sales are not told apart.
- No fuel scale-charge calculation.
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

- **Provider chain (`AI_PROVIDERS=modal,meta,spark`) is tested on fake transports only.** Failover order, the circuit breaker, no failover on our own 4xx, the user's own key staying single, the record of who served each result, `/ai/health` and `/ai/warm` are unit-tested with `httpx.MockTransport`; the e2e suite runs the chain with every provider pointed at the stub AI. No request from this branch has reached Modal, the Meta Model API or the Spark. Not measured: the Modal cold start inside the runtime (the 60-120 s figure is from the eval runs on Modal), and whether 150 s covers it under load.
- **Muse Spark on the Meta Model API is still not run in our evals**, so as the second provider it is unmeasured: its accuracy and latency on the 200 gold documents are unknown. The chain's quality numbers on `/models` are Glimmer's and Spark Open's.
- **A document read by Modal and verified by Modal is Glimmer checking Glimmer** (same model, different prompt) unless the owner sets `BASETEN_API_KEY`, in which case Spark Open verifies first.
- **The chain sends documents to third parties the user did not pick.** A request with no AI choice now goes to Modal (the owner's workspace) or the Meta Model API (the owner's key) before the Spark. Before the chain the same request went to the server's single default. Inbox triage still uses only a backend the user chose (`routes_mail.chosen_ai`).
- **The Modal health line is a guess unless `AI_HEALTH_PROBE_MODAL=1`:** "warm" means a call succeeded in the last 5 minutes, "idle" means none did; probing for real would start a paid GPU container each minute someone has `/models` open.
- **`/ai/calls` is shared across all users of one runtime** (provider, model, task, latency only; no content, no user id) and lives in memory: a restart or a second worker shows a different list. The circuit breaker is per process too.
- **`MODAL_KEEP_WARM` is untested:** it uses Modal's documented `Function.autoscaler.update(min_containers=...)` from two scheduled functions; it has not been deployed. The price ($1.95/h for the L40S) is Modal's list price on 28 Oct 2026, not a measured bill.
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
- **Payment chasing drafts; the base rate is a config value.** Reminder steps (`_System/chasing.json`: 3 days before, due day, 7/14/30 days overdue) render editable email drafts that become to-dos; nothing is sent until the user approves it in *Send*. Statutory interest (base rate + 8%, plus GBP 40/70/100 compensation under the Late Payment of Commercial Debts (Interest) Act 1998, checked 28 Oct 2026) is figured for business customers only; the Bank of England base rate is a config value with its effective date in the same file, not a live rate — update it when the Bank moves.
- The web mileage log can add, edit and delete journeys; vehicles can be renamed, deactivated or deleted from the page (deletion is refused, with the reason, while journeys or tagged receipts reference the vehicle). The Review vehicle picker offers *Add a vehicle* when no business vehicle is active. Vehicle pre-fill at scan uses a category plus keyword list.

## CIS and the VAT reverse charge

- **Rules were checked on GOV.UK on 28 Oct 2026, but not in a browser:** `www.gov.uk` is blocked from the build container, so the pages were read through a page-reading service (the CIS contractor and subcontractor guides, CIS 340, the CISR61190–61230 manual pages on the CIS300, the SA103S/SA103F 2026 notes, and both reverse charge guides). URLs are in `services/runtime/app/cis.py` and `packages/ledger/src/accnomos_ledger/vat.py`. Re-check them before relying on the figures.
- **How a deduction is rounded is not written down by HMRC** in the pages read. Code rounds down to the penny (never withholding more than the rate); the contractor's statement is the authority, and a penny either way is accepted by the checks.
- **Nothing is filed.** The CIS300 is prepared as figures and a CSV/JSON in `07 Reports/CIS/`; the user files it through HMRC's CIS online service or CIS software, and verifies subcontractors there. Paying the deductions to HMRC (by the 22nd) is not a feature: match the bank line against `2220 CIS deductions owed` by hand. No inactivity requests, no CIS refunds, no CITB levy, no gross-status turnover test.
- **The AI reading of statements and reverse-charge bills has run on a faked model only** (and the e2e stub never reads one). The prompt and schema are new and unmeasured. `evals/gold/gen_gold_cis.py` makes the documents to measure it with (Qwen names, code figures, distractors) but has not been run on the Spark: only with the stub Qwen. No harness scores the reader against that gold yet.
- **Statements post nothing.** The deduction is posted when the payment is recorded with it; a statement is the evidence the year totals use, and a difference between statements and books is shown, not corrected. A payment matched straight to an invoice on the Bank page carries no deduction; record it with *Record payment* instead.
- **Reverse charge:** the user ticks it; code checks only that both VAT numbers are present and a line is at 20% or 5%. Whether the customer is CIS-registered or has sent an end-user notice is the user's call (the page shows HMRC's wording for that notice). Credit notes against a reverse-charge invoice are refused (not built). The 5% disregard, scaffolding, and supplies of staff are explained, not modelled. Flat Rate and Cash Accounting interactions are explained on the page; the VAT engine has neither scheme.
- **Contractor side:** a payment against a bill already in the books goes through *Record payment* (so the bill shows paid); one with no bill posts the cost, VAT and deduction in one entry. A subcontractor's own VAT (standard or reverse charge) is worked out at 20% or 5% half up from the gross typed in. Removing a payment on the Invoices or Contacts page shows it removed on the CIS page too.
- **Not on Android**, and not in Ask's facts pack or Books.xlsx. Never run against a real OneDrive.
- **Reverse charge under a VAT scheme (merged in `claude/batch-tax`, 28 Oct 2026) is not checked against HMRC.** Under standard accounting the scheme engine gives exactly the boxes `compute_vat_return` does (tested). Under cash accounting and the flat rate it counts a reverse-charge purchase's VAT on the invoice date, in box 1, and in box 4 only outside the flat rate (Notice 733 §6.4-6.5 says how the flat rate treats it; not re-read here because gov.uk was unreachable from that session). Every such return carries a warning to check it; a reverse-charge *sale* on the flat rate stays in flat rate turnover as before.
- **Cash accounting and the income tax cash basis read the same money** (`cash_basis.document_money`, merged in `claude/batch-tax`): payments, matched bank lines and overpayments applied, dated when the money moved. A credit note's credit applied to an invoice is not money and no longer counts as a payment for VAT cash accounting.
- Gates on `claude/cis` (28 Oct 2026, Linux): runtime 1437 passed, ledger 53, evals 332, web e2e 253 passed (58 skipped); ruff, pyright and eslint clean. Flutter not touched.

## Online payments (payment links)

- **Never run against live Stripe or PayPal, and not against their test/sandbox APIs either.** Every provider call in the tests and in test mode goes to fakes (`services/runtime/app/online_fakes.py`) written from the documented request and response shapes (pages and dates in `app/payment_providers.py`). No Stripe test account or PayPal sandbox app was available to this branch.
- Stripe is connected with Connect OAuth (Standard accounts). Stripe says OAuth "isn't recommended for new Connect platforms" but is still the way for an application that needs access to an *existing* account; Accounts v2 onboarding would create a new account controlled by the platform instead of linking the user's own. Revisit before going live.
- PayPal partner onboarding and `PayPal-Auth-Assertion` need PayPal to approve the platform as a partner; not applied for. That a PayPal invoice payment's `payment_id` can be read with `GET /v2/payments/captures/{id}` (for the fee) is unverified: when it fails the user types the fee.
- PayPal.me links (`paypal.me/<name>/<amount>GBP`) are only checked by a redirect on 28 Oct 2026 (the decimal form kept its path); PayPal documents whole amounts in its example. Those payments are never found by code.
- **PayPal is untested against PayPal's real API, sandbox included.** Partner onboarding, the Invoicing v2 calls, `PayPal-Auth-Assertion` and the capture read for the fee have only met the fake in `app/online_fakes.py`; the first run against the PayPal sandbox may need changes. The same holds for Stripe (never called), but Stripe's shapes are better documented.
- Payments are found only when the user opens Invoices (no webhooks: the runtime holds no token to write to OneDrive). A customer's payment is invisible to the books until then, and is posted only when the user approves it. The gross goes to the provider's clearing account (1230 Stripe clearing or 1240 PayPal clearing, not 1210, which is Cash) and the fee is a separate exempt expense out of it. The provider's payout is matched on the Bank page as **Payout from Stripe/PayPal** (Dr 1200 Bank / Cr clearing; unmatching reverses it), so the money is counted once and 1200 Bank only moves when the statement shows it. A payout larger than the clearing balance is refused. Not handled: payouts in another currency, Stripe or PayPal balances used for refunds or disputes (chargebacks), and reserves held back by the provider: those leave a clearing balance the user must journal by hand. Fees on payments approved before this change sat in 1200 Bank; nothing migrates them.
- A link has a fixed amount. If the balance changes (a bank payment, a credit note) the old link still asks for the old amount until the user makes a new one; the list shows "Not the amount owed now". A payment that arrives on an invoice already paid another way is not proposed (paid invoices are not checked); it stays in Stripe/PayPal for the user to refund or record by hand.
## Sales and purchases: items, quotes, orders, repeating, overviews, statements

- **Products and services** (`app/items.py`, `_System/Items/items.json`) fill invoice, quote, order and repeating lines. The *income account* is stored and exported but **invoices still post every sale to 4000 Sales** (the VAT package finds sales by that name), so changing it changes nothing in the books. A bill or purchase order uses one *expense account*: a bill whose lines come from items with different expense accounts posts them all to the account with the most net, which the Review card shows and the user can change. CSV import reads our own columns and Xero's inventory export; rows it cannot read are skipped and listed; it has not been tried on a real Xero file.
- **Quotes** (`app/quotes.py`) post nothing: an offer is not a sale. *Expired* is worked out from the expiry date each time a quote is read; nothing changes the file. *Convert to invoice* makes a draft invoice first and then records the link on the quote; if the runtime stops between the two, an orphan draft invoice with the quote's lines can exist (the quote can then be converted again, and the orphan voided).
- **Purchase orders** (`app/purchase_orders.py`) are not commitments in the books either. *Convert to bill* writes a proposal in Review with the order's lines and totals; the user still approves it, and a bill with a failed check still shows *needs a look*. A bill the model read from a scan is **not matched to an open order automatically**: the user picks *Match a received bill*, which lists that supplier's bills with the difference from the order, and only links them. One bill per order. The same crash caveat applies between making the proposal and saving the link (the proposal id is derived from the order, so a retry finds it, it does not make a second).
- **Repeating invoices and bills** (`app/repeating.py`) run **only when something asks**: opening Sales, Purchases or Repeating in the app, or a call to `POST /repeating/process` (for example from a Power Automate timer). There is no background server, so nothing is made while the user is away; the next visit catches up, at most 12 occurrences per schedule per call, each dated on its scheduled day. *Approve automatically* is a standing approval: an invoice is emailed to the customer from the user's Outlook and posted without another question (if it cannot be sent it stays a draft and says why, so a repeating invoice needs the mail permission on the visit that makes it); a bill is approved and posted unless a check fails. Every occurrence is in the audit log and an item made this way carries `repeating:<id>` as its approver. Not tried against a real mailbox or across a long gap in real use; month-end dates are covered by unit tests only.
- **Sales and Purchases overviews** (`app/overview.py`) are computed from the same invoices and ledger as Contacts and the aged reports, with a 30-day window for money in/out and invoiced. Money out and the bills owed are only as complete as the payments the user has recorded or matched; a bill paid at the time counts as paid.
- **Customer statements** (`app/statements.py`) show customer-side documents only. The list of unpaid invoices appears only for statements that run to today, because open items describe the books now. Sent statements are kept in `03 Sales/statements` and audited. Tested on fake storage and a fake mailbox; not sent through real Outlook.

## Import history and opening balances

- **No export from a real Xero, QuickBooks Online, Sage 50, Sage Accounting or FreeAgent account has been read.** The sample files in `services/runtime/tests/fixtures/import/` (one fictional company, SAMPLE — FICTIONAL COMPANY) were written by hand from what the vendors' help pages say their exports contain. Those pages (central.xero.com, quickbooks.intuit.com, help.sbc.sage.com, support.freeagent.com) could not be opened from the build machine on 28 Oct 2026; their content was taken from web search summaries, partly via third-party guides (TinyTax, QuickFile). The parser accepts many spellings of each column (`FIELDS` in `import_formats.py`), but an export whose header uses none of them is refused, and the FreeAgent Summary CSV layout (code, category, signed total) is a guess.
- Xero's invoice export has one row per line item; open items are de-duplicated by contact and number, so an invoice is counted once, but two different invoices with the same number for the same contact would collapse into one. Credit notes and receipts in an aged list are left out (each is listed as skipped): the list must be of what is still owed per invoice.
- Mapping suggestions are name rules and type words, not a model. A name rule can be wrong (an account called "Vehicle hire" goes to 7300 Motor expenses); every suggestion is shown and editable, and an account whose type we cannot tell blocks posting.
- **Open items are documents, not ledger events.** They live in `_System/Import/opening.json` and appear in aged balances, statements, Books.xlsx and *Record payment*. They cannot be matched straight to a bank line on the Bank page (that needs a posted entry), and a credit note cannot yet be raised against one from Invoices; record the payment instead. Undo is refused while a payment, credit use or credit note points at one.
- Converting part way through a year posts this year's income and costs so far as one entry on the balance date, so a P&L for a period containing that date shows them all at once ("keep"); "retained" folds them into 3200 Retained profit instead. Neither is a tax rule; the VAT treatment (opening balances are on no return) follows VAT Notice 700/12, read through a search summary only.
- Not imported: transaction history before the conversion date, fixed-asset registers and depreciation, payroll year-to-date figures, stock, multi-currency balances, VAT already submitted (the VAT control balance comes across as one figure). Android has no import screen.

## Bank feeds (TrueLayer)

- **Never run against TrueLayer, not even its sandbox.** No TrueLayer app or credentials were available, and this
  session could not open docs.truelayer.com: the request and response shapes in `services/runtime/app/truelayer.py`
  come from TrueLayer's documentation as quoted in search results (28 Oct 2026). Every call in the tests and in test mode
  goes to the fake in `services/runtime/app/bankfeed_fakes.py`, which answers with those same assumed shapes, so a
  wrong assumption would pass every test. Least certain: `POST /connections/extend` (request fields, the
  `user_input_link` answer) and whether a refresh answers a new refresh token (the code keeps one if it does).
- **Why TrueLayer and not GoCardless** (which would need no secret in the user's books): GoCardless reportedly stopped
  taking new Bank Account Data customers in July 2025. That comes from a third-party project's docs; no GoCardless
  notice was found. None of the four providers publishes UK prices for small volumes. `docs/research/BANK_FEEDS.md`.
- **No 2025 FCA change to the 90-day rule was found.** The code follows PS21/19 (reconfirm with the app at least every
  90 days, stop reading otherwise); the FCA's 2026 consultation on the long-term open banking framework was not read.
- **The refresh token is stored**, sealed with the server key `BANKFEEDS_TOKEN_KEY` in the user's
  `_System/bankfeeds.json`. Whoever holds both the key and a user's file can read that user's transactions until the
  consent ends. Rotating the key makes every connection "connect again". There is no key rotation with re-sealing.
- Duplicates between a feed and a statement CSV are found by code (same amount, dates within 2 days, same reference or a
  word in common), tested on the gold Barclays CSV and six made-up feed lines only. Two payments of the same amount to
  the same payee within 2 days, one only in the CSV and one only in the feed, would be taken as one. Same amount and
  date with no word in common are kept as two (a duplicate the user can ignore is safer than a lost payment).
- Fetched on app open at most hourly per tab, and only on a device where the Bank page has seen a feed. Two tabs
  syncing at the same moment could both add the same new lines (no lock across requests; there is no server state).
- Pending transactions are not read (booked only). Only GBP lines are kept; others are counted as skipped.
- Android does not show bank feeds yet; the phone still imports CSVs through the runtime.

## Payroll

- **Not HMRC-recognised for RTI, and never files.** PAYE RTI is not on HMRC's REST Developer Hub: it is GovTalk XML sent to HMRC's Transaction Engine (Document Submission Protocol, IRmark), and live filing needs HMRC software recognition (HMRC "How to use the Internet services: RTI" v1.94, read 28 Oct 2026). Accnomos has neither recognition nor SDST test credentials. It generates FPS and EPS files to the 2026-27 schemas ("RTI RIM 2027 v1.0", vendored in `services/runtime/tests/fixtures/hmrc_rti_2026_27/`, and every generated file in the tests validates against them with `xmllint`) for the user to check. The page says, beside every RTI download: *File with HMRC's Basic PAYE Tools or your payroll provider. Direct submission from Accnomos is currently not available.* Every FPS and EPS file also opens with an XML comment saying it was not submitted to HMRC, must be filed using HMRC's Basic PAYE Tools (or a recognised provider's software) and that direct submission is not available. Basic PAYE Tools cannot import these files; they are a checklist of what to type or what the provider should send. There is no GovTalk envelope, no IRmark and no submission path; `EmployerSettings.rti_test_submission_enabled` is a switch typed `Literal[False]` (it cannot be turned on) for a future External Test Service path, which would need SDST credentials (owner work).
- **Rates verified on 28 Oct 2026** (re-read independently the same day on branch claude/payroll-finish, through a web reader since that container could not reach gov.uk directly: every figure on the employer rates page, including the final Scottish bands, the SSP £123.25 / 80 % of AWE from day one, SMP £194.32, student and postgraduate loan per-period thresholds, Employment Allowance £10,500, and TPR's 2026-27 auto-enrolment table, matched the code) against GOV.UK and HMRC's technical specifications for 2026-27, each cited in `app/paye_rates.py` and pinned a second time in `tests/test_paye_rates.py`: rates and thresholds for employers (updated 1 Sep 2026), PAYE Tax Table Routines v24.0 (Scottish parameters "subject to parliamentary approval" when issued), NI guidance for software developers v1.1, student loans from 6 April 2026, the DWP/TPR auto-enrolment thresholds. Re-check every spring; pay dates outside 2026-27 are refused.
- **What is tested against HMRC's own figures:** Tables A free pay, all twelve 2026-27 NI worked examples (HMRC's example 3 prints a total of £47.94 where its steps add to £47.69; the steps are tested), the full SSP amounts table, two director examples. **What is not:** HMRC publishes no 2026-27 PAYE worked examples and its calculators could not be scripted, so income tax goldens are hand-worked from the routines spec (each step written in the test). A payroll professional should run a sample through HMRC's calculator or Basic PAYE Tools before relying on it; every figure is labelled "Estimate — check before filing".
- Not covered (said on the page): quarterly, annual or irregular pay; directors on the alternative NI arrangements; SPP, SAP, ShPP, SPBP, SNCP; benefits in kind, Class 1A, court orders, apprenticeship levy, off-payroll workers; pension refunds after an opt-out and three-yearly re-enrolment (flagged, not calculated). New starters' suggested tax codes follow HMRC's long-standing starter-checklist rules, which the 2026-27 CWG2 no longer prints, so they are marked unverified. Directors with student loans are calculated per period and flagged.
- Pension provider files, checked against the providers' current published specifications on 28 Oct 2026 but **never uploaded to a live provider account**: Nest from the Employer payroll guide on Nest's site (contribution schedule, file version 4; frequency "Tax Weekly"/"Tax Monthly" schedules are not written; the paper opt-out notice fields are left blank); The People's Pension from its Contributions file data requirements v9 (still the version it publishes; details-section headings and its refused characters handled); Smart Pension from its "CSV Specification – PAPDIS 1.0 – PAP01" (43 fields; a heading row is written although the spec does not say whether one is expected; net pay arrangement only, relief at source is refused with a message); NOW: Pensions from its undated online guide. Missing/partial contribution codes are derived for leavers, opt-outs and nil earnings only (not family leave, group or payment-source changes). The generic CSV is Accnomos's own layout.
- **Property tests** (`tests/test_payroll_properties.py`, Hypothesis): pence rounding helpers, NI within a penny of the exact percentage, loans in whole pounds, SSP caps, cumulative PAYE summing to the month-12 liability, every payslip's net = gross − sacrifice − deductions and the journal balancing, over thousands of generated inputs. They prove internal consistency, not agreement with HMRC.
- **End-to-end:** `e2e/paye.spec.ts` (settings → employee → pay run → Review → approve → FPS with its notice, EPS, Nest and Smart Pension files, payslip PDF, P32 XLSX) was first run on the payroll-finish branch, where it found and fixed two bugs: the settings panel collapsed as soon as a PAYE reference was typed, and amounts showed without thousands separators.
- Employee records hold personal data HMRC requires (NI number, date of birth, address, gender as HMRC holds it) in `_System/Payroll/employees.json` in the owner's OneDrive only; audit lines carry ids, never those details.
- The older *quick estimate from timesheets* is still on the page for owners whose provider runs payroll: monthly, 1257L month 1, England/NI, category A; its constants now come from `paye_rates.py`. Undoing its ledger entry from outside the Payroll page leaves that run "confirmed" until it is reopened.

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
- A journal with VAT (and its void, automatic reversal or a VAT recode) counts on the side it names: boxes 1 and 6 for
  sales, 4 and 7 for purchases, with its signed figures; the VAT page lists each one with the boxes it moved, and Ask's
  totals use the same rule. Boxes 2, 8 and 9 (NI/EU) cannot be reached by a journal. A reversal into a later period can
  make box 4 (or box 1) negative there; that HMRC's MTD VAT API accepts negative box values was **not re-checked**
  against HMRC's specification on 28 Oct 2026 (developer.service.gov.uk is not reachable from the session that made
  this change); the ledger allowed negative boxes before it.

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

## Landlords and property income

- **Built on fakes, never run against HMRC.** `/property/*` (`services/runtime/app/property.py`) and the relay's UK property routes (`services/hmrc-relay/relay/itsa_property.py`) are tested on the in-memory OneDrive and a mocked HMRC. The relay tests use HMRC's own example request bodies from github.com/hmrc/property-business-api (6.0), not a recorded sandbox exchange. No sandbox UK property business has been created or updated from this code. Direct submission is **sandbox only** (403 against production unless `RELAY_ITSA_PRODUCTION=1`, which nothing sets); for real use the page saves a JSON file in `07 Reports` with the exact bodies to submit through other MTD software or an agent.
- **The tax rules were checked through gov.uk search results, not by opening gov.uk** (this session's network could not reach gov.uk, developer.service.hmrc.gov.uk or assets.publishing.service.gov.uk; 28 Oct 2026). HMRC's API definitions and the SA105 mapping file were read from HMRC's GitHub repositories. Each rule cites its page in `property.py`; re-check them on gov.uk before relying on them.
- **The finance cost credit is an estimate.** 20 % (22 % from 2027-28) of the lowest of finance costs plus brought forward, property profits and, only if the user types it in, adjusted total income above the personal allowance. Accnomos has no view of other income, so by default the third limit is not applied and the page says so. Brought-forward amounts are typed in by the user per tax year.
- **As approved, not cash basis.** Each entry counts on its own date. HMRC's default for landlords with receipts up to £150,000 is the cash basis; the summary warns, it does not convert.
- **Ownership:** spouses and civil partners are taxed 50:50 unless the user ticks that a Form 17 declaration is in force; Accnomos does not check that HMRC holds one. Other joint owners use their stated shares. Splits are exact to the penny (largest remainder); only the user's own share goes to HMRC. A property's other owners file their own returns: Accnomos holds no books for them.
- **What is left out:** capital allowances, structures and buildings allowance, losses brought forward, the non-resident landlord scheme (`taxDeducted`), lease premium working sheets (the user enters the taxable part), foreign property, the property income allowance in the submission (shown as a comparison only), Rent a Room "jointly let" flags, and furnished holiday lettings before 2025-26 (refused: the regime ended on 6 April 2025).
- **Quick entries are kept off the VAT return** (VAT code O). A VAT-registered landlord with commercial lets opted to tax should record those through Invoices and Review instead.
- **An ordinary receipt reaches a property only when it is tagged** on the Property page (`_System/Property/tags.json`); untagged entries on the property accounts go to the only property when there is one, otherwise they count as 100 % the user's with a warning. Mortgage interest in an ordinary account counts as a finance cost only if the account name says interest or mortgage.
- **Self-employment overlap:** branch `claude/self-employment` maps 4000–4899 to turnover and 8000–8099 to depreciation; the property accounts (4700–4740, 8500–8580) would be counted there too when both are merged, unless its mapping skips them (noted in `docs/reviews/landlords/REVIEW.md`).
- **Android:** nothing yet; the Property page is web only.

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

## Month-end close

- **Run on fakes only**: unit tests on the in-memory OneDrive (`services/runtime/tests/test_month_end.py`) and the e2e
  spec on the test runtime (`apps/web/e2e/month-end.spec.ts`), never against a real OneDrive or mailbox. How long a run
  takes on a large real book through Graph is unmeasured; it reads the whole ledger and every bank line once.
- **Closing does not lock anything.** Nothing stops a receipt, bank line or undo being dated into a closed month: the
  app detects it afterwards (snapshot hash), says what changed with before/after figures and offers a re-close. The
  snapshot and close record are plain files in the user's OneDrive: not signed, so an edit made there by hand would be
  reported as a change, or could forge a record.
- Bank coverage is inferred from the dates of the lines in each imported statement (statement files carry no period).
  A run of up to 3 days without a statement at a month edge or between two statements is taken as days without
  transactions; a longer quiet spell shows as a missing statement. Balances are compared only between consecutive
  statements of one bank, and only when both carry running balances. Banks are told apart by the file name
  (`<date>_<bank>.csv`), so two accounts at one bank are treated as one.
- There is no suspense account in the chart: "uncategorised" means a balance on `7999 Sundry expenses`, where costs
  with no better category go. Duplicates are the same counterparty, amount and day; "unusual" is over 3× the
  supplier's median of at least three earlier purchases and £100 over it. Rules of thumb, not an audit.
- Outlook is only read in a dry run (what intake *would* copy), and only when the app says intake is on; copying is
  still the user's *Check now*. Documents in `00 Inbox` always block, because their dates are unknown until scanned.
- Cards expire after 15 minutes and are not stored; reloading the page shows the last run without its cards (run again).
  The VAT step shows the boxes for the period the month ends; filing stays on the VAT page. Corrections to a submitted
  period follow the existing Undo rule; anything else (HMRC's error-correction rules) is not handled.
- The balance sheet is the trial balance by account code with the profit to date in place of retained earnings; no
  opening balances, accruals or prepayments.
- The phone is read only (the last run, its summary and changes since the close) and its widget tests were written in
  this branch and not run here (no Flutter SDK); the web streams the steps, the phone does not.

## Load sample books

- **Never run against a real OneDrive.** *Load sample books* (`POST /books/sample`) and the seed it runs have only run on the in-memory fake OneDrive (`test_sample_books.py`, the e2e spec). **How long it takes against Graph is unmeasured.** On the fake the whole seed makes about 11,300 storage calls (most of them folder listings and reads behind each approval), and each is roughly one Graph request, so at a few tenths of a second each it could take well over half an hour, more than a token lasts; throttling (429s are retried) is untested there. (`tools/seed_demo.md` said "several hundred Graph calls"; corrected.)
- The Graph token expires after about an hour and the runtime cannot refresh it. The page hands the runtime a fresh token every four minutes and whenever the run says it needs one; if the page is closed, the run waits ten minutes, then stops, and the next press (or visit to Home) carries on from the recorded step. Resuming was checked on the fake by refusing the token at, and right after, every one of the 710 writes of a run (1,420 runs, each compared with the books the CLI writes): the first pass found 11 failures in 6 kinds of two-write action, all now repaired and each kept as a named test (an approval posted but not saved, a filed document not yet recorded, an emailed receipt copied but not recorded, a sent invoice's PDF, a filed statement whose lines were not stored, a payment's entry without its record or its record without its line match, a rule coding posted but not saved). A refusal at a read or listing between writes, and a second stop in the same step, were not swept.
- `test_sample_books.py` waits for the background run to stop (an event the run sets), not for a fixed number of
  polls; the old polling budget lost the race on loaded machines (`docs/reviews/known-fixes/REVIEW.md`).
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

## Spending, cheaper options, shopping list

- **Only the user's own books.** Price comparisons cover suppliers already in the ledger, from the line items of approved receipts and bills. No shop, marketplace or price site is searched or scraped. A live price search is an interface (`app/price_search.py`) switched off by default (`PRICE_SEARCH_PROVIDER` empty); the only provider that exists is a test fake, which refuses to run outside test mode. No real provider has been chosen, wired or tested, and the UI says "Live price search is off".
- **Line items are only as good as the reading.** Entries posted by hand or by a bank rule have no lines; a reader that misses a pack size ("6 pack") makes the price per item six times too high. Normalisation is regular expressions for mm/cm/m, g/kg, ml/l, "pack of", "6x1.5L", "10pk", "pair" and 17 colour words; feet, inches, "dozen" and brands are not understood, and units written as words ("fifty metres") are not read.
- **"Same product" is narrow by design.** Code joins only the same name words, size and colour; two names are joined only by the user, or by the model where code's size rules agree, and the model's view is never stored. The model's same-product judgement has run on the test stub only. Equivalence allows a different colour (noted) but not a different measure or a width more than 10 % off.
- **Savings are hindsight, not a forecast.** "Could save" is (average paid − lowest paid in the books) × the usual monthly volume over up to 12 months; it ignores delivery, minimum orders, stock, quality and price changes since. A live offer's saving (when a search is on) is labelled with its source and time and says to check it before buying.
- **Spending summary**: the figures are code's; the model's words pass Ask's number check (every figure must be in the facts; a previous-period figure must name its period), so it shares Ask's limits: a figure that exists in both periods cannot be told apart. Recurring and unusual rules are fixed thresholds (3 months, £100, 3× the median), not learnt. Spend is before VAT. Run on the stub model only.
- **Voice**: "Remember to order 2-inch bolts for the Hendon job" is tested through `/books/ask/voice` with a stubbed transcription and test mode's pattern-based intent stub, not with Muse Voice or a real model; how well Glimmer or Spark fill `item_text` and `job_ref` from such sentences is unmeasured. A size in inches is part of what the item is (2-inch and 3-inch bolts are different products), not its unit of price.
- **Shopping list**: one list per books folder, at most 300 items, rewritten whole (an ETag conflict re-reads and retries). Turning it into a purchase order or a supplier email is not built; the buttons are disabled. Android has no screens for these features.

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
- Home shows the VAT tile and the (all-VAT) Deadlines card only for a VAT-registered business: `GET /books/dashboard`
  reads `_System/profile.json` and answers `vat_applies` (an unreadable profile counts as the default, a VAT-registered
  company, so VAT shows). Before the dashboard answers, the web uses the profile it last read on this device. Customers
  and Suppliers in the menu open the same Contacts page (it has no filter yet).
- Several menu pages are being built elsewhere (`/sales`, `/purchases`, `/accounting/*`, `/self-employment`, `/personal`
  and others); the menu shows each only once its page is in the build, so today those groups are shorter.
- Android has one account at a time (*Switch account*). Its More screen leaves out Invoices and Payroll for personal
  books and mentions VAT under Reports only when the books have it (`GET /profile` features, read when the tab first
  opens: after *Switch account* it follows the new books once the app restarts, or the tab is rebuilt), and Home drops
  the VAT tile on `vat_applies=false`. The bottom bar's VAT tab is still there for every profile (its screen answers
  with the runtime's sentence for books without VAT). `flutter analyze` and `flutter test` (279 tests) pass, on
  Flutter 3.47.8 in a Linux container; not run on a phone.
## Reports and exports

- **Nothing has been test-imported into Xero, QuickBooks Online, Sage 50, Sage Accounting or FreeAgent.** Each import file
  follows the vendor's published template as checked on 28 Oct 2026 (golden files in `services/runtime/tests/fixtures/exports/`
  hold the headings and first rows exactly). How each was verified:

  | File | Checked against | How sure |
  |---|---|---|
  | Xero manual journals | Xero Central's article is behind a login; headings from Xero's template as copied by Sequence (docs.sequencehq.com) and corroborated by Business Importer and PostTrans | secondary sources only |
  | Xero contacts | central.xero.com/0/article/Import-contacts-into-Xero (column names, rules) | official; the full heading row comes from Xero's download, which we could not fetch |
  | Xero sales invoices, bills | central.xero.com/0/article/Import-customer-invoices-UK (DD/MM/YYYY, tax names); heading rows as copied from SalesInvoiceTemplate.csv / BillTemplate.csv (notestoself.dev, syslumelab.com, kedgework.com, gigsorted.com) | rules official, headings secondary |
  | Xero bank statement | central.xero.com/0/article/Import-a-CSV-bank-statement | official; Xero maps columns at import |
  | Xero chart of accounts | template as copied (accountantmaster.com); UK default codes from two independent lists | secondary |
  | QuickBooks journal entries, invoices, bank, chart of accounts, customers, suppliers | quickbooks.intuit.com learn-support articles (US journal and bank articles, UK invoice and chart articles, global customers/suppliers article) | official; QuickBooks maps columns at import, and its sample files were not downloaded |
  | Sage 50 audit trail, nominal records | gb-kb.sage.com 250321114601443 and 250321114606157 (21 Mar 2025), 200427112601918 | official |
  | Sage 50 customer and supplier records | first nine columns as gb-kb.sage.com 220225121155067 and import.makingithappen.co.uk list them | partly official |
  | Sage Accounting journals, contacts | gb-kb.sage.com 222001000100916 (13 Feb 2025) and 240701101019900 (8 Oct 2026) | official |
  | Sage Accounting chart of accounts | ie-kb.sage.com 222001000100819 for the five headings; the UK page names the columns but not the UK tax-rate words, so "Standard / Lower / Zero / Exempt / No VAT" is our guess | headings official (Irish page), tax words unverified |
  | FreeAgent bank statement, contacts, invoices | support.freeagent.com 115001222564, 115001222864, 36670919996050 | official; the invoice importer is for Practice Partners only, and whether a multi-line invoice repeats its invoice columns on each row is not stated (we leave them blank after the first) |

- **Account mapping defaults are ours.** Xero's UK default codes come from two third-party lists that agree, Sage 50's from a
  v26 list and Sage's control-account article, QuickBooks' Debtors/Creditors from Intuit; the QuickBooks detail types for
  equity and overheads ("Owner's Equity", "Office/General Administrative Expenses") and the Xero tax names for zero-rated and
  exempt income are standard names we did not see on a vendor page. The bank account always needs the user's choice
  (quality "check"); Xero may refuse bank accounts on manual journals (not confirmed on a Xero page), so its file says to bring
  bank lines in with the statement file.
- **Journals carry no VAT code** so the new package does not count VAT already on Accnomos's returns. Bank files are the
  books' 1200 Bank entries, not the bank's own statement lines. Credit notes are in no invoice file. The Sage 50 file puts the
  single VAT control account on 2202 VAT Liability.
- **VAT reports:** box wording is HMRC's VAT Notice 700/12 (sections 3.2–3.10, page updated 19 Dec 2025) and the digital-links
  trail follows VAT Notice 700/22 paragraph 3.2.1 (updated 1 Apr 2022), both read on gov.uk on 28 Oct 2026. The return is the
  same `compute_vat_return` the VAT page submits; there is no cash accounting or flat rate scheme. No EC Sales List: since
  2021 only Northern Ireland goods sold to the EU need one, and the books record no NI/EU movements (boxes 2, 8, 9 are 0).
- **Reports are not statutory accounts.** No year-end close, accruals, prepayments, depreciation or stock: the balance sheet
  shows earlier profit as one brought-forward line, and fixed-asset schedules, budgets, tracking and the cash-flow forecast
  are left to the accounting-tools feature (ids reserved). Bank reconciliation reads the Bank page's matching against 1200 Bank
  only. Debtor and creditor days are simple ratios. The general-ledger exceptions are fixed rules (round £100s from £500,
  weekend dates, approval over 90 days late, no account code, unexpected sign), a prompt to look, not findings.
- Run on fake storage only (unit tests and the e2e spec); no PDF or XLSX has been opened in a real viewer other than by the
  tests' parsers, and nothing has been saved to a real OneDrive.

## Accountant collaboration

Branch `claude/accountant`; review in `docs/reviews/accountant/REVIEW.md` (gates on that branch, 28 Oct 2026: runtime
1432 passed, connectors 63, e2e 255 passed / 58 skipped, `flutter test` 274). **Nothing here has called Microsoft Graph**:
every sharing call ran against httpx mocks shaped like the Microsoft Learn examples, or the test-mode fake sharing world.

- **Sharing the personal app folder is documented, not tried.** `driveItem: invite` lists `Files.ReadWrite` as the least
  privileged scope and forbids permissions only on a personal drive's *root* item; the app folder (`Apps/Accnomos`) is not
  the root, and the app-folder page says it "supports all the standard item operations". So the web asks a personal
  account for `Files.ReadWrite` (the whole OneDrive) when they invite someone. If Microsoft refuses anyway, the client is
  told to share the folder in OneDrive by hand and record it ("I shared it myself"), or to use a work account; a
  dedicated shared folder outside the app folder is **not built**.
- **A view-only accountant's write access to `_System/queries`** is a second permission on a subfolder of a folder shared
  read-only. OneDrive documents path-addressed items and per-item permissions; whether a child can be given more than its
  parent on a personal OneDrive has not been tried.
- **`sharedWithMe` is deprecated** and "will stop returning data" after November 2026, with no documented replacement
  (Microsoft Q&A says so). The portal also lists client codes the accountant adds by hand (from the invitation email);
  after November it depends on them. `?allowexternal=true` (other tenants) is sent; cross-tenant and personal ↔ work
  sharing (a personal-account client, a work-account accountant) has not been tried.
- **Identity**: the audit names the accountant by the email Graph `/me` gives for their token (needs `User.Read`, which
  sign-in asks for). A ledger event's `approved_by` still comes from `X-User`, as everywhere, so an accountant's approval
  is attributed by the audit line, not by the event. In test mode the identity is `X-User`.
- **Read-only** is enforced by the runtime for a view-only open (403 before Graph) and by the client's OneDrive permission
  otherwise. Inside a client the browser token has `Files.ReadWrite.All` (queries are writes); the accountant's app
  registration must allow `Files.Read.All` and `Files.ReadWrite.All`, not yet added in Entra.
- **The portal summary is the client's own word**: name, kind and VAT stagger come from the profile the client saved in
  Settings › Your accountant (pre-filled from that device's business details); without one the portal shows the folder
  name and "Not set by the client". Annual VAT accounting is not worked out. **MTD for Income Tax deadlines are not
  shown**: gov.uk could not be reached from this session (blocked by the network policy), so the dates could not be
  checked against the official source and were left out. "Last activity" reads only this and last month's audit files.
- The browser's previews and file links inside a client read `/drives/{d}/items/{i}:/…`; the test-mode Graph look-alike
  does not serve that address, so client previews are untested. Upload to Inbox and onboarding refuse inside a client.
- Revoking stops future access; copies an accountant downloaded stay with them (the consent text says so). Microsoft
  sends the invitation email (`sendInvitation: true`); its delivery and wording are Microsoft's and were not seen.
- Android shows who has access and the query threads, read-only (More › Your accountant); answering is on the web.

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
  tested end to end; the `0` build has been built and its files scanned (the pre-launch words are there), not run in a browser.
  The submission build is checked twice for pre-launch wording ("Early access / testers", "coming soon", "beta",
  "launch"/"launching", the early-adopter list): `e2e/submission-mode.spec.ts` reads every page's DOM text, title,
  description and labels, signed out and in (not the pixels of screenshots), and CI scans every file of the
  production export (`scripts/prelaunch-words.mjs`). In the submission build the privacy page leaves out the
  early-adopter list, since that build cannot collect sign-ups. "Available on Android" on the landing page means the
  app exists and builds; per `docs/submission/JUDGING.md` the Play production listing was still in review on 27 Oct
  and no real-phone sign-in is recorded. "Try the demo" (`DemoLink.tsx`) starts a demo sandbox and opens `/judges`
  inside it in one click; it is a plain link to `/judges` underneath, which explains when the server runs no demos.
- **Site layout (28 Oct 2026, `docs/reviews/site-layout/REVIEW.md`).** `/terms` and `/judges` now also use the public
  shell signed out. The landing page names landlords and personal finances because the books and the Personal page
  serve them today. Its text comes from
  `docs/marketing/COPY.md` (written by Muse Spark), checked line by line against the code; four lines were corrected
  where the deck claimed more than the code does (pricing in the app, "no" to model training whatever the provider,
  an always-independent second reading, an overtime rate on timesheet cards). **The terms of use were written from this repository's docs, not by a lawyer.** MTD dates and thresholds are
  deliberately not stated on the page: gov.uk could not be reached from the session that wrote it, so nothing there
  depends on a rule that was not checked. The "before" screenshots were taken from the `site` branch (the exact export
  Plesk serves at accnomos.com) served locally, because accnomos.com itself was blocked from that session; with no
  runtime reachable they also show the "reader isn't answering" strip, which the live site would not. Lighthouse was
  run on a local production export behind a local gzip server (mobile 96 performance, 100 accessibility; desktop 100,
  100), not against accnomos.com behind Plesk. At integration (after `claude/batch-tax` reached `main`) two lines were
  corrected: landlords' property income figures and flat-rate VAT are in the build now, and only sending payroll (RTI)
  to HMRC is missing, not the FPS and EPS files.

## Security and deployment

- Single-worker limits: the **rate limit is per process** (in-memory buckets, cleared on restart; several replicas would each allow the full rate) and the relay's spent-state set is per process, hence one relay worker (`deploy/Dockerfile.relay`).
- The Graph provider's `_safe_path` raises a plain `ValueError`, so a hand-edited unsafe path in the user's books returns a 500 with a correlation id, not a 400 (nothing can escape the folder either way).
- Deploy files are checked by config tests only: images not built, `docker compose up` and `nginx -t` not run, `.htaccess` not tried on Apache/Plesk, base images pinned by tag not digest, nothing tried against live `api.accnomos.com`. `Permissions-Policy` lists the deprecated `interest-cohort`.
- No authentication of callers beyond holding a valid token; `X-User` is not checked against the token. No script CSP on the web app. The AI key and HMRC tokens live in browser storage, readable by an XSS on the web origin. Prompt injection beyond file names is only mitigated by checks and approval.
- The shared `.venv` on the Spark can hold editable installs from another checkout; run `uv sync --all-packages` in the checkout you serve from.

## Testing and process

- The web has no unit tests; pages are checked by `pnpm run build` and the Playwright suite. The e2e suite runs on GitHub as the `e2e` job of `.github/workflows/ci.yml` on every push and PR (first green run 28 Oct 2026, `docs/reviews/ci/REVIEW.md`); its fake calendar is seeded but no e2e flow uses it. The suite does not prove real MSAL, Graph, HMRC relay or model accuracy.
- The SAM response fixture `services/runtime/tests/fixtures/sam_response.json` is marked ILLUSTRATIVE and must be replaced with a captured real response before turning on `SAM_CROP`.
