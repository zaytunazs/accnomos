# Judges' video: 3-minute submission video, timed shot list

Total **180 s**. Voice-over runs at about 2.5 words per second; every line below
fits its shot. All data shown is the demo sandbox's sample company, labelled
SAMPLE — FICTIONAL COMPANY. HMRC contact is sandbox only. Nothing here promises
live filing, live model accuracy on real photos, or anything `docs/HONESTY.md`
says is untested or unavailable.

Conventions: each shot names the app route or screen, the on-screen action, a
caption of at most 8 words, and the spoken voice-over with its word count.

## Shot 1 — what existed before the event (0:00–0:10, 10 s)

Screen: dark card, white text (still, 1920 × 1080), over the Muse Image title
art if it has been generated (`docs/video/cards/`).

On-screen action: card holds for the full 10 s:

> Before the hackathon: only a local GPU server I already owned.
> Everything for Accnomos, including the Meta models on it, was set up after kickoff.
> Repo created 26 Oct 2026 22:30 UTC (kickoff 16:00 UK).
> Meta models: Muse Spark, Muse Spark Open, Muse Glimmer, Muse Voice Transcribe, Muse Image, Segment Anything.

Caption: `Only a local server predates the event` (7 words).

Voice-over (23 words, ≤ 25): "Before the hackathon I had only a local
server. Everything you see, and the Meta models it runs, was set up after
kickoff."

Owner's rule for this card and everything judge-facing in the video: no
hardware name and no third-party tool name. The model list was checked on
29 Oct 2026 against `docs/submission/META_MODELS.md` on `main` (`715c564`):
all six are in the build (Muse Voice Transcribe merged in `b589cd7`; Muse Image
made the brand and title art; Segment Anything is wired, off by default).
Check it again on the day you record and drop any model that is not on `main`.

## Impact — who it helps, MTD deadlines (0:10–0:48, 38 s)

### Shot 2 — one dashboard for the compulsory part (0:10–0:28, 18 s)

Screen: Home dashboard (`/`), demo sandbox with the SAMPLE — FICTIONAL COMPANY
banner over six months of the fictional joinery's books.

On-screen action: slow scroll down the dashboard: cash in and out, amounts owed,
then rest on the Coming up deadlines card (VAT return, quarterly Income Tax
update, Self Assessment 31 January).

Caption: `Digital records and MTD deadlines, one dashboard` (7 words).

Voice-over (44 words, ≤ 45): "Accnomos helps UK small businesses, sole
traders and landlords with the compulsory part: digital records and Making Tax
Digital filings. The dashboard shows cash, what is owed, and what is due: the
VAT return, quarterly Income Tax updates, and Self Assessment on 31 January."

### Shot 3 — paperwork starts on the phone (0:28–0:48, 20 s)

Screen: Android app capture, then web Review (`/review`).

On-screen action: photograph a receipt in the Android app; cut to the same
document waiting in web Review; point at the sender line of a supplier email
picked up by Outlook intake.

Caption: `Phone photos and email become your books` (7 words).

Voice-over (36 words, ≤ 50): "Paperwork starts on the phone. Photograph a
receipt in the Android app and it lands in your own OneDrive. Forward a
supplier email and Outlook intake picks it up, read only. Nothing posts without
your tap."

## Use of Meta AI tooling — which models, measured numbers (0:48–1:28, 40 s)

### Shot 4 — a Meta model reads, code checks (0:48–1:08, 20 s)

Screen: web Review (`/review`), one proposal card.

On-screen action: point at the reader line (Muse Glimmer 30B), the code checks
and repaired figures, then the Verifier line: second reading agrees on all six
fields. Do not film the mic.

Caption: `Meta models read, code checks, you approve` (7 words).

Voice-over (36 words, ≤ 50): "A Meta model reads each document: Muse Glimmer
30B with open weights, or Muse Spark with your key. Code checks the arithmetic
and repairs VAT-inclusive totals. A second independent reading checks six
fields before you approve."

### Shot 5 — measured numbers (1:08–1:28, 20 s)

Screen: full-screen eval card (still, 1920 × 1080). Burn in exactly:

```
Measured on synthetic documents, Meta models only
Receipts and invoices, every field right (200 clean + 200 messy)
  Muse Spark Open     91 % clean   93 % messy
  Muse Glimmer 30B    85 % clean   80 % messy
CIS statements and invoices, all fields exact   92.5 % of 120
Property statements and bills, all fields exact 89.8 % of 108
Bank lines coded to the right account           91.6 % of 459
Ask: figures exact in 32 of 32 questions
Synthetic documents: real photos will score lower
```

Caption: `Measured on synthetic documents, Meta models only` (7 words).

Voice-over (45 words, ≤ 50): "Measured on synthetic documents: receipts
fully right 91 and 93 per cent for Muse Spark Open, 85 and 80 for Muse
Glimmer. Glimmer also reads CIS and property papers and codes bank lines,
about nine in ten right. Real photos will score lower."

Sources, `evals/runs/*/summary.json` on `main` (`715c564`, read 29 Oct 2026):
`spark_open_200` and `spark_open_messy_200` (`all_fields_correct` 0.91 / 0.93, n 200 each);
`glimmer_200_v2` and `glimmer_messy_200_v2` (0.85 / 0.80, n 200 each); `cis_read` (`all_exact_pct` 92.5,
`docs` 120); `property_docs` (`all_exact_pct` 89.8, `docs` 108); Ask from `evals/runs/ask_40/report.md` (Glimmer
column, 32/32; there is no `summary.json` for it). The CIS, property and bank rows are Muse Glimmer.
**Bank lines 91.6 % of 459 is the owner's figure from the Glimmer `harness/bank_ai.py` run: its
`evals/runs/bank_ai/summary.json` is not committed on `main` yet. Commit it before recording, or drop the row.**
The card names no hosting provider, serving tool or non-Meta model (owner's rule).

## Technical depth — propose, approve, code computes (1:28–2:08, 40 s)

### Shot 6 — approve posts an event; books live in OneDrive (1:28–1:48, 20 s)

Screen: web Review (`/review`) → Files (`/files`).

On-screen action: press Approve on the card; open
`_System/Ledger/events` and show the new event file; open the books folder and
show `Books.xlsx` beside it.

Caption: `Immutable ledger in your own OneDrive` (6 words).

Voice-over (30 words, ≤ 50): "Approving writes an immutable ledger event,
never an edit. Your books are files in your own OneDrive: ledger events and
Books.xlsx. There is no Accnomos database, so disconnecting loses nothing."

### Shot 7 — VAT by code, sandbox, test gates (1:48–2:08, 20 s)

Screen: VAT return (`/vat`), then the HMRC sandbox declaration card.

On-screen action: point at the nine boxes worked out by code; walk through
Connect to HMRC (sandbox), obligations and the legal declaration; hold on the
sandbox receipt in `06 VAT returns/`.

Caption: `VAT by code, HMRC sandbox only` (6 words).

Voice-over (34 words, ≤ 50): "The nine VAT boxes are worked out by code in
whole pence, then walked through HMRC's sandbox flow after the legal
declaration. Tested with 1260 runtime checks, 208 browser tests and 248 app
tests."

## Demo quality — one receipt end to end (2:08–3:00, 52 s)

### Shot 8 — email receipt in, proposal ready (2:08–2:26, 18 s)

Screen: Settings (`/settings`) Outlook intake → web Review (`/review`).

On-screen action: press Check my inbox now; the emailed supplier receipt lands
in `00 Inbox`; its proposal card opens with supplier, date and totals filled
in.

Caption: `Email receipt in, proposal ready` (5 words).

Voice-over (33 words, ≤ 45): "Watch one receipt travel. A supplier email
arrives in Outlook and intake copies it to the inbox. The proposal shows
supplier, date and totals, with a second reading agreeing on all six fields."

### Shot 9 — approve, then the AI summary (2:26–2:38, 12 s)

Screen: web Review (`/review`) → Home dashboard (`/`).

On-screen action: press Approve; cut to Home where the AI summary now reflects
the new entry; point at one checked figure and its source.

Caption: `Approve once, summary explains` (4 words).

Voice-over (23 words, ≤ 30): "I approve and it posts to the ledger. Home's AI
summary words the position in plain sentences, every figure checked against the
books."

### Shot 10 — VAT return in the HMRC sandbox (2:38–2:52, 14 s)

Screen: VAT return (`/vat`), sandbox flow.

On-screen action: the return shows the boxes the receipt changed; connect to
HMRC's sandbox, tick the declaration, submit; hold on the receipt saved to
`06 VAT returns/`.

Caption: `VAT return submitted to sandbox` (5 words).

Voice-over (25 words, ≤ 35): "The VAT return shows the boxes the receipt
changed. I connect to HMRC's sandbox, confirm the declaration, and submit. The
receipt lands in my OneDrive."

### Shot 11 — voice, then end card (2:52–3:00, 8 s)

Screen: Ask (`/ask`), then end card over Home.

On-screen action: hold the mic button and say the line; the timesheet card
appears; cut to the end card: `github.com/zaytunazs/accnomos · Sample data ·
HMRC sandbox · docs/HONESTY.md lists every gap · Title art: Muse Image (Meta).`
(the credit sits on its own line under the rest).

Caption: `Voice becomes an approval card` (5 words).

Voice-over (20 words, ≤ 20): "By voice: Andy did 2 hours overtime at double
time on the Hendon job. It becomes a card I approve."

## Criteria map

| Criterion | Shots |
|---|---|
| Impact | 2, 3 |
| Use of Meta AI tooling | 4, 5 |
| Technical depth and execution | 6, 7 |
| Demo quality | 8, 9, 10, 11 |

Fallbacks: if the sandbox run fails off camera, stop shot 10 at the declaration
card and add `submission not yet run end to end`. If sign-in fails on the phone,
film shot 3 in the phone browser at 390 px and change the caption to
`Phone browser, 390 px`. Never film the mic beyond the scripted line, keys,
tokens, passwords, or a real mailbox.
