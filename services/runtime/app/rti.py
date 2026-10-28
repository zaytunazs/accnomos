"""RTI files and year-end figures: FPS and EPS XML (2026-27 schemas), P45 and P60 figures, and the employer payment
record (what to pay HMRC by the 22nd). Pure code over posted pay runs (app/payrun.py).

PAYE RTI is not on HMRC's REST Developer Hub. It is sent as GovTalk XML to HMRC's Transaction Engine under the
Document Submission Protocol, with an IRmark, and live filing needs HMRC-recognised software ("How to use the
Internet services: RTI", v1.94, https://assets.publishing.service.gov.uk/media/69b1a6ad24c6431b84f0e50e/RTI-howtouse-v1-94.odt).
Accnomos is not recognised and has no SDST test credentials, so it never submits: these functions build the
<IRenvelope> body that HMRC's 2026-27 schemas define ("RTI RIM 2027 v1.0", FullPaymentSubmission-2027-v1-0.xsd and
EmployerPaymentSummary-2027-v1-0.xsd, namespaces .../FullPaymentSubmission/26-27/1 and
.../EmployerPaymentSummary/26-27/1, from
https://www.gov.uk/government/publications/real-time-information-internet-submissions-2026-to-2027-technical-specifications)
for the user to check against what their payroll provider or HMRC's Basic PAYE Tools files. There is no GovTalk
envelope and no IRmark (both belong to a submission). Tests validate the output against the published XSDs.

Data items follow "RTI data item guide 2026 to 2027 v1.0".
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from app import paye as P
from app import paye_rates as R
from app.payrun import FILING_NOTE, Employee, EmployerSettings, PayLine, PayRun

FPS_NS = "http://www.govtalk.gov.uk/taxation/PAYE/RTI/FullPaymentSubmission/26-27/1"
EPS_NS = "http://www.govtalk.gov.uk/taxation/PAYE/RTI/EmployerPaymentSummary/26-27/1"
SCHEMA_SOURCE = (
    "RTI RIM 2027 v1.0 (HMRC, 2026-27), schemas FullPaymentSubmission-2027-v1-0 / EmployerPaymentSummary-2027-v1-0"
)


class RtiError(ValueError):
    """The file cannot be built from what is held (a missing reference, an unposted run...)."""


def money(pence: int) -> str:
    sign = "-" if pence < 0 else ""
    return f"{sign}{abs(pence) // 100}.{abs(pence) % 100:02d}"


def _charset(s: str, allowed: str, fallback: str = "") -> str:
    out = re.sub(f"[^{allowed}]", "", s.replace("’", "'"))
    return out.strip() or fallback


def _names(emp: Employee) -> tuple[list[str], str]:
    fores = [_charset(f, "A-Za-z \\-'") for f in emp.forenames.split()][:2]
    fores = [f for f in fores if f and f[0].isalpha()]
    return fores, _charset(emp.surname, "A-Za-z \\-'", "Unknown")[:35]


def _sub(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    el = ET.SubElement(parent, tag, attrs)
    if text is not None:
        el.text = text
    return el


def _header(root: ET.Element, settings: EmployerSettings, period_end: date) -> None:
    h = _sub(root, "IRheader")
    keys = _sub(h, "Keys")
    _sub(keys, "Key", settings.paye_office, Type="TaxOfficeNumber")
    _sub(keys, "Key", settings.paye_reference, Type="TaxOfficeReference")
    _sub(h, "PeriodEnd", period_end.isoformat())
    _sub(h, "DefaultCurrency", "GBP")
    _sub(h, "Sender", "Employer")


def _emprefs(parent: ET.Element, s: EmployerSettings, sa_utr: bool = True) -> None:
    refs = _sub(parent, "EmpRefs")
    _sub(refs, "OfficeNo", s.paye_office)
    _sub(refs, "PayeRef", s.paye_reference)
    _sub(refs, "AORef", s.accounts_office_ref)
    if s.cotax_ref:
        _sub(refs, "COTAXRef", s.cotax_ref)


def _check_refs(s: EmployerSettings) -> None:
    if not s.references_complete:
        raise RtiError("Add your HMRC office number, PAYE reference and Accounts Office reference in Payroll settings")


def _serialise(root: ET.Element) -> bytes:
    ET.indent(root)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")


# --------------------------------------------------------------------------- #
# FPS
# --------------------------------------------------------------------------- #


def _employee(parent: ET.Element, emp: Employee, ln: PayLine, run: PayRun, tax_year_first: date) -> None:
    e = _sub(parent, "Employee")
    d = _sub(e, "EmployeeDetails")
    if emp.nino:
        _sub(d, "NINO", emp.nino)
    name = _sub(d, "Name")
    if emp.title:
        _sub(name, "Ttl", _charset(emp.title, "A-Za-z\\- .'")[:35])
    fores, sur = _names(emp)
    for f in fores:
        _sub(name, "Fore", f[:35])
    if not fores:
        _sub(name, "Initials", (emp.forenames[:1] or "X").upper())
    _sub(name, "Sur", sur)
    lines = [_charset(a, "A-Za-z0-9 .,\\-()/=!\"%&*;<>'+:?")[:35] for a in emp.address if a.strip()]
    lines = [a for a in lines if a and a[0].isalnum()][:4]
    postcode = _charset(emp.postcode.upper(), "A-Za-z0-9 ")[:10]
    if lines or postcode:
        addr = _sub(d, "Address")
        for a in lines:
            _sub(addr, "Line", a)
        if postcode:
            _sub(addr, "UKPostcode", postcode)
    _sub(d, "BirthDate", emp.dob.isoformat())
    _sub(d, "Gender", emp.gender)

    em = _sub(e, "Employment")
    if emp.director:
        _sub(em, "DirectorsNIC", "AN")
        if emp.director_appointed_on and emp.director_appointed_on > tax_year_first:
            _sub(em, "TaxWkOfApptOfDirector", str(P.tax_week(emp.director_appointed_on)))
    if ln.starter and emp.start_date >= tax_year_first:
        st = _sub(em, "Starter")
        _sub(st, "StartDate", emp.start_date.isoformat())
        if not emp.starter_declaration:
            raise RtiError(f"{emp.name} is a new starter: record their starter declaration (A, B or C)")
        _sub(st, "StartDec", emp.starter_declaration)
        if emp.student_loan_plan:
            _sub(st, "StudentLoan", "yes")
        if emp.postgrad_loan:
            _sub(st, "PostgradLoan", "yes")
    if emp.ni_category in R.NI_NEEDS_WORKPLACE_POSTCODE and emp.workplace_postcode:
        _sub(em, "EmployeeWorkplacePostcode", emp.workplace_postcode.upper())
    _sub(em, "PayId", _charset(emp.payroll_id, "A-Za-z0-9 .,\\-()/=!\"%&*;<>'+:?")[:35] or emp.id)
    if emp.leaving_date and (ln.leaver or ln.payment_after_leaving):
        _sub(em, "LeavingDate", emp.leaving_date.isoformat())
    y = ln.ytd
    ftd = _sub(em, "FiguresToDate")
    _sub(ftd, "TaxablePay", money(max(0, y.taxable_pay_pence)))
    _sub(ftd, "TotalTax", money(y.tax_pence))
    if emp.student_loan_plan or y.student_loan_pence:
        _sub(ftd, "StudentLoansTD", money(y.student_loan_pence))
    if emp.postgrad_loan or y.postgrad_loan_pence:
        _sub(ftd, "PostgradLoansTD", money(y.postgrad_loan_pence))
    if y.ee_pension_net_pay_pence:
        _sub(ftd, "EmpeePenContribnsPaidYTD", money(y.ee_pension_net_pay_pence))
    if y.ee_pension_other_pence:
        _sub(ftd, "EmpeePenContribnsNotPaidYTD", money(y.ee_pension_other_pence))

    pay = _sub(em, "Payment")
    _sub(pay, "PayFreq", R.RTI_PAY_FREQ[run.frequency])
    _sub(pay, "PmtDate", run.pay_date.isoformat())
    if run.frequency == "monthly":
        _sub(pay, "MonthNo", str(run.period))
    else:
        _sub(pay, "WeekNo", str(run.period))
    _sub(pay, "PeriodsCovered", "1")
    if ln.payment_after_leaving:
        _sub(pay, "PmtAfterLeaving", "yes")
    _sub(pay, "HoursWorked", emp.hours_band)
    code = P.parse_tax_code("0T", True) if ln.payment_after_leaving else emp.code
    attrs: dict[str, str] = {}
    if code.non_cumulative or ln.tax_basis != "cumulative":
        attrs["BasisNonCumulative"] = "yes"
    if code.prefix:
        attrs["TaxRegime"] = code.prefix
    _sub(pay, "TaxCode", code.body, **attrs)
    _sub(pay, "TaxablePay", money(ln.taxable_pay_pence))
    after_tax = ln.ee_pension_from_net_pence + ln.deductions_after_tax_pence
    if after_tax:
        _sub(pay, "DednsFromNetPay", money(after_tax))
    _sub(pay, "PayAfterStatDedns", money(ln.net_pay_pence + after_tax))
    if ln.ee_pension_net_pay_pence:
        _sub(pay, "EmpeePenContribnsPaid", money(ln.ee_pension_net_pay_pence))
    if ln.ee_pension_from_net_pence:
        _sub(pay, "EmpeePenContribnsNotPaid", money(ln.ee_pension_from_net_pence))
    if ln.student_loan_plan:
        _sub(pay, "StudentLoanRecovered", money(ln.student_loan_pence), PlanType=f"0{ln.student_loan_plan}")
    if emp.postgrad_loan:
        _sub(pay, "PostgradLoanRecovered", money(ln.postgrad_loan_pence))
    _sub(pay, "TaxDeductedOrRefunded", money(ln.tax_pence))
    if y.smp_pence:
        _sub(pay, "SMPYTD", money(y.smp_pence))

    for letter in sorted(y.ni, key=lambda k: (k != ln.ni_category, k))[:4]:
        v = y.ni[letter]
        this = letter == ln.ni_category
        ni = _sub(em, "NIlettersAndValues")
        _sub(ni, "NIletter", letter)
        _sub(ni, "GrossEarningsForNICsInPd", money(ln.ni_earnings_pence if this else 0))
        _sub(ni, "GrossEarningsForNICsYTD", money(v.gross_pence))
        _sub(ni, "AtLELYTD", money(v.at_lel_pence))
        _sub(ni, "LELtoPTYTD", money(v.lel_to_pt_pence))
        _sub(ni, "PTtoUELYTD", money(v.pt_to_uel_pence))
        _sub(ni, "TotalEmpNICInPd", money(ln.er_ni_pence if this else 0))
        _sub(ni, "TotalEmpNICYTD", money(v.er_pence))
        _sub(ni, "EmpeeContribnsInPd", money(ln.ee_ni_pence if this else 0))
        _sub(ni, "EmpeeContribnsYTD", money(v.ee_pence))


def build_fps(
    run: PayRun, settings: EmployerSettings, employees: dict[str, Employee], final_for_year: bool = False
) -> bytes:
    """The FPS <IRenvelope> for one pay run: one <Employee> per person paid, with year-to-date figures."""
    _check_refs(settings)
    if not run.lines:
        raise RtiError("Nobody was paid in this run")
    first = P.tax_year_start(run.pay_date)
    root = ET.Element("IRenvelope", {"xmlns": FPS_NS})
    _header(root, settings, run.pay_date)
    fps = _sub(root, "FullPaymentSubmission")
    _emprefs(fps, settings)
    _sub(fps, "RelatedTaxYear", R.RELATED_TAX_YEAR)
    for ln in run.lines:
        emp = employees.get(ln.employee_id)
        if emp is None:
            raise RtiError(f"Employee {ln.name} is no longer on file")
        _employee(fps, emp, ln, run, first)
    if final_for_year:
        fin = _sub(fps, "FinalSubmission")
        _sub(fin, "ForYear", "yes")
    return _serialise(root)


# --------------------------------------------------------------------------- #
# Employer payment record (P32-style) and EPS
# --------------------------------------------------------------------------- #


@dataclass
class MonthRecord:
    tax_month: int
    start: date
    end: date
    due: date
    runs: list[str] = field(default_factory=list)
    tax_pence: int = 0
    student_loan_pence: int = 0
    postgrad_loan_pence: int = 0
    ee_ni_pence: int = 0
    er_ni_pence: int = 0
    smp_paid_pence: int = 0
    smp_recovered_pence: int = 0
    nic_compensation_pence: int = 0
    employment_allowance_pence: int = 0

    @property
    def gross_ni_pence(self) -> int:
        return self.ee_ni_pence + self.er_ni_pence

    @property
    def due_pence(self) -> int:
        return (
            self.tax_pence
            + self.student_loan_pence
            + self.postgrad_loan_pence
            + self.gross_ni_pence
            - self.smp_recovered_pence
            - self.nic_compensation_pence
            - self.employment_allowance_pence
        )


def employer_payment_record(runs: list[PayRun], settings: EmployerSettings, tax_year_first: date) -> list[MonthRecord]:
    """Each tax month's PAYE bill from the posted runs paid in it (P32-style). Statutory pay recovery: 92 %, or
    100 % plus 9 % NIC compensation for a small employer (rates page section 10)."""
    months = []
    for m in range(1, 13):
        start, end = P.tax_month_bounds(tax_year_first, m)
        months.append(MonthRecord(m, start, end, P.payment_due(tax_year_first, m)))
    for run in runs:
        if run.status != "posted" or P.tax_year_start(run.pay_date) != tax_year_first:
            continue
        rec = months[P.tax_month(run.pay_date) - 1]
        rec.runs.append(run.id)
        rec.tax_pence += run.total("tax_pence")
        rec.student_loan_pence += run.total("student_loan_pence")
        rec.postgrad_loan_pence += run.total("postgrad_loan_pence")
        rec.ee_ni_pence += run.total("ee_ni_pence")
        rec.er_ni_pence += run.total("er_ni_pence")
        rec.smp_paid_pence += run.total("smp_pence")
        rec.employment_allowance_pence += run.employment_allowance_pence
    for rec in months:
        if not rec.smp_paid_pence:
            continue
        if settings.small_employer_relief:
            rec.smp_recovered_pence = rec.smp_paid_pence
            rec.nic_compensation_pence = P.floor_penny(
                P.Fraction(rec.smp_paid_pence * (R.STAT_PAY_RECOVERY_SMALL_BP - 10_000)) * P.BP
            )
        else:
            rec.smp_recovered_pence = P.floor_penny(P.Fraction(rec.smp_paid_pence * R.STAT_PAY_RECOVERY_BP) * P.BP)
    return months


def build_eps(
    months: list[MonthRecord],
    tax_month: int,
    settings: EmployerSettings,
    *,
    claim_employment_allowance: bool = False,
    final_for_year: bool = False,
) -> bytes:
    """The EPS <IRenvelope> for tax month `tax_month`: no payment (no runs in the month), the Employment Allowance
    indicator, statutory pay recovered year to date, and the final submission for the year."""
    _check_refs(settings)
    rec = months[tax_month - 1]
    root = ET.Element("IRenvelope", {"xmlns": EPS_NS})
    _header(root, settings, rec.end)
    eps = _sub(root, "EmployerPaymentSummary")
    _emprefs(eps, settings)
    any_item = False
    if not rec.runs:
        _sub(eps, "NoPaymentForPeriod", "yes")
        nd = _sub(eps, "NoPaymentDates")
        _sub(nd, "From", rec.start.isoformat())
        _sub(nd, "To", rec.end.isoformat())
        any_item = True
    if claim_employment_allowance:
        _sub(eps, "EmpAllceInd", "yes")
        any_item = True
    upto = months[:tax_month]
    smp = sum(m.smp_recovered_pence for m in upto)
    comp = sum(m.nic_compensation_pence for m in upto)
    if smp or comp:
        rec_ytd = _sub(eps, "RecoverableAmountsYTD")
        _sub(rec_ytd, "TaxMonth", str(tax_month))
        _sub(rec_ytd, "SMPRecovered", money(smp))
        if comp:
            _sub(rec_ytd, "NICCompensationOnSMP", money(comp))
        any_item = True
    _sub(eps, "RelatedTaxYear", R.RELATED_TAX_YEAR)
    if final_for_year:
        fin = _sub(eps, "FinalSubmission")
        _sub(fin, "ForYear", "yes")
        any_item = True
    if not any_item:
        raise RtiError(
            f"No EPS is needed for tax month {tax_month}: people were paid, nothing is recovered and no "
            "Employment Allowance claim or final submission was asked for"
        )
    return _serialise(root)


# --------------------------------------------------------------------------- #
# P45 and P60 figures
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class P45Figures:
    employee_id: str
    name: str
    nino: str | None
    payroll_id: str
    leaving_date: date
    tax_code: str
    week1_month1: bool
    last_period: str  # "Month 7" / "Week 30"
    total_pay_to_date_pence: int  # includes a previous employment's pay when the code was operated cumulatively
    total_tax_to_date_pence: int
    this_employment_pay_pence: int
    this_employment_tax_pence: int
    student_loan_continue: bool
    postgrad_loan_continue: bool
    note: str = (
        "Figures for the P45. Print the official P45 from HMRC's Basic PAYE Tools or your payroll provider; "
        + FILING_NOTE
    )


def p45_figures(emp: Employee, last: PayLine, run: PayRun) -> P45Figures:
    if not emp.leaving_date:
        raise RtiError(f"{emp.name} has no leaving date")
    code = emp.code
    cumulative = not code.non_cumulative
    prev_pay = (emp.p45_previous_pay_pence or 0) if cumulative else 0
    prev_tax = (emp.p45_previous_tax_pence or 0) if cumulative else 0
    return P45Figures(
        employee_id=emp.id,
        name=emp.name,
        nino=emp.nino,
        payroll_id=emp.payroll_id,
        leaving_date=emp.leaving_date,
        tax_code=f"{code.prefix}{code.body}",
        week1_month1=code.non_cumulative,
        last_period=f"Month {run.period}" if run.frequency == "monthly" else f"Week {run.period}",
        total_pay_to_date_pence=prev_pay + last.ytd.taxable_pay_pence,
        total_tax_to_date_pence=prev_tax + last.ytd.tax_pence,
        this_employment_pay_pence=last.ytd.taxable_pay_pence,
        this_employment_tax_pence=last.ytd.tax_pence,
        student_loan_continue=bool(emp.student_loan_plan),
        postgrad_loan_continue=emp.postgrad_loan,
    )


@dataclass(frozen=True)
class P60Figures:
    employee_id: str
    name: str
    nino: str | None
    payroll_id: str
    tax_year: str
    final_tax_code: str
    previous_pay_pence: int
    previous_tax_pence: int
    this_employment_pay_pence: int
    this_employment_tax_pence: int
    total_pay_pence: int
    total_tax_pence: int
    ni: dict[str, dict[str, int]]
    student_loan_pence: int
    postgrad_loan_pence: int
    smp_pence: int
    note: Literal["P60 figures"] = "P60 figures"


def p60_figures(emp: Employee, last: PayLine) -> P60Figures:
    """End-of-year figures for an employee still employed on 5 April (leavers get a P45 instead)."""
    code = emp.code
    cumulative = not code.non_cumulative
    prev_pay = (emp.p45_previous_pay_pence or 0) if cumulative else 0
    prev_tax = (emp.p45_previous_tax_pence or 0) if cumulative else 0
    y = last.ytd
    return P60Figures(
        employee_id=emp.id,
        name=emp.name,
        nino=emp.nino,
        payroll_id=emp.payroll_id,
        tax_year=R.TAX_YEAR,
        final_tax_code=last.tax_code,
        previous_pay_pence=prev_pay,
        previous_tax_pence=prev_tax,
        this_employment_pay_pence=y.taxable_pay_pence,
        this_employment_tax_pence=y.tax_pence,
        total_pay_pence=prev_pay + y.taxable_pay_pence,
        total_tax_pence=prev_tax + y.tax_pence,
        ni={k: v.model_dump() for k, v in y.ni.items()},
        student_loan_pence=y.student_loan_pence,
        postgrad_loan_pence=y.postgrad_loan_pence,
        smp_pence=y.smp_pence,
    )


def readable_fps(run: PayRun, employees: dict[str, Employee]) -> list[dict[str, str]]:
    """The FPS contents as rows a person can read next to the XML: one row per employee and data item."""
    rows = []
    for ln in run.lines:
        emp = employees.get(ln.employee_id)
        item = [
            ("NI number", (emp.nino if emp else None) or "not known"),
            ("Payroll ID", ln.payroll_id),
            ("Pay frequency / date", f"{R.RTI_PAY_FREQ[run.frequency]} / {run.pay_date:%d/%m/%Y}"),
            ("Week or month number", str(run.period)),
            ("Tax code", ln.tax_code),
            ("Taxable pay in period", P.gbp(ln.taxable_pay_pence)),
            ("Tax deducted or refunded", P.gbp(ln.tax_pence)),
            ("Taxable pay to date", P.gbp(ln.ytd.taxable_pay_pence)),
            ("Tax to date", P.gbp(ln.ytd.tax_pence)),
            ("NI letter", ln.ni_category),
            ("Gross for NI in period / to date", f"{P.gbp(ln.ni_earnings_pence)} / {P.gbp(ln.ytd.ni_gross_pence)}"),
            ("Employee NI in period / to date", f"{P.gbp(ln.ee_ni_pence)} / {P.gbp(ln.ytd.ee_ni_pence)}"),
            ("Employer NI in period / to date", f"{P.gbp(ln.er_ni_pence)} / {P.gbp(ln.ytd.er_ni_pence)}"),
            ("Student loan (plan)", f"{P.gbp(ln.student_loan_pence)} ({ln.student_loan_plan or 'none'})"),
            ("Postgraduate loan", P.gbp(ln.postgrad_loan_pence)),
            (
                "Pension (net pay) / (other)",
                f"{P.gbp(ln.ee_pension_net_pay_pence)} / {P.gbp(ln.ee_pension_from_net_pence)}",
            ),
            ("Starter / leaver", f"{'starter' if ln.starter else ''}{' leaver' if ln.leaver else ''}".strip() or "no"),
        ]
        rows.extend({"employee": ln.name, "item": k, "value": v} for k, v in item)
    return rows
