"""Repeating invoices and bills: a schedule that makes a draft (or, if the user ticked "approve automatically", an
approved item) each time it comes round.

Files, in the user's folder:

    _System/Repeating/RP-0001.json       one template: the schedule and the invoice or bill it makes
    _System/Repeating/sequence.json      {"prefix": "RP-", "next": 2}

No background servers. There is nothing of ours running for a user between visits, so a schedule is only worked
through when something asks: opening the Sales, Purchases or Repeating page in the app, or a call to
`POST /repeating/process` (anything that can make an HTTP call with the user's token can do that on a timer, e.g. a
Power Automate flow). Each call makes every occurrence that has come due since the last one (at most 12 per template
per call; the rest on the next), dated on its scheduled day, not on the day it was worked out.

Schedule: weekly, monthly, quarterly or yearly, every N of them, from a start date to an optional end date. Months are
counted from the start date, never from the previous run, so the 31st goes 31 Jan, 28 Feb, 31 Mar, 30 Apr and a 29
Feb yearly schedule falls on 28 Feb in other years, and neither drifts.

What an occurrence makes:
  * invoice: a draft invoice (app/invoicing.create_invoice), numbered from the usual sequence and priced by code. With
    "approve automatically" it is also emailed to the customer from the user's Outlook and posted, exactly as the Send
    button does; if it cannot be (no customer email, the mailbox token has no Mail.Send, the profile is incomplete) it
    stays a draft and says why. Sending an invoice cannot be taken back, so the tick is the user's standing approval.
  * bill: a proposal in Review (app/bills.py). With "approve automatically" it is approved in advance and posted by
    code, unless a check fails (then it waits in Review like any bill that needs a look).

Everything it does is in the audit log (`repeating_generated`, `repeating_problem`), and an item made on approval
carries `repeating:<template>` as the approver, so the books show it was the standing approval and not a click.

Each occurrence is claimed before it is made (a `pending` mark on the template, taken with the file's ETag), and
made under an identity derived from the template and the occurrence (the tag on the invoice, the id of the bill
proposal), so two tabs opening at once, or a run cut short, never make it twice.
"""

from __future__ import annotations

import calendar
import contextlib
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from accnomos_connectors.base import MailSender
from app import approve as approve_
from app import bills
from app import invoicing as inv_
from app.books import Books, now
from app.books import today as london_today
from app.invoicing import InvoiceCustomer, InvoiceDraft, InvoiceError, LineIn, price_lines
from app.items import EXPENSE_RE, load_items
from app.numbering import NUMBER_RE, allocate, safe_number
from app.paths import SYSTEM
from app.validation import LENIENT, Day, StrictBody

REPEATING = f"{SYSTEM}/Repeating"
SEQUENCE = f"{REPEATING}/sequence.json"
MAX_PER_RUN = 12  # occurrences one template makes in one call; a long-neglected schedule catches up over a few visits
KEEP_HISTORY = 24
Frequency = Literal["weekly", "monthly", "quarterly", "yearly"]
Kind = Literal["invoice", "bill"]
Outcome = Literal["draft", "sent", "proposed", "posted"]
MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #


def add_months(start: date, months: int) -> date:
    """`start` plus whole months, on the same day of the month or the month's last day if it is shorter."""
    y, m = divmod(start.year * 12 + start.month - 1 + months, 12)
    return date(y, m + 1, min(start.day, calendar.monthrange(y, m + 1)[1]))


def occurrence(start: date, frequency: Frequency, every: int, n: int) -> date:
    """The n-th occurrence (n = 0 is the start date itself), always counted from the start date."""
    if frequency == "weekly":
        return start + timedelta(weeks=every * n)
    return add_months(start, MONTHS[frequency] * every * n)


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #


class RepeatingIn(StrictBody):
    kind: Kind
    name: str | None = Field(None, max_length=80)  # a label for the list; the customer or supplier when blank
    frequency: Frequency
    every: int = Field(1, ge=1, le=52)
    start_date: Day  # the first occurrence
    end_date: Day | None = None  # no occurrence after this day
    approve_automatically: bool = False
    party: InvoiceCustomer  # the customer of an invoice, the supplier of a bill
    lines: list[LineIn] = Field(min_length=1, max_length=100)
    reference: str | None = Field(None, max_length=60)  # invoices: the customer's reference
    notes: str | None = Field(None, max_length=1000)  # invoices: printed on each one
    due_days: int | None = Field(None, ge=0, le=120)  # invoices: days to pay (None: the invoice profile's terms)
    account: str | None = Field(None, max_length=60)  # bills: the expense account to post to
    paused: bool = False

    @model_validator(mode="after")
    def _check(self) -> RepeatingIn:
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("The end date is before the start date")
        if self.account is not None and not EXPENSE_RE.fullmatch(self.account.strip()):
            raise ValueError('The expense account is a 5000-8999 account, e.g. "5000 Materials"')
        return self


class Generated(BaseModel):
    index: int
    date: date
    outcome: Outcome
    number: str | None = None  # the invoice
    proposal_id: str | None = None  # the bill
    note: str | None = None
    at: datetime = Field(default_factory=now)


class Pending(BaseModel):
    index: int
    date: date
    at: datetime = Field(default_factory=now)


class Template(RepeatingIn):
    id: str
    created_by: str
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    next_index: int = 0  # the occurrence to make next
    pending: Pending | None = None  # claimed, not yet recorded
    last_run_at: datetime | None = None
    last_error: str | None = None
    history: list[Generated] = []
    deleted_at: datetime | None = None  # stopped for good: kept on file so its history stays readable

    def next_run(self) -> date | None:
        """The day the next occurrence falls on; None once the schedule has finished."""
        d = occurrence(
            self.start_date, self.frequency, self.every, self.pending.index if self.pending else self.next_index
        )
        return None if self.end_date is not None and d > self.end_date else d

    def label(self) -> str:
        return self.name or self.party.name


class TemplateRow(Template):
    next_date: date | None = None
    finished: bool = False
    due_now: bool = False  # an occurrence is due and has not been made (it will be on the next visit)
    totals: tuple[int, int, int] = (0, 0, 0)  # net, VAT, total of one occurrence, in pence


def row(t: Template, today: date | None = None) -> TemplateRow:
    today = today or london_today()
    nxt = t.next_run()
    _, _, net, vat = price_lines(t.lines)
    return TemplateRow(
        **t.model_dump(),
        next_date=nxt,
        finished=nxt is None,
        due_now=bool(nxt and nxt <= today and not t.paused),
        totals=(net, vat, net + vat),
    )


def _path(tid: str) -> str:
    return f"{REPEATING}/{safe_number(tid)}.json"


async def get_template(books: Books, tid: str) -> Template:
    return Template.model_validate_json(await books.storage.read(_path(tid)), **LENIENT)


async def save_template(books: Books, t: Template) -> None:
    t.updated_at = now()
    await books.write_json(_path(t.id), t.model_dump(mode="json"))


async def list_templates(books: Books) -> list[Template]:
    files = [
        f
        for f in await books.list_files(REPEATING)
        if f.name.endswith(".json") and f.name != "sequence.json" and NUMBER_RE.fullmatch(f.name[:-5])
    ]
    out = [Template.model_validate_json(await books.storage.read(f.path), **LENIENT) for f in files]
    return sorted((t for t in out if t.deleted_at is None), key=lambda t: t.id)


async def create_template(books: Books, body: RepeatingIn, user: str) -> Template:
    price_lines(body.lines)  # a line that cannot be priced is refused before a number is used
    tid = await allocate(books, SEQUENCE, "RP-", _path)
    t = Template(id=tid, created_by=user, **body.model_dump())
    await save_template(books, t)
    await books.audit(f"user:{user}", "repeating_created", {"template": tid, "kind": t.kind})
    return t


async def update_template(books: Books, tid: str, body: RepeatingIn, user: str) -> Template:
    old = await get_template(books, tid)
    if body.kind != old.kind:
        raise InvoiceError("A repeating invoice cannot become a repeating bill: set up a new one")
    keep = old.model_dump(include={"id", "created_by", "created_at", "next_index", "pending", "last_run_at", "history"})
    t = Template(**keep, **body.model_dump())
    await save_template(books, t)
    which = (
        "repeating_paused"
        if body.paused and not old.paused
        else "repeating_resumed"
        if old.paused and not body.paused
        else "repeating_edited"
    )
    await books.audit(f"user:{user}", which, {"template": tid, "kind": t.kind})
    return t


async def delete_template(books: Books, tid: str, user: str) -> None:
    """Stop it for good. The invoices and bills it already made stay, and the number is not reused: the file is kept,
    marked deleted, so its history stays readable."""
    t = await get_template(books, tid)
    t.paused, t.deleted_at = True, now()
    await save_template(books, t)
    await books.audit(f"user:{user}", "repeating_deleted", {"template": tid, "kind": t.kind})


# --------------------------------------------------------------------------- #
# Working through the schedule
# --------------------------------------------------------------------------- #


class MadeNow(BaseModel):
    template: str
    kind: Kind
    date: date
    outcome: Outcome
    number: str | None = None
    proposal_id: str | None = None
    note: str | None = None


class ProcessResult(BaseModel):
    made: list[MadeNow]
    problems: list[str]
    more_due: int  # occurrences still due after the per-call limit (the next call makes them)


def actor_of(t: Template) -> str:
    return f"repeating:{t.id}"


def _tag(t: Template, index: int) -> str:
    return f"{t.id}#{index}"


async def _claim(books: Books, tid: str, index: int, when: date) -> bool:
    """Mark occurrence `index` as being made. False when another request already has (or has moved past) it."""
    won: dict[str, bool] = {"ok": False}

    def change(raw: dict) -> dict:
        t = Template.model_validate(raw, **LENIENT)
        won["ok"] = t.pending is None and t.next_index == index
        if won["ok"]:
            t.pending = Pending(index=index, date=when)
        return t.model_dump(mode="json")

    await books._update_json(_path(tid), {}, change)
    return won["ok"]


async def _finish(books: Books, tid: str, made: Generated) -> Template:
    out: dict[str, Template] = {}

    def change(raw: dict) -> dict:
        t = Template.model_validate(raw, **LENIENT)
        t.next_index, t.pending, t.last_run_at = made.index + 1, None, now()
        t.last_error = made.note if made.outcome in ("draft", "proposed") and made.note else None
        t.history = [*t.history, made][-KEEP_HISTORY:]
        t.updated_at = now()
        out["t"] = t
        return t.model_dump(mode="json")

    await books._update_json(_path(tid), {}, change)
    return out["t"]


async def _make_invoice(books: Books, sender: MailSender | None, t: Template, index: int, when: date) -> Generated:
    profile = await inv_.load_profile(books)
    tag = _tag(t, index)
    existing = next((i for i in await inv_.list_invoices(books) if i.repeating == tag), None)
    if existing is None:
        draft = InvoiceDraft(
            customer=t.party,
            issue_date=when,
            due_date=when + timedelta(days=t.due_days if t.due_days is not None else profile.terms_days),
            lines=t.lines,
            reference=t.reference,
            notes=t.notes,
            job_id=None,
        )
        existing = await inv_.create_invoice(books, draft, t.created_by)
        existing.repeating = tag
        await inv_.save_invoice(books, existing)
    inv = existing
    outcome: Outcome = "sent" if inv.status == "sent" else "draft"
    note = None
    if t.approve_automatically and inv.status == "draft":
        if sender is None:
            note = "Not sent: no way to send mail from this call"
        elif problems := inv_.send_problems(inv, profile, inv.customer.email):
            note = "Not sent: " + "; ".join(problems)
        else:
            from app.pdf import render_invoice

            try:
                pdf = render_invoice(inv, profile, await inv_.load_logo(books, profile))
                await inv_.send_invoice(books, sender, inv.number, actor_of(t), pdf)
            except Exception as exc:  # noqa: BLE001  a mail or storage failure must not lose the draft
                note = f"Not sent: {str(exc)[:200]}"
            inv = await inv_.get_invoice(books, inv.number)
            outcome = "sent" if inv.status == "sent" else "draft"
    return Generated(index=index, date=when, outcome=outcome, number=inv.number, note=note)


async def _make_bill(books: Books, t: Template, index: int, when: date) -> Generated:
    accounts = {i.code: i.expense_account for i in await load_items(books)}
    account = t.account or bills.dominant_account(t.lines, accounts)
    p = await bills.make_bill_proposal(
        books,
        pid=bills.proposal_id("repeating", t.id, str(index)),
        evidence=f"repeating:{t.id}:{index}",
        source=f"Repeating bill {t.id}",
        note=f"Made by code from repeating bill {t.id}, occurrence for {when:%d/%m/%Y}.",
        supplier_name=t.party.name,
        contact_id=t.party.contact_id,
        supplier_vat_number=t.party.vrn,
        bill_date=when,
        lines=t.lines,
        account=account,
        model="code:repeating",
    )
    outcome: Outcome = "posted" if p.status == "posted" else "proposed"
    note = None
    if t.approve_automatically and p.status == "proposed":
        try:
            p = await approve_.approve(books, p.id, actor_of(t))
            outcome = "posted"
        except approve_.ApprovalError as exc:
            note = f"Waiting in Review: {exc}"
    elif t.approve_automatically and p.status == "needs_a_look":
        note = "Waiting in Review: a check needs a look (" + "; ".join(p.reasons)[:160] + ")"
    return Generated(index=index, date=when, outcome=outcome, proposal_id=p.id, note=note)


async def run_template(
    books: Books, t: Template, sender: MailSender | None, today: date, budget: int = MAX_PER_RUN
) -> tuple[list[MadeNow], list[str], int]:
    """Make every occurrence of `t` that is due on or before `today` (at most `budget`). (made, problems, still due)."""
    made: list[MadeNow] = []
    problems: list[str] = []
    while True:
        t = await get_template(books, t.id)
        if t.paused:
            return made, problems, 0
        index = t.pending.index if t.pending else t.next_index
        when = t.pending.date if t.pending else t.next_run()
        if when is None or when > today:
            return made, problems, 0
        if len(made) >= budget:
            return made, problems, _count_due(t, index, today)
        if t.pending is None and not await _claim(books, t.id, index, when):
            return made, problems, 0  # someone else is making it
        try:
            g = await (
                _make_invoice(books, sender, t, index, when)
                if t.kind == "invoice"
                else _make_bill(books, t, index, when)
            )
        except InvoiceError as exc:
            msg = f"{t.id} for {when:%d/%m/%Y}: {exc}"
            problems.append(msg)
            await books.audit(
                "agent:repeating", "repeating_problem", {"template": t.id, "date": when.isoformat(), "error": str(exc)}
            )
            await _record_error(books, t.id, str(exc))
            return made, problems, 0  # stays claimed: the same occurrence is tried again on the next call
        await _finish(books, t.id, g)
        what = f"invoice {g.number}" if g.number else "a bill for review"
        await books.audit(
            "agent:repeating",
            "repeating_generated",
            {
                "template": t.id,
                "kind": t.kind,
                "date": when.isoformat(),
                "outcome": g.outcome,
                "what": what,
                "invoice": g.number,
                "proposal": g.proposal_id,
                "approve_automatically": t.approve_automatically,
                "created_by": t.created_by,
                "note": g.note,
            },
        )
        made.append(
            MadeNow(
                template=t.id,
                kind=t.kind,
                date=when,
                outcome=g.outcome,
                number=g.number,
                proposal_id=g.proposal_id,
                note=g.note,
            )
        )


def _count_due(t: Template, first: int, today: date) -> int:
    """How many occurrences from `first` on are due on or before `today`."""
    n = 0
    while (d := occurrence(t.start_date, t.frequency, t.every, first + n)) <= today and (
        t.end_date is None or d <= t.end_date
    ):
        n += 1
    return n


async def _record_error(books: Books, tid: str, message: str) -> None:
    def change(raw: dict) -> dict:
        t = Template.model_validate(raw, **LENIENT)
        t.last_error = message[:300]
        return t.model_dump(mode="json")

    with contextlib.suppress(Exception):
        await books._update_json(_path(tid), {}, change)


async def process_due(books: Books, sender: MailSender | None, today: date | None = None) -> ProcessResult:
    """Work through every template: make what has come due. Safe to call as often as you like."""
    today = today or london_today()
    made: list[MadeNow] = []
    problems: list[str] = []
    more = 0
    for t in await list_templates(books):
        if t.paused:
            continue
        m, p, left = await run_template(books, t, sender, today)
        made += m
        problems += p
        more += left
    return ProcessResult(made=made, problems=problems, more_due=more)
