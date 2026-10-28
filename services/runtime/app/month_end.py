"""The month-end close agent: one button, "Close October", works through the close checklist.

The agent loop is plain code, one step after another, each one reported as it finishes (docs/ARCHITECTURE.md,
"The month-end close"):

    1 Inbox      documents still waiting in 00 Inbox or Review for the month; Outlook (a dry run) if intake is on
    2 Bank       statement coverage (gaps between imported statements, balance jumps), unreconciled lines,
                 matches suggested by code offered as approve cards
    3 Sales      overdue invoices -> reminder cards (words by the user's AI, figures by code); drafts not sent
    4 Purchases  bills due, supplier credits not applied
    5 Payroll    the month's pay run, if payroll is used
    6 VAT        if the month ends a VAT period: the 9 boxes, the digital-links trail, the deadline; never submitted
    7 Checks     uncategorised (7999 Sundry) and uncoded balances, duplicates, negative bank balances, unusual postings
    8 Reports    the month's P&L and balance sheet saved as a draft in 07 Reports, once nothing blocks the close
    9 Lock       "Mark October closed": an approve card; approving records a close event with a snapshot hash

Each step ends `ok`, `needs_you` or `blocked` with one plain-English reason and a link. A step that cannot run says
what is missing and how to fix it (never a silent skip, never an invented figure). Findings are `blocking` (the
month's figures are incomplete or wrong until it is dealt with), `needs_you` (worth doing, does not stop the close)
or `note`.

**The agent posts nothing.** It reads the books; the only files a run writes are its own record
(`_System/close/<yyyy-mm>.json`, the last RUNS_KEPT runs), one `close_run` audit line, and (step 8) the draft
report. Everything else is a card that waits for Approve through POST /actions/approve (app/actions.py: signed,
15-minute expiry, executed once): `chase_invoice`, `match_bank_line`, `close_month`. Approving `close_month`
recomputes the month's snapshot and refuses if it differs from the one on the card.

**After close.** The snapshot covers every ledger event and bank line dated in the month and the month's P&L and
VAT figures. If anything dated in a closed month changes later (a late receipt approved, a bank line imported or
matched, an undo dated in the month), the snapshot no longer matches: GET /close and GET /close/{month} say so with
the before/after figures, and running the close again offers a re-close, which records a new close event and new
reports. Corrections to a VAT period already submitted keep following app/approve.py (Undo dates them today).
"""

from __future__ import annotations

import calendar
import hashlib
import json
import logging
import re
import statistics
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from accnomos_connectors.base import MailProvider
from accnomos_ledger import LedgerEvent, compute_vat_return
from accnomos_ledger.bank import BankLine
from app import actions
from app import contacts as cb
from app import reports as rp
from app.ai import close_summary
from app.ai.config import AiConfig
from app.autopilot import supplier_key
from app.books import SYSTEM, Books, bank_of, now
from app.books import today as london_today
from app.checks import parse_iso_date
from app.deadlines import add_months, filing_deadline, period_containing, period_id
from app.deadlines import period_label as vat_label
from app.journal import SUNDRY
from app.paths import BANK, INBOX, REPORTS, upgrade
from app.schemas import Clarification, ProposedAction
from app.vat_cycle import VatCycle

log = logging.getLogger(__name__)

CLOSE = f"{SYSTEM}/close"
ACTOR = "agent:close"
RUNS_KEPT = 10
GAP_DAYS = 3  # up to this many days without a statement at a month edge or between two statements: no transactions
DORMANT_DAYS = 60  # a bank whose last statement ended this long before the month: not checked, and said so
UNUSUAL_TIMES = 3  # a purchase more than this many times the supplier's usual (median) amount
UNUSUAL_MIN_PENCE = 10_000  # ... and at least £100 over it
DUE_SOON_DAYS = 7
MAX_BANK_CARDS = 10
MAX_CHASE_CARDS = 5
MONTH_RE = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
SETTINGS, INVOICES = "/settings", "/invoices"  # web paths; the phone maps them to its own screens

StepId = Literal["inbox", "bank", "sales", "purchases", "payroll", "vat", "checks", "reports", "lock"]
StepStatus = Literal["ok", "needs_you", "blocked"]
Level = Literal["blocking", "needs_you", "note"]
STEPS: list[tuple[StepId, str]] = [
    ("inbox", "Inbox"),
    ("bank", "Bank"),
    ("sales", "Sales"),
    ("purchases", "Purchases"),
    ("payroll", "Payroll"),
    ("vat", "VAT"),
    ("checks", "Checks"),
    ("reports", "Reports"),
    ("lock", "Lock"),
]


class CloseError(ValueError):
    """The month cannot be closed (or run) as asked."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def money(pence: int) -> str:
    return actions.money(pence)


def day(d: date) -> str:
    """'3 Oct'."""
    return f"{d.day} {calendar.month_abbr[d.month]}"


def span(a: date, b: date) -> str:
    """'12–31 Oct', '28 Sep–3 Oct', '12 Oct'."""
    if a == b:
        return day(a)
    if a.month == b.month:
        return f"{a.day}–{b.day} {calendar.month_abbr[b.month]}"
    return f"{day(a)}–{day(b)}"


def month_bounds(month: str) -> tuple[date, date]:
    if not MONTH_RE.fullmatch(month or ""):
        raise CloseError(f"{month!r} is not a month like 2026-10", 422)
    y, m = int(month[:4]), int(month[5:])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def month_label(month: str) -> str:
    start, _ = month_bounds(month)
    return f"{calendar.month_name[start.month]} {start.year}"


def month_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def previous_month(today: date) -> str:
    return month_of(date(today.year, today.month, 1) - timedelta(days=1))


def check_month(month: str, today: date) -> tuple[date, date]:
    start, end = month_bounds(month)
    if start > today:
        raise CloseError(f"{month_label(month)} has not started yet", 422)
    if start < add_months(date(today.year, today.month, 1), -36):
        raise CloseError("Only the last 36 months can be closed here", 422)
    return start, end


def record_path(month: str) -> str:
    month_bounds(month)  # validates, so nothing but yyyy-mm reaches a path
    return f"{CLOSE}/{month}.json"


def draft_report_path(month: str) -> str:
    return f"{REPORTS}/{month}-month-end-draft.xlsx"


def _live(events: list[LedgerEvent]) -> list[LedgerEvent]:
    undone = {e.reverses for e in events if e.reverses}
    return [e for e in events if e.kind != "reversal" and e.id not in undone]


def gross_of(e: LedgerEvent) -> int:
    return sum(ln.debit for ln in e.lines)


# --------------------------------------------------------------------------- #
# What a run reports
# --------------------------------------------------------------------------- #


class Finding(BaseModel):
    text: str  # plain English, figures already formatted by code
    level: Level = "needs_you"
    link: str | None = None
    refs: dict[str, Any] = Field(default_factory=dict)  # ids: invoice, line, event, bank, ...

    @property
    def counts(self) -> bool:
        return self.level != "note"


class Step(BaseModel):
    id: StepId
    n: int
    title: str
    status: StepStatus
    reason: str  # one sentence: what was found, or what is missing and how to fix it
    link: str | None = None
    checked: list[str] = Field(default_factory=list)  # what the step looked at
    found: list[Finding] = Field(default_factory=list)
    proposes: list[str] = Field(default_factory=list)  # ids of the cards this step proposes
    data: dict[str, Any] = Field(default_factory=dict)  # step-specific figures (VAT boxes, coverage, report path)
    ms: int = 0

    @property
    def blocking(self) -> int:
        return sum(f.level == "blocking" for f in self.found)

    @property
    def needs_you(self) -> int:
        return sum(f.counts for f in self.found)


class CardRef(BaseModel):
    id: str
    kind: str
    summary_md: str


class EventRow(BaseModel):
    id: str
    date: date
    kind: str
    counterparty: str | None
    gross_pence: int
    approved_at: datetime
    reverses: str | None = None
    credit_note: bool = False


class BankRow(BaseModel):
    id: str
    date: date
    amount_pence: int
    description: str
    status: str
    bank: str


class Figures(BaseModel):
    sales_pence: int
    cost_of_sales_pence: int
    gross_profit_pence: int
    overheads_pence: int
    net_profit_pence: int
    accounts: dict[str, int]  # P&L account -> amount for the month
    vat: dict[str, str]  # box "1".."9" -> amount for the month's entries alone (pounds, as on the VAT page)


class Snapshot(BaseModel):
    month: str
    events: list[EventRow]
    bank: list[BankRow]
    figures: Figures
    hash: str = ""


class FigureChange(BaseModel):
    label: str
    before: str
    after: str


class Changes(BaseModel):
    closed_at: datetime
    closed_by: str
    count: int
    items: list[str]  # one plain-English sentence per change
    figures: list[FigureChange]  # P&L lines and VAT boxes that moved
    vat_note: str | None = None
    headline: str


class CloseRecord(BaseModel):
    id: str
    month: str
    closed_at: datetime
    closed_by: str
    snapshot_hash: str
    snapshot: Snapshot
    run_id: str | None = None
    action_id: str | None = None
    report_path: str | None = None
    reclose: bool = False
    changes_since_previous: list[str] = Field(default_factory=list)


class StoredRun(BaseModel):
    id: str
    month: str
    label: str
    started_at: datetime
    finished_at: datetime
    by: str
    steps: list[Step]
    cards: list[CardRef] = Field(default_factory=list)
    summary_md: str
    summary_model: str
    summary_fallback_reason: str | None = None
    needs_you: int
    blocking: int
    can_close: bool
    snapshot_hash: str


class CloseRun(StoredRun):
    """What POST /close/{month}/run returns: the stored run plus the signed cards (kept by the app only)."""

    actions: list[ProposedAction] = Field(default_factory=list)
    changes: Changes | None = None


class MonthFile(BaseModel):
    month: str
    runs: list[StoredRun] = Field(default_factory=list)  # newest last
    closes: list[CloseRecord] = Field(default_factory=list)  # oldest first


# --------------------------------------------------------------------------- #
# Snapshot of a month and what changed since
# --------------------------------------------------------------------------- #


def _hash(snap: Snapshot) -> str:
    body = json.dumps(snap.model_dump(mode="json", exclude={"hash"}), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def snapshot_from(events: list[LedgerEvent], lines: list[BankLine], month: str) -> Snapshot:
    """Every event and bank line dated in the month, and the month's P&L and VAT, with a hash over all of it."""
    from app.routes_vat import box_amounts  # routes_vat imports the route layer; only needed here

    start, end = month_bounds(month)
    inside = [e for e in events if start <= e.date <= end]
    pl = rp.profit_and_loss(inside, start, end)
    ret = compute_vat_return(inside, "", start, end)
    accounts = {r.account: r.amount_pence for sec in (pl.sales, pl.cost_of_sales, pl.overheads) for r in sec.rows}
    snap = Snapshot(
        month=month,
        events=sorted(
            (
                EventRow(
                    id=e.id,
                    date=e.date,
                    kind=e.kind,
                    counterparty=e.counterparty,
                    gross_pence=gross_of(e),
                    approved_at=e.approved_at,
                    reverses=e.reverses,
                    credit_note=e.is_credit_note,
                )
                for e in inside
            ),
            key=lambda r: (r.date, r.id),
        ),
        bank=sorted(
            (
                BankRow(
                    id=ln.id,
                    date=ln.date,
                    amount_pence=ln.amount_pence,
                    description=ln.description[:120],
                    status=ln.status,
                    bank=bank_of(upgrade(ln.source_file)),
                )
                for ln in lines
                if start <= ln.date <= end
            ),
            key=lambda r: (r.date, r.id),
        ),
        figures=Figures(
            sales_pence=pl.sales.total_pence,
            cost_of_sales_pence=pl.cost_of_sales.total_pence,
            gross_profit_pence=pl.gross_profit_pence,
            overheads_pence=pl.overheads.total_pence,
            net_profit_pence=pl.net_profit_pence,
            accounts=accounts,
            vat={str(k): v for k, v in box_amounts(ret).items()},
        ),
    )
    snap.hash = _hash(snap)
    return snap


async def snapshot(books: Books, month: str) -> Snapshot:
    start, end = month_bounds(month)
    return snapshot_from(await books.list_events(start, end), await books.stored_bank_lines(), month)


_KIND_WORDS = {"purchase": "a purchase", "sale": "a sale", "bank": "a payment", "adjustment": "an adjustment"}


def _event_words(e: EventRow, by_id: dict[str, EventRow]) -> str:
    if e.kind == "reversal" and e.reverses:
        orig = by_id.get(e.reverses)
        what = f"the entry for {orig.counterparty or 'an entry'}" if orig else "an entry"
        return f"{what} was undone ({money(e.gross_pence)}, dated {day(e.date)})"
    what = "a credit note" if e.credit_note else _KIND_WORDS.get(e.kind, "an entry")
    who = f" {'to' if e.kind == 'sale' else 'from'} {e.counterparty}" if e.counterparty else ""
    return f"{what}{who} for {money(e.gross_pence)} dated {day(e.date)} was approved on {day(e.approved_at.date())}"


def diff(before: Snapshot, after: Snapshot) -> tuple[list[str], list[FigureChange]]:
    """(sentences, figure changes) from one snapshot of a month to another."""
    items: list[str] = []
    old_ev, new_ev = {e.id: e for e in before.events}, {e.id: e for e in after.events}
    every = {**old_ev, **new_ev}
    for e in after.events:
        if e.id not in old_ev:
            words = _event_words(e, every)
            items.append(words[0].upper() + words[1:])
    for e in before.events:
        if e.id not in new_ev:
            who = e.counterparty or "an entry"
            items.append(f"The entry for {who} ({money(e.gross_pence)}) is no longer in the ledger")
    old_bk, new_bk = {b.id: b for b in before.bank}, {b.id: b for b in after.bank}
    for b in after.bank:
        was = old_bk.get(b.id)
        if was is None:
            items.append(f"A {b.bank} bank line of {money(b.amount_pence)} on {day(b.date)} was imported")
        elif was.status != b.status:
            line = f"The {b.bank} bank line of {money(b.amount_pence)} on {day(b.date)}"
            items.append(f"{line} is now {b.status} (was {was.status})")
    for b in before.bank:
        if b.id not in new_bk:
            items.append(f"The {b.bank} bank line of {money(b.amount_pence)} on {day(b.date)} is no longer stored")
    figures: list[FigureChange] = []
    fb, fa = before.figures, after.figures
    for label, attr in (
        ("Sales", "sales_pence"),
        ("Cost of sales", "cost_of_sales_pence"),
        ("Gross profit", "gross_profit_pence"),
        ("Overheads", "overheads_pence"),
        ("Net profit", "net_profit_pence"),
    ):
        a, b = getattr(fb, attr), getattr(fa, attr)
        if a != b:
            figures.append(FigureChange(label=label, before=money(a), after=money(b)))
    for acct in sorted(set(fb.accounts) | set(fa.accounts)):
        a, b = fb.accounts.get(acct, 0), fa.accounts.get(acct, 0)
        if a != b:
            figures.append(FigureChange(label=acct, before=money(a), after=money(b)))
    for box in [str(i) for i in range(1, 10)]:
        a, b = fb.vat.get(box, "0"), fa.vat.get(box, "0")
        if a != b:
            figures.append(FigureChange(label=f"VAT box {box} (this month's entries)", before=f"£{a}", after=f"£{b}"))
    return items, figures


async def _vat_submitted(books: Books, month: str) -> str | None:
    """The submitted VAT period the month falls in, as 'Jul–Sep 2026', or None."""
    from app.routes_vat import read_obligations, submitted_periods

    start, end = month_bounds(month)
    spans = list((await submitted_periods(books)).keys())
    spans += [(o.start, o.end) for o in await read_obligations(books) if o.status == "F"]
    hit = next(((s, e) for s, e in spans if s <= start and end <= e), None)
    return vat_label(*hit) if hit else None


async def changes_since_close(books: Books, record: MonthFile, now_snap: Snapshot) -> Changes | None:
    if not record.closes:
        return None
    last = record.closes[-1]
    if last.snapshot_hash == now_snap.hash:
        return None
    items, figures = diff(last.snapshot, now_snap)
    submitted = await _vat_submitted(books, record.month)
    vat_note = (
        f"Your VAT return for {submitted} was already submitted, so these changes are not on it. Undo dates a "
        "correction today, in the open period; anything else needs HMRC's error-correction rules, which Accnomos "
        "does not handle."
        if submitted
        else None
    )
    label = month_label(record.month)
    n = len(items) or 1
    headline = (
        f"{label.split()[0]} was closed on {day(last.closed_at.date())}; {n} change{'s' if n != 1 else ''} since: "
        + "; ".join(items[:2])
        + ("…" if len(items) > 2 else "")
        + " — re-close?"
    )
    return Changes(
        closed_at=last.closed_at,
        closed_by=last.closed_by,
        count=n,
        items=items or ["The month's figures changed since it was closed"],
        figures=figures,
        vat_note=vat_note,
        headline=headline,
    )


# --------------------------------------------------------------------------- #
# The record file
# --------------------------------------------------------------------------- #


async def load_record(books: Books, month: str) -> MonthFile:
    raw = await books.read_json(record_path(month), None)
    if not isinstance(raw, dict):
        return MonthFile(month=month)
    try:
        return MonthFile.model_validate(raw)
    except ValueError:
        log.warning("close record for %s could not be read; treated as empty", month)
        return MonthFile(month=month)


async def _update_record(books: Books, month: str, change: Callable[[MonthFile], MonthFile]) -> None:
    def apply(obj: Any) -> Any:
        try:
            current = MonthFile.model_validate(obj) if isinstance(obj, dict) and obj else MonthFile(month=month)
        except ValueError:
            current = MonthFile(month=month)
        return change(current).model_dump(mode="json")

    await books._update_json(record_path(month), {}, apply)


async def recorded_months(books: Books) -> list[str]:
    """Months with a close record (a run or a close) in _System/close/."""
    return sorted(
        f.name.removesuffix(".json")
        for f in await books.list_files(CLOSE)
        if f.name.endswith(".json") and MONTH_RE.fullmatch(f.name.removesuffix(".json"))
    )


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


@dataclass
class Ctx:
    books: Books
    month: str
    today: date
    cycle: VatCycle
    user: str
    token: str | None = None  # signs the cards; None: findings only
    cfg: AiConfig | None = None
    mail: MailProvider | None = None  # Outlook intake is on and the token can read mail
    outlook: bool = False  # the app says intake is on
    cards: list[ProposedAction] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    _ledger: cb.Ledger | None = None

    @property
    def start(self) -> date:
        return month_bounds(self.month)[0]

    @property
    def end(self) -> date:
        return month_bounds(self.month)[1]

    @property
    def label(self) -> str:
        return month_label(self.month)

    @property
    def short(self) -> str:
        return calendar.month_name[self.start.month]

    @property
    def ended(self) -> bool:
        return self.end < self.today

    async def ledger(self) -> cb.Ledger:
        if self._ledger is None:
            self._ledger = await cb.load_ledger(self.books)
        return self._ledger

    def in_month(self, d: date) -> bool:
        return self.start <= d <= self.end

    def card(self, draft: actions.Draft) -> ProposedAction | None:
        if self.token is None:
            return None
        action = actions.new_action(draft, self.token)
        self.cards.append(action)
        return action

    def blocking_so_far(self) -> int:
        return sum(s.blocking for s in self.steps)


def _status(found: list[Finding]) -> StepStatus:
    return "needs_you" if any(f.counts for f in found) else "ok"


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else many or one + 's'}"


# ---- 1 Inbox ----------------------------------------------------------------


async def step_inbox(ctx: Ctx) -> Step:
    books = ctx.books
    files = [f for f in await books.list_files(INBOX) if not f.name.startswith(".")]
    waiting = [p for p in await books.list_proposals() if p.status in ("proposed", "needs_a_look")]
    dated: list[Any] = []
    undated: list[Any] = []
    for p in waiting:
        d = parse_iso_date(p.extracted.date)
        if d is None:
            undated.append(p)
        elif ctx.in_month(d):
            dated.append(p)
    found: list[Finding] = []
    if files:
        found.append(
            Finding(
                text=f"{_plural(len(files), 'document')} in {INBOX} not read yet; they may be dated in "
                f"{ctx.short}. Scan them on Review.",
                level="blocking",
                link="/review",
                refs={"files": [f.name for f in files[:20]]},
            )
        )
    if dated:
        looks = sum(p.status == "needs_a_look" for p in dated)
        found.append(
            Finding(
                text=f"{_plural(len(dated), 'document')} dated in {ctx.short} waiting on Review"
                + (f" ({looks} in Needs a look)" if looks else "")
                + ": approve or reject them.",
                level="blocking",
                link="/review",
                refs={"proposals": [p.id for p in dated[:50]]},
            )
        )
    if undated:
        found.append(
            Finding(
                text=f"{_plural(len(undated), 'document')} on Review with no readable date: check whether "
                f"{'it belongs' if len(undated) == 1 else 'they belong'} to {ctx.short}.",
                level="needs_you",
                link="/review",
                refs={"proposals": [p.id for p in undated[:50]]},
            )
        )
    checked = [
        f"{INBOX}: {_plural(len(files), 'file')}",
        f"Review: {len(waiting)} waiting, {len(dated)} dated in {ctx.short}",
    ]
    if not ctx.outlook:
        checked.append("Outlook: not checked (Outlook intake is off in Settings)")
        found.append(
            Finding(
                text="Outlook intake is off, so your mailbox was not checked for receipts.",
                level="note",
                link="/settings",
            )
        )
    elif ctx.mail is None:
        checked.append("Outlook: not checked (no mailbox access)")
        found.append(
            Finding(text="Outlook could not be checked: sign in again with mail access.", level="note", link=SETTINGS)
        )
    else:
        from app.intake import scan_mail

        since = min(90, max(1, (ctx.today - ctx.start).days + 1))
        try:
            res = await scan_mail(books, ctx.mail, since_days=since, dry_run=True, user=ctx.user)
            checked.append(f"Outlook: {res.scanned} messages since {day(ctx.start)} (a dry run: nothing copied)")
            if res.items:
                found.append(
                    Finding(
                        text=f"{_plural(len(res.items), 'likely receipt')} in Outlook not copied into {INBOX} yet: "
                        "copy them with Check now in Settings › Outlook, then scan.",
                        level="needs_you",
                        link="/settings",
                        refs={"subjects": [i.subject[:80] for i in res.items[:10]]},
                    )
                )
        except Exception as exc:  # noqa: BLE001  a mailbox problem must not stop the close
            checked.append("Outlook: could not be read")
            found.append(
                Finding(
                    text=f"Outlook could not be checked ({type(exc).__name__}); sign in again with mail access.",
                    level="note",
                    link="/settings",
                )
            )
    reason = (
        f"Nothing for {ctx.short} is waiting in {INBOX} or on Review."
        if not any(f.counts for f in found)
        else found[0].text
    )
    return Step(
        id="inbox",
        n=1,
        title="Inbox",
        status=_status(found),
        reason=reason,
        link="/review",
        checked=checked,
        found=found,
    )


# ---- 2 Bank -----------------------------------------------------------------


def opening_balance(lines: list[BankLine]) -> int | None:
    """The balance before the first line: on the first day, the line no other line's balance leads into."""
    dated = [ln for ln in lines if ln.balance_pence is not None]
    if not dated:
        return None
    first = min(ln.date for ln in dated)
    day_lines = [ln for ln in dated if ln.date == first]
    closings = {ln.balance_pence for ln in day_lines}
    for ln in day_lines:
        opening = ln.balance_pence - ln.amount_pence  # type: ignore[operator]
        if opening not in closings:
            return opening
    return day_lines[0].balance_pence - day_lines[0].amount_pence  # type: ignore[operator]


def coverage_gaps(
    spans: list[tuple[date, date]], start: date, end: date, slack: int = GAP_DAYS
) -> list[tuple[date, date]]:
    """Runs of days in [start, end] no statement covers, longer than `slack` days."""
    gaps: list[tuple[date, date]] = []
    cursor = start
    for s, e in sorted(spans):
        if e < start or s > end:
            continue
        s, e = max(s, start), min(e, end)
        if (s - cursor).days > slack:
            gaps.append((cursor, s - timedelta(days=1)))
        cursor = max(cursor, e + timedelta(days=1))
    if cursor <= end and (end - cursor).days + 1 > slack:
        gaps.append((cursor, end))
    return gaps


async def step_bank(ctx: Ctx) -> Step:
    from app.dashboard import closing_line

    ledger = await ctx.ledger()
    lines = ledger.bank_lines
    upto = min(ctx.end, ctx.today)
    if not lines:
        return Step(
            id="bank",
            n=2,
            title="Bank",
            status="needs_you",
            reason=f"No bank statements imported yet: upload {ctx.short}'s statement (CSV) on Bank.",
            link="/bank",
            checked=[f"{BANK}: none imported"],
            found=[
                Finding(
                    text=f"No bank statement for {ctx.label}: download it from your bank as CSV and upload it on Bank.",
                    level="blocking",
                    link="/bank",
                )
            ],
        )
    by_bank: dict[str, dict[str, list[BankLine]]] = defaultdict(lambda: defaultdict(list))
    for ln in lines:
        path = upgrade(ln.source_file)
        by_bank[bank_of(path)][path].append(ln)
    found: list[Finding] = []
    checked: list[str] = []
    coverage: dict[str, Any] = {}
    for bank, files in sorted(by_bank.items()):
        spans = sorted((min(x.date for x in ls), max(x.date for x in ls), path) for path, ls in files.items())
        last_end = max(e for _, e, _ in spans)
        if last_end < ctx.start - timedelta(days=DORMANT_DAYS):
            checked.append(f"{bank}: last statement ends {day(last_end)} {last_end.year}; not checked")
            found.append(
                Finding(
                    text=f"{bank}: the last statement ends on {day(last_end)} {last_end.year}, so it was not checked "
                    f"for {ctx.short}. If the account is still open, upload its statements.",
                    level="note",
                    link="/bank",
                )
            )
            continue
        gaps = coverage_gaps([(s, e) for s, e, _ in spans], ctx.start, upto)
        coverage[bank] = {
            "statements": [{"path": p, "from": s.isoformat(), "to": e.isoformat()} for s, e, p in spans],
            "gaps": [{"from": a.isoformat(), "to": b.isoformat()} for a, b in gaps],
        }
        in_month = [x for ls in files.values() for x in ls if ctx.in_month(x.date)]
        checked.append(f"{bank}: {_plural(len(spans), 'statement')}, {_plural(len(in_month), 'line')} in {ctx.short}")
        for a, b in gaps:
            found.append(
                Finding(
                    text=f"Bank statement missing for {span(a, b)} ({bank}): upload it on Bank.",
                    level="blocking",
                    link="/bank",
                    refs={"bank": bank, "from": a.isoformat(), "to": b.isoformat()},
                )
            )
        # Consecutive statements whose balances do not join up: lines are missing between them.
        ordered = sorted(files.items(), key=lambda kv: (min(x.date for x in kv[1]), kv[0]))
        for (p1, l1), (p2, l2) in zip(ordered, ordered[1:], strict=False):
            first2 = min(x.date for x in l2)
            if not (ctx.start - timedelta(days=31) <= first2 <= upto):
                continue
            close1, open2 = closing_line(l1), opening_balance(l2)
            if close1 is None or close1.balance_pence is None or open2 is None or close1.date > first2:
                continue
            if close1.balance_pence != open2:
                found.append(
                    Finding(
                        text=f"{bank}: the balance is {money(close1.balance_pence)} at the end of the statement to "
                        f"{day(close1.date)} but {money(open2)} at the start of the next one ({day(first2)}): lines "
                        "are missing between them. Upload the statement for the days in between.",
                        level="blocking",
                        link="/bank",
                        refs={"bank": bank, "before": p1, "after": p2},
                    )
                )
    month_lines = [ln for ln in lines if ctx.in_month(ln.date)]
    open_lines = [ln for ln in month_lines if not ln.resolved]
    suggestions = {m.line_id: m for m in await ctx.books.bank_suggestions(lines)} if open_lines else {}
    events = {e.id: e for e in ledger.events}
    carded = 0
    no_match: list[BankLine] = []
    for ln in sorted(open_lines, key=lambda x: (x.date, x.id)):
        m = suggestions.get(ln.id)
        if m is None or carded >= MAX_BANK_CARDS:
            no_match.append(ln)
            continue
        evs = [events[i] for i in m.event_ids if i in events]
        to = (
            ", ".join(f"{e.counterparty or 'entry'} {money(gross_of(e))} ({day(e.date)})" for e in evs)
            or "a ledger entry"
        )
        preview = {
            "month": ctx.month,
            "line_id": ln.id,
            "date": ln.date.isoformat(),
            "amount_pence": ln.amount_pence,
            "description": ln.description[:200],
            "bank": bank_of(upgrade(ln.source_file)),
            "event_ids": m.event_ids,
            "to": to,
            "match_kind": m.kind,
            "reasons": m.reasons[:4],
            "suggested_by": "code",
            "warnings": [],
        }
        summary = (
            f"**Match** the bank line **{money(ln.amount_pence)}** on {day(ln.date)} "
            f"(“{actions._md(ln.description[:80])}”) to **{actions._md(to)}**."
        )
        card = ctx.card(actions.Draft("match_bank_line", summary, preview, "Record this match (posts nothing)"))
        carded += 1
        found.append(
            Finding(
                text=f"Bank line {money(ln.amount_pence)} on {day(ln.date)} (“{ln.description[:60]}”) is not "
                f"reconciled; code suggests {to}.",
                level="blocking",
                link="/bank",
                refs={"line": ln.id, "card": card.id if card else None, "events": m.event_ids},
            )
        )
    if no_match:
        found.append(
            Finding(
                text=f"{_plural(len(no_match), 'bank line')} in {ctx.short} with no match: match, code or mark "
                "them on Bank.",
                level="blocking",
                link="/bank",
                refs={"lines": [x.id for x in no_match[:50]]},
            )
        )
    done = len(month_lines) - len(open_lines)
    checked.append(f"Reconciliation: {done} of {len(month_lines)} lines in {ctx.short} done")
    blocking = [f for f in found if f.level == "blocking"]
    if blocking:
        reason = blocking[0].text if len(blocking) == 1 else f"{blocking[0].text} ({len(blocking) - 1} more below)"
    elif month_lines:
        reason = f"Statements cover {ctx.short} and all {_plural(len(month_lines), 'line')} are reconciled."
    else:
        reason = f"Statements cover {ctx.short}; there were no transactions in it."
    return Step(
        id="bank",
        n=2,
        title="Bank",
        status=_status(found),
        reason=reason,
        link="/bank",
        checked=checked,
        found=found,
        proposes=[c for f in found if (c := f.refs.get("card"))],
        data={"coverage": coverage, "lines": len(month_lines), "open": len(open_lines)},
    )


# ---- 3 Sales ----------------------------------------------------------------


async def step_sales(ctx: Ctx) -> Step:
    from app import invoicing

    ledger = await ctx.ledger()
    settled = ledger.settlement()
    invoices = await invoicing.list_invoices(ctx.books)
    found: list[Finding] = []
    proposes: list[str] = []
    drafts = [i for i in invoices if i.status == "draft" and ctx.in_month(i.issue_date)]
    for inv in drafts:
        found.append(
            Finding(
                text=f"{inv.number} ({inv.customer.name}, {money(inv.total_pence)}) dated {day(inv.issue_date)} is "
                f"still a draft, so it is not in {ctx.short}'s sales: send it or void it on Invoices.",
                level="blocking",
                link="/invoices",
                refs={"invoice": inv.number},
            )
        )
    overdue = sorted(
        (
            i
            for i in invoices
            if i.status == "sent"
            and i.due_date < ctx.today
            and (i.event_id is None or settled.outstanding(i.event_id) > 0)
        ),
        key=lambda i: i.due_date,
    )
    for n, inv in enumerate(overdue):
        owed = settled.outstanding(inv.event_id) if inv.event_id else inv.total_pence
        days = (ctx.today - inv.due_date).days
        base = f"{inv.number} ({inv.customer.name}, {money(owed)} owed) is {_plural(days, 'day')} overdue"
        if n >= MAX_CHASE_CARDS or ctx.token is None:
            found.append(Finding(text=f"{base}: chase it from Invoices.", link=INVOICES, refs={"invoice": inv.number}))
            continue
        try:
            draft = await actions.chase_draft(ctx.books, inv, ctx.cfg, ctx.today)
        except Exception as exc:  # noqa: BLE001  one reminder that cannot be drafted must not stop the close
            found.append(
                Finding(
                    text=f"{base}; the reminder could not be drafted ({type(exc).__name__}): chase it from Invoices.",
                    link="/invoices",
                    refs={"invoice": inv.number},
                )
            )
            continue
        if isinstance(draft, Clarification):
            found.append(
                Finding(
                    text=f"{base}, but it has no email address: add one on Contacts, then chase it.",
                    link="/contacts",
                    refs={"invoice": inv.number},
                )
            )
            continue
        card = ctx.card(draft)
        if card:
            proposes.append(card.id)
        found.append(
            Finding(
                text=f"{base}: a reminder is drafted below for you to approve.",
                link="/invoices",
                refs={"invoice": inv.number, "card": card.id if card else None},
            )
        )
    sent_in_month = [i for i in invoices if i.status in ("sent", "paid") and ctx.in_month(i.issue_date)]
    checked = [
        f"Invoices: {len(invoices)} in all, {len(sent_in_month)} raised in {ctx.short}",
        f"Drafts dated in {ctx.short}: {len(drafts)}",
        f"Overdue today: {len(overdue)}",
    ]
    if not found:
        reason = f"No overdue invoices and no unsent drafts dated in {ctx.short}."
    elif drafts:
        reason = found[0].text
    else:
        total = sum(settled.outstanding(i.event_id) if i.event_id else i.total_pence for i in overdue)
        reason = f"{_plural(len(overdue), 'invoice')} overdue ({money(total)}): reminders are drafted for you."
    return Step(
        id="sales",
        n=3,
        title="Sales",
        status=_status(found),
        reason=reason,
        link="/invoices",
        checked=checked,
        found=found,
        proposes=proposes,
    )


# ---- 4 Purchases ------------------------------------------------------------


async def step_purchases(ctx: Ctx) -> Step:
    ledger = await ctx.ledger()
    contacts, _, _ = await cb.contact_book(ctx.books, ledger)
    aged = cb.aged(contacts, ledger, ctx.today)
    found: list[Finding] = []
    horizon = ctx.today + timedelta(days=DUE_SOON_DAYS)
    due: list[tuple[str, cb.AgedDoc]] = [
        (row.name, d) for row in aged.creditors.rows for d in row.documents if d.due_date <= horizon
    ]
    due.sort(key=lambda nd: nd[1].due_date)
    for name, d in due[:20]:
        ref = f" {d.reference}" if d.reference else ""
        when = f"was due on {day(d.due_date)}" if d.due_date < ctx.today else f"is due on {day(d.due_date)}"
        found.append(
            Finding(
                text=f"Bill from {name}{ref} ({money(d.amount_pence)} to pay) {when}: pay it and record the payment.",
                link="/contacts",
                refs={"event": d.event_id},
            )
        )
    docs = {d.event.id: d for d in cb.documents(ledger)}
    credits = [c for c in ledger.settlement().credits if c.side == "purchase" and c.amount_pence > 0]
    for c in credits:
        who = docs[c.doc_event_id].name if c.doc_event_id in docs else "a supplier"
        found.append(
            Finding(
                text=f"{who} owes you a credit of {money(c.amount_pence)} not applied yet: apply it to a bill or "
                "record the refund on Contacts.",
                link="/contacts",
                refs={"credit": c.id},
            )
        )
    bills = [d for row in aged.creditors.rows for d in row.documents]
    checked = [
        f"Bills unpaid: {len(bills)} ({money(aged.creditors.total_pence)})",
        f"Due by {day(horizon)}: {len(due)}",
        f"Supplier credits not applied: {len(credits)}",
    ]
    reason = (
        "No bills due in the next week and no supplier credits waiting."
        if not found
        else f"{_plural(len(due), 'bill')} due or overdue, {_plural(len(credits), 'supplier credit')} not applied."
    )
    return Step(
        id="purchases",
        n=4,
        title="Purchases",
        status=_status(found),
        reason=reason,
        link="/contacts",
        checked=checked,
        found=found,
    )


# ---- 5 Payroll --------------------------------------------------------------


async def step_payroll(ctx: Ctx) -> Step:
    from app import jobs, payroll

    staff = [s for s in await jobs.load_staff(ctx.books) if s.active]
    runs = await payroll.list_runs(ctx.books)
    if not staff and not runs:
        return Step(
            id="payroll",
            n=5,
            title="Payroll",
            status="ok",
            reason="Payroll is not used: there are no staff on Jobs and no pay runs.",
            link="/payroll",
            checked=["Staff: none", "Pay runs: none"],
        )
    run = await payroll.load_run(ctx.books, ctx.month)
    hours = sum(float(e.hours) for e in await jobs.load_entries(ctx.books, ctx.month))
    found: list[Finding] = []
    if run is None:
        if hours:
            found.append(
                Finding(
                    text=f"No pay run for {ctx.label}, but {hours:g} hours were logged: prepare it on Payroll and "
                    "confirm what your payroll provider calculated, so the wages are in the books.",
                    level="blocking",
                    link="/payroll",
                )
            )
        else:
            found.append(
                Finding(
                    text=f"No pay run for {ctx.label} and no hours logged. If nobody was paid in {ctx.short}, "
                    "there is nothing to do; otherwise prepare the pay run on Payroll.",
                    level="needs_you",
                    link="/payroll",
                )
            )
    elif run.status == "draft":
        found.append(
            Finding(
                text=f"The pay run for {ctx.label} is a draft (estimated gross {money(run.est_gross_pence)}): confirm "
                "what your payroll provider calculated, so the wages are posted.",
                level="blocking",
                link="/payroll",
            )
        )
    checked = [
        f"Staff: {len(staff)} active",
        f"Hours logged in {ctx.short}: {hours:g}",
        f"Pay run {ctx.month}: {'none' if run is None else run.status}",
    ]
    reason = (
        found[0].text
        if found
        else f"The pay run for {ctx.label} is confirmed (gross {money(run.confirmed_gross_pence or 0)})."
        if run
        else ""
    )
    return Step(
        id="payroll",
        n=5,
        title="Payroll",
        status=_status(found),
        reason=reason,
        link="/payroll",
        checked=checked,
        found=found,
    )


# ---- 6 VAT ------------------------------------------------------------------


async def step_vat(ctx: Ctx) -> Step:
    from app.routes_vat import LABELS, box_amounts, period_key_for, read_obligations, submitted_periods

    ps, pe = period_containing(ctx.end, ctx.cycle.start_month, ctx.cycle.months)
    label = vat_label(ps, pe)
    notes: list[Finding] = []
    if ctx.cycle.assumed:
        notes.append(
            Finding(
                text="Calendar quarters were assumed: set your VAT periods in Settings › Business if yours differ.",
                level="note",
                link="/settings",
            )
        )
    if pe != ctx.end:
        return Step(
            id="vat",
            n=6,
            title="VAT",
            status="ok",
            reason=f"{ctx.short} does not end a VAT period ({label} ends on {day(pe)} {pe.year}).",
            link="/vat",
            checked=[f"VAT period: {label}"],
            found=notes,
        )
    events = await ctx.books.list_events(ps, pe)
    ret = compute_vat_return(events, period_key_for(ps), ps, pe)
    boxes = box_amounts(ret)
    obligations = [o for o in await read_obligations(ctx.books) if (o.start, o.end) == (ps, pe)]
    fulfilled = next((o for o in obligations if o.status == "F"), None)
    receipt = (await submitted_periods(ctx.books)).get((ps, pe))
    deadline = obligations[0].due if obligations else filing_deadline(pe)
    pid = period_id(ps, ctx.cycle.months)
    used = set(ret.event_ids)
    by_id = {e.id: e for e in events}
    trail = [
        {
            "event_id": e.id,
            "date": e.date.isoformat(),
            "kind": e.kind,
            "counterparty": e.counterparty,
            "net_pence": e.net,
            "vat_pence": e.vat,
            "evidence": e.evidence,
        }
        for i in ret.event_ids
        if (e := by_id.get(i))
    ]
    data = {
        "period": pid,
        "label": label,
        "start": ps.isoformat(),
        "end": pe.isoformat(),
        "deadline": deadline.isoformat(),
        "submitted": bool(fulfilled or receipt),
        "boxes": [{"box": i, "label": LABELS[i], "amount": boxes[i]} for i in range(1, 10)],
        "trail": trail[:200],
        "trail_total": len(trail),
        "left_out": len([e for e in events if e.id not in used]),
        "warnings": ret.warnings,
    }
    found = list(notes)
    for w in ret.warnings[:5]:
        found.append(Finding(text=f"VAT: {w}", level="needs_you", link=f"/vat?period={pid}"))
    link = f"/vat?period={pid}"
    checked = [f"VAT period: {label}", f"Entries in it: {len(events)} ({len(trail)} on the return)"]
    if fulfilled or receipt:
        reason = f"The return for {label} has been submitted."
    else:
        owed = ret.total_vat_due - ret.vat_reclaimed
        to = "to pay" if owed >= 0 else "to reclaim"
        late = deadline < ctx.today
        reason = (
            f"The return for {label} is ready to check: box 5 £{boxes[5]} {to}, due by {day(deadline)} "
            f"{deadline.year}{' (overdue)' if late else ''}. Review and submit it on the VAT page; "
            "Accnomos never submits on its own."
        )
        found.insert(0, Finding(text=reason, level="needs_you", link=link))
        if ctx.blocking_so_far():
            found.append(
                Finding(
                    text=f"These figures will change if you clear the "
                    f"{_plural(ctx.blocking_so_far(), 'blocking item')} above first.",
                    level="note",
                    link=link,
                )
            )
    return Step(
        id="vat",
        n=6,
        title="VAT",
        status=_status(found),
        reason=reason,
        link=link,
        checked=checked,
        found=found,
        data=data,
    )


# ---- 7 Checks ---------------------------------------------------------------


async def step_checks(ctx: Ctx) -> Step:
    ledger = await ctx.ledger()
    month_events = [e for e in ledger.events if ctx.in_month(e.date)]
    live = _live(ledger.events)
    found: list[Finding] = []
    pl = rp.profit_and_loss(month_events, ctx.start, ctx.end)
    sundry = next((r.amount_pence for r in pl.overheads.rows if r.account == SUNDRY), 0)
    if sundry:
        found.append(
            Finding(
                text=f"{money(sundry)} in {SUNDRY} (uncategorised) in {ctx.short}: recode those entries to the right "
                "accounts (Undo and approve again, or a bank rule).",
                level="blocking",
                link="/reports",
            )
        )
    uncoded = sorted({ln.account for e in month_events for ln in e.lines if rp.account_code(ln.account) is None})
    if uncoded:
        found.append(
            Finding(
                text=f"Entries in {ctx.short} use accounts that are not in the chart: {', '.join(uncoded[:5])}. "
                "Recode them.",
                level="blocking",
                link="/reports",
            )
        )
    groups: dict[tuple[str, str, int, date], list[LedgerEvent]] = defaultdict(list)
    for e in live:
        if e.kind in ("purchase", "sale") and ctx.in_month(e.date):
            groups[(e.kind, supplier_key(e.counterparty or ""), gross_of(e), e.date)].append(e)
    for (kind, _, gross, when), evs in sorted(groups.items(), key=lambda kv: kv[0][3]):
        if len(evs) > 1:
            who = evs[0].counterparty or "the same counterparty"
            found.append(
                Finding(
                    text=f"Possible duplicate: {len(evs)} {kind}s {'to' if kind == 'sale' else 'from'} {who} for "
                    f"{money(gross)} on {day(when)}. Undo one if it was entered twice.",
                    level="blocking",
                    link="/review",
                    refs={"events": [e.id for e in evs]},
                )
            )
    lows: dict[str, BankLine] = {}
    for ln in ledger.bank_lines:
        if ctx.in_month(ln.date) and ln.balance_pence is not None and ln.balance_pence < 0:
            bank = bank_of(upgrade(ln.source_file))
            if bank not in lows or ln.balance_pence < (lows[bank].balance_pence or 0):
                lows[bank] = ln
    for bank, ln in sorted(lows.items()):
        found.append(
            Finding(
                text=f"The {bank} balance went below zero in {ctx.short} (lowest {money(ln.balance_pence or 0)} on "
                f"{day(ln.date)}): check for overdraft charges.",
                level="needs_you",
                link="/bank",
            )
        )
    history: dict[str, list[int]] = defaultdict(list)
    for e in live:
        if e.kind == "purchase" and e.date < ctx.start and e.counterparty:
            history[supplier_key(e.counterparty)].append(gross_of(e))
    for e in live:
        if e.kind != "purchase" or not ctx.in_month(e.date) or not e.counterparty:
            continue
        past = history.get(supplier_key(e.counterparty), [])
        if len(past) < 3:
            continue
        usual = int(statistics.median(past))
        if gross_of(e) > UNUSUAL_TIMES * usual and gross_of(e) - usual >= UNUSUAL_MIN_PENCE:
            found.append(
                Finding(
                    text=f"{e.counterparty} {money(gross_of(e))} on {day(e.date)} is more than {UNUSUAL_TIMES} times "
                    f"the usual {money(usual)}: check it is right.",
                    level="needs_you",
                    link="/review",
                    refs={"event": e.id},
                )
            )
    adjustments = [e for e in month_events if e.kind == "adjustment"]
    if adjustments:
        found.append(
            Finding(
                text=f"{_plural(len(adjustments), 'manual adjustment')} dated in {ctx.short}: check "
                f"{'it is' if len(adjustments) == 1 else 'they are'} right.",
                level="needs_you",
                link="/reports",
                refs={"events": [e.id for e in adjustments]},
            )
        )
    checked = [
        f"Entries dated in {ctx.short}: {len(month_events)}",
        f"{SUNDRY}: {money(sundry)}",
        "Duplicates: same counterparty, amount and day",
        "Bank balances below zero",
        f"Purchases over {UNUSUAL_TIMES}× the supplier's usual amount",
    ]
    clean = "No uncategorised balance, duplicates, negative balances or unusual postings."
    reason = found[0].text if found else clean
    return Step(
        id="checks",
        n=7,
        title="Checks",
        status=_status(found),
        reason=reason,
        link="/reports",
        checked=checked,
        found=found,
    )


# ---- 8 Reports --------------------------------------------------------------


async def write_reports(books: Books, month: str, *, draft: bool, closed_line: str | None = None) -> tuple[str, Any]:
    """(path, web_url): the month's P&L and balance sheet. The draft is rewritten by each run; a closed month's
    report is never overwritten (a re-close saves '… (2).xlsx')."""
    start, end = month_bounds(month)
    events = await books.list_events(None, end)
    pl = rp.profit_and_loss(events, start, end)
    bs = rp.balance_sheet(events, end)
    data, _ = rp.build_month_end_xlsx(
        month_label(month), pl, bs, draft=draft, closed_line=closed_line, sample=rp.is_sample(events)
    )
    await books.storage.ensure_folder(REPORTS)
    path = draft_report_path(month) if draft else await books.free_path(REPORTS, f"{month}-month-end.xlsx")
    ref = await books.storage.write(path, data)
    return path, ref.web_url


async def step_reports(ctx: Ctx) -> Step:
    blocking = ctx.blocking_so_far()
    if not ctx.ended:
        return Step(
            id="reports",
            n=8,
            title="Reports",
            status="blocked",
            reason=f"{ctx.label} ends on {day(ctx.end)}: the month's reports are saved once it has ended.",
            link="/reports",
        )
    if blocking:
        return Step(
            id="reports",
            n=8,
            title="Reports",
            status="blocked",
            reason=f"Waiting for {_plural(blocking, 'blocking item')} above: the P&L and balance sheet are saved "
            "once nothing blocks the close.",
            link="/reports",
        )
    path, url = await write_reports(ctx.books, ctx.month, draft=True)
    start, end = ctx.start, ctx.end
    events = await ctx.books.list_events(None, end)
    pl = rp.profit_and_loss(events, start, end)
    bs = rp.balance_sheet(events, end)
    return Step(
        id="reports",
        n=8,
        title="Reports",
        status="ok",
        reason=f"Draft P&L and balance sheet saved to {path} (net {'profit' if pl.net_profit_pence >= 0 else 'loss'} "
        f"{money(abs(pl.net_profit_pence))}).",
        link="/files",
        checked=[f"P&L {ctx.label}", f"Balance sheet at {day(end)} {end.year}"],
        data={
            "path": path,
            "web_url": url,
            "net_profit_pence": pl.net_profit_pence,
            "sales_pence": pl.sales.total_pence,
            "net_assets_pence": bs.net_assets_pence,
            "balances": bs.difference_pence == 0,
        },
    )


# ---- 9 Lock -----------------------------------------------------------------


async def step_lock(ctx: Ctx, snap: Snapshot, record: MonthFile, changes: Changes | None) -> Step:
    blocking = ctx.blocking_so_far()
    last = record.closes[-1] if record.closes else None
    link = f"/month-end?month={ctx.month}"
    if not ctx.ended:
        return Step(
            id="lock",
            n=9,
            title="Lock",
            status="blocked",
            reason=f"{ctx.label} has not ended yet (it ends on {day(ctx.end)}), so it cannot be closed.",
            link=link,
        )
    if last and changes is None:
        return Step(
            id="lock",
            n=9,
            title="Lock",
            status="ok",
            reason=f"{ctx.label} was closed on {day(last.closed_at.date())} and nothing dated in it has changed since.",
            link=link,
            data={"snapshot_hash": snap.hash, "closed_at": last.closed_at.isoformat()},
        )
    if blocking:
        return Step(
            id="lock",
            n=9,
            title="Lock",
            status="blocked",
            reason=f"Clear the {_plural(blocking, 'blocking item')} above first; then run the close again to mark "
            f"{ctx.short} closed.",
            link=link,
        )
    reclose = last is not None
    f = snap.figures
    preview = {
        "month": ctx.month,
        "label": ctx.label,
        "snapshot_hash": snap.hash,
        "reclose": reclose,
        "figures": {
            "sales_pence": f.sales_pence,
            "cost_of_sales_pence": f.cost_of_sales_pence,
            "overheads_pence": f.overheads_pence,
            "net_profit_pence": f.net_profit_pence,
            "vat_box1": f.vat.get("1"),
            "vat_box4": f.vat.get("4"),
        },
        "entries": len(snap.events),
        "bank_lines": len(snap.bank),
        "changes": changes.items[:10] if changes else [],
        "warnings": [changes.vat_note] if changes and changes.vat_note else [],
    }
    verb = "Re-close" if reclose else "Close"
    summary = (
        f"**{verb} {actions._md(ctx.label)}**: {_plural(len(snap.events), 'entry', 'entries')} and "
        f"{_plural(len(snap.bank), 'bank line')}; sales {money(f.sales_pence)}, net "
        f"{'profit' if f.net_profit_pence >= 0 else 'loss'} {money(abs(f.net_profit_pence))}. "
        "A snapshot of these figures is recorded; if anything dated in the month changes later, you will be told."
    )
    card = ctx.card(actions.Draft("close_month", summary, preview, f"Mark {ctx.label} closed"))
    text = (
        f"Approve to re-close {ctx.label}: {changes.count if changes else 0} change(s) since it was closed."
        if reclose
        else f"Everything is in: approve to mark {ctx.label} closed."
    )
    return Step(
        id="lock",
        n=9,
        title="Lock",
        status="needs_you",
        reason=text,
        link=link,
        found=[Finding(text=text, level="needs_you", link=link, refs={"card": card.id if card else None})],
        proposes=[card.id] if card else [],
        data={"snapshot_hash": snap.hash},
    )


# ---- the loop ---------------------------------------------------------------

StepFn = Callable[[Ctx], Awaitable[Step]]
STEP_FNS: dict[StepId, StepFn] = {
    "inbox": step_inbox,
    "bank": step_bank,
    "sales": step_sales,
    "purchases": step_purchases,
    "payroll": step_payroll,
    "vat": step_vat,
    "checks": step_checks,
    "reports": step_reports,
}


def _failed(step_id: StepId, n: int, title: str, exc: Exception) -> Step:
    """A step that could not run says so; the close cannot go ahead without it."""
    log.exception("month-end step %s failed", step_id)
    return Step(
        id=step_id,
        n=n,
        title=title,
        status="blocked",
        reason=f"This step could not run ({type(exc).__name__}: {str(exc)[:160]}). Fix that and run the close again.",
        found=[Finding(text=f"{title} could not be checked: {type(exc).__name__}.", level="blocking")],
    )


def _summary_facts(ctx: Ctx, steps: list[Step], snap: Snapshot, closed: bool, can_close: bool) -> dict[str, Any]:
    f = snap.figures
    return {
        "month": ctx.label,
        "needs_you": sum(s.needs_you for s in steps),
        "blocking": sum(s.blocking for s in steps),
        "can_close": can_close,
        "closed": closed,
        "steps": [{"title": s.title, "status": s.status, "reason": s.reason} for s in steps],
        "figures": {
            "sales": money(f.sales_pence),
            "net_profit": money(f.net_profit_pence),
            "entries": len(snap.events),
            "bank_lines": len(snap.bank),
        },
    }


async def run(ctx: Ctx) -> AsyncIterator[tuple[str, Any]]:
    """The agent loop: yields ("start", plan), ("step", Step) as each finishes, ("summary", …), ("run", CloseRun)."""
    run_id = uuid.uuid4().hex
    started = now()
    yield (
        "start",
        {
            "run_id": run_id,
            "month": ctx.month,
            "label": ctx.label,
            "steps": [{"id": i, "n": n + 1, "title": t} for n, (i, t) in enumerate(STEPS)],
        },
    )
    for n, (sid, title) in enumerate(STEPS[:-1]):
        t0 = time.monotonic()
        try:
            step = await STEP_FNS[sid](ctx)
        except Exception as exc:  # noqa: BLE001  one step failing is reported, never hidden
            step = _failed(sid, n + 1, title, exc)
        step.ms = int((time.monotonic() - t0) * 1000)
        ctx.steps.append(step)
        yield "step", step
    t0 = time.monotonic()
    record = await load_record(ctx.books, ctx.month)
    snap = await snapshot(ctx.books, ctx.month)
    changes = await changes_since_close(ctx.books, record, snap)
    try:
        lock = await step_lock(ctx, snap, record, changes)
    except Exception as exc:  # noqa: BLE001
        lock = _failed("lock", 9, "Lock", exc)
    lock.ms = int((time.monotonic() - t0) * 1000)
    ctx.steps.append(lock)
    yield "step", lock

    steps = ctx.steps
    blocking = sum(s.blocking for s in steps)
    can_close = lock.status == "needs_you" and bool(lock.proposes)
    closed = bool(record.closes) and changes is None
    summary = await close_summary.summarise(_summary_facts(ctx, steps, snap, closed, can_close), ctx.cfg)
    yield "summary", summary
    stored = StoredRun(
        id=run_id,
        month=ctx.month,
        label=ctx.label,
        started_at=started,
        finished_at=now(),
        by=ctx.user,
        steps=steps,
        cards=[CardRef(id=c.id, kind=c.kind, summary_md=c.summary_md) for c in ctx.cards],
        summary_md=summary.summary_md,
        summary_model=summary.model,
        summary_fallback_reason=summary.fallback_reason,
        needs_you=sum(s.needs_you for s in steps),
        blocking=blocking,
        can_close=can_close,
        snapshot_hash=snap.hash,
    )
    await _update_record(
        ctx.books,
        ctx.month,
        lambda m: m.model_copy(update={"runs": [*m.runs, stored][-RUNS_KEPT:]}),
    )
    await ctx.books.audit(
        ACTOR,
        "close_run",
        {
            "month": ctx.month,
            "run": run_id,
            "user": ctx.user,
            "needs_you": stored.needs_you,
            "blocking": blocking,
            "cards": len(ctx.cards),
            "can_close": can_close,
        },
    )
    yield "run", CloseRun(**stored.model_dump(), actions=ctx.cards, changes=changes)


async def run_to_end(ctx: Ctx) -> CloseRun:
    result: CloseRun | None = None
    async for event, data in run(ctx):
        if event == "run":
            result = data
    assert result is not None
    return result


# --------------------------------------------------------------------------- #
# Lock (the user's Approve on the close_month card, app/actions.py)
# --------------------------------------------------------------------------- #


async def lock(books: Books, preview: dict[str, Any], user: str, action_id: str | None = None) -> CloseRecord:
    month = str(preview.get("month") or "")
    month_bounds(month)
    snap = await snapshot(books, month)
    if snap.hash != preview.get("snapshot_hash"):
        raise actions.ActionError(
            f"{month_label(month)}'s figures changed after this check ran, so it was not closed. Run the close again.",
            409,
        )
    record = await load_record(books, month)
    previous = record.closes[-1] if record.closes else None
    if previous and previous.snapshot_hash == snap.hash:
        raise actions.ActionError(f"{month_label(month)} is already closed with these figures.", 409)
    since = diff(previous.snapshot, snap)[0] if previous else []
    at = now()
    closed_line = f"Closed on {at:%d/%m/%Y} by {user}; snapshot {snap.hash[:12]}"
    if previous:
        first = f"first closed {previous.closed_at:%d/%m/%Y}"
        closed_line = f"Re-closed on {at:%d/%m/%Y} by {user} ({first}); snapshot {snap.hash[:12]}"
    try:
        report_path, _ = await write_reports(books, month, draft=False, closed_line=closed_line)
    except Exception:  # noqa: BLE001  the close stands without the spreadsheet; said in the record and the audit
        log.exception("month-end report could not be saved")
        report_path = None
    rec = CloseRecord(
        id=uuid.uuid4().hex,
        month=month,
        closed_at=at,
        closed_by=user,
        snapshot_hash=snap.hash,
        snapshot=snap,
        run_id=record.runs[-1].id if record.runs else None,
        action_id=action_id,
        report_path=report_path,
        reclose=previous is not None,
        changes_since_previous=since,
    )
    await _update_record(books, month, lambda m: m.model_copy(update={"closes": [*m.closes, rec]}))
    await books.audit(
        f"user:{user}",
        "month_reclosed" if rec.reclose else "month_closed",
        {"month": month, "snapshot": snap.hash, "report": report_path, "action": action_id, "changes": len(since)},
    )
    return rec


# --------------------------------------------------------------------------- #
# Status (Home card, the Month-end page, the phone)
# --------------------------------------------------------------------------- #


class MonthStatus(BaseModel):
    month: str
    label: str
    ended: bool
    closed: bool  # closed, and nothing dated in it has changed since
    closed_at: datetime | None = None
    closed_by: str | None = None
    last_run_at: datetime | None = None
    needs_you: int | None = None  # from the last run
    blocking: int | None = None
    can_close: bool | None = None
    changes: Changes | None = None
    headline: str


class CloseOverview(BaseModel):
    today: date
    target: MonthStatus  # the month that ended last
    changed: list[MonthStatus]  # other closed months with changes since, newest first


class MonthDetail(MonthStatus):
    run: StoredRun | None = None  # the last run
    closes: list[CloseRecord] = Field(default_factory=list)


def _headline(st: MonthStatus) -> str:
    short = st.label.split()[0]
    if st.changes is not None:
        return st.changes.headline
    if st.closed and st.closed_at:
        return f"{short} was closed on {day(st.closed_at.date())}."
    if not st.ended:
        return f"{short} has not ended yet."
    if st.last_run_at is None:
        return f"{short} has not been closed yet: run the month-end close."
    if st.can_close:
        return f"{short} is ready to close: approve it on Month-end."
    n = st.needs_you or 0
    if n == 0:
        return f"{short}: run the close again to finish it."
    return f"{short}: {n} thing{'s need' if n != 1 else ' needs'} you before close."


async def month_status(
    books: Books, month: str, today: date, events: list[LedgerEvent] | None = None, lines: list[BankLine] | None = None
) -> MonthDetail:
    start, end = month_bounds(month)
    record = await load_record(books, month)
    changes = None
    if record.closes:
        if events is None:
            events = await books.list_events(start, end)
        if lines is None:
            lines = await books.stored_bank_lines()
        changes = await changes_since_close(books, record, snapshot_from(events, lines, month))
    last_run = record.runs[-1] if record.runs else None
    last_close = record.closes[-1] if record.closes else None
    st = MonthDetail(
        month=month,
        label=month_label(month),
        ended=end < today,
        closed=bool(last_close) and changes is None,
        closed_at=last_close.closed_at if last_close else None,
        closed_by=last_close.closed_by if last_close else None,
        last_run_at=last_run.finished_at if last_run else None,
        needs_you=last_run.needs_you if last_run else None,
        blocking=last_run.blocking if last_run else None,
        can_close=last_run.can_close if last_run else None,
        changes=changes,
        headline="",
        run=last_run,
        closes=record.closes,
    )
    st.headline = _headline(st)
    return st


async def overview(books: Books, today: date | None = None) -> CloseOverview:
    today = today or london_today()
    target = previous_month(today)
    months = [m for m in await recorded_months(books) if m != target]
    events = await books.list_events() if months else None  # once for every recorded month, not once each
    lines = await books.stored_bank_lines() if months else None
    tgt = await month_status(books, target, today, events, lines)
    changed: list[MonthStatus] = []
    for m in sorted(months, reverse=True)[:24]:
        st = await month_status(books, m, today, events, lines)
        if st.changes is not None:
            changed.append(MonthStatus(**st.model_dump(exclude={"run", "closes"})))
    return CloseOverview(today=today, target=MonthStatus(**tgt.model_dump(exclude={"run", "closes"})), changed=changed)
