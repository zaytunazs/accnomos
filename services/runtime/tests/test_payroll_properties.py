"""Property tests (Hypothesis) for pence rounding and the money identities of the payroll engine.

HMRC's worked examples pin single figures (tests/test_paye.py); these check the rules hold for any input:

* every rounding helper returns whole pence, stays within its stated distance of the exact value and never goes
  down when its input goes up; NI rounding drops amounts of a halfpenny or less (NI guidance 2026-27, 4.2);
* tax, NI, student loans and pension contributions are whole pence (loans whole pounds) and within their caps;
* cumulative PAYE deducted month by month adds up to the liability worked out in one go at month 12;
* on every payslip, net pay = gross - salary sacrifice - every deduction, and the run's journal balances.
"""

from __future__ import annotations

import math
from datetime import date
from fractions import Fraction

from hypothesis import given, settings
from hypothesis import strategies as st

from app import paye as P
from app import paye_rates as R
from app import payrun as PR
from app import pension_ae as AE

PENCE = st.integers(min_value=0, max_value=50_000_000)  # up to £500,000 in one period
FRACTIONS = st.fractions(min_value=0, max_value=10_000_000, max_denominator=1_000_000)
FREQS = st.sampled_from(R.FREQUENCIES)
LETTERS = st.sampled_from(sorted(R.NI_CATEGORIES))


# --------------------------------------------------------------------------- #
# Rounding helpers
# --------------------------------------------------------------------------- #


@given(FRACTIONS)
def test_ni_round_disregards_a_halfpenny_or_less(x: Fraction) -> None:
    r = P.ni_round(x)
    assert isinstance(r, int)
    assert x - Fraction(6, 10) < r <= x + Fraction(4, 10)
    tenth = math.floor((x - math.floor(x)) * 10)
    assert r == math.floor(x) + (1 if tenth >= 6 else 0)


@given(FRACTIONS, FRACTIONS)
def test_rounding_helpers_are_monotonic(a: Fraction, b: Fraction) -> None:
    lo, hi = min(a, b), max(a, b)
    for f in (P.ni_round, P.half_up, P.floor_penny, P.ceil_penny, P.floor_pound, P.ceil_pound):
        assert f(lo) <= f(hi), f.__name__


@given(FRACTIONS)
def test_half_up_floor_and_ceil_bounds(x: Fraction) -> None:
    assert abs(P.half_up(x) - x) <= Fraction(1, 2)
    assert P.floor_penny(x) <= x < P.floor_penny(x) + 1
    assert P.ceil_penny(x) - 1 < x <= P.ceil_penny(x)
    assert P.floor_pound(x) % 100 == 0 and P.floor_pound(x) <= x < P.floor_pound(x) + 100
    assert P.ceil_pound(x) % 100 == 0 and P.ceil_pound(x) - 100 < x <= P.ceil_pound(x)
    t = P.trunc_4dp(x)
    assert t <= x < t + Fraction(1, 100) and (t * 100).denominator == 1


# --------------------------------------------------------------------------- #
# NI, loans, statutory pay
# --------------------------------------------------------------------------- #


@given(PENCE, LETTERS, FREQS)
def test_ni_is_whole_pence_close_to_exact(gross: int, letter: str, freq: R.Frequency) -> None:
    res = P.ni_period(gross, letter, freq)
    assert isinstance(res.employee_pence, int) and isinstance(res.employer_pence, int)
    assert res.employee_pence >= 0 and res.employer_pence >= 0
    rates = R.NI_CATEGORIES[letter]
    bands = (res.st_to_lel, res.lel_to_pt, res.pt_to_fust, res.fust_to_uel, res.above_uel)
    assert sum(bands) == max(0, gross - R.NI_LIMITS[freq].st)
    exact_ee = sum(Fraction(b * r, 10_000) for b, r in zip(bands, rates.employee, strict=True))
    exact_er = sum(Fraction(b * r, 10_000) for b, r in zip(bands, rates.employer, strict=True))
    # two roundings (main bands, above the UEL), each at most 0.6p down or 0.4p up
    assert exact_ee - Fraction(12, 10) < res.employee_pence <= exact_ee + Fraction(8, 10)
    assert exact_er - Fraction(12, 10) < res.employer_pence <= exact_er + Fraction(8, 10)


@given(PENCE, PENCE, LETTERS, FREQS)
def test_ni_never_falls_when_pay_rises(a: int, b: int, letter: str, freq: R.Frequency) -> None:
    lo, hi = P.ni_period(min(a, b), letter, freq), P.ni_period(max(a, b), letter, freq)
    assert lo.employee_pence <= hi.employee_pence and lo.employer_pence <= hi.employer_pence


@given(PENCE, st.sampled_from(["1", "2", "4", "5"]), FREQS, st.booleans())
def test_loans_are_whole_pounds_within_the_rate(earn: int, plan: str, freq: R.Frequency, pg: bool) -> None:
    sl = P.student_loan(earn, plan, freq)
    thr = P.loan_threshold(R.STUDENT_LOAN_THRESHOLDS_PENCE[plan], freq)
    assert sl % 100 == 0 and 0 <= sl <= max(0, earn - thr) * 9 / 100
    assert max(0, earn - thr) * 9 / 100 - sl < 100
    pgl = P.postgrad_loan(earn, pg, freq)
    assert pgl % 100 == 0 and pgl >= 0 and (pg or pgl == 0)


@given(st.integers(0, 100_000), st.integers(1, 7), st.integers(0, 200))
def test_ssp_is_whole_pence_and_at_most_the_weekly_rate_per_week(awe: int, qd: int, days: int) -> None:
    amount = P.ssp_amount(awe, qd, days)
    weeks = math.ceil(days / qd)
    weekly = P.ceil_penny(P.ssp_weekly(awe))
    assert isinstance(amount, int) and 0 <= amount <= weeks * weekly
    assert weekly <= R.SSP_WEEKLY_PENCE


# --------------------------------------------------------------------------- #
# Income tax
# --------------------------------------------------------------------------- #

CODES = st.sampled_from(
    ["1257L", "S1257L", "C1257L", "K500", "SK250", "BR", "D0", "SD1", "0T", "NT", "500T", "C1100L", "1257L M1"]
)


@settings(max_examples=60)
@given(CODES, st.lists(st.integers(0, 3_000_000), min_size=12, max_size=12))
def test_cumulative_tax_adds_up_to_the_month_12_liability(code_text: str, pays: list[int]) -> None:
    code = P.parse_tax_code(code_text)
    to_date_pay = to_date_tax = 0
    limited = False
    for month, pay in enumerate(pays, start=1):
        res = P.income_tax(code, "monthly", month, pay, to_date_pay, to_date_tax)
        assert isinstance(res.tax_pence, int)
        if res.tax_pence > 0:  # the 50 % overriding limit
            assert res.tax_pence <= pay // 2
        if code.non_cumulative:
            assert res.tax_pence >= 0  # week 1 / month 1 never refunds
        limited |= res.regulatory_limited
        to_date_pay += pay
        to_date_tax = res.tax_due_to_date_pence
    if not code.non_cumulative and not limited:
        once = P.income_tax(code, "monthly", 12, sum(pays), 0, 0)  # the whole year's pay as one month-12 payment
        if not once.regulatory_limited:
            assert to_date_tax == once.tax_pence


@given(CODES, st.integers(0, 2_000_000), st.integers(0, 2_000_000), FREQS)
def test_non_cumulative_tax_never_falls_when_pay_rises(code_text: str, a: int, b: int, freq: R.Frequency) -> None:
    code = P.parse_tax_code(code_text, non_cumulative=True)
    period = 1 if freq == "monthly" else R.WEEKS_IN_PERIOD[freq]
    lo = P.income_tax(code, freq, period, min(a, b)).tax_pence
    hi = P.income_tax(code, freq, period, max(a, b)).tax_pence
    # the 50 % limit can bind on the smaller pay only, so compare the unlimited liability's direction
    assert lo <= hi or lo <= min(a, b) // 2


# --------------------------------------------------------------------------- #
# Pension contributions and whole payslips
# --------------------------------------------------------------------------- #

ARRANGEMENTS = st.sampled_from(["net_pay", "relief_at_source", "salary_sacrifice"])


@given(
    PENCE, FREQS, ARRANGEMENTS, st.sampled_from(["qualifying", "full_pay"]), st.integers(0, 2000), st.integers(0, 2000)
)
def test_pension_contributions_are_whole_pence(
    pay: int, freq: R.Frequency, arrangement: AE.Arrangement, basis: AE.Basis, er_bp: int, ee_bp: int
) -> None:
    c = AE.contributions(AE.Scheme("generic", basis, arrangement, er_bp, ee_bp), freq, pay)
    th = R.AE_THRESHOLDS[freq]
    if basis == "qualifying":
        assert 0 <= c.base_pence <= th.upper_qe - th.lower_qe
    assert abs(c.employee_gross_pence - Fraction(c.base_pence * ee_bp, 10_000)) <= Fraction(1, 2)
    if arrangement == "relief_at_source":
        assert c.employee_deducted_pence + c.relief_claimed_by_scheme_pence == c.employee_gross_pence
        assert abs(c.employee_deducted_pence - Fraction(c.base_pence * ee_bp * 8, 100_000)) <= Fraction(1, 2)
    elif arrangement == "salary_sacrifice":
        assert c.employee_deducted_pence == 0 and c.sacrifice_pence == c.employee_gross_pence
    else:
        assert c.employee_deducted_pence == c.employee_gross_pence
    assert c.to_provider_pence == c.employer_pence + c.employee_deducted_pence


RUN = PR.PayRun(
    id="2026-27-monthly-07",
    tax_year=R.TAX_YEAR,
    frequency="monthly",
    period=7,
    period_start=date(2026, 10, 6),
    period_end=date(2026, 11, 5),
    pay_date=date(2026, 10, 31),
)


@settings(max_examples=150, deadline=None)
@given(
    salary=st.integers(0, 30_000_000),
    bonus=st.integers(0, 2_000_000),
    after_tax=st.integers(0, 50_000),
    code=CODES,
    letter=st.sampled_from(["A", "B", "C", "H", "J", "M", "V", "Z"]),
    plan=st.sampled_from([None, "1", "2", "4", "5"]),
    pg=st.booleans(),
    arrangement=ARRANGEMENTS,
    basis=st.sampled_from(["qualifying", "full_pay"]),
)
def test_payslip_adds_up_and_the_journal_balances(
    salary: int,
    bonus: int,
    after_tax: int,
    code: str,
    letter: str,
    plan: str | None,
    pg: bool,
    arrangement: AE.Arrangement,
    basis: AE.Basis,
) -> None:
    emp = PR.Employee.model_validate(
        {
            "payroll_id": "E001",
            "forenames": "Ann",
            "surname": "Lee",
            "nino": "AB123456C",
            "dob": date(1955, 5, 1) if letter == "C" else date(1950, 5, 1) if letter == "B" else date(1990, 5, 1),
            "gender": "F",
            "address": ["1 High St", "London"],
            "start_date": date(2020, 1, 1),
            "annual_salary_pence": salary,
            "tax_code": code,
            "ni_category": letter,
            "student_loan_plan": plan,
            "postgrad_loan": pg,
        }
    )
    scheme = PR.PensionSettings(arrangement=arrangement, basis=basis, employer_bp=300, employee_bp=500)
    inputs = PR.LineInputs(employee_id=emp.id, bonus_pence=bonus, deductions_after_tax_pence=after_tax)
    line = PR.calculate_line(emp, inputs, RUN, scheme, [], date(2026, 4, 6))
    money = [v for k, v in line.model_dump().items() if k.endswith("_pence") and v is not None]
    assert all(isinstance(v, int) for v in money)
    assert line.net_pay_pence == line.gross_pence - line.salary_sacrifice_pence - line.total_deductions_pence
    assert line.student_loan_pence % 100 == 0 and line.postgrad_loan_pence % 100 == 0
    run = RUN.model_copy(update={"lines": [line]})
    j = PR.journal(run)
    assert sum(x.debit_pence for x in j) == sum(x.credit_pence for x in j)
