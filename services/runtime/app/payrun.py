"""PAYE payroll: employees, pay runs with year-to-date figures, and posting through the proposal -> approve flow.

    _System/Payroll/employer.json            PAYE references, Employment Allowance, pension scheme settings
    _System/Payroll/employees.json           the payroll record of each employee (see Employee: personal data)
    _System/Payroll/payruns/{run_id}.json    one pay run: {tax year}-{frequency}-{period}, e.g. 2026-27-monthly-07

Code calculates every figure (app/paye.py, app/pension_ae.py); nothing here is guessed by a model. A pay run goes:

    draft     prepared from the employees' pay, editable (hours, bonus, sick and maternity days...)
    proposed  "Send to Review": a Proposal with the run's balanced journal; the user approves it in Review
    posted    the journal is in the ledger; the run's figures count towards year to date

Undoing the journal (Review or the ledger) puts the run back to proposed; "Back to draft" rejects the proposal.

Accnomos does not file RTI. FPS and EPS files are generated for the user to check, and the user files with HMRC's
Basic PAYE Tools or their payroll provider (docs/HONESTY.md).

The journal on approval (pence):

    Dr 7000 Gross wages             gross pay after salary sacrifice (statutory pay included)
    Dr 7010 Employer's NI           employer Class 1 NI
    Dr 7020 Employer's pension      employer pension contributions (salary sacrifice included)
    Cr 2220 PAYE and NI (HMRC)      tax, employee and employer NI, student and postgraduate loans
    Cr 2230 Pension contributions   everything due to the pension provider (employer + employee)
    Cr 2240 Net wages               net pay due to employees
    Cr 2250 Other payroll deductions  deductions from net pay the user typed in (e.g. a staff loan)
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from datetime import date, timedelta
from fractions import Fraction
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from app import paye as P
from app import paye_rates as R
from app import pension_ae as AE
from app.books import SYSTEM, Books, now
from app.paye_rates import Frequency
from app.schemas import Check, ExtractedDoc, ExtractedLine, JournalLine, Proposal

log = logging.getLogger(__name__)

ROOT = f"{SYSTEM}/Payroll"
EMPLOYER = f"{ROOT}/employer.json"
EMPLOYEES = f"{ROOT}/employees.json"
RUNS = f"{ROOT}/payruns"

WAGES = "7000 Gross wages"
EMPLOYER_NI = "7010 Employer's NI"
EMPLOYER_PENSION = "7020 Employer's pension"
HMRC_LIABILITY = "2220 PAYE and NI (HMRC)"
PENSION_LIABILITY = "2230 Pension contributions"
NET_WAGES = "2240 Net wages"
OTHER_DEDUCTIONS = "2250 Other payroll deductions"

FILING_NOTE = (
    "File with HMRC's Basic PAYE Tools or your payroll provider. "
    "Direct submission from Accnomos is currently not available."
)
ESTIMATE_NOTE = "Estimate — check before filing"
RUN_ID_RE = re.compile(r"(\d{4}-\d{2})-(weekly|fortnightly|four_weekly|monthly)-(\d{2})")
NINO_RE = re.compile(
    r"([ACEHJLMOPRSWXY][A-CEGHJ-NPR-TW-Z]|B[A-CEHJ-NPR-TW-Z]|G[ACEGHJ-NPR-TW-Z]|[KT][A-CEGHJ-MPR-TW-Z]"
    r"|N[A-CEGHJL-NPR-SW-Z]|Z[A-CEGHJ-NPR-TW-Y])[0-9]{6}[A-D]"
)
Pence = Annotated[int, Field(ge=0, le=100_000_000_00)]


class PayrunError(ValueError):
    """The change cannot be made as asked."""


class PayrunConflict(PayrunError):
    """The run or an earlier one is in the wrong state."""


# --------------------------------------------------------------------------- #
# Settings and employees
# --------------------------------------------------------------------------- #


class PensionSettings(BaseModel):
    provider: AE.Provider = "generic"
    basis: AE.Basis = "qualifying"
    arrangement: AE.Arrangement = "relief_at_source"
    employer_bp: int = Field(default=300, ge=0, le=10_000)
    employee_bp: int = Field(default=500, ge=0, le=10_000)
    provider_ref: str = Field(default="", max_length=40)  # Nest EMPnnnnnnnnn / People's Pension account / NOW ER code
    payment_source: str = Field(default="", max_length=40)  # Nest
    pay_code: str = Field(default="", max_length=4)  # NOW: Pensions
    duties_start: date | None = None  # the employer's duties start date (first day auto-enrolment applies)

    def scheme(self) -> AE.Scheme:
        return AE.Scheme(self.provider, self.basis, self.arrangement, self.employer_bp, self.employee_bp)


class EmployerSettings(BaseModel):
    name: str = Field(default="", max_length=120)
    paye_office: str = Field(default="", pattern=r"^(\d{3})?$")  # HMRC office number: 3 digits
    paye_reference: str = Field(default="", max_length=10)  # the part after the slash, e.g. AB12345
    accounts_office_ref: str = Field(default="", pattern=r"^([0-9]{3}P[A-Z][0-9]{7}[0-9X])?$")
    cotax_ref: str = Field(default="", pattern=r"^(\d{10})?$")
    claim_employment_allowance: bool = False
    small_employer_relief: bool = False  # Class 1 NI last tax year £45,000 or less: recover 109 % of SMP etc.
    pension: PensionSettings = Field(default_factory=PensionSettings)
    #: A switch for a future test-only path to HMRC's External Test Service. It cannot be turned on: the ETS needs
    #: SDST test credentials and software recognition this project does not have (docs/HONESTY.md).
    rti_test_submission_enabled: Literal[False] = False

    @field_validator("paye_reference", "accounts_office_ref")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    @property
    def references_complete(self) -> bool:
        return bool(self.paye_office and self.paye_reference and self.accounts_office_ref)


class BroughtForward(BaseModel):
    """This employment's year-to-date figures before Accnomos ran its payroll (moving from another payroll)."""

    taxable_pay_pence: int = 0
    tax_pence: int = 0
    ni_category: str = "A"
    ni_gross_pence: int = 0
    ni_at_lel_pence: int = 0
    ni_lel_to_pt_pence: int = 0
    ni_pt_to_uel_pence: int = 0
    ee_ni_pence: int = 0
    er_ni_pence: int = 0
    student_loan_pence: int = 0
    postgrad_loan_pence: int = 0
    ee_pension_net_pay_pence: int = 0
    ee_pension_other_pence: int = 0
    smp_pence: int = 0


class Employee(BaseModel):
    """The payroll record of one employee. Unlike the timesheet staff list (app/jobs.py: name and role only) this
    holds personal data HMRC requires on an FPS (NI number, date of birth, address, gender as HMRC records it). It
    lives only in the owner's own OneDrive, like the rest of the books."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    payroll_id: str = Field(min_length=1, max_length=35, pattern=r"^[^ ].*")  # never re-used, even after leaving
    staff_id: str | None = None  # the timesheet staff member, for hourly pay from timesheets
    title: str = Field(default="", max_length=35)
    forenames: str = Field(min_length=1, max_length=71)
    surname: str = Field(min_length=1, max_length=35)
    nino: str | None = Field(default=None, max_length=16)  # spaces allowed in, stored as 9 characters
    dob: date
    gender: Literal["M", "F"]  # as HMRC holds it (RTI data item 33)
    address: list[Annotated[str, Field(max_length=35)]] = Field(default_factory=list, max_length=4)
    postcode: str = Field(default="", max_length=10)
    email: str = Field(default="", max_length=100)
    start_date: date
    starter_declaration: Literal["A", "B", "C"] | None = None
    p45_previous_pay_pence: int | None = Field(default=None, ge=0)
    p45_previous_tax_pence: int | None = None
    tax_code: str = Field(default=R.EMERGENCY_CODE, max_length=10)
    week1_month1: bool = False
    ni_category: str = Field(default="A", pattern=r"^[A-Z]$")
    workplace_postcode: str = Field(default="", max_length=8)  # Freeport / Investment Zone letters only
    director: bool = False
    director_appointed_on: date | None = None
    student_loan_plan: Literal["1", "2", "4", "5"] | None = None
    postgrad_loan: bool = False
    frequency: Frequency = "monthly"
    pay_type: Literal["salary", "hourly"] = "salary"
    annual_salary_pence: int = Field(default=0, ge=0)
    hourly_rate_pence: int = Field(default=0, ge=0)
    usual_hours: float = Field(default=0, ge=0, le=744)  # per pay period, for hourly pay without timesheets
    #: Overtime rule for hourly pay from timesheets: hours over this many in a week (Monday to Sunday) are paid at
    #: `overtime_multiplier`. None: no automatic overtime (entries can still carry their own multiplier).
    overtime_after_hours_week: float | None = Field(default=None, gt=0, le=168)
    overtime_multiplier: float = Field(default=1.5, ge=1.0, le=3.0)
    hours_band: Literal["A", "B", "C", "D", "E"] = "D"  # RTI data item 54: normal weekly hours band
    pension_exempt: bool = False  # e.g. a director with no contract of employment (not a worker)
    enrolled_on: date | None = None
    opted_in_on: date | None = None
    opted_out_on: date | None = None
    leaving_date: date | None = None
    brought_forward: BroughtForward | None = None

    @field_validator("nino")
    @classmethod
    def _nino(cls, v: str | None) -> str | None:
        if not v or not v.strip():
            return None
        s = re.sub(r"\s", "", v).upper()
        if not NINO_RE.fullmatch(s):
            raise ValueError("That isn't a valid National Insurance number (two letters, six digits, A-D)")
        return s

    @field_validator("tax_code")
    @classmethod
    def _code(cls, v: str) -> str:
        code = P.parse_tax_code(v)
        return code.raw

    @field_validator("ni_category")
    @classmethod
    def _cat(cls, v: str) -> str:
        if v not in R.NI_CATEGORIES:
            raise ValueError(f"NI category {v} isn't supported (use {', '.join(R.NI_CATEGORIES)})")
        return v

    @model_validator(mode="after")
    def _rules(self) -> Employee:
        if self.ni_category in R.NI_REDUCED_RATE and (self.gender == "M" or self.dob > date(1961, 4, 5)):
            raise ValueError("NI letters B, E and I are only for women born on or before 5 April 1961")
        if self.ni_category in R.NI_NEEDS_WORKPLACE_POSTCODE and not self.workplace_postcode:
            raise ValueError(f"NI letter {self.ni_category} needs the Freeport or Investment Zone workplace postcode")
        if self.pay_type == "hourly" and not self.hourly_rate_pence:
            raise ValueError("Set an hourly rate for hourly pay")
        if not self.nino and len([a for a in self.address if a.strip()]) < 2:
            raise ValueError("Without an NI number HMRC needs at least two lines of address")
        return self

    @property
    def name(self) -> str:
        return f"{self.forenames} {self.surname}".strip()

    @property
    def code(self) -> P.TaxCode:
        return P.parse_tax_code(self.tax_code, self.week1_month1)


def suggested_starter_code(declaration: Literal["A", "B", "C"] | None) -> tuple[str, bool, str]:
    """(code, week1/month1, note) for a new employee without a P45. These are the long-standing HMRC rules; the
    2026-27 CWG2 no longer prints them (HMRC moved them to the online tool), so they are NOT verified here."""
    note = "Confirm with HMRC's new employee tax code tool: https://www.gov.uk/new-employee-tax-code"
    if declaration == "A":
        return R.EMERGENCY_CODE, False, note
    if declaration == "B":
        return R.EMERGENCY_CODE, True, note
    if declaration == "C":
        return "BR", False, note
    return "0T", True, note


async def load_employer(books: Books) -> EmployerSettings:
    return EmployerSettings.model_validate(await books.read_json(EMPLOYER, {}))


async def save_employer(books: Books, s: EmployerSettings, user: str) -> EmployerSettings:
    await books.write_json(EMPLOYER, s.model_dump(mode="json"))
    await books.audit(f"user:{user}", "payroll_employer_saved", {"references": s.references_complete})
    return s


async def load_employees(books: Books) -> list[Employee]:
    return [Employee.model_validate(e) for e in await books.read_json(EMPLOYEES, [])]


async def get_employee(books: Books, employee_id: str) -> Employee:
    for e in await load_employees(books):
        if e.id == employee_id:
            return e
    raise FileNotFoundError(f"No employee {employee_id}")


async def save_employee(books: Books, emp: Employee, user: str) -> Employee:
    every = await load_employees(books)
    others = [e for e in every if e.id != emp.id]
    if any(e.payroll_id == emp.payroll_id for e in others):
        raise PayrunError(f"Payroll ID {emp.payroll_id} is already used: HMRC needs a new one for each employment")
    await books.write_json(EMPLOYEES, [e.model_dump(mode="json") for e in [*others, emp]])
    await books.audit(f"user:{user}", "payroll_employee_saved", {"employee": emp.id})  # no personal data in the log
    return emp


async def delete_employee(books: Books, employee_id: str, user: str) -> None:
    for run in await list_runs(books):
        if any(ln.employee_id == employee_id for ln in run.lines):
            raise PayrunConflict("This employee has been paid: record a leaving date instead of deleting them")
    every = await load_employees(books)
    if not any(e.id == employee_id for e in every):
        raise FileNotFoundError(f"No employee {employee_id}")
    await books.write_json(EMPLOYEES, [e.model_dump(mode="json") for e in every if e.id != employee_id])
    await books.audit(f"user:{user}", "payroll_employee_deleted", {"employee": employee_id})


# --------------------------------------------------------------------------- #
# Pay run models
# --------------------------------------------------------------------------- #


class SickPay(BaseModel):
    model_config = {"extra": "forbid"}

    awe_pence: int = Field(ge=0, le=10_000_000)
    qualifying_days_per_week: int = Field(ge=1, le=7)
    days: int = Field(ge=0, le=31 * 7)


class MaternityPay(BaseModel):
    model_config = {"extra": "forbid"}

    awe_pence: int = Field(ge=0, le=10_000_000)
    first_week: int = Field(ge=1, le=39)
    weeks: int = Field(ge=0, le=39)

    @model_validator(mode="after")
    def _span(self) -> MaternityPay:
        if self.first_week + self.weeks - 1 > 39:
            raise ValueError("SMP is paid for at most 39 weeks")
        return self


class LineInputs(BaseModel):
    """What the user can change on a draft line. Everything else is calculated."""

    model_config = {"extra": "forbid"}

    employee_id: str = Field(max_length=32)
    basic_pence: Pence | None = None  # override the salary / hours x rate (a part period, unpaid leave...)
    hours: float | None = Field(default=None, ge=0, le=744)
    bonus_pence: Pence = 0  # bonus, overtime, commission: taxable and NI-able
    sick: SickPay | None = None
    maternity: MaternityPay | None = None
    deductions_after_tax_pence: Pence = 0  # e.g. a staff loan repayment, from net pay
    notes: str = Field(default="", max_length=300)


class NiYtd(BaseModel):
    gross_pence: int = 0
    at_lel_pence: int = 0
    lel_to_pt_pence: int = 0
    pt_to_uel_pence: int = 0
    ee_pence: int = 0
    er_pence: int = 0


class Ytd(BaseModel):
    """This employment's figures for the tax year, after the payment."""

    gross_pay_pence: int = 0
    taxable_pay_pence: int = 0
    tax_pence: int = 0
    ni: dict[str, NiYtd] = Field(default_factory=dict)
    student_loan_pence: int = 0
    postgrad_loan_pence: int = 0
    ee_pension_net_pay_pence: int = 0  # RTI 'EmpeePenContribnsPaidYTD'
    ee_pension_other_pence: int = 0  # RTI 'EmpeePenContribnsNotPaidYTD' (relief at source, as deducted)
    er_pension_pence: int = 0
    ssp_pence: int = 0
    smp_pence: int = 0
    net_pay_pence: int = 0

    @property
    def ee_ni_pence(self) -> int:
        return sum(v.ee_pence for v in self.ni.values())

    @property
    def er_ni_pence(self) -> int:
        return sum(v.er_pence for v in self.ni.values())

    @property
    def ni_gross_pence(self) -> int:
        return sum(v.gross_pence for v in self.ni.values())


class PensionLine(BaseModel):
    category: AE.Category
    age: int
    member: bool
    auto_enrolled_now: bool = False
    enrolled_on: date | None = None
    opt_out_ends: date | None = None
    basis: AE.Basis = "qualifying"
    arrangement: AE.Arrangement = "relief_at_source"
    band_low_pence: int = 0
    band_high_pence: int = 0
    pensionable_pence: int = 0  # earnings the contributions are worked out on
    employer_pence: int = 0
    employee_gross_pence: int = 0
    employee_deducted_pence: int = 0
    sacrifice_pence: int = 0
    relief_claimed_by_scheme_pence: int = 0
    notes: list[str] = Field(default_factory=list)

    @property
    def to_provider_pence(self) -> int:
        return self.employer_pence + self.employee_deducted_pence


class PayItem(BaseModel):
    """One line of pay on the payslip: basic hours, overtime at a multiplier, salary."""

    label: str
    hours: float | None = None
    rate_pence: int | None = None
    multiplier: float = 1.0
    pence: int
    entry_ids: list[str] = Field(default_factory=list)


HOLIDAY_PAY_NOTE = (
    "Regular overtime can count towards holiday pay (the 'normal remuneration' rules): Accnomos does not average "
    "holiday pay. Check with your adviser."
)


def _mult_label(m: float) -> str:
    return {1.5: "time and a half", 2.0: "double time", 3.0: "triple time"}.get(m, f"{m:g}x")


def timesheet_items(
    entries: list[Any], rate_pence: int, after_hours_week: float | None, ot_multiplier: float
) -> list[PayItem]:
    """Pay from timesheet entries (app/jobs.TimesheetEntry): hours x rate x the entry's multiplier. With a weekly rule,
    normal-rate hours beyond `after_hours_week` in a Monday-Sunday week (counting every hour worked that week in
    these entries, oldest first) are paid at `ot_multiplier`. Quarter hours; pence rounded half up per item."""
    from app.jobs import quarters

    buckets: dict[float, list[int]] = defaultdict(lambda: [0, 0])  # multiplier -> [quarters, unused]
    ids: dict[float, list[str]] = defaultdict(list)
    week_q: dict[tuple[int, int], int] = defaultdict(int)
    limit_q = None if after_hours_week is None else round(after_hours_week * 4)
    for e in sorted(entries, key=lambda x: (x.date, x.id)):
        q = quarters(e.hours)
        wk = tuple(e.date.isocalendar()[:2])
        m = float(e.rate_multiplier)
        if m == 1.0 and limit_q is not None:
            normal = max(0, min(q, limit_q - week_q[wk]))
            extra = q - normal
            if normal:
                buckets[1.0][0] += normal
                ids[1.0].append(e.id)
            if extra:
                buckets[float(ot_multiplier)][0] += extra
                ids[float(ot_multiplier)].append(e.id)
        else:
            buckets[m][0] += q
            ids[m].append(e.id)
        week_q[wk] += q
    items = []
    for m in sorted(buckets):
        q = buckets[m][0]
        if not q:
            continue
        pence = P.half_up(Fraction(q * rate_pence) * Fraction(m).limit_denominator(100) / 4)
        label = "Basic hours" if m == 1.0 else f"Overtime at {_mult_label(m)}"
        items.append(
            PayItem(label=label, hours=q / 4, rate_pence=rate_pence, multiplier=m, pence=pence, entry_ids=ids[m])
        )
    return items


class PayLine(BaseModel):
    employee_id: str
    payroll_id: str
    name: str
    inputs: LineInputs
    basic_pence: int
    bonus_pence: int
    overtime_pence: int = 0
    pay_items: list[PayItem] = Field(default_factory=list)
    ssp_pence: int
    smp_pence: int
    gross_pence: int  # before salary sacrifice
    salary_sacrifice_pence: int
    ni_earnings_pence: int  # gross for NI this period ('GrossEarningsForNICsInPd')
    ee_pension_net_pay_pence: int  # deducted before tax
    taxable_pay_pence: int
    tax_code: str  # as operated, e.g. "S1257L", "1257L W1/M1"
    tax_basis: str
    tax_pence: int
    tax_notes: list[str] = Field(default_factory=list)
    ni_category: str
    ee_ni_pence: int
    er_ni_pence: int
    ni_st_to_lel_pence: int = 0
    ni_lel_to_pt_pence: int = 0
    ni_pt_to_uel_pence: int = 0
    ni_above_uel_pence: int = 0
    ni_at_lel_pence: int = 0
    director: bool = False
    student_loan_plan: str | None = None
    student_loan_pence: int = 0
    postgrad_loan_pence: int = 0
    pension: PensionLine
    ee_pension_from_net_pence: int = 0  # relief at source, deducted after tax
    deductions_after_tax_pence: int = 0
    net_pay_pence: int = 0
    employment_allowance_pence: int = 0  # set at run level, shown per line for the payslip only when 0
    starter: bool = False
    leaver: bool = False
    payment_after_leaving: bool = False
    ytd: Ytd = Field(default_factory=Ytd)
    warnings: list[str] = Field(default_factory=list)

    @property
    def total_deductions_pence(self) -> int:
        return (
            self.tax_pence
            + self.ee_ni_pence
            + self.student_loan_pence
            + self.postgrad_loan_pence
            + self.ee_pension_net_pay_pence
            + self.ee_pension_from_net_pence
            + self.deductions_after_tax_pence
        )


class PayRun(BaseModel):
    id: str
    tax_year: str
    frequency: Frequency
    period: int  # tax week (weekly / 2- / 4-weekly: the last week of the period) or tax month
    period_start: date
    period_end: date
    pay_date: date
    status: Literal["draft", "proposed", "posted"] = "draft"
    lines: list[PayLine] = Field(default_factory=list)
    inputs: list[LineInputs] = Field(default_factory=list)
    proposal_id: str | None = None
    event_id: str | None = None
    employment_allowance_pence: int = 0  # set against employer NI in this run (up to £10,500 a year)
    warnings: list[str] = Field(default_factory=list)
    prepared_at: str | None = None
    label: str = ESTIMATE_NOTE

    @property
    def tax_month(self) -> int:
        return P.tax_month(self.pay_date)

    def total(self, field: str) -> int:
        return sum(int(getattr(ln, field)) for ln in self.lines)

    @property
    def hmrc_due_pence(self) -> int:
        """PAYE, employee and employer NI, student and postgraduate loans, less Employment Allowance."""
        return (
            self.total("tax_pence")
            + self.total("ee_ni_pence")
            + self.total("er_ni_pence")
            + self.total("student_loan_pence")
            + self.total("postgrad_loan_pence")
            - self.employment_allowance_pence
        )


def run_id(tax_year: str, freq: Frequency, period: int) -> str:
    return f"{tax_year}-{freq}-{period:02d}"


def period_dates(freq: Frequency, tax_year_first: date, period: int) -> tuple[date, date]:
    if freq == "monthly":
        return P.tax_month_bounds(tax_year_first, period)
    k = R.WEEKS_IN_PERIOD[freq]
    end = tax_year_first + timedelta(days=7 * period - 1)
    start = end - timedelta(days=7 * k - 1)
    last = date(tax_year_first.year + 1, 4, 5)
    return start, min(end, last)


# --------------------------------------------------------------------------- #
# The calculation for one employee (pure)
# --------------------------------------------------------------------------- #


def _ytd_before(emp: Employee, earlier: list[PayLine]) -> Ytd:
    y = Ytd()
    bf = emp.brought_forward
    if bf:
        y.taxable_pay_pence = y.gross_pay_pence = bf.taxable_pay_pence
        y.tax_pence = bf.tax_pence
        y.ni[bf.ni_category] = NiYtd(
            gross_pence=bf.ni_gross_pence,
            at_lel_pence=bf.ni_at_lel_pence,
            lel_to_pt_pence=bf.ni_lel_to_pt_pence,
            pt_to_uel_pence=bf.ni_pt_to_uel_pence,
            ee_pence=bf.ee_ni_pence,
            er_pence=bf.er_ni_pence,
        )
        y.student_loan_pence, y.postgrad_loan_pence = bf.student_loan_pence, bf.postgrad_loan_pence
        y.ee_pension_net_pay_pence, y.ee_pension_other_pence = bf.ee_pension_net_pay_pence, bf.ee_pension_other_pence
        y.smp_pence = bf.smp_pence
    if earlier:
        return earlier[-1].ytd.model_copy(deep=True)
    return y


def _add_ytd(before: Ytd, ln: PayLine) -> Ytd:
    y = before.model_copy(deep=True)
    y.gross_pay_pence += ln.ni_earnings_pence
    y.taxable_pay_pence += ln.taxable_pay_pence
    y.tax_pence += ln.tax_pence
    n = y.ni.setdefault(ln.ni_category, NiYtd())
    n.gross_pence += ln.ni_earnings_pence
    n.at_lel_pence += ln.ni_at_lel_pence
    n.lel_to_pt_pence += ln.ni_lel_to_pt_pence
    n.pt_to_uel_pence += ln.ni_pt_to_uel_pence
    n.ee_pence += ln.ee_ni_pence
    n.er_pence += ln.er_ni_pence
    y.student_loan_pence += ln.student_loan_pence
    y.postgrad_loan_pence += ln.postgrad_loan_pence
    y.ee_pension_net_pay_pence += ln.ee_pension_net_pay_pence
    y.ee_pension_other_pence += ln.ee_pension_from_net_pence
    y.er_pension_pence += ln.pension.employer_pence
    y.ssp_pence += ln.ssp_pence
    y.smp_pence += ln.smp_pence
    y.net_pay_pence += ln.net_pay_pence
    return y


def _director_week(emp: Employee, tax_year_first: date) -> int | None:
    d = emp.director_appointed_on
    if not emp.director or d is None or d <= tax_year_first:
        return None
    return P.tax_week(d)


def calculate_line(
    emp: Employee,
    inputs: LineInputs,
    run: PayRun,
    scheme: PensionSettings,
    earlier: list[PayLine],
    tax_year_first: date,
    timesheet: list[Any] | None = None,
) -> PayLine:
    """Every figure for one employee in one pay run. `earlier` are this employee's posted lines in the tax year so
    far, oldest first (their YTD carries forward). `timesheet`: their timesheet entries dated in the pay period
    (hourly pay is worked out from them when there are any and no hours were typed in)."""
    freq, pay_date = run.frequency, run.pay_date
    if emp.frequency != freq:
        raise PayrunError(f"{emp.name} is paid {emp.frequency.replace('_', '-')}, not {freq.replace('_', '-')}")
    warnings: list[str] = []
    before = _ytd_before(emp, earlier)

    # Pay
    items: list[PayItem] = []
    overtime = 0
    if inputs.basic_pence is not None:
        basic = inputs.basic_pence
        items = [PayItem(label="Basic pay (typed in)", pence=basic)]
    elif emp.pay_type == "salary":
        basic = P.half_up(Fraction(emp.annual_salary_pence, R.PERIODS_IN_YEAR[freq]))
        items = [PayItem(label="Salary", pence=basic)]
    elif inputs.hours is None and timesheet:
        items = timesheet_items(
            timesheet, emp.hourly_rate_pence, emp.overtime_after_hours_week, emp.overtime_multiplier
        )
        basic = sum(i.pence for i in items if i.multiplier == 1.0)
        overtime = sum(i.pence for i in items if i.multiplier != 1.0)
        if overtime:
            warnings.append(HOLIDAY_PAY_NOTE)
    else:
        hours = emp.usual_hours if inputs.hours is None else inputs.hours
        basic = P.half_up(Fraction(round(hours * 4)) * emp.hourly_rate_pence / 4)
        items = [PayItem(label="Hours", hours=round(hours * 4) / 4, rate_pence=emp.hourly_rate_pence, pence=basic)]
    ssp = (
        P.ssp_amount(inputs.sick.awe_pence, inputs.sick.qualifying_days_per_week, inputs.sick.days)
        if inputs.sick
        else 0
    )
    smp = (
        P.smp_amount(inputs.maternity.awe_pence, inputs.maternity.first_week, inputs.maternity.weeks)
        if inputs.maternity
        else 0
    )
    gross = basic + overtime + inputs.bonus_pence + ssp + smp
    leaver = emp.leaving_date is not None and run.period_start <= emp.leaving_date <= run.period_end
    after_leaving = emp.leaving_date is not None and pay_date > emp.leaving_date and not leaver
    starter = not earlier and emp.brought_forward is None and emp.start_date >= tax_year_first

    # Pension: assess on this period's earnings, then work out contributions.
    a = AE.assess(emp.dob, pay_date, gross, freq)
    duties = scheme.duties_start is None or pay_date >= scheme.duties_start
    enrolled_on = emp.enrolled_on
    auto_now = False
    pnotes = list(a.notes)
    if (
        not emp.pension_exempt
        and a.category == "eligible_jobholder"
        and enrolled_on is None
        and emp.opted_out_on is None
        and duties
    ):
        enrolled_on, auto_now = pay_date, True
        pnotes.append(
            "Enrolled automatically this period: send the enrolment information within 6 weeks; "
            f"they can opt out until {AE.opt_out_ends(pay_date):%d %b %Y}"
        )
    if emp.opted_in_on and enrolled_on is None and a.category != "not_a_worker":
        enrolled_on = emp.opted_in_on
    member = (
        not emp.pension_exempt
        and enrolled_on is not None
        and enrolled_on <= pay_date
        and (emp.opted_out_on is None or emp.opted_out_on > pay_date)
        and not after_leaving
    )
    if emp.opted_out_on and enrolled_on and emp.opted_out_on <= AE.opt_out_ends(enrolled_on):
        pnotes.append(
            "Opted out within the one-month window: refund the employee's contributions (through the provider "
            "or payroll; not calculated here)"
        )
    if a.category == "entitled_worker" and member:
        pnotes.append("Entitled worker: the employer doesn't have to contribute, but this scheme's rates are applied")
    c = AE.contributions(scheme.scheme(), freq, gross) if member else AE.NO_CONTRIBUTION
    pnotes.extend(c.warnings)
    pension = PensionLine(
        category=a.category,
        age=a.age,
        member=member,
        auto_enrolled_now=auto_now,
        enrolled_on=enrolled_on,
        opt_out_ends=AE.opt_out_ends(enrolled_on) if enrolled_on else None,
        basis=scheme.basis,
        arrangement=scheme.arrangement,
        band_low_pence=c.band_low_pence if member else R.AE_THRESHOLDS[freq].lower_qe,
        band_high_pence=c.band_high_pence if member else R.AE_THRESHOLDS[freq].upper_qe,
        pensionable_pence=c.base_pence,
        employer_pence=c.employer_pence,
        employee_gross_pence=c.employee_gross_pence,
        employee_deducted_pence=c.employee_deducted_pence,
        sacrifice_pence=c.sacrifice_pence,
        relief_claimed_by_scheme_pence=c.relief_claimed_by_scheme_pence,
        notes=pnotes,
    )
    sacrifice = c.sacrifice_pence if member else 0
    ni_earn = gross - sacrifice
    net_pay_pension = c.employee_deducted_pence if member and scheme.arrangement == "net_pay" else 0
    ras = c.employee_deducted_pence if member and scheme.arrangement == "relief_at_source" else 0
    taxable = ni_earn - net_pay_pension

    # Tax
    code = P.parse_tax_code("0T", True) if after_leaving else emp.code
    if after_leaving:
        warnings.append("Payment after leaving: taxed on 0T week 1 / month 1 (CWG2 1.14)")
    use_p45 = (not code.non_cumulative) and emp.p45_previous_pay_pence is not None and not after_leaving
    prev_pay = (emp.p45_previous_pay_pence or 0) if use_p45 else 0
    prev_tax = (emp.p45_previous_tax_pence or 0) if use_p45 else 0
    tax = P.income_tax(
        code,
        freq,
        run.period,
        taxable,
        pay_to_date_before_pence=prev_pay + before.taxable_pay_pence,
        tax_to_date_before_pence=prev_tax + before.tax_pence,
    )

    # NI
    if emp.director:
        prior = before.ni.get(emp.ni_category, NiYtd())
        others = sum(v.gross_pence for k, v in before.ni.items() if k != emp.ni_category)
        if others:
            warnings.append("Director whose NI letter changed this year: check the director's NI with your provider")
        d = P.ni_director(
            prior.gross_pence + ni_earn,
            emp.ni_category,
            _director_week(emp, tax_year_first),
            prior.ee_pence,
            prior.er_pence,
        )
        ni_ee, ni_er = d.employee_pence, d.employer_pence
        bands = (
            d.to_date.st_to_lel,
            d.to_date.lel_to_pt - prior.lel_to_pt_pence,
            d.to_date.pt_to_uel - prior.pt_to_uel_pence,
            d.to_date.above_uel,
            d.to_date.at_lel - prior.at_lel_pence,
        )
        if emp.student_loan_plan or emp.postgrad_loan:
            warnings.append("Director with a student loan: worked out per period here; check the annual basis")
    else:
        n = P.ni_period(ni_earn, emp.ni_category, freq)
        ni_ee, ni_er = n.employee_pence, n.employer_pence
        bands = (n.st_to_lel, n.lel_to_pt, n.pt_to_uel, n.above_uel, n.at_lel)

    # Loans
    sl = P.student_loan(ni_earn, emp.student_loan_plan, freq)
    pgl = P.postgrad_loan(ni_earn, emp.postgrad_loan, freq)
    net = ni_earn - net_pay_pension - tax.tax_pence - ni_ee - sl - pgl - ras - inputs.deductions_after_tax_pence
    if net < 0:
        warnings.append("Net pay is negative: reduce the deductions after tax")
    if not emp.nino:
        warnings.append("No NI number: HMRC will trace them from the address; ask them for it")
    if leaver:
        warnings.append(f"Leaver on {emp.leaving_date:%d/%m/%Y}: give them a P45 (figures on the P45 report)")

    line = PayLine(
        employee_id=emp.id,
        payroll_id=emp.payroll_id,
        name=emp.name,
        inputs=inputs,
        basic_pence=basic,
        bonus_pence=inputs.bonus_pence,
        overtime_pence=overtime,
        pay_items=items,
        ssp_pence=ssp,
        smp_pence=smp,
        gross_pence=gross,
        salary_sacrifice_pence=sacrifice,
        ni_earnings_pence=ni_earn,
        ee_pension_net_pay_pence=net_pay_pension,
        taxable_pay_pence=taxable,
        tax_code=code.display(),
        tax_basis=tax.basis,
        tax_pence=tax.tax_pence,
        tax_notes=list(tax.notes),
        ni_category=emp.ni_category,
        ee_ni_pence=ni_ee,
        er_ni_pence=ni_er,
        ni_st_to_lel_pence=bands[0],
        ni_lel_to_pt_pence=bands[1],
        ni_pt_to_uel_pence=bands[2],
        ni_above_uel_pence=bands[3],
        ni_at_lel_pence=bands[4],
        director=emp.director,
        student_loan_plan=emp.student_loan_plan,
        student_loan_pence=sl,
        postgrad_loan_pence=pgl,
        pension=pension,
        ee_pension_from_net_pence=ras,
        deductions_after_tax_pence=inputs.deductions_after_tax_pence,
        net_pay_pence=net,
        starter=starter,
        leaver=leaver,
        payment_after_leaving=after_leaving,
        warnings=warnings,
    )
    line.ytd = _add_ytd(before, line)
    return line


def employment_allowance(settings: EmployerSettings, er_ni_pence: int, used_before_pence: int) -> int:
    """How much Employment Allowance to set against this run's employer NI: all of it until the £10,500 is used."""
    if not settings.claim_employment_allowance:
        return 0
    return max(0, min(er_ni_pence, R.EMPLOYMENT_ALLOWANCE_PENCE - used_before_pence))


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #


def _path(rid: str) -> str:
    if not RUN_ID_RE.fullmatch(rid):
        raise PayrunError(f"{rid!r} is not a pay run id like 2026-27-monthly-07")
    return f"{RUNS}/{rid}.json"


async def list_runs(books: Books) -> list[PayRun]:
    out = []
    for f in await books.list_files(RUNS):
        if f.name.endswith(".json") and RUN_ID_RE.fullmatch(f.name.removesuffix(".json")):
            out.append(PayRun.model_validate(await books.read_json(f.path, {})))
    return sorted(out, key=lambda r: (r.pay_date, r.id))


async def load_run(books: Books, rid: str) -> PayRun | None:
    raw = await books.read_json(_path(rid), None)
    return None if raw is None else PayRun.model_validate(raw)


async def get_run(books: Books, rid: str) -> PayRun:
    run = await load_run(books, rid)
    if run is None:
        raise FileNotFoundError(f"No pay run {rid}")
    return run


async def _save(books: Books, run: PayRun) -> PayRun:
    await books.write_json(_path(run.id), run.model_dump(mode="json"))
    return run


# --------------------------------------------------------------------------- #
# Prepare and edit
# --------------------------------------------------------------------------- #


async def _timesheets_in(books: Books, run: PayRun) -> dict[str, list[Any]]:
    """Timesheet entries dated in the run's pay period, by staff id (app/jobs.py)."""
    from app.jobs import load_entries

    months = sorted({f"{run.period_start:%Y-%m}", f"{run.period_end:%Y-%m}"})
    out: dict[str, list[Any]] = defaultdict(list)
    for m in months:
        for e in await load_entries(books, m):
            if run.period_start <= e.date <= run.period_end:
                out[e.staff_id].append(e)
    return out


async def _calculate(books: Books, run: PayRun, inputs: list[LineInputs]) -> PayRun:
    settings = await load_employer(books)
    employees = {e.id: e for e in await load_employees(books)}
    first = P.tax_year_start(run.pay_date)
    others = [r for r in await list_runs(books) if r.tax_year == run.tax_year and r.id != run.id]
    blocking = [r for r in others if r.pay_date <= run.pay_date and r.status != "posted"]
    if blocking:
        raise PayrunConflict(
            f"Approve (or discard) the earlier pay run {blocking[0].id} first: year-to-date figures build on it"
        )
    later = [r for r in others if r.pay_date > run.pay_date and r.status != "draft"]
    if later:
        raise PayrunConflict(f"A later pay run ({later[0].id}) is already sent to Review or posted")
    posted = [r for r in others if r.status == "posted" and r.pay_date <= run.pay_date]
    by_emp: dict[str, list[PayLine]] = defaultdict(list)
    for r in posted:
        for ln in r.lines:
            by_emp[ln.employee_id].append(ln)
    sheets = await _timesheets_in(books, run)
    lines: list[PayLine] = []
    seen: set[str] = set()
    for inp in inputs:
        emp = employees.get(inp.employee_id)
        if emp is None:
            raise PayrunError(f"No employee {inp.employee_id}")
        if emp.id in seen:
            raise PayrunError("Each employee can be on a pay run once")
        seen.add(emp.id)
        try:
            sheet = sheets.get(emp.staff_id or "", []) if emp.pay_type == "hourly" else []
            lines.append(calculate_line(emp, inp, run, settings.pension, by_emp[emp.id], first, sheet))
        except P.PayeError as exc:
            raise PayrunError(f"{emp.name}: {exc}") from exc
    lines.sort(key=lambda ln: (ln.name.lower(), ln.payroll_id))
    used = sum(r.employment_allowance_pence for r in posted)
    er = sum(ln.er_ni_pence for ln in lines)
    warnings: list[str] = []
    if not settings.references_complete:
        warnings.append("Add your PAYE reference and Accounts Office reference (Payroll settings) for the FPS file")
    if not lines:
        warnings.append("No employees on this pay run")
    if (
        settings.claim_employment_allowance
        and sum(1 for e in employees.values() if not e.leaving_date) == 1
        and any(e.director for e in employees.values())
    ):
        warnings.append(
            "Employment Allowance can't be claimed when a sole director is the only employee paid above the "
            "secondary threshold: check you're eligible (gov.uk/claim-employment-allowance/eligibility)"
        )
    return run.model_copy(
        update={
            "lines": lines,
            "inputs": inputs,
            "employment_allowance_pence": employment_allowance(settings, er, used),
            "warnings": warnings,
            "prepared_at": now().isoformat(),
        }
    )


def default_inputs(employees: list[Employee], run: PayRun) -> list[LineInputs]:
    out = []
    for e in employees:
        if e.frequency != run.frequency or e.start_date > run.period_end:
            continue
        if e.leaving_date and e.leaving_date < run.period_start:
            continue
        out.append(LineInputs(employee_id=e.id))
    return out


async def prepare(books: Books, freq: Frequency, pay_date: date, user: str) -> PayRun:
    """A draft for every employee paid at `freq` and employed in the period. Replaces a draft of the same period."""
    if freq not in R.FREQUENCIES:
        raise PayrunError(f"Unknown pay frequency {freq}")
    ty = P.tax_year_label(pay_date)
    if ty != R.TAX_YEAR:
        raise PayrunError(f"Rates are only loaded for tax year {R.TAX_YEAR}; {pay_date:%d/%m/%Y} is in {ty}")
    period = P.period_number(freq, pay_date)
    first = P.tax_year_start(pay_date)
    start, end = period_dates(freq, first, period)
    rid = run_id(ty, freq, period)
    old = await load_run(books, rid)
    if old is not None and old.status != "draft":
        raise PayrunConflict(f"The {rid} pay run is {old.status}; take it back to draft to change it")
    run = PayRun(
        id=rid, tax_year=ty, frequency=freq, period=period, period_start=start, period_end=end, pay_date=pay_date
    )
    employees = await load_employees(books)
    run = await _calculate(books, run, default_inputs(employees, run))
    await _save(books, run)
    await books.audit(f"user:{user}", "payrun_prepared", {"run": rid, "lines": len(run.lines)})
    return run


async def update(books: Books, rid: str, inputs: list[LineInputs], user: str, pay_date: date | None = None) -> PayRun:
    run = await get_run(books, rid)
    if run.status != "draft":
        raise PayrunConflict(f"The {rid} pay run is {run.status}; take it back to draft to change it")
    if pay_date and pay_date != run.pay_date:
        if P.period_number(run.frequency, pay_date) != run.period or P.tax_year_label(pay_date) != run.tax_year:
            raise PayrunError("That pay date is in a different tax period: prepare a run for that period instead")
        run = run.model_copy(update={"pay_date": pay_date})
    run = await _calculate(books, run, inputs)
    await _save(books, run)
    await books.audit(f"user:{user}", "payrun_edited", {"run": rid, "lines": len(run.lines)})
    return run


async def discard_run(books: Books, rid: str, user: str) -> str:
    """Set a draft aside (nothing is deleted from the books): moved to payruns/discarded/."""
    run = await get_run(books, rid)
    if run.status != "draft":
        raise PayrunConflict("Only a draft pay run can be discarded")
    await books.storage.ensure_folder(f"{RUNS}/discarded")
    dest = f"{RUNS}/discarded/{rid}-{now():%Y%m%dT%H%M%S}.json"
    await books.storage.move(_path(rid), dest)
    await books.audit(f"user:{user}", "payrun_discarded", {"run": rid, "path": dest})
    return dest


# --------------------------------------------------------------------------- #
# The journal and the proposal
# --------------------------------------------------------------------------- #


def journal(run: PayRun) -> list[JournalLine]:
    """The balanced journal the run posts (see the module docstring). Lines with nothing in them are left out."""
    gross = run.total("ni_earnings_pence")
    er_ni = run.total("er_ni_pence")
    er_pen = sum(ln.pension.employer_pence for ln in run.lines)
    hmrc = run.hmrc_due_pence
    pension = sum(ln.pension.to_provider_pence for ln in run.lines)
    net = run.total("net_pay_pence")
    other = run.total("deductions_after_tax_pence")
    ea = run.employment_allowance_pence
    out = [
        JournalLine(account=WAGES, debit_pence=gross),
        JournalLine(account=EMPLOYER_NI, debit_pence=er_ni - ea),
        JournalLine(account=EMPLOYER_PENSION, debit_pence=er_pen),
        JournalLine(account=HMRC_LIABILITY, credit_pence=hmrc),
        JournalLine(account=PENSION_LIABILITY, credit_pence=pension),
        JournalLine(account=NET_WAGES, credit_pence=net),
        JournalLine(account=OTHER_DEDUCTIONS, credit_pence=other),
    ]
    fixed = []
    for j in out:  # a negative figure (a refund of tax, say) goes on the other side
        if j.debit_pence < 0:
            j = JournalLine(account=j.account, credit_pence=-j.debit_pence)
        if j.credit_pence < 0:
            j = JournalLine(account=j.account, debit_pence=-j.credit_pence)
        if j.debit_pence or j.credit_pence:
            fixed.append(j)
    debits, credits = sum(j.debit_pence for j in fixed), sum(j.credit_pence for j in fixed)
    if debits != credits:  # cannot happen: net = gross - every deduction; checked so a slip never posts
        raise PayrunError(f"Pay run journal does not balance ({debits} vs {credits}); nothing was posted")
    return fixed


def proposal_id_for(run: PayRun, attempt: int) -> str:
    return hashlib.sha256(f"payrun:{run.id}:{attempt}".encode()).hexdigest()[:32]


async def propose(books: Books, rid: str, user: str) -> tuple[PayRun, Proposal]:
    """Send the draft to Review as a proposal carrying its journal. Nothing posts until the user approves it."""
    from app.checks import decide

    run = await get_run(books, rid)
    if run.status != "draft":
        raise PayrunConflict(f"The {rid} pay run is already {run.status}")
    run = await _calculate(books, run, run.inputs)  # employees may have changed since it was prepared
    if not run.lines:
        raise PayrunError("There's nobody on this pay run")
    j = journal(run)
    gross = run.total("ni_earnings_pence")
    attempts = len([p for p in await books.list_proposals() if p.payroll_run == rid])
    pid = proposal_id_for(run, attempts)
    doc = ExtractedDoc(
        doc_type="purchase_invoice",
        supplier_name=f"Payroll {run.id}",
        supplier_vat_number=None,
        customer_name=None,
        invoice_number=run.id,
        date=run.pay_date.isoformat(),
        currency="GBP",
        lines=[
            ExtractedLine(
                description=f"{ln.name}: gross pay",
                qty=1,
                unit_price=ln.ni_earnings_pence / 100,
                net=ln.ni_earnings_pence / 100,
                vat_rate=None,
                vat=0,
            )
            for ln in run.lines
        ],  # fmt: skip
        net_total=gross / 100,
        vat_total=0,
        gross_total=gross / 100,
        payment_method=None,
        card_last4=None,
        category_guess="Sundry",
        confidence=1,
    )
    checks = [
        Check(
            code="PAYROLL",
            ok=True,
            severity="warn",
            message=(
                f"Calculated by code: {len(run.lines)} employee(s), pay date {run.pay_date:%d/%m/%Y}, "
                f"{R.TAX_YEAR} rates verified {R.VERIFIED_ON}. {ESTIMATE_NOTE}. {FILING_NOTE}"
            ),
        )
    ]
    if any(ln.net_pay_pence < 0 for ln in run.lines):
        checks.append(
            Check(code="NEGATIVE_NET", ok=False, severity="fail", message="An employee's net pay is negative")
        )
    status, reasons = decide(checks)
    p = Proposal(
        id=pid,
        doc_sha256=hashlib.sha256(run.model_dump_json().encode()).hexdigest(),
        extracted=doc,
        checks=checks,
        status=status,
        reasons=reasons,
        suggested_filename=f"Payroll {run.id}",
        journal_draft=j,
        model="code:payroll",
        elapsed_s=0,
        payroll_run=run.id,
        created_at=now(),
    )
    await books.save_proposal(p)
    run = run.model_copy(update={"status": "proposed", "proposal_id": pid})
    await _save(books, run)
    await books.audit(f"user:{user}", "payrun_proposed", {"run": rid, "proposal": pid})
    return run, p


async def back_to_draft(books: Books, rid: str, user: str) -> PayRun:
    """A proposed run back to draft: its proposal is rejected (a posted run is undone from Review first)."""
    from app.approve import reject

    run = await get_run(books, rid)
    if run.status == "posted":
        raise PayrunConflict("This pay run is posted: undo its entry in Review (or the ledger) first")
    if run.status == "draft":
        return run
    if run.proposal_id:
        try:
            p = await books.get_proposal(run.proposal_id)
            if p.status in ("proposed", "needs_a_look"):
                await reject(books, p.id, user, "Pay run taken back to draft")
        except FileNotFoundError:
            pass
    run = run.model_copy(update={"status": "draft", "proposal_id": None})
    await _save(books, run)
    await books.audit(f"user:{user}", "payrun_back_to_draft", {"run": rid})
    return run


async def on_posted(books: Books, p: Proposal, event_id: str, user: str) -> None:
    """Called by app.approve once a payroll proposal is posted: the run becomes posted and anyone enrolled
    automatically in it is recorded as enrolled."""
    if not p.payroll_run:
        return
    run = await load_run(books, p.payroll_run)
    if run is None or run.proposal_id != p.id:
        log.warning("Posted payroll proposal %s has no matching pay run", p.id)
        return
    run = run.model_copy(update={"status": "posted", "event_id": event_id})
    await _save(books, run)
    every = await load_employees(books)
    enrolled = {ln.employee_id: ln.pension.enrolled_on for ln in run.lines if ln.pension.auto_enrolled_now}
    if enrolled:
        updated = [
            e.model_copy(update={"enrolled_on": enrolled[e.id]}) if e.id in enrolled and not e.enrolled_on else e
            for e in every
        ]
        await books.write_json(EMPLOYEES, [e.model_dump(mode="json") for e in updated])
    await books.audit(f"user:{user}", "payrun_posted", {"run": run.id, "event": event_id})


async def on_undone(books: Books, p: Proposal) -> None:
    """Called by app.approve after the run's journal is undone: the run is proposed again (in Review)."""
    if not p.payroll_run:
        return
    run = await load_run(books, p.payroll_run)
    if run is None or run.proposal_id != p.id:
        return
    later = [r for r in await list_runs(books) if r.tax_year == run.tax_year and r.pay_date > run.pay_date]
    if any(r.status == "posted" for r in later):
        log.warning("Pay run %s undone while a later run is posted; year-to-date figures need checking", run.id)
    await _save(books, run.model_copy(update={"status": "proposed", "event_id": None}))


async def on_rejected(books: Books, p: Proposal) -> None:
    """Rejected in Review: the run goes back to draft."""
    if not p.payroll_run:
        return
    run = await load_run(books, p.payroll_run)
    if run is None or run.proposal_id != p.id or run.status != "proposed":
        return
    await _save(books, run.model_copy(update={"status": "draft", "proposal_id": None}))


def as_dict(run: PayRun) -> dict[str, Any]:
    d = run.model_dump(mode="json")
    d["hmrc_due_pence"] = run.hmrc_due_pence
    d["journal"] = [j.model_dump() for j in journal(run)] if run.lines else []
    return d
