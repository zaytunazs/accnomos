"""Pins every 2026-27 payroll constant to the published figure, so an edit (or a copy-paste slip) fails a test.

Source: GOV.UK, "Rates and thresholds for employers 2026 to 2027"
(https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2026-to-2027) for the Class 1 NIC thresholds and
rates, and its income tax table (also https://www.gov.uk/income-tax-rates) for the Personal Allowance and the
England/NI bands. Read on 27 Oct 2026: PT £12,570, ST £5,000, UEL £50,270 a year; employee 8% / 2%; employer 15%;
basic rate 20% up to £37,700 of taxable income (so to £50,270), higher 40% to £125,140, additional 45% above.

The figures below are written out as pounds, not imported, on purpose: this test is the second copy that must
agree. Re-check the page each April and change both together.
"""

from __future__ import annotations

from app import payroll_rates as r


def pence(pounds: int) -> int:
    return pounds * 100


def test_tax_year_and_code() -> None:
    assert r.TAX_YEAR == "2026-27"
    assert r.TAX_CODE == "1257L"
    assert r.SOURCE_URL == "https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2026-to-2027"


def test_income_tax_thresholds_and_rates_england_ni() -> None:
    assert pence(12_570) == r.PERSONAL_ALLOWANCE
    assert pence(50_270) == r.BASIC_RATE_LIMIT
    assert pence(37_700) == r.BASIC_RATE_LIMIT - r.PERSONAL_ALLOWANCE  # the basic rate band
    assert pence(125_140) == r.ADDITIONAL_RATE_THRESHOLD
    assert (r.BASIC_RATE, r.HIGHER_RATE, r.ADDITIONAL_RATE) == (20, 40, 45)


def test_class_1_ni_thresholds_and_rates_category_a() -> None:
    assert pence(12_570) == r.NI_PRIMARY_THRESHOLD
    assert pence(50_270) == r.NI_UPPER_EARNINGS_LIMIT
    assert pence(5_000) == r.NI_SECONDARY_THRESHOLD
    assert r.NI_EMPLOYEE_MAIN_RATE == 8
    assert r.NI_EMPLOYEE_UPPER_RATE == 2
    assert r.NI_EMPLOYER_RATE == 15


def test_no_unpinned_numeric_constant() -> None:
    """A new rate constant added to the module must be pinned above, not slip through."""
    pinned = {
        "PERSONAL_ALLOWANCE", "BASIC_RATE_LIMIT", "ADDITIONAL_RATE_THRESHOLD", "BASIC_RATE", "HIGHER_RATE",
        "ADDITIONAL_RATE", "NI_PRIMARY_THRESHOLD", "NI_UPPER_EARNINGS_LIMIT", "NI_EMPLOYEE_MAIN_RATE",
        "NI_EMPLOYEE_UPPER_RATE", "NI_SECONDARY_THRESHOLD", "NI_EMPLOYER_RATE",
    }  # fmt: skip
    numeric = {k for k, v in vars(r).items() if k.isupper() and isinstance(v, int) and not isinstance(v, bool)}
    assert numeric == pinned
