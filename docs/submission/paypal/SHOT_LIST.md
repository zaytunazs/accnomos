# PayPal video: shot list and pre-recording checklist (v2, 11 Nov 2026)

Companion to [`VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md). Footage comes from three places:

- **Signed-in sandbox books** (h1, h2, h3, montage 11 and 13): the owner's test sign-in on `https://accnomos.com` with
  **Load sample books** (a fictional company), PayPal connected in direct mode, and the seed invoices below. These
  scenes need real sandbox payments from hours earlier: PayPal's Transaction Search lists a payment up to 3 hours
  late, and a fresh demo copy cannot see them. The tie-out (h3) appears only when PayPal is really connected; it is
  hidden on the demo's sample history.
- **"Try the demo"** (h4, h5, most of the montage): a fresh copy of the fictional demo books with no sign-in. The demo has
  one SAMPLE dispute built by code; with the server in direct mode it can connect PayPal and send sandbox payouts.
- **Presenter** (i0, o0): recorded by the owner, either on camera or as a clearly labelled AI presenter.

Automated capture of the demo-mode shots: `tools/video/paypal/capture_paypal.ts` (below). The Android shot and the
presenter are recorded by hand.

## Pre-recording checklist

**Server and branch**

- [ ] `paypal-wave3` is **deployed** to `accnomos.com` / `api.accnomos.com`. It includes the trust fixes (tie-out, VAT
      choice on unmatched sales) and the fictional sample suppliers. Also deploy `paypal-default` (PayPal first,
      Stripe hidden) and, for montage shot 15, `billpay-schedule` (Upcoming PayPal payments, commit `3dfb7b39`). If
      `billpay-schedule` is not deployed, cut the calendar clause from m1 and show `/help` instead.
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

**Presenter (i0, o0)**

- [ ] On camera: plain background, no brand logos on clothing or behind, lapel or USB microphone, 1080p, same
      words as `narration/00-i0-presenter-intro.txt` and `narration/08-o0-presenter-outro.txt`.
- [ ] AI presenter: a label "AI presenter" on screen for the whole slot and a line in the YouTube description; the
      voice can be `bf_emma` (render i0 and o0 with `render.sh i0,o0`). The owner must have the rights to the avatar.

## Click paths: hero scenes

`demo` = `https://accnomos.com/judges` → **Start the demo** (wait about 12 s). `signed-in` = the test sign-in above.

### h1 Sync PayPal (signed-in, after 19:40 on 11 Nov)
1. Sidebar **Files**: hold 2 s on the books folder (lead-in for "your own OneDrive or Google Drive").
2. Sidebar **Invoices**, scroll to the **PayPal** panel. Hover *"Every transaction waits for your approval"*.
3. Click **Sync PayPal**. Wait for *"N new from PayPal · N waiting for you"*.
4. Hover the **DEMO-1002** card: title, then *PayPal fee £… · you receive £…*, then the Dr/Cr table.
5. Scroll to the sale with no invoice. Open **VAT on this sale (choose before approving)** → *Standard rate*.
6. Back to DEMO-1002 → **Approve £…**. Hold on *"Invoice payment of £… (…) is in your books."*

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

### h6 Title card
Made in the edit: three lines over a blurred Invoices still.

## Click paths: montage (about 3 s each, demo unless marked)

1. `/review` → **Add a receipt** (the sample receipt) → **Confirm** → proposal card → **Approve**. Use only the
   approve moment (the model's reading time is cut).
2. `/bank`: the Bank feed card and matched lines.
3. `/invoices` (list), then `/sales/quotes` (one quote).
4. `/vat`: the nine boxes.
5. `/vat` → submit to HMRC's sandbox → HMRC's receipt (reuse the v3 footage of the sandbox filing if it still matches
   the current screens).
6. `/reports/profit-and-loss`.
7. `/ask` (a typed question and its answer), then **Talk to Accnomos** → the voice button. Blur bylines.
8. `/jobs` → one job.
9. `/vehicles`: the mileage log.
10. `/payroll`: the pay run estimate.
11. `/calendar`, then Home **Plan today** (signed-in: it needs a calendar).
12. `/contacts` → one contact's statement.
13. `/files` (signed-in): the books folder and `Books.xlsx`.
14. Android phone or emulator: APK from GitHub Releases → **Try the company demo** → Home, then Review.
15. `/purchases` → **Upcoming PayPal payments** → **Calendar** or **Download all (.ics)** (only if `billpay-schedule`
    is deployed); otherwise `/help`.

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

Hero shots: `pp-sync`, `pp-ask`, `pp-billpay`, `pp-disputes` (plus `pp-invoice` for a payment-link insert). Montage
shots: `m-review`, `m-bank`, `m-invoices`, `m-quotes`, `m-vat`, `m-reports`, `m-ask`, `m-jobs`, `m-vehicles`,
`m-payroll`, `m-calendar`, `m-contacts`, `m-upcoming`, `m-help`. In the demo, `pp-sync` reads the labelled sample history
unless `PAYPAL_CONNECT=1`; the tie-out shows only when connected. The signed-in hero footage (h1–h3 with the seed
invoices) is recorded by hand, following the click paths above.

## Voice-over

```bash
bash docs/submission/paypal/narration/render.sh                      # on the GPU server, in the TTS venv
bash docs/submission/paypal/narration/render.sh h1,h2,h3,h4,h5,h6,m1 # if the owner presents i0/o0 on camera
```
