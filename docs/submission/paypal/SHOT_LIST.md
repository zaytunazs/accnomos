# PayPal video: shot list and pre-recording checklist (v3, 12 Nov 2026)

Companion to [`VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md). Footage comes from three places:

- **Signed-in sandbox books** (h1, ag, h2, h3, montage 1 and 10): the owner's test sign-in on `https://accnomos.com` with
  **Load sample books** (a fictional company), PayPal connected in direct mode, and the seed invoices below. These
  scenes need real sandbox payments from hours earlier: PayPal's Transaction Search lists a payment up to 3 hours
  late, and a fresh demo copy cannot see them. The tie-out (h3) appears only when PayPal is really connected; it is
  hidden on the demo's sample history.
- **"Try the demo"** (h4, h5, most of the montage; `ag` can also be filmed here on the sample history): a fresh copy of the fictional demo books with no sign-in. The demo has
  one SAMPLE dispute built by code; with the server in direct mode it can connect PayPal and send sandbox payouts.
- **AI presenter** (i0, o0): a realistic AI presenter, labelled "AI presenter" on screen. It must never claim to be
  the founder; the words are fixed in `narration/00-i0-presenter-intro.txt` and `narration/10-o0-presenter-outro.txt`.
- **Cards** (pr, hw): `cards/problem.svg` and `cards/how-it-works.svg`, rendered to PNG (`cards/README.md`).

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
- [ ] For h2, at least one PayPal fee must be **approved** in the books in the current quarter (approve DEMO-1003's
      card off camera, or film h2 after h1). Ask's answers count only approved entries.
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

### h2 Ask about PayPal (signed-in, after h1 so fees are approved)
1. Sidebar **Ask**. Type *What did PayPal cost me this quarter?* → **Ask**. Hold on the figure 2 s.
2. Type *How much is in PayPal?* → **Ask**. Hold on the figure 2 s. Blur the byline under each answer.

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

## Click paths: montage (12 × 3 s, demo unless marked)

1. `/files` (signed-in): the books folder and `Books.xlsx`.
2. `/review`: a receipt proposal card → **Approve** (cut the reading time).
3. `/bank`: the Bank feed card and matched lines.
4. `/sales/quotes`: one quote.
5. `/vat`: the nine boxes, then HMRC's sandbox receipt (reuse earlier sandbox-filing footage if it still matches).
6. `/reports/profit-and-loss`.
7. **Talk to Accnomos** → the voice button → the card for a spoken question. Blur bylines.
8. `/jobs` → one job.
9. `/payroll`: the pay run estimate.
10. Home **Plan today** (signed-in: it needs a calendar).
11. Android phone or emulator: APK from GitHub Releases → **Try the company demo** → Home, then Review.
12. `/purchases` → **Upcoming PayPal payments** → **Calendar**; the last second on `/support` (the help centre).

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
`m-bank`, `m-quotes`, `m-vat`, `m-reports`, `m-jobs`, `m-payroll`, `m-upcoming`, `m-support` (the rest are by hand). In the demo, `pp-sync` reads the labelled sample history
unless `PAYPAL_CONNECT=1`; the tie-out shows only when connected. The signed-in hero footage (h1–h3 with the seed
invoices) is recorded by hand, following the click paths above.

## Voice-over

```bash
bash docs/submission/paypal/narration/render.sh                                  # all lines, on the GPU server
bash docs/submission/paypal/narration/render.sh pr,hw,h1,ag,h2,h3,h4,h5,m1       # if the presenter tool voices i0/o0
```
