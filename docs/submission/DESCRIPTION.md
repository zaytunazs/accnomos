# Project description (Meta Global AI Developer Hackathon, Indie track)

Refreshed 28 Oct 2026. Every claim below comes from `README.md`, `docs/HONESTY.md`, `docs/PROVENANCE.md`,
`docs/submission/META_MODELS.md` and the reports named there. Owner: Zohaib Sharif, Zaytuna Business Services Ltd (solo).
**Word counts** (`wc -w` on the text between the rules, so `91 %` counts as two words): the 150-word text is **149**,
the 400-word text **388**. The form's counter may differ; trim a sentence if it objects.

Rules for editing:

- The "ran live" runs are the maintainers' own with no committed log (`docs/HONESTY.md`): say "our record", not "verified".
- Quote the 27 Oct 200-document extraction runs with repairs, re-read and Verifier on (Spark Open 91 % clean / 93 % messy,
  Glimmer 85 % / 80 %), not the earlier 60-document or no-Verifier runs. Always say "synthetic documents".
- Quote Autopilot with its caveat (17 false posts in 467, all re-dated copies); never shorten it to "0 false posts".
- Muse Spark 1.3, Muse Voice Transcribe and SAM 3.1 are unit-tested only: never say they were measured or run live.
- **Not on `main` on 28 Oct, so not in the text:** the month-end close agent, company / sole-trader / personal profiles,
  Glimmer on Modal in the models panel, and the no-sign-in `/judges` page. Add a sentence for each only after it is merged
  and run, and say how it was tested. iPhone is not built: "coming soon" at most.

## Tagline

**Accounting, intelligently done: Meta models read the paperwork, you approve, code does the VAT, and the books stay in your OneDrive.**

(Shorter: *AI proposes, you approve, code calculates.*)

## 150-word version

---
Accnomos is bookkeeping and MTD VAT for UK small businesses. Your books are files in your own OneDrive; we keep no database.

Snap a receipt on the Android app, or let one arrive by email, and a Meta model reads it: Muse Glimmer 30B with open weights, or Muse Spark with your key, with Muse Spark Open on Baseten as an independent second reader. Code checks the arithmetic, you approve, and code calculates the nine VAT boxes for an HMRC sandbox submission. Ask answers in plain English, and every figure is checked against your books.

Measured on 200 synthetic documents: every field right on 91 % clean and 93 % messy for Spark Open, 85 % and 80 % for Glimmer.

Honestly: only sign-in, receipt-to-VAT-boxes and the model evals ran for real; the rest is tested on fakes. HMRC is sandbox only and not yet run end to end.
---

## 400-word version

---
**The problem.** A VAT-registered UK small business must keep digital records and file through Making Tax Digital software, and someone has to turn a shoebox of receipts into those records. Accnomos asks whether AI can do the typing while the owner keeps control.

**The approach.** *AI proposes*: snap a receipt on the Android app, upload it on the web, or let Outlook intake pick it up from email, and a Meta model reads it into strict JSON. *You approve*: nothing posts until you tap Approve. *Code calculates*: arithmetic checks, ledger events, the nine VAT boxes, invoices, payments, credit notes and reports are deterministic code with tests. In Ask, every figure is checked against the books; an invented number is replaced by the facts.

**Your books, your OneDrive.** The runtime is stateless. The ledger is append-only event files in your OneDrive, and `Books.xlsx` is regenerated for your accountant. Disconnect and every file is still yours.

**What is built.** Receipt capture, review and an independent second reading; contacts and ageing; invoicing with part payments and credit notes; bank rules and reconciliation; reports; an audit trail; the VAT return with an HMRC sandbox flow; jobs, mileage and pay-run estimates; Ask, plus chat actions that wait for Approve; a web app and an Android app.

**The Meta models.** Muse Glimmer 30B, Meta's open-weights model, reads documents in local mode. Muse Spark 1.3 does the same with your key. Muse Spark Open on Baseten is the key-mode second reader. Muse Image made the brand art; Muse Code helped write the app.

**Measured, and its limits.** On 200 synthetic documents, clean and messy, every field was right on 91 % and 93 % (Spark Open) and 85 % and 80 % (Glimmer); real photos will score lower. Ask got 32 of 32 figures exact. Autopilot, off by default, was tested on 467 documents: no false posts on 154 clean ones, but 17 overall, all re-dated copies of receipts already posted.

**Honest status.** Sign-in and receipt-to-VAT-boxes ran live on a personal account (our record). The rest is tested on fakes. HMRC is sandbox only and not yet run end to end; Spark 1.3 and voice have never been called live; no real-phone Android sign-in is recorded. Demo data is synthetic. Only the owner's DGX Spark and Ollama predate the event (`docs/PROVENANCE.md`); `docs/HONESTY.md` lists every gap.
---
