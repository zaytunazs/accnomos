# PayPal AI Hackathon: demo video script (v4, 12 Nov 2026)

Planned length **2:47** (hard limit 2:50; the rules allow under 3:00). The judging criteria (Technological
Implementation, Design, Potential Impact, Innovation, Presentation) carry equal weight, and Devpost's advice is to open
with the problem and who it is for, show PayPal and AI end to end, and cut loading and set-up. The video follows that:

1. **PRESENTER intro** (11 s): a labelled **AI presenter**. It never claims to be the founder.
2. **Problem card** (6 s): the problem and who it is for, on screen and spoken.
3. **PayPal hero** (1:41): how it works (card), Sync PayPal, the Power grid (AG Grid), Ask about PayPal, the tie-out,
   paying a bill by payout, dispute evidence.
4. **AI in action** slide (6 s): six real screenshots of the AI at work, each saying what the AI did and what code or
   the owner did.
5. **Montage** (30 s): 10 shots of 3 s each, captions burned in.
6. **Everything in Accnomos** slide (5 s): every feature, grouped.
7. **PRESENTER outro** (8 s).

Narration is 346 words, about 2:18 of speech at 150 words a minute. The voice is female and British (`bf_emma`, through
`docs/submission/paypal/narration/render.sh`). The voice-over says "you" and "the owner", never "I", so no line sounds
like the founder speaking. Cards and slides are in [`cards/`](cards/) (`problem.svg`, `how-it-works.svg`, `ai-in-action.png`,
`features.png`); click paths, the checklist and the blur list are in
[`SHOT_LIST.md`](SHOT_LIST.md); upload settings are in [`UPLOAD.md`](UPLOAD.md).

**Pitch:** Accnomos keeps a UK small business's books in its own OneDrive or Google Drive and files VAT to HMRC; PayPal
is where it gets paid and pays its bills.

**Rules this script follows**

- Under 3 minutes and public on YouTube. It shows the project working on the web (desktop browser) and the Android app
  (montage). The hero scenes are all on the web, because the Android app has no PayPal screens.
- PayPal is central: every hero scene is a PayPal API call or its result in the books.
- No third-party logos. PayPal is named as the sponsor, in text only. AG Grid is named in a caption, as a sponsor tool.
  Music comes from YouTube's Audio Library with "Attribution not required" (see Music below).
- Fictional data and sandbox only, said on screen.
- No model names, no Settings › AI, no model bylines on screen (blur them).
- Every claim is one `docs/HONESTY.md` allows. "How much is in PayPal?" is answered from the books' PayPal account
  (which Sync PayPal fills); the tie-out is the screen that reads PayPal's own balance.

## Scenes

"Narration" is spoken and captioned word for word (spoken-only spellings are under `say` in `narration/lines.json`).

| # | Time | Screen / route | Action | Narration | On-screen caption |
|---|---|---|---|---|---|
| i0 **PRESENTER** | 0:00–0:11 | AI presenter, labelled **"AI presenter"** on screen for the whole slot | Speaks to camera; Accnomos wordmark lower third | Hi, I'm an AI presenter. Accnomos was built by a UK business owner who gets paid, and pays suppliers, through PayPal. Here's how it keeps the books. | **AI presenter** · Accnomos × PayPal |
| pr | 0:11–0:17 | Card `cards/problem.svg` | Static; the headline fades in | Small businesses paid through PayPal still match the fees and the VAT by hand. | (the card: "UK small businesses paid through PayPal still reconcile PayPal fees and VAT by hand.") |
| hw | 0:17–0:24 | Card `cards/how-it-works.svg` | Boxes build left to right, one a second | PayPal's data comes in, the AI proposes, code calculates to the penny, and the owner approves. | (the card) |
| h1 | 0:24–0:44 | `/invoices` → **PayPal** panel → **Sync PayPal** → proposal cards (signed-in sandbox books) | Sync; status line; hover the DEMO-1002 card (*PayPal fee £… · you receive £…*, Dr/Cr lines); the sale with no invoice → **VAT on this sale (choose before approving)** → *Standard rate*; DEMO-1002 → **Approve £…** | Press Sync PayPal, and Accnomos fetches every payment from PayPal itself: the gross, PayPal's fee and the net, matched to the invoice it pays. A sale with no invoice waits for you to choose its VAT. Nothing posts until you approve. | PayPal Transaction Search · gross / fee / net matched to the invoice · nothing posts without your approval |
| ag | 0:44–0:56 | Power grid on (Settings › Business › **Power grid** › *Use the power grid*, set off camera). `/invoices` PayPal panel as **PayPal review grid** → tick rows → **Approve selected (3)** → *Total of N shown (GBP)*; cut to `/reports/ledger-grid` → **Show me…** *PayPal fees over £5* → **Filter** | Tick three waiting rows, the totals row, approve; then type the filter and show the filtered grid | Turn on the Power grid, and you can tick several PayPal rows and approve them together, with totals. Or just type: PayPal fees over five pounds. | **AG Grid Community** · Power grid: bulk approve, totals, plain-English filters (filters never change the books) |
| h2 | 0:56–1:10 | `/ask` | *What did PayPal cost me this quarter?* → figure; *How much is in PayPal?* → figure. Blur bylines | Then just ask: what did PayPal cost me this quarter? How much is in PayPal? Code works out the figure from those PayPal entries, and the AI explains it. | Figures by code from the PayPal entries in your books |
| h3 | 1:10–1:20 | `/invoices`, top of the PayPal panel: *"PayPal says £… (as of …) · your books (1240 PayPal clearing) £…"* and the *Difference …* line | Zoom (edit); cursor under the "as of" time | The tie-out checks the books against PayPal's own balance, shows when PayPal last refreshed it, and explains any difference. | PayPal Balances API · PayPal's figure as of its last refresh (it can lag up to 3 h) |
| h4 | 1:20–1:44 | `/purchases` → **Pay bills with PayPal** → **Due today** → **Approve payment** → **Pay £…** → *PayPal is processing it* → *Paid and posted* | Approve and pay; the wait is sped up and captioned "sped up" | Paying a supplier works the other way. When a bill falls due, Accnomos offers a PayPal payout. You approve, PayPal confirms in about half a minute, and only then does it post. A retry never pays twice. PayPal can't date a payout ahead, so it goes on the due date, when the app is open. | PayPal Payouts API · posts only on SUCCESS · same batch id on a retry, so never paid twice |
| h5 | 1:44–1:58 | `/invoices` → **PayPal disputes** (demo SAMPLE dispute) → **Build evidence** → preview → **Send to PayPal (demo)** | Build; scroll the preview; blur the byline; Send (demo) | If a customer opens a dispute, Accnomos builds the evidence pack from the books, checks every figure by code, and waits for you to read it before anything goes to PayPal. | PayPal Disputes API · SAMPLE dispute in the demo: nothing sent to PayPal |
| ai | 1:58–2:04 | Slide `cards/ai-in-action.png` | Static; slow 3 % zoom | Everywhere in Accnomos, the AI proposes, code checks the figures, and you approve. | (the slide: six screenshots with captions; footer "The AI proposes · code calculates in pence · you approve") |
| m1 | 2:04–2:34 | Montage, 10 shots of 3 s (below) | Cut on the narration's beats | And PayPal sits inside a full set of books, kept in your own OneDrive or Google Drive. Scan receipts, match the bank, and file VAT to HMRC's sandbox. Reports, voice, jobs and payroll, on the web and Android, with upcoming PayPal payments in your calendar and help when you need it. | One caption per shot, burned in |
| fl | 2:34–2:39 | Slide `cards/features.png` | Static | And that's everything Accnomos does today, in one app. | (the slide) |
| o0 **PRESENTER** | 2:39–2:47 | AI presenter (labelled); end card behind: `accnomos.com` · github.com/zaytunazs/accnomos | Speaks; end card holds | Everything you saw runs on PayPal's sandbox. Try it yourself at accnomos.com, no sign-in needed. | **accnomos.com** · Try the demo, no sign-in · github.com/zaytunazs/accnomos · PayPal sandbox; no real money moved |

### Why the AI slide sits before the montage

The AI slide goes after the PayPal hero, just before the montage, not after the how-it-works card. Devpost's advice is to
show PayPal working early, and the hero scenes already start late at 0:24. Another 6 s there would push the first
PayPal screen past 0:30. Placed here, the slide sums up the AI the judges have just watched in the PayPal scenes, then
opens onto the rest of the app: three of its six tiles (receipts, the calendar card, the support assistant) belong to
features the montage goes on to show.

### Montage shots (m1): 10 × 3 s, captions burned in

| # | Time | Route | Shot | Caption |
|---|---|---|---|---|
| 1 | 2:04 | `/files` (signed-in) | The books folder and `Books.xlsx` | Your books, in your own OneDrive or Google Drive |
| 2 | 2:07 | `/review` | Receipt proposal card → **Approve** | Receipts read by AI, checked by code |
| 3 | 2:10 | `/bank` | Bank feed card and matched lines | Bank feed and matching |
| 4 | 2:13 | `/vat` → HMRC sandbox receipt | Nine boxes, then HMRC's sandbox receipt (password blurred) | VAT filed to HMRC (sandbox) |
| 5 | 2:16 | `/reports/profit-and-loss` | Profit and loss | Reports |
| 6 | 2:19 | **Talk to Accnomos** | The voice button and a spoken question's card | Ask by voice |
| 7 | 2:22 | `/jobs` | A job with its costs | Jobs |
| 8 | 2:25 | `/payroll` | Pay run estimate | Payroll estimates |
| 9 | 2:28 | Android phone (APK, **Try the company demo**) | Home, then Review | Android app |
| 10 | 2:31 | `/purchases` **Upcoming PayPal payments** → **Calendar**; last second: `/support` | The schedule and the calendar button; the help centre | Upcoming PayPal payments in your calendar · Help centre |

Dropped in v4: quotes (invoices are already in the hero, and the features slide lists quotes) and Plan today (it needs
the signed-in calendar, and the AI slide already shows a calendar card). Dropped in v3: invoices list, mileage,
contacts, typed Ask, `/help`. Captions: white text on a dark band, bottom left, at least 44 px at 1080p, on screen for
the whole 3 s.

## Music

A YouTube Audio Library track whose licence is **"Attribution not required"**. In YouTube Studio › Audio Library ›
Free music, filter *Attribution: Not required*. Pick a calm instrumental (*Genre: Ambient* or *Cinematic*; *Mood: Calm*
or *Inspirational*), about 3 minutes long so it needs no loop. Download it and note its title in `UPLOAD.md`. Mix it at
about −28 dB under the voice (−20 dB under the cards with no voice), with a 1 s fade in and a 2 s fade out. Don't use
music from anywhere else. After uploading, check YouTube Studio shows no copyright claim.

## Timing check

| Part | Lines | Words | Speech at 150 wpm | Slot |
|---|---|---|---|---|
| PRESENTER intro | i0 | 27 | 10.8 s | 11 s |
| Problem and how it works | pr, hw | 30 | 12.0 s | 13 s |
| PayPal hero | h1, ag, h2, h3, h4, h5 | 201 | 1:20 | 1:34 |
| AI in action | ai | 13 | 5.2 s | 6 s |
| Montage | m1 | 51 | 20.4 s | 30 s |
| Everything in Accnomos | fl | 9 | 3.6 s | 5 s |
| PRESENTER outro | o0 | 15 | 6.0 s | 8 s |
| **Total** | | **346** | **2:18** | **2:47** |

There are 3 s of headroom under 2:50. If the cut runs long, trim in this order: montage shot 10's help-centre second,
the ledger-explorer half of `ag`, montage shot 1.
