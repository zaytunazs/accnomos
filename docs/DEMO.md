# Four-minute demo

**Pitch in one line:** *AI proposes, you approve, code calculates. Your books live in your own OneDrive.*

**Who is signed in:** a throwaway **personal Microsoft account** (not anyone's real books) with OneDrive opened once, on the
laptop's browser at `https://accnomos.com`. HMRC is a separate sandbox **test user** (`POST /hmrc/test-user` on the relay gives
`userId`, `password`, `vrn`; keep them on a card). On the phone, the **debug build**, signed in with the same Microsoft account
(from 0.3.1+4 a Play build carries the Play signing hash registered in Entra, but sign-in on a real phone is still untried, see `docs/HONESTY.md`).
**Sample business:** Bramblewood Joinery Ltd, fictional, shown only while signed out and labelled "SAMPLE — FICTIONAL COMPANY". Once signed in, every page shows the throwaway account's own (empty) books.

**The numbers.** The demo date is 4 Nov 2026, so on stagger 1 the current VAT period is **Oct–Dec 2026**. The receipt is
`https://accnomos.com/sample-receipt.png` (`apps/web/public/sample-receipt.png`, drawn by `tools/make_sample_receipt.py`):
fictional **Novex Office Supplies Ltd**, VAT GB 882431902, dated **2 Nov 2026**, 2 × A4 paper £25.00 + gel pens £18.25 =
net **£43.25** + VAT **£8.65** = **£51.90**, stamped *SAMPLE — FICTIONAL COMPANY*. On an account with no other entries in Oct–Dec 2026,
approving it gives Box 4 = **£8.65**, Box 5 = **£8.65** (to reclaim), Box 7 = **£43** (whole pounds, rounded down), every other box 0.
Proved by `services/runtime/tests/test_vat_periods.py::test_vat_defaults_to_the_current_period_by_settings` (today 4 Nov 2026,
Box 4 `8.65`, Box 7 `43`, label "Oct–Dec 2026") and by running `compute_vat_return` on that one event. If the account holds
other approved entries dated Oct–Dec 2026, the figures rise by theirs: check before going on. Row 11's invoice to JM Trading
Ltd (£100 + VAT £20 = **£120**) is a sale in the same quarter, so after it Box 1 is £20, Box 6 £100 and Box 5 **£11.35 to pay**.

**Dry run.** `pnpm run e2e:demo` in `apps/web` plays every row below in test mode (stage date 4 Nov 2026, the stub AI reading
`sample-receipt.png`, mail to a fake sender), at 1280 × 800 and 390 px, checks the words quoted here and writes the stills to
`docs/submission/shots/` (`apps/web/e2e/demo.spec.ts`; about 6 s a viewport). Rows 8 (HMRC) and 13 (Android) are skipped there.
Test mode differs from the stage in three visible ways: the model is called `accnomos-test-stub`, nothing is cropped
(`CROP_MODE=off`), and timestamps (Files, *Recent activity*) are the real clock's, not 4 Nov.

## Set up before you go on (not part of the four minutes)

1. Sign in on a laptop and complete *Connect* once, so the folder exists and the tree is visible. Empty `00 Inbox`.
2. `curl https://api.accnomos.com/health` returns `"ok": true`. On the Spark, `ollama list` shows `muse-glimmer:30b`; run one dummy scan so the model is warm. (Not checked from this review: the live sites were unreachable.)
3. Settings → *Autopilot level* stays **L1** (propose only). Settings → *VAT periods* stays **Quarterly, stagger 1**.
   Settings → *Invoice profile*: the business name, address and a **VAT number** (without one the invoice card charges no VAT
   and says *No VAT charged: your invoice profile has no VAT registration number.*).
4. The customer for row 11: put **JM Trading Ltd** with an email address in the account's Outlook contacts, then **Contacts** →
   tick *When importing, also add Outlook contacts that are not in your books (as customers)* → **Import from Outlook**.
   Send one invoice from **Invoices** off stage first: *Mail.Send* is asked for on the first **Send via Outlook**. (That the
   action card's Approve then sends has only been run against the fake sender; see row 12's fallback.)
5. On **Home**, press **Dismiss** on *Get set up*, so the dashboard tiles are on screen at the end.
6. Download the sample receipt to the laptop. Have `docs/META_MODELS.md`, `pytest -q` in `services/hmrc-relay` (102 pass, HMRC mocked) and a screen recording ready as the last resorts below.

For judges who want to click through six months of books rather than one receipt: **judges can use their own Microsoft
account and press Load sample books.** Signed in on accnomos.com with an empty Accnomos folder, Home (and Connect's last
step) shows *Try it with sample books*; the button fills that folder with the Bramblewood books below, every document
labelled *SAMPLE — FICTIONAL COMPANY*, with a progress bar, and reloads into Home when done. It only ever goes into an empty
folder, and deleting the Accnomos folder in OneDrive removes it. (`tools/seed_demo.md` does the same from the command line
for a throwaway account.) Don't load it into the account used for this script (it leaves 25 documents in `00 Inbox`).
What those books show is in [the table at the end](#what-the-judge-account-shows).

## Script

Step numbers are the `test.step` names in `apps/web/e2e/demo.spec.ts`; the stills are `docs/submission/shots/<nn>-*.png`.

| # | Time | Do | Say | If it fails, do this |
|---|---|---|---|---|
| 1 | 0:00 | Open **accnomos.com** → *Home*: *Good morning, …* over the tiles; the sidebar ends *AI: Glimmer 30B on your machine* | "A bookkeeper for a UK small business that owns its data. There is no Accnomos database: the books are files in your OneDrive." | Site down: run locally (`docs/DEV.md`, runtime :8780, web :3000), else play the recording |
| 2 | 0:15 | **Files** (or **Open in OneDrive**): show `00 Inbox` … `07 Reports`, then press *rules, audit log, ledger events · show* on `_System` to open `Ledger` | "If you disconnect us, every file is still there." | Sign-in or Graph error: the signed-out Files page shows the labelled sample tree; narrate from it and show a folder screenshot |
| 3 | 0:25 | **Connect → Choose your AI** (the page reads *Choose how Meta AI runs your books*): leave **On my own machine**, press **Test connection** → *Connected · …* | "Muse Glimmer 30B, open weights, so the receipt never goes to Meta or Baseten. Or paste your own Meta key for Muse Spark." Be honest: "here that machine is our DGX Spark." | Unreachable (*Not connected*): switch to **My own Meta API key** and test again; if that fails too, narrate the next step from the eval table in `docs/META_MODELS.md` |
| 4 | 0:40 | **Review → Add a receipt** → `sample-receipt.png` (*1 file added to 00 Inbox. Press “Scan 00 Inbox now”.*) → **Scan 00 Inbox now** → *1 new proposal* | "The agent crops, reads, then checks. 20–40 s on local Glimmer. While it runs: *code* checks the arithmetic, VAT maths, VAT-number format, duplicates and whether the date is in this VAT period." | Slow: say "this is the local read" and keep talking over it. Never finishes: `/connect/ai` → **Test connection**, then rescan |
| 5 | 1:10 | The card *Novex Office Supplies Ltd · £51.90* appears | Point at *Read by Glimmer 30B on your machine*, *2 Nov 2026*, *GB 882431902 ✓*, *£43.25 · £8.65 · £51.90*, the *Why: 2 lines, totals add up (43.25 + 8.65 = 51.90) …* line, and the teal line *Verifier agrees · all 6 fields match — … · checks by code: 12 of 12 passed* (12 in the dry run). "A second reading, with a different prompt, never saw the first answer. Code compares six fields; a mismatch would land in *Needs a look* with both values." Click the receipt: if the photo was cropped (a *Cropped* badge), the original and *What was read* sit side by side; a flat image says *Read as it arrived: not cropped.* **Close** | "Second reading unavailable": it is a warning, not a pass, and the proposal waits for you: say that is the safety design. A mismatch: show both values, then approve anyway |
| 6 | 1:30 | Tick **Always do this for Novex Office Supplies Ltd**, press **Approve (post to books)** (on a phone just **Approve**) → *Approved · Autopilot will do this for Novex Office Supplies Ltd next time · U to undo* | "A human approves. The ledger event is immutable and says who approved. Autopilot is off at L1; at L2 only receipts matching a rule I saved post alone, with **Undo**, which adds a reversing entry." | Approve errors: reload Review (the proposal is saved); if still stuck, show the card and say the post is one ledger file |
| 7 | 1:45 | **VAT return**: the picker's top row reads **Oct–Dec 2026**, an *Open* chip and *current period · 1 entry*; the return *Your return · Oct–Dec 2026 (current period)*; point at the boxes | "Nine boxes by plain code from the entries I approved, for the current period by my stagger. **Box 4 is £8.65**, the VAT on that receipt; **Box 7 is £43**, whole pounds. The model never touches a VAT number." (Box 4 is *VAT reclaimed on purchases*, Box 7 *Total purchases excluding VAT*; under the table *£8.65 to reclaim*.) Then pick **Jul–Sep 2026**: zero on a fresh account. Switch back | Figures differ from the above: other entries exist in the quarter; say "plus the earlier ones" and read the live numbers. Picker missing: the runtime is down; use the Ask fallback below |
| 8 | 2:10 | **Connect to HMRC (sandbox)** → sign in as the test user → enter the `vrn` → **Show obligations** → pick one → read the confirmation card → tick the declaration → **Submit to HMRC (sandbox)** (signed in, the sample mock-up is not shown) | "Through our relay, which holds only HMRC's client secret and adds the fraud-prevention headers. Nothing is sent until I make the legal declaration. This is HMRC's **sandbox**; we do not file for real." | **This step has never been run end to end in a browser, and the dry run skips it** (test mode has no relay and no HMRC). On any error stop at the confirmation card (it shows the body and the declaration), then show `pytest -q` in `services/hmrc-relay` (102 passing, HMRC mocked) and `docs/HMRC.md`. Say plainly that the live submit is unverified |
| 9 | 2:40 | **Files → Rebuild Books.xlsx** (*Books.xlsx rebuilt from your ledger events · …*) → **Open** on the `Books.xlsx` row | "For your accountant, a spreadsheet generated from the same events. It is a read-only copy." | Excel will not open it from OneDrive (never checked there): show the sheet list from `docs/ARCHITECTURE.md` and move on |
| 10 | 2:50 | **Ask**: type "How much VAT have I reclaimed this quarter?" | "Words from the model, numbers from code." Under the answer the figures read **VAT reclaimed (Box 4) £8.65** for the period picked on *VAT return*, with the file chip `_System/Ledger/events/2026-11/` it used and *Numbers by code · explanation by …*. "If the model quotes a figure that is not in your books, we replace the answer with the facts." | Plain facts answer: good, say that is the grounding guard working. Error: check the AI setting; do **not** demo the mic (key mode only; request format unverified; never run live) |
| 11 | 3:05 | Still on **Ask**: type "send a £100 invoice to JM Trading". The card *Proposed · Invoice · needs your OK*: *JM Trading Ltd · emailed to …*, *Work £100.00*, *20% on £100.00 £20.00*, *Due 4 December 2026 £120.00*, *Create the invoice and email it to …?* | "An instruction gets a card, not an action. The model only copied my words; code found the customer, priced it in pence, added the VAT and the due date from my terms. Nothing is created or sent yet." | *Which customer did you mean?*: pick **JM Trading Ltd**. No VAT on the card: the invoice profile has no VAT number (set-up step 3); say so and carry on |
| 12 | 3:20 | Press **Approve** → *✓ Invoice INV-0001 for £120.00 sent to …* | "Approved once: it is in the audit log, and approving again would not send a second one." | *saved as a draft but not sent* (no *Mail.Send* yet): say so, open **Invoices** and send it there. An approval that stopped halfway: the card says to give it 10 minutes and check Invoices; once it says the approval did not finish, check Invoices, **Reject**, and ask again only if the invoice is not there |
| 13 | 3:35 | **Android** (device or mirrored screen): **Review** lists proposals from the same folder, **VAT** shows the nine boxes (calendar quarters: the phone sends no stagger), camera icon *Photograph a receipt* | "Same runtime, same folder: the phone captures, reviews and asks. Filing with HMRC is web only." | Sign-in fails ("signature not registered"): show the signed-out sample Review and 9-box VAT, and say a release build's signature still has to be registered with Microsoft. The Flutter app has never been analysed or tested by us: keep claims to what is on screen. The dry run skips this row; its 390 px run of the web app (`*-phone.png`) is the other fallback |
| 14 | 3:50 | Back to **Home**: *Owed to you £120 · 1 unpaid sale*; *Deadlines* *VAT period Oct–Dec 2026 ends · Box 5 £11.35 to pay (so far)*; *Recent activity* *Invoice sent · INV-0001* | "AI proposes, you approve, code calculates." | n/a |

## Other things that can go wrong

| Failure | Fallback |
|---|---|
| A receipt from another quarter is scanned | The card warns, e.g. *Dated 14 Aug 2026 — falls in the previous period (Jul–Sep 2026); it will go on that return*. Approving keeps the receipt's own date, so it counts in Jul–Sep, not on screen: pick Jul–Sep in the picker to show it |
| Stagger changed to 2 or 3 | The current period on 4 Nov becomes Nov–Jan (2) or Sep–Nov (3); both include 2 Nov, so Box 4 and Box 7 are unchanged, but the picker label differs |
| Verifier or scan disagrees with the numbers above | Do not edit the figures; show *Needs a look* with both readings |

## What the judge account shows

A judge's own account after **Load sample books**, or the **second** throwaway account filled by `tools/seed_demo.py`
(the same books either way; not the account used for the script above, and never the account in the video). Fictional *Bramblewood Joinery Ltd*, Apr–Sep 2026, VAT quarterly on stagger 1; every document,
invoice and statement says *SAMPLE — FICTIONAL COMPANY*. Figures are for a seed run in Oct–Dec 2026, from the fake-OneDrive
run in `services/runtime/tests/test_seed_demo.py` (and `test_sample_books.py` for the button); neither has **yet been run
against a real OneDrive**, so load it once on a throwaway account and open each page before judges arrive. Full detail: `tools/seed_demo.md` §3.

| Page | What to look at |
|---|---|
| **Home** | *Owed to you* £17,949.78 (6 documents, 2 overdue: INV-0002 and INV-0005), the two to-dos, recent activity |
| **Review** | Empty; **Scan 00 Inbox now** (three presses) reads the 25 waiting documents: 23 proposals, 2 *Needs a look* (EUR invoice, malformed VAT number) |
| **VAT return** | Jul–Sep 2026: Box 1 £3,857.63, Box 4 £50.30, Box 5 £3,807.33 (CN-0001 and a supplier credit note already netted). Apr–Jun 2026: Box 1 £1,053.00, Box 4 £452.50, Box 5 £600.50. Oct–Dec: zero |
| **Invoices** | One of each state: INV-0001 paid, INV-0002 overdue, INV-0003 overpaid (£41.00 credit), INV-0004 paid by an exact bank match, INV-0005 part paid (£600.00 left), INV-0006 sent with credit note **CN-0001** (£318.00) |
| **Contacts** | Aged debtors £17,949.78; Thornfield Interiors' *Credit on account* £41.00 (Apply / Refund); Oakfield Hardware Supplies' statement: bill, its linked credit note, the payment made from *Bills to pay* |
| **Bank** | Apr–Jun reconciled; *Reconciled to 3 Jul 2026*; 16 Jul–Sep suggestions to confirm; **Rules** tab: account fee and insurance rules, which coded 8 lines |
| **Jobs** | Kitchen fit-out closed and invoiced (INV-0001); Office partitions open with 85.5 h unbilled, ready to invoice |
| **Vehicles** | Director's car, 13 journeys, 181.7 miles; Jul–Sep allowance £23.99 claimed |
| **Payroll** | Draft estimate for September 2026 from the timesheets (£426.00 gross), not confirmed |
| **Reports** | P&L, aged balances, VAT by period, trend; `07 Reports/<day>-reports.xlsx` already saved |
| **Audit trail** | Lines from *You*, *Autopilot* (posted six energy bills by its rules) and *Intake* (two receipts emailed in) |
| **Files** | The folder tree, filed receipts `01 Receipts/2026-04` … `2026-09`, `03 Sales` invoices and credit notes, statements, `07 Reports`, **Books.xlsx** |
| **Ask** | "How much VAT did I reclaim last quarter?" → £50.30 (Jul–Sep) |
