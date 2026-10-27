"""GET /books/dashboard: the Home tiles in one call, worked out by code from the user's files (app/dashboard.py)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query

from app import dashboard
from app.books import Books, now
from app.routes_books import get_books
from app.routes_vat import vat_period_start

router = APIRouter(prefix="/books", tags=["dashboard"])


@router.get("/dashboard", response_model=dashboard.Dashboard)
async def get_dashboard(
    stagger: int | None = Query(None, ge=1, le=3, description="HMRC stagger 1, 2 or 3, as /books/deadlines"),
    start_month: int | None = Query(None, ge=1, le=12, description="custom: a month in which a VAT period starts"),
    months: int = Query(3, description="3 for quarterly VAT returns, 1 for monthly"),
    today: date | None = Query(None, description="the user's date (Europe/London); defaults to today in UTC"),
    books: Books = Depends(get_books),
) -> dashboard.Dashboard:
    """Cash, owed to and by you, the VAT estimate and deadline, what needs attention, recent activity and the
    last Autopilot, intake and triage runs. Reads only; no model calls."""
    first = vat_period_start(stagger, start_month, months)
    return await dashboard.build(books, today or now().date(), first, months)
