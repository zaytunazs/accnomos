"""Jobs, staff and timesheets, as files in the user's folder; invoice lines from unbilled hours.

    _System/Jobs/jobs.json             [{id, name, customer_id, site_address, estimate_hours, status, created_at}]
    _System/Staff/staff.json           [{id, name, role, hourly_rate_pence, charge_rate_pence, active}]
    _System/Timesheets/{yyyy-mm}.jsonl one entry per line, filed by the entry's date

Money is integer pence throughout. Hours are decimals in quarter-hour steps; maths is done on whole
quarters so nothing drifts through floats. Job costs from purchases are the ex-VAT net of posted
(and not undone) ledger entries whose proposal was tagged with the job on approval.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from accnomos_ledger.events import LedgerEvent
from app.books import SYSTEM, Books, _month, now
from app.schemas import Proposal

JOBS = f"{SYSTEM}/Jobs/jobs.json"
STAFF = f"{SYSTEM}/Staff/staff.json"
TIMESHEETS = f"{SYSTEM}/Timesheets"
from app.contacts import CONTACTS  # noqa: E402  written by the contacts feature, read here for names only

MAX_HOURS_PER_ENTRY = 24
ID_RE = re.compile(r"[0-9a-f]{12}")
MONTH_RE = re.compile(r"\d{4}-\d{2}")


class JobsError(ValueError):
    """The change cannot be made as asked (bad value, unknown reference)."""


class JobsConflict(JobsError):
    """The change clashes with the books' state (invoiced entry, closed job, entries still on it)."""


class NotFound(LookupError):
    pass


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# --------------------------------------------------------------------------- #
# Hours and pence
# --------------------------------------------------------------------------- #


def round_hours(hours: float | int | str | Decimal) -> Decimal:
    """Hours to the nearest quarter hour (half-up: 7m30s rounds up). Raises JobsError when out of range."""
    try:
        h = Decimal(str(hours))
    except InvalidOperation as exc:
        raise JobsError(f"Hours {hours!r} is not a number") from exc
    if not h.is_finite():
        raise JobsError(f"Hours {hours!r} is not a number")
    quarters = (h * 4).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if quarters <= 0:
        raise JobsError("Hours must be at least 0.25")
    if quarters > MAX_HOURS_PER_ENTRY * 4:
        raise JobsError(f"Hours must be at most {MAX_HOURS_PER_ENTRY} per entry")
    return quarters / 4


def quarters(hours: float | Decimal) -> int:
    """Whole quarter hours in a stored (already rounded) hours value."""
    return int((Decimal(str(hours)) * 4).to_integral_value(rounding=ROUND_HALF_UP))


def hours_value(q: int) -> float:
    """Quarter hours back to a JSON-friendly decimal (0.25 steps are exact in binary)."""
    return q / 4


def pence_for(q: int, rate_pence: int) -> int:
    """`q` quarter hours at `rate_pence` an hour, rounded half-up to the penny."""
    return (q * rate_pence + 2) // 4  # == round-half-up(q * rate / 4) in integers


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


class Job(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str = Field(min_length=1, max_length=200)
    customer_id: str | None = None
    site_address: str | None = None
    estimate_hours: float | None = Field(
        default=None, gt=0, le=MAX_HOURS_PER_ENTRY, description="time on site for one visit"
    )
    status: Literal["open", "closed"] = "open"
    created_at: datetime = Field(default_factory=now)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Give the job a name")
        return v.strip()


class StaffMember(BaseModel):
    """Name and role only: no personal identifiers are kept."""

    id: str = Field(default_factory=new_id)
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="", max_length=120)
    hourly_rate_pence: int = Field(ge=0, description="what an hour costs the business")
    charge_rate_pence: int | None = Field(default=None, ge=0, description="what an hour is charged to customers")
    active: bool = True

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Give the staff member a name")
        return v.strip()


class TimesheetEntry(BaseModel):
    id: str = Field(default_factory=new_id)
    staff_id: str
    job_id: str
    date: date
    hours: float
    note: str = Field(default="", max_length=500)
    billable: bool = True
    invoiced_in: str | None = None
    #: Pay-rate multiplier for payroll (1 = normal hours; 1.5 = time and a half; 2 = double time). It changes what
    #: the employee is paid in a PAYE pay run (app/payrun.py), never what the customer is charged.
    rate_multiplier: float = Field(default=1.0, ge=1.0, le=3.0)

    @field_validator("rate_multiplier")
    @classmethod
    def _multiplier_steps(cls, v: float) -> float:
        if v * 4 != round(v * 4):
            raise ValueError("Use a pay multiplier in quarter steps, like 1.5 or 2")
        return float(v)

    @field_validator("hours", mode="before")
    @classmethod
    def _quarter_hours(cls, v: Any) -> float:
        try:
            return float(round_hours(v))
        except JobsError as exc:
            raise ValueError(str(exc)) from exc


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #


def _sheet_path(month: str) -> str:
    return f"{TIMESHEETS}/{month}.jsonl"


def _parse_jsonl(raw: bytes | None) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (raw or b"").decode().splitlines() if x.strip()]


def _dump_jsonl(rows: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(json.dumps(r, ensure_ascii=False).encode() + b"\n" for r in rows)


async def load_jobs(books: Books) -> list[Job]:
    return [Job.model_validate(j) for j in await books.read_json(JOBS, [])]


async def load_staff(books: Books) -> list[StaffMember]:
    return [StaffMember.model_validate(s) for s in await books.read_json(STAFF, [])]


async def get_job(books: Books, job_id: str) -> Job:
    job = next((j for j in await load_jobs(books) if j.id == job_id), None)
    if job is None:
        raise NotFound("No such job")
    return job


async def save_job(books: Books, job: Job) -> Job:
    """Insert or replace by id."""
    row = job.model_dump(mode="json")
    await books._update_json(JOBS, [], lambda rows: [*(r for r in rows if r.get("id") != job.id), row])
    return job


async def delete_job(books: Books, job_id: str) -> None:
    await get_job(books, job_id)
    if any(e.job_id == job_id for e in await load_entries(books)):
        raise JobsConflict("This job has timesheet entries; close it instead")
    await books._update_json(JOBS, [], lambda rows: [r for r in rows if r.get("id") != job_id])


async def save_staff(books: Books, member: StaffMember) -> StaffMember:
    row = member.model_dump(mode="json")
    await books._update_json(STAFF, [], lambda rows: [*(r for r in rows if r.get("id") != member.id), row])
    return member


async def delete_staff(books: Books, staff_id: str) -> None:
    if not any(s.id == staff_id for s in await load_staff(books)):
        raise NotFound("No such staff member")
    if any(e.staff_id == staff_id for e in await load_entries(books)):
        raise JobsConflict("This person has timesheet entries; mark them inactive instead")
    await books._update_json(STAFF, [], lambda rows: [r for r in rows if r.get("id") != staff_id])


async def _months(books: Books) -> list[str]:
    return sorted(
        f.name.removesuffix(".jsonl")
        for f in await books.list_files(TIMESHEETS)
        if f.name.endswith(".jsonl") and MONTH_RE.fullmatch(f.name.removesuffix(".jsonl"))
    )


async def load_entries(books: Books, month: str | None = None) -> list[TimesheetEntry]:
    """Timesheet entries, oldest first (all months, or one `yyyy-mm`)."""
    months = [month] if month else await _months(books)
    out: list[TimesheetEntry] = []
    for m in months:
        try:
            raw = await books.storage.read(_sheet_path(m))
        except FileNotFoundError:
            continue
        out += [TimesheetEntry.model_validate(r) for r in _parse_jsonl(raw)]
    return sorted(out, key=lambda e: (e.date, e.id))


async def _check_refs(books: Books, entry: TimesheetEntry) -> None:
    job = await get_job(books, entry.job_id)
    if job.status != "open":
        raise JobsConflict(f"Job {job.name!r} is closed; reopen it to add or change hours")
    if not any(s.id == entry.staff_id for s in await load_staff(books)):
        raise JobsError("No such staff member")


async def add_entry(books: Books, entry: TimesheetEntry) -> TimesheetEntry:
    if entry.invoiced_in:
        raise JobsError("A new entry cannot already be invoiced")
    await _check_refs(books, entry)
    row = entry.model_dump(mode="json")
    await books._update(_sheet_path(_month(entry.date)), lambda old: (old or b"") + _dump_jsonl([row]))
    return entry


async def get_entry(books: Books, entry_id: str) -> TimesheetEntry:
    found = next((e for e in await load_entries(books) if e.id == entry_id), None)
    if found is None:
        raise NotFound("No such timesheet entry")
    return found


async def _remove_line(books: Books, month: str, entry_id: str) -> None:
    await books._update(
        _sheet_path(month),
        lambda old: _dump_jsonl(r for r in _parse_jsonl(old) if r.get("id") != entry_id),
    )


async def update_entry(books: Books, entry_id: str, changes: dict[str, Any]) -> TimesheetEntry:
    """Edit an uninvoiced entry; moves it to another month's file when its date changes month."""
    old = await get_entry(books, entry_id)
    if old.invoiced_in:
        raise JobsConflict(f"This entry is on invoice {old.invoiced_in}; it can't be changed")
    if "invoiced_in" in changes:
        raise JobsError("Entries are marked invoiced when the invoice is sent")
    try:
        new = TimesheetEntry.model_validate({**old.model_dump(), **changes, "id": old.id})
    except ValueError as exc:
        raise JobsError(str(exc)) from exc
    await _check_refs(books, new)
    row = new.model_dump(mode="json")
    if _month(new.date) == _month(old.date):
        await books._update(
            _sheet_path(_month(old.date)),
            lambda raw: _dump_jsonl(row if r.get("id") == entry_id else r for r in _parse_jsonl(raw)),
        )
    else:  # write the new line first: a failure in between leaves a duplicate, never a lost entry
        await books._update(_sheet_path(_month(new.date)), lambda raw: (raw or b"") + _dump_jsonl([row]))
        await _remove_line(books, _month(old.date), entry_id)
    return new


async def set_rate_multiplier(books: Books, entry_ids: Sequence[str], multiplier: float) -> list[TimesheetEntry]:
    """Set the payroll pay-rate multiplier on these entries (overtime). Only that field changes, so an entry already
    billed to a customer can still be paid at overtime rates: the invoice is untouched."""
    wanted = set(entry_ids)
    found = [e for e in await load_entries(books) if e.id in wanted]
    if {e.id for e in found} != wanted:
        raise NotFound("No such timesheet entry")
    TimesheetEntry.model_validate({**found[0].model_dump(), "rate_multiplier": multiplier})  # checks the steps
    for month in {_month(e.date) for e in found}:
        await books._update(
            _sheet_path(month),
            lambda raw: _dump_jsonl(
                {**r, "rate_multiplier": multiplier} if r.get("id") in wanted else r for r in _parse_jsonl(raw)
            ),
        )
    return [e.model_copy(update={"rate_multiplier": multiplier}) for e in found]


async def delete_entry(books: Books, entry_id: str) -> TimesheetEntry:
    entry = await get_entry(books, entry_id)
    if entry.invoiced_in:
        raise JobsConflict(f"This entry is on invoice {entry.invoiced_in}; it can't be deleted")
    await _remove_line(books, _month(entry.date), entry_id)
    return entry


async def mark_invoiced(books: Books, entry_ids: Sequence[str], invoice_id: str) -> list[TimesheetEntry]:
    """Record that these entries were billed on `invoice_id`. Call when the invoice is *sent*.

    All or nothing: refuses if any entry is unknown, not billable, or already on another invoice.
    Marking again with the same invoice id changes nothing (a retried send is safe).
    """
    if not invoice_id.strip():
        raise JobsError("invoice_id required")
    wanted = set(entry_ids)
    entries = [e for e in await load_entries(books) if e.id in wanted]
    if missing := wanted - {e.id for e in entries}:
        raise JobsError(f"No such timesheet entry {sorted(missing)[0]}")
    for e in entries:
        if not e.billable:
            raise JobsError(f"Entry {e.id} is not billable")
        if e.invoiced_in and e.invoiced_in != invoice_id:
            raise JobsConflict(f"Entry {e.id} is already on invoice {e.invoiced_in}")
    for month in sorted({_month(e.date) for e in entries}):

        def change(raw: bytes | None) -> bytes:
            return _dump_jsonl(
                {**r, "invoiced_in": invoice_id} if r.get("id") in wanted else r for r in _parse_jsonl(raw)
            )

        await books._update(_sheet_path(month), change)
    return [e.model_copy(update={"invoiced_in": invoice_id}) for e in entries]


async def unmark_invoiced(books: Books, invoice_id: str) -> list[TimesheetEntry]:
    """Free the hours billed on `invoice_id` (voiding it): clear `invoiced_in` wherever it still names it.

    Only entries still on that invoice are touched, so calling it twice changes nothing.
    """
    if not invoice_id.strip():
        raise JobsError("invoice_id required")
    wanted = {e.id for e in await load_entries(books) if e.invoiced_in == invoice_id}
    if not wanted:
        return []
    for month in await _months(books):

        def change(raw: bytes | None) -> bytes:
            return _dump_jsonl(
                {**r, "invoiced_in": None} if r.get("invoiced_in") == invoice_id else r for r in _parse_jsonl(raw)
            )

        await books._update(_sheet_path(month), change)
    return [e for e in await load_entries(books) if e.id in wanted]


async def customer_names(books: Books) -> dict[str, str]:
    """Contact id -> name from _System/Contacts/contacts.json, when the contacts feature has written it."""
    try:
        rows = await books.read_json(CONTACTS, [])
    except ValueError:
        return {}
    return {str(r["id"]): str(r.get("name") or r["id"]) for r in rows if isinstance(r, dict) and r.get("id")}


# --------------------------------------------------------------------------- #
# Summaries (pure: computed from what was loaded, so tests need no storage)
# --------------------------------------------------------------------------- #


class StaffHours(BaseModel):
    staff_id: str
    name: str
    role: str
    hours: float
    labour_cost_pence: int
    billable_value_pence: int


class JobSummary(BaseModel):
    job: Job
    customer_name: str | None = None
    hours: float
    billable_hours: float
    unbilled_hours: float  # billable and not yet on an invoice
    labour_cost_pence: int
    billable_value_pence: int
    invoiced_value_pence: int
    unbilled_value_pence: int
    materials_pence: int  # ex-VAT net of purchases tagged to the job
    purchases: list[dict[str, Any]]  # {proposal_id, event_id, date, supplier, net_pence}
    margin_pence: int  # billable value - labour cost - materials
    by_staff: list[StaffHours]
    warnings: list[str]


def charge_rate(member: StaffMember) -> int:
    """The rate an hour is charged at; with no charge rate set, hours are charged at cost."""
    return member.hourly_rate_pence if member.charge_rate_pence is None else member.charge_rate_pence


def job_purchases(job_id: str, proposals: Sequence[Proposal], events: Sequence[LedgerEvent]) -> list[dict[str, Any]]:
    """Posted purchases tagged to `job_id` whose ledger entry still stands (not undone)."""
    reversed_ids = {e.reverses for e in events if e.reverses}
    live = {e.id: e for e in events if e.kind == "purchase" and e.id not in reversed_ids}
    out = []
    for p in proposals:
        ev = live.get(p.event_id or "")
        if p.job_id == job_id and p.status == "posted" and ev is not None:
            vat = ev.vat or 0
            net = ev.net if ev.net is not None else sum(ln.debit for ln in ev.lines) - vat
            out.append(
                {
                    "proposal_id": p.id,
                    "event_id": ev.id,
                    "date": ev.date.isoformat(),
                    "supplier": ev.counterparty,
                    "net_pence": net,
                }
            )
    return sorted(out, key=lambda x: (x["date"], x["event_id"]))


def summarise(
    job: Job,
    entries: Sequence[TimesheetEntry],
    staff: Sequence[StaffMember],
    purchases: Sequence[dict[str, Any]] = (),
    customer_name: str | None = None,
) -> JobSummary:
    """Hours, labour cost, billable value and margin for one job. Costs are worked out per staff
    member (their total quarters × their rate), so per-entry rounding never adds up to a stray penny."""
    people = {s.id: s for s in staff}
    mine = [e for e in entries if e.job_id == job.id]
    q_all: dict[str, int] = defaultdict(int)
    q_bill: dict[str, int] = defaultdict(int)
    q_invoiced: dict[str, int] = defaultdict(int)
    for e in mine:
        q = quarters(e.hours)
        q_all[e.staff_id] += q
        if e.billable:
            q_bill[e.staff_id] += q
            if e.invoiced_in:
                q_invoiced[e.staff_id] += q
    warnings: list[str] = []
    by_staff: list[StaffHours] = []
    for sid in sorted(q_all, key=lambda s: (people[s].name.lower() if s in people else "~", s)):
        member = people.get(sid)
        if member is None:
            warnings.append(f"Hours for an unknown staff member ({sid}) are left out of costs")
            continue
        if member.charge_rate_pence is None and q_bill[sid]:
            warnings.append(f"{member.name} has no charge rate; their hours are valued at cost")
        by_staff.append(
            StaffHours(
                staff_id=sid,
                name=member.name,
                role=member.role,
                hours=hours_value(q_all[sid]),
                labour_cost_pence=pence_for(q_all[sid], member.hourly_rate_pence),
                billable_value_pence=pence_for(q_bill[sid], charge_rate(member)),
            )
        )
    known = [sid for sid in q_all if sid in people]
    billable_value = sum(s.billable_value_pence for s in by_staff)
    invoiced_value = sum(pence_for(q_invoiced[sid], charge_rate(people[sid])) for sid in known)
    labour = sum(s.labour_cost_pence for s in by_staff)
    materials = sum(p["net_pence"] for p in purchases)
    total_bill_q = sum(q_bill.values())
    unbilled_q = total_bill_q - sum(q_invoiced.values())
    return JobSummary(
        job=job,
        customer_name=customer_name,
        hours=hours_value(sum(q_all.values())),
        billable_hours=hours_value(total_bill_q),
        unbilled_hours=hours_value(unbilled_q),
        labour_cost_pence=labour,
        billable_value_pence=billable_value,
        invoiced_value_pence=invoiced_value,
        unbilled_value_pence=billable_value - invoiced_value,
        materials_pence=materials,
        purchases=list(purchases),
        margin_pence=billable_value - labour - materials,
        by_staff=by_staff,
        warnings=warnings,
    )


class InvoiceLine(BaseModel):
    """One proposed line for the invoice form. The invoice code computes VAT; this only proposes."""

    description: str
    qty: float  # hours
    unit: str = "hour"
    unit_price_pence: int
    net_pence: int
    vat_code: str = "S"
    staff_id: str
    role: str
    entry_ids: list[str]


class InvoiceProposal(BaseModel):
    job_id: str
    customer_id: str | None
    lines: list[InvoiceLine]
    entry_ids: list[str]  # the invoice's lines carry these; sending it marks them (invoicing.mark_hours)
    net_pence: int
    warnings: list[str]


def invoice_lines(job: Job, entries: Sequence[TimesheetEntry], staff: Sequence[StaffMember]) -> InvoiceProposal:
    """Unbilled billable hours as invoice lines: one per staff member (name and role), hours × charge rate.

    Nothing is marked: the entries become invoiced only when the invoice is sent (mark_invoiced).
    """
    people = {s.id: s for s in staff}
    todo = [e for e in entries if e.job_id == job.id and e.billable and not e.invoiced_in]
    grouped: dict[str, list[TimesheetEntry]] = defaultdict(list)
    warnings: list[str] = []
    for e in todo:
        if e.staff_id in people:
            grouped[e.staff_id].append(e)
        else:
            warnings.append(f"Entry {e.id} is for an unknown staff member and was left out")
    lines: list[InvoiceLine] = []
    for sid, group in sorted(grouped.items(), key=lambda kv: (people[kv[0]].role.lower(), people[kv[0]].name.lower())):
        member = people[sid]
        if member.charge_rate_pence is None:
            warnings.append(f"{member.name} has no charge rate; their hours are charged at cost")
        q = sum(quarters(e.hours) for e in group)
        first, last = min(e.date for e in group), max(e.date for e in group)
        span = f"{first:%d/%m/%Y}" if first == last else f"{first:%d/%m/%Y}–{last:%d/%m/%Y}"
        who = f"{member.role} ({member.name})" if member.role else member.name
        rate = charge_rate(member)
        lines.append(
            InvoiceLine(
                description=f"{job.name}: {who}, labour {span}",
                qty=hours_value(q),
                unit_price_pence=rate,
                net_pence=pence_for(q, rate),
                staff_id=sid,
                role=member.role,
                entry_ids=[e.id for e in group],
            )
        )
    if not lines:
        warnings.append("No unbilled billable hours on this job")
    return InvoiceProposal(
        job_id=job.id,
        customer_id=job.customer_id,
        lines=lines,
        entry_ids=[i for ln in lines for i in ln.entry_ids],
        net_pence=sum(ln.net_pence for ln in lines),
        warnings=warnings,
    )


async def summaries(
    books: Books,
    events: Sequence[LedgerEvent] | None = None,
    proposals: Sequence[Proposal] | None = None,
) -> list[JobSummary]:
    """Every job's summary, open jobs first then newest."""
    jobs = await load_jobs(books)
    if not jobs:
        return []
    staff, entries, names = await load_staff(books), await load_entries(books), await customer_names(books)
    events = await books.list_events() if events is None else events
    proposals = [p for p in (await books.list_proposals("posted") if proposals is None else proposals) if p.job_id]
    out = [
        summarise(j, entries, staff, job_purchases(j.id, proposals, events), names.get(j.customer_id or ""))
        for j in jobs
    ]
    return sorted(out, key=lambda s: (s.job.status != "open", -s.job.created_at.astimezone(UTC).timestamp()))
