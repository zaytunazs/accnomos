"""GET /books/dashboard: the Home tiles in one call, worked out by code from the user's files (app/dashboard.py)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from app import dashboard
from app.books import Books, now
from app.routes_books import get_books
from app.vat_cycle import VatCycle, vat_cycle

router = APIRouter(prefix="/books", tags=["dashboard"])


@router.get("/dashboard", response_model=dashboard.Dashboard)
async def get_dashboard(
    cycle: VatCycle = Depends(vat_cycle),  # stagger / start_month / months, as /books/deadlines
    today: date | None = Query(None, description="the user's date (Europe/London); defaults to today in UTC"),
    books: Books = Depends(get_books),
) -> dashboard.Dashboard:
    """Cash, owed to and by you, the VAT estimate and deadline, what needs attention, recent activity and the
    last Autopilot, intake and triage runs. Reads only; no model calls."""
    return await dashboard.build(
        books, today or now().date(), cycle.start_month, cycle.months, vat_assumed=cycle.assumed
    )
