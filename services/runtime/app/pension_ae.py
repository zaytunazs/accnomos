"""Workplace pension: automatic enrolment assessment and contributions, per employee per pay period. Pure code.

Assessment (Pensions Act 2008 ss.1, 3, 7, 8; thresholds per pay reference period from The Pensions Regulator, see
app/paye_rates.py):

* eligible jobholder: aged at least 22 and under State Pension age, earnings MORE than the earnings trigger
  (s.3(1) says "more than"; GOV.UK's employee page says "at least £10,000", so the boundary penny is flagged).
  Must be enrolled automatically.
* non-eligible jobholder: aged 16 to 74 with earnings above the lower level of qualifying earnings but not an
  eligible jobholder. Can opt in; the employer must then contribute.
* entitled worker: aged 16 to 74 with earnings at or below the lower level. Can ask to join; the employer does not
  have to contribute.
* not a worker for auto-enrolment: under 16 or 75 and over.

Contributions: on qualifying earnings (earnings in the period between the lower and upper levels) or on all pay
("full pay", which the employer must certify meets the alternative quality tests: not checked here). Minimum on
qualifying earnings: employer 3 %, total 8 % (GOV.UK, "what you, your employer and the government pay").

Tax relief basis:
* net pay arrangement: the employee's contribution comes off pay before tax (not before NI);
* relief at source (RAS): the employee pays 80 % from net pay and the scheme claims 20 % basic-rate relief from HMRC;
* salary sacrifice: the employee gives up that much salary; the employer pays it in as an employer contribution,
  so tax and NI are worked out on the lower pay.

Opt-out: the employee can opt out within one month of being enrolled and get back what they paid
(https://www.gov.uk/workplace-pensions/if-you-want-to-leave-your-workplace-pension-scheme).
Rounding of contributions is to the nearest penny, half up: an assumption; providers state their own.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from typing import Literal

from app import paye_rates as R
from app.paye import BP, add_months, age_on, half_up, state_pension_date
from app.paye_rates import Frequency

Category = Literal["eligible_jobholder", "non_eligible_jobholder", "entitled_worker", "not_a_worker"]
Basis = Literal["qualifying", "full_pay"]
Arrangement = Literal["net_pay", "relief_at_source", "salary_sacrifice"]
Provider = Literal["generic", "nest", "peoples_pension", "smart_pension", "now_pensions"]

CATEGORY_LABELS: dict[str, str] = {
    "eligible_jobholder": "Eligible jobholder (enrol automatically)",
    "non_eligible_jobholder": "Non-eligible jobholder (can opt in; employer contributes)",
    "entitled_worker": "Entitled worker (can join; employer need not contribute)",
    "not_a_worker": "Outside auto-enrolment age (under 16 or 75+)",
}
ARRANGEMENT_LABELS: dict[str, str] = {
    "net_pay": "Net pay arrangement (before tax)",
    "relief_at_source": "Relief at source (employee pays 80%, scheme claims 20%)",
    "salary_sacrifice": "Salary sacrifice (employer pays it all; tax and NI on lower pay)",
}


@dataclass(frozen=True)
class Assessment:
    category: Category
    age: int
    earnings_pence: int
    thresholds: R.AeThresholds
    reached_spa: bool
    notes: tuple[str, ...] = ()


def assess(dob: date, on: date, earnings_pence: int, freq: Frequency) -> Assessment:
    """Who the person is for auto-enrolment in this pay reference period, on its pay date."""
    th = R.AE_THRESHOLDS[freq]
    age = age_on(dob, on)
    spa = on >= state_pension_date(dob)
    notes: list[str] = []
    if earnings_pence == th.trigger:
        notes.append(
            "Earnings are exactly the trigger: the Pensions Act says 'more than', so not an eligible jobholder; "
            "check with your pension provider"
        )
    if age < R.AE_WORKER_MIN_AGE or age >= R.AE_WORKER_MAX_AGE:
        cat: Category = "not_a_worker"
    elif age >= R.AE_MIN_AGE and not spa and earnings_pence > th.trigger:
        cat = "eligible_jobholder"
    elif earnings_pence > th.lower_qe:
        cat = "non_eligible_jobholder"
    else:
        cat = "entitled_worker"
    return Assessment(cat, age, earnings_pence, th, spa, tuple(notes))


@dataclass(frozen=True)
class Scheme:
    """The employer's pension scheme settings (EmployerSettings.pension)."""

    provider: Provider = "generic"
    basis: Basis = "qualifying"
    arrangement: Arrangement = "relief_at_source"
    employer_bp: int = 300
    employee_bp: int = 500


@dataclass(frozen=True)
class Contribution:
    member: bool  # contributions were taken this period
    base_pence: int  # qualifying earnings or full pay used
    band_low_pence: int
    band_high_pence: int
    employer_pence: int  # what the employer pays in (salary sacrifice: including the sacrificed amount)
    employee_gross_pence: int  # the employee's contribution before any tax relief
    employee_deducted_pence: int  # what comes off the payslip (RAS: 80 %; salary sacrifice: 0, pay is lower instead)
    sacrifice_pence: int  # gross pay given up (salary sacrifice only)
    relief_claimed_by_scheme_pence: int  # RAS: the 20 % the scheme claims from HMRC
    arrangement: Arrangement
    warnings: tuple[str, ...] = ()

    @property
    def to_provider_pence(self) -> int:
        """Paid to the pension provider this period by the employer (its share and what it took from pay)."""
        return self.employer_pence + self.employee_deducted_pence


NO_CONTRIBUTION = Contribution(False, 0, 0, 0, 0, 0, 0, 0, 0, "relief_at_source")


def contributions(scheme: Scheme, freq: Frequency, pensionable_pence: int) -> Contribution:
    """Contributions for a member on `pensionable_pence` (pay before any salary sacrifice)."""
    th = R.AE_THRESHOLDS[freq]
    if scheme.basis == "qualifying":
        low, high = th.lower_qe, th.upper_qe
        base = max(0, min(pensionable_pence, high) - low)
    else:
        low, high = 0, 0
        base = max(0, pensionable_pence)
    er = half_up(Fraction(base * scheme.employer_bp) * BP)
    ee_gross = half_up(Fraction(base * scheme.employee_bp) * BP)
    warnings: list[str] = []
    if scheme.basis == "qualifying" and (
        scheme.employer_bp < R.AE_MIN_EMPLOYER_BP or scheme.employer_bp + scheme.employee_bp < R.AE_MIN_TOTAL_BP
    ):
        warnings.append("Below the auto-enrolment minimum (employer 3%, total 8% of qualifying earnings)")
    if scheme.basis == "full_pay":
        warnings.append("Full-pay basis: the employer must certify it meets the alternative quality requirement")
    sacrifice = deducted = relief = 0
    if scheme.arrangement == "salary_sacrifice":
        sacrifice, er, deducted = ee_gross, er + ee_gross, 0
    elif scheme.arrangement == "relief_at_source":
        deducted = half_up(Fraction(base * scheme.employee_bp) * BP * (10_000 - R.RAS_BASIC_RELIEF_BP) * BP)
        relief = ee_gross - deducted
    else:
        deducted = ee_gross
    return Contribution(
        True, base, low, high, er, ee_gross, deducted, sacrifice, relief, scheme.arrangement, tuple(warnings)
    )


def opt_out_ends(enrolled_on: date) -> date:
    """The last day of the one-month opt-out window that starts on the enrolment date (an approximation: the window
    runs from the later of the enrolment date and the day the employee got the enrolment information)."""
    return add_months(enrolled_on, 1)


# --------------------------------------------------------------------------- #
# Contribution files for the pension provider
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ScheduleRow:
    employee_id: str
    payroll_id: str
    title: str
    forename: str
    surname: str
    nino: str
    dob: date | None
    gender: str
    category: str
    pensionable_pence: int
    employer_pence: int
    employee_pence: int  # as deducted (RAS: net of relief; Nest and People's Pension want this)
    employee_gross_pence: int
    enrolled_on: date | None
    opted_out_on: date | None
    left_on: date | None
    gross_pay_pence: int
    start_date: date | None
    address: tuple[str, ...] = ()
    postcode: str = ""
    email: str = ""
    salary_sacrifice: bool = False
    reason_code: str = ""  # overrides the provider's derived missing/partial contribution code


@dataclass(frozen=True)
class ScheduleHeader:
    period_start: date
    period_end: date
    pay_date: date
    frequency: Frequency
    provider_ref: str = ""  # Nest employer reference / People's Pension admin account / NOW: ER code
    payment_source: str = ""  # Nest payment source name
    pay_code: str = ""  # NOW: Pensions pay code
    due_date: date | None = None
    arrangement: Arrangement = "net_pay"
    period_number: int = 0  # tax week or month of the pay date (Smart Pension field 10)


class PensionFileError(ValueError):
    pass


def _status(h: ScheduleHeader, r: ScheduleRow) -> Literal["left", "opted_out", "no_earnings", ""]:
    """Why a row may have no or partial contributions, in the order the providers' codes rank them."""
    if r.left_on is not None and r.left_on <= h.period_end:
        return "left"
    if r.opted_out_on is not None and r.opted_out_on <= h.period_end:
        return "opted_out"
    if r.pensionable_pence <= 0:
        return "no_earnings"
    return ""


def _money(p: int) -> str:
    return f"{p / 100:.2f}"


def _safe(s: str) -> str:
    return f"'{s}" if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def generic_csv(h: ScheduleHeader, rows: list[ScheduleRow]) -> str:
    """Accnomos's own layout, one row per employee: any provider can map it."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(
        [
            "Payroll ID", "Forename", "Surname", "NI number", "Date of birth", "Assessment", "Pay period start",
            "Pay period end", "Pay date", "Pensionable earnings", "Employer contribution", "Employee contribution",
            "Employee contribution (gross)", "Enrolled on", "Opted out on", "Left on",
        ]
    )  # fmt: skip
    for r in rows:
        w.writerow(
            [
                _safe(r.payroll_id), _safe(r.forename), _safe(r.surname), r.nino,
                r.dob.isoformat() if r.dob else "", CATEGORY_LABELS.get(r.category, r.category),
                h.period_start.isoformat(), h.period_end.isoformat(), h.pay_date.isoformat(),
                _money(r.pensionable_pence), _money(r.employer_pence), _money(r.employee_pence),
                _money(r.employee_gross_pence), r.enrolled_on.isoformat() if r.enrolled_on else "",
                r.opted_out_on.isoformat() if r.opted_out_on else "", r.left_on.isoformat() if r.left_on else "",
            ]
        )  # fmt: skip
    return buf.getvalue()


NEST_FREQ = {"weekly": "Weekly", "fortnightly": "Fortnightly", "four_weekly": "Four Weekly", "monthly": "Monthly"}
#: Detail field 9, "Reason for partial or non-payment" (guide section 3.2.2): 1 no further contributions (left),
#: 9 member has opted out, 5 member has insufficient earnings.
NEST_REASON = {"left": "1", "opted_out": "9", "no_earnings": "5", "": ""}
NEST_FILE_VERSION = "4"  # trailer field 3, "Please enter 4"


def nest_csv(h: ScheduleHeader, rows: list[ScheduleRow]) -> str:
    """Nest contribution schedule ("CS"), from Nest's "Employer payroll guide" (the edition on Nest's site, read 28 Oct
    2026; it asks for file version 4 in the trailer), section 3.2:
    https://www.nestpensions.org.uk/schemeweb/dam/nestlibrary/employer-payroll-guide.pdf
    Header H (11 fields: employer reference, CS, earnings period end date, payment source, payment due date,
    frequency, two exception-schedule fields left blank, earnings period start date, bulk update), one D record per
    worker (21 fields: surname, NI number or else the alternative unique identifier, pensionable earnings, a blank
    family-leave field, employer and member contributions, reason code, then fields 10-21 for group, payment source,
    opt-out notice and second-enrolment changes, all blank here) and trailer T (count of D records, file version 4).
    Dates YYYY-MM-DD. Member contributions are what was deducted (relief at source: net of 20 %).
    Frequency must match the schedule's frequency in Nest exactly; Nest also offers "Tax Weekly" and "Tax Monthly",
    which this file does not write. Reason 9 (opted out) is for opt-outs the employer was told about; Nest's paper
    opt-out notice fields 17 and 18 are left blank."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(
        [
            "H", h.provider_ref, "CS", h.period_end.isoformat(), h.payment_source,
            h.due_date.isoformat() if h.due_date else "", NEST_FREQ[h.frequency], "", "",
            h.period_start.isoformat(), "",
        ]
    )  # fmt: skip
    for r in rows:
        reason = r.reason_code or NEST_REASON[_status(h, r)]
        w.writerow(
            [
                "D", _safe(r.surname[:30]), r.nino, _safe(r.payroll_id[:30]) if not r.nino else "",
                _money(r.pensionable_pence), "", _money(r.employer_pence), _money(r.employee_pence), reason,
                *([""] * 12),
            ]
        )  # fmt: skip
    w.writerow(["T", str(len(rows)), NEST_FILE_VERSION])
    return buf.getvalue()


#: Detail field F2, "Missing/partial pension code": 1 left the company, 4 chosen to stop contributions,
#: 5 earnings below the threshold or no pension-related earnings.
TPP_REASON = {"left": "1", "opted_out": "4", "no_earnings": "5", "": ""}
TPP_DETAIL_HEADINGS = [
    "Record Type", "Date of Birth", "Unique Identifier", "Employer Pension Contribution",
    "Employee Pension Contribution", "Missing/partial pension code", "EAC/ELC premium", "Pensionable earnings per PRP",
]  # fmt: skip
#: Characters The People's Pension refuses anywhere in the file (data requirements v9, "Essential requirements").
_TPP_FORBIDDEN = str.maketrans("", "", "=!\u2018\u2019'[]\u201c\u201d\"\\")


def _tpp_text(s: str) -> str:
    return s.translate(_TPP_FORBIDDEN).replace(",", " ").strip()[:50]


def peoples_pension_csv(h: ScheduleHeader, rows: list[ScheduleRow]) -> str:
    """The People's Pension contributions file, "Contributions file data requirements" version 9 (with effect from
    August 2020; still the version The People's Pension links to, read 28 Oct 2026):
    https://uvlznp.files.cmp.optimizely.com/download/assets/contributions-file-data-requirements.pdf/15821c5c27ad11f1b359f6bb85ab62d3
    Header H (admin account, pay period start and end, file type CO); then column headings, which the guide requires
    "for the details record section of the file only"; one D record per employee (date of birth, unique identifier,
    employer and employee contributions, missing/partial code, EAC/ELC premium, pensionable earnings per pay
    reference period); trailer T with the employer plus employee total. The characters = ! ' [ ] " \\ are not
    allowed anywhere, so they are removed from text rather than quoted. Employee contributions are as deducted."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_NONE, escapechar=None)
    w.writerow(
        ["H", _tpp_text(h.provider_ref), h.period_start.strftime("%d/%m/%Y"), h.period_end.strftime("%d/%m/%Y"), "CO"]
    )
    w.writerow(TPP_DETAIL_HEADINGS)
    total = 0
    for r in rows:
        total += r.employer_pence + r.employee_pence
        w.writerow(
            [
                "D", r.dob.strftime("%d/%m/%Y") if r.dob else "", _tpp_text(r.payroll_id),
                _money(r.employer_pence), _money(r.employee_pence), r.reason_code or TPP_REASON[_status(h, r)], "",
                _money(r.pensionable_pence),
            ]
        )  # fmt: skip
    w.writerow(["T", _money(total)])
    return buf.getvalue()


SMART_PAPDIS_HEADINGS = [
    "PAPDIS Version", "Pension Provider ID", "Employer ID", "Group", "Sub Group", "Pay Period Start Date",
    "Pay Period End Date", "Contribution Deduction Date", "Frequency Code", "Tax Period", "Title", "Forename 1",
    "Forename 2", "Surname", "Employee ID", "Birth Date", "Gender", "National Insurance Number", "Address 1",
    "Address 2", "Address 3", "Address 4", "Postcode", "Country", "Email Address", "Employment Start Date",
    "Exit Date", "Exit Reason Code", "Assessment Code", "Event Code", "Event Date", "Deferral Date",
    "AE Opt-Out Date", "AE Opt-Out Reference", "Enrolment Communications Issued Date",
    "Employer Contributions Amount", "Employee Contributions Amount", "Additional Voluntary Contributions Amount",
    "Additional Voluntary Contributions Percent", "Pensionable Earnings Amount", "Employer Contributions Percent",
    "Employee Contributions Percent", "Salary Sacrifice Indicator",
]  # fmt: skip
SMART_TITLES = frozenset(["Mr", "Mrs", "Ms", "Miss", "Dr", "Lord", "Lady", "Sir", "Prof", "Rev", "Captain", "Bursar"])
#: Field 29, Assessment Code.
SMART_ASSESSMENT = {
    "not_a_worker": "0",
    "eligible_jobholder": "1",
    "non_eligible_jobholder": "2",
    "entitled_worker": "3",
}
#: Field 30, Event Code when the member was enrolled in this pay period: 1 automatic enrolment, 2 opt-in,
#: 3 voluntary joiner.
SMART_EVENT = {"eligible_jobholder": "1", "non_eligible_jobholder": "2", "entitled_worker": "3", "not_a_worker": "3"}


def _pct(part: int, base: int) -> str:
    """A contribution as a percentage of pensionable earnings: up to 3 decimal places, no % sign."""
    if base <= 0:
        return "0"
    thousandths = half_up(Fraction(part * 100_000, base))
    whole, frac = divmod(thousandths, 1000)
    return f"{whole}.{frac:03d}".rstrip("0").rstrip(".")


def smart_pension_csv(h: ScheduleHeader, rows: list[ScheduleRow]) -> str:
    """Smart Pension contribution upload in PAPDIS 1.0 ("PAP01"), the 43 fields of Smart Pension's "CSV
    Specification - PAPDIS 1.0 - PAP01" (read 28 Oct 2026):
    https://uploads-ssl.webflow.com/5de10f93d41c9b7a31b7c9ca/5f461a5a33c1194026afe6e8_smart-pension-csv-data-interface-specification-papdis-1.0.pdf
    and its help centre "How do I use a PAPDIS file to upload pre-assessed pension contributions?".
    One row per employee after a row of field names (the specification does not say whether a heading row is
    expected; payroll packages' PAPDIS exports carry one). Dates YYYY-MM-DD, money in pounds and pence with no
    symbol or commas. Smart processes this file only for the net pay arrangement; relief at source is refused.
    Salary sacrifice: the whole contribution is the employer's and the employee amount is 0.00. Pensionable earnings
    are the earnings the contributions were worked out on (qualifying earnings: the band amount, as the spec asks)."""
    if h.arrangement == "relief_at_source":
        raise PensionFileError(
            "Smart Pension's PAPDIS upload is for the net pay arrangement only: contributions under relief at source "
            "are not processed through it (Smart Pension, CSV Specification PAPDIS 1.0). Ask Smart Pension for "
            "their relief at source template, or use the generic CSV."
        )
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(SMART_PAPDIS_HEADINGS)

    def d(x: date | None) -> str:
        return x.isoformat() if x else ""

    for r in rows:
        first, *rest = (r.forename or "").split(" ", 1) or [""]
        addr = [_safe(a[:35]) for a in r.address[:4]] + [""] * (4 - len(r.address[:4]))
        status = _status(h, r)
        enrolled_now = r.enrolled_on is not None and h.period_start <= r.enrolled_on <= h.period_end
        event = SMART_EVENT[r.category] if enrolled_now else "0"
        employee = 0 if r.salary_sacrifice else r.employee_pence
        w.writerow(
            [
                "PAP01", "Smart Pension", _safe(h.provider_ref), "", "", d(h.period_start), d(h.period_end),
                d(h.pay_date), R.RTI_PAY_FREQ[h.frequency], f"{h.period_number:02d}",
                r.title if r.title in SMART_TITLES else "", _safe(first[:35]), _safe((rest[0] if rest else "")[:35]),
                _safe(r.surname[:35]), _safe(r.payroll_id[:35]), d(r.dob), r.gender, r.nino, *addr, r.postcode, "",
                r.email, d(r.start_date), d(r.left_on) if status == "left" else "", "1" if status == "left" else "",
                SMART_ASSESSMENT[r.category], event, d(r.enrolled_on) if event != "0" else "", "",
                d(r.opted_out_on) if status == "opted_out" else "", "", "", _money(r.employer_pence),
                _money(employee), "0.00", "", _money(r.pensionable_pence), _pct(r.employer_pence, r.pensionable_pence),
                _pct(employee, r.pensionable_pence), "Y" if r.salary_sacrifice else "N",
            ]
        )  # fmt: skip
    return buf.getvalue()


NOW_FREQ = {"weekly": "Weekly", "fortnightly": "Fortnightly", "four_weekly": "Four-weekly", "monthly": "Monthly"}
NOW_CATEGORY = {
    "eligible_jobholder": "Eligible jobholder",
    "non_eligible_jobholder": "Non-eligible jobholder",
    "entitled_worker": "Entitled worker",
    "not_a_worker": "Worker",
}


def now_pensions_csv(h: ScheduleHeader, rows: list[ScheduleRow], period_number: int) -> str:
    """NOW: Pensions pension data file, the 36 items of "Understanding the pension data file" (page undated, read
    28 Oct 2026) in their listed order; contributions gross.
    https://www.nowpensions.com/support/employers/guides/understanding-the-pension-data-file"""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(
        [
            "Forename 1", "Forename 2", "Surname", "NINO", "STARTDATE", "Title", "DOB", "SEX", "PAYROLLNO", "PAYSTART",
            "PAYPERIOD", "PAYFREQ", "ENROL DATE", "POSTPONEMENT DATE", "ASSESSMENT", "ADDRESS 1", "ADDRESS 2",
            "ADDRESS 3", "ADDRESS 4", "ADDRESS 5", "POSTCODE", "EMAIL", "SAL SACRIFICE", "EE CONTS", "ER CONTS",
            "AVCs", "OPTIN", "OPTOUT", "GROSS PAY", "EXIT DATE", "EE CONT %", "ER CONT %", "PAY CODE", "ER CODE",
            "SCHEME CODE", "PENSIONABLE EARNINGS",
        ]
    )  # fmt: skip

    def d(x: date | None) -> str:
        return x.strftime("%d/%m/%Y") if x else ""

    for r in rows:
        first, *rest = (r.forename or "").split(" ", 1) or [""]
        addr = list(r.address[:5]) + [""] * (5 - len(r.address[:5]))
        w.writerow(
            [
                _safe(first), _safe(rest[0] if rest else ""), _safe(r.surname), r.nino, d(r.start_date), r.title,
                d(r.dob), r.gender, _safe(r.payroll_id), d(h.period_start), str(period_number), NOW_FREQ[h.frequency],
                d(r.enrolled_on), "", NOW_CATEGORY.get(r.category, "Worker"), *[_safe(a) for a in addr], r.postcode,
                r.email, "Y" if r.salary_sacrifice else "N",
                _money(0 if r.salary_sacrifice else r.employee_gross_pence), _money(r.employer_pence), "", "",
                d(r.opted_out_on), _money(r.gross_pay_pence), d(r.left_on), "", "", h.pay_code, h.provider_ref, "",
                _money(r.pensionable_pence),
            ]
        )  # fmt: skip
    return buf.getvalue()
