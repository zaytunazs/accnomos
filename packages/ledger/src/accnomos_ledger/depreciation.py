"""Depreciation of fixed assets, by code: the schedule of charges for one asset. Integer pence, no model.

This is book depreciation for the accounts. It is not tax: capital allowances (AIA, writing-down allowances) are
worked out separately on the tax return, and an asset's tax written-down value is not its book value here.

Methods:
- straight line by **life**: (cost − residual) spread evenly over the life. Each charge is the difference of the
  rounded cumulative amounts, round((cost − residual) × n / periods), so the charges always add up exactly.
- straight line by **rate**: (cost − residual) × rate % a year, the same cumulative rounding, never past the residual.
- reducing balance by **rate**: book value at the start of the period × rate % (÷ 12 for a monthly charge), rounded
  half up, never below the residual. It stops when a charge rounds to nothing.

Frequency: **monthly** charges each calendar month from the month the asset was bought (a full month in the month of
purchase); **yearly** charges once per 12 months from that month, the year ending on the last day of its 12th month.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

Method = Literal["straight_line", "reducing_balance"]
Frequency = Literal["monthly", "yearly"]
MAX_PERIODS = 1200  # 100 years of months: a safety stop for reducing balance, which never quite reaches zero


def _round(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def add_months(d: date, months: int) -> date:
    """First of the month `months` after d's month."""
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    return date(y, m + 1, 1)


def month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


@dataclass(frozen=True)
class Policy:
    method: Method
    frequency: Frequency = "monthly"
    rate_percent: Decimal | None = None  # a year; required for reducing balance, or instead of a life
    life_years: int | None = None  # straight line only
    residual_pence: int = 0

    def __post_init__(self) -> None:
        if self.method == "reducing_balance" and not self.rate_percent:
            raise ValueError("Reducing balance needs a rate")
        if self.method == "straight_line" and not (self.rate_percent or self.life_years):
            raise ValueError("Straight line needs a rate or a life")
        if self.method == "straight_line" and self.rate_percent and self.life_years:
            raise ValueError("Give a rate or a life, not both")
        if self.rate_percent is not None and not (Decimal(0) < self.rate_percent <= Decimal(100)):
            raise ValueError("The rate is a percentage a year, more than 0 and at most 100")
        if self.life_years is not None and not (1 <= self.life_years <= 100):
            raise ValueError("The life is 1 to 100 years")
        if self.residual_pence < 0:
            raise ValueError("The residual value cannot be negative")

    @property
    def per_year(self) -> int:
        return 12 if self.frequency == "monthly" else 1


@dataclass(frozen=True)
class Period:
    index: int  # 1-based
    start: date
    end: date
    charge_pence: int
    accumulated_pence: int
    book_value_pence: int


def period_bounds(first_month: date, index: int, frequency: Frequency) -> tuple[date, date]:
    """(start, end) of period `index` (1-based) for an asset depreciated from `first_month`'s month."""
    step = 1 if frequency == "monthly" else 12
    start = add_months(first_month, (index - 1) * step)
    return start, month_end(add_months(start, step - 1))


def schedule(cost_pence: int, bought: date, policy: Policy, upto: date | None = None) -> list[Period]:
    """Every period from the month `bought` until the asset is written down to its residual value (or until the last
    period ending on or before `upto`)."""
    if cost_pence <= 0:
        raise ValueError("The cost must be more than £0.00")
    if policy.residual_pence > cost_pence:
        raise ValueError("The residual value is more than the cost")
    depreciable = cost_pence - policy.residual_pence
    out: list[Period] = []
    accumulated = 0
    n = 0
    first = date(bought.year, bought.month, 1)
    while accumulated < depreciable and n < MAX_PERIODS:
        n += 1
        start, end = period_bounds(first, n, policy.frequency)
        if upto is not None and end > upto:
            break
        if policy.method == "straight_line":
            if policy.life_years:
                periods = policy.life_years * policy.per_year
                cumulative = _round(Decimal(depreciable) * min(n, periods) / periods)
            else:
                rate = policy.rate_percent or Decimal(0)
                cumulative = min(depreciable, _round(Decimal(depreciable) * rate * n / (100 * policy.per_year)))
            charge = cumulative - accumulated
        else:
            book = cost_pence - accumulated
            rate = policy.rate_percent or Decimal(0)
            charge = min(_round(Decimal(book) * rate / (100 * policy.per_year)), depreciable - accumulated)
        if charge <= 0:
            break
        accumulated += charge
        out.append(Period(n, start, end, charge, accumulated, cost_pence - accumulated))
    return out


@dataclass(frozen=True)
class Disposal:
    book_value_pence: int  # cost − accumulated depreciation at the date of disposal
    gain_pence: int  # proceeds − book value: positive is a gain (a credit), negative a loss (a debit)


def disposal(cost_pence: int, accumulated_pence: int, proceeds_pence: int) -> Disposal:
    if proceeds_pence < 0:
        raise ValueError("Proceeds cannot be negative")
    book = cost_pence - accumulated_pence
    return Disposal(book_value_pence=book, gain_pence=proceeds_pence - book)
