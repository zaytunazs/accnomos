# PayPal AI Hackathon: demo video script

Target length **2:45** (hard limit 2:50; the rules allow under 3:00). Narration is 313 words at about 150 words a
minute (2:05 of speech); the rest is screen time between lines. Voice: the existing voice-over tool, voice `bf_emma`
(`docs/submission/paypal/narration/render.sh`). Click paths, the pre-recording checklist and what to blur are in
[`SHOT_LIST.md`](SHOT_LIST.md); per-scene narration files are in [`narration/`](narration/).

**Pitch (one sentence, kept to throughout):** Accnomos keeps a UK small business's books in its own OneDrive or Google
Drive and files VAT to HMRC; PayPal is where it gets paid and pays its bills.

**Rules this script follows**

- Under 3 minutes, public on YouTube, the project shown working on the device it was built for: the web app in a
  desktop browser (the Android app has no PayPal screen, so there is no phone shot).
- PayPal is the centre: every scene after the pitch is a PayPal call or its result in the books.
- No third-party logos or music. PayPal's name is used as the sponsor; PayPal's own sandbox checkout pages appear in
  scene p3 as they are. Background music, if any, must be original or licensed for this use (none is planned).
- Only fictional data: the sample books' business, customers and suppliers; sandbox buyer and payee accounts.
- Honest limits on screen: sandbox only (p2, p3 captions); PayPal's reporting lag with its refresh time (p4, p5);
  payouts cannot be future-dated in PayPal (p6). Every claim is one `docs/HONESTY.md` allows.
- The AI is described only as "the AI": no model names, no Settings › AI, no model bylines on screen (blur them where a
  card shows one, see SHOT_LIST.md). Autopilot, voice and chat apps are not in this video.

## Scenes

Times are the planned cut. "Narration" is spoken and captioned verbatim (spoken-only fixes are in
`narration/lines.json` under `say`).

| # | Time | Screen / route | Action | Narration | On-screen caption |
|---|---|---|---|---|---|
| p0 | 0:00–0:10 | `/invoices` (signed-in sandbox books), invoice DEMO-1001 row with **Paid** chip; quick cuts (1 s each) to the PayPal proposal card, the Purchases **Due today** card and the VAT boxes | Cursor rests on the paid invoice; three one-second flash-forwards | A customer just paid this invoice with PayPal. Watch the money reach the books, pay a supplier and land in the VAT return. | **Accnomos × PayPal** · AI bookkeeping and VAT for UK small businesses |
| p1 | 0:10–0:25 | `/` Home, then `/files` (the books folder in the owner's own drive) | Scroll Home once; open Files, hover the books folder and `Books.xlsx` | This is Accnomos. It keeps a UK small business's books in its own OneDrive or Google Drive, and files VAT to HMRC. PayPal is where the business gets paid, and where it pays its bills. | Your books, in your own drive · VAT filed to HMRC (sandbox in this video) |
| p2 | 0:25–0:43 | `/invoices` → DEMO-1003 → **Add payment link** → dialog *Payment link for DEMO-1003* → **Paid into: PayPal** → **Make payment link**; then **View PDF** | Make the link; the dialog shows the PayPal link; open the PDF and hover the pay link | I add a PayPal payment link to an invoice. Accnomos creates a real PayPal invoice, in PayPal's sandbox, with the same lines and VAT, and puts the link on the PDF and in the email. | PayPal Invoicing API · create and send · **PayPal sandbox: no real money** |
| p3 | 0:43–0:55 | PayPal's sandbox pay page for DEMO-1003 (separate browser profile, signed in as the sandbox buyer) | Pay; PayPal's confirmation | The customer pays in PayPal. This is PayPal's sandbox, so no real money moves. | Customer's view · PayPal sandbox buyer account (fictional) |
| p4 | 0:55–1:22 | `/invoices` → **PayPal** panel → **Sync PayPal** → status line *"N new from PayPal · N waiting for you"* → proposal cards | Click Sync; hover a card for DEMO-1001: *"Invoice payment · … received £… · PayPal fee £… · you receive £…"* and its Dr/Cr lines; scroll to the sale with no invoice, open **VAT on this sale (choose before approving)**, pick *Standard rate*; back to DEMO-1001 → **Approve £…** | PayPal's reports can lag by up to three hours, so here are payments from earlier today. Sync PayPal proposes each one: the gross, PayPal's fee and the net, matched to its invoice. A sale with no invoice waits until I choose its VAT. The AI suggests, code does the sums in pence, and nothing posts until I approve. | PayPal Transaction Search · paid ≥ 3 h ago (PayPal's reporting delay) · nothing posts without your approval |
| p5 | 1:22–1:33 | Same page, the tie-out line at the top of the PayPal panel: *"PayPal says £… (as of 11 Nov, 14:05) · your books (1240 PayPal clearing) £…"* and *"Difference … = waiting for your approval … + not posted …"* | Zoom (edit) on the line; cursor under the "as of" time | Then the tie-out: PayPal's own balance, with the time PayPal last refreshed it, against PayPal in my books, with the difference explained. | PayPal Balances API · PayPal's figure as of its last refresh |
| p6 | 1:33–1:58 | `/purchases` → **Pay bills with PayPal** → **Due today** card (fictional supplier, sandbox payee email) → **Approve payment** → *"Pay £… to … from your PayPal account now?"* → **Pay £…**; status *Paid and posted*; then the upcoming payments list → **Add to calendar** (only if the schedule work is deployed, see SHOT_LIST.md) | Approve and pay; hover the status; hover the next payment's date and Add to calendar | Bills work the other way. On a supplier bill's due date, Accnomos offers to pay it by PayPal Payout. I approve, and it posts when PayPal confirms. PayPal can't schedule a payout ahead, so Accnomos pays on or after the due date, when the app is open. Upcoming payments can go in my calendar. | PayPal Payouts API · one payout per bill, retried safely (same batch id) · pays on or after the due date |
| p7 | 1:58–2:15 | `/invoices` → **PayPal disputes** panel (the demo's SAMPLE dispute) → **Build evidence** → *Response for PayPal (preview)* → **Send to PayPal (demo)** | Build; scroll the preview (invoice number, amounts, dates); blur the "Drafted by …" byline; click Send (demo) | If a customer opens a dispute, Accnomos builds the evidence from the books: the invoice, the payment and the dates, every figure checked by code. I read it before anything goes to PayPal. | PayPal Disputes API · SAMPLE dispute in the demo: nothing is sent to PayPal |
| p8 | 2:15–2:26 | `/vat` → the open period's nine boxes; hover Box 1 and Box 6 | Hover; optionally open Box 6's explanation and point at the PayPal sale | And when the quarter ends, those PayPal sales are already in the VAT return, ready to file with HMRC's sandbox. | Box 1 and Box 6 include the approved PayPal sales · HMRC sandbox |
| p9 | 2:26–2:45 | End card (still, no logos but Accnomos's) | Hold | Accnomos. The AI proposes, code calculates, and you approve. Try the demo at accnomos.com. The code is on GitHub. | **accnomos.com** · Try the demo, no sign-in · github.com/zaytunazs/accnomos · PayPal sandbox only; no real money moved |

## Timing check

| Scene | Narration (words) | Speech at 150 wpm | Slot |
|---|---|---|---|
| p0 | 23 | 9.2 s | 10 s |
| p1 | 35 | 14.0 s | 15 s |
| p2 | 35 | 14.0 s | 18 s |
| p3 | 14 | 5.6 s | 12 s |
| p4 | 58 | 23.2 s | 27 s |
| p5 | 22 | 8.8 s | 11 s |
| p6 | 54 | 21.6 s | 25 s |
| p7 | 33 | 13.2 s | 17 s |
| p8 | 20 | 8.0 s | 11 s |
| p9 | 19 | 7.6 s | 19 s (end card held) |
| **Total** | **313** | **2:05** | **2:45** |

If the rendered voice runs long, cut in this order: the calendar sentence in p6 (if the upcoming-payments list is not
deployed, it must go anyway), the flash-forwards in p0, the PDF in p2.

## Upload

- YouTube, **Public**, title "Accnomos: PayPal-powered bookkeeping and VAT for UK small businesses (PayPal AI
  Hackathon)". Description: the pitch sentence, `https://accnomos.com`, `https://github.com/zaytunazs/accnomos`,
  "Recorded against PayPal's sandbox; no real money moved."
- Captions: upload the narration as the caption track (the text in `narration/lines.json`).
- No music, or only original or properly licensed music; YouTube's Content ID check must show no claims before the
  link goes on Devpost.
