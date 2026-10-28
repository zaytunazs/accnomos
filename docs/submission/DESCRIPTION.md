# Project description (draft for the Meta Global AI Developer Hackathon, Indie track)

Refreshed 27 Oct 2026. Every claim below comes from `README.md`, `docs/HONESTY.md`, `docs/submission/META_MODELS.md` and the reports named there. Owner: Zohaib Sharif, Zaytuna Business Services Ltd (solo).
The 150-word text is 149 words and the 400-word text 398 (whitespace-separated words between the rules); the form's counter may differ, so trim a sentence if it objects.
Rules for editing: the "ran live" runs are the maintainers' own with no committed log (`docs/HONESTY.md`), so say "our record", not "verified". Quote the 27 Oct 200-document extraction runs with repairs, re-read and Verifier on (Glimmer 85 % clean / 80 % messy, Spark Open 91 % / 93 %), not a mix with the earlier 88 % Glimmer run (no repairs, re-read or Verifier) or the 60-document one. The Autopilot figures are for Glimmer 30B on synthetic documents and are quoted with their caveat; do not shorten them to "0 false posts".
Muse Spark Open's figures are in the 400-word text with the same caveat (synthetic documents, 200 clean and 200 messy).

## Tagline

**Accounting, intelligently done: Meta models read the paperwork, you approve, code does the VAT, and the books stay in your OneDrive.**

(Shorter: *AI proposes, you approve, code calculates.*)

## 150-word version

---
Accnomos is bookkeeping and MTD VAT for UK small businesses. Your books are files in your own OneDrive; we keep no database.

Meta models read the paperwork: Muse Glimmer 30B on our own hardware, or Muse Spark 1.3 with your key, with Muse Spark Open on Baseten as an independent second reader. Code checks the arithmetic, you approve, and code calculates the nine VAT boxes. Around that sit contacts, invoicing with part payments and credit notes, bank rules, reconciliation, reports, an audit trail, chat and voice actions, and an Android app.

Autopilot is off by default. Measured on Glimmer over 467 synthetic documents, verifier on: no false posts on 154 clean ones, but 17 overall, all re-dated copies of posted receipts.

Honestly: only sign-in, receipt-to-VAT-boxes and the model evals ran for real; the rest is tested on fakes. HMRC is sandbox only and not yet run end to end.
---

## 400-word version

---
**The problem.** A VAT-registered UK small business must keep digital records and file through Making Tax Digital software, and someone has to turn a shoebox of receipts into those records. Accnomos asks whether AI can do the typing while the owner keeps control.

**The approach.** *AI proposes*: a Meta model reads a receipt, invoice or credit note into strict JSON. *You approve*: nothing posts until you tap Approve. *Code calculates*: arithmetic checks, VAT treatment, ledger events, the nine VAT boxes, invoice totals, payments, credit notes, reports, mileage and pay-run estimates are deterministic code with tests. Models write words only; a figure in an answer that is not in your books is replaced by the facts.

**Your books, your OneDrive.** The runtime is stateless. The ledger is append-only event files in your OneDrive, and `Books.xlsx` is regenerated for your accountant. Disconnect and every file is still yours.

**What is built.** Receipt scan, review and an independent second reading; contacts with statements and ageing; invoicing with PDF, Outlook send, part payments and credit notes; bank import with rules and reconciliation; reports; an audit trail of every action; the VAT return by period with an HMRC sandbox flow; jobs, mileage and pay-run estimates; Outlook intake; Ask, plus chat and voice actions that show a card and wait for Approve; a web app and an Android app.

**The Meta models.** Muse Glimmer 30B (open weights, our DGX Spark) reads locally. Muse Spark 1.3 does the same with your key. Muse Spark Open on Baseten is the key-mode verifier. Muse Voice Transcribe takes spoken questions. SAM 3.1 crops photos, off by default. Muse Image made the brand art.

**Measured, and its limits.** On 200 synthetic documents, clean and messy, every field was right on 85 % and 80 % (Glimmer) and 91 % and 93 % (Spark Open). Autopilot (posting without a tap, only for suppliers you have a rule for) was tested on 467 documents with the verifier on: no false posts on 154 clean ones, but 17 overall (3.6 %), all re-dated copies of receipts already posted.

**Honest status.** Sign-in and receipt-to-VAT-boxes ran live on a personal account (our record). The rest is tested on fakes. HMRC is sandbox only and not yet run end to end; Spark 1.3, Voice and SAM have never been called live; no real-phone Android sign-in is recorded. Demo data is synthetic. `docs/HONESTY.md` lists every gap.
---
