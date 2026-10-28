"""Every PAYE, National Insurance, student loan, statutory pay and auto-enrolment figure for tax year 2026-27.

The one table the payroll engine (app/paye.py, app/pension_ae.py, app/rti.py) reads; tests/test_paye_rates.py pins
each figure a second time against the published source. Money is integer pence, rates are basis points
(1 bp = 0.01 %, so 1.85 % is 185). Re-check every source each spring before 6 April and bump TAX_YEAR.

Sources, all read on 28 Oct 2026 and re-read independently the same day on branch claude/payroll-finish (every
figure below matched, including the final Scottish bands that v24.0 of the routines spec had as provisional):

* HMRC, "Rates and thresholds for employers 2026 to 2027" (published 30 Jan 2026, updated 1 Sep 2026)
  https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2026-to-2027
  personal allowance, income tax bands (England and NI, Scotland, Wales), emergency code, NI thresholds and every
  category letter's rates, Employment Allowance, student and postgraduate loan thresholds and rates, SSP, SMP,
  statutory pay recovery.
* HMRC, "Specification for PAYE Tax Table Routines" version 24.0 (February 2026), Appendices A, B and C
  https://www.gov.uk/government/publications/payroll-technical-specifications-income-tax
  the bandwidths, cumulative annual tax (K, SK, WK), the basic-rate pointers G, G1, G2 and the 50 % regulatory limit.
  HMRC notes the Scottish parameters were "subject to parliamentary approval" when issued.
* HMRC, "NI Guidance for software developers 2026 to 2027" v1.1, sections 4-5, 9.2 and Appendix 1
  https://assets.publishing.service.gov.uk/media/6a3bc1fe4c7605ab567238ff/NI-Guidance-2026-27_v1.1.odt
  the earnings limits for 1, 2 and 4 weeks and a month, the band rates per letter, the rounding rule.
* HMRC, "Collection of student loans from 6 April 2026" (12 Dec 2025)
  https://www.gov.uk/government/publications/payroll-technical-specifications-student-loans/collection-of-student-loans-from-6-april-2026
* DWP, "Review of the automatic enrolment earnings trigger and qualifying earnings band for 2026/27" (18 Dec 2025)
  https://www.gov.uk/government/publications/review-of-the-automatic-enrolment-earnings-trigger-and-qualifying-earnings-band-for-202627
  and The Pensions Regulator, "Earnings thresholds" (per pay reference period)
  https://www.thepensionsregulator.gov.uk/employers/new-employers/im-an-employer-who-has-to-provide-a-pension/declare-your-compliance/ongoing-duties-for-employers/earnings-thresholds
* GOV.UK, "Workplace pensions: what you, your employer and the government pay" (employer 3 %, total 8 %)
  https://www.gov.uk/workplace-pensions/what-you-your-employer-and-the-government-pay
* Acas, "Statutory sick pay changes 2026" (8 Apr 2026): SSP from the first day of sickness, no lower earnings limit,
  lower of 80 % of average weekly earnings or the weekly rate. https://www.acas.org.uk/statutory-sick-pay-changes-2026
* GOV.UK, "Statutory Sick Pay (SSP): employer guide", Eligibility and Entitlement pages (read 28 Oct 2026): paid
  from the first full day of sickness, £123.25 or 80 % of average weekly earnings, whichever is lower.
  https://www.gov.uk/employers-sick-pay/entitlement
* Pensions Act 2014 explanatory notes, Part 6 (state pension age 66 to 67 for those born 6 Apr 1960 to 5 Mar 1961)
  https://www.legislation.gov.uk/ukpga/2014/19/notes/division/6/3/data.pdf
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

TAX_YEAR: Final = "2026-27"
RELATED_TAX_YEAR: Final = "26-27"  # the FPS / EPS <RelatedTaxYear>
VERIFIED_ON: Final = "28 Oct 2026"
RATES_URL: Final = "https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2026-to-2027"
PAYE_SPEC_URL: Final = "https://www.gov.uk/government/publications/payroll-technical-specifications-income-tax"
NI_SPEC_URL: Final = (
    "https://assets.publishing.service.gov.uk/media/6a3bc1fe4c7605ab567238ff/NI-Guidance-2026-27_v1.1.odt"
)
SL_SPEC_URL: Final = (
    "https://www.gov.uk/government/publications/payroll-technical-specifications-student-loans/"
    "collection-of-student-loans-from-6-april-2026"
)
AE_URL: Final = (
    "https://www.gov.uk/government/publications/"
    "review-of-the-automatic-enrolment-earnings-trigger-and-qualifying-earnings-band-for-202627"
)
TPR_THRESHOLDS_URL: Final = (
    "https://www.thepensionsregulator.gov.uk/employers/new-employers/im-an-employer-who-has-to-provide-a-pension/"
    "declare-your-compliance/ongoing-duties-for-employers/earnings-thresholds"
)

Frequency = Literal["weekly", "fortnightly", "four_weekly", "monthly"]
FREQUENCIES: Final[tuple[Frequency, ...]] = ("weekly", "fortnightly", "four_weekly", "monthly")
#: Pay periods in a tax year, for dividing annual thresholds (student loans) and numbering runs.
PERIODS_IN_YEAR: Final[dict[Frequency, int]] = {"weekly": 52, "fortnightly": 26, "four_weekly": 13, "monthly": 12}
#: Weeks in one pay period (PAYE uses weekly tables times this for 2- and 4-weekly pay; months use monthly tables).
WEEKS_IN_PERIOD: Final[dict[Frequency, int]] = {"weekly": 1, "fortnightly": 2, "four_weekly": 4, "monthly": 1}
#: RTI data item 42, Pay frequency.
RTI_PAY_FREQ: Final[dict[Frequency, str]] = {"weekly": "W1", "fortnightly": "W2", "four_weekly": "W4", "monthly": "M1"}


# --------------------------------------------------------------------------- #
# Income tax (PAYE Tax Table Routines v24.0, Appendices A to C)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TaxRegime:
    """One set of rates and annual bandwidths, in the routine's order (lowest rate first)."""

    name: str
    prefix: str  # "" (England and NI), "S" (Scotland), "C" (Wales)
    rates_bp: tuple[int, ...]  # R1, R2, ... (the last rate has no upper limit)
    bandwidths_pence: tuple[int, ...]  # B1, B2, ... (one fewer than the rates)
    cumulative_tax_pence: tuple[int, ...]  # K1, K2, ... as published
    basic_pointer: int  # G: the basic rate is rates_bp[G - 1]; D0 is rates_bp[G], D1 rates_bp[G + 1] ...


ENGLAND_NI: Final = TaxRegime(
    name="England and Northern Ireland",
    prefix="",
    rates_bp=(1000, 2000, 4000, 4500),  # Rate 1 (10 %) has a zero bandwidth: the old starting rate
    bandwidths_pence=(0, 3_770_000, 8_744_000),
    cumulative_tax_pence=(0, 754_000, 4_251_600),
    basic_pointer=2,
)
SCOTLAND: Final = TaxRegime(
    name="Scotland",
    prefix="S",
    rates_bp=(1900, 2000, 2100, 4200, 4500, 4800),
    bandwidths_pence=(396_700, 1_298_900, 1_413_600, 3_133_800, 6_271_000),
    cumulative_tax_pence=(75_373, 335_153, 632_009, 1_948_205, 4_770_155),
    basic_pointer=2,
)
WALES: Final = TaxRegime(
    name="Wales",
    prefix="C",
    rates_bp=(1000, 2000, 4000, 4500),
    bandwidths_pence=(0, 3_770_000, 8_744_000),  # Appendix C gives only rates and K; bands follow England's
    cumulative_tax_pence=(0, 754_000, 4_251_600),
    basic_pointer=2,
)
REGIMES: Final = {"": ENGLAND_NI, "S": SCOTLAND, "C": WALES}

PERSONAL_ALLOWANCE_PENCE: Final = 1_257_000  # £12,570
EMERGENCY_CODE: Final = "1257L"  # operated W1 / M1 (or X) per the rates page
REGULATORY_LIMIT_BP: Final = 5000  # M, Maxrate: no more than 50 % of the period's pay deducted as tax
#: Free pay (or additional pay) for each 500 of code above the remainder: (500 x £10) / 52 or / 12, rounded up.
FREE_PAY_500_WEEK_PENCE: Final = 9_616
FREE_PAY_500_MONTH_PENCE: Final = 41_667


# --------------------------------------------------------------------------- #
# Class 1 National Insurance (NI Guidance for software developers 2026-27)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class NiLimits:
    """Earnings limits for one earnings period, in pence (section 9.2: whole pounds)."""

    st: int
    lel: int
    pt: int
    fust: int  # Freeport / Investment Zone upper secondary threshold
    uel: int  # also UST, AUST and VUST in 2026-27


NI_LIMITS: Final[dict[str, NiLimits]] = {
    "weekly": NiLimits(st=9_600, lel=12_900, pt=24_200, fust=48_100, uel=96_700),
    "fortnightly": NiLimits(st=19_300, lel=25_800, pt=48_400, fust=96_200, uel=193_400),
    "four_weekly": NiLimits(st=38_500, lel=51_600, pt=96_700, fust=192_400, uel=386_700),
    "monthly": NiLimits(st=41_700, lel=55_900, pt=104_800, fust=208_300, uel=418_900),
    "annual": NiLimits(st=500_000, lel=670_800, pt=1_257_000, fust=2_500_000, uel=5_027_000),
}
#: Weekly figures used to pro-rate a director's annual earnings period (section 6.8): annual / 52 x weeks, rounded
#: up to the pound, except the LEL which is the weekly LEL x weeks.
NI_ANNUAL_FOR_PRO_RATA: Final = NI_LIMITS["annual"]
NI_WEEKLY_LEL_PENCE: Final = 12_900


@dataclass(frozen=True)
class NiRates:
    """Basis points per band: (ST-LEL, LEL-PT, PT-FUST, FUST-UEL, above UEL). Employee bands below PT are 0."""

    employee: tuple[int, int, int, int, int]
    employer: tuple[int, int, int, int, int]
    description: str


# Appendix 1 of the NI guidance, cross-checked against sections 3 and 4 of the rates page.
NI_CATEGORIES: Final[dict[str, NiRates]] = {
    "A": NiRates((0, 0, 800, 800, 200), (1500, 1500, 1500, 1500, 1500), "Standard"),
    "B": NiRates((0, 0, 185, 185, 200), (1500, 1500, 1500, 1500, 1500), "Married women and widows (reduced rate)"),
    "C": NiRates((0, 0, 0, 0, 0), (1500, 1500, 1500, 1500, 1500), "Over State Pension age"),
    "D": NiRates((0, 0, 200, 200, 200), (0, 0, 0, 1500, 1500), "Investment Zone, deferment"),
    "E": NiRates((0, 0, 185, 185, 200), (0, 0, 0, 1500, 1500), "Investment Zone, reduced rate"),
    "F": NiRates((0, 0, 800, 800, 200), (0, 0, 0, 1500, 1500), "Freeport"),
    "H": NiRates((0, 0, 800, 800, 200), (0, 0, 0, 0, 1500), "Apprentice under 25"),
    "I": NiRates((0, 0, 185, 185, 200), (0, 0, 0, 1500, 1500), "Freeport, reduced rate"),
    "J": NiRates((0, 0, 200, 200, 200), (1500, 1500, 1500, 1500, 1500), "Deferment"),
    "K": NiRates((0, 0, 0, 0, 0), (0, 0, 0, 1500, 1500), "Investment Zone, over State Pension age"),
    "L": NiRates((0, 0, 200, 200, 200), (0, 0, 0, 1500, 1500), "Freeport, deferment"),
    "M": NiRates((0, 0, 800, 800, 200), (0, 0, 0, 0, 1500), "Under 21"),
    "N": NiRates((0, 0, 800, 800, 200), (0, 0, 0, 1500, 1500), "Investment Zone"),
    "S": NiRates((0, 0, 0, 0, 0), (0, 0, 0, 1500, 1500), "Freeport, over State Pension age"),
    "V": NiRates((0, 0, 800, 800, 200), (0, 0, 0, 0, 1500), "Veteran (first civilian job)"),
    "Z": NiRates((0, 0, 200, 200, 200), (0, 0, 0, 0, 1500), "Under 21, deferment"),
}
#: Letters whose employer relief needs the Freeport / Investment Zone workplace postcode (FPS rule NILETTER.2).
NI_NEEDS_WORKPLACE_POSTCODE: Final = frozenset("FILSNEDK")
#: Reduced-rate letters, only for women born before 6 April 1961 (FPS rules NILETTER.0 and NILETTER.3).
NI_REDUCED_RATE: Final = frozenset("BEI")

EMPLOYMENT_ALLOWANCE_PENCE: Final = 1_050_000  # £10,500 a year


# --------------------------------------------------------------------------- #
# Student and postgraduate loans
# --------------------------------------------------------------------------- #

LoanPlan = Literal["1", "2", "4", "5"]
STUDENT_LOAN_THRESHOLDS_PENCE: Final[dict[str, int]] = {
    "1": 2_690_000,
    "2": 2_938_500,
    "4": 3_379_500,
    "5": 2_500_000,
}
POSTGRAD_THRESHOLD_PENCE: Final = 2_100_000
STUDENT_LOAN_RATE_BP: Final = 900
POSTGRAD_RATE_BP: Final = 600


# --------------------------------------------------------------------------- #
# Statutory pay
# --------------------------------------------------------------------------- #

SSP_WEEKLY_PENCE: Final = 12_325  # £123.25, or 80 % of average weekly earnings if lower
SSP_AWE_BP: Final = 8000
SSP_MAX_WEEKS: Final = 28
SMP_WEEKLY_PENCE: Final = 19_432  # £194.32 (weeks 7-39), or 90 % of AWE if lower
SMP_AWE_BP: Final = 9000
SMP_HIGHER_WEEKS: Final = 6
SMP_MAX_WEEKS: Final = 39
#: Recovery of SMP, SPP, SAP, ShPP, SPBP and SNCP (rates page section 10): 92 %, or 109 % when the employer's total
#: Class 1 NI for the previous tax year was £45,000 or less (the EPS reports 100 % as "recovered" and the extra 9 %
#: as "NIC compensation"). SSP cannot be recovered.
STAT_PAY_RECOVERY_BP: Final = 9200
STAT_PAY_RECOVERY_SMALL_BP: Final = 10900
SMALL_EMPLOYER_NIC_LIMIT_PENCE: Final = 4_500_000


# --------------------------------------------------------------------------- #
# Automatic enrolment (Pensions Act 2008; thresholds per pay reference period from TPR)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AeThresholds:
    lower_qe: int  # lower level of qualifying earnings
    trigger: int  # earnings trigger: an eligible jobholder earns MORE than this (Pensions Act 2008 s.3(1))
    upper_qe: int  # upper level of qualifying earnings


AE_THRESHOLDS: Final[dict[str, AeThresholds]] = {
    "weekly": AeThresholds(lower_qe=12_000, trigger=19_200, upper_qe=96_700),
    "fortnightly": AeThresholds(lower_qe=24_000, trigger=38_400, upper_qe=193_400),
    "four_weekly": AeThresholds(lower_qe=48_000, trigger=76_800, upper_qe=386_700),
    "monthly": AeThresholds(lower_qe=52_000, trigger=83_300, upper_qe=418_900),
    "annual": AeThresholds(lower_qe=624_000, trigger=1_000_000, upper_qe=5_027_000),
}
AE_MIN_EMPLOYER_BP: Final = 300  # 3 % of qualifying earnings
AE_MIN_TOTAL_BP: Final = 800  # 8 % of qualifying earnings
AE_MIN_AGE: Final = 22  # eligible jobholder: aged at least 22 and under State Pension age
AE_WORKER_MIN_AGE: Final = 16  # jobholder / entitled worker: aged at least 16 and under 75
AE_WORKER_MAX_AGE: Final = 75
RAS_BASIC_RELIEF_BP: Final = 2000  # relief at source: the member pays 80 %, the scheme claims 20 % from HMRC
