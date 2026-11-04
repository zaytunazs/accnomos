# Submission pack (Cerebral Valley form, 4 Nov 2026)

Paste-ready answers for the form at `https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit` (field
names as the form shows them on 4 Nov 2026, 21:10 UK). Every claim is one `docs/HONESTY.md` allows. Long fields are
capped at 3,000 characters by the form; the texts below are under that.

| Field | Answer |
|---|---|
| Team Name | Accnomos |
| Team Members | zohaibsharif (solo) |
| Which track | Indie Developer Track |
| Which problem statement | Build for Your World |
| X post link (Most Viral) | the post made from `docs/submission/X_POST.md` |
| Public GitHub Repository | https://github.com/zaytunazs/accnomos (public, MIT) |
| 3-Minute Demo Video | https://youtu.be/gTZCC_gadEE (2:56, unlisted) |
| Partner technologies feedback (150 chars) | see below |

## Project Description (≤ 3,000 characters; this is about 2,730)

Accnomos is bookkeeping, VAT and household money in plain English, for UK small businesses, sole traders, landlords and households, built on Meta's Muse models. Your books are files in your own OneDrive; we keep no database.

The problem. A VAT-registered UK small business must keep digital records and file through Making Tax Digital software; someone has to turn a shoebox of receipts into those records. Accnomos asks whether AI can do the typing while the owner keeps control.

The approach. AI proposes: snap a receipt on the Android app, upload it on the web, or let Outlook intake fetch it from email; a Meta model reads it into strict JSON. You approve: nothing posts until you tap Approve. Code calculates: arithmetic checks, ledger events, the nine VAT boxes, invoices, payments, credit notes and reports are deterministic, tested code. In Ask, every figure is checked against the books; an invented number is replaced by the facts.

Your books, your OneDrive. The runtime is stateless: the ledger is append-only event files in your OneDrive; Books.xlsx is regenerated for your accountant. Disconnect and every file is still yours.

What is built. Receipt capture, review and a second reading; contacts and ageing; invoicing with part payments and credit notes; bank statements, rules, reconciliation and an Open Banking feed; reports; audit trail; the VAT return with an HMRC sandbox flow; MTD Income Tax figures for sole traders and landlords; jobs, mileage, payroll; household budgets and goals; Ask, a hands-free assistant and chat actions that wait for Approve; web and Android apps.

The Meta models. Muse Spark 1.3 on the Meta Model API answers first on the live server; Muse Glimmer 30B, Meta's open-weights model on our own server, is the fallback and local mode. Muse Voice Transcribe hears spoken questions, SAM 3.1 crops receipt photos, Muse Image made the brand art, Muse Code helped write it.

Measured, and its limits. On 200 synthetic documents, clean and messy, every field was right on 95 % and 96 % (Muse Spark 1.3), 85 % and 80 % (Glimmer); real photos score lower. Ask got 32 of 32 figures exact. Autopilot, off by default, made 17 false posts in 467 documents, all re-dated copies of posted receipts.

Honest status. The Meta paths ran live on the public server on 4 Nov 2026, records committed. HMRC is sandbox only: the demo files to HMRC's sandbox with a test user. The bank feed has met TrueLayer's sandbox only; the Android app one real phone. Other features are mostly tested on fakes; demo data is fictional. Only the owner's server predates the event; docs/HONESTY.md lists every gap.

Try it with no sign-in: https://accnomos.com → Try the demo (guide: /judges). Android APK: GitHub Releases.

## Describe your use of Meta products to build the submitted project (≤ 3,000; this is about 2,200)

At run time, five Meta models, each in a job code checks:

Muse Spark 1.3 (Meta Model API, muse-spark-1.3-contributor on the live server; the user's own key in key mode) reads receipts, invoices, credit notes and emailed bills into strict JSON, suggests categories, answers Ask questions, turns spoken or typed instructions into action cards, writes the Home and month-end summaries, codes bank lines, triages the inbox and drafts reminders. Code repairs VAT-inclusive totals from the receipt's own arithmetic, re-reads at higher resolution when unsure, checks every figure, and never lets the model post anything.

Muse Glimmer 30B (open weights) runs on our own server as the fallback and as the user-selectable "local model only" route, so a user can keep every document on their own hardware. Settings › AI offers Meta API first, local first (Meta when the local answer is unclear), or local only.

Muse Voice Transcribe turns the spoken question into text for the hands-free assistant on web and Android (a local fallback model if it fails); the assistant reads back with the device's own voice (Meta has no text-to-speech model, and we say so).

SAM 3.1 (Meta Model API) crops receipt photos before reading (SAM_CROP=1 on the live server; measured on 20 synthetic scenes: a box every time, IoU 0.90, no reading gain yet, said honestly).

Muse Spark Open (hosted open weights) was the independent second reader (Verifier) in the evals; it is off on the live server since 2 Nov, where the second reading is Muse Spark checking itself.

At build time: Muse Image made the brand art and the video cards (credited on the judges' slide); Muse Code wrote the web and Android screens alongside other AI tools; every merge was reviewed by a second agent (docs/reviews, 101 reviews).

Evidence in the repo: docs/submission/META_MODELS.md (one row per model and job, how each is checked, what is measured), docs/submission/OPEN_WEIGHTS.md (where the open weights run, with live call records), evals/runs/live_checks_2026-11-04 (every Meta path called on the public server with the provider recorded per call), evals/runs/spark13_200 and spark13_messy_200 (the 95 % / 96 % figures), evals/runs/sam_crop_live.

## Why are Meta's models important to your solution? (≤ 3,000; this is about 1,330)

Three reasons, in the order they decided the design.

Open weights make "your data never leaves your machine" possible. Bookkeeping is the most private data a small business has. With Muse Glimmer 30B we run the reader on our own hardware, and a user can choose local-only in Settings so no document, bank line or question goes to any API. No closed model gives us that option; the same open weights also let us measure the model on 200 documents ourselves rather than trust a claim.

One family, two deployments. Muse Spark 1.3 on the Meta Model API and Muse Glimmer 30B locally share prompts, JSON schemas and code checks, so the user chooses a privacy and speed trade-off, not a different product. The provider chain fails over between them with the choice recorded per call.

Multimodal in one API. Reading a receipt photo, cropping it (SAM 3.1), hearing a spoken question (Muse Voice Transcribe) and writing a plain-English answer are four calls to one vendor with one key, which is what made a solo build of this scope possible in ten days.

What we measured: every field right on 95 % clean / 96 % messy synthetic documents for Muse Spark 1.3 with repairs and a second reading, 85 % / 80 % for Glimmer; 32 of 32 Ask figures exact. The limits are written down too: synthetic documents only, sandbox HMRC, one real phone.

## Partner technologies feedback (≤ 150 characters; this is 150)

Modal served Glimmer 30B for the 27 Oct evals (fast cold starts); Baseten hosted Muse Spark Open as the Verifier. Both simple; both off at submission.

## Survey answers (the owner's; suggested)

- How likely to build with Meta Model API: Very likely. Opinion: Very favorable. Recommend API: 5. Recommend Muse Code: 4.
- Biggest obstacle: "A model capability we needed was missing" (no Meta text-to-speech) or "Rate limits or usage limits" — the owner's call.
- Compared with other models: Somewhat better / About the same — the owner's call.
- What matters most: Open weights or self-hosting. Hardest to switch: Our product is tuned to our current model's behaviour and prompts.
- Production blocker: How our data and our users' data would be stored or used (Contributor mode lets Meta use content) — or Nothing would stop us.
- Permission checkbox: tick.
