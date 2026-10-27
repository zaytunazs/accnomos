"""/reports/*: profit and loss, aged balances, VAT summary and monthly trend, by code (app/reports.py).

Same headers as /books/*. The GETs read the ledger and write nothing. `POST /reports/export` (needs `X-User`)
saves one spreadsheet in 07 Reports and an audit line; it never posts to the ledger. VAT settings are the usual
query parameters (`stagger` / `start_month`, `months`; app/vat_cycle.py): they set the default P&L period (the
VAT period we are in now) and the periods in the VAT summary.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import contacts as cb
from app import reports as rp
from app.books import Books
from app.books import today as current_date  # `today` is a query parameter below
from app.deadlines import recent_periods
from app.paths import REPORTS
from app.routes_books import get_books, require_user
from app.validation import Day, StrictBody
from app.vat_cycle import VatCycle, vat_cycle

router = APIRouter(prefix="/reports", tags=["reports"])
TODAY = Query(None, description="for previews and tests; defaults to today")


def _period(cycle: VatCycle, today: date, start: date | None, end: date | None) -> tuple[date, date]:
    if (start is None) != (end is None):
        raise HTTPException(status_code=422, detail="send both 'from' and 'to', or neither")
    if start is None or end is None:
        return cycle.current(today)
    if end < start:
        raise HTTPException(status_code=422, detail="'to' is before 'from'")
    return start, end


@router.get("/pl", response_model=rp.ProfitAndLoss)
async def profit_and_loss(
    start: date | None = Query(None, alias="from", description="ISO date; send with 'to'"),
    end: date | None = Query(None, alias="to", description="ISO date; send with 'from'"),
    today: date | None = TODAY,
    cycle: VatCycle = Depends(vat_cycle),
    books: Books = Depends(get_books),
) -> rp.ProfitAndLoss:
    """Sales, cost of sales and overheads by account, gross and net profit, as approved. Default: this VAT period."""
    s, e = _period(cycle, today or current_date(), start, end)
    return rp.profit_and_loss(await books.list_events(s, e), s, e)


class AgedReport(cb.AgedBalances):
    sample: bool = False


@router.get("/aged", response_model=AgedReport)
async def aged(as_of: date | None = Query(None), books: Books = Depends(get_books)) -> AgedReport:
    """Debtors and creditors by age: the same figures as `GET /contacts/aged`."""
    contacts, ledger, _ = await cb.contact_book(books)
    balances = cb.aged(contacts, ledger, as_of or current_date())
    return AgedReport(**balances.model_dump(), sample=rp.is_sample(ledger.events))


def _spans(cycle: VatCycle, today: date, periods: int) -> list[tuple[date, date]]:
    return recent_periods(today, cycle.start_month, cycle.months, previous=periods - 1)


@router.get("/vat", response_model=rp.VatSummary)
async def vat(
    periods: int = Query(4, ge=1, le=9, description="the current VAT period and the ones before it"),
    today: date | None = TODAY,
    cycle: VatCycle = Depends(vat_cycle),
    books: Books = Depends(get_books),
) -> rp.VatSummary:
    """Boxes 1, 4, 6, 7 and the net VAT per period (compute_vat_return), oldest first."""
    spans = _spans(cycle, today or current_date(), periods)
    events = await books.list_events(spans[-1][0], spans[0][1])
    return rp.vat_summary(events, spans, cycle.months)


@router.get("/trend", response_model=rp.Trend)
async def trend(
    months: int = Query(12, ge=1, le=24),
    today: date | None = TODAY,
    books: Books = Depends(get_books),
) -> rp.Trend:
    """Sales, purchases (cost of sales + overheads) and net per calendar month, ending with this month."""
    last = today or current_date()
    events = await books.list_events(*rp.trend_window(last, months))
    return rp.monthly_trend(events, last, months)


class ExportBody(StrictBody):
    report: rp.ReportKind = "all"
    start: Day | None = Field(None, alias="from")  # the P&L period; default the VAT period we are in now
    end: Day | None = Field(None, alias="to")
    periods: int = Field(4, ge=1, le=9)  # VAT summary
    months: int = Field(12, ge=1, le=24)  # trend


class ExportResult(BaseModel):
    path: str  # "07 Reports/2026-10-27-profit-and-loss.xlsx"
    name: str
    size: int
    web_url: str | None
    sample: bool
    sheets: list[str]
    kind: Literal["xlsx"] = "xlsx"


@router.post("/export", response_model=ExportResult)
async def export(
    body: ExportBody | None = None,
    today: date | None = TODAY,
    cycle: VatCycle = Depends(vat_cycle),
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> ExportResult:
    """Save the report as a spreadsheet in 07 Reports (a same-day file of the same name gets ' (2)'). Posts nothing."""
    body = body or ExportBody.model_validate({})
    day = today or current_date()
    kind = body.report
    ledger = await cb.load_ledger(books)
    events = ledger.events
    pl = aged_now = vat_now = trend_now = None
    if kind in ("pl", "all"):
        s, e = _period(cycle, day, body.start, body.end)
        pl = rp.profit_and_loss(events, s, e)
    if kind in ("aged", "all"):
        contacts, _, _ = await cb.contact_book(books, ledger)
        aged_now = cb.aged(contacts, ledger, day)
    if kind in ("vat", "all"):
        vat_now = rp.vat_summary(events, _spans(cycle, day, body.periods), cycle.months)
    if kind in ("trend", "all"):
        trend_now = rp.monthly_trend(events, day, body.months)
    sample = rp.is_sample(events)
    data, sheets = rp.build_report_xlsx(kind, pl=pl, aged=aged_now, vat=vat_now, trend=trend_now, sample=sample)
    await books.storage.ensure_folder(REPORTS)
    path = await books.free_path(REPORTS, rp.report_filename(kind, day))
    ref = await books.storage.write(path, data)
    await books.audit(f"user:{user}", "report_exported", {"report": kind, "path": path, "sample": sample})
    return ExportResult(
        path=path, name=path.rsplit("/", 1)[1], size=ref.size, web_url=ref.web_url, sample=sample, sheets=sheets
    )
