"""PayPal in the reports and summaries: the figures, by code, in pence.

One place works out what Home, the dashboard, the cash flow page, the month-end close, the profit answers and Ask
may say about PayPal, so every one of them quotes the same numbers. Nothing here posts anything, and nothing is
estimated or invented: each figure is read from the books (1240 PayPal clearing, 7900 Bank charges entries with PayPal
as the counterparty or posted against 1240), from what Sync PayPal is holding for approval, from PayPal's open
disputes, or from bills the owner approved and planned to pay through PayPal. The words around them are written by
code or, when the owner has an AI set up, by the AI and then checked against these figures.

`PayPalHome` is None when PayPal has nothing to say (no 1240 entries, nothing waiting, no dispute, no planned bill
payment), so books that never use PayPal see no PayPal line anywhere.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Iterable
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, NamedTuple

from pydantic import BaseModel

from accnomos_ledger import LedgerEvent
from app.journal import CATEGORY_ACCOUNTS, PAYPAL_CLEARING

if TYPE_CHECKING:
    from app.books import Books

log = logging.getLogger(__name__)

#: How the 1240 balance is labelled wherever it sits beside the bank balance.
LABEL = "PayPal (books)"
FEES_ACCOUNT = CATEGORY_ACCOUNTS["Bank charges"]  # 7900 Bank charges
DISPUTES_TIMEOUT_S = 4.0
BILL_WINDOWS = (7, 30)


# --------------------------------------------------------------------------- #
# Pure pieces
# --------------------------------------------------------------------------- #


def touches_paypal(ev: LedgerEvent) -> bool:
    """PayPal is the counterparty, or a line of the entry is on 1240 PayPal clearing."""
    return ev.counterparty == "PayPal" or any(ln.account == PAYPAL_CLEARING for ln in ev.lines)


def clearing_balance(events: Iterable[LedgerEvent], as_of: date | None = None) -> int | None:
    """What 1240 PayPal clearing holds by the books (debit minus credit), or None when no entry has ever touched it:
    books that do not use PayPal show no PayPal figure."""
    used = False
    total = 0
    for ev in events:
        if as_of is not None and ev.date > as_of:
            continue
        for ln in ev.lines:
            if ln.account == PAYPAL_CLEARING:
                used = True
                total += ln.debit - ln.credit
    return total if used else None


class Totals(NamedTuple):
    fees_pence: int  # PayPal's fees: 7900 entries from PayPal, reversals netted
    fee_entries: int
    received_pence: int  # money received through PayPal: debits to 1240 that are not reversals


def period_totals(events: Iterable[LedgerEvent]) -> Totals:
    """PayPal's fees and the money received through PayPal over `events` (already limited to the period). The same
    rule as the fees question in Ask (app/paypal_assistant.py `fee_facts`, which uses this): an entry with a 7900
    line counts as a fee, any other PayPal entry that is not a reversal counts what it put into 1240."""
    fees = entries = received = 0
    for ev in events:
        if not touches_paypal(ev):
            continue
        fee = sum(ln.debit - ln.credit for ln in ev.lines if ln.account == FEES_ACCOUNT)
        if fee:
            fees += fee
            entries += 1 if fee > 0 else 0
        elif ev.kind != "reversal":
            received += sum(ln.debit for ln in ev.lines if ln.account == PAYPAL_CLEARING)
    return Totals(fees, entries, received)


def totals_between(events: Iterable[LedgerEvent], start: date, end: date) -> Totals:
    return period_totals(e for e in events if start <= e.date <= end)


# --------------------------------------------------------------------------- #
# What Home and the summaries read
# --------------------------------------------------------------------------- #


class MonthTotals(BaseModel):
    label: str  # "November 2026 so far", "October 2026"
    fees_pence: int
    received_pence: int


class Waiting(BaseModel):
    count: int  # synced from PayPal, proposed, not yet approved
    net_pence: int  # the money in them, net of fees (signed)


class DisputesOpen(BaseModel):
    count: int  # not yet resolved
    needs_reply: int  # waiting for the owner's reply
    amount_pence: int  # what the open ones add up to
    respond_by: date | None = None  # the soonest reply date among those waiting for the owner
    sample: bool = False  # only the demo's SAMPLE dispute


class BillPayments(BaseModel):
    """Bills the owner approved and planned to pay through PayPal, not yet paid or on their way."""

    due_now_count: int
    due_now_pence: int
    within_7_days_count: int  # due after today and within 7 days
    within_7_days_pence: int
    within_30_days_count: int  # due after today and within 30 days (includes the 7)
    within_30_days_pence: int


class PayPalHome(BaseModel):
    balance_pence: int | None  # 1240 PayPal clearing by the books ("PayPal (books)"); None: never used
    this_month: MonthTotals
    last_month: MonthTotals
    waiting: Waiting | None = None
    disputes: DisputesOpen | None = None
    bills: BillPayments | None = None


def _month_label(d: date) -> str:
    return f"{d:%B %Y}"


def has_data(p: PayPalHome) -> bool:
    return bool(
        p.balance_pence is not None
        or p.this_month.fees_pence
        or p.this_month.received_pence
        or p.last_month.fees_pence
        or p.last_month.received_pence
        or p.waiting
        or p.disputes
        or p.bills
    )


async def _waiting(books: Books, demo: bool) -> Waiting | None:
    from app import paypal_sync as ps

    v = await ps.view(books, demo)
    todo = [i for i in v.items if i.status == "proposed"]
    if not todo:
        return None
    return Waiting(count=len(todo), net_pence=sum(i.net_pence for i in todo))


async def _disputes(books: Books, demo: bool) -> DisputesOpen | None:
    from app import paypal_disputes as pd

    got = await asyncio.wait_for(pd.list_disputes(books, sample=demo), DISPUTES_TIMEOUT_S)
    live = [d for d in got.disputes if d.status != "RESOLVED"]
    if not live:
        return None
    mine = [d for d in live if d.status == "WAITING_FOR_SELLER_RESPONSE"]
    dates = [d.respond_by for d in mine if d.respond_by]
    return DisputesOpen(
        count=len(live),
        needs_reply=len(mine),
        amount_pence=sum(d.amount_pence or 0 for d in live),
        respond_by=min(dates, default=None),
        sample=all(d.sample for d in live),
    )


async def bill_payments(books: Books, today: date) -> BillPayments | None:
    """Bills that are open, approved by a person and planned for PayPal (a plan, or the supplier's PayPal email saved),
    that have no payout on its way or paid, by when they fall due. Reads no documents and pays nothing."""
    from app import billpay

    o = await billpay.bills(books, today=today, read_documents=False)
    live = [
        b
        for b in [*o.due, *o.upcoming]
        if b.person_approved
        and b.plan != "not_paypal"
        and (b.payee_email or b.plan == "paypal")
        and not (b.payout and (b.payout.status in billpay.WAITING or b.payout.status == "paid"))
        and b.owed_pence > 0
    ]
    if not live:
        return None
    due_now = [b for b in live if b.due_date <= today]

    def within(days: int) -> list[Any]:
        return [b for b in live if today < b.due_date <= today + timedelta(days=days)]

    w7, w30 = within(BILL_WINDOWS[0]), within(BILL_WINDOWS[1])
    out = BillPayments(
        due_now_count=len(due_now),
        due_now_pence=sum(b.owed_pence for b in due_now),
        within_7_days_count=len(w7),
        within_7_days_pence=sum(b.owed_pence for b in w7),
        within_30_days_count=len(w30),
        within_30_days_pence=sum(b.owed_pence for b in w30),
    )
    return out if out.due_now_count or out.within_30_days_count else None


async def _quietly(name: str, work: Awaitable[Any]) -> Any:
    """One part failing (PayPal slow, a file unreadable) leaves that part out; it never fails Home or a close."""
    try:
        return await work
    except Exception:  # noqa: BLE001
        log.info("paypal reports: %s could not be worked out", name, exc_info=True)
        return None


async def home_figures(
    books: Books, today: date, events: list[LedgerEvent] | None = None, *, demo: bool = False
) -> PayPalHome | None:
    """Everything Home says about PayPal, or None when there is nothing to say. `events`: the ledger, when the caller
    has it. Disputes are asked of PayPal only when PayPal is connected (or the demo); a slow answer is left out."""
    from app import online_payments as op

    events = events if events is not None else await books.list_events()
    first = today.replace(day=1)
    last_end = first - timedelta(days=1)
    this = totals_between(events, first, today)
    last = totals_between(events, last_end.replace(day=1), last_end)
    balance = clearing_balance(events)
    connected = (await op.load_connections(books)).paypal is not None
    waiting = await _quietly("waiting", _waiting(books, demo))
    disputes = await _quietly("disputes", _disputes(books, demo)) if connected or demo else None
    bills = await _quietly("bills", bill_payments(books, today)) if connected or balance is not None else None
    out = PayPalHome(
        balance_pence=balance,
        this_month=MonthTotals(
            label=f"{_month_label(today)} so far", fees_pence=this.fees_pence, received_pence=this.received_pence
        ),
        last_month=MonthTotals(
            label=_month_label(last_end), fees_pence=last.fees_pence, received_pence=last.received_pence
        ),
        waiting=waiting,
        disputes=disputes,
        bills=bills,
    )
    return out if has_data(out) else None


# --------------------------------------------------------------------------- #
# Facts: figures formatted by code, for the summaries' words
# --------------------------------------------------------------------------- #


def home_facts(p: PayPalHome, gbp: Any) -> dict[str, Any]:
    """The facts Home's summary may quote about PayPal: every figure already formatted, nothing the books lack."""
    f: dict[str, Any] = {}
    if p.balance_pence is not None:
        f["balance_by_your_books"] = gbp(p.balance_pence)
        f["balance_label"] = LABEL
    for key, m in (("this_month", p.this_month), ("last_month", p.last_month)):
        if m.fees_pence or m.received_pence:
            f[key] = {"label": m.label, "fees": gbp(m.fees_pence), "received": gbp(m.received_pence)}
    if p.waiting:
        f["waiting_in_sync_paypal"] = {"payments": p.waiting.count, "net": gbp(p.waiting.net_pence)}
    if p.disputes:
        d = p.disputes
        f["open_disputes"] = {
            "count": d.count,
            "waiting_for_your_reply": d.needs_reply,
            "amount": gbp(d.amount_pence),
            **({"reply_by": f"{d.respond_by.day} {d.respond_by:%b %Y}"} if d.respond_by else {}),
        }
    if p.bills:
        b = p.bills
        f["bill_payments_through_paypal"] = {
            **({"due_now": {"bills": b.due_now_count, "amount": gbp(b.due_now_pence)}} if b.due_now_count else {}),
            **(
                {"due_within_7_days": {"bills": b.within_7_days_count, "amount": gbp(b.within_7_days_pence)}}
                if b.within_7_days_count
                else {}
            ),
            **(
                {"due_within_30_days": {"bills": b.within_30_days_count, "amount": gbp(b.within_30_days_pence)}}
                if b.within_30_days_count
                else {}
            ),
        }
    return f


async def close_facts(
    books: Books, start: date, end: date, gbp: Any, events: list[LedgerEvent] | None = None
) -> dict[str, Any]:
    """What the month-end summary may say about PayPal for the month [start, end]: fees, money received, the 1240
    balance at the month end, and what is waiting in Sync PayPal. Empty when PayPal has nothing to say."""
    events = events if events is not None else await books.list_events()
    t = totals_between(events, start, end)
    balance = clearing_balance(events, end)
    waiting = await _quietly("waiting", _waiting(books, False))
    out: dict[str, Any] = {}
    if t.fees_pence or t.received_pence:
        out["fees"] = gbp(t.fees_pence)
        out["received"] = gbp(t.received_pence)
    if balance is not None:
        out["balance_at_month_end"] = gbp(balance)
    if waiting:
        out["waiting_in_sync_paypal"] = waiting.count
    return out
