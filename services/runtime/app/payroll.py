"""Pay runs prepared from timesheets for the owner's payroll provider. Estimates only: not payroll, not RTI.

    _System/Payroll/runs/{yyyy-mm}.json   one pay run per calendar month
    05 Payroll/{yyyy-mm}.csv              the export handed to the payroll provider (or HMRC Basic PAYE Tools)

Accnomos does not run payroll or file anything with HMRC. It adds up each person's hours for the month at
their hourly rate (staff.json `hourly_rate_pence`), estimates PAYE and NI with the one rates table in
app/payroll_rates.py, and, once the owner types in what the provider actually calculated, posts the staff
costs to the ledger:

    Dr 7000 Gross wages        actual gross     Cr 2210 Payroll liabilities
    Dr 7010 Employer's NI      actual ER NI     Cr 2210 Payroll liabilities

2210 holds what is owed to staff (net pay) and to HMRC (PAYE, employee and employer NI) until it is paid.
Money is integer pence throughout; hours are quarter-hour steps (app/jobs.py).
"""

from __future__ import annotations

import calendar
import csv
import io
import logging
import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from accnomos_ledger.events import LedgerEvent, Line
from app import payroll_rates as R
from app.books import SYSTEM, Books, now
from app.jobs import hours_value, load_entries, load_staff, pence_for, quarters
from app.paths import PAYROLL
from app.validation import Pence, StrictBody

log = logging.getLogger(__name__)

RUNS = f"{SYSTEM}/Payroll/runs"
EXPORTS = PAYROLL
WAGES = "7000 Gross wages"
EMPLOYER_NI = "7010 Employer's NI"
LIABILITIES = "2210 Payroll liabilities"
PERIOD_RE = re.compile(r"(\d{4})-(0[1-9]|1[0-2])")
MAX_HOURS_PER_MONTH = 744  # 31 days × 24 hours


class PayrollError(ValueError):
    """The change cannot be made as asked."""


class PayrollConflict(PayrollError):
    """The run is in the wrong state (already confirmed, or not yet)."""


# --------------------------------------------------------------------------- #
# Estimates (pure)
# --------------------------------------------------------------------------- #


class Estimate(BaseModel):
    paye_pence: int
    ee_ni_pence: int
    er_ni_pence: int
    net_pence: int


def _band(amount: Fraction, low: Fraction, high: Fraction | None) -> Fraction:
    """The part of `amount` between `low` and `high` (no upper limit when None)."""
    top = amount if high is None else min(amount, high)
    return max(Fraction(0), top - low)


def _ni_round(x: Fraction) -> int:
    """HMRC's NI rounding: to the nearest penny, half a penny rounds down."""
    whole, rest = divmod(x, 1)
    return int(whole) + (1 if rest > Fraction(1, 2) else 0)


def estimate(gross_pence: int) -> Estimate:
    """Monthly PAYE (tax code 1257L, month 1 basis), employee and employer Class 1 NI (category A).

    Annual thresholds are pro-rated to a month as ÷ 12. Taxable pay is rounded down to whole pounds and tax
    down to the penny, as HMRC's tables do; NI is rounded to the nearest penny.
    """
    if gross_pence < 0:
        raise PayrollError("Gross pay can't be negative")
    g = Fraction(gross_pence)
    month = Fraction(1, 12)
    free = R.PERSONAL_ALLOWANCE * month
    taxable = Fraction((max(Fraction(0), g - free) // 100) * 100)
    basic_top = (R.BASIC_RATE_LIMIT - R.PERSONAL_ALLOWANCE) * month
    higher_top = (R.ADDITIONAL_RATE_THRESHOLD - R.PERSONAL_ALLOWANCE) * month
    tax = (
        _band(taxable, Fraction(0), basic_top) * R.BASIC_RATE
        + _band(taxable, basic_top, higher_top) * R.HIGHER_RATE
        + _band(taxable, higher_top, None) * R.ADDITIONAL_RATE
    ) / 100
    paye = int(tax)  # rounded down
    pt, uel, st = R.NI_PRIMARY_THRESHOLD * month, R.NI_UPPER_EARNINGS_LIMIT * month, R.NI_SECONDARY_THRESHOLD * month
    ee = _ni_round((_band(g, pt, uel) * R.NI_EMPLOYEE_MAIN_RATE + _band(g, uel, None) * R.NI_EMPLOYEE_UPPER_RATE) / 100)
    er = _ni_round(_band(g, st, None) * R.NI_EMPLOYER_RATE / 100)
    return Estimate(paye_pence=paye, ee_ni_pence=ee, er_ni_pence=er, net_pence=gross_pence - paye - ee)


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


class PayLine(BaseModel):
    staff_id: str
    hours: float
    rate_pence: int = Field(ge=0)
    gross_pence: int
    est_paye_pence: int
    est_ee_ni_pence: int
    est_er_ni_pence: int
    est_net_pence: int
    notes: str = ""


class PayRun(BaseModel):
    period_start: date
    period_end: date
    pay_date: date
    lines: list[PayLine]
    status: Literal["draft", "confirmed"] = "draft"
    confirmed_gross_pence: int | None = None
    confirmed_er_ni_pence: int | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    event_ids: list[str] = Field(default_factory=list)  # ledger entries posted on confirm
    undone_event_ids: list[str] = Field(default_factory=list)  # from confirms reopened since
    warnings: list[str] = Field(default_factory=list)
    estimate: str = R.ESTIMATE_LABEL  # said in the file too, for anyone opening it in OneDrive
    limits: list[str] = Field(default_factory=lambda: list(R.LIMITS))

    @property
    def period(self) -> str:
        return f"{self.period_start:%Y-%m}"

    @property
    def est_gross_pence(self) -> int:
        return sum(ln.gross_pence for ln in self.lines)

    @property
    def est_er_ni_pence(self) -> int:
        return sum(ln.est_er_ni_pence for ln in self.lines)


class LineEdit(StrictBody):
    staff_id: str = Field(max_length=32)
    hours: float | Annotated[str, Field(max_length=12)]
    rate_pence: Pence = Field(ge=0, le=100_000)  # up to £1,000 an hour
    notes: str = Field("", max_length=300)


def period_bounds(period: str) -> tuple[date, date]:
    """'2026-10' -> (1 Oct 2026, 31 Oct 2026)."""
    m = PERIOD_RE.fullmatch(period or "")
    if not m:
        raise PayrollError(f"Period {period!r} should be a month like 2026-10")
    y, mo = int(m.group(1)), int(m.group(2))
    return date(y, mo, 1), date(y, mo, calendar.monthrange(y, mo)[1])


def month_quarters(hours: float | str) -> int:
    """Hours for a month (0 to 744) as whole quarter hours, rounded half-up."""
    try:
        h = Decimal(str(hours))
    except InvalidOperation as exc:
        raise PayrollError(f"Hours {hours!r} is not a number") from exc
    if not h.is_finite() or h < 0 or h > MAX_HOURS_PER_MONTH:
        raise PayrollError(f"Hours must be between 0 and {MAX_HOURS_PER_MONTH}")
    return int((h * 4).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def make_line(staff_id: str, q: int, rate_pence: int, notes: str = "") -> PayLine:
    gross = pence_for(q, rate_pence)
    est = estimate(gross)
    return PayLine(
        staff_id=staff_id,
        hours=hours_value(q),
        rate_pence=rate_pence,
        gross_pence=gross,
        est_paye_pence=est.paye_pence,
        est_ee_ni_pence=est.ee_ni_pence,
        est_er_ni_pence=est.er_ni_pence,
        est_net_pence=est.net_pence,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #


def _path(period: str) -> str:
    period_bounds(period)  # validates, so nothing but yyyy-mm reaches a path
    return f"{RUNS}/{period}.json"


async def load_run(books: Books, period: str) -> PayRun | None:
    raw = await books.read_json(_path(period), None)
    return None if raw is None else PayRun.model_validate(raw)


async def get_run(books: Books, period: str) -> PayRun:
    run = await load_run(books, period)
    if run is None:
        raise FileNotFoundError(f"No pay run for {period}; prepare it first")
    return run


async def list_runs(books: Books) -> list[PayRun]:
    """Every pay run, newest period first."""
    out = []
    for f in await books.list_files(RUNS):
        stem = f.name.removesuffix(".json")
        if f.name.endswith(".json") and PERIOD_RE.fullmatch(stem):
            out.append(PayRun.model_validate(await books.read_json(f.path, {})))
    return sorted(out, key=lambda r: r.period_start, reverse=True)


async def _save(books: Books, run: PayRun) -> PayRun:
    await books.write_json(_path(run.period), run.model_dump(mode="json"))
    return run


def _refuse_confirmed(run: PayRun | None) -> None:
    if run is not None and run.status == "confirmed":
        raise PayrollConflict(f"The {run.period} pay run is confirmed and posted; reopen it to change it")


# --------------------------------------------------------------------------- #
# Prepare, edit, export, confirm, reopen
# --------------------------------------------------------------------------- #


async def prepare(books: Books, period: str, pay_date: date | None, user: str) -> PayRun:
    """The month's timesheet hours × each person's hourly rate. Replaces a draft (edits included)."""
    start, end = period_bounds(period)
    old = await load_run(books, period)
    _refuse_confirmed(old)
    staff = {s.id: s for s in await load_staff(books)}
    q: dict[str, int] = defaultdict(int)
    for e in await load_entries(books, period):
        q[e.staff_id] += quarters(e.hours)
    warnings = [f"Hours for an unknown staff member ({sid}) are left out" for sid in sorted(q) if sid not in staff]
    lines = []
    for sid in sorted((s for s in q if s in staff), key=lambda s: (staff[s].name.lower(), s)):
        member = staff[sid]
        notes = [] if member.active else ["Marked inactive"]
        if member.hourly_rate_pence == 0:
            notes.append("No hourly rate set")
        lines.append(make_line(sid, q[sid], member.hourly_rate_pence, "; ".join(notes)))
    if not lines:
        warnings.append(f"No timesheet hours in {start:%B %Y}")
    run = PayRun(
        period_start=start,
        period_end=end,
        pay_date=pay_date or (old.pay_date if old else end),
        lines=lines,
        warnings=warnings,
    )
    await _save(books, run)
    await books.audit(
        f"user:{user}",
        "payroll_prepared",
        {"period": period, "lines": len(lines), "est_gross_pence": run.est_gross_pence},
    )
    return run


async def update(books: Books, period: str, lines: Sequence[LineEdit], pay_date: date | None, user: str) -> PayRun:
    """Replace the draft's lines with edited hours, rates and notes; estimates are worked out again."""
    run = await get_run(books, period)
    _refuse_confirmed(run)
    known = {s.id for s in await load_staff(books)}
    seen: set[str] = set()
    new = []
    for edit in lines:
        if edit.staff_id not in known:
            raise PayrollError(f"No such staff member {edit.staff_id}")
        if edit.staff_id in seen:
            raise PayrollError("Each person can only be on the pay run once")
        seen.add(edit.staff_id)
        new.append(make_line(edit.staff_id, month_quarters(edit.hours), edit.rate_pence, edit.notes.strip()))
    run = run.model_copy(update={"lines": new, "pay_date": pay_date or run.pay_date})
    await _save(books, run)
    await books.audit(
        f"user:{user}", "payroll_edited", {"period": period, "lines": len(new), "est_gross_pence": run.est_gross_pence}
    )
    return run


CSV_HEADER = (
    "Employee",
    "Role",
    "Hours",
    "Hourly rate £",
    "Gross pay £",
    "Est. PAYE £",
    "Est. employee NI £",
    "Est. net pay £",
    "Est. employer NI £",
    "Notes",
)


def _gbp(pence: int) -> str:
    return f"{pence / 100:.2f}"


def _hours(h: float) -> str:
    """15.5 -> '15.5', 8.0 -> '8', 12345.25 -> '12345.25' (quarter hours; :g would round big totals)."""
    return f"{h:.2f}".rstrip("0").rstrip(".")


def _text(s: str) -> str:
    """Typed-in text (names, roles, notes) that a spreadsheet would run as a formula gets a leading apostrophe."""
    return f"'{s}" if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def export_csv(run: PayRun, names: dict[str, tuple[str, str]]) -> str:
    """The estimate label and limits first, then one row per employee and a totals row."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([R.ESTIMATE_LABEL])
    w.writerow([f"Pay run {run.period_start:%d/%m/%Y}–{run.period_end:%d/%m/%Y}, pay date {run.pay_date:%d/%m/%Y}"])
    for limit in R.LIMITS:
        w.writerow([limit])
    w.writerow([])
    w.writerow(CSV_HEADER)
    for ln in run.lines:
        name, role = names.get(ln.staff_id, (ln.staff_id, ""))
        w.writerow(
            [
                _text(name),
                _text(role),
                _hours(ln.hours),
                _gbp(ln.rate_pence),
                _gbp(ln.gross_pence),
                _gbp(ln.est_paye_pence),
                _gbp(ln.est_ee_ni_pence),
                _gbp(ln.est_net_pence),
                _gbp(ln.est_er_ni_pence),
                _text(ln.notes),
            ]
        )
    w.writerow(
        [
            "Total",
            "",
            _hours(sum(ln.hours for ln in run.lines)),
            "",
            *(
                _gbp(sum(getattr(ln, f) for ln in run.lines))
                for f in ("gross_pence", "est_paye_pence", "est_ee_ni_pence", "est_net_pence", "est_er_ni_pence")
            ),
            "",
        ]
    )
    return buf.getvalue()


async def staff_names(books: Books) -> dict[str, tuple[str, str]]:
    return {s.id: (s.name, s.role) for s in await load_staff(books)}


async def export(books: Books, period: str, user: str) -> tuple[str, str]:
    """(path, csv text). Writes 05 Payroll/{period}.csv, replacing an earlier export of the same month."""
    run = await get_run(books, period)
    text = export_csv(run, await staff_names(books))
    path = f"{EXPORTS}/{period}.csv"
    await books.storage.ensure_folder(EXPORTS)
    await books.storage.write(path, text.encode("utf-8-sig"))  # BOM: Excel then reads £ and – correctly
    await books.audit(f"user:{user}", "payroll_exported", {"period": period, "path": path})
    return path, text


def staff_cost_events(run: PayRun, gross_pence: int, er_ni_pence: int, user: str, at: datetime) -> list[LedgerEvent]:
    """Balanced adjustments for what was actually paid: gross wages and (when there is any) employer NI."""
    who = f"Payroll {run.period}"
    events = [
        LedgerEvent(
            kind="adjustment",
            date=run.pay_date,
            approved_by=user,
            approved_at=at,
            counterparty=who,
            lines=[
                Line(
                    account=WAGES, debit=gross_pence, memo=f"{who}: gross pay (as calculated by your payroll provider)"
                ),
                Line(
                    account=LIABILITIES,
                    credit=gross_pence,
                    memo=f"{who}: net pay to staff, PAYE and employee NI to HMRC",
                ),
            ],
        )
    ]
    if er_ni_pence:
        events.append(
            LedgerEvent(
                kind="adjustment",
                date=run.pay_date,
                approved_by=user,
                approved_at=at,
                counterparty=who,
                lines=[
                    Line(account=EMPLOYER_NI, debit=er_ni_pence, memo=f"{who}: employer's Class 1 NI"),
                    Line(account=LIABILITIES, credit=er_ni_pence, memo=f"{who}: employer NI to HMRC"),
                ],
            )
        )
    return events


async def confirm(books: Books, period: str, gross_pence: int, er_ni_pence: int, user: str) -> PayRun:
    """Post the actual figures (from the payroll provider, not the estimate) and mark the run confirmed."""
    run = await get_run(books, period)
    _refuse_confirmed(run)
    if gross_pence <= 0:
        raise PayrollError("Type in the actual gross pay from your payroll provider")
    if er_ni_pence < 0:
        raise PayrollError("Employer NI can't be negative")
    at = now()
    events = staff_cost_events(run, gross_pence, er_ni_pence, user, at)
    posted: list[LedgerEvent] = []
    try:
        for ev in events:
            await books.post_event(ev)
            posted.append(ev)
        run = run.model_copy(
            update={
                "status": "confirmed",
                "confirmed_gross_pence": gross_pence,
                "confirmed_er_ni_pence": er_ni_pence,
                "confirmed_by": user,
                "confirmed_at": at,
                "event_ids": [e.id for e in events],
            }
        )
        await _save(books, run)
    except Exception:
        # Never leave half a pay run in the books, or entries the run file doesn't know about (a second
        # confirm would then post them twice).
        from app.approve import undo

        for ev in posted:
            try:
                await undo(books, ev.id, user)
            except Exception:
                log.exception("Could not undo pay run entry %s after a failed confirm", ev.id)
        raise
    await books.audit(
        f"user:{user}",
        "payroll_confirmed",
        {
            "period": period,
            "gross_pence": gross_pence,
            "er_ni_pence": er_ni_pence,
            "events": run.event_ids,
            "est_gross_pence": run.est_gross_pence,
            "est_er_ni_pence": run.est_er_ni_pence,
        },
    )
    await books.rebuild_safely(f"user:{user}")
    return run


async def reopen(books: Books, period: str, user: str) -> PayRun:
    """Undo the confirm: reverse its ledger entries and put the run back to draft."""
    from app.approve import ProposalStateError, undo

    run = await get_run(books, period)
    if run.status != "confirmed":
        raise PayrollConflict(f"The {period} pay run isn't confirmed")
    for event_id in run.event_ids:
        try:
            await undo(books, event_id, user)  # ApprovalError (e.g. a matched bank line) stops here
        except (ProposalStateError, FileNotFoundError):
            pass  # already undone by hand, or never written
    run = run.model_copy(
        update={
            "status": "draft",
            "confirmed_gross_pence": None,
            "confirmed_er_ni_pence": None,
            "confirmed_by": None,
            "confirmed_at": None,
            "event_ids": [],
            "undone_event_ids": [*run.undone_event_ids, *run.event_ids],
        }
    )
    await _save(books, run)
    await books.audit(f"user:{user}", "payroll_reopened", {"period": period, "undone": run.undone_event_ids})
    await books.rebuild_safely(f"user:{user}")
    return run
