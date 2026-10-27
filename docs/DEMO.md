# Three-minute demo

**Sample business:** Bramblewood Joinery Ltd, fictional (the banner on every app page says so). **Receipt:** `https://accnomos.com/sample-receipt.png`
(fictional Novex Office Supplies, dated **2 Nov 2026**, net £43.25 + VAT £8.65 = £51.90, labelled *SAMPLE — FICTIONAL COMPANY*,
drawn by `tools/make_sample_receipt.py`). 2 Nov falls in the VAT quarter containing 4 Nov 2026 for every stagger, so it lands in the period on screen.
**Pitch in one line:** *AI proposes, you approve, code calculates. Your books live in your own OneDrive.*

## Set up before you go on (not part of the three minutes)

1. A throwaway personal Microsoft account with OneDrive opened once. Sign in on a laptop, complete *Connect* (below) so the folder exists.
2. `curl https://api.accnomos.com/health` returns `"ok": true`. On the Spark, `ollama list` shows `muse-glimmer:30b`, and one dummy scan has already run so the model is warm.
3. Settings → *Autopilot level* stays on **L1** (propose only). Settings → *VAT periods* stays **Quarterly, stagger 1** (Oct–Dec 2026 on 4 Nov).
   The throwaway account has **no other approved entries dated Oct–Dec 2026**, otherwise the Box 4/Box 7 figures below rise by theirs.
4. A sandbox HMRC test user: `POST /hmrc/test-user` on the relay gives `userId`, `password`, `vrn`. Keep them on a card.
5. Download the sample receipt to the laptop. Android: debug build installed and signed in. Empty `00 Inbox`.

## Script

| Time | Click | Say |
|---|---|---|
| 0:00 | Open **accnomos.com** → *Home* | "A bookkeeper for a UK small business that owns its data. There is no Accnomos database: the books are files in your OneDrive." |
| 0:15 | **Connect your OneDrive** → *Sign in with Microsoft* → *Create my Accnomos folder* → *Open in OneDrive* (already done, so just show the tree) | "00 Inbox to 06 Reports, and `_System/Ledger/events`. If you disconnect us, every file is still there." |
| 0:30 | Step 2 (*Choose your AI*): leave **On my own machine**, press **Test connection** | "Muse Glimmer 30B, open weights, so the receipt never goes to Meta or Baseten. Or paste your own Meta key for Muse Spark." Be honest: "here that machine is our DGX Spark." |
| 0:40 | **Review** → **Add a receipt** → choose `sample-receipt.png` → **Scan 00 Inbox now** | "The agent crops, reads, then checks. This takes 20–40 s on local Glimmer, so while it runs: *code* checks the arithmetic, VAT maths, VAT-number format, duplicates and whether the date is in this VAT period." |
| 1:10 | The proposal card appears | Point at *Read by Glimmer 30B on your machine*, the green checks, **Verifier agrees · all 6 fields match**. "A second reading, with a different prompt, never saw the first answer. Code compares six fields; a mismatch would land in *Needs a look* with both values." |
| 1:30 | Tick **Always do this for Novex Office Supplies**, press **Approve (post to books)** | "A human approves. The ledger event is immutable and says who approved. Autopilot is off by default; if I switch to L2 later, matching receipts post alone, with Undo, which adds a reversing entry." |
| 1:50 | **VAT return** (top of the page): the picker says **Oct–Dec 2026 · current** | "Nine boxes, computed by plain code from the entries I approved, for the current VAT period by my stagger. **Box 4 is £8.65**, the VAT on that receipt, and **Box 7 is £43**: HMRC wants whole pounds for boxes 6 to 9. The model never touches a VAT number." Then open the picker and choose **Jul–Sep 2026**: the boxes recompute for that quarter (zero on a fresh account) and *Prepare submission* stays available only for the current or previous period. Switch back to Oct–Dec. |
| 2:05 | **Connect to HMRC (sandbox)** → sign in with the test user → enter the `vrn` → **Show obligations** → pick one → read the confirmation card → tick the declaration → **Submit to HMRC (sandbox)** (the button in the *upper* card, not the lower mock-up) | "Through our relay, which holds only HMRC's client secret, adds the fraud-prevention headers and keeps nothing. Nothing is sent until I make the legal declaration. This is HMRC's **sandbox**; we do not file for real." |
| 2:30 | **Files** → **Rebuild Books.xlsx** → *Open* | "And for your accountant, a spreadsheet generated from the same events." |
| 2:40 | **Ask**: type "How much VAT have I reclaimed this quarter?" (expected: £8.65, for Oct–Dec 2026, the period picked on *VAT return*) | "Words from the model, numbers from code. If the model quotes a figure that is not in your books, we replace the answer with the facts." |
| 2:50 | **Android** (on the device or a mirrored screen): **Review** tab shows the same proposal; **VAT** tab shows the nine boxes; camera icon *Photograph a receipt* | "Same runtime, same folder. The phone captures receipts and approves. Filing and voice are web only today." |

## If X fails, show this instead

| Failure | Fallback |
|---|---|
| Scan slow or Glimmer unreachable | Say "this is the 20–40 s local read"; open `/connect/ai` and press **Test connection**. Switch to **My own Meta API key** (Muse Spark) and rescan. Last resort: the eval table in `docs/META_MODELS.md` |
| Verifier shows "Second reading unavailable" | It is a warning, not a pass: the proposal waits for you. That *is* the safety design; say so |
| Microsoft sign-in or OneDrive "pending provisioning" | Signed-out pages show the labelled sample tree and cards; narrate from those, and show a folder screenshot |
| HMRC step errors (**end-to-end browser run is still unverified**) | Stop at the confirmation card showing the 11-field body and the declaration. Then show `pytest -q` in `services/hmrc-relay` (100 passing, HMRC mocked) and `docs/HMRC.md` |
| accnomos.com or api.accnomos.com is down | Run locally: `docs/DEV.md` (runtime :8780, web :3000). Failing that, a screen recording made beforehand |
| Ask returns the plain "facts" fallback | Good: say that is the grounding guard working |
| A receipt from another quarter is scanned | The card shows a warning, e.g. *Dated 14 Aug 2026 — falls in the previous period (Jul–Sep 2026); it will go on that return*. It is only a warning: approving keeps the receipt's own date, so it counts in Jul–Sep, not on screen. Pick Jul–Sep in the period picker to show it |
| Android sign-in fails ("signature not registered") | Show the signed-out sample Review and the 9-box VAT screen, and say sign-in needs the build's signature registered with Microsoft |
| Mic on Ask | Do not demo it live: key mode only, request format unverified, never run with a real key |
