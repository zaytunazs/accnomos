# PayPal video: shot list and pre-recording checklist

Companion to [`VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md). Two kinds of footage:

- **Signed-in sandbox books** (scenes p0, p2, p3, p4, p5, p8): the owner's test sign-in on `https://accnomos.com` with
  **Load sample books** (fictional company), PayPal connected in direct mode. Needed because Sync PayPal reads PayPal's
  Transaction Search, which lists a payment up to 3 hours late, and a fresh demo copy cannot hold payments made hours
  earlier. The tie-out (p5) only shows when PayPal is really connected (it is hidden on the demo's sample history).
- **"Try the demo"** (scenes p6, p7, optionally p4 as a fallback): a fresh copy of the fictional demo books, no sign-in.
  The demo has one SAMPLE dispute built by code; with the server in direct mode the demo can connect PayPal and send
  sandbox payouts.

Automated capture of the demo-mode scenes: `tools/video/paypal/capture_paypal.ts` (below). The PayPal checkout (p3) is
filmed by hand: it is PayPal's own page and the sandbox buyer's sign-in must not be scripted with credentials in the
repo.

## Pre-recording checklist

Do these in order. Tick each before pressing record.

**Server and branch (the day before, or at least 4 hours before recording)**

- [ ] The branch to film is merged and **deployed** to `accnomos.com` / `api.accnomos.com`: `paypal-wave3` plus
      `paypal-trust` (tie-out, VAT choice on unmatched sales) and `paypal-default` (PayPal first in the payment-link
      dialog). For the calendar line in p6, also the upcoming-payments work (`billpay-schedule`, not committed at the
      time of writing): if it is not deployed, cut that sentence and shot.
- [ ] The API server's runtime env has `PAYPAL_DIRECT=1` and the **sandbox** REST app's `PAYPAL_CLIENT_ID` /
      `PAYPAL_CLIENT_SECRET` (direct mode refuses live credentials). Check: Settings › Online payments shows
      **Connect PayPal (test mode)**.
- [ ] `STRIPE_VISIBLE` is unset, so Stripe is not offered anywhere on screen.
- [ ] Smoke test from the server: `uv run python tools/payments_sandbox_smoke.py paypal` creates, sends and reads back a
      £1.20 sandbox invoice.

**Seed data (at least 3 hours before recording: PayPal's Transaction Search delay)**

- [ ] Sign in to `accnomos.com` with the owner's **test** account (not a real business), **Load sample books**.
- [ ] Settings › Business: fictional business name, address and VAT number only (the sample books' own). These go on
      the PayPal invoices.
- [ ] Invoice numbers DEMO-1001, DEMO-1002, DEMO-1003: there is no settings screen for the prefix; before creating
      them, set `_System/Invoicing/sequence.json` in the books folder to `{"prefix": "DEMO-", "next": 1001}` (or
      keep the sample books' own `INV-` numbers: the narration names no invoice number).
- [ ] Settings › Online payments → **Connect PayPal (test mode)** (direct mode returns at once).
- [ ] Create three invoices to fictional customers, each with a fictional customer email (for example
      `accounts@example.co.uk`), small amounts (£12–£90), 20% VAT: DEMO-1001, DEMO-1002, DEMO-1003. **Add payment
      link** → PayPal on each; **Preview and send** DEMO-1001 and DEMO-1002.
- [ ] In a separate browser profile, open the PayPal links for **DEMO-1001 and DEMO-1002** and pay both as the sandbox
      **personal** buyer `<<SANDBOX BUYER LOGIN>>` (credentials stay in the owner's password manager, never in the
      repo or on screen).
- [ ] From the same sandbox buyer, send one small payment to the sandbox business account **with no invoice** (PayPal
      sandbox "Send money"), so p4 has a sale with no invoice that needs its VAT chosen.
- [ ] **DEMO-1003 stays unpaid** for the live payment in p3.
- [ ] Note the time. Do not record p4/p5 until at least 3 hours later; then press **Sync PayPal** once off camera to
      check both payments appear, and **Reject nothing / approve nothing** (they must still be waiting on camera). If a
      payment is approved by mistake, p4 can be filmed on the demo's sample history instead (labelled "Sample PayPal
      history for this demo" on screen; then say "here is the demo's sample history" in place of "payments from
      earlier today").
- [ ] VAT: on `/vat`, note Box 1 and Box 6 for the open period that contains today's date **before** approving, so p8
      can show they moved. If the open period does not contain today's date, film p8 as Box 6's explanation listing the
      PayPal sale, or drop the claim.

**Bill pay (for p6; in "Try the demo" or the signed-in books)**

- [ ] A supplier contact (fictional name) with a **sandbox personal account's email** saved under *Suppliers' PayPal
      emails*, and an unpaid bill from that supplier whose due date (the contact's terms, else 30 days after the bill
      date) is **today**, so it shows under **Due today**. In the demo, check off camera which supplier has a bill due
      today, or add a bill dated 30 days ago.
- [ ] A payout to an **unregistered** sandbox email stays PENDING/UNCLAIMED (seen in the sandbox): use a registered
      sandbox personal account so PayPal can answer SUCCESS and the bill shows *Paid and posted*. SUCCESS to a
      registered account has not been seen yet (HONESTY.md): do one off-camera dry run first.
- [ ] Autopilot for bills stays **Off** (not in this video).

**Browser and screen**

- [ ] Chrome/Chromium, a clean profile with no extensions, bookmarks bar hidden, window 1280 × 720 CSS pixels at
      device scale 2 (records 2560 × 1440; the edit scales to 1920 × 1080), browser zoom 100 %, `en-GB`, Europe/London.
- [ ] OS notifications, chat apps and mail off (Do Not Disturb). Close every other tab.
- [ ] Nothing personal on screen: no real names, emails, phone numbers, addresses, merchant ids or account numbers.
      Signed-in account chip: use the test account and crop or blur its email in the header.
- [ ] **Blur in the edit:** the "Connected: …" merchant id in Settings › Online payments; any "Drafted by …" or
      "coded by …" byline that names a model (dispute preview in p7, purchase rows in p4); the sandbox buyer's email
      on PayPal's pages; the PayPal invoice id (`INV2-…`) if it is legible.
- [ ] Keep the demo sample history's purchase rows (named after real retailers) **off screen or blurred**: no
      third-party trade names. Only PayPal is named.
- [ ] No Settings › AI page, no model names, no Autopilot, voice or chat-app screens.

## Click paths

`demo` = `https://accnomos.com/judges` → **Start the demo** (wait about 12 s for the books). `signed-in` = the test
sign-in prepared above.

### p0 Hook (signed-in, after p4 has been filmed so DEMO-1001 is paid)
1. `/invoices`. Park the cursor beside **DEMO-1001 · …** with its **Paid** chip. Hold 3 s.
2. One-second cut-ins (taken from p4, p6 and p8 footage): the DEMO-1001 proposal card, the **Due today** card, the VAT
   boxes.

### p1 Pitch (signed-in or demo)
1. `/`: hold on Home 2 s, scroll 150 px.
2. Sidebar **Files**: hover the books folder name and `Books.xlsx`. Hold 3 s.

### p2 Invoice with a PayPal link (signed-in)
1. `/invoices`. On **DEMO-1003** click **Add payment link**.
2. Dialog *Payment link for DEMO-1003*: under **Paid into**, PayPal is selected (first). Click **Make payment link**.
   Wait for the **Payment link** field. Hover it 1.5 s. Close.
3. Click **View PDF** on DEMO-1003, scroll to the pay link line. Hold 2 s. Close.

### p3 Customer pays (hand-held, separate profile)
1. Paste DEMO-1003's link in the buyer profile. PayPal's sandbox invoice page: hover the amount.
2. Pay as the sandbox buyer (sign-in typed off camera or blurred). Hold on PayPal's confirmation 2 s.
3. Back in Accnomos, `/invoices` may show **Paid online: waiting for your approval** for DEMO-1003 at once (Invoicing
   read). Do not dwell on it: the narration moves to Sync PayPal.

### p4 Sync PayPal (signed-in, ≥ 3 h after seeding)
1. `/invoices`, scroll to the **PayPal** panel. Hover *"Every transaction waits for your approval"*.
2. Click **Sync PayPal**. Wait for the status line (*"2 new from PayPal · 3 waiting for you"* or similar).
3. Hover the DEMO-1001 card: the title line, then *PayPal fee £… · you receive £…*, then the Dr/Cr table.
4. Scroll to the sale with no invoice. Open **VAT on this sale (choose before approving)**, choose *Standard rate*.
   Do not approve it on camera (optional).
5. Scroll back to DEMO-1001 → **Approve £…**. Hold on the green note *"Invoice payment of £… (…) is in your books."*

### p5 Tie-out (signed-in, straight after p4)
1. Scroll to the top of the PayPal panel: the line *"PayPal says £… (as of …) · your books (1240 PayPal clearing) £…"*.
2. Park the cursor under the "as of" time 2 s, then under *"Difference … = waiting for your approval … + not posted …"*
   2 s. Zoom in the edit.

### p6 Pay a bill with PayPal (demo or signed-in)
1. Sidebar **Purchases** (`/purchases`), scroll to **Pay bills with PayPal**.
2. Under **Due today**, hover the supplier and amount. Click **Approve payment**.
3. Confirmation *"Pay £… to … from your PayPal account now?"*: hover it 1.5 s (blur the email), click **Pay £…**.
4. Wait for the status: *Paid and posted* (or *PayPal is processing it*; film again later on the next visit if so).
5. If deployed: the upcoming payments list → hover the next date → **Add to calendar**. Otherwise skip and cut the line.

### p7 Disputes evidence (demo)
1. `/invoices`, scroll to **PayPal disputes** (one SAMPLE dispute on the latest PayPal-linked invoice).
2. Hover the dispute's status *Waiting for your answer* and *answer by …*. Click **Build evidence**.
3. Wait for *Response for PayPal (preview)*. Scroll the text slowly (blur the byline under the heading).
4. Click **Send to PayPal (demo)**. Hold on *"Demo: recorded as sent. Nothing was sent to PayPal."*

### p8 VAT return (signed-in)
1. Sidebar **VAT** (`/vat`). Hover **Box 1**, then **Box 6** of the open period. Optional: open Box 6's explanation and
   point at the approved PayPal sale.

### p9 End card
Still card: Accnomos wordmark, `accnomos.com`, "Try the demo, no sign-in", `github.com/zaytunazs/accnomos`, "PayPal
sandbox only; no real money moved". No other logos.

## Automated capture (demo-mode scenes)

`tools/video/paypal/capture_paypal.ts` reuses the v3 capture helpers (`tools/video/lib/human.ts` cursor and pacing,
`tools/video/lib/recorder.ts` compositor recording). It drives the live site in "Try the demo" and records one WebM per
shot plus `<shot>.marks.json`; it fakes nothing: if a screen is not there (for example PayPal not configured on the
server) the shot ends with an error in its marks file.

```bash
# from a folder whose node_modules has playwright (e.g. apps/web after pnpm install)
PW_FROM=apps/web node tools/video/paypal/capture_paypal.ts docs/video/raw-paypal
PW_FROM=apps/web node tools/video/paypal/capture_paypal.ts docs/video/raw-paypal pp-disputes,pp-billpay
# PAYPAL_CONNECT=1 connects PayPal (test mode) in the demo copy first (needs PAYPAL_DIRECT=1 on the server);
# PAY=1 really presses "Pay £…" in pp-billpay (a sandbox payout); without it the shot stops at the confirmation.
```

Shots: `pp-invoice` (Add payment link → PayPal → Make payment link), `pp-sync` (Sync PayPal, choose VAT on the sale with
no invoice, approve the first invoice payment), `pp-billpay` (Due today → Approve payment → confirmation [→ Pay]),
`pp-disputes` (Build evidence → preview → Send to PayPal (demo)), `pp-vat` (Box 1, Box 6). In the demo, `pp-sync` reads
the labelled sample history unless `PAYPAL_CONNECT=1`; the tie-out appears only when connected.

## Voice-over

```bash
bash docs/submission/paypal/narration/render.sh      # on the voice-over machine, in the TTS venv; WAVs in docs/video/paypal-vo/
```
