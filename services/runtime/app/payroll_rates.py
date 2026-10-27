"""UK PAYE and Class 1 NI rates for the current tax year, used for pay-run *estimates* only (app/payroll.py).

Source: HMRC, "Rates and thresholds for employers 2026 to 2027",
https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2026-to-2027
Check these figures against that page each April; nothing else in the code holds a rate.

Limits, stated plainly (also on every screen and file):
- England and Northern Ireland income tax bands only (not Scottish or Welsh rates).
- The standard tax code (1257L), worked out on a non-cumulative (month 1) basis; no other tax codes,
  no K codes, no emergency codes, no personal allowance taper.
- NI category letter A only. Student loans, postgraduate loans, pensions (auto-enrolment), statutory pay
  (SSP, SMP...), benefits in kind, salary sacrifice and the Employment Allowance are out of scope.
Your payroll provider calculates the actual tax and NI.
"""

from __future__ import annotations

from typing import Final

TAX_YEAR: Final = "2026-27"
# Figures checked against this page on 27 Oct 2026.
SOURCE_URL: Final = "https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2026-to-2027"
TAX_CODE: Final = "1257L"

# Annual figures in pence. Monthly figures are these ÷ 12 (pro-rated), not HMRC's monthly tables, so estimates
# differ from the provider's: code 1257L gives £1,048.25 free pay a month in HMRC's tables (not £1,047.50), so the
# estimated tax runs about 20p a month high; HMRC's rounded monthly NI thresholds move NI by a few pence.
PERSONAL_ALLOWANCE: Final = 1_257_000  # £12,570
BASIC_RATE_LIMIT: Final = 5_027_000  # £50,270: basic rate band £37,700 above the allowance
ADDITIONAL_RATE_THRESHOLD: Final = 12_514_000  # £125,140
BASIC_RATE: Final = 20  # %
HIGHER_RATE: Final = 40
ADDITIONAL_RATE: Final = 45

NI_PRIMARY_THRESHOLD: Final = 1_257_000  # £12,570 (PT)
NI_UPPER_EARNINGS_LIMIT: Final = 5_027_000  # £50,270 (UEL)
NI_EMPLOYEE_MAIN_RATE: Final = 8  # % between PT and UEL
NI_EMPLOYEE_UPPER_RATE: Final = 2  # % above UEL
NI_SECONDARY_THRESHOLD: Final = 500_000  # £5,000 (ST)
NI_EMPLOYER_RATE: Final = 15  # % above ST

ESTIMATE_LABEL: Final = "Estimate — your payroll provider calculates the actual tax and NI"
LIMITS: Final = (
    f"Tax code {TAX_CODE} only, England and Northern Ireland rates, worked out month by month (non-cumulative).",
    (
        "NI category A only. Student loans, pensions, statutory pay,"
        " benefits in kind and the Employment Allowance are not included."
    ),
    f"Rates for tax year {TAX_YEAR}: {SOURCE_URL}",
)
