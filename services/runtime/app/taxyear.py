"""The UK personal tax year, 6 April to 5 April: the one place that rule is written.

Used by contacts (year-to-date figures) and mileage (the '2026-27' labels and quarters).
"""

from __future__ import annotations

from datetime import date


def uk_tax_year_start(day: date) -> date:
    """6 April on or before `day`."""
    start = date(day.year, 4, 6)
    return start if day >= start else date(day.year - 1, 4, 6)
