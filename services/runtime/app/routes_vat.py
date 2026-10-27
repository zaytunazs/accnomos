"""VAT return from the user's own ledger events — computed by code, never by a model (PRD §3.2)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from accnomos_ledger import LedgerEvent, VatReturn, compute_vat_return
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.books import Books
from app.deadlines import (
    STAGGER_START_MONTH, filing_deadline, period_containing, period_label, previous_period, stagger_of,
)
from app.routes_books import get_books

router = APIRouter(prefix="/books", tags=["vat"])


class VatBox(BaseModel):
    box: int
    label: str
    amount: str  # pounds, as HMRC will receive it (2 dp for 1-5, whole for 6-9)
    entries: int


class VatReturnView(BaseModel):
    period_key: str
    start: date
    end: date
    boxes: list[VatBox]
    event_ids: list[str]
    warnings: list[str]
    hmrc_body: dict
    events_in_period: int


LABELS = {
    1: "VAT due on sales",
    2: "VAT due on acquisitions from NI/EU",
    3: "Total VAT due (1 + 2)",
    4: "VAT reclaimed on purchases",
    5: "Net VAT to pay HMRC (3 − 4)",
    6: "Total sales excluding VAT",
    7: "Total purchases excluding VAT",
    8: "Supplies of goods to NI/EU",
    9: "Acquisitions of goods from NI/EU",
}


def quarter_bounds(today: date) -> tuple[date, date, str]:
    """Default to the last complete calendar quarter (e.g. on 27 Oct → 1 Jul–30 Sep)."""
    this_q_start = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
    prev_q_end = this_q_start - date.resolution  # last day of the previous quarter
    prev_q_start = date(prev_q_end.year, ((prev_q_end.month - 1) // 3) * 3 + 1, 1)
    key = f"{prev_q_start.year % 100:02d}A{(prev_q_start.month - 1) // 3 + 1}"
    return prev_q_start, prev_q_end, key


def period_key_for(start: date) -> str:
    return f"{start.year % 100:02d}A{(start.month - 1) // 3 + 1}"


def box_amounts(ret: VatReturn) -> dict[int, str]:
    """The 9 boxes as HMRC will receive them: pounds to 2 dp for 1-5, whole pounds for 6-9."""
    return {
        1: f"{ret.vat_due_sales:.2f}", 2: f"{ret.vat_due_acquisitions:.2f}", 3: f"{ret.total_vat_due:.2f}",
        4: f"{ret.vat_reclaimed:.2f}", 5: f"{ret.net_vat_due:.2f}", 6: str(ret.total_sales_ex_vat),
        7: str(ret.total_purchases_ex_vat), 8: str(ret.goods_supplied_ni_eu), 9: str(ret.acquisitions_ni_eu),
    }


@router.get("/vat", response_model=VatReturnView)
async def vat_return(
    start: date | None = Query(None),
    end: date | None = Query(None),
    period_key: str | None = Query(None, pattern=r"^[A-Za-z0-9#]{4}$"),  # HMRC period key, e.g. 26A3
    books: Books = Depends(get_books),
) -> VatReturnView:
    if start is None or end is None:
        s, e, k = quarter_bounds(date.today())
        start, end, period_key = start or s, end or e, period_key or k
    period_key = period_key or period_key_for(start)
    events = await books.list_events(start, end)
    ret = compute_vat_return(events, period_key, start, end)
    sales = [e for e in events if e.kind == "sale"]
    purchases = [e for e in events if e.kind == "purchase"]
    counts = {1: len(sales), 2: 0, 3: len(sales), 4: len(purchases), 5: len(events), 6: len(sales), 7: len(purchases), 8: 0, 9: 0}
    amounts = box_amounts(ret)
    return VatReturnView(
        period_key=period_key, start=start, end=end,
        boxes=[VatBox(box=i, label=LABELS[i], amount=amounts[i], entries=counts[i]) for i in range(1, 10)],
        event_ids=ret.event_ids, warnings=ret.warnings, hmrc_body=ret.to_hmrc(finalised=False),
        events_in_period=len(events),
    )


class PeriodDeadline(BaseModel):
    start: date
    end: date
    label: str  # "Jul–Sep 2026"
    period_key: str | None  # calendar quarters only; otherwise HMRC's obligations give the key
    deadline: date  # return and payment due (1 month + 7 days after `end`)
    days_to_end: int  # 0 or less once the period has ended
    days_remaining: int  # until `deadline`; negative when late
    box5: str  # net VAT so far, pounds to 2 dp (absolute, as HMRC takes it)
    box5_direction: Literal["pay", "reclaim", "nil"]
    entries: int  # approved entries counted in the boxes


class Deadlines(BaseModel):
    today: date
    months: int  # 3 quarterly, 1 monthly
    start_month: int  # a month in which a period starts (1-12)
    stagger: int | None  # HMRC stagger 1/2/3 for quarterly returns
    current: PeriodDeadline  # the period we are in now: Box 5 is an estimate so far
    due: PeriodDeadline | None  # the period that has ended but whose return is not yet due, if any
    rule: str = "Return and payment due 1 calendar month and 7 days after the period ends (VAT Notice 700/12)."


def _period_deadline(events: list[LedgerEvent], start: date, end: date, months: int, today: date) -> PeriodDeadline:
    calendar_quarter = months == 3 and start.month in (1, 4, 7, 10)
    key = period_key_for(start) if calendar_quarter else None
    ret = compute_vat_return(events, key or "", start, end)
    diff = ret.total_vat_due - ret.vat_reclaimed
    deadline = filing_deadline(end)
    return PeriodDeadline(
        start=start, end=end, label=period_label(start, end), period_key=key, deadline=deadline,
        days_to_end=(end - today).days, days_remaining=(deadline - today).days, box5=f"{ret.net_vat_due:.2f}",
        box5_direction="pay" if diff > 0 else "reclaim" if diff < 0 else "nil", entries=len(ret.event_ids),
    )


@router.get("/deadlines", response_model=Deadlines)
async def deadlines(
    stagger: int | None = Query(None, ge=1, le=3, description="HMRC stagger 1, 2 or 3 (quarterly)"),
    start_month: int | None = Query(None, ge=1, le=12, description="custom: a month in which a VAT period starts"),
    months: int = Query(3, description="3 for quarterly returns, 1 for monthly"),
    today: date | None = Query(None, description="for previews and tests; defaults to today"),
    books: Books = Depends(get_books),
) -> Deadlines:
    """Current VAT period, the return that is due next, days remaining and the Box 5 estimate (code, not a model)."""
    if months not in (1, 3):
        raise HTTPException(status_code=422, detail="months must be 3 (quarterly) or 1 (monthly)")
    if stagger is not None and start_month is not None and stagger_of(start_month) != stagger:
        raise HTTPException(status_code=400, detail="stagger and start_month disagree; send one of them")
    first = start_month or STAGGER_START_MONTH[stagger or 1]
    today = today or date.today()
    cur_start, cur_end = period_containing(today, first, months)
    prev_start, prev_end = previous_period(cur_start, months)
    events = await books.list_events(prev_start, cur_end)
    due = (
        _period_deadline(events, prev_start, prev_end, months, today)
        if filing_deadline(prev_end) >= today else None
    )
    return Deadlines(
        today=today, months=months, start_month=stagger_of(first) if months == 3 else 1,
        stagger=stagger_of(first) if months == 3 else None,
        current=_period_deadline(events, cur_start, cur_end, months, today), due=due,
    )
