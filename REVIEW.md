# Review: credits applied and refunded, bills paid on the web, one movement counted once (`claude/payments-2`)

Follows `docs/reviews/part-payments/REVIEW.md`, picking up its "What remains" list.

## What was built

**1. Apply or refund a contact's credit** (`services/runtime/app/credits.py`, new)
- A credit (`settlement.Credit`, now with an id: `payment:<id>` or `credit_note:<event id>`) can be
  - *applied* to another open invoice/bill of the same contact (same normalised name, same side): a `CreditUse`
    kind `apply`, nothing posted — the money is already in 1100 Debtors / 2100 Creditors on that contact;
  - *refunded*: kind `refund`, posted by code as a `bank` event with no VAT — customer: Dr 1100 Debtors / Cr 1200 Bank
    (or 1210 Cash); supplier refund received: Dr 1200 Bank / Cr 2100 Creditors. With `bank_line_id` the line is
    matched to the refund event.
- Saved in `_System/Payments/credit_uses.json`; `settle()` takes uses after payments (same day), each taking no more
  than is left of its credit (and, for apply, of the document). An overpayment applied counts as `paid` on the target;
  a credit note's credit applied counts as `credited`.
- *Remove* (`DELETE /credits/uses/{id}`, or Remove on the invoice row): apply marked removed; refund reversed and its
  line unmatched. Guards: a payment, Bank-page line, credit note (void or undo) whose credit is used, or an invoice a
  credit was applied to, cannot be removed/voided until the use is removed.
- Routes: `GET /credits?side=`, `POST /credits/apply`, `POST /credits/refund`, `DELETE /credits/uses/{id}`.
  Statement gains `credits`, `open_documents`, `credit_uses` and `refund` lines. Audit summaries for the new kinds.
- Web: Invoices — *Apply credit* on a sent invoice with balance when the customer has credit, *Refund* on the invoice
  (or credit note) the credit came from, Remove on applied credits. Contacts — *Credit on account* with Apply
  credit / Refund, *Credit used* with Remove, Remove on statement payment/refund lines.

**2. Paying bills in the web**: Contacts side panel *Bills to pay* (each open bill: date, due date, paid, balance)
with *Record payment* → `POST /payments` side `purchase` (amount, date, bank or cash, reference; money over is a
credit the supplier owes). Undo: Remove on the statement's payment line (`DELETE /payments/{id}`).

**3. Supplier credit notes link to their bill**: `ExtractedDoc.original_invoice_number` (optional; prompt asks for
it on credit notes). On approval, `approve.credited_bill` sets the event's `credits` to the one standing bill on
account (Cr 2100) of the same supplier whose number matches (`same_number`: letter/digit runs must end the printed
text, or match with punctuation removed; "Inv no. H 77" = "H-77", "H-177" ≠ "77"). Unmatched or ambiguous → stays a
credit on the supplier. A refund line on the Bank page is offered against a contact credit of the same amount
(Reconcile tab, *Refund of a credit* → `approve` kind `refund`).

**4. Double counting guard** (`payments.py`, bottom section; hooks in `Books.confirm_match/unmatch/bank_suggestions`)
- Bank suggestions: an open line with the same signed amount as an unlinked recorded payment or refund (in 1200 Bank,
  dated 5 days before to 14 days after) is suggested to that entry ("Recorded payment of £… on … — link the line to
  it"); documents already settled are never suggested (also in Reconcile exact).
- `confirm_match` refuses (409) a match to a settled document, naming the recorded payment to link to; a match to a
  payment/refund entry must be alone and of the same amount. Linking/unlinking keeps the record's `bank_line_id` in step.
- Reverse: `record_payment` on an invoice already paid by a Bank-page match says so and points to *Post as payment*;
  `POST /payments/from-bank-line/{id}` turns that match into a recorded payment for the same split (line rematched to
  it; restored if recording fails). Web: *Post as payment* on bank-line rows in Payments and history.

**5. Payment terms**: `terms_days` added to `ContactEdit` (it was refused by the strict body before, so the old docs'
"settable via PUT" was not actually true); web Edit has *Payment terms (days)* (blank = 30, 0–365 checked) and the
panel shows it. Ageing already used it.

Docs: README (Sales invoicing row text and Contacts/Sales feature rows), `docs/REMAINING.md`, `docs/HONESTY.md`.
Android: no change needed (it reads `money` generically; nothing parses the new `source: "credit"`).

## What I verified

From the worktree root, `source .v/bin/activate`,
`export PYTHONPATH=$PWD/packages/ledger/src:$PWD/packages/connectors/src:$PWD/services/runtime`:
- `python -m pytest services/runtime packages -q` → **1071 passed, 1 skipped** (main: 1056 + 1 skipped; 15 new tests in
  `services/runtime/tests/test_payments.py`: apply / apply checks / customer refund with bank line and remove guard /
  refund checks / credit-note credit applied (void guards) / supplier refund on a bank line + undo guard / credit
  routes + terms route / supplier CN linked to its bill / unknown bill stays a credit / number comparison / the
  review's double-count scenario / amount check and unlink / reverse via from-bank-line / Bank reconcile refund for
  a customer and for a supplier). `test_bank_gold.py` updated for the new `label` field on suggestion events.
- `ruff check services/runtime packages` → all checks passed; `ruff format --check` → 137 files already formatted.
- `pyright services/runtime/app` → 0 errors, 0 warnings.
- Web (`apps/web`): `pnpm exec eslint .` clean; `pnpm run build` OK; `pnpm exec tsc --noEmit` clean.
- E2E: `E2E_WEB_PORT=3500 E2E_RUNTIME_PORT=9181 E2E_RELAY_PORT=9189 pnpm run e2e:build`, then `playwright test`
  (full suite) → **193 passed, 1 failed**: only `site-health.spec.ts:10` (hard-codes port 3100). New
  `e2e/credits-bills.spec.ts` (3 tests) also passed 9/9 with `--repeat-each=3`; invoices, invoice-payments, contacts,
  bank and bank-rules specs pass. (While the shared `.v` was briefly broken the e2e runtime ran from a private
  `uv sync --frozen` venv in the scratchpad; the pytest/ruff/pyright figures above are from the rebuilt shared `.v`.)
- Not run: Flutter (no SDK); anything against a real OneDrive, mailbox, bank export or model; extraction eval with
  `original_invoice_number`.

## What remains

- Android has none of: Apply credit, Refund, paying bills, Post as payment, payment terms.
- Review does not show which bill a supplier credit note will be linked to before approval; the link is set at
  approval only (undo and re-approve to change it). Extraction eval not re-run with the new field.
- Link suggestions need the exact same amount and a 5-before/14-after day window; a refund line is offered only for a
  credit of exactly its amount. One credit per apply/refund action (no split across credits).
- A bank line matched straight to invoices still posts nothing until *Post as payment* is used.
- `credit_uses.json` and `payments.json` are rewritten whole (last write wins).
- Old "Mark paid" invoices (no amount) still count paid on Invoices/Home but open in Contacts/ageing (unchanged).
