"""Pins every 2026-27 figure in app/paye_rates.py a second time, written out as pounds from the published source.

Sources (read 28 Oct 2026): HMRC "Rates and thresholds for employers 2026 to 2027" (updated 1 Sep 2026); HMRC
"Specification for PAYE Tax Table Routines" v24.0 (Feb 2026) Appendices A-C; HMRC "NI Guidance for software
developers 2026 to 2027" v1.1 section 9.2 and Appendix 1; HMRC "Collection of student loans from 6 April 2026";
DWP "Review of the automatic enrolment earnings trigger and qualifying earnings band for 2026/27" (18 Dec 2025) and
The Pensions Regulator "Earnings thresholds". Re-check every source each spring and change both copies together.
"""

from __future__ import annotations

from app import paye_rates as r
from app.paye import loan_threshold


def p(pounds: float) -> int:
    return round(pounds * 100)


def test_year_and_sources() -> None:
    assert (r.TAX_YEAR, r.RELATED_TAX_YEAR) == ("2026-27", "26-27")
    assert r.RATES_URL == "https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2026-to-2027"
    for url in (r.PAYE_SPEC_URL, r.SL_SPEC_URL, r.AE_URL):
        assert url.startswith("https://www.gov.uk/")


def test_income_tax_england_ni_and_wales() -> None:
    # Basic 20% up to £37,700, higher 40% to £125,140, additional 45%; Rate 1 (10%) has a zero bandwidth.
    for regime in (r.ENGLAND_NI, r.WALES):
        assert regime.rates_bp == (1000, 2000, 4000, 4500)
        assert regime.bandwidths_pence == (0, p(37_700), p(87_440))
        assert regime.cumulative_tax_pence == (0, p(7_540), p(42_516))
        assert regime.basic_pointer == 2
    assert r.WALES.prefix == "C" and r.ENGLAND_NI.prefix == ""


def test_income_tax_scotland() -> None:
    s = r.SCOTLAND
    assert s.rates_bp == (1900, 2000, 2100, 4200, 4500, 4800)
    # Starter to £3,967, basic to £16,956, intermediate to £31,092, higher to £62,430, advanced to £125,140.
    assert s.bandwidths_pence == (p(3_967), p(12_989), p(14_136), p(31_338), p(62_710))
    cum = 0
    tops = []
    for b in s.bandwidths_pence:
        cum += b
        tops.append(cum)
    assert tops == [p(3_967), p(16_956), p(31_092), p(62_430), p(125_140)]
    assert s.cumulative_tax_pence == (p(753.73), p(3_351.53), p(6_320.09), p(19_482.05), p(47_701.55))
    assert s.basic_pointer == 2 and s.prefix == "S"


def test_allowance_codes_and_limit() -> None:
    assert p(12_570) == r.PERSONAL_ALLOWANCE_PENCE
    assert r.EMERGENCY_CODE == "1257L"
    assert r.REGULATORY_LIMIT_BP == 5000
    assert (p(96.16), p(416.67)) == (r.FREE_PAY_500_WEEK_PENCE, r.FREE_PAY_500_MONTH_PENCE)


def test_ni_limits() -> None:
    expected = {
        "weekly": (96, 129, 242, 481, 967),
        "fortnightly": (193, 258, 484, 962, 1_934),
        "four_weekly": (385, 516, 967, 1_924, 3_867),
        "monthly": (417, 559, 1_048, 2_083, 4_189),
        "annual": (5_000, 6_708, 12_570, 25_000, 50_270),
    }
    for period, (st, lel, pt, fust, uel) in expected.items():
        lim = r.NI_LIMITS[period]
        assert (lim.st, lim.lel, lim.pt, lim.fust, lim.uel) == (p(st), p(lel), p(pt), p(fust), p(uel)), period
    assert p(129) == r.NI_WEEKLY_LEL_PENCE


def test_ni_rates_every_letter() -> None:
    # (employee PT-FUST, FUST-UEL, above UEL) and (employer ST-LEL, LEL-PT, PT-FUST, FUST-UEL, above UEL), in %.
    expected = {
        "A": ((8, 8, 2), (15, 15, 15, 15, 15)),
        "B": ((1.85, 1.85, 2), (15, 15, 15, 15, 15)),
        "C": ((0, 0, 0), (15, 15, 15, 15, 15)),
        "D": ((2, 2, 2), (0, 0, 0, 15, 15)),
        "E": ((1.85, 1.85, 2), (0, 0, 0, 15, 15)),
        "F": ((8, 8, 2), (0, 0, 0, 15, 15)),
        "H": ((8, 8, 2), (0, 0, 0, 0, 15)),
        "I": ((1.85, 1.85, 2), (0, 0, 0, 15, 15)),
        "J": ((2, 2, 2), (15, 15, 15, 15, 15)),
        "K": ((0, 0, 0), (0, 0, 0, 15, 15)),
        "L": ((2, 2, 2), (0, 0, 0, 15, 15)),
        "M": ((8, 8, 2), (0, 0, 0, 0, 15)),
        "N": ((8, 8, 2), (0, 0, 0, 15, 15)),
        "S": ((0, 0, 0), (0, 0, 0, 15, 15)),
        "V": ((8, 8, 2), (0, 0, 0, 0, 15)),
        "Z": ((2, 2, 2), (0, 0, 0, 0, 15)),
    }
    assert set(r.NI_CATEGORIES) == set(expected)
    for letter, (ee, er) in expected.items():
        rates = r.NI_CATEGORIES[letter]
        assert rates.employee == (0, 0, *(round(x * 100) for x in ee)), letter
        assert rates.employer == tuple(round(x * 100) for x in er), letter


def test_employment_allowance_loans_statutory_pay() -> None:
    assert p(10_500) == r.EMPLOYMENT_ALLOWANCE_PENCE
    assert {"1": p(26_900), "2": p(29_385), "4": p(33_795), "5": p(25_000)} == r.STUDENT_LOAN_THRESHOLDS_PENCE
    assert p(21_000) == r.POSTGRAD_THRESHOLD_PENCE
    assert (r.STUDENT_LOAN_RATE_BP, r.POSTGRAD_RATE_BP) == (900, 600)
    assert (p(123.25), 8000, 28) == (r.SSP_WEEKLY_PENCE, r.SSP_AWE_BP, r.SSP_MAX_WEEKS)
    assert (p(194.32), 9000, 6, 39) == (r.SMP_WEEKLY_PENCE, r.SMP_AWE_BP, r.SMP_HIGHER_WEEKS, r.SMP_MAX_WEEKS)
    assert (r.STAT_PAY_RECOVERY_BP, r.STAT_PAY_RECOVERY_SMALL_BP) == (9200, 10900)
    assert p(45_000) == r.SMALL_EMPLOYER_NIC_LIMIT_PENCE


def test_auto_enrolment() -> None:
    expected = {
        "weekly": (120, 192, 967),
        "fortnightly": (240, 384, 1_934),
        "four_weekly": (480, 768, 3_867),
        "monthly": (520, 833, 4_189),
        "annual": (6_240, 10_000, 50_270),
    }
    for period, (low, trig, up) in expected.items():
        t = r.AE_THRESHOLDS[period]
        assert (t.lower_qe, t.trigger, t.upper_qe) == (p(low), p(trig), p(up)), period
    assert (r.AE_MIN_EMPLOYER_BP, r.AE_MIN_TOTAL_BP, r.AE_MIN_AGE) == (300, 800, 22)
    assert (r.AE_WORKER_MIN_AGE, r.AE_WORKER_MAX_AGE, r.RAS_BASIC_RELIEF_BP) == (16, 75, 2000)


def test_periods() -> None:
    assert r.PERIODS_IN_YEAR == {"weekly": 52, "fortnightly": 26, "four_weekly": 13, "monthly": 12}
    assert r.RTI_PAY_FREQ == {"weekly": "W1", "fortnightly": "W2", "four_weekly": "W4", "monthly": "M1"}


def test_loan_thresholds_per_period_match_the_rates_page() -> None:
    """The per-month and per-week thresholds printed on "Rates and thresholds for employers 2026 to 2027" (student
    loan and postgraduate loan recovery; re-read 28 Oct 2026) are the annual figure divided and rounded down."""
    printed = {  # annual: (per month, per week) in pence
        r.STUDENT_LOAN_THRESHOLDS_PENCE["1"]: (224_166, 51_730),
        r.STUDENT_LOAN_THRESHOLDS_PENCE["2"]: (244_875, 56_509),
        r.STUDENT_LOAN_THRESHOLDS_PENCE["4"]: (281_625, 64_990),
        r.STUDENT_LOAN_THRESHOLDS_PENCE["5"]: (208_333, 48_076),
        r.POSTGRAD_THRESHOLD_PENCE: (175_000, 40_384),
    }
    for annual, (month, week) in printed.items():
        assert (loan_threshold(annual, "monthly"), loan_threshold(annual, "weekly")) == (month, week)
