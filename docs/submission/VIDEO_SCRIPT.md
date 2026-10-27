# Demo video script: 3:00 and 30-second cut

Built from `docs/DEMO.md` (the 4-minute run), tightened to 3:00. Same account, same receipt, same numbers; **read DEMO.md's "Set up before you go on" first**.
Narration is plain, first person, UK English. No claim on screen or in the voice-over goes beyond what `docs/HONESTY.md` allows.

## Before you press record

- **Account:** a throwaway personal Microsoft account, signed in at `https://accnomos.com`, *Connect* done once, `00 Inbox` empty, Autopilot **L1**, VAT **Quarterly, stagger 1**.
- **Receipt:** `https://accnomos.com/sample-receipt.png` (fictional Novex Office Supplies Ltd, dated 2 Nov 2026, net £43.25 + VAT £8.65 = £51.90, stamped SAMPLE — FICTIONAL COMPANY).
- **Expected figures** (any day 1 Oct–31 Dec 2026, empty account): Box 4 **£8.65**, Box 5 **£8.65**, Box 7 **£43**, other boxes 0. If the account holds other entries in Oct–Dec, the figures differ: reset it or read the live figures.
- **Warm the model:** one dummy scan first, so the recorded scan is the 20–40 s case, not a cold load. `curl https://api.accnomos.com/health` must say `"ok": true` (DEMO.md notes the live sites were unreachable from the drafting session: check yourself).
- **Do not record the video on the test-mode build.** Its stub AI knows a fixed set of images (the gold receipts and `sample-receipt.png`) and is not a model; the video needs the real Glimmer on the Spark.
- **The stills** in `docs/submission/shots/` are from that test-mode dry run (`pnpm run e2e:demo` in `apps/web`; 1280 × 800 and 390 × 844, PNG, each under 400 kB): use them for the storyboard, the thumbnail and caption timing, not as proof of a live run. They show the model as `accnomos-test-stub`, the test address on *Choose your AI*, no crop, and real-clock timestamps in Files and *Recent activity*.
- **Before the invoice shot:** an invoice profile with a VAT number and JM Trading Ltd imported from Outlook (DEMO.md set-up steps 3–4).
- **Do record off camera first** and keep the take only if it works: the HMRC submit (never run end to end), Android sign-in, and any mic use (never run live). Rules for those are in the table.
- **Screen sizes:** web at **1280 × 720** (browser window, 100 % zoom, bookmarks bar hidden). Phone at **390 px** wide: either the Android emulator or Chrome DevTools device toolbar set to 390 × 844. Prefer the emulator only if you have signed in on it successfully; the Flutter app has never been analysed or tested by us (`docs/HONESTY.md`), so the 390 px PWA is the safe shot and the Android shot is a bonus.
- **Captions:** burn them in (white on dark, bottom third). Whatever you speed up must carry a visible "sped up" caption.

## 3:00 script

*Still* is the dry run's frame for that moment in `docs/submission/shots/` (DEMO.md row number first; `-phone` is 390 px).

| Time | Shot (viewport) | Exact clicks | Voice-over | On-screen caption | If it fails | Still |
|---|---|---|---|---|---|---|
| 0:00–0:14 | Web 1280. `accnomos.com` **Home** | Open the site; hover the sidebar | "Accnomos is a bookkeeper for a UK small business that owns its data. There is no Accnomos database: the books are files in your own OneDrive. AI proposes, you approve, code calculates." | `Accnomos — AI proposes · you approve · code calculates` | Site down: run locally (`docs/DEV.md`, runtime :8780, web :3000) | [01-home](shots/01-home.png) |
| 0:14–0:26 | Web 1280. **Connect → Choose your AI** (*Choose how Meta AI runs your books*) | Leave **On my own machine**, press **Test connection** → *Connected · …* | "Muse Glimmer 30B, open weights, on our DGX Spark, so this receipt never goes to Meta. Or paste your own Meta key for Muse Spark." | `Muse Glimmer 30B · open weights · here: our DGX Spark` | Unreachable: switch to **My own Meta API key**; if that fails too, cut this shot | [03-choose-ai](shots/03-choose-ai.png) |
| 0:26–0:48 | Web 1280. **Review → Add a receipt** | Pick `sample-receipt.png`, press **Scan 00 Inbox now** → *1 new proposal*. Speed the wait up in the edit | "The agent crops, reads, then code checks: arithmetic, VAT maths, VAT-number format, duplicates, and whether the date is in this VAT period." | `Real scan, about 22–40 s on local Glimmer — shown sped up` (only if sped up) | Slow: keep talking; never finishes: `/connect/ai` → **Test connection**, rescan | [04-scan](shots/04-scan.png) |
| 0:48–1:08 | Web 1280. The proposal card | Point at *Read by Glimmer 30B on your machine*, the *Why: … totals add up* line, the teal *Verifier agrees · all 6 fields match — … · checks by code: 12 of 12 passed* (do not click yet) | "A second reading, with a different prompt, never saw the first answer. Code compares six fields; any mismatch would land in *Needs a look* with both values side by side." | `Second reading · code compares 6 fields` | Verifier unavailable: it shows as a warning, not a pass; say that is the design | [05-proposal](shots/05-proposal.png) |
| 1:08–1:20 | Web 1280. Same card | Tick **Always do this for Novex Office Supplies Ltd**, press **Approve (post to books)** | "A human approves. The ledger event is immutable. Autopilot is off at this level; if I turn it on, only receipts matching a rule I saved post alone, and each has Undo." | `Approve → immutable ledger event` | Approve errors: reload Review (the proposal is saved), retry | [06-approve](shots/06-approve.png) |
| 1:20–1:42 | Web 1280. **VAT return** | Show the picker's top row **Oct–Dec 2026** *current period · 1 entry*; point at Box 4 then Box 7. Pick **Jul–Sep 2026** (zeros), switch back | "Nine boxes, worked out by plain code from the entries I approved. Box 4 is £8.65, the VAT on that receipt. Box 7 is £43, whole pounds. The model never touches a VAT number." | `Box 4 £8.65 · Box 7 £43 · calculated by code` | Different figures: other entries exist; read the live numbers | [07-vat](shots/07-vat.png) |
| 1:42–2:00 | Web 1280. **VAT return → Connect to HMRC (sandbox)** | **Only if you have run this end to end off camera:** sign in as the sandbox test user, enter `vrn`, **Show obligations**, pick one, read the confirmation card, tick the declaration, **Submit to HMRC (sandbox)**. **Otherwise stop at the confirmation card** and do not press Submit | "Through our relay, which holds only HMRC's client secret and adds the fraud-prevention headers. Nothing is sent until I make the legal declaration. This is HMRC's sandbox; we do not file for real." | `HMRC SANDBOX only — not production` (add `Submission not yet run end to end` if you stop at the card) | Any error: stop at the card; do not claim a filing | none: the dry run cannot reach HMRC (DEMO.md row 8) |
| 2:00–2:12 | Web 1280. **Ask** | Type "How much VAT have I reclaimed this quarter?" and send | "Words from the model, numbers from code. If the model quotes a figure that is not in your books, we replace the answer with the facts." | `Every figure checked against your books` | Plain facts answer is fine: that is the guard working. Do not use the mic | [10-ask](shots/10-ask.png) |
| 2:12–2:32 | Web 1280. **Ask**, same thread | Type "send a £100 invoice to JM Trading"; hold on the card (*JM Trading Ltd · emailed to …*, *Due 4 December 2026*, *£120.00*), press **Approve** → *✓ Invoice INV-0001 for £120.00 sent to …* | "An instruction gets a card, not an action: code found the customer, priced it and added the VAT. Nothing goes until I approve, and it goes once." | `The model copies your words · code prices it · you approve` | *saved as a draft but not sent*: cut after the card, or send from Invoices off camera and say nothing more | [11-invoice-card](shots/11-invoice-card.png), [12-invoice-sent](shots/12-invoice-sent.png) |
| 2:32–2:50 | **Phone 390 px.** PWA (or Android debug build) on **Review**, then **VAT** | Open Review (proposals from the same folder), then VAT (nine boxes), then the camera icon *Photograph a receipt* if on Android | "Same runtime, same folder: capture, review and ask from the phone. Filing with HMRC is web only." | `Phone view · 390 px` ; add `Android debug build` if used | Android sign-in fails: use the 390 px PWA and drop the camera shot | [05-proposal-phone](shots/05-proposal-phone.png), [07-vat-phone](shots/07-vat-phone.png) |
| 2:50–3:00 | Full screen caption card, then Home | None | "AI proposes, you approve, code calculates. Everything here is synthetic, HMRC is sandbox, and our docs list every gap." | `Synthetic data · HMRC sandbox · docs/HONESTY.md lists every gap` · `github.com/<owner>/accnomos` (fill in) | n/a | [14-home-after](shots/14-home-after.png) |

Labels checked against `apps/web/src` and `apps/mobile/lib` on drafting, and the web ones again by `apps/web/e2e/demo.spec.ts`. The clicks are DEMO.md's; the timings are tighter than DEMO.md's (it drops the *Files / Books.xlsx* step and the OneDrive tour to fit 3:00).
Names to match on screen exactly when you rehearse: **Scan 00 Inbox now**, **Always do this for Novex Office Supplies Ltd**, **Approve (post to books)**, **Connect to HMRC (sandbox)**, **Show obligations**, **Submit to HMRC (sandbox)**, and on the invoice card **Approve**. If a label has changed, fix the script, not the app.

## Shot list

| # | Capture | Size | Notes | Dry-run still |
|---|---|---|---|---|
| 1 | Home, signed in (empty books, so no sample banner; *Get set up* dismissed) | Web 1280 × 720 | Check the sidebar's "AI: local Meta agent (Glimmer 30B)" line is true for your setting: it is hard-coded (`docs/HONESTY.md`) | [01-home](shots/01-home.png) · [phone](shots/01-home-phone.png) |
| 2 | Connect → Choose your AI → Test connection | Web 1280 | Crop out any key field | [03-choose-ai](shots/03-choose-ai.png) |
| 3 | Review → Add a receipt → scan running | Web 1280 | Record the whole scan; speed up only in the edit | [04-scan](shots/04-scan.png) |
| 4 | Proposal card close-up (checks, verifier line) | Web 1280, zoom 125 % | Needed legible at 1080p | [05-proposal](shots/05-proposal.png) |
| 5 | Approve click, ledger event | Web 1280 | Optional: show `_System/Ledger/events` in OneDrive (only if you want the "files are yours" proof) | [06-approve](shots/06-approve.png), [02-files](shots/02-files.png) |
| 6 | VAT return, both periods | Web 1280 | Box 4 and Box 7 must be readable | [07-vat](shots/07-vat.png) |
| 7 | HMRC confirmation card (and receipt if a live run worked) | Web 1280 | Never show the test user's password or the client secret | none (not reachable in test mode) |
| 8 | Ask question and answer with its figures and the file used | Web 1280 | | [10-ask](shots/10-ask.png) |
| 9 | Ask "send a £100 invoice to JM Trading": the card, then Approve | Web 1280 | The card must show the email address and £120.00 | [11-invoice-card](shots/11-invoice-card.png), [12-invoice-sent](shots/12-invoice-sent.png) |
| 10 | Review and VAT on the phone | **390 × 844** | Emulator or DevTools; hide the debug banner | [05-proposal-phone](shots/05-proposal-phone.png), [07-vat-phone](shots/07-vat-phone.png) |
| 11 | End card: honesty line, repo URL, over Home with the invoice owed | 1280 × 720 | Static, 3 s | [14-home-after](shots/14-home-after.png) |

Do not show: tokens or keys in headers or DevTools, the sandbox test-user password, the signed-out `/vat` mock-up (it has a "Reviewer's note (Muse Spark)" that no running reviewer backs), or the mic button.

## 30-second cut

| Time | Shot | Voice-over | Caption | Still |
|---|---|---|---|---|
| 0:00–0:04 | Home, web 1280 | "Accnomos: bookkeeping and VAT for UK small businesses, with the books in your own OneDrive." | `AI proposes · you approve · code calculates` | [01-home](shots/01-home.png) |
| 0:04–0:12 | Review: scan (sped up), proposal card with the verifier line | "A Meta model reads the receipt. Code checks it. A second reading with a different prompt, and code compares six fields." | `Muse Glimmer 30B · sped up` | [04-scan](shots/04-scan.png), [05-proposal](shots/05-proposal.png) |
| 0:12–0:17 | Approve click | "You approve. Nothing posts before that." | `Approve → ledger event` | [06-approve](shots/06-approve.png) |
| 0:17–0:23 | VAT return: Box 4 £8.65, Box 7 £43 | "The nine VAT boxes are calculated by code, never by a model." | `Calculated by code` | [07-vat](shots/07-vat.png) |
| 0:23–0:27 | Phone 390 px, Review | "Same books on your phone." | `390 px` | [05-proposal-phone](shots/05-proposal-phone.png) |
| 0:27–0:30 | End card | "Synthetic data, HMRC sandbox. Every gap is in our docs." | `docs/HONESTY.md lists every gap` | [14-home-after](shots/14-home-after.png) |

Skip HMRC, Ask and the invoice in the 30-second cut: less to caveat.
