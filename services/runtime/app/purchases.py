"""The user's purchase history, read from their own books: approved ledger events, plus each one's line items.

Spend comes from the ledger only (approved entries, the same sign rule as the VAT return: a supplier's credit note
or an undo counts against the purchase). Line items come from the proposal an event was approved from
(`_System/proposals/{id}.json`, the reading of the receipt or bill), so an entry posted by hand or by a bank rule has
no lines. Nothing here calls a model, and nothing is written.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import date

from accnomos_ledger import LedgerEvent, vat_side
from app.books import Books
from app.schemas import Proposal

#: Ledger accounts that are not where the cost went (money, VAT and balances).
_NOT_COST = re.compile(r"^(?:1\d{3}|2\d{3}|3\d{3}|4\d{3})\b|vat control|bank|creditors|debtors|loan", re.I)


@dataclass(frozen=True)
class ItemLine:
    """One printed line of a receipt or bill, in pence (the reading's 2 dp pounds, converted by code)."""

    description: str
    qty: float
    unit_price_pence: int
    net_pence: int


@dataclass(frozen=True)
class Purchase:
    """One approved purchase (or a reduction of one) as the ledger holds it."""

    event_id: str
    date: date
    supplier: str
    category: str
    net_pence: int  # signed: negative for a credit note or an undo
    vat_pence: int
    source: str  # the event file in the books
    proposal_id: str | None = None
    lines: tuple[ItemLine, ...] = field(default=())

    @property
    def gross_pence(self) -> int:
        return self.net_pence + self.vat_pence


def _pence(pounds: float) -> int:
    return round(float(pounds) * 100)


def category_of(ev: LedgerEvent) -> str:
    """The cost account's name without its number ("5000 Materials" -> "Materials"); the largest one wins."""
    cost = [ln for ln in ev.lines if not _NOT_COST.search(ln.account)]
    if not cost:
        return "Uncategorised"
    top = max(cost, key=lambda ln: ln.debit + ln.credit)
    return re.sub(r"^\d+\s+", "", top.account).strip() or top.account


def supplier_of(ev: LedgerEvent) -> str:
    return (ev.counterparty or "").strip() or "(no name)"


def _lines(p: Proposal | None) -> tuple[ItemLine, ...]:
    if p is None:
        return ()
    return tuple(
        ItemLine(
            description=ln.description.strip(),
            qty=float(ln.qty or 0),
            unit_price_pence=_pence(ln.unit_price),
            net_pence=_pence(ln.net),
        )
        for ln in p.extracted.lines
        if ln.description.strip()
    )


async def _proposal(books: Books, proposal_id: str | None) -> Proposal | None:
    if not proposal_id:
        return None
    try:
        return await books.get_proposal(proposal_id)
    except (FileNotFoundError, ValueError):  # a proposal file removed or hand-edited: the spend still counts
        return None


async def load_purchases(books: Books, start: date, end: date, *, with_lines: bool = True) -> list[Purchase]:
    """Approved purchases dated within [start, end], oldest first, each with its line items when it has any."""
    entries = await books.list_event_entries(start, end)
    picked = [(path, ev, sd[1]) for path, ev in entries if (sd := vat_side(ev)) and sd[0] == "purchases"]
    picked = [(path, ev, sign) for path, ev, sign in picked if ev.net is not None]
    proposals = (
        await asyncio.gather(*(_proposal(books, ev.proposal_id) for _p, ev, _s in picked))
        if with_lines
        else [None] * len(picked)
    )
    undone = {ev.reverses for _p, ev in entries if ev.reverses}
    out = []
    for (path, ev, sign), prop in zip(picked, proposals, strict=True):
        out.append(
            Purchase(
                event_id=ev.id,
                date=ev.date,
                supplier=supplier_of(ev),
                category=category_of(ev),
                net_pence=sign * (ev.net or 0),
                vat_pence=sign * (ev.vat or 0),
                source=path,
                proposal_id=ev.proposal_id,
                # A reversal's lines are the original's, and an undone purchase's prices were never paid.
                lines=_lines(prop) if sign > 0 and ev.id not in undone else (),
            )
        )
    return out
