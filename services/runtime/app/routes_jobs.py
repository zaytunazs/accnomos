"""/jobs, /staff, /timesheets: jobs, the people who work on them and their hours (app/jobs.py).

Same headers as /books/* (`X-Graph-Token`, `X-Account-Kind`); changes also need `X-User`.
Books.xlsx's Jobs sheet is rebuilt when entries are marked invoiced and on /books/rebuild;
plain timesheet edits do not rebuild it (that would re-read the whole ledger on every row).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import jobs
from app.books import Books
from app.jobs import Job, JobsError, JobSummary, NotFound, StaffMember, TimesheetEntry
from app.routes_books import get_books, require_user

router = APIRouter(tags=["jobs"])


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFound):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=409 if isinstance(exc, jobs.JobsConflict) else 400, detail=str(exc))


def _id(value: str) -> str:
    if not jobs.ID_RE.fullmatch(value):
        raise HTTPException(status_code=404, detail="Not found")
    return value


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #


class JobIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    customer_id: str | None = None
    site_address: str | None = None
    status: Literal["open", "closed"] = "open"


@router.get("/jobs", response_model=list[JobSummary])
async def list_jobs(books: Books = Depends(get_books)) -> list[JobSummary]:
    """Every job with its summary (hours, costs, margin)."""
    return await jobs.summaries(books)


@router.post("/jobs", response_model=Job)
async def create_job(body: JobIn, books: Books = Depends(get_books), user: str = Depends(require_user)) -> Job:
    try:
        job = await jobs.save_job(books, Job(**body.model_dump()))
    except ValueError as exc:
        raise _http(exc) from exc
    await books.audit(f"user:{user}", "job_created", {"job": job.id})
    return job


@router.put("/jobs/{job_id}", response_model=Job)
async def update_job(job_id: str, body: JobIn, books: Books = Depends(get_books), user: str = Depends(require_user)) -> Job:
    try:
        old = await jobs.get_job(books, _id(job_id))
        job = await jobs.save_job(books, Job(**{**old.model_dump(), **body.model_dump()}))
    except (NotFound, ValueError) as exc:
        raise _http(exc) from exc
    await books.audit(f"user:{user}", "job_updated", {"job": job.id, "status": job.status})
    return job


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> None:
    try:
        await jobs.delete_job(books, _id(job_id))
    except (NotFound, JobsError) as exc:
        raise _http(exc) from exc
    await books.audit(f"user:{user}", "job_deleted", {"job": job_id})


@router.get("/jobs/{job_id}/summary", response_model=JobSummary)
async def job_summary(job_id: str, books: Books = Depends(get_books)) -> JobSummary:
    try:
        job = await jobs.get_job(books, _id(job_id))
    except NotFound as exc:
        raise _http(exc) from exc
    posted = [p for p in await books.list_proposals("posted") if p.job_id == job.id]
    names = await jobs.customer_names(books)
    return jobs.summarise(
        job, await jobs.load_entries(books), await jobs.load_staff(books),
        jobs.job_purchases(job.id, posted, await books.list_events() if posted else []),
        names.get(job.customer_id or ""),
    )


@router.post("/jobs/{job_id}/invoice-lines", response_model=jobs.InvoiceProposal)
async def job_invoice_lines(job_id: str, books: Books = Depends(get_books)) -> jobs.InvoiceProposal:
    """Proposed invoice lines from the job's unbilled billable hours. Marks nothing: the web passes the
    lines into the invoice form, and the entries are marked once that invoice is sent (below)."""
    try:
        job = await jobs.get_job(books, _id(job_id))
    except NotFound as exc:
        raise _http(exc) from exc
    return jobs.invoice_lines(job, await jobs.load_entries(books), await jobs.load_staff(books))


class MarkInvoicedBody(BaseModel):
    invoice_id: str = Field(min_length=1, max_length=64)
    entry_ids: list[str]


@router.post("/jobs/{job_id}/mark-invoiced", response_model=list[TimesheetEntry])
async def mark_invoiced(
    job_id: str, body: MarkInvoicedBody, books: Books = Depends(get_books), user: str = Depends(require_user),
) -> list[TimesheetEntry]:
    """Record the invoice the entries were billed on. Call only once the invoice has been sent.

    TODO(invoicing): sales invoicing (routes_invoices.py) is not on main yet. When it lands, its send step
    should call jobs.mark_invoiced(books, invoice.source_entry_ids, invoice.id) right after the invoice
    becomes `sent`, and the web should stop calling this route itself.
    """
    try:
        await jobs.get_job(books, _id(job_id))
        others = [e.id for e in await jobs.load_entries(books) if e.id in set(body.entry_ids) and e.job_id != job_id]
        if others:
            raise JobsError(f"Entry {others[0]} belongs to another job")
        marked = await jobs.mark_invoiced(books, body.entry_ids, body.invoice_id.strip())
    except (NotFound, JobsError) as exc:
        raise _http(exc) from exc
    await books.audit(f"user:{user}", "timesheets_invoiced",
                      {"job": job_id, "invoice": body.invoice_id, "entries": [e.id for e in marked]})
    await books.rebuild_safely(user)
    return marked


# --------------------------------------------------------------------------- #
# Staff
# --------------------------------------------------------------------------- #


class StaffIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = Field("", max_length=120)
    hourly_rate_pence: int = Field(ge=0)
    charge_rate_pence: int | None = Field(None, ge=0)
    active: bool = True


@router.get("/staff", response_model=list[StaffMember])
async def list_staff(books: Books = Depends(get_books)) -> list[StaffMember]:
    return sorted(await jobs.load_staff(books), key=lambda s: (not s.active, s.name.lower()))


@router.post("/staff", response_model=StaffMember)
async def create_staff(body: StaffIn, books: Books = Depends(get_books), user: str = Depends(require_user)) -> StaffMember:
    try:
        member = await jobs.save_staff(books, StaffMember(**body.model_dump()))
    except ValueError as exc:
        raise _http(exc) from exc
    await books.audit(f"user:{user}", "staff_created", {"staff": member.id})
    return member


@router.put("/staff/{staff_id}", response_model=StaffMember)
async def update_staff(
    staff_id: str, body: StaffIn, books: Books = Depends(get_books), user: str = Depends(require_user),
) -> StaffMember:
    if not any(s.id == _id(staff_id) for s in await jobs.load_staff(books)):
        raise HTTPException(status_code=404, detail="No such staff member")
    try:
        member = await jobs.save_staff(books, StaffMember(id=staff_id, **body.model_dump()))
    except ValueError as exc:
        raise _http(exc) from exc
    await books.audit(f"user:{user}", "staff_updated", {"staff": member.id})
    return member


@router.delete("/staff/{staff_id}", status_code=204)
async def delete_staff(staff_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> None:
    try:
        await jobs.delete_staff(books, _id(staff_id))
    except (NotFound, JobsError) as exc:
        raise _http(exc) from exc
    await books.audit(f"user:{user}", "staff_deleted", {"staff": staff_id})


# --------------------------------------------------------------------------- #
# Timesheet entries
# --------------------------------------------------------------------------- #


class EntryIn(BaseModel):
    staff_id: str
    job_id: str
    date: date
    hours: float
    note: str = Field("", max_length=500)
    billable: bool = True


@router.get("/timesheets", response_model=list[TimesheetEntry])
async def list_entries(
    job_id: str | None = None, staff_id: str | None = None,
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    books: Books = Depends(get_books),
) -> list[TimesheetEntry]:
    return [
        e for e in await jobs.load_entries(books, month)
        if (job_id is None or e.job_id == job_id) and (staff_id is None or e.staff_id == staff_id)
    ]


@router.post("/timesheets", response_model=TimesheetEntry)
async def create_entry(body: EntryIn, books: Books = Depends(get_books), user: str = Depends(require_user)) -> TimesheetEntry:
    try:
        entry = await jobs.add_entry(books, TimesheetEntry(**body.model_dump()))
    except (NotFound, ValueError) as exc:
        raise _http(exc) from exc
    await books.audit(f"user:{user}", "timesheet_added", {"entry": entry.id, "job": entry.job_id, "hours": entry.hours})
    return entry


@router.put("/timesheets/{entry_id}", response_model=TimesheetEntry)
async def update_entry(
    entry_id: str, body: dict[str, Any], books: Books = Depends(get_books), user: str = Depends(require_user),
) -> TimesheetEntry:
    """Partial update: send only the fields that change (staff_id, job_id, date, hours, note, billable)."""
    if unknown := set(body) - set(EntryIn.model_fields):
        raise HTTPException(status_code=400, detail=f"Can't edit {', '.join(sorted(unknown))}")
    try:
        entry = await jobs.update_entry(books, _id(entry_id), body)
    except (NotFound, JobsError) as exc:
        raise _http(exc) from exc
    await books.audit(f"user:{user}", "timesheet_updated", {"entry": entry.id, "fields": sorted(body)})
    return entry


@router.delete("/timesheets/{entry_id}", response_model=TimesheetEntry)
async def delete_entry(entry_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> TimesheetEntry:
    try:
        entry = await jobs.delete_entry(books, _id(entry_id))
    except (NotFound, JobsError) as exc:
        raise _http(exc) from exc
    await books.audit(f"user:{user}", "timesheet_deleted", {"entry": entry.id, "job": entry.job_id})
    return entry
