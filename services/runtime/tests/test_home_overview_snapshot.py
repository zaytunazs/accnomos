"""Home's business snapshot (app/home_overview.py): the year to date against last year, the 12-month trend, the cash
forecast line and the summary facts they add. Code only; no model.

The ledger below (pence, no VAT so the P&L is the lines themselves), books for a company, today 2 Nov 2026:

    date         account                      this year (1 Jan – 2 Nov 2026)   last year (1 Jan – 2 Nov 2025)
    10 Mar 2025  4000 Sales        100,000                                    100,000
    11 Mar 2025  5000 Materials     40,000                                     40,000
    20 Dec 2025  4000 Sales        999,999   (after 2 Nov 2025: in neither span)
    15 May 2026  4000 Sales         80,000    80,000
    16 May 2026  7500 Office        10,000    10,000
    20 Sep 2026  4000 Sales         32,000    32,000
    21 Sep 2026  5000 Materials     20,000    20,000
     1 Oct 2026  6200 Advertising    5,000     5,000
     3 Nov 2026  4000 Sales         50,000   (after today: in neither)

    Turnover    112,000 against 100,000: up 12%
    Expenses     35,000 against  40,000: down 12.5%, rounded half up (on its size) to down 13%
    Net profit   77,000 against  60,000: up 28.33% -> 28%
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

import pytest

from accnomos_ledger import LedgerEvent, Line
from app import cashflow as cf
from app import dashboard as dash
from app import home_overview as ho
from app import reports as rp
from app.ai import home_summary as hs
from app.ai.ask import KnownNumbers
from app.routes_vat import Deadlines, PeriodDeadline

TODAY = date(2026, 11, 2)


def _ev(n: int, when: date, account: str, pence: int) -> LedgerEvent:
    sale = account.startswith("4")
    lines = (
        [Line(account="1200 Bank", debit=pence), Line(account=account, credit=pence)]
        if sale
        else [Line(account=account, debit=pence), Line(account="1200 Bank", credit=pence)]
    )
    return LedgerEvent(
        id=f"{n:032x}",
        kind="sale" if sale else "purchase",
        date=when,
        lines=lines,
        approved_by="sam@example.co.uk",
        approved_at=datetime(2026, 11, 1, tzinfo=UTC),
    )


EVENTS = [
    _ev(1, date(2025, 3, 10), "4000 Sales", 100_000),
    _ev(2, date(2025, 3, 11), "5000 Materials", 40_000),
    _ev(3, date(2025, 12, 20), "4000 Sales", 999_999),
    _ev(4, date(2026, 5, 15), "4000 Sales", 80_000),
    _ev(5, date(2026, 5, 16), "7500 Office supplies", 10_000),
    _ev(6, date(2026, 9, 20), "4000 Sales", 32_000),
    _ev(7, date(2026, 9, 21), "5000 Materials", 20_000),
    _ev(8, date(2026, 10, 1), "6200 Advertising", 5_000),
    _ev(9, date(2026, 11, 3), "4000 Sales", 50_000),
]


# --------------------------------------------------------------------------- #
# The year start and the change
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("kind", "settings", "today", "start", "rule"),
    [
        ("company", {}, TODAY, date(2026, 1, 1), "calendar year"),
        ("partnership", {}, date(2026, 1, 1), date(2026, 1, 1), "calendar year"),
        ("sole_trader", {}, TODAY, date(2026, 4, 6), "tax year"),
        ("sole_trader", {"accounting_period_start": "04-06"}, date(2026, 4, 5), date(2025, 4, 6), "tax year"),
        ("sole_trader", {"accounting_period_start": "08-01"}, TODAY, date(2026, 8, 1), "Settings"),
        ("sole_trader", {"accounting_period_start": "12-01"}, TODAY, date(2025, 12, 1), "Settings"),
        ("sole_trader", {"accounting_period_start": "02-31"}, date(2026, 3, 1), date(2026, 2, 28), "Settings"),
        ("landlord", {}, TODAY, date(2026, 4, 6), "tax year"),
    ],
)
def test_year_start_follows_the_books(kind: str, settings: dict[str, Any], today: date, start: date, rule: str) -> None:
    got, words = ho.year_start(kind, settings, today)
    assert got == start and rule in words


@pytest.mark.parametrize(
    ("now", "before", "pct"),
    [
        (112_000, 100_000, 12),
        (35_000, 40_000, -13),  # -12.5 rounds half up on its size
        (100_500, 100_000, 1),  # 0.5 rounds up
        (100_499, 100_000, 0),
        (5_000, 0, None),  # nothing last year: no percentage, never a division by zero
        (0, 0, None),
        (-50_000, -100_000, 50),  # a loss that halves is better: +50% against the size of last year's figure
        (-20_000, 10_000, -300),
    ],
)
def test_change_pct(now: int, before: int, pct: int | None) -> None:
    assert ho.change_pct(now, before) == pct


def test_span_label_and_a_year_earlier() -> None:
    assert ho.span_label(date(2026, 4, 6), TODAY) == "6 Apr – 2 Nov 2026"
    assert ho.span_label(date(2025, 12, 1), TODAY) == "1 Dec 2025 – 2 Nov 2026"
    assert ho.a_year_earlier(date(2028, 2, 29)) == date(2027, 2, 28)


# --------------------------------------------------------------------------- #
# The snapshot
# --------------------------------------------------------------------------- #


def _vat(due: bool) -> Deadlines:
    def pd(start: date, end: date, deadline: date, box5: str, direction: str) -> PeriodDeadline:
        return PeriodDeadline(
            start=start,
            end=end,
            label=f"{start:%b}–{end:%b %Y}",
            period_key=None,
            deadline=deadline,
            days_to_end=(end - TODAY).days,
            days_remaining=(deadline - TODAY).days,
            box5=box5,
            box5_direction=direction,  # type: ignore[arg-type]
            entries=3,
        )

    current = pd(date(2026, 10, 1), date(2026, 12, 31), date(2027, 2, 7), "120.00", "pay")
    ended = pd(date(2026, 7, 1), date(2026, 9, 30), date(2026, 11, 7), "1234.56", "reclaim")
    return Deadlines(today=TODAY, months=3, start_month=1, stagger=1, current=current, due=ended if due else None)


def test_snapshot_year_to_date_against_the_same_span_last_year() -> None:
    s = ho.snapshot(EVENTS, TODAY, "company", {}, "traditional", _vat(due=True))
    assert (s.start, s.end, s.period_label) == (date(2026, 1, 1), TODAY, "1 Jan – 2 Nov 2026")
    assert (s.last_year_start, s.last_year_end, s.last_year_label) == (
        date(2025, 1, 1),
        date(2025, 11, 2),
        "1 Jan – 2 Nov 2025",
    )
    assert (s.turnover_pence, s.expenses_pence, s.net_profit_pence) == (112_000, 35_000, 77_000)
    assert s.last_year.model_dump() == {"turnover_pence": 100_000, "expenses_pence": 40_000, "net_profit_pence": 60_000}
    assert s.change_pct.model_dump() == {"turnover": 12, "expenses": -13, "net_profit": 28}
    assert s.basis == "accrual from approved entries" and s.entries == 5
    # The P&L for the same span gives the same figures: the snapshot is the report, not a second calculation.
    pl = rp.profit_and_loss(EVENTS, s.start, TODAY)
    assert pl.sales.total_pence == s.turnover_pence and pl.net_profit_pence == s.net_profit_pence


def test_snapshot_with_nothing_last_year_has_no_percentages() -> None:
    s = ho.snapshot(EVENTS[3:], TODAY, "company", {}, "traditional")
    assert s.last_year.turnover_pence == 0
    assert s.change_pct.model_dump() == {"turnover": None, "expenses": None, "net_profit": None}
    assert s.vat_position is None  # not VAT registered (no tile)


def test_vat_position_is_the_dashboards_figure() -> None:
    due = ho.snapshot(EVENTS, TODAY, "company", {}, "traditional", _vat(due=True)).vat_position
    assert due is not None
    assert due.model_dump() == {
        "label": "Jul–Sep 2026",
        "amount_pence": 123456,
        "direction": "reclaim",
        "due": date(2026, 11, 7),
        "days_left": 5,
        "estimate": False,
    }
    now = ho.vat_position(_vat(due=False))
    assert now is not None and (now.amount_pence, now.direction, now.estimate) == (12000, "pay", True)
    assert ho.vat_position(dash.TileError(error="x")) is None


def test_snapshot_cash_basis_says_so() -> None:
    s = ho.snapshot(EVENTS, TODAY, "sole_trader", {}, "cash")
    assert (s.start, s.basis, s.accounting_basis) == (date(2026, 4, 6), "cash basis", "cash")
    assert s.turnover_pence == 112_000  # 15 May and 20 Sep 2026; nothing between 6 Apr and 2 Nov 2025


# --------------------------------------------------------------------------- #
# Trend and the cash line
# --------------------------------------------------------------------------- #


def test_trend_facts_best_weakest_and_direction() -> None:
    t = rp.monthly_trend(EVENTS, TODAY)
    assert [m.month for m in t.months][0] == "2025-12" and t.months[-1].month == "2026-11"
    f = ho.trend_facts(t)
    assert f == {
        "best_month": {"month": "Dec 2025", "net": "£9,999.99"},
        "weakest_month": {"month": "Oct 2026", "net": "-£50.00"},  # Nov 2026 is not over, so left out
        "last_3_months": {"months": "Aug–Oct 2026", "net": "£70.00"},
        "previous_3_months": {"months": "May–Jul 2026", "net": "£700.00"},
        "direction": "down",
    }
    assert ho.trend_facts(rp.monthly_trend([], TODAY)) is None  # nothing to compare


def _cf(opening: int, items: list[tuple[str, date, int]]) -> cf.CashFlow:
    from app.contacts import AgedBalances, AgedTable

    empty = AgedTable(rows=[], buckets={}, total_pence=0)
    extra = [
        cf.CashItem(
            direction=d,  # type: ignore[arg-type]
            contact="x",
            reference=None,
            due_date=when,
            amount_pence=p,
            overdue=False,
            event_id=f"e{i}",
        )
        for i, (d, when, p) in enumerate(items)
    ]
    aged = AgedBalances(as_of=TODAY, debtors=empty, creditors=empty)
    return cf.forecast(aged, opening, ["1200 Bank"], TODAY, extra)


def test_cash_series_samples_weekly_and_marks_the_low_point() -> None:
    flow = _cf(100_000, [("out", date(2026, 11, 10), 150_000), ("in", date(2026, 12, 14), 80_000)])
    s = cf.series(flow)
    assert (s.lowest_balance_pence, s.lowest_on, s.below_zero_on) == (-50_000, date(2026, 11, 10), date(2026, 11, 10))
    days = [p.days for p in s.points]
    assert days[:3] == [0, 7, 8] and {30, 60, 90} <= set(days) and days == sorted(set(days))
    by_day = {p.days: p.balance_pence for p in s.points}
    assert (by_day[0], by_day[7], by_day[8], by_day[42], by_day[90]) == (100_000, 100_000, -50_000, 30_000, 30_000)
    calm = cf.series(_cf(100_000, [("in", date(2026, 11, 20), 5_000)]))
    assert calm.below_zero_on is None and calm.lowest_on == TODAY


# --------------------------------------------------------------------------- #
# Summary facts and the code-written summary
# --------------------------------------------------------------------------- #


def _facts(**over: Any) -> dict[str, Any]:
    d = dash.Dashboard(
        today=TODAY,
        cash=dash.Cash(balance_pence=540_000, as_of=date(2026, 10, 31), bank=None, statement=None, reconciled_to=None),
        owed_to_you=None,
        owed_by_you=None,
        vat=None,
        attention=dash.Attention(proposed=1, needs_a_look=0, unmatched_bank_lines=0, overdue_invoices=0, total=1),
        activity=[],
        runs=dash.Runs(scan=None, autopilot=None, intake=None, triage=None),
        unavailable=[],
    )
    o: dict[str, Any] = {
        "kind": "company",
        "money": None,
        "week": None,
        "aged": None,
        "deadlines": [],
        "snapshot": ho.snapshot(EVENTS, TODAY, "company", {}, "traditional"),
        "trend": rp.monthly_trend(EVENTS, TODAY),
        "cash_points": cf.series(_cf(100_000, [("out", date(2026, 12, 14), 150_000)])),
    } | over
    return ho.summary_facts(d, o)


def test_facts_carry_the_year_the_trend_and_the_forecast() -> None:
    f = _facts()
    assert f["year_to_date"] == {
        "period": "1 Jan – 2 Nov 2026",
        "basis": "accrual from approved entries",
        "last_year_period": "1 Jan – 2 Nov 2025",
        "turnover": "£1,120.00",
        "turnover_last_year": "£1,000.00",
        "turnover_vs_last_year": "up 12%",
        "expenses": "£350.00",
        "expenses_last_year": "£400.00",
        "expenses_vs_last_year": "down 13%",
        "net_profit": "£770.00",
        "net_profit_last_year": "£600.00",
        "net_profit_vs_last_year": "up 28%",
    }
    assert f["monthly_trend"]["direction"] == "down"
    assert f["cash_forecast"] == {
        "days": 90,
        "lowest": "-£500.00",
        "lowest_on": "14 Dec 2026",
        "goes_below_zero": True,
        "below_zero_from": "14 Dec 2026",
    }
    # Every figure is one KnownNumbers accepts, so the model may quote them.
    known = KnownNumbers(f)
    for said in ("turnover up 12%", "£1,120.00", "£770", "a loss of £500.00 on 14 Dec 2026", "£9,999.99", "28%"):
        assert not known.unknown(said, all_tokens=False), said
    assert known.unknown("turnover up 15%", all_tokens=False) == ["15%"]


def test_facts_leave_out_what_is_not_there() -> None:
    f = _facts(snapshot=None, trend=None, cash_points=None)
    assert not {"year_to_date", "monthly_trend", "cash_forecast"} & set(f)
    nothing_last_year = _facts(snapshot=ho.snapshot(EVENTS[3:], TODAY, "company", {}, "traditional"))
    assert "turnover_vs_last_year" not in nothing_last_year["year_to_date"]


def _sentences(text: str) -> int:
    return len(re.findall(r"[.!?](?:\s|$)", text))


def test_fallback_has_one_sentence_on_the_year_to_date() -> None:
    f = _facts()
    text = hs.fallback_summary(f)
    assert text == (
        "You had £5,400.00 in the bank on 31 Oct 2026, and the 90-day forecast goes below £0 from 14 Dec 2026. "
        "This year so far (1 Jan – 2 Nov 2026, accrual from approved entries), turnover was £1,120.00 and expenses "
        "£350.00: a net profit of £770.00, with turnover up 12% on 1 Jan – 2 Nov 2025. "
        "To do: 1 item waiting in Review."
    )
    assert 2 <= _sentences(text) <= 4
    assert hs.ground(text, f) is None  # code's own words pass the same check as the model's


def test_fallback_says_a_loss_and_no_change_plainly() -> None:
    f = _facts(cash_points=None)
    f["year_to_date"] |= {"net_profit": "-£25.00", "turnover_vs_last_year": "no change"}
    text = hs.fallback_summary(f)
    assert "a net loss of £25.00, with the same turnover as 1 Jan – 2 Nov 2025." in text
    assert "forecast" not in text
    del f["year_to_date"]["turnover_vs_last_year"]
    assert "a net loss of £25.00." in hs.fallback_summary(f)


def test_fallback_says_how_late_a_deadline_is() -> None:
    f = {"today": "2 Nov 2026", "next_deadline": {"what": "Pay run", "due": "30 Oct 2026", "days_left": -3}}
    assert hs.fallback_summary(f).endswith("due 30 Oct 2026 (3 days late).")


def test_prompt_lets_the_model_talk_about_the_year_and_the_trend() -> None:
    p = hs.SYSTEM_PROMPT
    assert "two to four sentence" in p and "year_to_date" in p and "monthly_trend" in p and "cash_forecast" in p
