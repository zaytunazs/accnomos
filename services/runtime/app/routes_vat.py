"""VAT return from the user's own ledger events — computed by code, never by a model (PRD §3.2)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from accnomos_ledger import LedgerEvent, SchemeBooks, VatReturn, compute_vat_return, vat_side
from app.approve import submitted_spans
from app.books import Books
from app.books import today as current_date  # `today` is a query parameter below
from app.deadlines import (
    period_label,
    stagger_of,
)
from app.paths import SYSTEM, VAT_RETURNS
from app.routes_books import get_books, require_feature, require_user
from app.vat_cycle import VatCycle, vat_cycle
from app.vat_schemes import (
    InstalmentView,
    SchemeContext,
    SchemeView,
    annual_view,
    books_from_events,
    scheme_books,
    scheme_context,
    scheme_return,
    scheme_view,
)

#: HMRC obligations the web app fetched through the relay and posted back, so a return
#: filed elsewhere still shows as submitted. The runtime holds no HMRC token; this file
#: is the only thing it can know about HMRC's own list.
OBLIGATIONS_PATH = f"{SYSTEM}/vat/obligations.json"

router = APIRouter(prefix="/books", tags=["vat"])


class VatBox(BaseModel):
    box: int
    label: str
    amount: str  # pounds, as HMRC will receive it (2 dp for 1-5, whole for 6-9)
    entries: int


class HmrcObligation(BaseModel):
    """One HMRC VAT obligation, as the relay returns it. Posted by the web app after it
    fetches obligations through the relay (the runtime holds no HMRC token)."""

    model_config = ConfigDict(extra="forbid")

    periodKey: str = Field(pattern=r"^[A-Za-z0-9#]{4}$", max_length=4)
    start: date
    end: date
    due: date
    status: Literal["O", "F"]  # open / fulfilled
    received: date | None = None  # when HMRC received the return, for fulfilled ones

    @model_validator(mode="after")
    def _dates_add_up(self) -> HmrcObligation:
        if self.end < self.start:
            raise ValueError("end is before start")
        return self


class ObligationsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    obligations: list[HmrcObligation]


class VatAdjustment(BaseModel):
    """A manual journal with VAT, its auto-reversal or void, or a VAT recode, counted in this return."""

    event_id: str
    date: date
    name: str  # "Journal MJ-0001", or what the entry names
    note: str | None  # the narration (the memo on its first line)
    side: Literal["sales", "purchases"]  # boxes 1 and 6, or boxes 4 and 7
    net_pence: int  # signed, as it counts in box 6 or 7
    vat_pence: int  # signed, as it counts in box 1 or 4


class VatReturnView(BaseModel):
    period_key: str
    start: date
    end: date
    period: str  # the period used, "2026-Q4" (quarterly) or "2026-11" (monthly)
    label: str  # "Oct–Dec 2026"
    current: bool  # the period we are in now
    submitted: bool  # HMRC says fulfilled, or a relay submission receipt is saved for it
    submitted_source: Literal["hmrc", "accnomos"] | None = None  # who says it is submitted
    received: date | None = None  # when HMRC received the return, when it says fulfilled
    can_submit: bool  # current or previous period, not yet submitted
    boxes: list[VatBox]
    event_ids: list[str]
    warnings: list[str]
    hmrc_body: dict
    events_in_period: int
    undone_in_period: int  # reversing events among them (each nets off the entry it reverses)
    adjustments: list[VatAdjustment] = []  # journals and recodes in the boxes, listed on the VAT page
    scheme: SchemeView | None = None  # flat rate, cash or annual accounting in use: how the boxes were worked out


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
    return await submitted_spans(books)


async def read_obligations(books: Books) -> list[HmrcObligation]:
    """HMRC's own obligations list, as the web app last posted it. A missing, corrupt or
    hand-edited file means no obligations, never a 500 — receipts still count on their own."""
    try:
        raw = await books.read_json(OBLIGATIONS_PATH, None)
    except ValueError:
        return []
    if isinstance(raw, list):
        raw = {"obligations": raw}
    if not isinstance(raw, dict) or not isinstance(raw.get("obligations"), list):
        return []
    out = []
    for item in raw["obligations"]:
        try:
            out.append(HmrcObligation.model_validate(item))
        except ValueError:
            continue  # one bad row must not hide the rest, or the receipts
    return out


def _resolve(
    ctx: SchemeContext,
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
            return ctx.period_from_id(period)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ctx.current(today)


def can_submit(start: date, ctx: SchemeContext, today: date, submitted: bool) -> bool:
    """Only the current period or the one just before it, and only while it hasn't been submitted."""
    cur_start, _ = ctx.current(today)
    return not submitted and start in (cur_start, ctx.previous(cur_start)[0])


@router.get("/vat", response_model=VatReturnView, dependencies=[require_feature("vat")])
async def vat_return(
    period_start: date | None = Query(None, description="ISO date; send with period_end"),
    period_end: date | None = Query(None, description="ISO date; send with period_start"),
    period: str | None = Query(
        None,
        pattern=r"^\d{4}-(Q[1-4]|\d{2}|Y\d{2})$",
        description="2026-Q4 (quarterly), 2026-11 (monthly) or 2026-Y01 (an annual period starting January 2026)",
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
    ctx = await scheme_context(books, cycle)
    start, end = _resolve(ctx, today, period, period_start or start, period_end or end)
    period_key = period_key or period_key_for(start)
    scheme: SchemeView | None = None
    if ctx.settings.in_use:
        sb = await scheme_books(books, ctx, start, end)
        events = [e for e in sb.events if start <= e.date <= end]
        out = scheme_return(sb, ctx, period_key, start, end)
        ret, scheme = out.ret, scheme_view(ctx, out, start, end)
        ret.warnings = ret.warnings + out.warnings
        pool = sb.events
    else:
        events = await books.list_events(start, end)
        ret = compute_vat_return(events, period_key, start, end)
        pool = events
    # The entries behind each box are the ones the boxes were summed from, on the side accnomos_ledger.vat_side puts
    # them (as both engines do): sales, purchases, reversals and credit notes on the side they net off, and journals
    # and recodes with VAT on theirs.
    counted_ids = set(ret.event_ids)
    counted = [e for e in pool if e.id in counted_ids]
    sales = sum(1 for e in counted if (vat_side(e) or ("purchases", -1))[0] == "sales")
    purchases = len(counted) - sales
    counts = {1: sales, 2: 0, 3: sales, 4: purchases, 5: sales + purchases, 6: sales, 7: purchases, 8: 0, 9: 0}
    adjustments = [
        VatAdjustment(
            event_id=e.id,
            date=e.date,
            name=e.counterparty or "Adjustment",
            note=next((ln.memo for ln in e.lines if ln.memo), None),
            side=e.vat_box,
            net_pence=e.net or 0,
            vat_pence=e.vat or 0,
        )
        for e in counted
        if e.kind == "adjustment" and e.vat_box
    ]
    amounts = box_amounts(ret)
    receipt_key = (await submitted_periods(books)).get((start, end))
    fulfilled = next(
        (o for o in await read_obligations(books) if (o.start, o.end) == (start, end) and o.status == "F"), None
    )
    if fulfilled is not None:
        period_key, submitted, source, received = fulfilled.periodKey, True, "hmrc", fulfilled.received
    elif receipt_key is not None:
        submitted, source, received = True, "accnomos", None
    else:
        submitted, source, received = False, None, None
    return VatReturnView(
        period_key=period_key,
        start=start,
        end=end,
        period=ctx.period_id(start, end),
        label=period_label(start, end),
        current=(start, end) == ctx.current(today),
        submitted=submitted,
        submitted_source=source,
        received=received,
        can_submit=can_submit(start, ctx, today, submitted),
        boxes=[VatBox(box=i, label=LABELS[i], amount=amounts[i], entries=counts[i]) for i in range(1, 10)],
        event_ids=ret.event_ids,
        warnings=ret.warnings,
        hmrc_body=ret.to_hmrc(finalised=False),
        events_in_period=len(events),
        undone_in_period=sum(1 for e in events if e.kind == "reversal"),
        adjustments=sorted(adjustments, key=lambda a: (a.date, a.name)),
        scheme=scheme,
    )


class VatPeriod(BaseModel):
    period: str  # "2026-Q4", "2026-11" or "2026-Y01" (annual); pass back as ?period=
    start: date
    end: date
    label: str  # "Oct–Dec 2026"
    current: bool
    deadline: date
    status: Literal["open", "submitted", "none"]  # submitted via HMRC or a receipt / still to file / nothing recorded
    hmrc_period_key: str | None  # HMRC's key when its dates match, else from the saved submission receipt
    submitted_source: Literal["hmrc", "accnomos"] | None = None  # who says it is submitted
    received: date | None = None  # when HMRC received the return, when it says fulfilled
    entries: int  # approved entries dated in the period
    can_submit: bool
    annual: bool = False  # an annual accounting period (one return a year)


class VatPeriods(BaseModel):
    today: date
    months: int
    start_month: int
    periods: list[VatPeriod]  # current first, then the 8 before it
    warnings: list[str] = []  # e.g. our periods do not match the ones HMRC holds
    status_source: str = (
        "Submitted = HMRC marks the obligation fulfilled, or a receipt saved in "
        f"{VAT_RETURNS} after a relay submission; HMRC's own list is in Connect to HMRC."
    )


@router.get("/vat/periods", response_model=VatPeriods, dependencies=[require_feature("vat")])
async def vat_periods(
    today: date | None = Query(None, description="for previews and tests; defaults to today"),
    cycle: VatCycle = Depends(vat_cycle),
    books: Books = Depends(get_books),
) -> VatPeriods:
    """The current VAT period and the 8 before it, with status, so the picker is built by code."""
    today = today or current_date()
    ctx = await scheme_context(books, cycle)
    spans = ctx.recent(today)
    events = await books.list_events(spans[-1][0], spans[0][1])
    submitted = await submitted_periods(books)
    obligations = {(o.start, o.end): o for o in await read_obligations(books)}
    warnings = [
        f"HMRC holds a VAT period {o.start.day} {o.start.strftime('%b %Y')} to {o.end.day} {o.end.strftime('%b %Y')} "
        "that does not match your VAT periods in Accnomos. Check your VAT period setting in Settings › Business — "
        "the dates HMRC holds decide what you can file."
        for o in obligations.values()
        if (o.start, o.end) not in spans
    ]
    periods = []
    for i, (s, e) in enumerate(spans):
        entries = sum(s <= ev.date <= e for ev in events)
        match = obligations.get((s, e))
        fulfilled = match if match is not None and match.status == "F" else None
        key = (fulfilled.periodKey if fulfilled else None) or submitted.get((s, e))
        source: Literal["hmrc", "accnomos"] | None = "hmrc" if fulfilled else ("accnomos" if key is not None else None)
        status: Literal["open", "submitted", "none"] = "submitted" if key else "open" if (i == 0 or entries) else "none"
        periods.append(
            VatPeriod(
                period=ctx.period_id(s, e),
                start=s,
                end=e,
                label=period_label(s, e),
                current=i == 0,
                deadline=fulfilled.due if fulfilled else ctx.deadline(s, e),
                status=status,
                hmrc_period_key=key,
                submitted_source=source,
                received=fulfilled.received if fulfilled else None,
                entries=entries,
                can_submit=can_submit(s, ctx, today, key is not None),
                annual=ctx.is_annual(s, e),
            )
        )
    return VatPeriods(
        today=today, months=cycle.months, start_month=cycle.start_month, periods=periods, warnings=warnings
    )


@router.post("/vat/obligations", status_code=201, dependencies=[require_feature("vat")])
async def post_obligations(
    body: ObligationsBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> dict:
    """Store HMRC's obligations list, fetched by the web app through the relay. Validated
    (periodKey, start, end, due, status O/F, received); replaces what was stored before."""
    await books.write_json(
        OBLIGATIONS_PATH,
        {
            "obligations": [o.model_dump(mode="json") for o in body.obligations],
            "updated_at": current_date().isoformat(),
        },
    )
    return {"stored": len(body.obligations)}


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
    annual: bool = False  # the current period is an annual accounting period
    instalments: list[InstalmentView] = []  # annual accounting: the interim payments for the current period
    rule: str = "Return and payment due 1 calendar month and 7 days after the period ends (VAT Notice 700/12)."


ANNUAL_RULE = (
    "Annual accounting: one return a year, due with the balancing payment 2 months after the period ends (1 month for "
    "a period under 4 months); interim payments at the end of months 4-12, or 4, 7 and 10 (VAT Notice 732)."
)


def _period_deadline(ret: VatReturn, start: date, end: date, key: str | None, due: date, today: date) -> PeriodDeadline:
    diff = ret.total_vat_due - ret.vat_reclaimed
    return PeriodDeadline(
        start=start,
        end=end,
        label=period_label(start, end),
        period_key=key,
        deadline=due,
        days_to_end=(end - today).days,
        days_remaining=(due - today).days,
        box5=f"{ret.net_vat_due:.2f}",
        box5_direction="pay" if diff > 0 else "reclaim" if diff < 0 else "nil",
        entries=len(ret.event_ids),
    )


@router.get("/deadlines", response_model=Deadlines, dependencies=[require_feature("vat")])
async def deadlines(
    today: date | None = Query(None, description="for previews and tests; defaults to today"),
    cycle: VatCycle = Depends(vat_cycle),
    books: Books = Depends(get_books),
) -> Deadlines:
    """Current VAT period, the return that is due next, days remaining and the Box 5 estimate (code, not a model)."""
    today = today or current_date()
    ctx = await scheme_context(books, cycle)
    window = deadline_window(today, ctx)
    sb = await scheme_books(books, ctx, *window) if ctx.settings.in_use else None
    events = list(sb.events) if sb is not None else await books.list_events(*window)
    return compute_deadlines(
        events, today, cycle.start_month, cycle.months, assumed=cycle.assumed, ctx=ctx, scheme_books=sb
    )


def deadline_window(today: date, ctx: SchemeContext) -> tuple[date, date]:
    """(start of the previous period, end of the current one): the events `compute_deadlines` needs."""
    cur_start, cur_end = ctx.current(today)
    return ctx.previous(cur_start)[0], cur_end


def compute_deadlines(
    events: list[LedgerEvent],
    today: date,
    first: int,
    months: int,
    *,
    assumed: bool = False,
    ctx: SchemeContext | None = None,
    scheme_books: SchemeBooks | None = None,
) -> Deadlines:
    """Box 5 so far for the current period and the one before it, under the saved VAT schemes when `ctx` has any."""
    ctx = ctx or SchemeContext(cycle=VatCycle(first, months, assumed))
    cur_start, cur_end = ctx.current(today)
    prev_start, prev_end = ctx.previous(cur_start)
    in_use = ctx.settings.in_use
    events = [e for e in events if prev_start <= e.date <= cur_end]
    sb = (scheme_books or books_from_events(ctx, events)) if in_use else None

    def one(start: date, end: date) -> PeriodDeadline:
        calendar_quarter = months == 3 and start.month in (1, 4, 7, 10) and not ctx.is_annual(start, end)
        key = period_key_for(start) if calendar_quarter else None
        if sb is not None:
            ret = scheme_return(sb, ctx, key or "", start, end).ret
        else:
            ret = compute_vat_return(events, key or "", start, end)
        return _period_deadline(ret, start, end, key, ctx.deadline(start, end), today)

    annual = ctx.is_annual(cur_start, cur_end)
    plan = annual_view(ctx, cur_start, cur_end, 0) if annual else None
    return Deadlines(
        today=today,
        months=months,
        start_month=stagger_of(first) if months == 3 else 1,
        stagger=stagger_of(first) if months == 3 else None,
        current=one(cur_start, cur_end),
        due=one(prev_start, prev_end) if ctx.deadline(prev_start, prev_end) >= today else None,
        assumed=assumed,
        annual=annual,
        instalments=plan.instalments if plan else [],
        **({"rule": ANNUAL_RULE} if annual else {}),
    )
