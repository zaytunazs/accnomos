"""Golden tests for app/paye.py against HMRC's published figures and worked examples.

* Free pay: HMRC "Tables A - Pay adjustment tables" (https://www.gov.uk/government/publications/tables-a-pay-adjustment-tables,
  the PDF read 28 Oct 2026; the tables depend only on the code, not the year).
* Income tax: hand-worked with HMRC "Specification for PAYE Tax Table Routines" v24.0 (Feb 2026), each step shown.
  HMRC publishes no worked PAYE examples for 2026-27; HMRC's online calculators could not be scripted here.
* NI: every worked example in HMRC "NI Guidance for software developers 2026 to 2027" v1.1, Appendix 2.
* SSP: every cell of the "amounts to pay" table on HMRC "Rates and thresholds for employers 2026 to 2027".
"""

from __future__ import annotations

from datetime import date

import pytest

from app import paye as P


def tax(code: str, freq: str, n: int, pay: int, pay_before: int = 0, tax_before: int = 0) -> P.TaxResult:
    return P.income_tax(P.parse_tax_code(code), freq, n, pay, pay_before, tax_before)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Tax codes and free pay (Tables A)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("number", "monthly", "pence"),
    [
        (1, False, 37),  # Week 1, code 1: £0.37
        (257, False, 4_960),  # Week 1, code 257: £49.60
        (500, False, 9_633),  # Week 1, code 500: £96.33
        (1, True, 159),  # Month 1, code 1: £1.59
        (257, True, 21_492),  # Month 1, code 257: £214.92
        (500, True, 41_742),  # Month 1, code 500: £417.42
        (1257, False, 24_192),  # 257 + 2 x £96.16 (Tables A "code more than 500" box)
        (1257, True, 104_826),  # 257 + 2 x £416.67
        (1000, True, 41_742 + 41_667),  # quotient 1, remainder 500
        (0, True, 0),
    ],
)
def test_free_pay_matches_tables_a(number: int, monthly: bool, pence: int) -> None:
    assert P.period1_allowance(number, monthly) == pence


def test_free_pay_later_periods_match_tables_a() -> None:
    # Tables A: code 257 is £99.20 in week 2, £1,289.52 in month 6, £2,579.04 in month 12, £2,579.20 in week 52.
    assert 2 * P.period1_allowance(257, False) == 9_920
    assert 6 * P.period1_allowance(257, True) == 128_952
    assert 12 * P.period1_allowance(257, True) == 257_904
    assert 52 * P.period1_allowance(257, False) == 257_920


@pytest.mark.parametrize(
    ("text", "prefix", "kind", "body", "nc"),
    [
        ("1257L", "", "suffix", "1257L", False),
        ("s1257l", "S", "suffix", "1257L", False),
        ("C1257L M1", "C", "suffix", "1257L", True),
        ("1257L W1", "", "suffix", "1257L", True),
        ("1257L X", "", "suffix", "1257L", True),
        ("K475", "", "K", "K475", False),
        ("SK100", "S", "K", "K100", False),
        ("BR", "", "BR", "BR", False),
        ("D1", "", "D", "D1", False),
        ("SD3", "S", "D", "D3", False),
        ("NT", "", "NT", "NT", False),
        ("0T", "", "suffix", "0T", False),
        ("1100M", "", "suffix", "1100M", False),
    ],
)
def test_parse_tax_code(text: str, prefix: str, kind: str, body: str, nc: bool) -> None:
    c = P.parse_tax_code(text)
    assert (c.prefix, c.kind, c.body, c.non_cumulative) == (prefix, kind, body, nc)


@pytest.mark.parametrize("bad", ["", "1257", "L1257", "SNT", "D2", "K0", "12345678L", "BR1"])
def test_bad_tax_codes_are_refused(bad: str) -> None:
    # D2 is beyond England's rates (D0 40%, D1 45%); SNT does not exist.
    with pytest.raises(P.PayeError):
        P.parse_tax_code(bad)


# --------------------------------------------------------------------------- #
# Income tax (PAYE Tax Table Routines v24.0)
# --------------------------------------------------------------------------- #


def test_monthly_basic_rate_month_1() -> None:
    # £3,000, 1257L, month 1: U = 3,000 - 1,048.26 = 1,951.74; Cvalue 1 = 0 so Tax Formula 2; T = £1,951 x 20%.
    r = tax("1257L", "monthly", 1, 300_000)
    assert (r.tax_pence, r.free_pay_pence, r.basis) == (39_020, 104_826, "cumulative")


def test_cumulative_month_7() -> None:
    # £3,000 a month all year. Month 6 to date: 18,000 - 6 x 1,048.26 = 11,710.44 -> 11,710 x 20% = 2,342.00.
    # Month 7: 21,000 - 7,337.82 = 13,662.18 -> 13,662 x 20% = 2,732.40; this month 2,732.40 - 2,342.00 = 390.40.
    assert tax("1257L", "monthly", 6, 300_000, 1_500_000, 195_160).tax_due_to_date_pence == 234_200
    r = tax("1257L", "monthly", 7, 300_000, 1_800_000, 234_200)
    assert (r.tax_pence, r.tax_due_to_date_pence) == (39_040, 273_240)


def test_higher_rate_month_1() -> None:
    # £6,000: U = 4,951.74 > Cvalue 2 (37,700/12 = 3,141.6666, rounded up 3,142), <= Cvalue 3 (10,429): Formula 3,
    # k2 + (T - c2) x 40% = 628.3333 + (4,951 - 3,141.6666) x 0.4 = 1,352.0666 -> £1,352.06.
    assert tax("1257L", "monthly", 1, 600_000).tax_pence == 135_206


def test_additional_rate_month_1() -> None:
    # £15,000: U = 13,951.74 > Cvalue 3: Formula 4, 3,543 + (13,951 - 10,428.3333) x 45% = 5,128.2000 -> £5,128.20.
    assert tax("1257L", "monthly", 1, 1_500_000).tax_pence == 512_820


def test_scottish_and_welsh_codes() -> None:
    # S1257L £3,000 month 1: U = 1,951.74 <= SCvalue 3 (2,591): Formula 3(S), Sk2 + (T - Sc2) x 21%
    # = 279.2941 + (1,951 - 1,413) x 0.21 = 392.2741 -> £392.27.
    assert tax("S1257L", "monthly", 1, 300_000).tax_pence == 39_227
    # S1257L £10,000: Formula 5(S), Sk4 + (8,951 - 5,202.5) x 45% = 1,623.5041 + 1,686.825 -> £3,310.32.
    assert tax("S1257L", "monthly", 1, 1_000_000).tax_pence == 331_032
    # Wales has England's rates in 2026-27.
    assert tax("C1257L", "monthly", 1, 300_000).tax_pence == 39_020


@pytest.mark.parametrize(
    ("code", "pence"),
    [
        ("BR", 24_680),  # £1,234 x 20%
        ("D0", 49_360),  # x 40%
        ("D1", 55_530),  # x 45%
        ("SBR", 24_680),  # Scottish basic 20%
        ("SD0", 25_914),  # intermediate 21%
        ("SD1", 51_828),  # higher 42%
        ("SD2", 55_530),  # advanced 45%
        ("SD3", 59_232),  # top 48%
        ("CBR", 24_680),
        ("NT", 0),
    ],
)
def test_flat_rate_codes(code: str, pence: int) -> None:
    # The whole of £1,234.56, rounded down to £1,234, at one rate (paras 5, 6, 7).
    assert tax(code, "monthly", 1, 123_456).tax_pence == pence


def test_k_code_and_regulatory_limit() -> None:
    # K475 month 1: additional pay (4,759 / 12 rounded up) = 396.59; £1,000 + 396.59 -> 1,396 x 20% = £279.20.
    assert tax("K475", "monthly", 1, 100_000).tax_pence == 27_920
    # £200 pay: 596 x 20% = £119.20, but no more than 50% of the £200 pay can be taken (para 4.5.2).
    r = tax("K475", "monthly", 1, 20_000)
    assert (r.tax_pence, r.regulatory_limited) == (10_000, True)
    # Cumulative: next month the £19.20 not taken is recovered (L1 was reduced to what was deducted).
    r2 = tax("K475", "monthly", 2, 100_000, 20_000, 10_000)
    assert r2.tax_pence == (120_000 + 2 * 39_659) // 100 * 20 - 10_000


def test_week1_month1_basis_ignores_the_year_and_never_refunds() -> None:
    assert tax("1257L M1", "monthly", 7, 300_000, 1_800_000, 0).tax_pence == 39_020
    assert tax("1257L M1", "monthly", 7, 50_000, 1_800_000, 500_000).tax_pence == 0


def test_cumulative_refund() -> None:
    # Month 1 £3,000 (tax £390.20), month 2 nothing: 3,000 - 2,096.52 = 903.48 -> £180.60; refund £209.60.
    assert tax("1257L", "monthly", 2, 0, 300_000, 39_020).tax_pence == -20_960


def test_fortnightly_uses_week_tables_for_week_2() -> None:
    # Week 2: free pay 2 x 241.92 = 483.84; £1,000 - 483.84 = 516.16 -> 516 x 20% = £103.20.
    assert tax("1257L", "fortnightly", 2, 100_000).tax_pence == 10_320


def test_week_53_is_non_cumulative() -> None:
    # Para 14: week 53 uses the week 1 table on its own: £500 - 241.92 -> 258 x 20% = £51.60.
    r = tax("1257L", "weekly", 53, 50_000, 2_000_000, 300_000)
    assert (r.tax_pence, r.basis) == (5_160, "week53")


def test_0t_has_no_free_pay() -> None:
    assert tax("0T", "monthly", 1, 100_000).tax_pence == 20_000


# --------------------------------------------------------------------------- #
# Tax periods
# --------------------------------------------------------------------------- #


def test_tax_periods() -> None:
    assert (P.tax_week(date(2026, 4, 6)), P.tax_week(date(2026, 4, 12)), P.tax_week(date(2026, 4, 13))) == (1, 1, 2)
    assert P.tax_week(date(2027, 4, 5)) == 53
    assert (P.tax_month(date(2026, 5, 5)), P.tax_month(date(2026, 5, 6)), P.tax_month(date(2027, 4, 5))) == (1, 2, 12)
    assert P.tax_month(date(2026, 10, 31)) == 7
    # RTI data item 44: a 4-weekly payroll reports week 4 for pay days 6 April to 3 May.
    assert P.period_number("four_weekly", date(2026, 5, 3)) == 4
    assert P.period_number("four_weekly", date(2026, 5, 4)) == 8
    assert P.period_number("fortnightly", date(2026, 4, 20)) == 4
    assert P.tax_month_bounds(date(2026, 4, 6), 9) == (date(2026, 12, 6), date(2027, 1, 5))
    assert P.payment_due(date(2026, 4, 6), 7) == date(2026, 11, 22)
    assert P.tax_year_label(date(2027, 4, 5)) == "2026-27"


# --------------------------------------------------------------------------- #
# National Insurance: HMRC's 2026-27 worked examples (Appendix 2)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("example", "pay", "letter", "freq", "ee", "er"),
    [
        (1, 12_953, "A", "weekly", 0, 503),  # £129.53 a week: employer 33.53 x 15% = 5.029 -> £5.03
        (2, 100_000, "A", "weekly", 5_866, 13_560),  # £1,000 a week: £58.66 and £135.60
        (3, 50_800, "B", "fortnightly", 44, 4_725),  # £508 for 2 weeks, reduced rate: £0.44 and £47.25 (*)
        (4, 100_400, "M", "weekly", 5_874, 555),  # under 21, £1,004 a week: £58.74 and £5.55
        (7, 25_000, "H", "weekly", 64, 0),  # apprentice under 25, £250 a week: £0.64 and nil
        (8, 500_000, "F", "monthly", 26_750, 43_755),  # Freeport, £5,000 a month: £267.50 and £437.55
        (9, 500_000, "I", "monthly", 7_433, 43_755),  # Freeport reduced rate: £74.33 and £437.55
        (10, 500_000, "K", "monthly", 0, 43_755),  # Investment Zone, over SPA: nil and £437.55
        (11, 500_000, "L", "monthly", 7_904, 43_755),  # deferment ("IZ" in HMRC's heading, letter L rates): £79.04
        (12, 500_000, "V", "monthly", 26_750, 12_165),  # veteran: £267.50 and £121.65
    ],
)
def test_ni_hmrc_worked_examples(example: int, pay: int, letter: str, freq: str, ee: int, er: int) -> None:
    # (*) HMRC's example 3 prints the total as £47.94; its own steps (£0.44 + £47.25) add up to £47.69.
    r = P.ni_period(pay, letter, freq)  # type: ignore[arg-type]
    assert (r.employee_pence, r.employer_pence) == (ee, er), f"example {example}"


def test_ni_example_1_reporting_bands() -> None:
    # Earnings reach the LEL, so they are recorded though no employee NI is due.
    r = P.ni_period(12_953, "A", "weekly")
    assert (r.st_to_lel, r.lel_to_pt, r.pt_to_uel, r.at_lel) == (3_300, 53, 0, 12_900)


def test_ni_below_secondary_threshold_and_category_c() -> None:
    assert P.ni_period(9_600, "A", "weekly").employer_pence == 0
    assert P.ni_period(200_000, "C", "monthly").employee_pence == 0
    with pytest.raises(P.PayeError):
        P.ni_period(100_000, "Q", "monthly")


def test_ni_rounding_half_penny_disregarded() -> None:
    # HMRC section 4.2: only the third decimal place counts, 5 or less down, 6 or more up.
    assert P.ni_round(P.Fraction(675_558, 100)) == 6_755  # £67.5558 -> £67.55 (not £67.56: the 4th place is ignored)
    assert P.ni_round(P.Fraction(675_568, 100)) == 6_756  # £67.5568 -> £67.56
    assert P.ni_round(P.Fraction(101, 2)) == 50  # exactly half a penny: disregarded
    assert P.ni_round(P.Fraction(5029, 10)) == 503  # example 1: £5.029 -> £5.03


def test_director_pro_rata_example_5() -> None:
    # Appointed 1 Dec 2026 (18 weeks left), £37,643: employee £1,448.82; employer £1,038.45 + £1,312.20 + £3,036.15.
    lim = P.director_limits(18)
    assert (lim.st, lim.lel, lim.pt, lim.fust, lim.uel) == (173_100, 232_200, 435_200, 865_400, 1_740_200)
    d = P.ni_director(3_764_300, "A", P.tax_week(date(2026, 12, 1)), 0, 0)
    assert P.tax_week(date(2026, 12, 1)) == 35
    assert (d.employee_pence, d.employer_pence) == (144_882, 538_680)
    assert d.employee_pence + d.employer_pence == 683_562  # HMRC's total £6,835.62


def test_director_annual_example_6() -> None:
    # 18-year-old director all year, £52,000, nothing paid yet: employee £3,050.60, employer £259.50 (total £3,310.10).
    d = P.ni_director(5_200_000, "M", None, 0, 0)
    assert (d.employee_pence, d.employer_pence) == (305_060, 25_950)
    # Paid to date is taken off: what's due this period is the difference.
    assert P.ni_director(5_200_000, "M", None, 300_000, 25_000).employee_pence == 5_060


# --------------------------------------------------------------------------- #
# Student loans
# --------------------------------------------------------------------------- #


def test_student_loan_thresholds_per_period() -> None:
    # Rates page: Plan 1 £2,241.66 a month, £517.30 a week; Plan 5 £480.76 a week; PGL £403.84 a week.
    assert P.loan_threshold(2_690_000, "monthly") == 224_166
    assert P.loan_threshold(2_690_000, "weekly") == 51_730
    assert P.loan_threshold(2_500_000, "weekly") == 48_076
    assert P.loan_threshold(2_100_000, "weekly") == 40_384
    assert P.loan_threshold(2_938_500, "monthly") == 244_875


def test_student_loan_deductions_round_down_to_the_pound() -> None:
    # Plan 2, £3,000 a month: (3,000 - 2,448.75) x 9% = 49.61 -> £49.
    assert P.student_loan(300_000, "2", "monthly") == 4_900
    assert P.student_loan(244_875, "2", "monthly") == 0
    # Postgraduate loan, £2,000 a month: (2,000 - 1,750) x 6% = £15.
    assert P.postgrad_loan(200_000, True, "monthly") == 1_500
    assert P.student_loan(300_000, None, "monthly") == 0
    with pytest.raises(P.PayeError):
        P.student_loan(300_000, "3", "monthly")


# --------------------------------------------------------------------------- #
# Statutory pay
# --------------------------------------------------------------------------- #

SSP_TABLE = {  # qualifying days in the week -> amounts for 1, 2, ... days (rates page section 11)
    7: [1761, 3522, 5283, 7043, 8804, 10565, 12325],
    6: [2055, 4109, 6163, 8217, 10271, 12325],
    5: [2465, 4930, 7395, 9860, 12325],
    4: [3082, 6163, 9244, 12325],
    3: [4109, 8217, 12325],
    2: [6163, 12325],
    1: [12325],
}


@pytest.mark.parametrize("qdays", list(SSP_TABLE))
def test_ssp_reproduces_hmrc_table(qdays: int) -> None:
    for days, pence in enumerate(SSP_TABLE[qdays], start=1):
        assert P.ssp_amount(1_000_000, qdays, days) == pence, (qdays, days)


def test_ssp_80_percent_of_low_earnings_and_whole_weeks() -> None:
    # From 6 April 2026 SSP is the lower of £123.25 and 80% of AWE: AWE £100 -> £80 a week.
    assert P.ssp_amount(10_000, 5, 5) == 8_000
    assert P.ssp_amount(1_000_000, 5, 10) == 2 * 12_325


def test_smp() -> None:
    # 90% of AWE for 6 weeks, then the lower of £194.32 and 90% of AWE.
    assert P.smp_week(50_000, 1) == 45_000
    assert P.smp_week(50_000, 7) == 19_432
    assert P.smp_week(20_000, 7) == 18_000
    assert P.smp_amount(50_000, 5, 4) == 2 * 45_000 + 2 * 19_432
    with pytest.raises(P.PayeError):
        P.smp_week(50_000, 40)


# --------------------------------------------------------------------------- #
# State pension age
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("dob", "spa"),
    [
        (date(1959, 6, 1), date(2025, 6, 1)),  # 66
        (date(1960, 4, 15), date(2026, 5, 15)),  # 66 and 1 month (the Act's notes' example)
        (date(1960, 9, 10), date(2027, 3, 10)),  # 66 and 6 months
        (date(1961, 1, 22), date(2027, 11, 22)),  # 66 and 10 months
        (date(1961, 3, 6), date(2028, 3, 6)),  # 67
        (date(1990, 2, 28), date(2057, 2, 28)),
    ],
)
def test_state_pension_age(dob: date, spa: date) -> None:
    assert P.state_pension_date(dob) == spa
