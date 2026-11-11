# PayPal AI Hackathon: demo video script (v5, 12 Nov 2026)

Length **2:46** (hard limit 2:50; the rules allow under 3:00). v5 follows the owner's review of draft 2: the app is the
main picture all the way through, the presenter is a small labelled picture-in-picture, the phone app sits beside the
web where it has the same screen, and a 52 s "Everything else, in action" section shows every other feature doing
something.

1. **Intro** (10.4 s): app footage with the presenter picture-in-picture.
2. **Problem and how it works** (10.4 s): two cards.
3. **PayPal hero** (1:18): Sync PayPal with the VAT choice, the Power grid (AG Grid), AI search, the tie-out, paying a
   bill by payout, dispute evidence.
4. **AI in action** slide (5 s).
5. **Everything else, in action** (52 s): receipts, bank feed, invoices, VAT to HMRC's sandbox, reports, talk, jobs,
   your own drive.
6. **Features** slide (3 s, silent) and the **outro** (7.4 s, end card with the presenter picture-in-picture).

Narration is 342 words in 19 lines (`narration/lines.json`; "text" is captioned, "say" is spoken). The voice-over is
`bf_emma` (British, female) via `narration/render.sh`; a lip-synced presenter clip can stand in for any line
(`presenter/<id>.mp4`, see `tools/video/paypal/assemble_paypal.sh`).

**Layout.** Split scenes: the web capture at 1440 × 810 on the left, the Android app in a plain device frame
(350 × 778) on the right, one caption under both (bottom left, white on the app's dark brown). The presenter
picture-in-picture is 320 × 180 at the bottom right with the label "AI-generated presenter" under it; it shows only
while its clip plays. Cards and slides are in [`cards/`](cards/); click paths and the blur list are in
[`SHOT_LIST.md`](SHOT_LIST.md); upload settings and chapters in [`UPLOAD.md`](UPLOAD.md).

**Pitch:** Accnomos keeps a UK small business's books in its own OneDrive or Google Drive and files VAT to HMRC; PayPal
is where it gets paid and pays its bills.

**Rules this script follows**

- Under 3 minutes and public on YouTube. It shows the project working on the web (desktop browser) and, beside it,
  the Android app (split scenes).
- PayPal is central: every hero scene is a PayPal API call or its result in the books.
- The presenter is never the main picture: a small picture-in-picture labelled "AI-generated presenter", and it never says it is the founder or calls itself an AI presenter (the label and YouTube's altered-content flag disclose it).
- No third-party logos. PayPal is named as the sponsor, in text only. AG Grid is named in a caption, as a sponsor tool.
  Music comes from YouTube's Audio Library with "Attribution not required" (see Music below).
- Fictional data and sandbox only, said on screen.
- No model names, no Settings › AI, no model bylines on screen (blur them).
- Every claim is one `docs/HONESTY.md` allows. "How much is in PayPal?" is answered from the books' PayPal account
  (which Sync PayPal fills); the tie-out is the screen that reads PayPal's own balance.

## Scenes

The timeline the assembler reads is `tools/video/paypal/timeline_paypal_v5.json` (made by `make_timeline_v5.py` from
the capture marks). Phone clips are `android/<id>.mp4` (1080 × 2400) and drop in by name.

| # | Time | Screen / action | Narration | On-screen caption |
|---|---|---|---|---|
| i0 | 0:00–0:10.4 | Home (web + phone), a Sync glimpse, Review (web + phone); presenter PiP bottom right | Accnomos was built by a UK business owner who gets paid, and pays suppliers, through PayPal. Here's how it keeps the books. | (none: PiP label "AI-generated presenter") |
| pr | 0:10.4–0:15.2 | Card `cards/problem.svg` | Small businesses paid through PayPal still match the fees and the VAT by hand. | (the card) |
| hw | 0:15.2–0:20.8 | Card `cards/how-it-works.svg`, built left to right | PayPal's data comes in, the AI proposes, code calculates to the penny, and you approve. | (the card) |
| h1 | 0:20.8–0:38.8 | `/invoices` PayPal panel, demo copy with PayPal connected (real sandbox): Sync PayPal → the £85 sale with no invoice → VAT *Standard 20%* → Approve; phone `a-sync` | Press Sync PayPal, and Accnomos fetches every payment from PayPal itself: the gross, PayPal's fee and the net. A sale with no invoice in your books waits for you to choose its VAT, and nothing posts until you approve. | PayPal Transaction Search · gross / fee / net · a sale with no invoice waits for your VAT choice |
| ag | 0:38.8–0:48.3 | Power grid on (demo sample history): tick 3 rows → Approve selected (3) → *3 of 3 approved*; Ledger explorer *PayPal fees over £5* | Turn on the Power grid to tick several PayPal rows and approve them together. Or just type: PayPal fees over five pounds. | AG Grid Community · Power grid: bulk approve, totals, plain-English filters |
| h2 | 0:48.3–1:02.8 | `/ask` (demo, PayPal NOT connected): the arrears question → £492.00 Wrenfield; the stationery question → £97.79 Quillstone; phone `a-ask-arrears`, `a-ask-search` | Or just ask, in your own words. Did that client pay the arrears? Accnomos checks your books and PayPal itself. A stationery order last month, around £100? Exactly £97.79. | AI search: the AI reads the question · code searches your books and PayPal · exact figures |
| h3 | 1:02.8–1:10.8 | Tie-out at the top of the PayPal panel (real sandbox): *PayPal says £… (as of …)*, Difference | The tie-out checks your books against PayPal's own balance, as of PayPal's last refresh. | PayPal Balances API · PayPal's figure as of its last refresh |
| h4 | 1:10.8–1:30.8 | `/purchases` Pay bills with PayPal (demo seed, PayPal connected): Approve payment → Pay £114.00 → *PayPal is processing it* → (≈90 s later) *Waiting for the supplier to claim it… Nothing is posted until they do* → Home *Upcoming PayPal payments*; phone `a-billpay`, `a-home` | Paying a supplier works the other way. When a bill falls due, Accnomos offers a PayPal payout. You approve it, PayPal processes it, and it posts only when PayPal confirms. A retry never pays twice. | PayPal Payouts API · you approve each payout · posts only when PayPal confirms |
| h5 | 1:30.8–1:38.8 | PayPal disputes (SAMPLE) → Build evidence → Send to PayPal (demo) | If a customer disputes a payment, Accnomos builds the evidence from your books, and nothing goes to PayPal until you send it. | PayPal Disputes API · SAMPLE dispute in the demo: nothing sent to PayPal |
| ai | 1:38.8–1:43.8 | Slide `cards/ai-in-action.png` | Everywhere in Accnomos, the AI proposes, code checks the figures, and you approve. | (the slide) |
| ea | 1:43.8–1:51.8 | Review › Add a receipt (`apps/web/public/sample-receipt.png`, fictional) → *Looks like a receipt* → Confirm → proposed entry → Approve (blur the verifier line: it names models); phone `a-capture`, `a-review` | Snap a receipt, and the AI reads it. Code checks the totals and the VAT, then you approve. | Receipts: the AI reads the photo · code checks totals and VAT · you approve |
| eb | 1:51.8–1:59.8 | Bank › Connect the test bank (TrueLayer sandbox, mock login blurred) → *40 new lines* → Matches › an *Exact* suggestion → Confirm; phone `a-bank` | Connect your bank by Open Banking. Here it's a test bank: the lines arrive and match your books. | Bank feed by Open Banking (TrueLayer's test bank) · lines arrive · matched to your books |
| ec | 1:59.8–2:06.8 | Ask *send a £450 invoice to Hartwell* → card → Approve → *INV-0008 sent* (demo); Add payment link → PayPal sandbox link | Ask for an invoice in plain words, and add a PayPal pay link. | Invoices from plain words · PayPal pay link |
| ed | 2:06.8–2:14.8 | `/vat` nine boxes → HMRC sandbox test user (password never on screen) → Submit → *Submitted to HMRC sandbox* receipt; phone `a-vat` | The nine VAT boxes are worked out by code and filed to HMRC's sandbox, with HMRC's own receipt. | VAT: nine boxes by code · filed to HMRC's sandbox · HMRC's receipt |
| ee | 2:14.8–2:19.8 | `/reports` profit and loss → Export to OneDrive | Reports, from profit and loss to who owes you. | Reports: profit and loss, who owes you · export to your drive |
| ef | 2:19.8–2:25.8 | Talk to Accnomos: *add a site visit tomorrow at 10* → calendar card → Approve; phone `a-talk` (voice) | Or talk to it, and approve what it proposes. | Talk to Accnomos: type or speak · you approve each card |
| eg | 2:25.8–2:30.8 | `/jobs` | Jobs, with their costs and margins. | Jobs: costs, hours and margin |
| eh | 2:30.8–2:35.8 | `/files`: the books folder, `Books.xlsx`, the exported report | And the books stay in your own OneDrive or Google Drive. | Your books, in your own OneDrive or Google Drive |
| fl | 2:35.8–2:38.8 | Slide `cards/features.png` (silent) | (none) | (the slide) |
| o0 | 2:38.8–2:46.2 | End card (accnomos.com · Try the demo, no sign-in · github.com/zaytunazs/accnomos · PayPal sandbox; no real money moved), presenter PiP | Everything you saw runs on PayPal's sandbox. Try it yourself at accnomos.com, no sign-in needed. | (the end card; PiP label) |

## What is real and what is sample

| Scene | Source |
|---|---|
| h1, h3 | PayPal's real **sandbox** (the demo copy connected to the server's sandbox app): the £85.00 and £372.00 payments of 11 Nov and PayPal's own balance |
| h4 | The demo's bill-pay seed; **Pay** sends a real sandbox payout to an `example.com` payee, which stays unclaimed: the screen says so and nothing posts |
| ag, h2 | The demo's labelled sample PayPal history (h2 must be filmed with PayPal NOT connected, or the answers change) |
| h5 | The demo's SAMPLE dispute; nothing is sent to PayPal |
| eb | TrueLayer's sandbox mock bank (public test login, blurred) |
| ed | HMRC's sandbox with a throwaway test user the demo makes |
| ea, ec, ee, ef, eg, eh | The fictional demo books |

## Music

A YouTube Audio Library track whose licence is **"Attribution not required"**, calm instrumental, about 3 minutes, mixed
about −28 dB under the voice, 1 s fade in and 2 s fade out (added in YouTube Studio or the edit). Don't use music from
anywhere else. After uploading, check YouTube Studio shows no copyright claim.

## Timing check

| Part | Lines | Slot |
|---|---|---|
| Intro | i0 | 10.4 s |
| Problem and how it works | pr, hw | 10.4 s |
| PayPal hero | h1, ag, h2, h3, h4, h5 | 1:18 |
| AI in action | ai | 5 s |
| Everything else | ea–eh | 52 s |
| Features (silent) and outro | o0 | 10.4 s |
| **Total** | | **2:46.2** |

If the cut runs long, trim in this order: the features slide, `eg` jobs, the ledger-explorer half of `ag`.
