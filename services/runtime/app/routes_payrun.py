"""/payroll/paye/*: PAYE payroll (app/payrun.py), RTI files (app/rti.py), pension files and payroll reports.

Code calculates; the user approves a pay run (here or in Review) before anything posts. Files come back as base64 in
JSON, like invoice PDFs, and RTI, pension and payslip files are also saved under 05 Payroll/<tax year>/ in OneDrive.
Accnomos never submits to HMRC: every RTI response says to file with Basic PAYE Tools or a payroll provider.
"""

from __future__ import annotations

import base64
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app import paye as P
from app import paye_rates as R
from app import payroll_reports as REP
from app import payrun as PR
from app import pension_ae as AE
from app import rti
from app.approve import ApprovalError, approve
from app.books import Books
from app.paths import PAYROLL
from app.pdf import render_payslip
from app.routes_books import get_books, require_feature, require_user

router = APIRouter(prefix="/payroll/paye", tags=["payroll"], dependencies=[require_feature("payroll")])  # as /payroll

SOURCES = [
    {"label": "HMRC rates and thresholds for employers 2026 to 2027", "url": R.RATES_URL},
    {"label": "HMRC Specification for PAYE Tax Table Routines v24.0 (Feb 2026)", "url": R.PAYE_SPEC_URL},
    {"label": "HMRC NI guidance for software developers 2026 to 2027 v1.1", "url": R.NI_SPEC_URL},
    {"label": "HMRC collection of student loans from 6 April 2026", "url": R.SL_SPEC_URL},
    {"label": "DWP automatic enrolment thresholds 2026/27", "url": R.AE_URL},
    {"label": "The Pensions Regulator earnings thresholds", "url": R.TPR_THRESHOLDS_URL},
    {
        "label": "HMRC RTI technical specifications 2026 to 2027 (schemas)",
        "url": "https://www.gov.uk/government/publications/real-time-information-internet-submissions-2026-to-2027-technical-specifications",
    },
]
LIMITS = [
    "Weekly, fortnightly, four-weekly and monthly pay. Not quarterly, annual or irregular payments.",
    "Directors' NI on the annual (or pro-rata annual) earnings period only, not the alternative arrangements.",
    "Statutory pay: SSP and SMP are calculated; paternity, adoption, shared parental, bereavement and neonatal pay "
    "are not.",
    "No benefits in kind through payroll, no Class 1A, no court orders, no apprenticeship levy, "
    "no off-payroll workers.",
    "Pension refunds after an opt-out and re-enrolment every three years are flagged, not calculated.",
    "New starters' tax codes: the suggested code follows HMRC's long-standing rules; confirm with HMRC's tool.",
]


class FileResult(BaseModel):
    name: str
    media_type: str
    base64: str
    saved_to: str | None = None
    note: str = PR.FILING_NOTE


def _file(name: str, media: str, data: bytes, saved: str | None = None, note: str = PR.FILING_NOTE) -> FileResult:
    return FileResult(name=name, media_type=media, base64=base64.b64encode(data).decode(), saved_to=saved, note=note)


async def _save(books: Books, sub: str, name: str, data: bytes) -> str:
    folder = f"{PAYROLL}/{R.TAX_YEAR}/{sub}"
    await books.storage.ensure_folder(f"{PAYROLL}/{R.TAX_YEAR}")
    await books.storage.ensure_folder(folder)
    path = f"{folder}/{name}"
    await books.storage.write(path, data)
    return path


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc) or "Not found")
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=400, detail="; ".join(e["msg"] for e in exc.errors()))
    conflict = isinstance(exc, (PR.PayrunConflict, ApprovalError))
    return HTTPException(status_code=409 if conflict else 400, detail=str(exc))


ERRORS = (PR.PayrunError, rti.RtiError, P.PayeError, FileNotFoundError, ApprovalError, ValueError)


# --------------------------------------------------------------------------- #
# Setup: employer and employees
# --------------------------------------------------------------------------- #


@router.get("/setup")
async def setup(books: Books = Depends(get_books)) -> dict[str, Any]:
    try:
        employer = await PR.load_employer(books)
        employees = await PR.load_employees(books)
    except (ValueError, ValidationError) as exc:
        raise _http(exc) from exc
    return {
        "employer": employer.model_dump(mode="json"),
        "employees": [e.model_dump(mode="json") for e in employees],
        "tax_year": R.TAX_YEAR,
        "verified_on": R.VERIFIED_ON,
        "sources": SOURCES,
        "limits": LIMITS,
        "filing_note": PR.FILING_NOTE,
        "estimate_note": PR.ESTIMATE_NOTE,
        "ni_categories": {k: v.description for k, v in R.NI_CATEGORIES.items()},
        "submission": {
            "available": False,
            "test_switch": employer.rti_test_submission_enabled,
            "reason": "Accnomos is not HMRC-recognised payroll software and has no HMRC test credentials. "
            + PR.FILING_NOTE,
        },
    }


@router.put("/employer")
async def put_employer(
    body: dict[str, Any], books: Books = Depends(get_books), user: str = Depends(require_user)
) -> dict[str, Any]:
    if body.get("rti_test_submission_enabled"):
        raise HTTPException(status_code=400, detail="RTI submission from Accnomos is not available. " + PR.FILING_NOTE)
    try:
        s = PR.EmployerSettings.model_validate(body)
    except ValidationError as exc:
        raise _http(exc) from exc
    return (await PR.save_employer(books, s, user)).model_dump(mode="json")


@router.post("/employees")
async def add_employee(
    body: dict[str, Any], books: Books = Depends(get_books), user: str = Depends(require_user)
) -> dict[str, Any]:
    body = {k: v for k, v in body.items() if k != "id"}
    try:
        emp = PR.Employee.model_validate(body)
        return (await PR.save_employee(books, emp, user)).model_dump(mode="json")
    except (ValidationError, *ERRORS) as exc:
        raise _http(exc) from exc


@router.put("/employees/{employee_id}")
async def edit_employee(
    employee_id: str, body: dict[str, Any], books: Books = Depends(get_books), user: str = Depends(require_user)
) -> dict[str, Any]:
    try:
        await PR.get_employee(books, employee_id)
        emp = PR.Employee.model_validate({**body, "id": employee_id})
        return (await PR.save_employee(books, emp, user)).model_dump(mode="json")
    except (ValidationError, *ERRORS) as exc:
        raise _http(exc) from exc


@router.delete("/employees/{employee_id}")
async def remove_employee(
    employee_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> dict[str, bool]:
    try:
        await PR.delete_employee(books, employee_id, user)
    except ERRORS as exc:
        raise _http(exc) from exc
    return {"ok": True}


@router.get("/starter-code")
async def starter_code(declaration: Literal["A", "B", "C", "none"] = "none") -> dict[str, Any]:
    code, w1, note = PR.suggested_starter_code(None if declaration == "none" else declaration)
    return {"tax_code": code, "week1_month1": w1, "note": note, "verified": False}


# --------------------------------------------------------------------------- #
# Pay runs
# --------------------------------------------------------------------------- #


class PrepareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frequency: R.Frequency
    pay_date: date


class EditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: list[PR.LineInputs] = Field(max_length=500)
    pay_date: date | None = None


@router.get("/payruns")
async def payruns(books: Books = Depends(get_books)) -> dict[str, Any]:
    try:
        runs = await PR.list_runs(books)
    except (ValueError, ValidationError) as exc:
        raise _http(exc) from exc
    return {"runs": [PR.as_dict(r) for r in reversed(runs)], "filing_note": PR.FILING_NOTE}


@router.post("/payruns/prepare")
async def prepare(body: PrepareBody, books: Books = Depends(get_books), user: str = Depends(require_user)) -> Any:
    try:
        return PR.as_dict(await PR.prepare(books, body.frequency, body.pay_date, user))
    except ERRORS as exc:
        raise _http(exc) from exc


@router.get("/payruns/{rid}")
async def get_run(rid: str, books: Books = Depends(get_books)) -> Any:
    try:
        return PR.as_dict(await PR.get_run(books, rid))
    except ERRORS as exc:
        raise _http(exc) from exc


@router.put("/payruns/{rid}")
async def edit_run(
    rid: str, body: EditBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> Any:
    try:
        return PR.as_dict(await PR.update(books, rid, body.inputs, user, body.pay_date))
    except ERRORS as exc:
        raise _http(exc) from exc


@router.post("/payruns/{rid}/propose")
async def propose(rid: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> Any:
    """Send to Review: a proposal with the journal. Nothing posts yet."""
    try:
        run, p = await PR.propose(books, rid, user)
    except ERRORS as exc:
        raise _http(exc) from exc
    return {"run": PR.as_dict(run), "proposal_id": p.id, "proposal_status": p.status}


@router.post("/payruns/{rid}/approve")
async def approve_run(rid: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> Any:
    """The user approves the run's proposal (the same as approving it in Review): its journal posts."""
    try:
        run = await PR.get_run(books, rid)
        if run.status != "proposed" or not run.proposal_id:
            raise PR.PayrunConflict("Send the pay run to Review first")
        await approve(books, run.proposal_id, user)
        return PR.as_dict(await PR.get_run(books, rid))
    except ERRORS as exc:
        raise _http(exc) from exc


@router.post("/payruns/{rid}/draft")
async def to_draft(rid: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> Any:
    try:
        return PR.as_dict(await PR.back_to_draft(books, rid, user))
    except ERRORS as exc:
        raise _http(exc) from exc


@router.post("/payruns/{rid}/discard")
async def discard(rid: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> dict[str, str]:
    try:
        return {"moved_to": await PR.discard_run(books, rid, user)}
    except ERRORS as exc:
        raise _http(exc) from exc


# --------------------------------------------------------------------------- #
# Payslips
# --------------------------------------------------------------------------- #


def payslip_pdf(run: PR.PayRun, ln: PR.PayLine, emp: PR.Employee | None, employer: str) -> bytes:
    g = P.gbp
    payments = [
        (
            f"{i.label} ({i.hours:g} h x {g(i.rate_pence)}{f' x {i.multiplier:g}' if i.multiplier != 1 else ''})"
            if i.hours is not None and i.rate_pence is not None
            else i.label,
            g(i.pence),
        )
        for i in ln.pay_items
    ] or [("Basic pay", g(ln.basic_pence))]
    if ln.bonus_pence:
        payments.append(("Bonus / overtime", g(ln.bonus_pence)))
    if ln.ssp_pence:
        payments.append(("Statutory Sick Pay", g(ln.ssp_pence)))
    if ln.smp_pence:
        payments.append(("Statutory Maternity Pay", g(ln.smp_pence)))
    if ln.salary_sacrifice_pence:
        payments.append(("Salary sacrifice (pension)", g(-ln.salary_sacrifice_pence)))
    payments.append(("Total pay", g(ln.ni_earnings_pence)))
    deductions = [("Income tax", g(ln.tax_pence)), ("National Insurance", g(ln.ee_ni_pence))]
    if ln.student_loan_pence or ln.student_loan_plan:
        deductions.append((f"Student loan (plan {ln.student_loan_plan})", g(ln.student_loan_pence)))
    if ln.postgrad_loan_pence:
        deductions.append(("Postgraduate loan", g(ln.postgrad_loan_pence)))
    if ln.ee_pension_net_pay_pence:
        deductions.append(("Pension (before tax)", g(ln.ee_pension_net_pay_pence)))
    if ln.ee_pension_from_net_pence:
        deductions.append(("Pension (relief at source)", g(ln.ee_pension_from_net_pence)))
    if ln.deductions_after_tax_pence:
        deductions.append(("Other deductions", g(ln.deductions_after_tax_pence)))
    deductions.append(("Total deductions", g(ln.total_deductions_pence)))
    y = ln.ytd
    ytd = [
        ("Taxable pay", g(y.taxable_pay_pence)),
        ("Income tax", g(y.tax_pence)),
        ("Employee NI", g(y.ee_ni_pence)),
        ("Employee pension", g(y.ee_pension_net_pay_pence + y.ee_pension_other_pence)),
    ]
    if y.student_loan_pence:
        ytd.append(("Student loan", g(y.student_loan_pence)))
    costs = [("Employer NI", g(ln.er_ni_pence)), ("Employer pension", g(ln.pension.employer_pence))]
    meta = [
        ("Pay date", f"{run.pay_date:%d %B %Y}"),
        ("Period", f"{'Month' if run.frequency == 'monthly' else 'Week'} {run.period} ({run.period_start:%d/%m} to "
                   f"{run.period_end:%d/%m/%Y})"),
        ("Payroll ID", ln.payroll_id),
        ("NI number", (emp.nino if emp else None) or "not known"),
        ("Tax code", ln.tax_code),
        ("NI category", ln.ni_category),
    ]  # fmt: skip
    notes = [*ln.tax_notes, *ln.pension.notes]
    if run.status != "posted":
        notes.insert(0, f"DRAFT: this pay run is {run.status}, not approved. {PR.ESTIMATE_NOTE}.")
    return render_payslip(employer, ln.name, meta, payments, deductions, g(ln.net_pay_pence), ytd, costs, notes)


@router.get("/payruns/{rid}/payslips/{employee_id}")
async def payslip(rid: str, employee_id: str, books: Books = Depends(get_books)) -> FileResult:
    try:
        run = await PR.get_run(books, rid)
        ln = next((x for x in run.lines if x.employee_id == employee_id), None)
        if ln is None:
            raise FileNotFoundError("That employee isn't on this pay run")
        employees = {e.id: e for e in await PR.load_employees(books)}
        employer = await PR.load_employer(books)
    except ERRORS as exc:
        raise _http(exc) from exc
    data = payslip_pdf(run, ln, employees.get(employee_id), employer.name)
    name = f"payslip-{run.id}-{ln.payroll_id}.pdf".replace(" ", "-")
    saved = await _save(books, "payslips", name, data) if run.status == "posted" else None
    return _file(name, "application/pdf", data, saved, note="Payslip. " + PR.ESTIMATE_NOTE)


# --------------------------------------------------------------------------- #
# RTI
# --------------------------------------------------------------------------- #


@router.get("/payruns/{rid}/fps")
async def fps(
    rid: str, final: bool = False, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> Any:
    """The FPS XML for a posted run (to the 2026-27 schema) and its contents as rows. Not submitted."""
    try:
        run = await PR.get_run(books, rid)
        if run.status != "posted":
            raise PR.PayrunConflict("Approve the pay run first: an FPS reports what was actually paid")
        employees = {e.id: e for e in await PR.load_employees(books)}
        data = rti.build_fps(run, await PR.load_employer(books), employees, final_for_year=final)
    except ERRORS as exc:
        raise _http(exc) from exc
    name = f"FPS-{run.id}.xml"
    saved = await _save(books, "RTI", name, data)
    await books.audit(f"user:{user}", "rti_fps_generated", {"run": rid, "path": saved, "submitted": False})
    readable = REP.fps_contents(run, employees).as_json()
    return {"file": _file(name, "application/xml", data, saved), "contents": readable, "schema": rti.SCHEMA_SOURCE}


@router.get("/eps/{tax_month}")
async def eps(
    tax_month: int,
    employment_allowance: bool = False,
    final: bool = False,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> Any:
    if not 1 <= tax_month <= 12:
        raise HTTPException(status_code=400, detail="Tax month is 1 (6 Apr-5 May) to 12 (6 Mar-5 Apr)")
    try:
        settings = await PR.load_employer(books)
        first = date(int(R.TAX_YEAR[:4]), 4, 6)
        months = rti.employer_payment_record(await PR.list_runs(books), settings, first)
        data = rti.build_eps(
            months, tax_month, settings, claim_employment_allowance=employment_allowance, final_for_year=final
        )
    except ERRORS as exc:
        raise _http(exc) from exc
    name = f"EPS-{R.TAX_YEAR}-month-{tax_month:02d}.xml"
    saved = await _save(books, "RTI", name, data)
    await books.audit(f"user:{user}", "rti_eps_generated", {"tax_month": tax_month, "path": saved, "submitted": False})
    rec = months[tax_month - 1]
    contents = [
        {"item": "Tax month", "value": f"{tax_month} ({rec.start:%d/%m/%Y} to {rec.end:%d/%m/%Y})"},
        {"item": "No payment for period", "value": "Yes" if not rec.runs else "No"},
        {"item": "Employment Allowance indicator", "value": "Yes" if employment_allowance else "Not sent"},
        {"item": "SMP recovered to date", "value": P.gbp(sum(m.smp_recovered_pence for m in months[:tax_month]))},
        {"item": "NIC compensation to date", "value": P.gbp(sum(m.nic_compensation_pence for m in months[:tax_month]))},
        {"item": "Final submission for year", "value": "Yes" if final else "No"},
    ]
    return {"file": _file(name, "application/xml", data, saved), "contents": contents, "schema": rti.SCHEMA_SOURCE}


# --------------------------------------------------------------------------- #
# Pension files and reports
# --------------------------------------------------------------------------- #


async def schedule(books: Books, run: PR.PayRun) -> tuple[AE.ScheduleHeader, list[AE.ScheduleRow]]:
    settings = await PR.load_employer(books)
    employees = {e.id: e for e in await PR.load_employees(books)}
    ps = settings.pension
    first = P.tax_year_start(run.pay_date)
    due = P.payment_due(first, P.tax_month(run.pay_date))
    h = AE.ScheduleHeader(
        run.period_start, run.period_end, run.pay_date, run.frequency, ps.provider_ref, ps.payment_source, ps.pay_code,
        due, ps.arrangement, run.period,
    )  # fmt: skip
    rows = []
    for ln in run.lines:
        e = employees.get(ln.employee_id)
        if e is None or not (ln.pension.member or ln.pension.category == "eligible_jobholder"):
            continue
        rows.append(
            AE.ScheduleRow(
                employee_id=e.id, payroll_id=e.payroll_id, title=e.title, forename=e.forenames, surname=e.surname,
                nino=e.nino or "", dob=e.dob, gender=e.gender, category=ln.pension.category,
                pensionable_pence=ln.pension.pensionable_pence, employer_pence=ln.pension.employer_pence,
                employee_pence=ln.pension.employee_deducted_pence,
                employee_gross_pence=ln.pension.employee_gross_pence, enrolled_on=ln.pension.enrolled_on,
                opted_out_on=e.opted_out_on, left_on=e.leaving_date if ln.leaver else None,
                gross_pay_pence=ln.gross_pence, start_date=e.start_date, address=tuple(e.address), postcode=e.postcode,
                email=e.email, salary_sacrifice=ln.pension.arrangement == "salary_sacrifice",
                reason_code="",
            )
        )  # fmt: skip
    return h, rows


PROVIDER_NOTES = {
    "generic": "Accnomos layout: map the columns in your provider's upload screen.",
    "nest": "Nest contribution schedule (CS) from Nest's Employer payroll guide (the edition on Nest's site "
    "on 28 Oct 2026, file version 4). The frequency and payment source must match your schedule in Nest exactly.",
    "peoples_pension": "The People's Pension contributions file (CO), from its Contributions file data requirements "
    "v9, the version it publishes today.",
    "smart_pension": "Smart Pension PAPDIS 1.0 (PAP01) file, from Smart Pension's CSV specification. For the net pay "
    "arrangement only. Upload under Contributions and payroll > Pre-assessed contributions.",
    "now_pensions": "NOW: Pensions pension data file (36 items), from its online guide (undated, read 28 Oct 2026).",
}


@router.get("/payruns/{rid}/pension/{provider}")
async def pension_file(rid: str, provider: AE.Provider, books: Books = Depends(get_books)) -> FileResult:
    try:
        run = await PR.get_run(books, rid)
        h, rows = await schedule(books, run)
    except ERRORS as exc:
        raise _http(exc) from exc
    if provider == "nest":
        text = AE.nest_csv(h, rows)
    elif provider == "peoples_pension":
        text = AE.peoples_pension_csv(h, rows)
    elif provider == "smart_pension":
        try:
            text = AE.smart_pension_csv(h, rows)
        except AE.PensionFileError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif provider == "now_pensions":
        text = AE.now_pensions_csv(h, rows, run.period)
    else:
        text = AE.generic_csv(h, rows)
    data = text.encode("utf-8")
    name = f"pension-{provider}-{run.id}.csv"
    saved = await _save(books, "Pension", name, data) if run.status == "posted" else None
    return _file(name, "text/csv", data, saved, note=PROVIDER_NOTES[provider])


ReportKey = Literal["payroll_summary", "p11", "p32", "pension", "fps", "journal", "p45", "p60"]


async def build_report(books: Books, key: ReportKey, run_id: str | None, employee_id: str | None) -> REP.Table:
    runs = await PR.list_runs(books)
    employees = {e.id: e for e in await PR.load_employees(books)}
    settings = await PR.load_employer(books)
    if key == "p32":
        return REP.p32(rti.employer_payment_record(runs, settings, date(int(R.TAX_YEAR[:4]), 4, 6)))
    if key in ("p11", "p45", "p60"):
        if not employee_id or employee_id not in employees:
            raise FileNotFoundError("Choose an employee")
        emp = employees[employee_id]
        if key == "p11":
            return REP.p11(emp, runs)
        posted = [(r, ln) for r in runs if r.status == "posted" for ln in r.lines if ln.employee_id == emp.id]
        if not posted:
            raise rti.RtiError(f"{emp.name} has no approved pay runs this year")
        last_run, last = posted[-1]
        if key == "p45":
            return REP.p45_table(rti.p45_figures(emp, last, last_run))
        if emp.leaving_date:
            raise rti.RtiError(f"{emp.name} has left: they get a P45, not a P60")
        return REP.p60_table(rti.p60_figures(emp, last))
    if not run_id:
        raise FileNotFoundError("Choose a pay run")
    run = await PR.get_run(books, run_id)
    if key == "payroll_summary":
        return REP.payroll_summary(run)
    if key == "pension":
        return REP.pension_workings(run)
    if key == "fps":
        return REP.fps_contents(run, employees)
    return REP.journal_rows(run)


@router.get("/reports/{key}")
async def report(
    key: ReportKey,
    run: str | None = Query(default=None, max_length=40),
    employee: str | None = Query(default=None, max_length=32),
    format: REP.Format = "json",  # noqa: A002
    books: Books = Depends(get_books),
) -> Any:
    try:
        t = await build_report(books, key, run, employee)
    except (*ERRORS, ValidationError) as exc:
        raise _http(exc) from exc
    if format == "json":
        return t.as_json()
    employer = (await PR.load_employer(books)).name
    stem = f"{key}-{run}" if key in ("payroll_summary", "pension", "fps", "journal") and run else key
    if key in ("p11", "p45", "p60") and employee:
        emp = next((e for e in await PR.load_employees(books) if e.id == employee), None)
        stem = f"{key}-{emp.payroll_id}" if emp else key
    data, media, name = REP.render(t, format, employer, stem)
    return _file(name, media, data, note=PR.ESTIMATE_NOTE)


@router.get("/rti/status")
async def rti_status(books: Books = Depends(get_books)) -> dict[str, Any]:
    s = await PR.load_employer(books)
    return {
        "submission_available": False,
        "test_submission_enabled": s.rti_test_submission_enabled,
        "filing_note": PR.FILING_NOTE,
        "specification": SOURCES[-1],
    }
