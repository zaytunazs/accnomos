"""PAYE income tax, Class 1 NI, student loans and statutory pay for one employee and one pay period. Pure code.

Every figure comes from app/paye_rates.py; every rounding follows the HMRC specification it cites:

* Income tax: "Specification for PAYE Tax Table Routines" v24.0 (Feb 2026). Free pay or additional pay from the
  code (para 4.3.1), cumulative or week 1 / month 1 (paras 4-11), tax due to date by Income Tests and Tax Formulae
  (para 4.4; thresholds to 4 dp of a pound, Cvalues rounded up to the pound, taxable pay rounded down to the pound,
  tax rounded down to the penny), the 50 % regulatory limit (para 4.5.2), weeks 53 / 54 / 56 (para 14).
* National Insurance: "NI Guidance for software developers 2026 to 2027" v1.1, exact percentage method (section 5),
  directors' annual or pro-rata annual earnings period (section 6), rounding (section 4: to the penny, half a
  penny or less disregarded).
* Student and postgraduate loans: "Collection of student loans from 6 April 2026": threshold divided by the number of
  periods (rounded down to the penny), deduction rounded down to the whole pound, on earnings for Class 1 NI.
* SSP (from 6 Apr 2026: day one, lower of 80 % of AWE or £123.25 a week) and SMP from the rates page.

Money is integer pence. Fractions keep intermediate figures exact until the specified rounding.
"""

from __future__ import annotations

import calendar
import math
import re
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from typing import Literal

from app import paye_rates as R
from app.paye_rates import Frequency

BP = Fraction(1, 10_000)


class PayeError(ValueError):
    """An input the rules cannot work with (an invalid tax code, an unknown NI letter...)."""


# --------------------------------------------------------------------------- #
# Rounding (all in pence)
# --------------------------------------------------------------------------- #


def floor_penny(x: Fraction) -> int:
    return math.floor(x)


def ceil_penny(x: Fraction) -> int:
    return math.ceil(x)


def floor_pound(x: Fraction) -> int:
    """Down to a whole pound, in pence."""
    return math.floor(x / 100) * 100


def ceil_pound(x: Fraction) -> int:
    return math.ceil(x / 100) * 100


def trunc_4dp(x: Fraction) -> Fraction:
    """To 4 decimal places of a pound (1/100 of a penny) "without applying any correction to the final place"."""
    return Fraction(math.floor(x * 100), 100) if x >= 0 else Fraction(math.ceil(x * 100), 100)


def ni_round(x: Fraction) -> int:
    """NI rounding (Social Security (Contributions) Regulations 2001 reg 12(1)(b): "any amount of a halfpenny or less
    shall be disregarded"), as HMRC applies it (NI guidance 2026-27 section 4.2): look only at the third decimal place
    of the pounds figure; 5 or less rounds down, 6 or more rounds up. So £67.5558 is £67.55 and £67.5568 is £67.56."""
    whole = math.floor(x)
    tenth = math.floor((x - whole) * 10)  # the third decimal place of the pounds figure
    return whole + (1 if tenth >= 6 else 0)


def half_up(x: Fraction) -> int:
    whole = math.floor(x)
    return whole + (1 if x - whole >= Fraction(1, 2) else 0)


# --------------------------------------------------------------------------- #
# Tax periods
# --------------------------------------------------------------------------- #


def tax_year_start(day: date) -> date:
    start = date(day.year, 4, 6)
    return start if day >= start else date(day.year - 1, 4, 6)


def tax_year_label(day: date) -> str:
    y = tax_year_start(day).year
    return f"{y}-{(y + 1) % 100:02d}"


def tax_week(day: date) -> int:
    """1 for 6-12 April ... 53 for the last day or two of the year (CWG2)."""
    return (day - tax_year_start(day)).days // 7 + 1


def tax_month(day: date) -> int:
    """1 for 6 April to 5 May ... 12 for 6 March to 5 April."""
    return (day.month - 4) % 12 + 1 if day.day >= 6 else (day.month - 5) % 12 + 1


def period_number(freq: Frequency, pay_date: date) -> int:
    """RTI data items 44 / 45: the tax week (weekly, 2- and 4-weekly: the last week of the period) or tax month."""
    if freq == "monthly":
        return tax_month(pay_date)
    w = tax_week(pay_date)
    k = R.WEEKS_IN_PERIOD[freq]
    return k * math.ceil(w / k)


def tax_month_bounds(tax_year_first: date, month: int) -> tuple[date, date]:
    """(6th, 5th) of tax month `month` (1-12) in the tax year starting `tax_year_first`."""
    y, m = tax_year_first.year, 4 + month - 1
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    start = date(y, m, 6)
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return start, date(ny, nm, 5)


def payment_due(tax_year_first: date, month: int) -> date:
    """PAYE for tax month `month` is due by the 22nd of the next tax month (paid electronically; the 19th by post).
    Source: https://www.gov.uk/pay-paye-tax ("the 22nd of the next tax month if you pay monthly")."""
    _, end = tax_month_bounds(tax_year_first, month)
    return date(end.year, end.month, 22)


# --------------------------------------------------------------------------- #
# Tax codes
# --------------------------------------------------------------------------- #

CODE_RE = re.compile(
    r"(?P<prefix>[SC])?(?P<body>NT|BR|D[0-8]|K[1-9][0-9]{0,5}|0T|[1-9][0-9]{0,5}[LMNPTY])"
    r"(?:\s*(?P<basis>W1|M1|X))?"
)


@dataclass(frozen=True)
class TaxCode:
    raw: str
    prefix: str  # "", "S" or "C"
    kind: Literal["suffix", "K", "BR", "D", "NT"]
    number: int = 0  # numeric part of a suffix or K code
    d_index: int = 0  # D0 -> 0, D1 -> 1 ...
    non_cumulative: bool = False

    @property
    def regime(self) -> R.TaxRegime:
        return R.REGIMES[self.prefix]

    @property
    def body(self) -> str:
        """The code as the FPS reports it (data item 55): no S/C prefix, no W1/M1."""
        if self.kind == "suffix":
            return "0T" if self.number == 0 else f"{self.number}{self.raw_suffix}"
        if self.kind == "K":
            return f"K{self.number}"
        if self.kind == "D":
            return f"D{self.d_index}"
        return self.kind

    @property
    def raw_suffix(self) -> str:
        m = CODE_RE.fullmatch(self.raw)
        return m.group("body")[-1] if m else "L"

    def display(self) -> str:
        basis = " W1/M1" if self.non_cumulative else ""
        return f"{self.prefix}{self.body}{basis}"


def parse_tax_code(text: str, non_cumulative: bool = False) -> TaxCode:
    """'1257L', 'S1257L', 'C1257L M1', 'K475', 'BR', 'D0', 'SD2', 'NT', '0T', '1257L X'. Raises PayeError."""
    raw = re.sub(r"\s+", " ", (text or "").strip().upper())
    m = CODE_RE.fullmatch(raw)
    if not m:
        raise PayeError(f"{text!r} is not a tax code this payroll can operate (e.g. 1257L, S1257L, K475, BR, D0, NT)")
    prefix, body = m.group("prefix") or "", m.group("body")
    nc = non_cumulative or bool(m.group("basis"))
    if body == "NT":
        if prefix:
            raise PayeError("There is no SNT or CNT code: NT applies to the whole UK")
        return TaxCode(raw, "", "NT", non_cumulative=nc)
    if body == "BR":
        return TaxCode(raw, prefix, "BR", non_cumulative=nc)
    if body.startswith("D"):
        d = int(body[1:])
        regime = R.REGIMES[prefix]
        if regime.basic_pointer + d >= len(regime.rates_bp):
            raise PayeError(f"{prefix}{body} is beyond the {regime.name} rates for {R.TAX_YEAR}")
        return TaxCode(raw, prefix, "D", d_index=d, non_cumulative=nc)
    if body.startswith("K"):
        return TaxCode(raw, prefix, "K", number=int(body[1:]), non_cumulative=nc)
    if body == "0T":
        return TaxCode(raw, prefix, "suffix", number=0, non_cumulative=nc)
    return TaxCode(raw, prefix, "suffix", number=int(body[:-1]), non_cumulative=nc)


def period1_allowance(number: int, monthly: bool) -> int:
    """Free pay (suffix codes) or additional pay (K codes) for week 1 or month 1, in pence (para 4.3.1)."""
    if number == 0:
        return 0
    q, r = divmod(number - 1, 500)
    r += 1
    annual = (r * 10 + 9) * 100
    value = ceil_penny(Fraction(annual, 12 if monthly else 52))
    return value + q * (R.FREE_PAY_500_MONTH_PENCE if monthly else R.FREE_PAY_500_WEEK_PENCE)


# --------------------------------------------------------------------------- #
# Income tax
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TaxResult:
    tax_pence: int  # deducted (+) or refunded (-) this period
    tax_due_to_date_pence: int  # L_n as limited: what has been deducted in the year so far, after this period
    taxable_pay_to_date_pence: int  # P_n (cumulative) or this period's pay (non-cumulative)
    free_pay_pence: int  # free pay (or minus additional pay) used this period, for the payslip
    regulatory_limited: bool = False
    basis: Literal["cumulative", "week1/month1", "week53"] = "cumulative"
    notes: tuple[str, ...] = ()


def _tax_on_taxable(regime: R.TaxRegime, u: Fraction, n: int, divisor: int) -> int:
    """Tax due on taxable pay `u` (pence, before rounding) at period n of `divisor` (52 or 12): para 4.4."""
    if u <= 0:
        return 0
    t = Fraction(floor_pound(u))
    cum_bands = []
    total = 0
    for b in regime.bandwidths_pence:
        total += b
        cum_bands.append(total)
    c = [Fraction(0)] + [trunc_4dp(Fraction(cb * n, divisor)) for cb in cum_bands]
    k = [Fraction(0)] + [trunc_4dp(Fraction(kk * n, divisor)) for kk in regime.cumulative_tax_pence]
    v = [ceil_pound(cx) for cx in c[1:]]
    # Income Test x: the first Cvalue that taxable pay does not exceed picks Tax Formula x; past the last, x + 1.
    formula = next((i + 1 for i, vx in enumerate(v) if u <= vx), len(v) + 1)
    rate = Fraction(regime.rates_bp[formula - 1]) * BP
    return floor_penny(k[formula - 1] + (t - c[formula - 1]) * rate)


def income_tax(
    code: TaxCode,
    freq: Frequency,
    period: int,
    pay_pence: int,
    pay_to_date_before_pence: int = 0,
    tax_to_date_before_pence: int = 0,
) -> TaxResult:
    """Tax for one payment. `period` is the tax week (weekly, 2- and 4-weekly) or tax month (monthly).

    Cumulative codes use pay and tax to date before this payment (including a previous employment's from a P45,
    when the employer is using them); week 1 / month 1 codes and weeks 53, 54 and 56 treat the payment alone.
    """
    monthly = freq == "monthly"
    divisor = 12 if monthly else 52
    k = R.WEEKS_IN_PERIOD[freq]
    week53 = not monthly and period > 52
    non_cum = code.non_cumulative or week53
    basis: Literal["cumulative", "week1/month1", "week53"] = (
        "week53" if week53 else "week1/month1" if code.non_cumulative else "cumulative"
    )
    regime = code.regime
    notes: list[str] = []
    if week53:
        notes.append(f"Week {period} payment: taxed on a week {k} basis, not cumulatively (PAYE spec para 14)")

    n = k if non_cum else period  # the Table week: weeks elapsed (non-cumulative) or week / month number
    p_n = Fraction(pay_pence if non_cum else pay_to_date_before_pence + pay_pence)
    free = 0
    if code.kind == "NT":
        liability = 0
    elif code.kind in ("BR", "D"):
        idx = regime.basic_pointer - 1 + (0 if code.kind == "BR" else 1 + code.d_index)
        liability = floor_penny(Fraction(floor_pound(p_n)) * regime.rates_bp[idx] * BP) if p_n > 0 else 0
    else:
        a1 = period1_allowance(code.number, monthly)
        free = n * a1 if code.kind == "suffix" else -n * a1
        u = p_n - free
        liability = _tax_on_taxable(regime, u, n, divisor)

    # Non-cumulative: each payment in isolation, so no refunds (paras 4.5.4, 8.3).
    tax = max(0, liability) if non_cum else liability - tax_to_date_before_pence

    limited = False
    if tax > 0:
        limit = floor_penny(Fraction(max(0, pay_pence)) * R.REGULATORY_LIMIT_BP * BP)
        if tax > limit:
            tax, limited = limit, True
            notes.append("Tax limited to 50% of this payment (overriding regulatory limit)")
    to_date = tax if non_cum else tax_to_date_before_pence + tax
    return TaxResult(
        tax_pence=tax,
        tax_due_to_date_pence=to_date,
        taxable_pay_to_date_pence=int(p_n),
        free_pay_pence=free,
        regulatory_limited=limited,
        basis=basis,
        notes=tuple(notes),
    )


# --------------------------------------------------------------------------- #
# National Insurance
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class NiResult:
    category: str
    employee_pence: int
    employer_pence: int
    # Earnings bands (exact-percentage method, steps 2-6), in pence
    st_to_lel: int = 0
    lel_to_pt: int = 0
    pt_to_fust: int = 0
    fust_to_uel: int = 0
    above_uel: int = 0
    at_lel: int = 0  # the LEL, when earnings reach it (RTI "earnings at LEL", whole pounds)
    gross_pence: int = 0

    @property
    def pt_to_uel(self) -> int:
        return self.pt_to_fust + self.fust_to_uel


def _limits(freq: Frequency | Literal["annual"]) -> R.NiLimits:
    return R.NI_LIMITS[freq]


def ni_on_earnings(gross_pence: int, category: str, limits: R.NiLimits) -> NiResult:
    """Exact percentage method, steps 1-8, for earnings `gross_pence` against one set of earnings limits."""
    rates = R.NI_CATEGORIES.get(category)
    if rates is None:
        raise PayeError(f"Unknown NI category letter {category!r}")
    gp = gross_pence
    if gp <= limits.st:
        return NiResult(category, 0, 0, gross_pence=gp)

    def band(lo: int, hi: int | None) -> int:
        top = gp if hi is None else min(gp, hi)
        return max(0, top - lo)

    s2, s3 = band(limits.st, limits.lel), band(limits.lel, limits.pt)
    s4, s5, s6 = band(limits.pt, limits.fust), band(limits.fust, limits.uel), band(limits.uel, None)
    e, r = rates.employee, rates.employer
    ee = ni_round(Fraction(s4 * e[2] + s5 * e[3]) * BP) + ni_round(Fraction(s6 * e[4]) * BP)
    er = ni_round(Fraction(s2 * r[0] + s3 * r[1] + s4 * r[2] + s5 * r[3]) * BP) + ni_round(Fraction(s6 * r[4]) * BP)
    return NiResult(
        category,
        ee,
        er,
        st_to_lel=s2,
        lel_to_pt=s3,
        pt_to_fust=s4,
        fust_to_uel=s5,
        above_uel=s6,
        at_lel=limits.lel if gp >= limits.lel else 0,
        gross_pence=gp,
    )


def ni_period(gross_pence: int, category: str, freq: Frequency) -> NiResult:
    """NI for an employee (not a director) on this period's earnings."""
    return ni_on_earnings(gross_pence, category, _limits(freq))


def director_limits(weeks: int) -> R.NiLimits:
    """Pro-rata annual earnings period for a director appointed in the year: `weeks` from the week of appointment to
    the end of the tax year (NI guidance 6.7-6.8). 52 weeks is the full annual period."""
    a = R.NI_ANNUAL_FOR_PRO_RATA
    if weeks >= 52:
        return a
    if weeks < 1:
        raise PayeError("A director's pro-rata period is at least one week")

    def pro(x: int) -> int:
        exact = Fraction(x * weeks, 52)
        return half_up(exact / 100) * 100 if weeks == 1 else ceil_pound(exact)

    return R.NiLimits(st=pro(a.st), lel=R.NI_WEEKLY_LEL_PENCE * weeks, pt=pro(a.pt), fust=pro(a.fust), uel=pro(a.uel))


@dataclass(frozen=True)
class DirectorNi:
    to_date: NiResult  # on earnings to date against the (pro-rata) annual limits
    employee_pence: int  # due this period: to date minus already paid
    employer_pence: int


def ni_director(
    earnings_to_date_pence: int,
    category: str,
    appointed_week: int | None,
    ee_paid_before: int,
    er_paid_before: int,
) -> DirectorNi:
    """A director's NI on the annual earnings method ("AN"): cumulative over the year, or from the week of
    appointment (pro rata) when appointed during it (section 6)."""
    weeks = 52 if not appointed_week or appointed_week <= 1 else 52 - min(appointed_week, 52) + 1
    res = ni_on_earnings(earnings_to_date_pence, category, director_limits(weeks))
    return DirectorNi(res, res.employee_pence - ee_paid_before, res.employer_pence - er_paid_before)


# --------------------------------------------------------------------------- #
# Student and postgraduate loans
# --------------------------------------------------------------------------- #


def loan_threshold(annual_pence: int, freq: Frequency) -> int:
    """Annual threshold / periods in the year, rounded down to the penny."""
    return floor_penny(Fraction(annual_pence, R.PERIODS_IN_YEAR[freq]))


def loan_deduction(ni_earnings_pence: int, annual_threshold_pence: int, rate_bp: int, freq: Frequency) -> int:
    thr = loan_threshold(annual_threshold_pence, freq)
    if ni_earnings_pence <= thr:
        return 0
    return floor_pound(Fraction(ni_earnings_pence - thr) * rate_bp * BP)


def student_loan(ni_earnings_pence: int, plan: str | None, freq: Frequency) -> int:
    if not plan:
        return 0
    if plan not in R.STUDENT_LOAN_THRESHOLDS_PENCE:
        raise PayeError(f"Unknown student loan plan {plan!r}: use 1, 2, 4 or 5")
    return loan_deduction(ni_earnings_pence, R.STUDENT_LOAN_THRESHOLDS_PENCE[plan], R.STUDENT_LOAN_RATE_BP, freq)


def postgrad_loan(ni_earnings_pence: int, has_loan: bool, freq: Frequency) -> int:
    if not has_loan:
        return 0
    return loan_deduction(ni_earnings_pence, R.POSTGRAD_THRESHOLD_PENCE, R.POSTGRAD_RATE_BP, freq)


# --------------------------------------------------------------------------- #
# Statutory pay
# --------------------------------------------------------------------------- #


def ssp_weekly(awe_pence: int) -> Fraction:
    """From 6 April 2026: the lower of £123.25 and 80 % of average weekly earnings."""
    return min(Fraction(R.SSP_WEEKLY_PENCE), Fraction(awe_pence) * R.SSP_AWE_BP * BP)


def ssp_amount(awe_pence: int, qualifying_days_per_week: int, days_to_pay: int) -> int:
    """SSP for `days_to_pay` qualifying days of a week with `qualifying_days_per_week` qualifying days: the daily rate
    (weekly / qualifying days) times days, rounded up to the penny, never more than the weekly rate. This reproduces
    every cell of HMRC's 2026-27 "amounts to pay" table (rates page section 11)."""
    if not 1 <= qualifying_days_per_week <= 7:
        raise PayeError("Qualifying days in a week are 1 to 7")
    if days_to_pay < 0:
        raise PayeError("Days to pay can't be negative")
    weekly = ssp_weekly(awe_pence)
    full_weeks, part = divmod(days_to_pay, qualifying_days_per_week)
    return full_weeks * ceil_penny(weekly) + ceil_penny(weekly * part / qualifying_days_per_week)


def smp_week(awe_pence: int, week_number: int) -> int:
    """SMP for one week of the 39: 90 % of AWE for the first 6, then the lower of £194.32 and 90 % of AWE.
    90 % of AWE is rounded up to the penny (an assumption: HMRC's employer guide wording, not in the rates page)."""
    if not 1 <= week_number <= R.SMP_MAX_WEEKS:
        raise PayeError("SMP is paid for weeks 1 to 39")
    ninety = ceil_penny(Fraction(awe_pence) * R.SMP_AWE_BP * BP)
    return ninety if week_number <= R.SMP_HIGHER_WEEKS else min(R.SMP_WEEKLY_PENCE, ninety)


def smp_amount(awe_pence: int, first_week: int, weeks: int) -> int:
    return sum(smp_week(awe_pence, w) for w in range(first_week, first_week + weeks))


# --------------------------------------------------------------------------- #
# State pension age (for auto-enrolment)
# --------------------------------------------------------------------------- #


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def state_pension_date(dob: date) -> date:
    """The date State Pension age is reached, for anyone of working age in 2026-27 (Pensions Act 2014 s.26):
    66 if born before 6 Apr 1960; 66 and 1-11 months if born 6 Apr 1960 to 5 Mar 1961 (one more month for each
    month of birth from the 6th); 67 if born 6 Mar 1961 to 5 Apr 1977. Later birth dates (68 from 2044 under the
    Pensions Act 2007) are treated as 67, which cannot be reached before 2044 anyway."""
    if dob < date(1960, 4, 6):
        return add_months(dob, 66 * 12)
    if dob < date(1961, 3, 6):
        months = 1
        while add_months(date(1960, 4, 6), months) <= dob:
            months += 1
        return add_months(dob, 66 * 12 + months)
    return add_months(dob, 67 * 12)


def age_on(dob: date, day: date) -> int:
    return day.year - dob.year - ((day.month, day.day) < (dob.month, dob.day))


def gbp(pence: int) -> str:
    sign = "-" if pence < 0 else ""
    return f"{sign}£{abs(pence) / 100:,.2f}"
