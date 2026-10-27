# Demo seed: a judge's walkthrough of Bramblewood Joinery Ltd

`tools/seed_demo.py` fills a **throwaway** Microsoft account's OneDrive with six months of books for the fictional
Bramblewood Joinery Ltd. Every document, invoice and statement it writes is labelled *SAMPLE — FICTIONAL COMPANY*.
It writes through the runtime's own code (`approve()`, Autopilot, Outlook intake, invoicing, payments, credit notes,
bank reconcile, jobs, mileage, contacts, payroll, to-dos, the reports export, `Books`), so the result is what the app itself
would have written after six months of use. Part payments, the overpayment, the exact bank match and the supplier credit note
use the figures of the ledger2 gold set (`evals/gold/ledger2`, made by Qwen and checked by code), not new ones.

What it writes. The dates below assume a run between 1 Oct and 31 Dec 2026 with VAT stagger 1; `--dry-run` prints them for any day.

| | |
|---|---|
| 59 ledger events | All in the last two complete VAT periods (Apr–Jun and Jul–Sep 2026). **45 approved**: 38 documents (36 gold receipts and sales invoices, plus Oakfield Hardware Supplies' bill INV-2026-0892 and its credit note), the Jul–Sep mileage claim, six invoices raised in the app. **14 posted by code for an action**: five payments, credit note CN-0001, eight statement lines coded by bank rules |
| Who approved | You (`demo-seed`) for 53; **Autopilot** for 6: each energy supplier's first bill was approved with *Always do this* ticked, and Autopilot posted the second one a quarter later. Two receipts in Jul–Sep came in by email through **Outlook intake** (from a stand-in mailbox holding only those two fictional receipts; the account's own mailbox is never read) |
| 25 documents in `00 Inbox` | Dated in the current period, not yet read. 23 should come out as proposals; two should land in *Needs a look* (an invoice in EUR, and a receipt with a malformed VAT number) |
| Contacts | 7 customers and 16 suppliers. Three customers have a (`.example`) email and an address, and the three ledger2 customers theirs from the invoice. The four suppliers whose receipts over £250 charge no VAT and show no VAT number are recorded as *not VAT-registered* before anything is scanned, so their receipts are proposed instead of asking "Is … VAT-registered?" |
| Jobs | *Kitchen fit-out, Harrogate* (closed, invoiced on INV-0001) and *Office partitions and doors* (open, hours not yet billed); two staff members, 24 timesheet entries, materials purchases tagged to each job |
| Vehicle | *Director's car (own)*, a personal car, with 13 business journeys; the Jul–Sep allowance (£23.99) has been claimed and posted |
| Invoices | INV-0001 paid (Record payment with its statement line); INV-0002 **overdue**; INV-0003 **overpaid** by £41.00 (a credit on Thornfield Interiors); INV-0004 paid by the Bank page's **exact match**, then *Post as payment*; INV-0005 **part paid** (£600 of £1,200) and overdue; INV-0006 sent, not yet due, with **CN-0001** (£318.00, one sash window) against it. None was emailed |
| Supplier credit note | Oakfield's credit note (–£996.00, VAT –£91.00) is linked to its bill on approval; the rest of the bill (£996.00) is paid from **Contacts → Bills to pay** with its statement line |
| Bank | Two Starling-layout statements, one per period, and two **bank rules** (*Starling account fee* → 7900 Bank charges; *Business insurance* → 7700 Insurance, exactly £42.50) that code 8 lines. Tax-pot transfers marked as transfers. Apr–Jun is fully reconciled; in Jul–Sep the payments above are matched and 16 suggested matches wait to be confirmed (bank reconciled to 3 Jul 2026) |
| Payroll | A draft pay-run **estimate** for September 2026 from the timesheets (28.5 h, £426.00 gross); not confirmed, so nothing posted |
| To-dos | Two: chase Oak & Ash Interiors for the £600.00 left on INV-0005, and ask Thornfield Interiors about their £41.00 credit |
| Books.xlsx and `07 Reports` | Books.xlsx rebuilt once, then every report (P&L for the current period, aged balances, VAT summary, trend) saved as `07 Reports/<day>-reports.xlsx`. That file is the seed's last write |

The documents were not read by a model. Their proposals carry the gold set's fields (shown as model
`seed:gold-reading`), and code ran every check and drafted every journal as usual. The 25 Inbox documents are read for real, by
whichever AI the account is set up with, when someone presses *Scan*. The gold has only Oakfield's credit note, so its bill
is the credit note's lines at twice the quantity (half the goods came back).

## 1. A throwaway account and a token

Use a Microsoft account made for the demo, never one with real data. Sign in once on onedrive.com so the drive exists.

**Personal account (outlook.com / hotmail / live): take the token from the Accnomos web app.** A personal account's books
are in the *app folder* `Apps/Accnomos`, and Graph gives each app its own folder, so the token must be one the
Accnomos app was issued. A Graph Explorer token would point at `Apps/Graph Explorer`. The seed checks the folder name and
refuses to write anything if it is not Accnomos.

1. Open accnomos.com, sign in with the throwaway account, and complete *Connect* (this creates the folder).
2. Open DevTools (F12) → **Network**. Press anything that calls the runtime (*Review* → *Scan 00 Inbox now* on an empty
   Inbox will do) and pick a request to `api.accnomos.com`.
3. Under *Request Headers*, copy the value of **`X-Graph-Token`** (a long string starting `eyJ` or `EwB`).

Do this with a demo account only: that token can read and write the account's OneDrive files for about an hour. Don't paste it
into chat, a ticket or a file.

**Work or school account:** the books are at `/Accnomos` in the drive root, so any token with `Files.ReadWrite` will do,
including one from [Graph Explorer](https://developer.microsoft.com/graph/graph-explorer). Sign in there, consent to
`Files.ReadWrite`, open *Access token* and copy it. Then add `--account work` to the commands below.

## 2. Run it

From the repository root, with the runtime's virtual environment active (`docs/DEV.md`):

```bash
python tools/seed_demo.py --business "Bramblewood Joinery Ltd" --dry-run     # the plan; needs no token
python tools/seed_demo.py --business "Bramblewood Joinery Ltd"               # asks for the token (hidden input)
```

The token is read from a hidden prompt or from `ACCNOMOS_GRAPH_TOKEN`. It is never accepted as an argument, so it stays out of
shell history, and it is kept in memory only. Expect a few minutes: the seed makes several hundred Graph calls.

* A wrong or expired token stops the seed with a message, not a traceback. If it expires part-way (the run takes a few
  minutes; tokens last about an hour), the folder is part-filled: copy a fresh token and run again with `--wipe`.
* Running it again on a folder it finished seeding changes nothing ("already seeded to the end: nothing to do"); the
  `07 Reports` file is its last write, so that is how it knows. A folder seeded part-way, or one with entries someone else
  approved, is refused. To start again, add `--wipe`. It lists what is in the Accnomos folder and deletes it only if you
  type `y`. Nothing outside that folder is touched, and OneDrive keeps the deleted items in its recycle bin.
* `--stagger 2` or `--stagger 3` if the account's *Settings → VAT periods* uses another stagger (the seeded periods follow it).
* Then, in the web app, open **Connect → Business details** and set the name to *Bramblewood Joinery Ltd*. The scan uses
  it to tell sales from purchases. This setting lives in the browser, so the seed can't set it for you.

## 3. What the judge sees

The figures are for a run in Oct–Dec 2026 with stagger 1. They were computed from a run on the in-memory fake OneDrive. The seed has
**not yet been run against a real account**, so check each page once on the throwaway account before judges arrive.

| Page | What is there |
|---|---|
| **Home** | The dashboard built from the books above: *Owed to you* £17,949.78 over 6 documents, 2 invoices overdue (£2,820.00: INV-0002 and INV-0005), this period's VAT, things to do, recent activity |
| **Review** | Empty until someone presses **Scan 00 Inbox now**. Each press reads up to 10 documents (about 20–40 s each on local Glimmer), so press it three times. 23 proposals and 2 *Needs a look*: the EUR invoice ("needs converting to GBP") and GreenLeaf Markets ("VAT number … is not a UK format"). Inbox documents are dated this period, so approving one changes this period's VAT boxes |
| **VAT return** | Pick **Jul–Sep 2026**: Box 1 £3,857.63, Box 4 £50.30, Box 5 £3,807.33, Box 6 £19,288, Box 7 £1,692 (Box 1 is net of CN-0001's £53.00, Box 4 of Oakfield's credit note's £91.00). Pick **Apr–Jun 2026**: Box 1 £1,053.00, Box 4 £452.50, Box 5 £600.50, Box 6 £5,265, Box 7 £4,357. Oct–Dec stays at zero until something dated in it is approved |
| **Bank** | Two statements (23 and 25 lines). Apr–Jun: every line settled (18 matched to documents and INV-0001's payment, 3 insurance direct debits and the fee coded by the rules, the tax pot a transfer). Jul–Sep: the four customer payments, the Oakfield bill payment, 3 insurance lines and the fee are done; 16 suggested matches wait to be confirmed (two are customer payments 10 days after the invoice, suggested on terms). *Reconciled to 3 Jul 2026*. **Rules** tab: the two rules |
| **Invoices** | INV-0001 Halloway & Sons Interiors £3,628.80 *paid*; INV-0002 Sterling & Co. Architects £2,220.00 *overdue* (good for drafting a reminder; sending one emails the `.example` address, which goes nowhere); INV-0003 Thornfield Interiors £1,596.00 *paid*, £41.00 over; INV-0004 Harlow & Finch Interiors £3,000.00 *paid* (bank match posted as payment); INV-0005 Oak & Ash Interiors £1,200.00 *part paid*, £600.00 to pay; INV-0006 Hartwell Property Maintenance £1,057.68 *sent*, credited £318.00, £739.68 to pay. **Credit notes**: CN-0001 |
| **Contacts** | 23 contacts. Aged debts £17,949.78: Sterling & Co. Architects £2,220.00 at 61–90 days late plus £5,259.60 at 0–30; Hartwell £4,437.90 at 61–90 and £739.68 not yet due; Oak & Ash £600.00 at 61–90. Nothing owed to suppliers. Thornfield Interiors has *Credit on account* £41.00 (Apply credit / Refund). Oakfield Hardware Supplies' statement shows the bill, its credit note and the payment |
| **Jobs** | Kitchen fit-out (closed): 85.5 h, labour £1,278.00, materials £1,373.90, invoiced £3,024.00. Office partitions (open): 85.5 h unbilled, worth £3,024.00, ready to turn into an invoice |
| **Vehicles** | Director's car: 181.7 business miles this tax year. Allowance £81.77 in total, of which £23.99 (Jul–Sep) is claimed and posted; Apr–Jun miles are still unclaimed |
| **Payroll** | A draft estimate for September 2026: Sam Ashdown 13.5 h £148.50, Priya Hale 15 h £277.50 (no PAYE or NI at these amounts). *Confirm* with the provider's figures would post it |
| **Reports** | Jul–Sep 2026 P&L, aged balances, VAT by period, trend; `07 Reports/2026-10-27-reports.xlsx` already saved (labelled sample) |
| **Audit trail** | Lines from *You*, *Autopilot* (six bills posted) and *Intake* (one mail scan, two receipts saved). There are no *Reader* lines: the proposals are written by `demo-seed`, not a model |
| **Files** | The folder tree, README.txt, the filed receipts under `01 Receipts/2026-04` … `2026-09`, sales invoices and credit notes under `03 Sales`, statements, `07 Reports` and **Books.xlsx** (*Rebuild* regenerates it) |
| **Ask** | Expected: "How much VAT did I reclaim last quarter?" gives £50.30 (Jul–Sep). The figures come from code and the wording from the model, so the sentence will vary |
| **To-dos** (Home) | The two above, due 30 Oct and 3 Nov 2026 |

## With the three-minute script (`docs/DEMO.md`)

That script needs an empty `00 Inbox` and nothing approved in Oct–Dec 2026. The seed approves nothing in the current period, but
it leaves 25 documents in the Inbox, and the scan takes them 10 at a time. Run the three-minute script on a **second**
throwaway account, or before seeding this one.

## Tests

`services/runtime/tests/test_seed_demo.py` checks the plan (counts, balance, date spread, labels, the ledger2 figures, other
staggers and days) and runs the whole seed once on the in-memory fake OneDrive as of 27 Oct 2026, checking the VAT boxes for
each quarter, invoice states and balances, the customer credit, aged balances, bank lines and the reconciled-to date, audit
lines from you, Autopilot and intake, payroll, to-dos and the report file quoted above; then that a second run changes no
file, and that part-seeded or someone else's books are refused. The Graph run is skipped unless `ACCNOMOS_SEED_GRAPH_TOKEN` is set.
With only the token it just reads the folder. With `ACCNOMOS_SEED_GRAPH_WRITE=1` as well, it seeds that account (a fresh one).
