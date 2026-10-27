# Project description (draft for the Meta Global AI Developer Hackathon, Indie track)

Every claim below is taken from `README.md` ("What works today"), `docs/HONESTY.md` and `docs/META_MODELS.md` as at 27 Oct 2026.
The 150-word text is 149 words and the 400-word text 395 (`wc -w` on the text between the rules). The "ran live" runs are the maintainers' own with no committed log (`docs/HONESTY.md`), so say "our record", not "verified". The 88 % figure is all fields right on 200 synthetic documents (`evals/REPORT_glimmer_messy_200_2026-10-27.md`); the same first 60 documents score 73 % in their own report and 82 % in the 200-document one, because the scoring changed (a `side` field was added and the expected status made explicit). Quote the 200-document run, not a mix. Owner: Zohaib Sharif, Zaytuna Business Services Ltd (solo).

## Tagline

**Accounting, intelligently done: Meta models read the paperwork, you approve, code does the VAT, and the books stay in your OneDrive.**

(Shorter: *AI proposes, you approve, code calculates.*)

## 150-word version

---
Accnomos is bookkeeping and MTD VAT for UK small businesses. Upload a receipt and a Meta model (Muse Glimmer 30B on our own hardware, or Muse Spark with your key) reads it into strict JSON. Code then checks the arithmetic, VAT number and period, and a second model reads the same image independently; code compares six fields. You approve, and an immutable ledger event is written. The nine VAT boxes are calculated by code, never by a model, and a sandbox HMRC submission is built into the web app.

There is no Accnomos database: the books are files in the user's own OneDrive, and our servers keep nothing.

Honestly: the read, approve, ledger, VAT-boxes path ran live on 26–27 Oct on a personal account; almost everything else is tested on fakes. HMRC is sandbox only and has not yet been run end to end. All demo data is synthetic.
---

## 400-word version

---
**The problem.** A VAT-registered UK small business must keep digital records and file its VAT return through Making Tax Digital-compatible software, and someone has to turn a shoebox of receipts into those records: the owner's evenings, or a bookkeeper's fee. Accnomos asks whether AI can do the typing while the owner keeps control of both the decisions and the records.

**The approach.** Accnomos splits the work three ways. *AI proposes*: a Meta model reads a receipt or invoice and returns structured fields. *The user approves*: nothing is posted until they tap Approve, and Autopilot, which posts without a tap, is off by default and only applies to suppliers the user has made a rule for, with Undo. *Code calculates*: arithmetic checks, VAT treatment, ledger events, the nine VAT boxes, invoice totals, mileage and pay-run estimates are all deterministic code with tests. Models write words only (Ask, reminder drafts, inbox summaries, the planner's rationale), and any figure in a model's answer that is not in the user's books is replaced by the facts.

**Your books, your OneDrive.** The runtime is stateless: each request carries the user's Microsoft token and AI settings and nothing is kept. The ledger is append-only event files in a `_System` folder, and `Books.xlsx` is regenerated from them for the accountant. If the user disconnects Accnomos, every file is still theirs.

**What is built.** Receipt scan, review and approve; an independent second-reading verifier; the VAT return by period with deadlines; an HMRC sandbox submission flow through a relay that holds only the client secret; Ask (typed and voice); bank-statement matching; sales invoicing with PDF and Outlook send; jobs and timesheets; mileage; pay-run estimates; Outlook intake and triage; a day planner; a Next.js PWA and an Android app. Meta models: Muse Glimmer 30B, Muse Spark 1.3, Muse Spark Open, Muse Voice Transcribe, SAM 3.1 (off by default) and Muse Image (brand art).

**What is honest.** The read-to-VAT-boxes path ran live (our record; no log committed) on a personal Microsoft account with Glimmer on our DGX Spark. On 200 synthetic messy documents Glimmer got every field right on 88%. Most other features are tested on in-memory fakes only. HMRC is sandbox only and never run end to end; key-mode Spark, Baseten, SAM and Voice have never been called for real; the Android app has not been analysed or tested; payroll is an estimate, not RTI. `docs/HONESTY.md` lists every known gap.
---
