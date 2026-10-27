# Demo video script: 3:00 and 30-second cut

Built from `docs/DEMO.md` (the 4-minute run), tightened to 3:00. Same account, same receipt, same numbers; **read DEMO.md's "Set up before you go on" first**.
Narration is plain, first person, UK English. No claim on screen or in the voice-over goes beyond what `docs/HONESTY.md` allows.

## Before you press record

- **Account:** a throwaway personal Microsoft account, signed in at `https://accnomos.com`, *Connect* done once, `00 Inbox` empty, Autopilot **L1**, VAT **Quarterly, stagger 1**.
- **Receipt:** `https://accnomos.com/sample-receipt.png` (fictional Novex Office Supplies Ltd, dated 2 Nov 2026, net £43.25 + VAT £8.65 = £51.90, stamped SAMPLE — FICTIONAL COMPANY).
- **Expected figures** (any day 1 Oct–31 Dec 2026, empty account): Box 4 **£8.65**, Box 5 **£8.65**, Box 7 **£43**, other boxes 0. If the account holds other entries in Oct–Dec, the figures differ: reset it or read the live figures.
- **Warm the model:** one dummy scan first, so the recorded scan is the 20–40 s case, not a cold load. `curl https://api.accnomos.com/health` must say `"ok": true` (DEMO.md notes the live sites were unreachable from the drafting session: check yourself).
- **Do not use the test-mode build for the video.** Its stub AI reads gold receipts only and would not read `sample-receipt.png`. The video needs the real Glimmer on the Spark.
- **Do record off camera first** and keep the take only if it works: the HMRC submit (never run end to end), Android sign-in, and any mic use (never run live). Rules for those are in the table.
- **Screen sizes:** web at **1280 × 720** (browser window, 100 % zoom, bookmarks bar hidden). Phone at **390 px** wide: either the Android emulator or Chrome DevTools device toolbar set to 390 × 844. Prefer the emulator only if you have signed in on it successfully; the Flutter app has never been analysed or tested by us (`docs/HONESTY.md`), so the 390 px PWA is the safe shot and the Android shot is a bonus.
- **Captions:** burn them in (white on dark, bottom third). Whatever you speed up must carry a visible "sped up" caption.

## 3:00 script

| Time | Shot (viewport) | Exact clicks | Voice-over | On-screen caption | If it fails |
|---|---|---|---|---|---|
| 0:00–0:14 | Web 1280. `accnomos.com` **Home** | Open the site; hover the sidebar | "Accnomos is a bookkeeper for a UK small business that owns its data. There is no Accnomos database: the books are files in your own OneDrive. AI proposes, you approve, code calculates." | `Accnomos — AI proposes · you approve · code calculates` | Site down: run locally (`docs/DEV.md`, runtime :8780, web :3000) |
| 0:14–0:26 | Web 1280. **Connect → Choose your AI** | Leave **On my own machine**, press **Test connection** | "Muse Glimmer 30B, open weights, on our DGX Spark, so this receipt never goes to Meta. Or paste your own Meta key for Muse Spark." | `Muse Glimmer 30B · open weights · here: our DGX Spark` | Unreachable: switch to **My own Meta API key**; if that fails too, cut this shot |
| 0:26–0:50 | Web 1280. **Review → Add a receipt** | Pick `sample-receipt.png`, press **Scan 00 Inbox now**. While it runs, the card shows the checks; speed the wait up in the edit | "The agent crops, reads, then code checks: arithmetic, VAT maths, VAT-number format, duplicates, and whether the date is in this VAT period." | `Real scan, about 22–40 s on local Glimmer — shown sped up` (only if sped up) | Slow: keep talking; never finishes: `/connect/ai` → **Test connection**, rescan |
| 0:50–1:15 | Web 1280. The proposal card | Point at *Read by Glimmer 30B on your machine*, the green checks, **Verifier agrees · all 6 fields match** (do not click yet) | "A second reading, with a different prompt, never saw the first answer. Code compares six fields; any mismatch would land in *Needs a look* with both values side by side." | `Second reading · code compares 6 fields` | Verifier unavailable: it shows as a warning, not a pass; say that is the design |
| 1:15–1:30 | Web 1280. Same card | Tick **Always do this for Novex Office Supplies**, press **Approve (post to books)** | "A human approves. The ledger event is immutable. Autopilot is off at this level; if I turn it on, only receipts matching a rule I saved post alone, and each has Undo." | `Approve → immutable ledger event` | Approve errors: reload Review (the proposal is saved), retry |
| 1:30–1:55 | Web 1280. **VAT return** | Show picker **Oct–Dec 2026 · current**; point at Box 4 then Box 7. Pick **Jul–Sep 2026** (zeros), switch back | "Nine boxes, worked out by plain code from the entries I approved. Box 4 is £8.65, the VAT on that receipt. Box 7 is £43, whole pounds. The model never touches a VAT number." | `Box 4 £8.65 · Box 7 £43 · calculated by code` | Different figures: other entries exist; read the live numbers |
| 1:55–2:15 | Web 1280. **VAT return → Connect to HMRC (sandbox)** | **Only if you have run this end to end off camera:** sign in as the sandbox test user, enter `vrn`, **Show obligations**, pick one, read the confirmation card, tick the declaration, **Submit to HMRC (sandbox)**. **Otherwise stop at the confirmation card** and do not press Submit | "Through our relay, which holds only HMRC's client secret and adds the fraud-prevention headers. Nothing is sent until I make the legal declaration. This is HMRC's sandbox; we do not file for real." | `HMRC SANDBOX only — not production` (add `Submission not yet run end to end` if you stop at the card) | Any error: stop at the card; do not claim a filing |
| 2:15–2:30 | Web 1280. **Ask** | Type "How much VAT have I reclaimed this quarter?" and send | "Words from the model, numbers from code. If the model quotes a figure that is not in your books, we replace the answer with the facts." | `Every figure checked against your books` | Plain facts answer is fine: that is the guard working. Do not use the mic |
| 2:30–2:50 | **Phone 390 px.** PWA (or Android debug build) on **Review**, then **VAT** | Open Review (proposals from the same folder), then VAT (nine boxes), then the camera icon *Photograph a receipt* if on Android | "Same runtime, same folder: capture, review and ask from the phone. Filing with HMRC is web only." | `Phone view · 390 px` ; add `Android debug build` if used | Android sign-in fails: use the 390 px PWA and drop the camera shot |
| 2:50–3:00 | Full screen caption card, then Home | None | "AI proposes, you approve, code calculates. Everything here is synthetic, HMRC is sandbox, and our docs list every gap." | `Synthetic data · HMRC sandbox · docs/HONESTY.md lists every gap` · `github.com/<owner>/accnomos` (fill in) | n/a |

Labels checked against `apps/web/src` and `apps/mobile/lib` on drafting. The clicks are DEMO.md's; the timings are tighter than DEMO.md's (it drops the *Files / Books.xlsx* step and the OneDrive tour to fit 3:00).
Names to match on screen exactly when you rehearse: **Scan 00 Inbox now**, **Approve (post to books)**, **Connect to HMRC (sandbox)**, **Show obligations**, **Submit to HMRC (sandbox)**. If a label has changed, fix the script, not the app.

## Shot list

| # | Capture | Size | Notes |
|---|---|---|---|
| 1 | Home, signed in (empty books, so no sample banner) | Web 1280 × 720 | Check the sidebar's "AI: local Meta agent (Glimmer 30B)" line is true for your setting: it is hard-coded (`docs/HONESTY.md`) |
| 2 | Connect → Choose your AI → Test connection | Web 1280 | Crop out any key field |
| 3 | Review → Add a receipt → scan running | Web 1280 | Record the whole scan; speed up only in the edit |
| 4 | Proposal card close-up (checks, verifier line) | Web 1280, zoom 125 % | Needed legible at 1080p |
| 5 | Approve click, ledger event | Web 1280 | Optional: show `_System/Ledger/events` in OneDrive (only if you want the "files are yours" proof) |
| 6 | VAT return, both periods | Web 1280 | Box 4 and Box 7 must be readable |
| 7 | HMRC confirmation card (and receipt if a live run worked) | Web 1280 | Never show the test user's password or the client secret |
| 8 | Ask question and answer with *Key numbers* | Web 1280 | |
| 9 | Review and VAT on the phone | **390 × 844** | Emulator or DevTools; hide the debug banner |
| 10 | End card: honesty line, repo URL | 1280 × 720 | Static, 3 s |

Do not show: tokens or keys in headers or DevTools, the sandbox test-user password, the signed-out `/vat` mock-up (it has a "Reviewer's note (Muse Spark)" that no running reviewer backs), or the mic button.

## 30-second cut

| Time | Shot | Voice-over | Caption |
|---|---|---|---|
| 0:00–0:04 | Home, web 1280 | "Accnomos: bookkeeping and VAT for UK small businesses, with the books in your own OneDrive." | `AI proposes · you approve · code calculates` |
| 0:04–0:12 | Review: scan (sped up), proposal card with the verifier line | "A Meta model reads the receipt. Code checks it. A second model reads it again, and code compares six fields." | `Muse Glimmer 30B · sped up` |
| 0:12–0:17 | Approve click | "You approve. Nothing posts before that." | `Approve → ledger event` |
| 0:17–0:23 | VAT return: Box 4 £8.65, Box 7 £43 | "The nine VAT boxes are calculated by code, never by a model." | `Calculated by code` |
| 0:23–0:27 | Phone 390 px, Review | "Same books on your phone." | `390 px` |
| 0:27–0:30 | End card | "Synthetic data, HMRC sandbox. Every gap is in our docs." | `docs/HONESTY.md lists every gap` |

Skip HMRC and Ask in the 30-second cut: less to caveat.
