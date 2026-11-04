# Project description (Meta Global AI Developer Hackathon, Indie track)

Refreshed 4 Nov 2026. Every claim below comes from `README.md`, `docs/HONESTY.md`, `docs/PROVENANCE.md`,
`docs/submission/META_MODELS.md` and the reports named there. Owner: Zohaib Sharif, Zaytuna Business Services Ltd (solo).
**Word counts** (`wc -w` on the text between the rules, so `95 %` counts as two words): the 150-word text is **154**,
the 400-word text **420**. The form's counter may differ; trim a sentence if it objects.

Rules for editing:

- The "ran live" runs are the maintainers' own with no committed log (`docs/HONESTY.md`): say "our record", not "verified".
- Quote the 27 Oct 200-document extraction runs with repairs, re-read and Verifier on (Spark Open 91 % clean / 93 % messy,
  Glimmer 85 % / 80 %), not the earlier 60-document or no-Verifier runs. Always say "synthetic documents".
- Quote Autopilot with its caveat (17 false posts in 467, all re-dated copies); never shorten it to "0 false posts".
- Muse Spark 1.3 is measured (95 % / 96 % on 200 synthetic documents each, `evals/runs/spark13_200`, `spark13_messy_200`); Muse Voice Transcribe and SAM 3.1 have run live (`evals/runs/live_checks_2026-11-04`, `evals/runs/sam_crop_live`). SAM showed no reading gain on synthetic scenes: never say it improves accuracy.
- HMRC is sandbox only: the demo's VAT return goes to HMRC's sandbox with a test user HMRC makes for it (run end to end on
  4 Nov 2026, `docs/HMRC_SANDBOX_DEMO.md`); never say "files to HMRC" without "sandbox". The bank feed has run against
  TrueLayer's sandbox only. The Android app has run on the owner's own phone and the emulator, no other phones.
- iPhone is not built: say nothing about it (no "coming soon": the public pages must not promise anything for later).

## Tagline

**Accounting, intelligently done: Meta models read the paperwork, you approve, code does the VAT, and the books stay in your OneDrive.**

(Shorter: *AI proposes, you approve, code calculates.*)

## 150-word version

---
Accnomos is bookkeeping and MTD VAT for UK small businesses, sole traders, landlords and households. Your books are files in your own OneDrive; no database.

Snap a receipt on the Android app, upload it on the web, or let it arrive by email, and a Meta model reads it: Muse Spark 1.3 on the Meta Model API first, Muse Glimmer 30B (open weights, our own server) as fallback or local mode. Code checks the arithmetic, you approve, and code calculates the nine VAT boxes for an HMRC sandbox submission. Ask, typed or spoken through Muse Voice Transcribe, answers with every figure checked against your books.

Measured on 200 synthetic documents each: every field right on 95 % clean and 96 % messy for Muse Spark 1.3, 85 % and 80 % for Glimmer.

Honestly: HMRC and the bank feed are sandbox only, most features are tested on fakes, and real photos will score lower.
---

## 400-word version

---
**The problem.** A VAT-registered UK small business must keep digital records and file through Making Tax Digital software, and someone has to turn a shoebox of receipts into those records. Accnomos asks whether AI can do the typing while the owner keeps control.

**The approach.** *AI proposes*: snap a receipt on the Android app, upload it on the web, or let Outlook intake pick it up from email, and a Meta model reads it into strict JSON. *You approve*: nothing posts until you tap Approve. *Code calculates*: arithmetic checks, ledger events, the nine VAT boxes, invoices, payments, credit notes and reports are deterministic code with tests. In Ask, every figure is checked against the books; an invented number is replaced by the facts.

**Your books, your OneDrive.** The runtime is stateless: the ledger is append-only event files in your OneDrive, and `Books.xlsx` is regenerated for your accountant. Disconnect and every file is still yours.

**What is built.** Receipt capture, review and a second reading; contacts and ageing; invoicing with part payments and credit notes; bank statements, rules, reconciliation and an Open Banking feed; reports; an audit trail; the VAT return with an HMRC sandbox flow; MTD Income Tax figures for sole traders and landlords; jobs, mileage, payroll; household budgets and goals; Ask, a hands-free assistant and chat actions that wait for Approve; web and Android apps.

**The Meta models.** Muse Spark 1.3 on the Meta Model API answers first on the live server; Muse Glimmer 30B, Meta's open-weights model on our own server, is the fallback and the local mode. Muse Voice Transcribe hears spoken questions, SAM 3.1 crops receipt photos, Muse Image made the brand art, Muse Code helped write the app.

**Measured, and its limits.** On 200 synthetic documents, clean and messy, every field was right on 95 % and 96 % (Muse Spark 1.3) and 85 % and 80 % (Glimmer); real photos will score lower. Ask got 32 of 32 figures exact. Autopilot, off by default, made no false posts on 154 clean documents but 17 in 467 overall, all re-dated copies of receipts already posted.

**Honest status.** The Meta paths ran live on the public server on 4 Nov 2026, records committed. HMRC is sandbox only: the demo files to HMRC's sandbox with a test user. The bank feed has met TrueLayer's sandbox only; the Android app one real phone, the owner's. Most other features are tested on fakes. Demo data is fictional. Only the owner's own server predates the event; `docs/HONESTY.md` lists every gap.
---
