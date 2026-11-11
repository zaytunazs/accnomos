# PayPal video: shot list and pre-recording checklist (v6, 12 Nov 2026)

## v6 cut (draft 6)

Scene ids and times are in [`VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md) (v6); the timeline is
`tools/video/paypal/timeline_paypal_v6.json` (from `make_timeline_v6.py`). v6 reuses the v5 footage below and adds:

```bash
node tools/video/paypal/capture_paypal.ts <media>/raw7 f-talkq    # w10: Talk answers "Who owes me the most?" (TALK_Q changes it)
```

| v6 scene | Footage (v5 id in brackets) | Notes |
|---|---|---|
| i0 | `m-home`, `pp-sync`, `m-review` + phone `a-home`, `a-review` | presenter picture-in-picture (`presenter_intro.mp4`) |
| pr | `cards/problem.png` | presenter picture-in-picture (`pr.mp4`); none after this (`"pip_until": 15.0`) |
| w1 (ea) | `raw6/f-receipt` + `a-capture`, `a-review` | |
| w2 (eb) | `f-bank`, `f-bankmatch` + `a-bank` | blur the bank names in the drop zone and the CSV line |
| w3 (ec) | `f-invoice`, `pp-invoice` | |
| w4 (h1), w5 (h3) | `pp-sync` + `a-sync`; `pp-tieout` | real sandbox |
| w6 (ag) | `pp-grid` | caption "AG Grid Community", 8.2 s |
| w7 (h4) | `raw5/pp-billpay`, `m-home` + `a-billpay`, `a-home` | ends *Waiting for the supplier to claim it* |
| w8 (h5) | `pp-disputes` | SAMPLE dispute |
| w9 (h2) | `pp-ask` + `a-ask-arrears`, `a-ask-search` | the phone shows only the typing: its answers show a link as raw text (`[Sync PayPal](/invoices…)`, fixed in Android 0.3.22), so the answers are the web, enlarged |
| w10 | `raw7/f-talkq` + `a-talk` | a typed question answered; caption "type or speak" |
| w11 (ed), w12 (ee), w13 (eh) | `f-vat` + `a-vat`; `f-reports` (blur the line naming other accounting products); `f-files` | |
| d1, d2, d3 | `cards/different-0…7.png`, `features-1…5.png`, `built-1…5.png` | built up point by point (`cards/README.md`) |
| o0 | end card | voice only |

Not used in v6: `m-jobs` (a plain look at the page: nothing happens in it), `f-talk` (the calendar card), the
"how it works" card and the "AI in action" slide.

In split scenes the small tag sits inside the web capture's top-right corner, so it no longer overlaps the phone.

Frame check for v6 (12 Nov): every scene looked at for model names, real email addresses and real bank, retailer or
accounting-product names. Seen and accepted: "the local open-weights model" (a description, not a name),
`demo@accnomos.example` and `example.com` payees (reserved example domains), PayPal's sandbox test payer name, and
fictional businesses only. Blurred: the bank-name list on Bank, the product-name line on Reports.

## v5 capture (what draft 3 was cut from)

All web footage is the live site in "Try the demo" (fictional books), recorded by
`tools/video/paypal/capture_paypal.ts`; the phone clips are recorded on the Android emulator (`android/a-*.mp4`,
1080 × 2400); the timeline is `tools/video/paypal/timeline_paypal_v5.json` (from `make_timeline_v5.py`) and the cut is
made by `tools/video/paypal/assemble_paypal.sh`.

```bash
export PW_FROM=<folder with playwright in node_modules>          # agent sandbox: /opt/npm-tools
R=<media>/raw5
PAYPAL_CONNECT=1 SALE_MATCH=DEMO-1002 node tools/video/paypal/capture_paypal.ts <media>/raw pp-sync   # h1 (real sandbox)
PAYPAL_CONNECT=1 SYNC_FIRST=1 node tools/video/paypal/capture_paypal.ts <media>/raw pp-tieout        # h3
SYNC_FIRST=1 GRID_APPROVE=1 node tools/video/paypal/capture_paypal.ts <media>/raw pp-grid            # ag (sample history)
node tools/video/paypal/capture_paypal.ts <media>/raw pp-ask,pp-disputes                             # h2 (NOT connected), h5
PAYPAL_CONNECT=1 PAY=1 node tools/video/paypal/capture_paypal.ts $R pp-billpay,m-home,pp-invoice     # h4 (sandbox payout), ec link
node tools/video/paypal/capture_paypal.ts <media>/raw6 f-receipt   # after the web fix
node tools/video/paypal/capture_paypal.ts $R f-invoice,f-reports,f-vat,f-files,f-bank,f-bankmatch,f-talk
```

- `f-bank` signs in to TrueLayer's sandbox with its public mock login (john / doe): blur it. `f-vat` signs in to
  HMRC's sandbox with the throwaway test user the demo makes: cut the HMRC pages and never show the password.
- `f-receipt`: since web af90aeda the verifier line says "the local open-weights model" instead of the raw model id;
  footage from before that deploy shows the id and must be blurred or cut. Check every frame anyway.
- `pp-ask` must run on a demo **without** PayPal connected (with the real sandbox connected the answers are "no").
- `pp-billpay` with `PAY=1` pays the demo's `example.com` payee in the sandbox: it ends *Waiting for the supplier to
  claim it* (never *Paid and posted*); say nothing that claims otherwise.
- Blur: bank names in Bank's drop zone ("Barclays, Starling, …") and `starling.csv`; the "Xero, QuickBooks, Sage and
  FreeAgent" line on Reports.

The v4 notes below still hold for the signed-in sandbox books and the checklist; the v4 montage is replaced by the
"Everything else, in action" scenes ea–eh.

Companion to [`VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md). Footage comes from three places:

- **Signed-in sandbox books** (h1, ag, h2, h3, montage 1): the owner's test sign-in on `https://accnomos.com` with
  **Load sample books** (a fictional company), PayPal connected in direct mode, and the seed invoices below. These
  scenes need real sandbox payments from hours earlier: PayPal's Transaction Search lists a payment up to 3 hours
  late, and a fresh demo copy cannot see them. The tie-out (h3) appears only when PayPal is really connected; it is
  hidden on the demo's sample history.
- **"Try the demo"** (h4, h5, most of the montage; `ag` can also be filmed here on the sample history): a fresh copy of the fictional demo books with no sign-in. The demo has
  one SAMPLE dispute built by code; with the server in direct mode it can connect PayPal and send sandbox payouts.
- **AI presenter** (i0, o0): a realistic AI presenter, labelled "AI presenter" on screen. It must never claim to be
  the founder; the words are fixed in `narration/00-i0-presenter-intro.txt` and `narration/18-o0-outro.txt` (v6: i0 and pr are the presenter; o0 is voice only).
- **Cards and slides** (pr, hw, ai, fl): `cards/problem.svg`, `cards/how-it-works.svg`, `cards/ai-in-action.png`,
  `cards/features.png` (sources and rendering: `cards/README.md`).

Automated capture of the demo-mode shots: `tools/video/paypal/capture_paypal.ts` (below). The Android shot and the
presenter are made by hand. Cut every loading spinner and set-up step: judges should see results, not waiting.

## Pre-recording checklist

**Server and branch**

- [ ] `main` (live) includes everything filmed: the trust fixes, PayPal first, Upcoming PayPal payments, the support
      centre and the Power grid. Check each screen opens on `accnomos.com` before recording.
- [ ] The API server's runtime env has `PAYPAL_DIRECT=1` and the **sandbox** REST app's `PAYPAL_CLIENT_ID` /
      `PAYPAL_CLIENT_SECRET` (direct mode refuses live credentials). Settings › Online payments shows **Connect PayPal
      (test mode)**.
- [ ] `STRIPE_VISIBLE` is unset, so Stripe is not offered anywhere on screen.
- [ ] Smoke test from the server: `uv run python tools/payments_sandbox_smoke.py paypal`.

**Seed data (status 11 Nov 2026)**

- [x] Invoices DEMO-1001, DEMO-1002 and DEMO-1003 exist in the signed-in sandbox books, each with a PayPal pay link.
- [x] **DEMO-1002 and DEMO-1003 were paid by the sandbox buyer at about 16:40 on 11 Nov.** Transaction Search
      should list them from about 19:40. Before recording h1, press **Sync PayPal** once **off camera** only to check
      they appear, then approve nothing.
- [ ] **DEMO-1001 is still unpaid.** Keep it unpaid: it is the "Add payment link" example if a payment-link shot is
      needed, and it shows that an unpaid invoice gets no proposal.
- [ ] One payment from the sandbox buyer to the sandbox business account **with no invoice** (PayPal sandbox "Send
      money"), at least 3 h before recording, so h1 has a sale whose VAT the owner chooses. If there is none, film the
      VAT choice on the demo's sample history and caption it "demo sample history".
- [ ] Customer and supplier names and emails are fictional (for example `accounts@example.co.uk`). The sandbox
      buyer's login is `<<SANDBOX BUYER LOGIN>>`; it lives in the owner's password manager, never in the repo or on
      screen.
- [ ] If anything was approved by mistake, film h1 on the demo's sample history instead (labelled "Sample PayPal
      history for this demo" on screen) and change "it fetches every payment from PayPal itself" in the caption to
      "demo sample history".

**Bill pay (h4)**

- [x] Verified 11 Nov 2026: a payout to a **registered** sandbox personal account reached SUCCESS (batch PENDING →
      PROCESSING → SUCCESS in about 30 s; PayPal's fee £0.02).
- [ ] A fictional supplier with that registered sandbox account's email saved under *Suppliers' PayPal emails*, and an
      unpaid bill from that supplier due **today** (the contact's terms, else 30 days after the bill date). In the demo,
      add a bill dated 30 days ago if none is due today.
- [ ] Autopilot for bills stays **Off** and is not shown.
- [ ] The status moves from *PayPal is processing it* to *Paid and posted* when Accnomos checks again. Record through it,
      reloading Purchases if needed, and speed it up in the edit with a "sped up" caption.

**Browser and screen**

- [ ] Clean Chrome/Chromium profile, no extensions, bookmarks bar hidden, window 1280 × 720 CSS px at device scale 2,
      zoom 100 %, `en-GB`, Europe/London. Do Not Disturb on; every other app and tab closed.
- [ ] Nothing personal on screen: no real names, emails, phone numbers, addresses, merchant ids or account numbers.
      Crop or blur the signed-in account's email in the header.
- [ ] **Blur in the edit:** the "Connected: …" merchant id; every byline that names a model ("explanation by …",
      "Drafted by …", "coded by …", "Read by …"); the sandbox buyer's and payee's emails; HMRC sandbox passwords; any
      PayPal invoice id (`INV2-…`) that is legible.
- [ ] Never show Settings › AI, model pickers, Autopilot or chat-app screens.

**Power grid (ag)**

- [ ] Settings › Business › **Power grid** › tick *Use the power grid* in the recording browser (it is saved on this
      device only). Do it off camera.
- [ ] At least three PayPal rows **waiting** in the grid when recording (re-sync after h1 or use the demo's sample
      history), so *Approve selected (3)* and the totals row have something to show.
- [ ] Off camera, open `/reports/ledger-grid`, type *PayPal fees over £5* → **Filter**, and check rows appear. The
      seed invoices are small, so their fees may all be under £5. If nothing shows, film the filter on the demo books
      or change the spoken amount in `ag` (and re-render it) to one that returns rows.

**AI presenter (i0, o0)**

- [ ] Labelled "AI presenter" on screen for the whole slot. Words exactly as in the narration files (it introduces
      itself as an AI presenter and never claims to be the founder).
- [ ] The owner has the rights to the avatar and its voice. In YouTube, *Altered content* = Yes (see `UPLOAD.md`).
- [ ] Plain background, no brand logos.

## Click paths: hero scenes

`demo` = `https://accnomos.com/judges` → **Start the demo** (wait about 12 s). `signed-in` = the test sign-in above.

### h1 Sync PayPal (signed-in, after 19:40 on 11 Nov)
Film with the Power grid **off** (the card list); turn it on for `ag` afterwards.
1. Sidebar **Invoices**, scroll to the **PayPal** panel. Hover *"Every transaction waits for your approval"*.
2. Click **Sync PayPal**. Wait for *"N new from PayPal · N waiting for you"*.
3. Hover the **DEMO-1002** card: title, then *PayPal fee £… · you receive £…*, then the Dr/Cr table.
4. Scroll to the sale with no invoice. Open **VAT on this sale (choose before approving)** → *Standard rate*.
5. Back to DEMO-1002 → **Approve £…**. Hold on *"Invoice payment of £… (…) is in your books."*

### h2 AI search in Ask (demo books: Try the demo › Start a new demo)
1. Sidebar **Ask**. Type *Did that client pay all the arrears? They had around £500 overdue — check PayPal.* → **Ask**.
   Hold 3 s on "Yes, the arrears look paid in full: **£492.00** on 8 Nov 2026 from Wrenfield Dental Studio through
   PayPal … not in your books yet".
2. Type *There was a payment via PayPal last month, probably around £100 for stationery — how much exactly was it?* →
   **Ask**. Hold 3 s on "It was **£97.79** on 14 Oct 2026 to Quillstone Office Supplies Ltd through PayPal".
   Both checked live on 11 Nov 2026. Cut the wait; blur any byline. Start a fresh demo just before filming (a demo ends
   after 2 hours or when the server restarts).

### h3 Tie-out (signed-in)
1. **Invoices**, top of the **PayPal** panel: *"PayPal says £… (as of …) · your books (1240 PayPal clearing) £…"*.
2. Cursor under the "as of" time 2 s, then under *"Difference … = …"* 2 s. Zoom in the edit.

### h4 Pay a bill with PayPal (demo or signed-in)
1. Sidebar **Purchases**, scroll to **Pay bills with PayPal**. Under **Due today**, hover the supplier and amount.
2. **Approve payment** → *"Pay £… to … from your PayPal account now?"* (blur the email) → **Pay £…**.
3. Hold on *PayPal is processing it*; reload Purchases after about 30 s → *Paid and posted*.

### h5 Disputes evidence (demo)
1. **Invoices**, scroll to **PayPal disputes**. Hover *Waiting for your answer* and *answer by …*.
2. **Build evidence** → *Response for PayPal (preview)*. Scroll slowly (blur the byline).
3. **Send to PayPal (demo)** → hold on *"Demo: recorded as sent. Nothing was sent to PayPal."*

### pr, hw Cards
`cards/problem.svg` (6 s), then `cards/how-it-works.svg` (7 s, boxes built left to right). Render: `cards/README.md`.

### ag Power grid (signed-in or demo, Power grid on)
1. **Invoices**, PayPal panel: the **PayPal review grid** is shown in place of the card list.
2. Tick three waiting rows. Hover the totals row *Total of N shown (GBP)*. Click **Approve selected (3)**, confirm,
   and hold on the results column (about 5 s).
3. Cut to **Reports › Ledger explorer** (`/reports/ledger-grid`). In **Show me…** type *PayPal fees over £5* →
   **Filter**. Hold on the filtered grid (about 5 s). Caption: "AG Grid Community". Blur any model byline.

### ai, fl Slides
`cards/ai-in-action.png` (6 s, before the montage) and `cards/features.png` (5 s, before the outro): stills, made by
the edit, with no screen recording.

## Click paths: montage (10 × 3 s, demo unless marked)

1. `/files` (signed-in): the books folder and `Books.xlsx`.
2. `/review`: a receipt proposal card → **Approve** (cut the reading time).
3. `/bank`: the Bank feed card and matched lines.
4. `/vat`: the nine boxes, then HMRC's sandbox receipt (reuse earlier sandbox-filing footage if it still matches).
5. `/reports/profit-and-loss`.
6. **Talk to Accnomos** → the voice button → the card for a spoken question. Blur bylines.
7. `/jobs` → one job.
8. `/payroll`: the pay run estimate.
9. Android phone or emulator: APK from GitHub Releases → **Try the company demo** → Home, then Review.
10. `/purchases` → **Upcoming PayPal payments** → **Calendar**; the last second on `/support` (the help centre).

## Automated capture (demo mode)

`tools/video/paypal/capture_paypal.ts` reuses the v3 capture helpers (`tools/video/lib/human.ts`,
`tools/video/lib/recorder.ts`), drives the live site in "Try the demo" and records one WebM per shot plus
`<shot>.marks.json`. It fakes nothing: if a screen is not there, the shot ends with an error in its marks file.

```bash
# from a folder whose node_modules has playwright (e.g. apps/web after pnpm install)
PW_FROM=apps/web node tools/video/paypal/capture_paypal.ts docs/video/raw-paypal
PW_FROM=apps/web node tools/video/paypal/capture_paypal.ts docs/video/raw-paypal pp-disputes,pp-billpay
PW_FROM=apps/web node tools/video/paypal/capture_paypal.ts docs/video/raw-paypal m-review,m-bank,m-quotes   # montage
# PAYPAL_CONNECT=1 connects PayPal (test mode) in the demo copy first (needs PAYPAL_DIRECT=1 on the server);
# PAY=1 really presses "Pay £…" in pp-billpay (a sandbox payout); without it the shot ends on the confirmation.
```

Hero shots: `pp-sync`, `pp-grid` (needs the Power grid on: the script turns it on in the demo copy's browser),
`pp-ask`, `pp-billpay`, `pp-disputes` (plus `pp-invoice` for a payment-link insert). Montage shots: `m-review`,
`m-bank`, `m-vat`, `m-reports`, `m-jobs`, `m-payroll`, `m-upcoming`, `m-support` (files, voice and Android are by hand;
`m-quotes` is kept for a spare shot). In the demo, `pp-sync` reads the labelled sample history
unless `PAYPAL_CONNECT=1`; the tie-out shows only when connected. The signed-in hero footage (h1–h3 with the seed
invoices) is recorded by hand, following the click paths above.

## Voice-over

```bash
bash docs/submission/paypal/narration/render.sh                                  # all lines, on the GPU server
bash docs/submission/paypal/narration/render.sh w1,w2,w3,w4,w5,w6,w7,w8,w9,w10,w11,w12,w13,d1,d2,d3 # the lines new in v6
# i0 and pr are spoken by the presenter clips (their own sound); o0 is voice only in v6
```
