"""VAT return from the user's own ledger events — computed by code, never by a model (PRD §3.2)."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from accnomos_ledger import LedgerEvent, VatReturn, compute_vat_return, reverses_sale
from app.books import Books
from app.books import today as current_date  # `today` is a query parameter below
from app.deadlines import (
    filing_deadline,
    period_containing,
    period_from_id,
    period_id,
    period_label,
    previous_period,
    recent_periods,
    stagger_of,
)
from app.paths import VAT_RETURNS
from app.routes_books import get_books
from app.vat_cycle import VatCycle, vat_cycle

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
    period: str  # the period used, "2026-Q4" (quarterly) or "2026-11" (monthly)
    label: str  # "Oct–Dec 2026"
    current: bool  # the period we are in now
    submitted: bool  # a relay submission receipt is saved for it
    can_submit: bool  # current or previous period, not yet submitted
    boxes: list[VatBox]
    event_ids: list[str]
    warnings: list[str]
    hmrc_body: dict
    events_in_period: int
    undone_in_period: int  # reversing events among them (each nets off the entry it reverses)


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


def period_key_for(start: date) -> str:
    return f"{start.year % 100:02d}A{(start.month - 1) // 3 + 1}"


def box_amounts(ret: VatReturn) -> dict[int, str]:
    """The 9 boxes as HMRC will receive them: pounds to 2 dp for 1-5, whole pounds for 6-9."""
    return {
        1: f"{ret.vat_due_sales:.2f}",
        2: f"{ret.vat_due_acquisitions:.2f}",
        3: f"{ret.total_vat_due:.2f}",
        4: f"{ret.vat_reclaimed:.2f}",
        5: f"{ret.net_vat_due:.2f}",
        6: str(ret.total_sales_ex_vat),
        7: str(ret.total_purchases_ex_vat),
        8: str(ret.goods_supplied_ni_eu),
        9: str(ret.acquisitions_ni_eu),
    }


async def submitted_periods(books: Books) -> dict[tuple[date, date], str]:
    """{(start, end): HMRC period key} for each return the web app saved after a relay submission
    (`06 VAT returns/{periodKey}/return.json`). The runtime holds no HMRC token, so this is what it can know."""
    try:
        folders = [f for f in await books.storage.list(VAT_RETURNS) if f.is_folder]
    except FileNotFoundError:
        return {}

    async def receipt(folder: str) -> object:
        try:
            return await books.read_json(f"{folder}/return.json", None)
        except ValueError:  # a hand-edited or half-written file: that period just doesn't count as submitted
            return None

    receipts = await asyncio.gather(*(receipt(f.path) for f in folders))
    out: dict[tuple[date, date], str] = {}
    for folder, saved in zip(folders, receipts, strict=True):
        if not isinstance(saved, dict):
            continue
        for span in (saved.get("obligation"), saved.get("calculated_for")):
            if not isinstance(span, dict):
                continue
            try:
                out[(date.fromisoformat(span["start"]), date.fromisoformat(span["end"]))] = str(
                    saved.get("periodKey") or folder.name
                )
            except (KeyError, TypeError, ValueError):
                continue
    return out


def _resolve(
    cycle: VatCycle,
    today: date,
    period: str | None,
    period_start: date | None,
    period_end: date | None,
) -> tuple[date, date]:
    if period_start is not None or period_end is not None:
        if period_start is None or period_end is None:
            raise HTTPException(status_code=422, detail="send both period_start and period_end")
        if period_end < period_start:
            raise HTTPException(status_code=422, detail="period_end is before period_start")
        if period is not None:
            raise HTTPException(status_code=400, detail="send period or period_start/period_end, not both")
        return period_start, period_end
    if period is not None:
        try:
            return period_from_id(period, cycle.start_month, cycle.months)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return cycle.current(today)


def can_submit(start: date, cycle: VatCycle, today: date, submitted: bool) -> bool:
    """Only the current period or the one just before it, and only while it hasn't been submitted."""
    cur_start, _ = cycle.current(today)
    return not submitted and start in (cur_start, previous_period(cur_start, cycle.months)[0])


@router.get("/vat", response_model=VatReturnView)
async def vat_return(
    period_start: date | None = Query(None, description="ISO date; send with period_end"),
    period_end: date | None = Query(None, description="ISO date; send with period_start"),
    period: str | None = Query(
        None, pattern=r"^\d{4}-(Q[1-4]|\d{2})$", description="2026-Q4 (quarterly) or 2026-11 (monthly)"
    ),
    start: date | None = Query(None, include_in_schema=False),  # older clients: same as period_start
    end: date | None = Query(None, include_in_schema=False),
    period_key: str | None = Query(None, pattern=r"^[A-Za-z0-9#]{4}$"),  # HMRC period key, e.g. 26A3
    today: date | None = Query(None, description="for previews and tests; defaults to today"),
    cycle: VatCycle = Depends(vat_cycle),
    books: Books = Depends(get_books),
) -> VatReturnView:
    """The 9 boxes for one period. Default: the period we are in now, by the saved VAT settings."""
    today = today or current_date()
    start, end = _resolve(cycle, today, period, period_start or start, period_end or end)
    period_key = period_key or period_key_for(start)
    events = await books.list_events(start, end)
    ret = compute_vat_return(events, period_key, start, end)
    # A reversal counts against the box it reverses (same predicate as the amounts above).
    sales = [e for e in events if e.kind == "sale" or reverses_sale(e)]
    purchases = [e for e in events if e.kind == "purchase" or (e.kind == "reversal" and not reverses_sale(e))]
    counts = {
        1: len(sales),
        2: 0,
        3: len(sales),
        4: len(purchases),
        5: len(events),
        6: len(sales),
        7: len(purchases),
        8: 0,
        9: 0,
    }
    amounts = box_amounts(ret)
    submitted = (start, end) in await submitted_periods(books)
    return VatReturnView(
        period_key=period_key,
        start=start,
        end=end,
        period=period_id(start, cycle.months),
        label=period_label(start, end),
        current=(start, end) == cycle.current(today),
        submitted=submitted,
        can_submit=can_submit(start, cycle, today, submitted),
        boxes=[VatBox(box=i, label=LABELS[i], amount=amounts[i], entries=counts[i]) for i in range(1, 10)],
        event_ids=ret.event_ids,
        warnings=ret.warnings,
        hmrc_body=ret.to_hmrc(finalised=False),
        events_in_period=len(events),
        undone_in_period=sum(1 for e in events if e.kind == "reversal"),
    )


class VatPeriod(BaseModel):
    period: str  # "2026-Q4" or "2026-11"; pass back as ?period=
    start: date
    end: date
    label: str  # "Oct–Dec 2026"
    current: bool
    deadline: date
    status: Literal["open", "submitted", "none"]  # submitted via the relay / still to file / nothing recorded
    hmrc_period_key: str | None  # from the saved submission receipt
    entries: int  # approved entries dated in the period
    can_submit: bool


class VatPeriods(BaseModel):
    today: date
    months: int
    start_month: int
    periods: list[VatPeriod]  # current first, then the 8 before it
    status_source: str = (
        f"Submitted = a receipt saved in {VAT_RETURNS} after a relay submission; HMRC's own list is in Connect to HMRC."
    )


@router.get("/vat/periods", response_model=VatPeriods)
async def vat_periods(
    today: date | None = Query(None, description="for previews and tests; defaults to today"),
    cycle: VatCycle = Depends(vat_cycle),
    books: Books = Depends(get_books),
) -> VatPeriods:
    """The current VAT period and the 8 before it, with status, so the picker is built by code."""
    today = today or current_date()
    spans = recent_periods(today, cycle.start_month, cycle.months)
    events = await books.list_events(spans[-1][0], spans[0][1])
    submitted = await submitted_periods(books)
    periods = []
    for i, (s, e) in enumerate(spans):
        entries = sum(s <= ev.date <= e for ev in events)
        key = submitted.get((s, e))
        status: Literal["open", "submitted", "none"] = "submitted" if key else "open" if (i == 0 or entries) else "none"
        periods.append(
            VatPeriod(
                period=period_id(s, cycle.months),
                start=s,
                end=e,
                label=period_label(s, e),
                current=i == 0,
                deadline=filing_deadline(e),
                status=status,
                hmrc_period_key=key,
                entries=entries,
                can_submit=can_submit(s, cycle, today, key is not None),
            )
        )
    return VatPeriods(today=today, months=cycle.months, start_month=cycle.start_month, periods=periods)


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
    assumed: bool = False  # no stagger was sent (none saved in Settings): calendar quarters (stagger 1) were assumed
    rule: str = "Return and payment due 1 calendar month and 7 days after the period ends (VAT Notice 700/12)."


def _period_deadline(events: list[LedgerEvent], start: date, end: date, months: int, today: date) -> PeriodDeadline:
    calendar_quarter = months == 3 and start.month in (1, 4, 7, 10)
    key = period_key_for(start) if calendar_quarter else None
    ret = compute_vat_return(events, key or "", start, end)
    diff = ret.total_vat_due - ret.vat_reclaimed
    deadline = filing_deadline(end)
    return PeriodDeadline(
        start=start,
        end=end,
        label=period_label(start, end),
        period_key=key,
        deadline=deadline,
        days_to_end=(end - today).days,
        days_remaining=(deadline - today).days,
        box5=f"{ret.net_vat_due:.2f}",
        box5_direction="pay" if diff > 0 else "reclaim" if diff < 0 else "nil",
        entries=len(ret.event_ids),
    )


@router.get("/deadlines", response_model=Deadlines)
async def deadlines(
    today: date | None = Query(None, description="for previews and tests; defaults to today"),
    cycle: VatCycle = Depends(vat_cycle),
    books: Books = Depends(get_books),
) -> Deadlines:
    """Current VAT period, the return that is due next, days remaining and the Box 5 estimate (code, not a model)."""
    first, months, today = cycle.start_month, cycle.months, today or current_date()
    window = deadline_window(today, first, months)
    return compute_deadlines(await books.list_events(*window), today, first, months, assumed=cycle.assumed)


def deadline_window(today: date, first: int, months: int) -> tuple[date, date]:
    """(start of the previous period, end of the current one): the events `compute_deadlines` needs."""
    cur_start, cur_end = period_containing(today, first, months)
    return previous_period(cur_start, months)[0], cur_end


def compute_deadlines(
    events: list[LedgerEvent], today: date, first: int, months: int, *, assumed: bool = False
) -> Deadlines:
    cur_start, cur_end = period_containing(today, first, months)
    prev_start, prev_end = previous_period(cur_start, months)
    events = [e for e in events if prev_start <= e.date <= cur_end]
    due = _period_deadline(events, prev_start, prev_end, months, today) if filing_deadline(prev_end) >= today else None
    return Deadlines(
        today=today,
        months=months,
        start_month=stagger_of(first) if months == 3 else 1,
        stagger=stagger_of(first) if months == 3 else None,
        current=_period_deadline(events, cur_start, cur_end, months, today),
        due=due,
        assumed=assumed,
    )
