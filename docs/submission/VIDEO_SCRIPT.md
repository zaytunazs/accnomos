# Demo video script: 3:00, phone first

Rewritten 28 Oct 2026 for the official judging: **Impact, Use of Meta AI tooling, Technical depth and execution, and Demo
quality, weighted equally.** The previous script (web first, 27 Oct) is in git history.
Narration is first person, plain UK English, about 150 words a minute. No claim in the voice-over or on screen goes beyond
what `docs/HONESTY.md` allows; every number is from `evals/runs/*/summary.json` or `docs/submission/META_MODELS.md`.

## Read this first: what is on `main` and what is not

Checked against `main` at `206848c` (28 Oct, 01:33 UTC). Other branches are adding features in parallel, so re-check on
the day you record.

| Shot | Status on `main` (28 Oct) | Rule |
|---|---|---|
| Android capture → web Review → Approve → ledger → VAT boxes | Built. The Android app (0.3.5+10) has **never run on a real device** and **no Play sign-in has been tried** (`docs/HONESTY.md`, Android) | Rehearse on the phone first. If sign-in fails, film *Photograph a receipt* in the phone's browser (the 390 px web app) and change the caption |
| HMRC sandbox submission | Built; **not yet run end to end** against the sandbox | Run it off camera first; if it fails, stop at the declaration card |
| Outlook intake | Built; **never run against a real mailbox** | Run it on the throwaway mailbox first; else cut |
| Ask with exact figures | Built and measured (40 prompts) | Film |
| Verifier sending a reading to *Needs a look* | Built and measured | Film a real disagreement; say "caught" only if the first reading was the wrong one |
| **Month-end close agent** | **Not on `main`** | Film only once merged and run; else use the fallback row |
| **Profiles: company, sole trader, personal, each its own OneDrive** | **Not on `main`** | As above |
| **Meta models panel (Glimmer on Modal first, Meta API second)** | **Not on `main`**; today's equivalent is *Connect → Choose your AI* | As above |
| **`/judges` (no sign-in)** | **Not on `main`**; today judges press *Load sample books* on their own account (never run against a real OneDrive) | As above |
| iPhone | **Not built** | Say "coming soon", nothing more |

**Do not film:** the mic (never run live), SAM 3.1 (off by default, never run live), the signed-out `/vat` mock-up (its
"Reviewer's note (Muse Spark)" is not backed by any running reviewer), keys, tokens, the HMRC test user's password, or a
real mailbox.

## Set-up

- **Account:** a throwaway personal Microsoft account, *Connect* done, `00 Inbox` empty, Autopilot **L1**, VAT
  **Quarterly, stagger 1**. A second throwaway mailbox that can send one receipt email to it (for the Outlook shot).
- **Receipt:** print `https://accnomos.com/sample-receipt.png` (fictional Novex Office Supplies Ltd, net £43.25 + VAT
  £8.65 = £51.90, stamped SAMPLE). On an otherwise empty account, Oct–Dec 2026: Box 4 **£8.65**, Box 5 **£8.65**,
  Box 7 **£43** (`docs/DEMO.md`). Other entries in the quarter change these: read the live figures.
- **Model:** warm it with one dummy scan. Never record on the test-mode build: its stub AI is not a model.
- **Screens:** web at 1280 × 720, 100 % zoom; phone screen-recorded natively (or the emulator), debug banner hidden.
- **Captions:** burned in, white on dark, bottom third. Any wait you cut gets a `sped up` caption.

## 3:00 script

| # | Time | Shot | Voice-over | On-screen caption |
|---|---|---|---|---|
| 1 | 0:00–0:07 | Black card, white text | "Before the hackathon I had only my DGX Spark with Ollama. Everything else was built after kickoff." | `Pre-existing: owner's DGX Spark + Ollama only. All code and Meta model set-up made after kickoff, 26 Oct 2026 (docs/PROVENANCE.md)` |
| 2 | 0:07–0:17 | Hand-held: a shoebox of receipts, then the phone | "UK small businesses must keep digital VAT records. Accnomos does the typing with Meta models, and you stay in charge." | `Accnomos · bookkeeping + MTD VAT for UK small businesses` |
| 3 | 0:17–0:32 | **Android app**: Review → *Photograph a receipt* → *Take a photo* of the printed receipt → crop preview → *Read with Meta AI* | "I snap the receipt on my Android phone. It goes into my own OneDrive and a Meta model reads it." | `Android app · photo saved to your OneDrive · read by a Meta model` (if filmed in the browser: `Phone browser, 390 px`) |
| 4 | 0:32–0:46 | **Web Review**: the same receipt's card; point at the reader line, the code checks and *Verifier agrees · all 6 fields match*; press Approve | "On the web it's waiting in Review. Code checked the sums; a second reading agrees on six fields. Nothing posts until I approve." | `AI proposes · code checks · you approve` (add `sped up` if the wait is cut) |
| 5 | 0:46–0:56 | **Web Review → Needs a look**: a card with both readings side by side, the disagreeing field highlighted | "When the two readings differ, it lands in *Needs a look* with both values, so a wrong figure can't slip through quietly." | `Second reading disagrees → Needs a look` |
| 6 | 0:56–1:08 | **Files** (`_System/Ledger/events`, one event file), then **VAT return**: Box 4, then Box 7 | "Approving writes an immutable ledger event. The nine VAT boxes are plain code: Box 4 is £8.65, Box 7 £43. No model touches them." | `Ledger event → 9 VAT boxes, calculated by code` |
| 7 | 1:08–1:18 | **VAT return → Connect to HMRC (sandbox)** → obligations → declaration → *Submit to HMRC (sandbox)* → receipt. Stop at the declaration if the off-camera run failed | "Then I file through HMRC's Making Tax Digital sandbox, after the legal declaration." | `HMRC SANDBOX, not production` (if stopped: `+ submission not yet run end to end`) |
| 8 | 1:18–1:28 | **Settings → Outlook intake → Check my inbox now**; the emailed PDF appears in `00 Inbox` | "Receipts that arrive by email are picked up from Outlook, read-only. It never sends, moves or deletes mail." | `Outlook intake · Mail.Read only` |
| 9 | 1:28–1:42 | **Ask**: "How much VAT do I owe this quarter?"; hold on the answer, its figures and the cited file | "Ask in plain English. Every figure in the answer is checked against figures code worked out from my books; a number the model invents is replaced." | `Every figure checked against the books · measured: 32 of 32 exact` |
| 10 | 1:42–1:54 | **Month-end close agent** run on the sample books: its checklist and what it proposes | "At month end an agent works through the close and proposes what's left. I approve each step." | `Month-end close · proposes, you approve` |
| 11 | 1:54–2:04 | **Profile switcher**: company → sole trader → personal; each opens a different OneDrive | "One app for my company, my sole-trader work and my own money: each profile is its own OneDrive." | `Company · sole trader · personal — each its own OneDrive` |
| 12 | 2:04–2:16 | **Meta models panel**: Glimmer on Modal first, Meta API second; press the test button | "Muse Glimmer, Meta's open-weights model, runs first; the Meta Model API with my own key is second. In key mode Muse Spark Open on Baseten is the second reader." | `Muse Glimmer 30B (open weights) → Meta Model API · Muse Spark Open verifier` |
| 13 | 2:16–2:30 | Full-screen card: the eval table below | "We measured it on 200 synthetic documents, clean and messy: every field right on 91 and 93 per cent for Muse Spark Open, 85 and 80 for Glimmer. Real photos will score lower." | the eval card (below) |
| 14 | 2:30–2:38 | **Files** → *Open in OneDrive*: `Books.xlsx` and the folders | "Accnomos keeps no database. The books are files in your OneDrive. Disconnect, and they're still yours." | `No Accnomos database · your books stay in your OneDrive` |
| 15 | 2:38–2:44 | Phone in hand, then a plain card | "Android today. iPhone is coming." | `Android now · iPhone coming soon` |
| 16 | 2:44–2:54 | **`/judges`** in a private window: the sample books, no sign-in | "Judges can try it with no sign-in: six months of a fictional joinery's books." | `accnomos.com/judges · no sign-in · fictional sample data` |
| 17 | 2:54–3:00 | End card over Home | "AI proposes, you approve, code calculates." | `github.com/zaytunazs/accnomos · Synthetic data · HMRC sandbox · docs/HONESTY.md lists every gap` |

Total: 3:00 (7 + 10 + 15 + 14 + 10 + 12 + 10 + 10 + 14 + 12 + 10 + 12 + 14 + 8 + 6 + 10 + 6 s). About 320 words of narration, so there is room to breathe.

### Fallbacks for shots that are not on `main` when you record

Keep the timings; swap the row.

| # | If not merged and run | Voice-over | Caption |
|---|---|---|---|
| 10 | **Invoices**: open an invoice, *Record payment* for part of it (fakes-tested only: run it first, else cut) | "Invoices, part payments and credit notes are code too." | `Invoices · part payments · credit notes, by code` |
| 11 | **Home** with Autopilot's level in Settings | "Autopilot is off by default. Measured on Glimmer: no false posts on 154 clean documents, 17 in 467 overall, all re-dated copies." | `Autopilot L2 eval: 0/154 clean · 17/467 overall · synthetic` |
| 12 | **Connect → Choose your AI** → *Test connection* (cut the Modal words) | "Muse Glimmer, Meta's open-weights model, on our own hardware; or the Meta Model API with your key. In key mode the second reader is Muse Spark Open on Baseten." | `Muse Glimmer 30B · or Muse Spark with your key` |
| 16 | **Home → Try it with sample books → Load sample books** on a throwaway account, sped up (never run against a real OneDrive: run it first) | "Judges can load six months of a fictional joinery's books into their own OneDrive with one button." | `Load sample books · fictional data · sped up` |

If the whole cut runs long, drop shot 8 (Outlook), then 10. Never drop shots 1, 7's sandbox caption, 13 or 17.

### The eval card (shot 13)

Burn in exactly this, from `docs/submission/META_MODELS.md` and `evals/runs/*/summary.json`:

```
200 synthetic gold documents · all fields right (supplier, VAT no., date, net, VAT, total, lines, side, status)
                         clean    messy
Muse Spark Open          91 %     93 %      evals/runs/spark_open_200, spark_open_messy_200
Muse Glimmer 30B         85 %     80 %      evals/runs/glimmer_200_v2, glimmer_messy_200_v2
Ask: figures exact 32/32 · no invented figure shown (evals/runs/ask_40)
Synthetic documents: real phone photos will score lower
```

Optional second line if there is room: `Second reading: Glimmer caught 8 wrong readings in 400, with 44 false alarms (all to Needs a look)`.
Do not say Muse Spark 1.3 was measured: it has no eval (unit-tested only).

## How the shots map to the four criteria

| Criterion | Shots | What the judge sees |
|---|---|---|
| **Impact** | 2, 3, 11, 14, 15, 16 | A real UK obligation (MTD VAT), a phone-first habit, books that stay the owner's, a no-sign-in way to try it |
| **Use of Meta AI tooling** | 3, 4, 5, 9, 12, 13 | Glimmer (open weights) and the Meta Model API reading documents, Muse Spark Open as an independent second reader, measured accuracy; Muse Code helped write the app (`docs/PROVENANCE.md`) |
| **Technical depth and execution** | 4, 5, 6, 7, 9, 10 | Code checks, two-reading comparison, immutable ledger, VAT by code, HMRC MTD sandbox, grounded Ask |
| **Demo quality** | all | One receipt followed end to end on real screens, honest captions, nothing faked or staged |

## Shot list

| # | Capture | Device | Notes |
|---|---|---|---|
| 1 | Provenance card | 1280 × 720 still | Text from `docs/PROVENANCE.md`; hold 7 s |
| 2 | Shoebox, then phone | Camera | No real receipts with real names in frame |
| 3 | Android capture → crop → *Read with Meta AI* | Phone screen recording | Rehearse sign-in on the same phone first |
| 4 | Review card + Approve | Web 1280, card at 125 % | Reader line and *Verifier agrees* legible at 1080p |
| 5 | *Needs a look* card with both readings | Web 1280 | Use a real disagreement from a live scan |
| 6 | `_System/Ledger/events`, then VAT return Box 4 / Box 7 | Web 1280 | Figures must match the caption |
| 7 | HMRC sandbox flow | Web 1280 | Never show the test user's password or the client secret |
| 8 | Outlook intake → `00 Inbox` | Web 1280 | Throwaway mailbox only; crop out addresses |
| 9 | Ask answer with figures and cited file | Web 1280 | |
| 10 | Month-end close agent (or fallback) | Web 1280 | Only once merged and run |
| 11 | Profile switcher (or fallback) | Web 1280 or phone | Only once merged; each profile a different throwaway OneDrive |
| 12 | Meta models panel (or *Choose your AI*) | Web 1280 | Crop out any key field |
| 13 | Eval card | 1280 × 720 still | Text above, exactly |
| 14 | Files → OneDrive with `Books.xlsx` | Web 1280 | |
| 15 | Phone in hand + "iPhone coming soon" card | Camera / still | |
| 16 | `/judges` in a private window (or *Load sample books*) | Web 1280 | Only once merged and run |
| 17 | End card over Home | 1280 × 720 still | Hold 6 s |

The dry-run stills in `docs/submission/shots/` (test mode, stub AI) are for storyboarding and the thumbnail only, not proof of a live run.
