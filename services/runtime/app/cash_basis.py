"""The cash basis: the approved ledger re-dated to when money actually moved. Code, never a model; writes nothing.

From 6 April 2024 the cash basis is the default for sole traders: "With cash basis you only record income or expenses
when you receive money or pay a bill" (gov.uk/simpler-income-tax-cash-basis, checked 28 Oct 2026). Traditional
accounting (accruals) counts them "by the date you invoiced or were billed", which is how the ledger is posted.

`cash_view(ledger)` turns the ledger into a list of *derived* events dated when the money moved, which the
self-employment summary (app/itsa.py) and the P&L (app/reports.py) read exactly as they read the ledger. The ledger
itself is never changed: switching basis changes only what is shown.

    Sales invoice / bill on account     counts when paid: each payment counts on its date, as its share of the
    (Dr 1100 Debtors, Cr 2100 Creditors) document (a £400 part payment of a £1,000 invoice counts 40% of each of its
                                        income or expense lines). Shares are worked out on the running total paid,
                                        so the payments of a fully paid document add up to it exactly.
    Credit note against one             no money moves, so it counts only through what is then paid (an invoice
                                        of £1,000 credited £200 and paid £800 counts £800); when the credit is
                                        refunded, the refund counts on its date as that share of the credit note.
    Anything not on account             counts on its own date as posted: a receipt paid when bought, a cash sale,
                                        a bank-statement line posted to an expense, a credit note settled in cash.
    Journals that touch debtors or      left out and listed (a bad debt written off: income never received is never
    creditors with a P&L line           counted, so writing it off is not an expense under the cash basis).
    Money not allocated to a document   left out and listed (an overpayment sits as a credit on the contact; if it
                                        is later applied to an invoice it counts on the day it was received).

Who paid what comes from app/settlement.py, the same allocation the Contacts and Invoices pages show, so a part
payment, a matched bank line, an applied credit and a refund are counted exactly as they are allocated there.

VAT: the derived events carry only income, expense and asset lines (never 2200 VAT control), so on a VAT-registered
business the figures exclude VAT, which gov.uk allows ("either excluding or including VAT ... you must treat income
and expenses the same way").
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel

from accnomos_ledger import LedgerEvent, Line
from app.contacts import Ledger, documents, reversed_ids
from app.journal import BANK, CREDITORS, DEBTORS
from app.settlement import Payment, Settlement

Basis = Literal["cash", "traditional"]
DEFAULT_BASIS: Basis = "cash"  # HMRC's default for sole traders from 6 April 2024
BASIS_LABEL: dict[Basis, str] = {"cash": "Cash basis", "traditional": "Traditional accounting (accruals)"}

Source = Literal["payment", "bank_line", "applied_credit", "refund", "on_its_date"]


class CashRef(BaseModel):
    """What a derived cash-basis entry came from: the payment and the document it paid, so a box's figure can be
    traced to the money behind it."""

    source: Source
    description: str  # "Payment received", "Bank: FASTER PAYMENT ACME", "Refund paid", ...
    money_pence: int  # the money that moved for this document (positive)
    document_event_id: str | None = None  # the invoice, bill or credit note it settled
    document_ref: str | None = None  # its number (INV-0004) when there is one
    document_gross_pence: int | None = None  # what the document was for, VAT included
    payment_id: str | None = None  # the recorded payment, bank line or credit use


class LeftOut(BaseModel):
    """An entry or an amount the cash basis does not count, listed so nothing goes missing quietly."""

    date: date
    event_id: str | None
    description: str
    pence: int
    reason: str


@dataclass
class CashView:
    events: list[LedgerEvent]  # derived, dated when the money moved; never posted
    refs: dict[str, CashRef] = field(default_factory=dict)  # derived event id -> where it came from
    left_out: list[LeftOut] = field(default_factory=list)


def _counts(account: str) -> bool:
    """Lines that carry income or expense (4xxx-8xxx), or an asset bought (0xxx), or have no code at all. Never the
    money, debtors, creditors, VAT control or capital (1xxx-3xxx)."""
    head = account.strip()[:4]
    if not (len(head) == 4 and head.isdigit()):
        return True
    return not 1000 <= int(head) <= 3999


def _share(amount: int, before: int, after: int, gross: int) -> int:
    """This payment's part of a line: round(amount × after/gross) − round(amount × before/gross), half up, so the
    parts of a fully paid document add up to the line exactly."""

    def r(n: int) -> int:
        return (2 * amount * n + gross) // (2 * gross)

    return r(after) - r(before)


def _derived_id(*parts: str) -> str:
    return "cash-" + hashlib.sha256(":".join(parts).encode()).hexdigest()[:27]


def _derive(
    source: LedgerEvent,
    kind: str,
    day: date,
    before: int,
    after: int,
    gross: int,
    money_account: str,
    counterparty: str | None,
    memo: str,
    id_parts: tuple[str, ...],
) -> LedgerEvent | None:
    """`source`'s counting lines scaled to the share paid between `before` and `after` (of `gross`), balanced by the
    money line. None when every share rounds to nothing."""
    lines: list[Line] = []
    for ln in source.lines:
        if not _counts(ln.account):
            continue
        debit = _share(ln.debit, before, after, gross) if ln.debit else 0
        credit = _share(ln.credit, before, after, gross) if ln.credit else 0
        if debit > 0 or credit > 0:
            lines.append(Line(account=ln.account, debit=debit, credit=credit, vat_code=ln.vat_code, memo=memo))
    if not lines:
        return None
    diff = sum(ln.debit for ln in lines) - sum(ln.credit for ln in lines)
    if diff:
        lines.append(Line(account=money_account, debit=max(0, -diff), credit=max(0, diff), memo=memo))
    if len(lines) < 2:
        return None
    return LedgerEvent(
        id=_derived_id(*id_parts),
        kind=kind,  # type: ignore[arg-type]
        date=day,
        lines=lines,
        evidence=source.evidence,
        approved_by=source.approved_by,
        approved_at=source.approved_at,
        proposal_id=source.proposal_id,
        counterparty=counterparty,
    )


def _on_its_date(e: LedgerEvent) -> str:
    if e.kind == "purchase":
        return "Paid when bought"
    if e.kind == "sale":
        return "Received when sold"
    if e.kind == "bank":
        return "Money in or out on the day"
    if e.kind == "reversal":
        return "Undo or credit note, counted on its date"
    return "Journal, counted on its date"


def cash_view(ledger: Ledger) -> CashView:
    """Every approved entry as the cash basis counts it, dated when the money moved (all dates; callers filter)."""
    view = CashView(events=[])
    docs = documents(ledger)
    s = ledger.settlement()
    undone = reversed_ids(ledger.events)
    doc_of = {d.event.id: d for d in docs}
    on_account = {d.event.id for d in docs if d.on_account}

    # 1. Entries not waiting for money count on their own date, as posted.
    for e in ledger.events:
        if e.id in on_account:
            continue
        touches_account = any(ln.account in (DEBTORS, CREDITORS) for ln in e.lines)
        counting = [ln for ln in e.lines if _counts(ln.account)]
        if not counting:
            continue
        if touches_account:
            if e.id in undone or e.reverses in undone:
                continue  # an undone journal and its undo cancel out: nothing to list
            view.left_out.append(
                LeftOut(
                    date=e.date,
                    event_id=e.id,
                    description=f"Journal on {', '.join(sorted({ln.account for ln in counting}))}",
                    pence=sum(ln.debit - ln.credit for ln in counting),
                    reason="It moves an amount owed (debtors or creditors), not money: under the cash basis only "
                    "money received or paid counts.",
                )
            )
            continue
        view.events.append(e)
        view.refs[e.id] = CashRef(
            source="on_its_date",
            description=_on_its_date(e),
            money_pence=sum(ln.debit for ln in e.lines),  # the entry's total, VAT included
        )

    # 2. Invoices and bills on account: each payment, as its share of the document.
    for doc_id, gross in s.gross.items():
        if gross <= 0:
            continue
        d = doc_of[doc_id]
        paid = 0
        for day, amount, ref in _money_for(s, doc_id):
            event = _derive(
                d.event,
                d.event.kind,
                day,
                paid,
                paid + amount,
                gross,
                ref.payment_account,
                d.name or None,
                f"{ref.description} for {ledger.refs.get(doc_id) or 'this document'}",
                (ref.payment_id, doc_id, str(paid)),
            )
            paid += amount
            if event is None:
                continue
            view.events.append(event)
            view.refs[event.id] = CashRef(
                source=ref.source,
                description=ref.description,
                money_pence=amount,
                document_event_id=doc_id,
                document_ref=ledger.refs.get(doc_id),
                document_gross_pence=gross,
                payment_id=ref.payment_id,
            )

    # 3. Credits refunded: money back to a customer (or from a supplier) counts against income (or expenses) on the
    #    day it moved. A credit note's credit is that share of the credit note; an overpayment refunded was never
    #    counted, so its refund is not either.
    refunded: dict[str, int] = defaultdict(int)
    accounts = {u.id: u.account for u in ledger.uses}
    for u in s.uses:
        if u.kind != "refund" or not u.applied_pence or u.source != "credit_note":
            continue
        cn = doc_of.get(u.source_id)
        if cn is None or cn.gross <= 0:
            continue
        before = refunded[cn.event.id]
        refunded[cn.event.id] += u.applied_pence
        description = "Refund paid" if cn.side == "sale" else "Refund received"
        event = _derive(
            cn.event,
            "reversal",
            u.date,
            before,
            before + u.applied_pence,
            cn.gross,
            accounts.get(u.id, BANK),
            cn.name or None,
            f"{description} for {ledger.refs.get(cn.event.id) or 'a credit note'}",
            (u.id, cn.event.id, str(before)),
        )
        if event is None:
            continue
        view.events.append(event)
        view.refs[event.id] = CashRef(
            source="refund",
            description=description,
            money_pence=u.applied_pence,
            document_event_id=cn.event.id,
            document_ref=ledger.refs.get(cn.event.id),
            document_gross_pence=cn.gross,
            payment_id=u.id,
        )

    # 4. Money with no document to count against (an overpayment still on the contact's account).
    for c in s.credits:
        if c.source == "payment" and c.amount_pence > 0:
            view.left_out.append(
                LeftOut(
                    date=c.date,
                    event_id=None,
                    description=("Money received" if c.side == "sale" else "Money paid")
                    + f" not matched to {'an invoice' if c.side == 'sale' else 'a bill'}",
                    pence=c.amount_pence,
                    reason="It is a credit on the contact's account. Apply it to an invoice or bill, or refund it, "
                    "and it will count.",
                )
            )

    view.events.sort(key=lambda e: (e.date, e.id))
    return view


@dataclass(frozen=True)
class _Money:
    source: Source
    description: str
    payment_id: str
    payment_account: str


def _money_for(s: Settlement, doc_id: str) -> list[tuple[date, int, _Money]]:
    """The money that settled a document, oldest first: payments allocated to it, and overpayments applied to it
    (counted on the day the money came in, which is when it moved)."""
    out: list[tuple[date, int, _Money]] = []
    payments = {p.id: p for p in s.payments}
    for p in s.payments:
        for a in p.allocations:
            if a.event_id == doc_id:
                out.append((p.date, a.amount_pence, _money(p)))
    for u in s.uses_for(doc_id):
        if u.source != "payment":
            continue  # a credit note's credit applied: no money moved
        p = payments.get(u.source_id)
        day = p.date if p else u.date
        out.append(
            (
                day,
                u.applied_pence,
                _Money("applied_credit", "Earlier overpayment applied", u.id, p.account if p else BANK),
            )
        )
    return sorted(out, key=lambda t: t[0])


def document_money(s: Settlement) -> list[tuple[str, date, int]]:
    """(document event id, day, pence) for every amount of money that settled a document on account: the same
    payments, matched bank lines and applied overpayments the cash basis counts, dated when the money moved. VAT
    cash accounting (app/vat_schemes.py) reads this too, so both count the same money on the same day; a credit
    note's credit applied moves no money and is not in it (the scheme engine folds credit notes into the document)."""
    return [(doc_id, day, amount) for doc_id in s.gross for day, amount, _ in _money_for(s, doc_id)]


def _money(p: Payment) -> _Money:
    return _Money("bank_line" if p.source == "bank_line" else "payment", p.description, p.id, p.account)
