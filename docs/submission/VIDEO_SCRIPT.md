# Demo video script: 3:00 and 30-second cut

Refreshed 27 Oct 2026 for the features added since the first draft (payments and credit notes, bank rules, reports, audit trail, Autopilot numbers, Android 0.3.2+5, Spark Open verifier). **Anything marked "film only if checked" has only been run on fakes or by test mode: run it yourself on the real account first, and cut the shot if it fails.** The dry-run stills in `shots/` predate those features, so the new rows have no still.

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
- **Muse Spark Open:** on 27 Oct a real call through the verifier code read a gold receipt in 7 s, and the key-mode Verifier is wired to it. The demo account uses local mode, where the verifier is Glimmer. Do not say the verifier on screen is Spark Open unless the account is in key mode and the server's `BASETEN_API_KEY` is set. The 200-receipt Spark Open eval has run (all fields 91 % clean, 93 % messy; `evals/runs/spark_open_200`, `spark_open_messy_200`; table in `META_MODELS.md`); quote it as synthetic documents, key-mode verifier only.
- **Do record off camera first** and keep the take only if it works: the HMRC submit (the owner has connected once; no end-to-end sandbox submission is recorded), Android sign-in, *Add from phone*, and any mic use (never run live). Rules for those are in the table.
- **Screen sizes:** web at **1280 × 720** (browser window, 100 % zoom, bookmarks bar hidden). Phone at **390 px** wide: either the Android emulator or Chrome DevTools device toolbar set to 390 × 844. Prefer the emulator or a phone only if you have signed in on it successfully: the Play app-signing hash was registered in Entra on 27 Oct and builds from 0.3.1+4 carry it, but no real-phone sign-in is recorded, so the 390 px PWA is the safe shot and the Android shot is a bonus (`flutter analyze` and `flutter test`, 248 tests, pass at the 28 Oct gate; nothing has run on a device).
- **Captions:** burn them in (white on dark, bottom third). Whatever you speed up must carry a visible "sped up" caption.

## 3:00 script

*Still* is the dry run's frame for that moment in `docs/submission/shots/` (DEMO.md row number first; `-phone` is 390 px).

| Time | Shot (viewport) | Exact clicks | Voice-over | On-screen caption | If it fails | Still |
|---|---|---|---|---|---|---|
| 0:00–0:11 | Web 1280. `accnomos.com` **Home** | Open the site; hover the sidebar | "Accnomos is a bookkeeper for a UK small business that owns its data. There is no Accnomos database: the books are files in your own OneDrive. AI proposes, you approve, code calculates." | `Accnomos — AI proposes · you approve · code calculates` | Site down: run locally (`docs/DEV.md`, runtime :8780, web :3000) | [01-home](shots/01-home.png) |
| 0:11–0:22 | Web 1280. **Connect → Choose your AI** | Leave **On my own machine**, press **Test connection** → *Connected · …* | "Muse Glimmer 30B, open weights, on our DGX Spark, so this receipt never goes to Meta. Or paste your own Meta key for Muse Spark; in key mode the second reader is Muse Spark Open on Baseten." | `Muse Glimmer 30B · open weights · here: our DGX Spark` | Unreachable: switch to **My own Meta API key**; if that fails too, cut this shot and drop the Baseten sentence | [03-choose-ai](shots/03-choose-ai.png) |
| 0:22–0:40 | Web 1280. **Review → Add a receipt** | Pick `sample-receipt.png`, press **Scan 00 Inbox now** → *1 new proposal*. Speed the wait up in the edit | "The agent crops, reads, then code checks: arithmetic, VAT maths, VAT-number format, duplicates, and whether the date is in this VAT period." | `Real scan, about 22–40 s on local Glimmer — shown sped up` (only if sped up) | Slow: keep talking; never finishes: `/connect/ai` → **Test connection**, rescan | [04-scan](shots/04-scan.png) |
| 0:40–0:56 | Web 1280. The proposal card | Point at *Read by Glimmer 30B on your machine*, the *Why: … totals add up* line, the teal *Verifier agrees · all 6 fields match — … · checks by code: 12 of 12 passed* | "A second reading, with a different prompt, never saw the first answer. Code compares six fields; any mismatch lands in *Needs a look* with both values side by side." | `Second reading · code compares 6 fields` | Verifier unavailable: it shows as a warning, not a pass; say that is the design | [05-proposal](shots/05-proposal.png) |
| 0:56–1:08 | Web 1280. Same card | Tick **Always do this for Novex Office Supplies Ltd**, press **Approve (post to books)** | "A human approves. The ledger event is immutable. Autopilot is off at this level; at L2 only receipts matching a rule I saved post alone, and each has Undo." | `Approve → immutable ledger event` | Approve errors: reload Review (the proposal is saved), retry | [06-approve](shots/06-approve.png) |
| 1:08–1:22 | Web 1280. **VAT return** | Show the picker's top row **Oct–Dec 2026** *current period · 1 entry*; point at Box 4 then Box 7 | "Nine boxes, worked out by plain code from the entries I approved. Box 4 is £8.65, the VAT on that receipt. Box 7 is £43, whole pounds. The model never touches a VAT number." | `Box 4 £8.65 · Box 7 £43 · calculated by code` | Different figures: other entries exist; read the live numbers | [07-vat](shots/07-vat.png) |
| 1:22–1:34 | Web 1280. **VAT return → Connect to HMRC (sandbox)** | **Only if you have run the full flow off camera and it worked:** sign in as the test user, enter `vrn`, **Show obligations**, pick one, tick the declaration, **Submit to HMRC (sandbox)**. **Otherwise stop at the confirmation card** and do not press Submit | "Through our relay, which holds only HMRC's client secret. Nothing is sent until I make the legal declaration. This is HMRC's sandbox; we do not file for real." | `HMRC SANDBOX only — not production` (add `Submission not yet run end to end` if you stop at the card) | Any error: stop at the card; do not claim a filing | none |
| 1:34–1:54 | Web 1280. **Ask** | Type "send a £100 invoice to JM Trading"; hold on the card (*JM Trading Ltd · emailed to …*, *Due 4 December 2026*, *£120.00*), press **Approve** → *✓ Invoice INV-0001 for £120.00 sent to …* | "An instruction gets a card, not an action: code found the customer, priced it and added the VAT. Nothing goes until I approve, and it goes once. Typed or, in key mode, spoken." | `The model copies your words · code prices it · you approve` | *saved as a draft but not sent*: cut after the card. Do not use the mic | [11-invoice-card](shots/11-invoice-card.png), [12-invoice-sent](shots/12-invoice-sent.png) |
| 1:54–2:12 | Web 1280. **Invoices** **(film only if checked)** | Open INV-0001; **Record payment** for part of £120.00 → *part paid* with the balance; then **Create credit note** for one line → CN-0001 | "Part payments, overpayments and credit notes are code too: a credit note is a reversal with the same VAT codes, so the VAT boxes net off in its period." | `Part payment · credit note · VAT nets off by code` | Cut the shot. Tested on fakes only (`invoice-payments.spec.ts`); never run on a real OneDrive | none (new) |
| 2:12–2:26 | Web 1280. **Bank → Rules / Reconcile** **(film only if checked)** | Drop `evals/gold/bank/barclays.csv`; **Reconcile** tab: an exact match to an open invoice, a rule match, then **Create rule from this** | "Bank rules, first match wins, then reconciliation. Any coding the model suggests is labelled *suggested by AI* and posts only when I approve." | `Bank rules · reconcile · approve to post` | Cut the shot. The AI coding has run only on the test stub; layouts are public formats, not real exports | none (new) |
| 2:26–2:38 | Web 1280. **Reports**, then **Audit trail** **(film only if checked)** | **Reports**: profit and loss for the period, then **Export to OneDrive**; **Audit trail** (*More*): filter *You* / *Autopilot* | "Profit and loss, ageing, VAT and a trend, all from the ledger, no model. And every action, by who did it, in one audit trail." | `Reports by code · every action audited` | Cut the shot; the signed-out pages show a labelled sample | none (new) |
| 2:38–2:50 | Text card of `evals/runs/autopilot_l2/report.md` headline, then **phone 390 px** (PWA, or Android 0.3.2+5 only if you signed in) | Show the headline table, then the phone's Review | "Autopilot, measured on Glimmer over 467 synthetic documents: no false posts on 154 clean ones, 17 overall, all re-dated copies of posted receipts. The same books on the phone." | `Autopilot L2 eval: 0/154 clean · 17/467 overall (re-dated copies) · synthetic` ; `Phone view · 390 px` | Android sign-in fails: use the 390 px PWA and drop the Android caption | [05-proposal-phone](shots/05-proposal-phone.png) |
| 2:50–3:00 | Full screen caption card, then Home | None | "AI proposes, you approve, code calculates. Everything here is synthetic, HMRC is sandbox, and our docs list every gap." | `Synthetic data · HMRC sandbox · docs/HONESTY.md lists every gap` · `github.com/<owner>/accnomos` (fill in) | n/a | [14-home-after](shots/14-home-after.png) |

Labels checked against `apps/web/src` on 27 Oct (*Record payment*, *Create credit note*, *Rules*, *Reconcile*, *Create rule from this*, *Export to OneDrive*, *Audit trail*, *Reports*); the core-path labels are also checked by `apps/web/e2e/demo.spec.ts`. The new rows are covered by other e2e specs (`invoice-payments`, `bank-rules`, `reports`, `audit`) on fakes, not by the demo spec.
Names to match on screen exactly when you rehearse: **Scan 00 Inbox now**, **Always do this for Novex Office Supplies Ltd**, **Approve (post to books)**, **Connect to HMRC (sandbox)**, **Show obligations**, **Submit to HMRC (sandbox)**, and on the invoice card **Approve**. If a label has changed, fix the script, not the app.
Tight on time: if the cut runs over 3:00, drop Bank first, then Reports/Audit. Do not drop the Autopilot caption or the HMRC-sandbox caption.

## Shot list

| # | Capture | Size | Notes | Dry-run still |
|---|---|---|---|---|
| 1 | Home, signed in (empty books, so no sample banner; *Get set up* dismissed) | Web 1280 × 720 | Check the sidebar's "AI: local Meta agent (Glimmer 30B)" line is true for your setting: it is hard-coded (`docs/HONESTY.md`) | [01-home](shots/01-home.png) · [phone](shots/01-home-phone.png) |
| 2 | Connect → Choose your AI → Test connection | Web 1280 | Crop out any key field | [03-choose-ai](shots/03-choose-ai.png) |
| 3 | Review → Add a receipt → scan running | Web 1280 | Record the whole scan; speed up only in the edit | [04-scan](shots/04-scan.png) |
| 4 | Proposal card close-up (checks, verifier line) | Web 1280, zoom 125 % | Needed legible at 1080p | [05-proposal](shots/05-proposal.png) |
| 5 | Approve click, ledger event | Web 1280 | Optional: show `_System/Ledger/events` in OneDrive (only if you want the "files are yours" proof) | [06-approve](shots/06-approve.png), [02-files](shots/02-files.png) |
| 6 | VAT return, both periods | Web 1280 | Box 4 and Box 7 must be readable | [07-vat](shots/07-vat.png) |
| 7 | HMRC confirmation card (and receipt only if a full sandbox run worked) | Web 1280 | Never show the test user's password or the client secret | none (not reachable in test mode) |
| 8 | Ask question and answer with its figures and the file used | Web 1280 | | [10-ask](shots/10-ask.png) |
| 9 | Ask "send a £100 invoice to JM Trading": the card, then Approve | Web 1280 | The card must show the email address and £120.00 | [11-invoice-card](shots/11-invoice-card.png), [12-invoice-sent](shots/12-invoice-sent.png) |
| 10 | Review and VAT on the phone | **390 × 844** | Emulator or DevTools; hide the debug banner. Android 0.3.2+5 only if a sign-in worked | [05-proposal-phone](shots/05-proposal-phone.png), [07-vat-phone](shots/07-vat-phone.png) |
| 10a | **Film only if checked.** Invoices: Record payment (part), Create credit note | Web 1280 | Fakes-tested only | none |
| 10b | **Film only if checked.** Bank: Reconcile tab, Create rule from this | Web 1280 | Fakes-tested only; use `evals/gold/bank/barclays.csv` | none |
| 10c | **Film only if checked.** Reports (Export to OneDrive) and Audit trail | Web 1280 | Fakes-tested only | none |
| 10d | Autopilot eval headline (text card) | 1280 × 720 | Screenshot of `evals/runs/autopilot_l2/report.md` headline; keep the caveat caption | none |
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
