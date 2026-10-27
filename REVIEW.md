# Review: `claude/seed-demo-2` (judges' demo data)

Brief: the seeded judge account for fictional *Bramblewood Joinery Ltd* (six months, VAT quarterly stagger 1) should show
every major feature already populated, written by the runtime's own code. Scope: `tools/seed_demo.py`,
`tools/seed_demo.md`, `services/runtime/tests/test_seed_demo.py`, `docs/DEMO.md`. No runtime code was changed.

## What was built

`tools/seed_demo.py` keeps everything it did (36 gold documents, mileage claim, jobs, timesheets, vehicle, 25 Inbox
documents, two Starling statements, contacts, Books.xlsx) and adds, all through the app's own functions:

| Feature | How it is seeded (function the app's route calls) | Figures from |
|---|---|---|
| Invoices in every state | `invoicing.create_invoice` / `send_invoice` (no email: `NotEmailed`), then `invoicing.mark_paid(bank_line_id=…)` (*Record payment*). INV-0001 paid, INV-0002 overdue, **INV-0003 overpaid** (£41.00 credit on Thornfield Interiors), **INV-0004 paid by the exact match** (`bank_reconcile.approve_line(kind="exact")` then `payments.payment_from_bank_line`, i.e. *Post as payment*), **INV-0005 part paid** (£600 of £1,200, overdue), INV-0006 sent | `evals/gold/ledger2/part_paid` 004_over, 002_exact, 003_part_open: customers, lines, payment days and amounts (moved from July 2026 to the newer period + 10 days; gold invoice numbers replaced by the folder's sequence in the payment references) |
| Credit note | `credit_notes.create_credit_note`: **CN-0001** against INV-0006, one sash window (£318.00) | the existing INV-0006 lines |
| Supplier credit note linked to its bill | Oakfield Hardware Supplies' bill INV-2026-0892 (on account) and credit note proposed and approved like every document; `approve.credited_bill` links the credit note (`credits` = the bill) | `ledger2/credit_notes/001`. The gold has no bill, so the bill is the credit note's lines at twice the quantity (said in the docs) |
| Bill paid from Contacts | `payments.record_payment(side="purchase", bank_line_id=…)`, what *Contacts → Bills to pay → Record payment* posts: the £996.00 left after the credit | derived |
| Bank rules | `bank_rules.save_bank_rules`: *Starling account fee* → 7900 Bank charges; *Business insurance* (`Ashworth Mutual`, exactly −£42.50) → 7700 Insurance. Six monthly insurance lines added to the statements; `bank_reconcile.approve_line(kind="rule")` codes all 8 matching lines; tax-pot lines `Books.mark_line(…, "transfer")` | new, fictional |
| Autopilot | Each energy supplier's first bill approved with `always=True` (saves the rule); the second, a quarter later, goes through `autopilot.evaluate` and `inbox._autopilot_post` exactly as the scan does: 6 entries `approved_by: autopilot`, audit lines `agent:autopilot` | the gold utilities |
| Outlook intake | Two Jul–Sep card receipts are put in a stand-in `FakeMailProvider` and `intake.scan_mail` copies them into `00 Inbox` (audit `agent:intake`), then they are proposed and approved. The account's own mailbox is never read | gold receipts |
| Payroll | `payroll.prepare("2026-09")`: a draft estimate (Sam 15 h £277.50, Priya 13.5 h £148.50), not confirmed | the timesheets |
| To-dos | `todos.add_todo` ×2 (chase INV-0005's £600; ask Thornfield about the £41 credit), due today +3 / +7 | derived |
| `07 Reports` | `routes_reports.export` (report `all`), called last | ledger |

Idempotence and safety: `seed_state()` says `empty` / `complete` / `partial` / `foreign`. `seed()` on a complete seed
writes nothing and returns `already_seeded: True`; the CLI prints "already seeded to the end: nothing to do" and exits 0.
Part-seeded books (no `07 Reports` file yet) and books with any entry approved by someone other than `demo-seed`/Autopilot
are refused (`RuntimeError`; CLI exit 1, "use --wipe"). The plan stays pure and deterministic; `--dry-run` prints
"59 ledger events: 45 approved entries and 14 posted by code…", each document (tagged `[Autopilot]`, `[Always do this]`,
`[emailed in]`, job), each invoice's state and payments, CN-0001, the bill payment, VAT per period, rules, pay run, to-dos.
`build_plan(..., extras=False)` gives the first 40 entries only (the books the stored eval reports were run on).

Docs: `tools/seed_demo.md` "What it writes" and "What the judge sees" tables rewritten with the new figures;
`docs/DEMO.md` gains **What the judge account shows** (page → what to look at). The video/live-script account stays unseeded
(DEMO.md and `docs/submission/CHECKLIST.md` already say so; the new section repeats it). The testmode `demo` seed was not
touched: it is the live script's (empty) account and does not use the plan.

## What I verified

From the worktree root: `source .v/bin/activate`;
`export PYTHONPATH=$PWD/packages/ledger/src:$PWD/packages/connectors/src:$PWD/services/runtime`.

- `python -m pytest services/runtime/tests/test_seed_demo.py -q` → **35 passed, 1 skipped** (the Graph test, no token).
  The full seed runs once per module on `FakeStorageProvider` as of 27 Oct 2026 and the tests assert:
  - 59 events, all balanced and inside Apr–Sep 2026: 53 approved by `demo-seed`, 6 by Autopilot; 2 credit-note reversals.
  - VAT boxes. **Apr–Jun**: Box 1 1053.00, Box 4 452.50, Box 5 600.50, Box 6 5265, Box 7 4357. **Jul–Sep**: Box 1
    3857.63, Box 4 50.30, Box 5 3807.33, Box 6 19288, Box 7 1692. Oct–Dec: zero.
  - Invoice status / payment status / balance: 0001 paid; 0002 sent, overdue; 0003 overpaid; 0004 paid; 0005 part paid
    60,000p; 0006 part paid 73,968p. Customer credit `[("sale", 4100, "payment")]`. The supplier CN credits its bill,
    and the bill's outstanding is 0. 5 payment records.
  - Aged debtors 1,794,978p (current 73,968 / 0–30 995,220 / 61–90 725,790), creditors 0. Home *Owed to you*: 6 documents,
    2 overdue, 282,000p. 7 customers, 16 suppliers.
  - Bank: 48 lines (`matched` 30, `unmatched` 16, `transfer` 2). Every Apr–Jun line is resolved; `reconciled_to` is
    **2026-07-03**; 16 suggestions are left for the judge; the 8 rule lines are matched to 7900/7700 entries.
  - Audit: lines from `user:demo-seed`, `agent:autopilot` (6 `approved`) and `agent:intake` (1 `mail_scanned`, saved 2),
    plus payment, credit note, bank-reconcile, transfer, payroll, to-do and report lines.
  - 25 Inbox files exactly as planned, so 23 proposals and 2 *Needs a look* by the checks. Pay run lines. Two to-dos.
    Books.xlsx Summary "Entries posted" 59. `07 Reports/2026-10-27-reports.xlsx` with sheets About, P&L, Debtors,
    Creditors, VAT summary, Trend, first line the SAMPLE label.
  - **A second `seed()` leaves `fake.files` byte-for-byte unchanged** (`already_seeded`). Part-seeded books → "partial";
    foreign books → "foreign"; both are refused.
  - The plan for 4 days × 3 staggers: 59 events, the six invoice states, every payment and credit note inside the window,
    to-dos in the future.
- I also ran the full seed by hand on fake storage for stagger 3 on 10 Jul 2026 and stagger 2 on 15 Aug 2026. Both gave
  59 events, 48 lines, reconciled to 3 Mar / 3 May. This is not in the suite.
- `python -m pytest services/runtime packages evals -q` → **1444 passed, 1 skipped** (3 min 16 s). `evals/tests/test_autopilot_sim.py` and
  `test_ask_and_judge_harness.py`, which call `seed()`, pass with the extras on.
- `ruff check` and `ruff format --check` on `tools/seed_demo.py` and `services/runtime/tests/test_seed_demo.py` are clean.
  `pyright services/runtime/app`: 0 errors. `pyright tools/seed_demo.py`: 6 errors, all pydantic-default "missing
  argument" / `from_` noise. Main had 7 of these before this branch, and none are new.
- `python tools/seed_demo.py --dry-run` (and `--stagger 2`) print the plan with the counts above.

## What remains

- **Never run against a real OneDrive.** The Graph call count is higher now: about 60 more writes and many reads. Throttling
  and token expiry mid-run are untested (a part-filled folder is refused until `--wipe`). The e2e suite was not run because no
  e2e file changed.
- **Finding for the bank owners, not fixed here (outside scope):** `bank_reconcile.approve_line(kind="rule")` posts the
  entry but leaves the bank line `unmatched`. The matcher then suggests the line to the new entry, and the seed confirms that
  match, which is what a user would do next. If the Reconcile tab is meant to settle the line in one step, it does not.
- The seed calls the private `inbox._autopilot_post` so that the Autopilot postings are exactly what the scan writes. A public
  hook would be cleaner.
- The intake demo uses a stand-in mailbox (two fictional receipts). On the judge account the intake log names `.example`
  senders, and the files are dated the run day, not the receipt day. The judge's own *Scan mail* reads their mailbox as usual.
- The supplier's bill is derived (credit-note lines at twice the quantity), not taken from gold. The insurance lines and the
  two bank rules are new fictional data.
- The 07 Reports file doubles as the seed's "finished" marker. If someone deletes it, a re-run treats the books as part-seeded
  and refuses them. That is safe, but it needs `--wipe`.
- The stored Ask and Autopilot eval reports were run on the 40-entry books. A re-run of `evals/harness/ask_40.py` or
  `autopilot_sim.py` now gets the extras, which changes their figures. Pass `extras=False` in those harnesses (not in this
  scope) to keep them comparable.
- `README.md` "What works today" (27 Oct demo-seed row) still describes the 40-entry seed. It is out of this scope; update it
  when merging.
- The Ask figure (£50.30 for Jul–Sep) is from Box 4, and no model was asked.
