"""Golden depreciation cases, worked by hand (pence)."""

from datetime import date
from decimal import Decimal

import pytest

from accnomos_ledger.depreciation import Policy, disposal, period_bounds, schedule


def charges(periods):
    return [p.charge_pence for p in periods]


def test_straight_line_life_yearly():
    s = schedule(120_000, date(2026, 4, 15), Policy("straight_line", "yearly", life_years=3))
    assert charges(s) == [40_000, 40_000, 40_000]
    assert (s[0].start, s[0].end) == (date(2026, 4, 1), date(2027, 3, 31))
    assert s[-1].end == date(2029, 3, 31) and s[-1].book_value_pence == 0


def test_straight_line_life_monthly_rounds_cumulatively():
    s = schedule(100_000, date(2026, 1, 31), Policy("straight_line", "monthly", life_years=3))
    assert len(s) == 36
    # 2777.78 -> 2778, 5555.56 -> 5556, 8333.33 -> 8333: charges 2778, 2778, 2777 ...
    assert charges(s)[:3] == [2778, 2778, 2777]
    assert sum(charges(s)) == 100_000
    assert s[0].end == date(2026, 1, 31) and s[1].end == date(2026, 2, 28)


def test_straight_line_rate_with_residual():
    s = schedule(
        600_000, date(2026, 10, 1), Policy("straight_line", "monthly", rate_percent=Decimal(20), residual_pence=100_000)
    )
    assert len(s) == 60
    assert charges(s)[:3] == [8333, 8334, 8333]
    assert s[-1].accumulated_pence == 500_000 and s[-1].book_value_pence == 100_000


def test_reducing_balance_yearly():
    s = schedule(1_000_000, date(2026, 1, 1), Policy("reducing_balance", "yearly", rate_percent=Decimal(25)))
    assert charges(s)[:4] == [250_000, 187_500, 140_625, 105_469]  # 105,468.75 rounds half up
    assert s[3].book_value_pence == 316_406


def test_reducing_balance_monthly():
    s = schedule(1_200_000, date(2026, 6, 10), Policy("reducing_balance", "monthly", rate_percent=Decimal(18)))
    assert charges(s)[:2] == [18_000, 17_730]  # 1.5% a month of the book value


def test_reducing_balance_stops_at_the_residual():
    s = schedule(
        10_000, date(2026, 1, 1), Policy("reducing_balance", "yearly", rate_percent=Decimal(50), residual_pence=2_000)
    )
    assert charges(s) == [5_000, 2_500, 500]
    assert s[-1].book_value_pence == 2_000


def test_upto_stops_at_the_last_period_ended():
    s = schedule(120_000, date(2026, 4, 15), Policy("straight_line", "monthly", life_years=1), upto=date(2026, 6, 30))
    assert [p.end for p in s] == [date(2026, 4, 30), date(2026, 5, 31), date(2026, 6, 30)]
    assert charges(s) == [10_000, 10_000, 10_000]


def test_period_bounds_yearly():
    assert period_bounds(date(2026, 4, 1), 2, "yearly") == (date(2027, 4, 1), date(2028, 3, 31))


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(method="reducing_balance"),
        dict(method="straight_line"),
        dict(method="straight_line", rate_percent=Decimal(10), life_years=5),
        dict(method="straight_line", rate_percent=Decimal(0)),
        dict(method="straight_line", life_years=0),
    ],
)
def test_bad_policies_refused(kwargs):
    with pytest.raises(ValueError):
        Policy(**kwargs)


def test_disposal_gain_and_loss():
    assert disposal(100_000, 60_000, 50_000).gain_pence == 10_000
    loss = disposal(100_000, 60_000, 30_000)
    assert loss.book_value_pence == 40_000 and loss.gain_pence == -10_000
