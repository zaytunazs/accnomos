"""GET /books/dashboard: the Home tiles in one call, worked out by code from the user's files (app/dashboard.py)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from accnomos_connectors.base import CalendarProvider
from app import dashboard, home_overview
from app.ai.config import AiConfig
from app.books import Books
from app.books import today as london_today
from app.routes_books import get_books
from app.routes_plan import optional_ai
from app.vat_cycle import VatCycle, vat_cycle

router = APIRouter(prefix="/books", tags=["dashboard"])


async def optional_calendar(request: Request) -> AsyncIterator[CalendarProvider | None]:
    """The user's calendar for Home's clash items, or None: never a 401 (Home works without a calendar). A demo gets
    its in-memory calendar; a token without Calendars.Read fails later, inside the defensive read in
    app/home_overview.py, and Home simply shows no clash."""
    from app import demo
    from app.ai.config import is_test_mode

    if (sandbox := demo.from_request(request)) is not None:
        yield sandbox.calendar
        return
    token = request.headers.get("X-Graph-Token", "").strip().removeprefix("Bearer ").strip()
    if not token:
        yield None
        return
    if is_test_mode():
        from app import testmode

        yield (await testmode.state()).calendar
        return
    from app import accounts

    try:
        provider = accounts.calendar_provider(token, request)  # Google Calendar or Outlook
    except HTTPException:  # no Google Calendar on this server yet: Home simply shows no clash
        yield None
        return
    try:
        yield provider
    finally:
        await provider.aclose()


@router.get("/dashboard", response_model=dashboard.Dashboard)
async def get_dashboard(
    cycle: VatCycle = Depends(vat_cycle),  # stagger / start_month / months, as /books/deadlines
    today: date | None = Query(None, description="the user's date (Europe/London); defaults to today in UTC"),
    books: Books = Depends(get_books),
) -> dashboard.Dashboard:
    """Cash, owed to and by you, the VAT estimate and deadline, what needs attention, recent activity and the
    last Autopilot, intake and triage runs. Reads only; no model calls."""
    return await dashboard.build(
        books, today or london_today(), cycle.start_month, cycle.months, vat_assumed=cycle.assumed
    )


@router.get("/home", response_model=home_overview.Overview)
async def get_home(
    cycle: VatCycle = Depends(vat_cycle),
    today: date | None = Query(None, description="the user's date (Europe/London); defaults to today in UTC"),
    summary_ai: bool = Query(True, description="false: code writes the summary even when an AI is set up"),
    cfg: AiConfig | None = Depends(optional_ai),
    books: Books = Depends(get_books),
    calendar: CalendarProvider | None = Depends(optional_calendar),
) -> home_overview.Overview:
    """Home's other cards (money in and out, this week, aged debts, Income Tax, payroll, CIS, property, deadlines)
    and a two to four sentence summary: code works out every figure; the user's AI, when set up, only words them,
    and code checks the words (app/ai/home_summary.py). Reads only."""
    return await home_overview.build(
        books,
        today or london_today(),
        cycle.start_month,
        cycle.months,
        vat_assumed=cycle.assumed,
        cfg=cfg if summary_ai else None,
        calendar_provider=calendar,
    )
