"""Home dashboard: one payload assembled by code from the user's own files. No model calls.

Read, never written: ledger events, proposals, bank lines, sales invoices and the last two months of audit files.
Each section is worked out on its own; one that cannot be read (a hand-edited file that no longer parses) comes
back as null and is named in `unavailable`, so the app shows "—" for that tile and the rest still work.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

from accnomos_ledger.bank import BankLine, reconciled_to
from app import contacts as cb
from app import invoicing
from app.books import AUDIT, AUTOPILOT_AUDIT, Books, bank_of
from app.paths import upgrade
from app.routes_vat import Deadlines, compute_deadlines
from app.schemas import Proposal
from app.settlement import load_records

log = logging.getLogger(__name__)
ACTIVITY_LIMIT = 10
AUDIT_MONTHS = 2  # recent activity and last runs look this far back
MONTH_FILE = re.compile(r"\d{4}-\d{2}\.jsonl")
TRIAGE_ACTOR = "agent:triage"  # /mail/triage (claude/inbox-triage), once merged


class Cash(BaseModel):
    balance_pence: int | None  # closing balance on the latest statement with a matched line; None without one
    as_of: date | None  # the date of that balance
    bank: str | None
    statement: str | None  # the statement file in the bank statements folder
    reconciled_to: date | None  # every bank line on or before this date is matched, a transfer or ignored


class Owed(BaseModel):
    total_pence: int
    documents: int
    oldest_days: int | None  # age of the oldest unpaid document, from its date


class OwedToYou(Owed):
    overdue: int | None  # sent invoices past their due date; None when the invoices could not be read
    overdue_pence: int | None
    most_overdue_days: int | None


class Attention(BaseModel):
    proposed: int
    needs_a_look: int
    unmatched_bank_lines: int  # open lines: not matched, a transfer or ignored
    overdue_invoices: int | None
    total: int


class ActivityItem(BaseModel):
    at: datetime
    actor: str  # "You", "Autopilot", "Intake", "Extractor", ...
    action: str  # the audit action, e.g. "approved"
    text: str
    tone: Literal["ok", "warn"]


class Run(BaseModel):
    at: datetime
    summary: str | None


class Runs(BaseModel):
    scan: Run | None  # last inbox scan (_System/cursors.json)
    autopilot: Run | None  # last entry Autopilot posted
    intake: Run | None  # last Outlook check
    triage: Run | None  # last inbox triage


class Dashboard(BaseModel):
    today: date
    cash: Cash | None
    owed_to_you: OwedToYou | None
    owed_by_you: Owed | None
    vat: Deadlines | None
    attention: Attention | None
    activity: list[ActivityItem]
    runs: Runs
    unavailable: list[str]  # sections that could not be worked out: show "—"


# --------------------------------------------------------------------------- #
# Pure pieces
# --------------------------------------------------------------------------- #


def closing_line(lines: Sequence[BankLine]) -> BankLine | None:
    """The last line with a running balance. On the last day, the line whose balance no other line starts from."""
    dated = [ln for ln in lines if ln.balance_pence is not None]
    if not dated:
        return None
    last = max(ln.date for ln in dated)
    day = [ln for ln in dated if ln.date == last]
    openings = {ln.balance_pence - ln.amount_pence for ln in day}  # type: ignore[operator]
    return next((ln for ln in reversed(day) if ln.balance_pence not in openings), day[-1])


def cash_position(lines: Sequence[BankLine]) -> Cash:
    by_file: dict[str, list[BankLine]] = {}
    for ln in lines:
        by_file.setdefault(upgrade(ln.source_file), []).append(ln)  # where it is now, after a folder rename
    matched = [(path, ls) for path, ls in by_file.items() if any(ln.status == "matched" for ln in ls)]
    latest = max(matched, key=lambda pl: (max(ln.date for ln in pl[1]), pl[0]), default=None)
    closing = closing_line(latest[1]) if latest else None
    statement = latest[0] if latest and closing else None
    return Cash(
        balance_pence=closing.balance_pence if closing else None,
        as_of=closing.date if closing else None,
        bank=bank_of(statement) if statement else None,
        statement=statement,
        reconciled_to=reconciled_to(lines),
    )


def owed(docs: Sequence[cb.Doc], today: date, ledger: cb.Ledger | None = None) -> Owed:
    return Owed(
        total_pence=sum(cb.outstanding(d, ledger) if ledger else d.gross for d in docs),
        documents=len(docs),
        oldest_days=max(((today - d.event.date).days for d in docs), default=None),
    )


def owed_to_you(ledger: cb.Ledger, invoices: list[invoicing.Invoice] | None, today: date) -> tuple[OwedToYou, Owed]:
    """What is still owed on sales and purchases on account, from the ledger (after part payments and credit
    notes, app/settlement.py). A sales invoice marked paid before payments were recorded is paid too; overdue counts
    come from the invoices' due dates (other sales carry none)."""
    paid = {i.event_id for i in invoices or [] if i.status == "paid" and i.paid_pence is None and i.event_id}
    open_docs = [
        d for d in cb.open_docs(cb.documents(ledger), ledger) if d.event.id not in paid and d.event.date <= today
    ]
    sales = [d for d in open_docs if d.side == "sale"]
    purchases = [d for d in open_docs if d.side == "purchase"]
    late: list[tuple[int, int]] | None = None
    if invoices is not None:
        still_open = {d.event.id for d in sales}
        late = [
            (days, ledger.settlement().outstanding(i.event_id))
            for i in invoices
            if i.event_id in still_open and (days := i.overdue_days(today)) is not None and days > 0
        ]
    return OwedToYou(
        **owed(sales, today, ledger).model_dump(),
        overdue=None if late is None else len(late),
        overdue_pence=None if late is None else sum(p for _, p in late),
        most_overdue_days=max((d for d, _ in late), default=None) if late is not None else None,
    ), owed(purchases, today, ledger)


def attention(ledger: cb.Ledger, overdue: int | None) -> Attention:
    every = ledger.proposals.values()
    counts = {
        "proposed": sum(p.status == "proposed" for p in every),
        "needs_a_look": sum(p.status == "needs_a_look" for p in every),
        "unmatched_bank_lines": sum(not ln.resolved for ln in ledger.bank_lines),
    }
    return Attention(**counts, overdue_invoices=overdue, total=sum(counts.values()) + (overdue or 0))


def actor_label(actor: str) -> str:
    if actor.startswith("user:"):
        return "You"
    if actor == "autopilot":
        return "Autopilot"
    return actor.removeprefix("agent:").replace("_", " ").capitalize() or "Accnomos"


WARN_ACTIONS = {"extract_failed", "books_rebuild_failed", "rejected", "undone", "invoice_voided"}


def activity_text(line: dict[str, Any], ledger: cb.Ledger) -> tuple[str, bool]:
    """(sentence, needs the user's eye) for one audit line, from its refs and the ledger."""
    action, refs = str(line.get("action", "")), line.get("refs") or {}
    p = ledger.proposals.get(str(refs.get("proposal", "")))
    who = f"{p.extracted.supplier_name} {invoicing.money(round(p.extracted.gross_total * 100))}" if p else "a document"
    match action:
        case "approved":
            return f"Posted {who} to the ledger", False
        case "proposed" if refs.get("status") == "needs_a_look":
            return f"Moved {who} to Needs a look", True
        case "proposed":
            return f"Proposed an entry for {who}", False
        case "rejected":
            return f"Rejected {who}", True
        case "mail_scanned":
            return f"Checked Outlook: {refs.get('saved', 0)} saved from {refs.get('candidates', 0)} candidates", False
        case "bank_imported":
            return f"Imported a {refs.get('bank', 'bank')} statement: {refs.get('new', 0)} new lines", False
        case "bank_matched":
            n = len(refs.get("events") or [])
            return f"Matched a bank line to {n} entr{'y' if n == 1 else 'ies'}", False
    text = action.replace("_", " ").capitalize() or "Activity"
    if refs.get("invoice"):
        text += f" · {refs['invoice']}"
    return text, action in WARN_ACTIONS


def recent_activity(
    lines: Sequence[dict[str, Any]],
    ledger: cb.Ledger,
    limit: int = ACTIVITY_LIMIT,
) -> list[ActivityItem]:
    out: list[ActivityItem] = []
    for line in sorted(lines, key=lambda x: x["ts"], reverse=True)[:limit]:
        text, warn = activity_text(line, ledger)
        out.append(
            ActivityItem(
                at=line["ts"],
                actor=actor_label(str(line.get("actor", ""))),
                action=str(line.get("action", "")),
                text=text,
                tone="warn" if warn else "ok",
            )
        )
    return out


def last_runs(audit: Sequence[dict[str, Any]], autopilot: Sequence[dict[str, Any]], last_scan: datetime | None) -> Runs:
    def latest(lines: Sequence[dict[str, Any]], keep: Callable[[dict[str, Any]], bool]) -> dict[str, Any] | None:
        return max((x for x in lines if keep(x)), key=lambda x: x["ts"], default=None)

    intake = latest(audit, lambda x: x.get("action") == "mail_scanned")
    triage = latest(audit, lambda x: x.get("actor") == TRIAGE_ACTOR)
    auto = latest(autopilot, lambda x: x.get("action") == "approved")
    intake_refs = (intake or {}).get("refs") or {}
    return Runs(
        scan=Run(at=last_scan, summary=None) if last_scan else None,
        autopilot=Run(
            at=auto["ts"],
            summary=f"Posted {auto.get('supplier_key') or 'an entry'} "
            f"{invoicing.money(int(auto.get('gross_pence') or 0))}",
        )
        if auto
        else None,
        intake=Run(at=intake["ts"], summary=f"{intake_refs.get('saved', 0)} imported from Outlook") if intake else None,
        triage=Run(at=triage["ts"], summary=str(triage.get("action", "")).replace("_", " ").capitalize())
        if triage
        else None,
    )


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


async def read_audit(books: Books, folder: str, months: int = AUDIT_MONTHS) -> list[dict[str, Any]]:
    """Lines of the last `months` monthly files in `folder`, with `ts` parsed; lines that do not parse are skipped."""
    files = sorted((f for f in await books.list_files(folder) if MONTH_FILE.fullmatch(f.name)), key=lambda f: f.name)
    out: list[dict[str, Any]] = []
    for f in files[-months:]:
        for raw in (await books.storage.read(f.path)).decode("utf-8", "replace").splitlines():
            try:
                line = json.loads(raw)
                line["ts"] = datetime.fromisoformat(line["ts"])
            except (ValueError, KeyError, TypeError):
                continue
            if isinstance(line, dict) and line["ts"].tzinfo is not None:
                out.append(line)
    return out


async def _try[T](name: str, missing: list[str], work: Callable[[], Awaitable[T]]) -> T | None:
    try:
        return await work()
    except ValueError:  # pydantic ValidationError and bad JSON in a hand-edited file
        log.exception("dashboard: %s could not be worked out", name)
        missing.append(name)
        return None


async def build(books: Books, today: date, first_vat_month: int, vat_months: int) -> Dashboard:
    missing: list[str] = []

    async def load_proposals() -> dict[str, Proposal]:
        return {p.id: p for p in await books.list_proposals()}

    # The ledger's three parts are read on their own, so one hand-edited file only blanks the tiles that need it.
    events = await _try("ledger", missing, books.list_events)
    proposals = await _try("proposals", missing, load_proposals)
    bank_lines = await _try("bank", missing, books.stored_bank_lines)
    records = await _try("payments", missing, lambda: load_records(books))
    ledger = cb.Ledger(
        events=events or [], proposals=proposals or {}, bank_lines=bank_lines or [], records=records or []
    )

    async def load_invoices() -> list[invoicing.Invoice]:
        return await invoicing.list_invoices(books)

    async def money() -> tuple[OwedToYou, Owed]:
        return owed_to_you(ledger, invoices, today)

    async def vat() -> Deadlines:
        return compute_deadlines(ledger.events, today, first_vat_month, vat_months)

    async def cash() -> Cash:
        return cash_position(ledger.bank_lines)

    invoices = await _try("invoices", missing, load_invoices)
    # Owed needs the events and the bank lines (payments); proposals only add labels.
    owed_pair = await _try("owed", missing, money) if events is not None and bank_lines is not None else None
    overdue = owed_pair[0].overdue if owed_pair else None
    audit = await read_audit(books, AUDIT)
    return Dashboard(
        today=today,
        cash=await _try("cash", missing, cash) if bank_lines is not None else None,
        owed_to_you=owed_pair[0] if owed_pair else None,
        owed_by_you=owed_pair[1] if owed_pair else None,
        vat=await _try("vat", missing, vat) if events is not None else None,
        attention=attention(ledger, overdue) if proposals is not None and bank_lines is not None else None,
        activity=recent_activity(audit, ledger),
        runs=last_runs(audit, await read_audit(books, AUTOPILOT_AUDIT), await books.last_scan()),
        unavailable=missing,
    )
