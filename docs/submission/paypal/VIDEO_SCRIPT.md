# PayPal AI Hackathon: demo video script (v6, 12 Nov 2026)

Length **2:38.9** (hard limit 2:50; the rules allow under 3:00). v6 follows the owner's review of draft 5 and the
research in [`VIDEO_RESEARCH.md`](VIDEO_RESEARCH.md):

1. **Hook** (0:00.0–0:16.4): the app from the first frame, the presenter as a small labelled picture-in-picture for the
   first two lines only, and the problem in one line.
2. **A week in the books** (0:16.4–1:57.2): one continuous story in which every beat does something. PayPal is its
   spine (pay link → payment → Sync → tie-out → payout → dispute → search), with the receipt, the bank feed, VAT to
   HMRC's sandbox, reports and the files in the owner's drive around it.
3. **What makes it different** (1:57.2–2:31.3): three slides whose points appear one by one: *What makes Accnomos
   different*, *Everything in one app*, *Built and verified*.
4. **Outro** (2:31.3–2:38.9): voice only over the end card.

Narration is 374 words in 19 lines (`narration/lines.json`; "text" is captioned, "say" is spoken). The voice-over is
`bf_emma` (British, female) via `narration/render.sh`. After the first two lines there is no presenter picture: the
timeline's `"pip_until": 15.0` turns the picture-in-picture off for every later segment (see
`tools/video/paypal/assemble_paypal.sh`).

**Layout.** Split scenes: the web capture at 1440 × 810 on the left, the Android app in a plain device frame
(350 × 778) on the right, one caption under both (bottom left, white on the app's dark brown). The small tag ("PayPal
sandbox", "Typing sped up"…) sits inside the web capture's top-right corner, clear of the phone. The presenter
picture-in-picture is 320 × 180 at the bottom right with the label "AI-generated presenter" under it. Cards and slides
are in [`cards/`](cards/); click paths and the blur list are in [`SHOT_LIST.md`](SHOT_LIST.md); upload settings and
chapters in [`UPLOAD.md`](UPLOAD.md).

**Pitch:** Accnomos keeps a UK small business's books in its own OneDrive or Google Drive and files VAT to HMRC; PayPal
is where it gets paid and pays its bills.

**Rules this script follows**

- Under 3 minutes and public on YouTube. It shows the project working on the web (desktop browser) and, beside it,
  the Android app (split scenes).
- PayPal is central: seven of the thirteen story beats are a PayPal API call or its result in the books, and each
  caption names the API.
- AG Grid (sponsor prize) is on screen for 8.2 s (0:54.0–1:02.2) with the caption "AG Grid Community".
- The presenter is never the main picture: a small picture-in-picture labelled "AI-generated presenter", on screen only
  for the first two lines, and it never says it is the founder (the label and YouTube's altered-content flag disclose it).
- No third-party logos or product names. PayPal is named as the sponsor, in text only. AG Grid is named in a caption,
  as a sponsor tool. No slide says what other products lack: the slide is "What makes Accnomos different" and lists
  only what Accnomos does (`VIDEO_RESEARCH.md`).
- Fictional data and sandbox only, said on screen.
- No model names, no Settings › AI, no model bylines on screen (blur them).
- Every claim is one `docs/HONESTY.md` allows. The payout scene ends "Waiting for the supplier to claim it" and the
  voice says it posts only when PayPal confirms. The Disputes calls have not met PayPal's sandbox, so the last slide
  marks Disputes "Sample in the demo" and the voice says "four of them run against PayPal's real sandbox". Income
  Tax appears only as "figures" on the features slide (nothing is sent to HMRC for it).

## Scenes

The timeline the assembler reads is `tools/video/paypal/timeline_paypal_v6.json` (made by `make_timeline_v6.py` from
the capture marks). Phone clips are `android/<id>.mp4` (1080 × 2400) and drop in by name.

| # | Time | Screen / action | Narration | On-screen caption |
|---|---|---|---|---|
| i0 | 0:00.0–0:10.4 | Home (web + phone), a Sync glimpse, Review (web + phone); presenter PiP bottom right | Accnomos is built for UK businesses and the self-employed who get paid, and pay suppliers, through PayPal. Here's how it keeps the books. | (none: PiP label "AI-generated presenter") |
| pr | 0:10.4–0:16.4 | Card `cards/problem.svg`; presenter PiP (its last appearance) | Small businesses paid through PayPal still match the fees and the VAT by hand. | (the card; PiP label) |
| w1 | 0:16.4–0:23.0 | Phone `a-capture` snaps a receipt; web Review › Add a receipt → *Looks like a receipt* → Confirm → proposed entry → Approve; phone `a-review` | Monday. A receipt. Snap it, the AI reads it, code checks the VAT, and you approve. | Receipts: the AI reads the photo · code checks totals and VAT · you approve |
| w2 | 0:23.0–0:30.6 | Bank › Connect the test bank (TrueLayer sandbox, mock login blurred) → new lines → Matches › an *Exact* suggestion → Confirm; phone `a-bank` | The bank feed lands, and the matches are suggested. Bank, PayPal and everything else, reconciled in one place. | Bank feed by Open Banking (TrueLayer's test bank) · matches suggested · you confirm |
| w3 | 0:30.6–0:37.2 | Ask *send a £450 invoice to Hartwell* → card → Approve → *sent* (demo); Add payment link → PayPal sandbox link | Time to get paid. Ask for an invoice in plain words, and add a PayPal pay link. | Invoice from plain words · PayPal Invoicing API: pay link |
| w4 | 0:37.2–0:49.2 | `/invoices` PayPal panel, demo copy with PayPal connected (real sandbox): Sync PayPal → the £85 sale with no invoice → VAT *Standard 20%* → Approve; phone `a-sync` | The customer pays. Press Sync PayPal, and in come the gross, PayPal's fee and the net. A sale with no invoice waits for your VAT choice, and nothing posts until you approve. | PayPal Transaction Search API · gross / fee / net · a sale with no invoice waits for your VAT choice |
| w5 | 0:49.2–0:54.0 | Tie-out at the top of the PayPal panel (real sandbox): *PayPal says £… (as of …)*, Difference | Then the tie-out checks your books against PayPal's own balance. | PayPal Balances API · PayPal's figure as of its last refresh |
| w6 | 0:54.0–1:02.2 | Power grid (demo sample history): tick 3 rows → Approve selected (3) → *3 of 3 approved*; Ledger explorer *PayPal fees over £5* | Busy week? The Power grid approves rows in bulk. Or filter in plain English: PayPal fees over £5. | AG Grid Community · Power grid: bulk approve, totals, plain-English filters |
| w7 | 1:02.2–1:13.2 | `/purchases` Pay bills with PayPal: Approve payment → Pay £114.00 → *PayPal is processing it* → (≈90 s later) *Waiting for the supplier to claim it… Nothing is posted until they do* → Home *Upcoming PayPal payments*; phone `a-billpay`, `a-home` | Bills go the other way. When one falls due, you approve it, and PayPal sends the payout. It posts only when PayPal confirms, and a retry never pays twice. | PayPal Payouts API · you approve each payout · posts only when PayPal confirms |
| w8 | 1:13.2–1:19.8 | PayPal disputes (SAMPLE) → Build evidence → Send to PayPal (demo) | A customer disputes a payment? The evidence is built from your books, and you choose when to send it. | PayPal Disputes API · SAMPLE dispute in the demo: nothing sent to PayPal |
| w9 | 1:19.8–1:33.4 | `/ask` (demo, PayPal NOT connected): the arrears question typed (phone `a-ask-arrears` typing beside it) → the answer enlarged, web only: £492.00 Wrenfield; the stationery question (phone `a-ask-search`) → £97.79 Quillstone | Can't remember something? Just ask. Did that client pay their arrears? Yes: £492, through PayPal. That stationery order, around £100? Exactly £97.79. | AI search: the AI reads the question · code searches your books and PayPal · exact figures |
| w10 | 1:33.4–1:39.0 | Talk to Accnomos: *Who owes me the most?* typed → the answer with its figures; phone `a-talk` hands-free, listening | Hands full? Type it, or just say it. | Talk to Accnomos: type or speak · every figure checked by code |
| w11 | 1:39.0–1:48.0 | `/vat` nine boxes → HMRC sandbox test user (password never on screen) → Submit → *Submitted to HMRC sandbox* receipt; phone `a-vat` | Quarter end. The nine VAT boxes are worked out by code and filed to HMRC's sandbox, with HMRC's own receipt. | VAT: nine boxes by code · filed to HMRC's sandbox · HMRC's receipt |
| w12 | 1:48.0–1:53.0 | `/reports` profit and loss → Export to OneDrive | Plus HMRC-ready reports, from VAT to profit and loss. | Reports: profit and loss, who owes you · export to your drive |
| w13 | 1:53.0–1:57.2 | `/files`: the books folder, `Books.xlsx`, the exported report | And all of it is saved as plain files in your own drive. | Your books: plain files in your own OneDrive or Google Drive |
| d1 | 1:57.2–2:14.7 | Slide `cards/different.html`: seven points, appearing one by one | So what makes Accnomos different? Your books live in your own OneDrive or Google Drive, not in our database. The AI proposes, code does the sums in pence, and you approve every posting. One search covers your books and PayPal. And the AI can run on your own machine. | (the slide) |
| d2 | 2:14.7–2:22.5 | Slide `cards/features.html`: five groups, appearing one by one | And it's all one app: PayPal, books and tax, an assistant, and the rest of the business, on the web and on Android. | (the slide) |
| d3 | 2:22.5–2:31.3 | Slide `cards/built.html`: the five PayPal APIs, then four proof boxes | Built on five PayPal APIs, four of them run against PayPal's real sandbox, and about four thousand automated tests. | (the slide) |
| o0 | 2:31.3–2:38.9 | End card (accnomos.com · Try the demo, no sign-in · github.com/zaytunazs/accnomos · PayPal sandbox; no real money moved); voice only | Everything you saw runs on PayPal's sandbox. Try it yourself at accnomos.com, no sign-in needed. | (the end card) |

Changes from v5: the "how it works" card, the "AI in action" slide and the Jobs look are out (Jobs showed nothing
happening; it stays on the features slide); the Talk scene now shows a question answered; the Ask answers are shown
enlarged on the web only, because the phone clips were recorded before Android 0.3.22 and show a link as raw text.

## What is real and what is sample

| Scene | Source |
|---|---|
| w4, w5 | PayPal's real **sandbox** (the demo copy connected to the server's sandbox app): the £85.00 and £372.00 payments of 11 Nov and PayPal's own balance |
| w3 (pay link) | A real sandbox PayPal invoice link, made by the demo's connection |
| w7 | The demo's bill-pay seed; **Pay** sends a real sandbox payout to an `example.com` payee, which stays unclaimed: the screen says so and nothing posts |
| w6, w9 | The demo's labelled sample PayPal history (w9 must be filmed with PayPal NOT connected, or the answers change) |
| w8 | The demo's SAMPLE dispute; nothing is sent to PayPal |
| w2 | TrueLayer's sandbox mock bank (public test login, blurred) |
| w11 | HMRC's sandbox with a throwaway test user the demo makes |
| w1, w10, w12, w13 | The fictional demo books (Bramblewood Joinery) |

## Music

An original bed made for this video: a soft pad with light plucks, synthesised by `tools/video/paypal/make_bed.py` (no
samples, no third-party recording), mixed 25 dB under the voice with a fade in and out. The final file already has it;
add nothing in YouTube Studio.
Don't use music from anywhere else. After uploading, check YouTube Studio shows no copyright claim.

## Timing check

| Part | Lines | Slot |
|---|---|---|
| Hook | i0, pr | 16.4 s |
| A week in the books | w1–w13 | 100.8 s |
| Slides | d1, d2, d3 | 34.1 s |
| Outro | o0 | 7.6 s |
| **Total** | | **2:38.9** |

There are about 11 s of headroom under 2:50. If the cut must be shorter, trim in this order: `w13` files, `w12`
reports, the ledger-explorer half of `w6` (keep at least 8 s of AG Grid in total).
