"""Recording and removing payments against sales invoices and bills (the user's action; app/settlement.py works out
what each payment paid).

*Record payment* (and *Mark paid*, which records the balance) posts, by code:

    money in from a customer:  Dr 1200 Bank (or 1210 Cash)  /  Cr 1100 Debtors
    money out to a supplier:   Dr 2100 Creditors            /  Cr 1200 Bank (or 1210 Cash)

as a `bank` event with no VAT (a payment is not a supply, so it never reaches the VAT return), and saves the split
the user chose in _System/Payments/payments.json. When the money is a line on an imported bank statement, the line is
matched to that event, so the Bank page shows it reconciled. Removing a payment appends a reversal of its event (and
unmatches its bank line); nothing is deleted. A bank line matched straight to an invoice on the Bank page is a
payment too, with nothing posted (as before); removing it unmatches the line.

Each document's status (open, part paid, paid, overpaid) is worked out from the allocations; a sales invoice's file
keeps a copy (`paid_pence`, `payment_status`, ...) refreshed whenever a payment, credit note or bank match changes.
"""

from __future__ import annotations

import contextlib
import hashlib
import uuid
from collections.abc import Iterable
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from accnomos_ledger.bank import BankLine
from accnomos_ledger.events import LedgerEvent, Line
from accnomos_ledger.matching import Match
from app.approve import reversal_of
from app.books import BankMatchError, Books, now
from app.books import today as london_today
from app.contacts import Doc, Ledger, documents, load_ledger
from app.invoicing import Invoice, InvoiceError, InvoiceStateError, list_invoices, money, save_invoice
from app.journal import BANK, CASH, CREDITORS, DEBTORS
from app.settlement import PAYMENTS, Allocation, Payment, PaymentRecord, PaymentStatus, Side
from app.validation import Day, Pence, StrictBody

PaymentAccount = Literal["1200 Bank", "1210 Cash"]
MAX_PENCE = 10_000_000_000  # £100m: anything bigger is a typing slip
assert BANK == "1200 Bank" and CASH == "1210 Cash"  # PaymentAccount spells them out for the API schema


class AllocationIn(StrictBody):
    event_id: str = Field(pattern=r"^[0-9a-f]{8,64}$", max_length=64)  # the invoice's or bill's ledger entry
    amount_pence: Pence = Field(gt=0, le=MAX_PENCE)


class PaymentIn(StrictBody):
    side: Side  # "sale": received from a customer; "purchase": paid to a supplier
    date: Day | None = None  # default: the bank line's date, else today
    amount_pence: Pence | None = Field(None, gt=0, le=MAX_PENCE)  # default: the bank line's amount
    account: PaymentAccount = "1200 Bank"
    reference: str | None = Field(None, max_length=120)
    allocations: list[AllocationIn] = Field(min_length=1, max_length=50)
    bank_line_id: str | None = Field(None, pattern=r"^[0-9a-f]{16}$", max_length=16)


class PaymentError(InvoiceError):
    """The payment cannot be recorded or removed as asked."""


def payment_event_id(record_id: str) -> str:
    return hashlib.sha256(f"payment:{record_id}".encode()).hexdigest()[:32]


def payment_event(r: PaymentRecord, user: str, refs: list[str]) -> LedgerEvent:
    memo = "Payment for " + ", ".join(refs) if refs else "Payment"
    if r.side == "sale":
        lines = [
            Line(account=r.account, debit=r.amount_pence, memo=memo),
            Line(account=DEBTORS, credit=r.amount_pence, memo=memo),
        ]
    else:
        lines = [
            Line(account=CREDITORS, debit=r.amount_pence, memo=memo),
            Line(account=r.account, credit=r.amount_pence, memo=memo),
        ]
    return LedgerEvent(
        id=payment_event_id(r.id),
        kind="bank",
        date=r.date,
        lines=lines,
        approved_by=user,
        approved_at=now(),
        net=0,
        vat=0,
        counterparty=r.counterparty,
    )


def _open(ledger: Ledger, side: Side) -> dict[str, Doc]:
    gone = {e.reverses for e in ledger.events if e.reverses}
    return {
        d.event.id: d
        for d in documents(ledger)
        if d.kind == "invoice" and not d.undo and d.on_account and d.side == side and d.event.id not in gone
    }


def _ref(d: Doc) -> str:
    return d.reference or f"{d.name} {d.event.date:%d/%m/%Y}"


async def record_payment(books: Books, body: PaymentIn, user: str, *, today: date | None = None) -> PaymentRecord:
    """Check the split against what is still owed, post the payment, save it, match its bank line.

    Raises PaymentError (a 400) or InvoiceStateError (a 409) when it cannot be recorded."""
    ledger = await load_ledger(books)
    docs = _open(ledger, body.side)
    settled = ledger.settlement()
    if len({a.event_id for a in body.allocations}) != len(body.allocations):
        raise PaymentError("A document is in the split twice")
    chosen: list[Doc] = []
    for a in body.allocations:
        d = docs.get(a.event_id)
        if d is None:
            what = "sales invoice" if body.side == "sale" else "bill on account"
            raise PaymentError(f"No open {what} {a.event_id[:8]}… (it may have been undone)")
        owed = settled.outstanding(a.event_id)
        if owed <= 0:
            by_line = [p for p in settled.payments_for(a.event_id) if p.source == "bank_line"]
            if by_line:
                p = by_line[0]
                raise InvoiceStateError(
                    f"{ledger.refs.get(a.event_id) or _ref(d)} is already paid by the bank line of {p.date:%d/%m/%Y} "
                    f"({money(p.amount_pence)}) matched on the Bank page. Use Post as payment on it to put that "
                    "money in the books, rather than recording it again"
                )
            raise InvoiceStateError(f"{_ref(d)} is already paid")
        if a.amount_pence > owed:
            raise PaymentError(f"{_ref(d)} has {money(owed)} left to pay; put the rest down as an overpayment")
        chosen.append(d)
    if len({d.key for d in chosen}) > 1:
        raise PaymentError("One payment is from one customer (or to one supplier); record the others separately")
    when, amount = body.date, body.amount_pence
    if body.bank_line_id:
        try:
            line = await books.find_bank_line(body.bank_line_id)
        except FileNotFoundError as exc:
            raise PaymentError("No such bank line") from exc
        if line.resolved:
            raise InvoiceStateError("This bank line is already settled; undo that first")
        if (line.amount_pence > 0) != (body.side == "sale"):
            raise PaymentError("That bank line is money " + ("out" if line.amount_pence < 0 else "in"))
        if amount is not None and amount != abs(line.amount_pence):
            raise PaymentError(f"The bank line is {money(abs(line.amount_pence))}, not {money(amount)}")
        amount, when = abs(line.amount_pence), when or line.date
        if body.account != BANK:
            raise PaymentError("A bank statement line is money in 1200 Bank")
    if amount is None:
        raise PaymentError("Say how much was paid")
    split = sum(a.amount_pence for a in body.allocations)
    if split > amount:
        raise PaymentError(f"The split adds up to {money(split)}, more than the payment of {money(amount)}")
    when = when or today or london_today()
    if when < min(d.event.date for d in chosen):
        raise PaymentError("The payment is dated before the document it pays")
    record = PaymentRecord(
        id=uuid.uuid4().hex[:16],
        side=body.side,
        date=when,
        amount_pence=amount,
        account=body.account,
        reference=(body.reference or "").strip() or None,
        counterparty=chosen[0].name,
        allocations=[Allocation(event_id=a.event_id, amount_pence=a.amount_pence) for a in body.allocations],
        bank_line_id=body.bank_line_id,
        created_by=user,
        created_at=now(),
    )
    event = payment_event(record, user, [_ref(d) for d in chosen])
    record.event_id = event.id
    path = await books.post_event(event)
    await books._update_json(PAYMENTS, [], lambda rows: [*(rows or []), record.model_dump(mode="json")])
    if body.bank_line_id:
        try:
            await books.confirm_match(body.bank_line_id, [event.id], user)
        except BankMatchError as exc:  # changed between the check and now: the payment stands, the line stays open
            await books.audit(f"user:{user}", "payment_line_not_matched", {"payment": record.id, "reason": str(exc)})
    await books.audit(
        f"user:{user}",
        "payment_recorded",
        {
            "payment": record.id,
            "event": event.id,
            "event_path": path,
            "side": record.side,
            "amount_pence": record.amount_pence,
            "unallocated_pence": amount - split,
            "documents": [a.event_id for a in body.allocations],
            "invoice": ledger.refs.get(body.allocations[0].event_id),
            "bank_line": body.bank_line_id,
        },
    )
    await sync_invoices(books, {a.event_id for a in body.allocations})
    await books.rebuild_safely(f"user:{user}")
    return record


async def remove_payment(books: Books, payment_id: str, user: str) -> list[str]:
    """Take a payment back: reverse a recorded payment's entry (and unmatch its bank line), or unmatch a bank line
    matched straight to documents. Returns the document event ids it had paid. Raises FileNotFoundError."""
    records = {r.id: r for r in await _records(books)}
    r = records.get(payment_id)
    if r is None:
        return await _unmatch_line(books, payment_id, user)
    if r.removed_at:
        raise InvoiceStateError("This payment has already been removed")
    from app.credits import refuse_while_used, stranded, uses_of

    refuse_while_used(await uses_of(books, "payment", r.id), "this payment")
    if why := await stranded(books, removing=r.id):
        raise InvoiceStateError(why)
    if r.event_id:
        stored = await books.stored_bank_lines()
        lines = [ln for ln in stored if ln.status == "matched" and r.event_id in ln.event_ids()]
        for ln in lines:
            if ln.id != r.bank_line_id:
                raise InvoiceStateError("A bank line is matched to this payment on the Bank page; unmatch it first")
            await books.unmatch(ln.id, user)
        try:
            original = await books.get_event(r.event_id)
        except FileNotFoundError:
            original = None
        if original is not None:
            reversal = reversal_of(original, user)
            with contextlib.suppress(FileExistsError):
                await books.post_event(reversal)
            r.reversal_event_id = reversal.id
    r.removed_at, r.removed_by = now(), user
    payload = r.model_dump(mode="json")
    await books._update_json(
        PAYMENTS, [], lambda rows: [payload if isinstance(x, dict) and x.get("id") == r.id else x for x in rows or []]
    )
    ids = [a.event_id for a in r.allocations]
    await books.audit(
        f"user:{user}",
        "payment_removed",
        {"payment": r.id, "event": r.event_id, "reversal": r.reversal_event_id, "documents": ids},
    )
    await sync_invoices(books, set(ids))
    await books.rebuild_safely(f"user:{user}")
    return ids


async def _unmatch_line(books: Books, line_id: str, user: str) -> list[str]:
    line = await books.find_bank_line(line_id)
    if line.status != "matched":
        raise FileNotFoundError(line_id)
    from app.credits import refuse_while_used, uses_of

    refuse_while_used(await uses_of(books, "payment", line_id), "this bank line")
    ids = line.event_ids()
    await books.unmatch(line_id, user)  # audited there; syncs the invoices
    return ids


async def _records(books: Books) -> list[PaymentRecord]:
    from app.settlement import load_records

    return await load_records(books)


# --------------------------------------------------------------------------- #
# Invoices: their payments, balance and status
# --------------------------------------------------------------------------- #


class InvoicePayment(BaseModel):
    id: str
    # "marked": marked paid before payments were recorded; "credit": a customer's credit (an overpayment of another
    # invoice) applied to this one (app/credits.py; `id` is the use's, Remove takes it back)
    source: Literal["recorded", "bank_line", "marked", "credit"]
    date: date | None
    amount_pence: int  # the whole payment
    applied_pence: int  # the part that paid this invoice
    account: str | None = None
    reference: str | None = None
    description: str


class AppliedCredit(BaseModel):
    number: str | None  # CN-0001
    event_id: str
    applied_pence: int
    use_id: str | None = None  # a credit note raised against another invoice, applied here (app/credits.py)


class InvoiceMoney(BaseModel):
    paid_pence: int
    credited_pence: int
    balance_pence: int  # still owed
    overpaid_pence: int  # money over, left as a credit on the customer
    payment_status: PaymentStatus
    payments: list[InvoicePayment]
    credit_notes: list[AppliedCredit]


def _applied(p: Payment, event_id: str) -> int:
    return sum(a.amount_pence for a in p.allocations if a.event_id == event_id)


def is_marked_paid(inv: Invoice) -> bool:
    """Marked paid before payments were recorded (no amount was kept): shown as paid in full, posted nothing."""
    return inv.status == "paid" and inv.paid_pence is None


def invoice_money(inv: Invoice, ledger: Ledger) -> InvoiceMoney | None:
    """Payments and credit notes against a sent invoice (None for drafts, void invoices and unposted ones)."""
    if inv.status not in ("sent", "paid") or not inv.event_id:
        return None
    s = ledger.settlement()
    eid = inv.event_id
    pays = s.payments_for(eid)
    out = [
        InvoicePayment(
            id=p.id,
            source=p.source,
            date=p.date,
            amount_pence=p.amount_pence,
            applied_pence=_applied(p, eid),
            account=p.account,
            reference=p.reference,
            description=p.description,
        )
        for p in pays
    ]
    for u in s.uses_for(eid):
        if u.source == "payment":
            out.append(
                InvoicePayment(
                    id=u.id,
                    source="credit",
                    date=u.date,
                    amount_pence=u.amount_pence,
                    applied_pence=u.applied_pence,
                    reference=ledger.refs.get(u.credit_doc_event_id),
                    description="Credit applied (overpaid on "
                    + (ledger.refs.get(u.credit_doc_event_id) or "another invoice")
                    + ")",
                )
            )
    paid, credited = s.paid.get(eid, 0), s.credited.get(eid, 0)
    if is_marked_paid(inv) and not paid and not credited:
        owed = inv.total_pence
        out.append(
            InvoicePayment(
                id="marked",
                source="marked",
                date=inv.paid_at,
                amount_pence=owed,
                applied_pence=owed,
                reference=inv.payment_ref,
                description="Marked paid (no payment was recorded)",
            )
        )
        return InvoiceMoney(
            paid_pence=owed,
            credited_pence=0,
            balance_pence=0,
            overpaid_pence=0,
            payment_status="paid",
            payments=out,
            credit_notes=[],
        )
    return InvoiceMoney(
        paid_pence=paid,
        credited_pence=credited,
        balance_pence=max(0, s.outstanding(eid)) if eid in s.gross else 0,
        overpaid_pence=sum(p.unallocated_pence for p in pays),
        payment_status=s.status(eid),
        payments=out,
        credit_notes=[
            AppliedCredit(number=ledger.refs.get(cn_id), event_id=cn_id, applied_pence=amt)
            for cn_id, amt in s.credit_notes.get(eid, [])
        ]
        + [
            AppliedCredit(
                number=ledger.refs.get(u.source_id), event_id=u.source_id, applied_pence=u.applied_pence, use_id=u.id
            )
            for u in s.uses_for(eid)
            if u.source == "credit_note"
        ],
    )


async def sync_invoices(books: Books, event_ids: Iterable[str]) -> None:
    """Refresh the payment copy on the sales invoices behind `event_ids`: paid when nothing is left to pay, sent
    otherwise. Other sent invoices with money against them are refreshed too, because a credit applied to one invoice
    can come from another's payment. Never fails the action that called it (a payment, a credit note, a bank match)."""
    wanted = set(event_ids)
    if not wanted:
        return
    try:
        invoices = [i for i in await list_invoices(books) if i.event_id and i.status in ("sent", "paid")]
        if not invoices:
            return
        ledger = await load_ledger(books)
        for inv in invoices:
            m = invoice_money(inv, ledger)
            if m is None or (is_marked_paid(inv) and m.payments and m.payments[-1].source == "marked"):
                continue
            if inv.event_id not in wanted and inv.paid_pence is None and not m.paid_pence + m.credited_pence:
                continue  # untouched and never paid: no copy to keep
            status = "paid" if m.balance_pence == 0 and (m.paid_pence + m.credited_pence) > 0 else "sent"
            last = max((p.date for p in m.payments if p.date), default=None)
            new = {
                "status": status,
                "paid_pence": m.paid_pence,
                "credited_pence": m.credited_pence,
                "balance_pence": m.balance_pence,
                "payment_status": m.payment_status,
                "paid_at": last if status == "paid" else None,
            }
            if any(getattr(inv, k) != v for k, v in new.items()):
                for k, v in new.items():
                    setattr(inv, k, v)
                await save_invoice(books, inv)
    except (ValueError, OSError):  # a hand-edited file: the figures are worked out again on every read anyway
        return


class OpenDocument(BaseModel):
    event_id: str
    side: Side
    date: date
    reference: str | None
    counterparty: str
    gross_pence: int
    outstanding_pence: int


def open_documents(ledger: Ledger, side: Side) -> list[OpenDocument]:
    """Sales invoices or bills on account with something left to pay, oldest first (for the payment split)."""
    s = ledger.settlement()
    return [
        OpenDocument(
            event_id=d.event.id,
            side=d.side,
            date=d.event.date,
            reference=d.reference,
            counterparty=d.name,
            gross_pence=d.gross,
            outstanding_pence=s.outstanding(d.event.id),
        )
        for d in _open(ledger, side).values()
        if s.outstanding(d.event.id) > 0
    ]


# --------------------------------------------------------------------------- #
# Bank lines and recorded money: one movement is counted once
# --------------------------------------------------------------------------- #
#
# A recorded payment (or a refund of a credit) already posted Dr/Cr 1200 Bank. A bank statement line for that money
# must be matched to the payment's entry, not to the invoice again: matching it to the invoice as well would count
# the money twice (the invoice paid, and the line's amount over as an overpayment). So the Bank page suggests the
# recorded payment for a line of the same amount, and a match to a document already settled is refused with the way
# out named. The reverse: a line matched straight to an invoice on the Bank page can be turned into a recorded
# payment (`payment_from_bank_line`), so it reaches the ledger, instead of being recorded again.

LINK_DAYS_BEFORE, LINK_DAYS_AFTER = 5, 14  # a statement line from 5 days before to 14 days after the recorded date


class MoneyEvent(BaseModel):
    """A posted payment or refund, as a bank line would show it."""

    event_id: str
    kind: Literal["payment", "refund"]
    id: str  # the payment record's id, or the credit use's
    side: Side
    date: date
    bank_pence: int  # signed: money in positive
    account: str
    counterparty: str
    reference: str | None = None

    @property
    def label(self) -> str:
        what = "Recorded payment" if self.kind == "payment" else "Refund of a credit"
        return f"{what} of {money(abs(self.bank_pence))} on {self.date:%d/%m/%Y} ({self.counterparty})"


def money_events(ledger: Ledger) -> dict[str, MoneyEvent]:
    """Standing recorded payments and refunds with a posted entry, by event id."""
    gone = {e.reverses for e in ledger.events if e.reverses}
    out: dict[str, MoneyEvent] = {}
    for r in ledger.records:
        if r.event_id and r.removed_at is None and r.event_id not in gone:
            out[r.event_id] = MoneyEvent(
                event_id=r.event_id,
                kind="payment",
                id=r.id,
                side=r.side,
                date=r.date,
                bank_pence=r.amount_pence if r.side == "sale" else -r.amount_pence,
                account=r.account,
                counterparty=r.counterparty,
                reference=r.reference,
            )
    for u in ledger.uses:
        if u.kind == "refund" and u.event_id and u.removed_at is None and u.event_id not in gone:
            out[u.event_id] = MoneyEvent(
                event_id=u.event_id,
                kind="refund",
                id=u.id,
                side=u.side,
                date=u.date,
                bank_pence=-u.amount_pence if u.side == "sale" else u.amount_pence,
                account=u.account,
                counterparty=u.counterparty,
                reference=u.reference,
            )
    return out


def _matched_ids(ledger: Ledger) -> set[str]:
    return {i for ln in ledger.bank_lines if ln.status == "matched" for i in ln.event_ids()}


def link_candidates(ledger: Ledger, line: BankLine) -> list[MoneyEvent]:
    """Recorded payments and refunds the line could be: same signed amount, in 1200 Bank, not matched to a line,
    dated near the line; nearest first."""
    taken = _matched_ids(ledger)
    out = [
        m
        for m in money_events(ledger).values()
        if m.event_id not in taken
        and m.account == BANK
        and m.bank_pence == line.amount_pence
        and -LINK_DAYS_BEFORE <= (line.date - m.date).days <= LINK_DAYS_AFTER
    ]
    return sorted(out, key=lambda m: (abs((line.date - m.date).days), m.date, m.id))


def settled_documents(ledger: Ledger) -> set[str]:
    """Documents on account with nothing left to pay (payments, credit notes, applied credits or bank matches)."""
    s = ledger.settlement()
    return {i for i in s.gross if s.outstanding(i) <= 0}


def link_suggestions(ledger: Ledger, lines: Iterable[BankLine]) -> list[Match]:
    """A suggested match to the recorded payment (or refund) for each open line that has one; each used once."""
    used: set[str] = set()
    out: list[Match] = []
    for ln in lines:
        if ln.resolved:
            continue
        m = next((m for m in link_candidates(ledger, ln) if m.event_id not in used), None)
        if m is None:
            continue
        used.add(m.event_id)
        out.append(
            Match(
                line_id=ln.id,
                event_id=m.event_id,
                event_ids=[m.event_id],
                score=0.95,
                kind="suggested",
                reasons=[f"{m.label}: link the line to it, so the money is counted once"],
            )
        )
    return out


async def check_match(books: Books, line: BankLine, ids: list[str]) -> None:
    """Refuse a bank match that would count money twice. Raises BankMatchError naming the way out."""
    ledger = await load_ledger(books)
    money_by = money_events(ledger)
    if linked := [money_by[i] for i in ids if i in money_by]:
        if len(ids) != 1:
            raise BankMatchError("Match a recorded payment or refund to its bank line on its own")
        m = linked[0]
        if m.account != BANK:
            raise BankMatchError("That payment was recorded as cash (1210 Cash), not through the bank")
        if m.bank_pence != line.amount_pence:
            raise BankMatchError(
                f"The line is {money(abs(line.amount_pence))} {'in' if line.amount_pence > 0 else 'out'}; {m.label}"
            )
        return
    s = ledger.settlement()
    docs = {d.event.id: d for d in documents(ledger)}
    for i in ids:
        if i not in s.gross or s.outstanding(i) > 0:
            continue
        d = docs[i]
        name = ledger.refs.get(i) or _ref(d)
        recorded = [p for p in s.payments_for(i) if p.source == "recorded" and p.event_id in money_by]
        unlinked = [p for p in recorded if p.event_id not in _matched_ids(ledger)]
        if unlinked:
            p = unlinked[0]
            raise BankMatchError(
                f"{name} is already paid by a payment recorded on {p.date:%d/%m/%Y} ({money(p.amount_pence)}). "
                "Link this line to that recorded payment instead, so the money is counted once"
            )
        raise BankMatchError(f"{name} has nothing left to pay; matching this line to it would be an overpayment")


async def on_line_changed(books: Books, line_id: str, ids: list[str], matched: bool) -> None:
    """Keep a recorded payment's or refund's `bank_line_id` in step with the Bank page (never fails the match)."""
    from app.settlement import CREDIT_USES

    def change(rows: Any) -> Any:
        out = []
        for x in rows if isinstance(rows, list) else []:
            if isinstance(x, dict) and x.get("event_id") in ids and x.get("removed_at") is None:
                if matched:
                    x = {**x, "bank_line_id": line_id}
                elif x.get("bank_line_id") == line_id:
                    x = {**x, "bank_line_id": None}
            out.append(x)
        return out

    try:
        for path in (PAYMENTS, CREDIT_USES):
            if await books.exists(path):
                await books._update_json(path, [], change)
    except (ValueError, OSError):
        return


async def payment_from_bank_line(books: Books, line_id: str, user: str) -> PaymentRecord:
    """Turn a bank line matched straight to invoices or bills on the Bank page into a recorded payment for the same
    split: the line is unmatched, the payment posted (Dr 1200 Bank / Cr 1100 Debtors, or the purchase mirror) and the
    line matched to it. If recording fails, the line is matched back as it was."""
    line = await books.find_bank_line(line_id)
    ledger = await load_ledger(books)
    pay = next((p for p in ledger.settlement().payments if p.source == "bank_line" and p.id == line_id), None)
    if line.status != "matched" or pay is None or not pay.allocations:
        raise PaymentError("This bank line is not matched straight to an invoice or bill")
    amount = abs(line.amount_pence)
    allocations: list[AllocationIn] = []
    left = amount
    for a in pay.allocations:  # a line within a penny pays in full; the payment cannot be split over its amount
        n = min(a.amount_pence, left)
        if n > 0:
            allocations.append(AllocationIn(event_id=a.event_id, amount_pence=n))
            left -= n
    before = line.event_ids()
    await books.unmatch(line_id, user)
    try:
        return await record_payment(
            books,
            PaymentIn(
                side=pay.side,
                amount_pence=None,
                allocations=allocations,
                bank_line_id=line_id,
                reference=line.reference,
            ),
            user,
        )
    except (InvoiceError, BankMatchError):
        await books.confirm_match(line_id, before, user)
        raise
