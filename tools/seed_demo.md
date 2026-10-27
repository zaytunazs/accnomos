# Demo seed: a judge's walkthrough of Bramblewood Joinery Ltd

`tools/seed_demo.py` fills a **throwaway** Microsoft account's OneDrive with six months of books for the fictional
Bramblewood Joinery Ltd. Every document, invoice and statement it writes is labelled *SAMPLE — FICTIONAL COMPANY*.
It writes through the runtime's own code (`approve()`, invoicing, jobs, mileage, contacts, `Books`), so the result
is what the app itself would have written after six months of use.

What it writes. The dates below assume a run between 1 Oct and 31 Dec 2026 with VAT stagger 1; `--dry-run` prints them for any day.

| | |
|---|---|
| 40 approved ledger entries | All in the last two complete VAT periods (Apr–Jun and Jul–Sep 2026): 36 documents approved in Review (purchases, quarterly energy bills, four sales invoices), one mileage allowance claim, three invoices raised in the app |
| 25 documents in `00 Inbox` | Dated in the current period, not yet read. 23 should come out as proposals; two should land in *Needs a look* (an invoice in EUR, and a receipt with a malformed VAT number) |
| Contacts | 4 customers and 13 suppliers, taken from the ledger; three customers have a (`.example`) email and an address |
| Jobs | *Kitchen fit-out, Harrogate* (closed, invoiced on INV-0001) and *Office partitions and doors* (open, hours not yet billed); two staff members, 24 timesheet entries, materials purchases tagged to each job |
| Vehicle | *Director's car (own)*, a personal car, with 13 business journeys; the Jul–Sep allowance (£23.99) has been claimed and posted |
| Invoices | INV-0001 paid (matched to the bank), INV-0002 **overdue**, INV-0003 sent and not yet due. None was emailed |
| Bank | Two Starling-layout statements, one per period. Apr–Jun is reconciled; Jul–Sep's lines are suggested matches waiting to be confirmed |
| Books.xlsx | Rebuilt once at the end |

The documents were not read by a model. Their proposals carry the gold set's fields (shown as model
`seed:gold-reading`), and code ran every check and drafted every journal as usual. The 25 Inbox documents are read for real, by
whichever AI the account is set up with, when someone presses *Scan*.

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
* A folder that already has ledger entries is refused. To start again, add `--wipe`. It lists what is in the Accnomos folder
  and deletes it only if you type `y`. Nothing outside that folder is touched, and OneDrive keeps the deleted items in its recycle bin.
* `--stagger 2` or `--stagger 3` if the account's *Settings → VAT periods* uses another stagger (the seeded periods follow it).
* Then, in the web app, open **Connect → Business details** and set the name to *Bramblewood Joinery Ltd*. The scan uses
  it to tell sales from purchases. This setting lives in the browser, so the seed can't set it for you.

## 3. What the judge sees

The figures are for a run in Oct–Dec 2026 with stagger 1. They were computed from a run on the in-memory fake OneDrive. The seed has
**not yet been run against a real account**, so check each page once on the throwaway account before judges arrive.

| Page | What is there |
|---|---|
| **Home** | The dashboard built from the books above: money owed to the business (INV-0002 overdue, plus unpaid sales), this period's VAT, things to do |
| **Review** | Empty until someone presses **Scan 00 Inbox now**. Each press reads up to 10 documents (about 20–40 s each on local Glimmer), so press it three times. 23 proposals and 2 *Needs a look*: the EUR invoice ("needs converting to GBP") and GreenLeaf Markets ("VAT number … is not a UK format"). Inbox documents are dated this period, so approving one changes this period's VAT boxes |
| **VAT return** | Pick **Jul–Sep 2026**: Box 1 £2,944.63, Box 4 £141.30, Box 5 £2,803.33, Box 6 £14,723, Box 7 £2,465. Pick **Apr–Jun 2026**: Box 1 £1,053.00, Box 4 £270.50, Box 5 £782.50, Box 6 £5,265, Box 7 £2,414. Oct–Dec stays at zero until something dated in it is approved |
| **Bank** | Two statements (filed as `2026-06-30_starling.csv` and `2026-09-30_starling.csv`). Apr–Jun: 18 lines matched; 2 open (a tax-pot transfer, which is a transfer, and the account fee, which has no ledger entry yet). Jul–Sep: 16 suggested matches to confirm (two of them customer payments 10 days after the invoice, suggested on terms), plus 2 open lines: the tax pot and the fee |
| **Invoices** | INV-0001 Halloway & Sons Interiors £3,628.80 *paid*; INV-0002 Sterling & Co. Architects £2,220.00 *overdue* (good for drafting a reminder; sending one emails the `.example` address, which goes nowhere); INV-0003 Hartwell Property Maintenance £1,057.68 *sent* |
| **Contacts** | 17 contacts. Aged debts: Sterling & Co. Architects owes £2,220.00 at 90+ days (INV-0002, counted from its invoice date) and £5,259.60 at 0–30 days. Each contact's statement lists their invoices and payments |
| **Jobs** | Kitchen fit-out (closed): 85.5 h, labour £1,278.00, materials £1,373.90, invoiced £3,024.00. Office partitions (open): 85.5 h unbilled, worth £3,024.00, ready to turn into an invoice |
| **Vehicles** | Director's car: 181.7 business miles this tax year. Allowance £81.77 in total, of which £23.99 (Jul–Sep) is claimed and posted; Apr–Jun miles are still unclaimed |
| **Files** | The folder tree, README.txt, the filed receipts under `01 Receipts/2026-04` … `2026-09`, sales invoices, statements and **Books.xlsx** (*Rebuild* regenerates it) |
| **Ask** | Expected: "How much VAT did I reclaim last quarter?" gives £141.30 (Jul–Sep). The figures come from code and the wording from the model, so the sentence will vary |
| **Payroll** | Nothing seeded; a pay run can be prepared from the timesheets |

## With the three-minute script (`docs/DEMO.md`)

That script needs an empty `00 Inbox` and nothing approved in Oct–Dec 2026. The seed approves nothing in the current period, but
it leaves 25 documents in the Inbox, and the scan takes them 10 at a time. Run the three-minute script on a **second**
throwaway account, or before seeding this one.

## Tests

`services/runtime/tests/test_seed_demo.py` checks the plan (counts, balance, date spread, labels, other staggers and days)
and runs the whole seed on the in-memory fake OneDrive as of 27 Oct 2026, checking the VAT boxes, invoice totals, bank
matches, contact counts and miles quoted above. The Graph run is skipped unless `ACCNOMOS_SEED_GRAPH_TOKEN` is set.
With only the token it just reads the folder. With `ACCNOMOS_SEED_GRAPH_WRITE=1` as well, it seeds that account (a fresh one).
