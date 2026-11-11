# PayPal AI Hackathon: demo video script (v2, 11 Nov 2026)

Planned length **2:48** (hard limit 2:50; the rules allow under 3:00). Three parts:

1. **PRESENTER intro**, 10 s: the founder, first person, either on camera or a clearly labelled AI presenter (the
   owner decides).
2. **PayPal hero scenes**, 1:45: what small businesses want most and other bookkeeping apps don't do. The AI fetches
   PayPal's own data and explains it, code does the sums, the owner approves.
3. **Montage**, 45 s: the rest of the app, 2–4 s a shot with captions, so judges see the full range. Then the
   **PRESENTER outro**, 8 s.

Narration: 328 words, about 2:11 of speech at 150 words a minute. Voice: female, British, `bf_emma`, through the
existing voice-over tool (`docs/submission/paypal/narration/render.sh`). Click paths, the checklist and the blur list
are in [`SHOT_LIST.md`](SHOT_LIST.md).

**Pitch (kept to throughout):** Accnomos keeps a UK small business's books in its own OneDrive or Google Drive and files
VAT to HMRC; PayPal is where it gets paid and pays its bills.

**Rules this script follows**

- Under 3 minutes, public on YouTube, shown working on the devices it was built for: the web app in a desktop browser,
  plus the Android app in the montage. The Android app has no PayPal screens, so the hero scenes are all on the web.
- PayPal is central: every hero scene is a PayPal API call or its result in the books.
- No third-party logos and no music unless it is original or licensed. PayPal is named as the sponsor. The demo's
  PayPal sample history uses fictional suppliers.
- Fictional data only. Sandbox only, and the video says so (captions and outro).
- No model names, no Settings › AI page, no model bylines on screen (blur them, see SHOT_LIST.md). The AI is "the AI".
- Every claim is one `docs/HONESTY.md` allows. Where it matters: "How much is in PayPal?" is answered from the books'
  PayPal account (filled by Sync PayPal), and the tie-out is what reads PayPal's live balance. The narration says
  exactly that.

## Scenes

"Narration" is spoken and captioned word for word (spoken-only spellings are under `say` in `narration/lines.json`).

| # | Time | Screen / route | Action | Narration | On-screen caption |
|---|---|---|---|---|---|
| i0 **PRESENTER** | 0:00–0:10 | AI presenter, labelled "AI presenter — generated" on screen for the whole slot | Speaks to camera; Accnomos wordmark lower third | Hi, I'm an AI presenter. Accnomos was built by a UK business owner who gets paid, and pays suppliers, through PayPal. Here's how it keeps the books. | **Accnomos × PayPal** · AI bookkeeping and VAT for UK small businesses |
| h1 | 0:10–0:38 | 2 s on `/files` (books folder in the owner's drive), then `/invoices` → **PayPal** panel → **Sync PayPal** → proposal cards (signed-in sandbox books) | Click Sync; status line *"N new from PayPal · N waiting for you"*; hover the DEMO-1002 card (title, *PayPal fee £… · you receive £…*, Dr/Cr lines); scroll to the sale with no invoice → **VAT on this sale (choose before approving)** → *Standard rate*; back to DEMO-1002 → **Approve £…** → green note | Accnomos keeps the books in your own OneDrive or Google Drive, and files VAT to HMRC. Press Sync PayPal, and it fetches every payment from PayPal itself: the gross, PayPal's fee and the net, matched to the invoice it pays. A sale with no invoice waits for me to choose its VAT. Nothing posts until I approve. | PayPal Transaction Search · gross / fee / net matched to the invoice · nothing posts without your approval |
| h2 | 0:38–0:56 | `/ask` | Type *What did PayPal cost me this quarter?* → answer with the figure; then *How much is in PayPal?* → answer. Blur the model byline under each answer | Then I just ask. What did PayPal cost me this quarter? How much is in PayPal? The answers come from those PayPal entries, worked out by code to the penny, and explained in plain English. | Figures by code from the PayPal entries in your books |
| h3 | 0:56–1:06 | `/invoices`, top of the PayPal panel: *"PayPal says £… (as of 11 Nov, 19:05) · your books (1240 PayPal clearing) £…"* and *"Difference … = waiting for your approval … + not posted …"* | Zoom (edit) on the line; cursor under the "as of" time | And the tie-out checks the books against PayPal's own balance, shows when PayPal last refreshed it, and explains any difference. | PayPal Balances API · PayPal's figure as of its last refresh (it can lag up to 3 h) |
| h4 | 1:06–1:32 | `/purchases` → **Pay bills with PayPal** → **Due today** (fictional supplier, registered sandbox payee) → **Approve payment** → *"Pay £… to … from your PayPal account now?"* → **Pay £…** → *PayPal is processing it* → *Paid and posted* | Approve and pay; hold through the status change (about 30 s, sped up in the edit and marked "sped up") | Paying a supplier works the other way. When a bill falls due, Accnomos offers to pay it by PayPal payout. I approve, PayPal confirms in about half a minute, and only then does it post. A retry can never pay twice. PayPal can't date a payout ahead, so it goes on the due date, when the app is open. | PayPal Payouts API · SUCCESS before it posts · same batch id on a retry, so never paid twice |
| h5 | 1:32–1:48 | `/invoices` → **PayPal disputes** (the demo's SAMPLE dispute) → **Build evidence** → *Response for PayPal (preview)* → **Send to PayPal (demo)** | Build; scroll the preview (invoice number, amounts, dates); blur the byline; Send (demo) | If a customer opens a dispute, Accnomos builds the evidence pack from the books, checks every figure by code, and waits for me to read it before anything goes to PayPal. | PayPal Disputes API · SAMPLE dispute in the demo: nothing sent to PayPal |
| h6 | 1:48–1:55 | Title card over a blurred Invoices page | Three lines appear one by one | The AI fetches and explains. Code calculates. I approve. | **The AI fetches and explains · Code calculates · You approve** |
| m1 | 1:55–2:40 | Montage, 15 shots of about 3 s each (list below) | Cut to the narration's beats | And PayPal sits inside a full set of books. Scan a receipt and approve it. Match the bank. Send invoices and quotes. Work out VAT and file it to HMRC's sandbox. Run reports. Ask by typing or by voice. Track jobs, mileage and payroll estimates. Plan the day around your calendar. Keep your contacts. The books stay in your own drive, on the web and on Android, with guides built in, and upcoming PayPal payments go straight into your calendar. | One caption per shot (list below) |
| o0 **PRESENTER** | 2:40–2:48 | Founder to camera (or the labelled AI presenter); end card behind or after: `accnomos.com` · github.com/zaytunazs/accnomos | Speaks; end card holds | Everything you saw runs on PayPal's sandbox. Try it yourself at accnomos.com, no sign-in needed. | **accnomos.com** · Try the demo, no sign-in · github.com/zaytunazs/accnomos · PayPal sandbox; no real money moved |

### Montage shots (m1)

Only screens that exist on `paypal-wave3` or a branch named here; each is in "Try the demo" unless marked.

| # | Time | Route | Shot | Caption |
|---|---|---|---|---|
| 1 | 1:55 | `/review` | **Add a receipt** → proposal card → **Approve** | Receipt read by AI, checked by code, approved by you |
| 2 | 1:58 | `/bank` | Bank lines matched (the Bank feed card in view) | Bank feed and matching |
| 3 | 2:01 | `/invoices` → `/sales/quotes` | Invoice list, then a quote | Invoices and quotes |
| 4 | 2:04 | `/vat` | The nine boxes | VAT return worked out from the ledger |
| 5 | 2:07 | `/vat` → HMRC sandbox → receipt | HMRC's sandbox receipt (password blurred) | Filed to HMRC's sandbox |
| 6 | 2:10 | `/reports/profit-and-loss` | Profit and loss | Reports and exports |
| 7 | 2:13 | `/ask` and **Talk to Accnomos** | A typed question, then the voice button (byline blurred) | Ask by typing or by voice |
| 8 | 2:16 | `/jobs` | A job with its costs | Jobs |
| 9 | 2:19 | `/vehicles` | Mileage log | Mileage |
| 10 | 2:22 | `/payroll` | Pay run estimate | Payroll estimates |
| 11 | 2:25 | `/calendar`, then Home **Plan today** (signed-in) | Calendar, then the proposed day | Calendar and day plan |
| 12 | 2:28 | `/contacts` | Contact with its statement | Contacts |
| 13 | 2:31 | `/files` (signed-in) | The books folder and `Books.xlsx` | Your books in your own OneDrive or Google Drive |
| 14 | 2:34 | Android phone (APK, **Try the company demo**) | Home, then Review | Android app |
| 15 | 2:37 | `/purchases` → **Upcoming PayPal payments** → **Calendar** / **Download all (.ics)**; or `/help` | The schedule and the calendar button; else the help page | Upcoming PayPal payments in your calendar · Help and guides |

Shot 15 depends on the upcoming-payments work (`billpay-schedule`, commit `3dfb7b39`) being merged and deployed. If it
is not, show `/help` and cut "and upcoming PayPal payments go straight into your calendar" from m1. A support desk
(help centre and tickets, branch `support-desk`) can replace `/help` only if it is deployed.

## Timing check

| Part | Lines | Words | Speech at 150 wpm | Slot |
|---|---|---|---|---|
| PRESENTER intro | i0 | 22 | 8.8 s | 10 s |
| Hero | h1–h6 | 211 | 1:24 | 1:45 |
| Montage | m1 | 80 | 32 s | 45 s |
| PRESENTER outro | o0 | 15 | 6.0 s | 8 s |
| **Total** | | **328** | **2:11** | **2:48** |

If the cut runs long, trim in this order: the calendar clause in m1, shot 5 (HMRC receipt) into shot 4, the `/files`
lead-in to h1.

## Upload

- YouTube, **Public**. Title: "Accnomos: PayPal-powered bookkeeping and VAT for UK small businesses (PayPal AI
  Hackathon)". Description: the pitch sentence, `https://accnomos.com`, `https://github.com/zaytunazs/accnomos`,
  "Recorded against PayPal's sandbox; no real money moved." If the presenter is AI-generated, say so in the
  description too.
- Captions: upload the narration (`narration/lines.json`, the `text` fields) as the caption track.
- Check YouTube shows no Content ID claims before the link goes on Devpost.
