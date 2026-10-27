# Four-minute demo

**Pitch in one line:** *AI proposes, you approve, code calculates. Your books live in your own OneDrive.*

**Who is signed in:** a throwaway **personal Microsoft account** (not anyone's real books) with OneDrive opened once, on the
laptop's browser at `https://accnomos.com`. HMRC is a separate sandbox **test user** (`POST /hmrc/test-user` on the relay gives
`userId`, `password`, `vrn`; keep them on a card). On the phone, the **debug build**, signed in with the same Microsoft account
(a release build's signing hash is not registered with Microsoft, see `docs/HONESTY.md`).
**Sample business:** Bramblewood Joinery Ltd, fictional, shown only while signed out and labelled "SAMPLE — FICTIONAL COMPANY". Once signed in, every page shows the throwaway account's own (empty) books.

**The numbers.** The demo date is 4 Nov 2026, so on stagger 1 the current VAT period is **Oct–Dec 2026**. The receipt is
`https://accnomos.com/sample-receipt.png` (`apps/web/public/sample-receipt.png`, drawn by `tools/make_sample_receipt.py`):
fictional **Novex Office Supplies Ltd**, VAT GB 882431902, dated **2 Nov 2026**, 2 × A4 paper £25.00 + gel pens £18.25 =
net **£43.25** + VAT **£8.65** = **£51.90**, stamped *SAMPLE — FICTIONAL COMPANY*. On an account with no other entries in Oct–Dec 2026,
approving it gives Box 4 = **£8.65**, Box 5 = **£8.65** (to reclaim), Box 7 = **£43** (whole pounds, rounded down), every other box 0.
Proved by `services/runtime/tests/test_vat_periods.py::test_vat_defaults_to_the_current_period_by_settings` (today 4 Nov 2026,
Box 4 `8.65`, Box 7 `43`, label "Oct–Dec 2026") and by running `compute_vat_return` on that one event. If the account holds
other approved entries dated Oct–Dec 2026, the figures rise by theirs: check before going on.

## Set up before you go on (not part of the four minutes)

1. Sign in on a laptop and complete *Connect* once, so the folder exists and the tree is visible. Empty `00 Inbox`.
2. `curl https://api.accnomos.com/health` returns `"ok": true`. On the Spark, `ollama list` shows `muse-glimmer:30b`; run one dummy scan so the model is warm. (Not checked from this review: the live sites were unreachable.)
3. Settings → *Autopilot level* stays **L1** (propose only). Settings → *VAT periods* stays **Quarterly, stagger 1**.
4. Download the sample receipt to the laptop. Have `docs/META_MODELS.md`, `pytest -q` in `services/hmrc-relay` (102 pass, HMRC mocked) and a screen recording ready as the last resorts below.

For judges who want to click through six months of books rather than one receipt, `tools/seed_demo.md` fills a
**separate** throwaway account; don't seed the account used for this script (it leaves 25 documents in `00 Inbox`).

## Script

| Time | Do | Say | If it fails, do this |
|---|---|---|---|
| 0:00 | Open **accnomos.com** → *Home* | "A bookkeeper for a UK small business that owns its data. There is no Accnomos database: the books are files in your OneDrive." | Site down: run locally (`docs/DEV.md`, runtime :8780, web :3000), else play the recording |
| 0:20 | **Files** (or *Open in OneDrive*): show `00 Inbox` … `07 Reports` and `_System/Ledger/events` | "If you disconnect us, every file is still there." | Sign-in or Graph error: the signed-out Files page shows the labelled sample tree; narrate from it and show a folder screenshot |
| 0:35 | **Connect → Choose your AI**: leave **On my own machine**, press **Test connection** | "Muse Glimmer 30B, open weights, so the receipt never goes to Meta or Baseten. Or paste your own Meta key for Muse Spark." Be honest: "here that machine is our DGX Spark." | Unreachable: switch to **My own Meta API key** and test again; if that fails too, narrate the next step from the eval table in `docs/META_MODELS.md` |
| 0:50 | **Review → Add a receipt** → `sample-receipt.png` → **Scan 00 Inbox now** | "The agent crops, reads, then checks. 20–40 s on local Glimmer. While it runs: *code* checks the arithmetic, VAT maths, VAT-number format, duplicates and whether the date is in this VAT period." | Slow: say "this is the local read" and keep talking over it. Never finishes: `/connect/ai` → **Test connection**, then rescan |
| 1:25 | The proposal card appears | Point at *Read by Glimmer 30B on your machine*, the green checks, **Verifier agrees · all 6 fields match**. "A second reading, with a different prompt, never saw the first answer. Code compares six fields; a mismatch would land in *Needs a look* with both values." | "Second reading unavailable": it is a warning, not a pass, and the proposal waits for you: say that is the safety design. A mismatch: show both values, then approve anyway |
| 1:50 | Tick **Always do this for Novex Office Supplies**, press **Approve (post to books)** | "A human approves. The ledger event is immutable and says who approved. Autopilot is off at L1; at L2 only receipts matching a rule I saved post alone, with **Undo**, which adds a reversing entry." | Approve errors: reload Review (the proposal is saved); if still stuck, show the card and say the post is one ledger file |
| 2:10 | **VAT return**: the picker reads **Oct–Dec 2026 · current**; point at the boxes | "Nine boxes by plain code from the entries I approved, for the current period by my stagger. **Box 4 is £8.65**, the VAT on that receipt; **Box 7 is £43**, whole pounds. The model never touches a VAT number." Then pick **Jul–Sep 2026**: zero on a fresh account. Switch back | Figures differ from the above: other entries exist in the quarter; say "plus the earlier ones" and read the live numbers. Picker missing: the runtime is down; use the Ask fallback below |
| 2:40 | **Connect to HMRC (sandbox)** → sign in as the test user → enter the `vrn` → **Show obligations** → pick one → read the confirmation card → tick the declaration → **Submit to HMRC (sandbox)** (signed in, the sample mock-up is not shown) | "Through our relay, which holds only HMRC's client secret and adds the fraud-prevention headers. Nothing is sent until I make the legal declaration. This is HMRC's **sandbox**; we do not file for real." | **This step has never been run end to end in a browser.** On any error stop at the confirmation card (it shows the body and the declaration), then show `pytest -q` in `services/hmrc-relay` (102 passing, HMRC mocked) and `docs/HMRC.md`. Say plainly that the live submit is unverified |
| 3:15 | **Files → Rebuild Books.xlsx → Open** | "For your accountant, a spreadsheet generated from the same events. It is a read-only copy." | Excel will not open it from OneDrive (never checked there): show the sheet list from `docs/ARCHITECTURE.md` and move on |
| 3:25 | **Ask**: type "How much VAT have I reclaimed this quarter?" | "Words from the model, numbers from code." The *Key numbers* list shows **VAT reclaimed (Box 4) £8.65** for the period picked on *VAT return*. "If the model quotes a figure that is not in your books, we replace the answer with the facts." | Plain facts answer: good, say that is the grounding guard working. Error: check the AI setting; do **not** demo the mic (key mode only; request format unverified; never run live) |
| 3:40 | **Android** (device or mirrored screen): **Review** lists proposals from the same folder, **VAT** shows the nine boxes (calendar quarters: the phone sends no stagger), camera icon *Photograph a receipt* | "Same runtime, same folder: the phone captures, reviews and asks. Filing with HMRC is web only." | Sign-in fails ("signature not registered"): show the signed-out sample Review and 9-box VAT, and say a release build's signature still has to be registered with Microsoft. The Flutter app has never been analysed or tested by us: keep claims to what is on screen |
| 3:55 | Back to **Home** | "AI proposes, you approve, code calculates." | n/a |

## Other things that can go wrong

| Failure | Fallback |
|---|---|
| A receipt from another quarter is scanned | The card warns, e.g. *Dated 14 Aug 2026 — falls in the previous period (Jul–Sep 2026); it will go on that return*. Approving keeps the receipt's own date, so it counts in Jul–Sep, not on screen: pick Jul–Sep in the picker to show it |
| Stagger changed to 2 or 3 | The current period on 4 Nov becomes Nov–Jan (2) or Sep–Nov (3); both include 2 Nov, so Box 4 and Box 7 are unchanged, but the picker label differs |
| Verifier or scan disagrees with the numbers above | Do not edit the figures; show *Needs a look* with both readings |
