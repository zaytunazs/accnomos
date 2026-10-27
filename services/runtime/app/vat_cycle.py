"""The business's VAT periods as the app's Settings keep them, read from the query string.

Same parameters as `GET /books/deadlines`: `stagger` (1-3), or `start_month` (1-12) for a custom stagger,
and `months` (3 quarterly, 1 monthly). Nothing sent means calendar quarters (stagger 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException, Query

from app.deadlines import STAGGER_START_MONTH, period_containing, stagger_of


@dataclass(frozen=True)
class VatCycle:
    """The business's VAT periods as saved in the app's Settings: a month a period starts in, and 3 or 1 months."""

    start_month: int = 1
    months: int = 3

    def current(self, today: date) -> tuple[date, date]:
        return period_containing(today, self.start_month, self.months)


def vat_cycle(
    stagger: int | None = Query(None, ge=1, le=3, description="HMRC stagger 1, 2 or 3 (quarterly)"),
    start_month: int | None = Query(None, ge=1, le=12, description="custom: a month in which a VAT period starts"),
    months: int = Query(3, description="3 for quarterly returns, 1 for monthly"),
) -> VatCycle:
    """The same VAT settings `/books/deadlines` takes; with none sent, calendar quarters (stagger 1)."""
    if months not in (1, 3):
        raise HTTPException(status_code=422, detail="months must be 3 (quarterly) or 1 (monthly)")
    if stagger is not None and start_month is not None and stagger_of(start_month) != stagger:
        raise HTTPException(status_code=400, detail="stagger and start_month disagree; send one of them")
    return VatCycle(start_month or STAGGER_START_MONTH[stagger or 1], months)
