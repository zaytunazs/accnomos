"""VAT period and deadline arithmetic (F12-lite). Pure date maths, no storage, no model.

HMRC staggers for quarterly VAT returns:
    stagger 1: periods end Mar, Jun, Sep, Dec  (quarters start Jan, Apr, Jul, Oct)
    stagger 2: periods end Apr, Jul, Oct, Jan  (quarters start Feb, May, Aug, Nov)
    stagger 3: periods end May, Aug, Nov, Feb  (quarters start Mar, Jun, Sep, Dec)
Return and payment are due one calendar month and seven days after the period ends
(VAT Notice 700/12); periods end on a month end, so that is the last day of the next month + 7 days.
"""

from __future__ import annotations

from datetime import date, timedelta

STAGGER_START_MONTH = {1: 1, 2: 2, 3: 3}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def add_months(first: date, n: int) -> date:
    """The first day of the month `n` months after the month of `first`."""
    index = first.year * 12 + first.month - 1 + n
    return date(index // 12, index % 12 + 1, 1)


def period_containing(day: date, start_month: int, months: int = 3) -> tuple[date, date]:
    """(start, end) of the VAT period that contains `day`. `start_month` is any month a period starts in."""
    offset = (day.month - start_month) % months
    start = add_months(date(day.year, day.month, 1), -offset)
    return start, add_months(start, months) - timedelta(days=1)


def previous_period(start: date, months: int = 3) -> tuple[date, date]:
    return add_months(start, -months), start - timedelta(days=1)


def filing_deadline(period_end: date) -> date:
    """Return and payment due date: one calendar month and seven days after the period end."""
    end_of_next_month = add_months(date(period_end.year, period_end.month, 1), 2) - timedelta(days=1)
    return end_of_next_month + timedelta(days=7)


def stagger_of(start_month: int) -> int:
    """Which HMRC stagger a quarter starting in `start_month` belongs to (1, 2 or 3)."""
    return (start_month - 1) % 3 + 1


def period_label(start: date, end: date) -> str:
    """'Jul–Sep 2026', or 'Dec 2026–Feb 2027' across a year end, or 'Oct 2026' for a month."""
    if (start.year, start.month) == (end.year, end.month):
        return f"{MONTHS[start.month - 1]} {start.year}"
    if start.year == end.year:
        return f"{MONTHS[start.month - 1]}–{MONTHS[end.month - 1]} {end.year}"
    return f"{MONTHS[start.month - 1]} {start.year}–{MONTHS[end.month - 1]} {end.year}"
