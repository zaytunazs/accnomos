"""VAT schemes in Settings: GET and PUT /books/vat/schemes. Saved in the user's own books (app/vat_schemes.py)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from accnomos_ledger.vat_schemes import (
    DEFAULT_RELEVANT_GOODS,
    FIRST_YEAR_DISCOUNT,
    LIMITED_COST_RATE,
    annual_period_containing,
    first_anniversary,
    sector_rate,
    span_at,
)
from app.books import Books, now
from app.books import today as current_date
from app.deadlines import add_months
from app.routes_books import get_books, require_user
from app.vat_cycle import VatCycle, vat_cycle
from app.vat_schemes import (
    CHECKED,
    NAMES,
    SCHEMES_PATH,
    SOURCES,
    Check,
    SchemeContext,
    SchemeRuleError,
    VatSchemeSettings,
    capital_candidates,
    check_timeline,
    eligibility,
    load_settings,
    sectors,
    segment_label,
)

router = APIRouter(prefix="/books", tags=["vat"])


class CurrentScheme(BaseModel):
    scheme: Literal["standard", "cash", "flat_rate"]
    label: str
    since: date | None  # None: standard accounting with nothing saved
    cash_basis: bool
    flat_rate_percent: str | None = None  # the sector rate today, before the limited cost test
    first_year_until: date | None = None  # the 1% reduction applies up to and including this day
    limited_cost_rate: str = f"{LIMITED_COST_RATE}"
    annual: bool = False
    annual_period: tuple[date, date] | None = None


class SchemesView(BaseModel):
    settings: VatSchemeSettings
    current: CurrentScheme
    checks: list[Check]
    warnings: list[str] = []  # from the last save: worth a second look, but allowed
    sectors: list[dict[str, str]]
    capital_candidates: list[dict[str, Any]]
    relevant_goods_default: list[str] = list(DEFAULT_RELEVANT_GOODS)
    path: str = SCHEMES_PATH
    sources: dict[str, str] = SOURCES
    checked: str = CHECKED


async def _view(books: Books, ctx: SchemeContext, today: date, warnings: list[str] | None = None) -> SchemesView:
    s = ctx.settings
    span = span_at(ctx.spans, today)
    current = CurrentScheme(
        scheme=span.scheme,
        label=segment_label(span.scheme, span) if span.scheme == "flat_rate" else NAMES[span.scheme],
        since=span.start if s.schemes and span.start != date.min else None,
        cash_basis=span.cash_basis,
    )
    if span.flat_rate is not None:
        current.flat_rate_percent = f"{sector_rate(span.flat_rate.sector, today).normalize():f}"
        if s.registered_on and today < (anniversary := first_anniversary(s.registered_on)):
            current.first_year_until = anniversary - timedelta(days=1)
            current.limited_cost_rate = f"{(LIMITED_COST_RATE - FIRST_YEAR_DISCOUNT).normalize():f}"
    if ctx.annual is not None and (p := annual_period_containing(ctx.annual, today)) is not None:
        current.annual, current.annual_period = True, p
    events = await books.list_events(add_months(date(today.year, today.month, 1), -24), today)
    return SchemesView(
        settings=s,
        current=current,
        checks=eligibility(ctx, events, today),
        warnings=warnings or [],
        sectors=sectors(today),
        capital_candidates=capital_candidates(events, set(s.capital_purchases)),
    )


@router.get("/vat/schemes", response_model=SchemesView)
async def get_schemes(
    today: date | None = Query(None, description="for previews and tests; defaults to today"),
    cycle: VatCycle = Depends(vat_cycle),
    books: Books = Depends(get_books),
) -> SchemesView:
    """The VAT schemes saved for this business, the one in use today, and the eligibility tests from its books."""
    return await _view(books, SchemeContext(await load_settings(books), cycle), today or current_date())


@router.put("/vat/schemes", response_model=SchemesView)
async def put_schemes(
    body: VatSchemeSettings,
    today: date | None = Query(None, description="for previews and tests; defaults to today"),
    cycle: VatCycle = Depends(vat_cycle),
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> SchemesView:
    """Save the VAT schemes (the whole timeline). 400 when HMRC's rules do not allow it, saying which rule."""
    day = today or current_date()
    try:
        warnings = check_timeline(body, cycle, day)
    except SchemeRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    saved = body.model_copy(
        update={"schemes": sorted(body.schemes, key=lambda e: e.start), "updated_at": now(), "updated_by": user}
    )
    await books.write_json(SCHEMES_PATH, saved.model_dump(mode="json", by_alias=True))
    await books.audit(
        f"user:{user}",
        "vat_schemes_saved",
        {
            "path": SCHEMES_PATH,
            "schemes": [{"from": e.start.isoformat(), "scheme": e.scheme} for e in saved.schemes],
            "annual": saved.annual is not None,
        },
    )
    return await _view(books, SchemeContext(saved, cycle), day, warnings)
