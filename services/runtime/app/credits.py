"""Using a credit left on a customer or supplier: apply it to another of their open documents, or refund it.

A credit on a contact (app/settlement.py `Credit`) is money over: an overpayment, or a credit note bigger than what
was owed. The user can

- *Apply credit*: put it towards another open sales invoice (or bill) of the same contact. Nothing is posted: the
  money is already in 1100 Debtors (2100 Creditors) on that contact's side, so only the allocation changes;
- *Refund*: pay it back. Posted by code as a `bank` event with no VAT:

      to a customer:          Dr 1100 Debtors   /  Cr 1200 Bank (or 1210 Cash)
      from a supplier:        Dr 1200 Bank (or 1210 Cash)  /  Cr 2100 Creditors

  When the money is a line on an imported bank statement (money out for a customer refund, money in for a
  supplier's), the line is matched to that event, so the Bank page shows it reconciled.

Both are saved in _System/Payments/credit_uses.json. *Remove* takes one back: an apply is marked removed (the credit
is on account again), a refund's entry is reversed and its bank line unmatched. Nothing is deleted.

While a credit is used, the payment or credit note it came from cannot be removed or voided (remove the use first),
so a refund is never left standing on a credit that has gone.
"""

from __future__ import annotations

import contextlib
import hashlib
import uuid
from datetime import date

from pydantic import Field

from accnomos_ledger.events import LedgerEvent, Line
from app.approve import reversal_of
from app.books import BankMatchError, Books, now
from app.books import today as london_today
from app.contacts import Doc, Ledger, documents, load_ledger
from app.invoicing import InvoiceError, InvoiceStateError, money
from app.journal import BANK, CREDITORS, DEBTORS
from app.payments import PaymentAccount, sync_invoices
from app.settlement import CREDIT_USES, Credit, CreditUse
from app.validation import Day, Pence, StrictBody

MAX_PENCE = 10_000_000_000
CREDIT_ID = r"^(payment|credit_note):[0-9a-f]{8,64}$"


class CreditError(InvoiceError):
    """The credit cannot be applied, refunded or taken back as asked."""


class ApplyIn(StrictBody):
    credit: str = Field(pattern=CREDIT_ID, max_length=80)
    event_id: str = Field(pattern=r"^[0-9a-f]{8,64}$", max_length=64)  # the open invoice or bill
    amount_pence: Pence | None = Field(None, gt=0, le=MAX_PENCE)  # default: as much as both allow
    date: Day | None = None  # default: today


class RefundIn(StrictBody):
    credit: str = Field(pattern=CREDIT_ID, max_length=80)
    amount_pence: Pence | None = Field(None, gt=0, le=MAX_PENCE)  # default: the bank line's, else all of the credit
    date: Day | None = None  # default: the bank line's date, else today
    account: PaymentAccount = "1200 Bank"
    reference: str | None = Field(None, max_length=120)
    bank_line_id: str | None = Field(None, pattern=r"^[0-9a-f]{16}$", max_length=16)


def refund_event_id(use_id: str) -> str:
    return hashlib.sha256(f"refund:{use_id}".encode()).hexdigest()[:32]


def refund_event(u: CreditUse, user: str) -> LedgerEvent:
    memo = "Refund of credit" + (f" {u.reference}" if u.reference else "")
    if u.side == "sale":  # money back to the customer
        lines = [
            Line(account=DEBTORS, debit=u.amount_pence, memo=memo),
            Line(account=u.account, credit=u.amount_pence, memo=memo),
        ]
    else:  # the supplier pays the user back
        lines = [
            Line(account=u.account, debit=u.amount_pence, memo=memo),
            Line(account=CREDITORS, credit=u.amount_pence, memo=memo),
        ]
    return LedgerEvent(
        id=refund_event_id(u.id),
        kind="bank",
        date=u.date,
        lines=lines,
        approved_by=user,
        approved_at=now(),
        net=0,
        vat=0,
        counterparty=u.counterparty,
    )


def _credit(ledger: Ledger, cid: str) -> tuple[Credit, Doc]:
    s = ledger.settlement()
    c = s.credit(cid)
    if c is None or c.amount_pence <= 0:
        raise CreditError("That credit has been used up, or is no longer on the account")
    doc = next((d for d in documents(ledger) if d.event.id == c.doc_event_id), None)
    if doc is None:
        raise CreditError("The document behind that credit is not in the books")
    return c, doc


async def _save(books: Books, u: CreditUse) -> None:
    payload = u.model_dump(mode="json")

    def change(rows: object) -> list[object]:
        rows = rows if isinstance(rows, list) else []
        if any(isinstance(x, dict) and x.get("id") == u.id for x in rows):
            return [payload if isinstance(x, dict) and x.get("id") == u.id else x for x in rows]
        return [*rows, payload]

    await books._update_json(CREDIT_USES, [], change)


async def apply_credit(books: Books, body: ApplyIn, user: str, *, today: date | None = None) -> CreditUse:
    """Put a contact's credit towards another of its open documents. Posts nothing."""
    ledger = await load_ledger(books)
    c, origin = _credit(ledger, body.credit)
    s = ledger.settlement()
    gone = {e.reverses for e in ledger.events if e.reverses}
    target = next(
        (
            d
            for d in documents(ledger)
            if d.event.id == body.event_id and d.kind == "invoice" and not d.undo and d.event.id not in gone
        ),
        None,
    )
    if target is None or not target.on_account:
        raise CreditError("No open invoice or bill on account with that id")
    if target.side != c.side:
        raise CreditError("A customer's credit goes on a sales invoice, a supplier's on a bill")
    if target.key != origin.key:
        raise CreditError(f"That credit is {origin.name}'s; the document is {target.name}'s")
    owed = s.outstanding(target.event.id)
    if owed <= 0:
        raise InvoiceStateError("That document is already paid")
    amount = body.amount_pence or min(owed, c.amount_pence)
    if amount > c.amount_pence:
        raise CreditError(f"The credit has {money(c.amount_pence)} left")
    if amount > owed:
        raise CreditError(f"The document has {money(owed)} left to pay")
    when = body.date or today or london_today()
    if when < max(c.date, target.event.date):
        raise CreditError("The credit is applied before it (or the document) existed")
    u = CreditUse(
        id=uuid.uuid4().hex[:16],
        kind="apply",
        side=c.side,
        date=when,
        amount_pence=amount,
        credit=c.id,
        credit_doc_event_id=c.doc_event_id,
        doc_event_id=target.event.id,
        reference=ledger.refs.get(target.event.id) or target.reference,
        counterparty=target.name,
        created_by=user,
        created_at=now(),
    )
    await _save(books, u)
    await books.audit(
        f"user:{user}",
        "credit_applied",
        {"use": u.id, "credit": c.id, "document": target.event.id, "amount_pence": amount},
    )
    await sync_invoices(books, {target.event.id, c.doc_event_id})
    await books.rebuild_safely(f"user:{user}")
    return u


async def refund_credit(books: Books, body: RefundIn, user: str, *, today: date | None = None) -> CreditUse:
    """Pay a credit back (or record the supplier paying it back): posts the refund, matches its bank line."""
    ledger = await load_ledger(books)
    c, origin = _credit(ledger, body.credit)
    when, amount = body.date, body.amount_pence
    if body.bank_line_id:
        try:
            line = await books.find_bank_line(body.bank_line_id)
        except FileNotFoundError as exc:
            raise CreditError("No such bank line") from exc
        if line.resolved:
            raise InvoiceStateError("This bank line is already settled; undo that first")
        if (line.amount_pence < 0) != (c.side == "sale"):
            want = "money out (to the customer)" if c.side == "sale" else "money in (from the supplier)"
            raise CreditError(f"A refund of this credit is {want}")
        if amount is not None and amount != abs(line.amount_pence):
            raise CreditError(f"The bank line is {money(abs(line.amount_pence))}, not {money(amount)}")
        if body.account != BANK:
            raise CreditError("A bank statement line is money in 1200 Bank")
        amount, when = abs(line.amount_pence), when or line.date
    amount = amount or c.amount_pence
    if amount > c.amount_pence:
        raise CreditError(f"The credit has {money(c.amount_pence)} left; refund no more than that")
    when = when or today or london_today()
    if when < c.date:
        raise CreditError("The refund is dated before the credit existed")
    u = CreditUse(
        id=uuid.uuid4().hex[:16],
        kind="refund",
        side=c.side,
        date=when,
        amount_pence=amount,
        credit=c.id,
        credit_doc_event_id=c.doc_event_id,
        account=body.account,
        reference=(body.reference or "").strip() or None,
        counterparty=origin.name,
        bank_line_id=body.bank_line_id,
        created_by=user,
        created_at=now(),
    )
    event = refund_event(u, user)
    u.event_id = event.id
    path = await books.post_event(event)
    await _save(books, u)
    if body.bank_line_id:
        try:
            await books.confirm_match(body.bank_line_id, [event.id], user)
        except BankMatchError as exc:  # changed meanwhile: the refund stands, the line stays open
            await books.audit(f"user:{user}", "refund_line_not_matched", {"use": u.id, "reason": str(exc)})
    await books.audit(
        f"user:{user}",
        "credit_refunded",
        {
            "use": u.id,
            "credit": c.id,
            "event": event.id,
            "event_path": path,
            "side": u.side,
            "amount_pence": amount,
            "bank_line": body.bank_line_id,
        },
    )
    await sync_invoices(books, {c.doc_event_id})
    await books.rebuild_safely(f"user:{user}")
    return u


async def remove_use(books: Books, use_id: str, user: str) -> CreditUse:
    """Take back an apply or a refund (a refund's entry is reversed, its bank line unmatched).
    Raises FileNotFoundError, InvoiceStateError."""
    from app.settlement import load_uses

    u = next((x for x in await load_uses(books) if x.id == use_id), None)
    if u is None:
        raise FileNotFoundError(use_id)
    if u.removed_at:
        raise InvoiceStateError("This has already been removed")
    if u.event_id:
        for ln in await books.stored_bank_lines():
            if ln.status == "matched" and u.event_id in ln.event_ids():
                await books.unmatch(ln.id, user)
        try:
            original = await books.get_event(u.event_id)
        except FileNotFoundError:
            original = None
        if original is not None:
            reversal = reversal_of(original, user)
            with contextlib.suppress(FileExistsError):
                await books.post_event(reversal)
            u.reversal_event_id = reversal.id
    u.removed_at, u.removed_by = now(), user
    await _save(books, u)
    await books.audit(
        f"user:{user}",
        "credit_use_removed",
        {"use": u.id, "kind": u.kind, "credit": u.credit, "reversal": u.reversal_event_id},
    )
    await sync_invoices(books, {i for i in (u.doc_event_id, u.credit_doc_event_id) if i})
    await books.rebuild_safely(f"user:{user}")
    return u


async def uses_of(books: Books, source: str, source_id: str) -> list[CreditUse]:
    """Standing uses of the credit a payment or a credit note left (so it cannot be removed under them)."""
    from app.settlement import credit_id, load_uses

    cid = credit_id(source, source_id)
    return [u for u in await load_uses(books) if u.credit == cid and u.removed_at is None]


async def uses_on(books: Books, event_id: str) -> list[CreditUse]:
    """Standing applies of a credit to this document."""
    from app.settlement import load_uses

    return [u for u in await load_uses(books) if u.doc_event_id == event_id and u.removed_at is None]


def refuse_while_used(uses: list[CreditUse], what: str) -> None:
    if uses:
        kinds = sorted({"applied to another document" if u.kind == "apply" else "refunded" for u in uses})
        raise InvoiceStateError(
            f"The credit {what} left has been {' and '.join(kinds)}; "
            "remove that first (Contacts → the contact → Credit on account)"
        )
