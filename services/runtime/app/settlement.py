"""Who has paid what: payments and credit notes allocated to invoices and bills, by code. Pure functions, no I/O.

A document on account (a sales invoice, Dr 1100 Debtors; a bill, Cr 2100 Creditors) waits for money. Three things
settle it, taken in date order:

- a credit note raised against it (app/credit_notes.py for sales; a supplier's credit note from Review): it reduces
  that document by up to what is still owed; anything over is left as a credit on the contact;
- a recorded payment (*Record payment* / *Mark paid*, app/payments.py): posted Dr 1200 Bank / Cr 1100 Debtors (or
  Dr 2100 Creditors / Cr 1200 Bank) and allocated to the documents the user chose, each by up to what is still owed;
  money over is a credit on the contact (an overpayment);
- a bank statement line matched to the document(s) on the Bank page, as before this module: nothing is posted. The
  line's amount is allocated to its documents in the order they were matched; a line within a penny a document of
  what they owe pays them in full (the matcher allows a penny of rounding), any more is an overpayment;
- a credit left on the contact (an overpayment, or a credit note bigger than what was owed) the user applied to
  another of that contact's open documents (app/credits.py, `CreditUse` kind "apply": nothing is posted, it moves
  within 1100 Debtors / 2100 Creditors), or refunded (kind "refund": posted Dr 1100 Debtors / Cr 1200 Bank for a
  customer, Dr 1200 Bank / Cr 2100 Creditors for a supplier). A use takes no more than is left of its credit.

Allocations are worked out on every request from the ledger events, the bank lines and
_System/Payments/payments.json (the payments and the split the user chose), so they cannot drift from the books.

Signs: amounts here are positive pence. Which way the money went is the document's side ("sale": received from a
customer, "purchase": paid to a supplier).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from accnomos_ledger.bank import BankLine
from app.books import SYSTEM, Books
from app.journal import BANK, CASH

if TYPE_CHECKING:  # app.contacts imports this module
    from app.contacts import Doc

log = logging.getLogger(__name__)
PAYMENTS = f"{SYSTEM}/Payments/payments.json"
CREDIT_USES = f"{SYSTEM}/Payments/credit_uses.json"
PAYMENT_ACCOUNTS = (BANK, CASH)
PENNY = 1  # the bank matcher's rounding tolerance per document (accnomos_ledger.matching.PENNY)
Side = Literal["sale", "purchase"]
PaymentStatus = Literal["open", "part_paid", "paid", "overpaid"]


class Allocation(BaseModel):
    event_id: str  # the invoice's or bill's ledger event
    amount_pence: int = Field(gt=0)


class PaymentRecord(BaseModel):
    """One payment the user recorded, as stored in payments.json. Its ledger entry is `event_id`."""

    id: str
    side: Side
    date: date
    amount_pence: int = Field(gt=0)  # what it settles: the money plus any CIS deduction
    account: str = BANK
    reference: str | None = None
    counterparty: str
    allocations: list[Allocation] = Field(min_length=1)
    # CIS (app/cis.py): the part of `amount_pence` the contractor deducted and paid HMRC instead (1150 CIS suffered on
    # a sale; 2220 CIS deductions owed on a purchase). The bank saw `amount_pence - cis_deduction_pence`.
    cis_deduction_pence: int = Field(0, ge=0)
    event_id: str | None = None  # Dr 1200 Bank / Cr 1100 Debtors (or the purchase mirror), posted by code
    bank_line_id: str | None = None  # the statement line this money came in or went out on, matched to `event_id`
    created_by: str
    created_at: datetime
    removed_at: datetime | None = None  # removed: its entry was reversed (`reversal_event_id`)
    removed_by: str | None = None
    reversal_event_id: str | None = None


class Payment(BaseModel):
    """A payment as shown: a recorded one, or a bank line matched straight to documents."""

    id: str  # the record id, or the bank line id
    source: Literal["recorded", "bank_line"]
    side: Side
    date: date
    amount_pence: int
    account: str
    reference: str | None = None
    description: str
    counterparty: str
    allocations: list[Allocation]  # what it actually paid, after earlier payments and credit notes
    unallocated_pence: int  # left over: a credit on the contact
    cis_deduction_pence: int = 0  # part of amount_pence deducted under CIS instead of paid (app/cis.py)
    event_id: str | None = None
    bank_line_id: str | None = None


class Credit(BaseModel):
    """Money left on a contact's account: an overpayment, or a credit note bigger than what was owed.

    `amount_pence` is what is left after the credit was applied to other documents or refunded."""

    id: str = ""  # "payment:<payment id>" or "credit_note:<event id>" (`credit_id`)
    side: Side
    date: date
    amount_pence: int
    source: Literal["payment", "credit_note"]
    source_id: str  # payment id, or the credit note's event id
    doc_event_id: str  # the document it came with, which says whose credit it is


def credit_id(source: str, source_id: str) -> str:
    return f"{source}:{source_id}"


class CreditUse(BaseModel):
    """A credit on a contact applied to another of its documents, or refunded; stored in credit_uses.json."""

    id: str
    kind: Literal["apply", "refund"]
    side: Side
    date: date
    amount_pence: int = Field(gt=0)
    credit: str  # the Credit's id: "payment:<id>" or "credit_note:<event id>"
    credit_doc_event_id: str = ""  # the document the credit came with (whose contact it is), as it was then
    doc_event_id: str | None = None  # apply: the invoice or bill it pays
    account: str = BANK  # refund: where the money went out (or came in)
    reference: str | None = None
    counterparty: str = ""
    event_id: str | None = None  # refund: Dr 1100 Debtors / Cr 1200 Bank (or the supplier mirror), posted by code
    bank_line_id: str | None = None  # refund: the statement line it went out (or came in) on
    created_by: str
    created_at: datetime
    removed_at: datetime | None = None
    removed_by: str | None = None
    reversal_event_id: str | None = None


class UseShown(BaseModel):
    """A credit use as it worked out: how much of it its credit (and, for "apply", its document) could take."""

    id: str
    kind: Literal["apply", "refund"]
    side: Side
    date: date
    credit: str
    source: Literal["payment", "credit_note"]
    source_id: str
    credit_doc_event_id: str  # the document the credit came with (whose contact it is)
    doc_event_id: str | None
    amount_pence: int  # asked
    applied_pence: int  # what it actually took
    reference: str | None = None
    event_id: str | None = None
    bank_line_id: str | None = None


@dataclass
class Settlement:
    gross: dict[str, int] = field(default_factory=dict)  # live documents on account -> gross
    paid: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    credited: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    payments: list[Payment] = field(default_factory=list)
    credits: list[Credit] = field(default_factory=list)
    credit_notes: dict[str, list[tuple[str, int]]] = field(
        default_factory=lambda: defaultdict(list)
    )  # doc -> [(credit note event id, amount applied)]
    uses: list[UseShown] = field(default_factory=list)  # credits applied or refunded, oldest first
    used: dict[str, int] = field(default_factory=lambda: defaultdict(int))  # credit id -> taken by uses

    def credit(self, cid: str) -> Credit | None:
        return next((c for c in self.credits if c.id == cid), None)

    def uses_for(self, event_id: str) -> list[UseShown]:
        """Credits applied to this document."""
        return [u for u in self.uses if u.kind == "apply" and u.doc_event_id == event_id and u.applied_pence]

    def outstanding(self, event_id: str) -> int:
        return self.gross.get(event_id, 0) - self.paid.get(event_id, 0) - self.credited.get(event_id, 0)

    def payments_for(self, event_id: str) -> list[Payment]:
        return [p for p in self.payments if any(a.event_id == event_id for a in p.allocations)]

    def status(self, event_id: str) -> PaymentStatus:
        settled = self.paid.get(event_id, 0) + self.credited.get(event_id, 0)
        if settled <= 0:
            return "open"
        if self.outstanding(event_id) > 0:
            return "part_paid"
        if any(p.unallocated_pence for p in self.payments_for(event_id)):
            return "overpaid"
        return "paid"


def settle(
    docs: Sequence[Doc],
    bank_lines: Iterable[BankLine],
    records: Iterable[PaymentRecord],
    reversed_ids: set[str],
    uses: Iterable[CreditUse] = (),
) -> Settlement:
    """Allocate every credit note, payment and use of a credit, oldest first (on the same day: credit notes, then
    payments, then uses)."""
    s = Settlement()
    live = {
        d.event.id: d
        for d in docs
        if d.kind == "invoice" and not d.undo and d.on_account and d.event.id not in reversed_ids
    }
    s.gross = {i: d.gross for i, d in live.items()}
    items: list[tuple[date, int, int, object]] = []
    for n, d in enumerate(docs):
        if d.kind == "credit_note" and not d.undo and d.event.id not in reversed_ids:
            items.append((d.event.date, 0, n, d))
    for n, r in enumerate(records):
        if r.removed_at is None and (r.event_id is None or r.event_id not in reversed_ids):
            items.append((r.date, 1, n, r))
    for n, ln in enumerate(bank_lines):
        if ln.status == "matched" and (ids := [i for i in ln.event_ids() if i in live]):
            items.append((ln.date, 1, 10_000_000 + n, (ln, ids)))
    for n, u in enumerate(uses):
        if u.removed_at is None and (u.event_id is None or u.event_id not in reversed_ids):
            items.append((u.date, 2, n, u))
    for _, _, _, item in sorted(items, key=lambda t: t[:3]):
        if isinstance(item, PaymentRecord):
            _record(s, item, live)
        elif isinstance(item, CreditUse):
            _use(s, item, live)
        elif isinstance(item, tuple):
            line, ids = item
            _bank_line(s, line, ids, live)
        else:
            _credit_note(s, item)  # type: ignore[arg-type]
    return s


def _take(s: Settlement, event_id: str, want: int) -> int:
    """How much of `want` the document can still take."""
    return max(0, min(want, s.outstanding(event_id)))


def _credit_note(s: Settlement, cn: Doc) -> None:
    target = cn.credits if cn.credits in s.gross else None
    applied = _take(s, target, cn.gross) if target else 0
    if applied and target:
        s.credited[target] += applied
        s.credit_notes[target].append((cn.event.id, applied))
    if cn.gross - applied > 0 and cn.on_account:
        s.credits.append(
            Credit(
                id=credit_id("credit_note", cn.event.id),
                side=cn.side,
                date=cn.event.date,
                amount_pence=cn.gross - applied,
                source="credit_note",
                source_id=cn.event.id,
                doc_event_id=cn.event.id,
            )
        )


def _record(s: Settlement, r: PaymentRecord, live: dict[str, Doc]) -> None:
    left = r.amount_pence
    done: list[Allocation] = []
    for a in r.allocations:
        if a.event_id not in live:
            continue  # the document was undone or voided since: its share is left over
        got = _take(s, a.event_id, min(a.amount_pence, left))
        if got:
            s.paid[a.event_id] += got
            left -= got
            done.append(Allocation(event_id=a.event_id, amount_pence=got))
    pay = Payment(
        id=r.id,
        source="recorded",
        side=r.side,
        date=r.date,
        amount_pence=r.amount_pence,
        account=r.account,
        reference=r.reference,
        description=("Payment received" if r.side == "sale" else "Payment made")
        + (" (cash)" if r.account == CASH else ""),
        counterparty=r.counterparty,
        allocations=done,
        unallocated_pence=left,
        cis_deduction_pence=r.cis_deduction_pence,
        event_id=r.event_id,
        bank_line_id=r.bank_line_id,
    )
    _add(s, pay, r.allocations[0].event_id)


def _bank_line(s: Settlement, ln: BankLine, ids: list[str], live: dict[str, Doc]) -> None:
    amount = abs(ln.amount_pence)
    owed = [(i, s.outstanding(i)) for i in ids]
    total = sum(o for _, o in owed)
    exact = total > 0 and abs(amount - total) <= PENNY * len(ids)  # nothing owed: all of it is money over
    left = amount
    done: list[Allocation] = []
    for i, o in owed:
        got = o if exact else max(0, min(o, left))
        if got:
            s.paid[i] += got
            left -= got
            done.append(Allocation(event_id=i, amount_pence=got))
    first = live[ids[0]]
    pay = Payment(
        id=ln.id,
        source="bank_line",
        side=first.side,
        date=ln.date,
        amount_pence=amount,
        account=BANK,
        reference=ln.reference,
        description=f"Bank: {ln.description}",
        counterparty=first.name,
        allocations=done,
        unallocated_pence=0 if exact else max(0, left),
        bank_line_id=ln.id,
    )
    _add(s, pay, ids[0])


def _add(s: Settlement, pay: Payment, first_doc: str) -> None:
    s.payments.append(pay)
    if pay.unallocated_pence > 0:
        s.credits.append(
            Credit(
                id=credit_id("payment", pay.id),
                side=pay.side,
                date=pay.date,
                amount_pence=pay.unallocated_pence,
                source="payment",
                source_id=pay.id,
                doc_event_id=first_doc,
            )
        )


def _use(s: Settlement, u: CreditUse, live: dict[str, Doc]) -> None:
    """Take a use out of its credit: an "apply" pays the document (as a payment, or as credit for a credit note's
    credit), a "refund" pays the money back. A use whose credit has gone (removed payment, voided credit note) or
    whose document was undone takes nothing."""
    c = s.credit(u.credit)
    left = c.amount_pence if c and c.side == u.side else 0
    want = min(u.amount_pence, left)
    got = 0
    if u.kind == "refund":
        got = want
    elif u.doc_event_id in live and live[u.doc_event_id].side == u.side:
        got = _take(s, u.doc_event_id, want)
        if got and c:
            if c.source == "payment":
                s.paid[u.doc_event_id] += got
            else:
                s.credited[u.doc_event_id] += got  # shown with its use (`uses_for`), not in `credit_notes`
    if c and got:
        c.amount_pence -= got
        s.used[c.id] += got
        if c.source == "payment" and (p := next((p for p in s.payments if p.id == c.source_id), None)):
            p.unallocated_pence -= got
        if c.amount_pence <= 0:
            s.credits.remove(c)
    source, _, source_id = u.credit.partition(":")
    s.uses.append(
        UseShown(
            id=u.id,
            kind=u.kind,
            side=u.side,
            date=u.date,
            credit=u.credit,
            source="credit_note" if source == "credit_note" else "payment",
            source_id=source_id,
            credit_doc_event_id=c.doc_event_id if c else u.credit_doc_event_id,
            doc_event_id=u.doc_event_id,
            amount_pence=u.amount_pence,
            applied_pence=got,
            reference=u.reference,
            event_id=u.event_id,
            bank_line_id=u.bank_line_id,
        )
    )


async def load_records(books: Books) -> list[PaymentRecord]:
    """payments.json as saved. A row that does not read (hand-edited) is skipped and logged, never fatal."""
    out: list[PaymentRecord] = []
    raw: Any = await books.read_json(PAYMENTS, [])
    for row in raw if isinstance(raw, list) else []:
        try:
            out.append(PaymentRecord.model_validate(row))
        except ValueError:
            log.warning("skipped an unreadable row in %s", PAYMENTS)
    return out


async def load_uses(books: Books) -> list[CreditUse]:
    """credit_uses.json as saved; an unreadable row is skipped and logged."""
    out: list[CreditUse] = []
    raw: Any = await books.read_json(CREDIT_USES, [])
    for row in raw if isinstance(raw, list) else []:
        try:
            out.append(CreditUse.model_validate(row))
        except ValueError:
            log.warning("skipped an unreadable row in %s", CREDIT_USES)
    return out
