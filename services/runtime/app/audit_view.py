"""The audit trail, read back for people: GET /audit (app/routes_audit.py). Reads only; never writes or edits a line.

Two logs feed it, both one JSON object per line in monthly files:

    _System/audit/{yyyy-mm}.jsonl          Books.audit(): {"ts", "actor", "action", "refs"}
    _System/audit/actions/{yyyy-mm}.jsonl  chat and voice actions (app/actions.py): {"ts", "action_id", "kind",
                                           "event": approving|executed|failed|rejected, "user", ...}

_System/audit/autopilot/ is not read: every Autopilot posting and every undo of one is already in the main log
(approve.py writes both), so reading it too would show each twice.

Every line becomes one AuditEntry with a plain-English summary from SUMMARIES below. A kind that is not in the
table still shows, as its own name ("Vehicle serviced"). Lines that do not parse are skipped, never fatal.
"""

from __future__ import annotations

import json
import logging
import posixpath
import re
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from pydantic import BaseModel

from app.actions import ACTIONS_AUDIT
from app.autopilot import AUTOPILOT
from app.books import AUDIT, LONDON, Books
from app.invoicing import money
from app.paths import REPORTS

log = logging.getLogger(__name__)
MAX_LIMIT = 500
DEFAULT_DAYS = 31  # the range when `from` is not given
MAX_DAYS = 366  # the widest range one request may read

# agent:<name> -> the chip the apps show. Anything else is its name, capitalised.
AGENT_LABELS = {
    "autopilot": "Autopilot",
    "intake": "Intake",
    "triage": "Triage",
    "planner": "Planner",
    "extractor": "Reader",
    "mileage": "Mileage",
    "folder-layout": "Folder tidy",
    "contacts": "Contacts",
}


class AuditRefs(BaseModel):
    proposal: str | None = None  # a Review card
    event: str | None = None  # a ledger event id
    invoice: str | None = None  # a sales invoice number
    action: str | None = None  # a chat or voice action id
    file: str | None = None  # a path in the user's OneDrive


class AuditEntry(BaseModel):
    ts: datetime
    actor: str  # as written: "user:<email>" or "agent:<name>"
    actor_kind: Literal["user", "agent"]
    actor_label: str  # "You", "Autopilot", "Intake", "Triage", "Planner", ...
    event: str  # the audit action, e.g. "approved"; actions log lines are action_done / action_rejected / action_failed
    summary: str
    refs: AuditRefs


class AuditPage(BaseModel):
    start: date
    end: date
    entries: list[AuditEntry]  # newest first
    truncated: bool  # more lines matched than `limit`


# --------------------------------------------------------------------------- #
# Summaries
# --------------------------------------------------------------------------- #


def _n(refs: dict[str, Any], key: str) -> int:
    v = refs.get(key)
    if isinstance(v, list):
        return len(v)
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else many or one + 's'}"


def _pounds(refs: dict[str, Any], key: str) -> str:
    v = refs.get(key)
    return f" for {money(int(v))}" if isinstance(v, int) else ""


def _qty(v: Any) -> str:
    """7.5 stays 7.5; 100.0 is 100."""
    f = float(v)
    return str(int(f)) if f.is_integer() else f"{f:g}"


def _inv(refs: dict[str, Any]) -> str:
    return str(refs.get("invoice") or "")


def _fields(refs: dict[str, Any]) -> str:
    f = refs.get("fields")
    return f" ({', '.join(str(x).replace('_', ' ') for x in f)})" if isinstance(f, list) and f else ""


def _plain(md: Any) -> str:
    """One line of markdown as text: no **, _, ` or links, at most 160 characters."""
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", str(md or ""))
    s = re.sub(r"[*_`#>]+", "", s)
    s = " ".join(s.split())
    return s if len(s) <= 160 else s[:159].rstrip() + "…"


def _moved(refs: dict[str, Any]) -> str:
    moved = [m for m in refs.get("moved") or [] if isinstance(m, dict)]
    return ", ".join(f"{m.get('old')} → {m.get('new')}" for m in moved) or "none"


VAT_STATUS = {"registered": "VAT-registered", "not_registered": "not VAT-registered", "unknown": "not known"}

# kind -> (refs, who) -> sentence. `who` is "Screwfix £12.00" when the line names a proposal we can read,
# otherwise "a document".
Summary = Callable[[dict[str, Any], str], str]
SUMMARIES: dict[str, Summary] = {
    # Review and the ledger
    "proposed": lambda r, w: (
        f"Read {w} and moved it to Needs a look"
        if r.get("status") == "needs_a_look"
        else f"Read {w} and proposed an entry"
    ),
    "approved": lambda r, w: f"Posted {w} to the ledger",
    "rejected": lambda r, w: f"Rejected {w}" + (f": {r['reason']}" if r.get("reason") else ""),
    "undone": lambda r, w: (
        f"Undid the entry for {w}"
        + (" that Autopilot posted" if r.get("originally_approved_by") == AUTOPILOT else "")
        + "; it is back in Review"
    ),
    "extract_failed": lambda r, w: f"Could not read {posixpath.basename(str(r.get('path') or '')) or 'a file'}",
    "books_rebuild_failed": lambda r, w: "Could not rebuild Books.xlsx; the ledger itself is unchanged",
    "rule_removed": lambda r, w: f"Stopped Autopilot for {r.get('supplier_key') or 'a supplier'}",
    "plan_applied": lambda r, w: (
        f"Applied the day plan for {r.get('date', 'a day')}: " + _plural(_n(r, "events"), "entry", "entries")
    ),
    # Mail
    "mail_scanned": lambda r, w: (
        f"Checked Outlook: {_n(r, 'saved')} saved from " + _plural(_n(r, "candidates"), "candidate")
    ),
    "mail_triaged": lambda r, w: (
        f"Sorted the inbox: {_plural(_n(r, 'threads'), 'thread')} from " + _plural(_n(r, "scanned"), "message")
    ),
    "mail_draft_created": lambda r, w: "Saved a reply in your Outlook drafts (not sent)",
    # Bank
    "bank_imported": lambda r, w: (
        f"Imported a {r.get('bank') or 'bank'} statement: " + _plural(_n(r, "new"), "new line")
    ),
    "bank_matched": lambda r, w: f"Matched a bank line to {_plural(_n(r, 'events'), 'entry', 'entries')}",
    "bank_unmatched": lambda r, w: "Undid a bank line match",
    "bank_transfer": lambda r, w: "Marked a bank line as a transfer between your own accounts",
    "bank_ignored": lambda r, w: "Marked a bank line as nothing to book",
    "bank_expense_proposed": lambda r, w: "Proposed an expense from a bank line",
    "bank_rule_created": lambda r, w: "Added a bank rule",
    "bank_rule_updated": lambda r, w: "Edited a bank rule",
    "bank_rule_deleted": lambda r, w: "Deleted a bank rule",
    "bank_rules_reordered": lambda r, w: "Reordered the bank rules",
    "bank_reconciled": lambda r, w: f"Reconciled a bank line ({r.get('kind') or 'match'}) through Review approval",
    # Sales invoices
    "invoice_profile_saved": lambda r, w: "Saved your invoice details",
    "invoice_created": lambda r, w: f"Created invoice {_inv(r)}" + _pounds(r, "total_pence"),
    "invoice_edited": lambda r, w: f"Edited invoice {_inv(r)}" + _pounds(r, "total_pence"),
    "invoice_posted": lambda r, w: f"Posted invoice {_inv(r)} to the ledger",
    "invoice_sent": lambda r, w: f"Emailed invoice {_inv(r)}" + (f" to {r['to']}" if r.get("to") else ""),
    "invoice_reminder_sent": lambda r, w: f"Sent a reminder for invoice {_inv(r)}",
    "invoice_paid": lambda r, w: f"Marked invoice {_inv(r)} as paid",
    "invoice_part_paid": lambda r, w: f"Recorded a part payment on invoice {_inv(r)}",
    "invoice_unmarked_paid": lambda r, w: f"Took back the Mark paid on invoice {_inv(r)}",
    # Payments (app/payments.py) and credit notes (app/credit_notes.py)
    "payment_recorded": lambda r, w: (
        ("Recorded money in" if r.get("side") == "sale" else "Recorded a payment out")
        + _pounds(r, "amount_pence")
        + (f" against invoice {_inv(r)}" if r.get("invoice") else "")
    ),
    "payment_removed": lambda r, w: "Removed a payment; its entry was reversed",
    "payment_line_not_matched": lambda r, w: "Recorded a payment but could not match its bank line",
    # Credits on contacts (app/credits.py)
    "credit_applied": lambda r, w: "Applied a credit on account to another document" + _pounds(r, "amount_pence"),
    "credit_refunded": lambda r, w: (
        ("Refunded a customer's credit" if r.get("side") == "sale" else "Recorded a supplier refunding a credit")
        + _pounds(r, "amount_pence")
    ),
    "refund_line_not_matched": lambda r, w: "Recorded a refund but could not match its bank line",
    "credit_use_removed": lambda r, w: (
        "Took back a refund of a credit; its entry was reversed"
        if r.get("kind") == "refund"
        else "Took back a credit applied to a document"
    ),
    "credit_note_created": lambda r, w: (
        f"Created credit note {r.get('credit_note') or ''} for invoice {_inv(r)}" + _pounds(r, "total_pence")
    ),
    "credit_note_posted": lambda r, w: f"Posted credit note {r.get('credit_note') or ''} to the ledger",
    "credit_note_sent": lambda r, w: (
        f"Emailed credit note {r.get('credit_note') or ''}" + (f" to {r['to']}" if r.get("to") else "")
    ),
    "credit_note_voided": lambda r, w: (
        f"Voided credit note {r.get('credit_note') or ''}" + (f": {r['reason']}" if r.get("reason") else "")
    ),
    "invoice_voided": lambda r, w: f"Voided invoice {_inv(r)}" + (f": {r['reason']}" if r.get("reason") else ""),
    # Jobs, staff, timesheets
    "job_created": lambda r, w: "Added a job",
    "job_updated": lambda r, w: "Updated a job" + (f" ({r['status']})" if r.get("status") else ""),
    "job_deleted": lambda r, w: "Deleted a job",
    "staff_created": lambda r, w: "Added a member of staff",
    "staff_updated": lambda r, w: "Updated a member of staff",
    "staff_deleted": lambda r, w: "Removed a member of staff",
    "timesheet_added": lambda r, w: "Logged time" + (f": {_qty(r['hours'])} hours" if r.get("hours") else ""),
    "timesheet_updated": lambda r, w: "Changed a timesheet entry" + _fields(r),
    "timesheet_deleted": lambda r, w: "Deleted a timesheet entry",
    "timesheets_invoiced": lambda r, w: (
        f"Marked {_plural(_n(r, 'entries'), 'timesheet entry', 'timesheet entries')} as billed on invoice {_inv(r)}"
    ),
    "timesheets_not_invoiced": lambda r, w: f"Could not mark timesheets as billed on invoice {_inv(r)}",
    # Payroll
    "payroll_prepared": lambda r, w: (
        f"Prepared payroll for {r.get('period', 'a period')}"
        + (f": estimated gross {money(int(r['est_gross_pence']))}" if isinstance(r.get("est_gross_pence"), int) else "")
    ),
    "payroll_edited": lambda r, w: f"Edited payroll for {r.get('period', 'a period')}",
    "payroll_exported": lambda r, w: f"Exported payroll for {r.get('period', 'a period')} for your payroll software",
    "payroll_confirmed": lambda r, w: (
        f"Posted payroll for {r.get('period', 'a period')} to the ledger" + _pounds(r, "gross_pence")
    ),
    "payroll_reopened": lambda r, w: f"Reopened payroll for {r.get('period', 'a period')}; its entries were undone",
    # Contacts
    "contacts_refreshed": lambda r, w: f"Refreshed contacts from the ledger: {_plural(_n(r, 'contacts'), 'contact')}",
    "contact_edited": lambda r, w: "Edited a contact" + _fields(r),
    "contact_vat_status": lambda r, w: (
        "Set a supplier as " + VAT_STATUS.get(str(r.get("vat_status")), str(r.get("vat_status")))
    ),
    "contact_vat_checked": lambda r, w: (
        f"Checked VAT number {r.get('vrn', '')} with HMRC: "
        + ("registered" if r.get("registered") else "not VAT-registered")
        + {"hmrc-sandbox": " (HMRC sandbox)", "sample": " (sample)"}.get(str(r.get("source")), "")
    ),
    "contacts_imported": lambda r, w: (
        f"Imported {_plural(_n(r, 'added'), 'contact')} from your phone"
        + (f" ({_plural(_n(r, 'updated'), 'contact')} updated)" if _n(r, "updated") else "")
        if str(r.get("source")) == "phone"
        else "Imported contacts from Outlook"
    ),
    "contacts_not_same": lambda r, w: "Said some contacts are not the same business",
    "contacts_merged": lambda r, w: f"Merged into one ({r.get('name', 'a contact')})",
    "contacts_merge_undone": lambda r, w: "Undid a contact merge",
    # Vehicles and mileage
    "vehicle_added": lambda r, w: "Added a vehicle",
    "vehicle_changed": lambda r, w: "Changed a vehicle" + _fields(r),
    "vehicle_deleted": lambda r, w: "Removed a vehicle",
    "mileage_added": lambda r, w: "Logged a journey" + (f": {_qty(r['miles'])} miles" if r.get("miles") else ""),
    "mileage_changed": lambda r, w: "Changed a journey" + _fields(r),
    "mileage_deleted": lambda r, w: "Deleted a journey",
    "mileage_proposed": lambda r, w: (
        f"Proposed a mileage claim: {_plural(_n(r, 'journeys'), 'journey')}" + _pounds(r, "pence")
    ),
    "mileage_refreshed": lambda r, w: (
        f"Updated the mileage claim: {_plural(_n(r, 'journeys'), 'journey')}" + _pounds(r, "pence")
    ),
    # Reports
    "report_exported": lambda r, w: (
        "Saved "
        + {
            "pl": "the profit and loss",
            "aged": "the aged debtors and creditors",
            "vat": "the VAT summary",
            "trend": "the monthly trend",
            "all": "all reports",
        }.get(str(r.get("report")), "a report")
        + f" to {REPORTS} as a spreadsheet"
    ),
    # To-dos and housekeeping
    "todo_added": lambda r, w: "Added a to-do",
    "todo_deleted": lambda r, w: "Ticked off a to-do",
    "folders_renamed": lambda r, w: f"Renamed old folders: {_moved(r)}",
    # Ask (chat and voice) actions, from _System/audit/actions/
    "action_done": lambda r, w: (
        f"Approved from Ask: {_plain(r.get('result_md') or r.get('summary_md')) or 'an action'}"
    ),
    "action_rejected": lambda r, w: (
        f"Said no in Ask: {_plain(r.get('summary_md')) or 'an action'}"
        + (f" ({r['reason']})" if r.get("reason") else "")
    ),
    "action_failed": lambda r, w: f"An action from Ask did not finish: {_plain(r.get('error')) or 'unknown error'}",
}


def summarise(event: str, refs: dict[str, Any], who: str = "a document") -> str:
    """The sentence for one line; the kind's own name when it is not in SUMMARIES or its refs are odd."""
    fn = SUMMARIES.get(event)
    if fn is not None:
        try:
            return fn(refs, who)
        except (KeyError, TypeError, ValueError, AttributeError):
            log.warning("audit: could not summarise a %s line", event)
    return event.replace("_", " ").capitalize() or "Activity"


# --------------------------------------------------------------------------- #
# Normalising
# --------------------------------------------------------------------------- #


def actor_of(actor: str) -> tuple[Literal["user", "agent"], str]:
    """(kind, label). A person is always "You": one OneDrive is one business."""
    if actor.startswith("user:"):
        return "user", "You"
    name = actor.removeprefix("agent:")
    return "agent", AGENT_LABELS.get(name) or name.replace("-", " ").replace("_", " ").capitalize() or "Accnomos"


def _str(v: Any) -> str | None:
    return str(v) if isinstance(v, str | int) and str(v) else None


def refs_of(refs: dict[str, Any]) -> AuditRefs:
    moved = refs.get("moved") if isinstance(refs.get("moved"), list) else []
    first_moved = moved[0].get("new") if moved and isinstance(moved[0], dict) else None
    return AuditRefs(
        proposal=_str(refs.get("proposal")),
        event=_str(refs.get("event")),
        invoice=_str(refs.get("invoice")),
        action=_str(refs.get("action")),
        file=_str(refs.get("file") or refs.get("path") or first_moved),
    )


def _parse_ts(raw: Any) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return ts if ts.tzinfo is not None else None


def from_books_line(line: dict[str, Any], names: dict[str, str]) -> AuditEntry | None:
    """One _System/audit line; None when it has no usable ts, actor or action."""
    ts, actor, event = _parse_ts(line.get("ts")), line.get("actor"), line.get("action")
    if ts is None or not isinstance(actor, str) or not isinstance(event, str):
        return None
    raw = line.get("refs")
    refs: dict[str, Any] = raw if isinstance(raw, dict) else {}
    kind, label = actor_of(actor)
    who = names.get(str(refs.get("proposal") or ""), "a document")
    return AuditEntry(
        ts=ts,
        actor=actor,
        actor_kind=kind,
        actor_label=label,
        event=event,
        summary=summarise(event, refs, who),
        refs=refs_of(refs),
    )


ACTION_EVENTS = {"executed": "action_done", "rejected": "action_rejected", "failed": "action_failed"}


def from_action_line(line: dict[str, Any]) -> AuditEntry | None:
    """One _System/audit/actions line. "approving" is the claim before the work, not an outcome: skipped."""
    ts, event = _parse_ts(line.get("ts")), ACTION_EVENTS.get(str(line.get("event")))
    if ts is None or event is None:
        return None
    user = line.get("user")
    actor = f"user:{user}" if isinstance(user, str) and user else "agent:ask"
    kind, label = actor_of(actor)
    return AuditEntry(
        ts=ts,
        actor=actor,
        actor_kind=kind,
        actor_label=label,
        event=event,
        summary=summarise(event, line),
        refs=AuditRefs(action=_str(line.get("action_id"))),
    )


def matches(e: AuditEntry, actor: str | None, kind: str | None) -> bool:
    """`actor`: "user", "agent", an agent's name ("autopilot") or a full actor ("user:sam@…").
    `kind`: an event ("approved") or a family by prefix ("invoice" is every invoice_* line, "action" every Ask one)."""
    if actor:
        a = actor.strip().lower()
        if a not in (e.actor_kind, e.actor.lower(), e.actor.lower().removeprefix("agent:")):
            return False
    if kind:
        k = kind.strip().lower()
        if e.event != k and not e.event.startswith(k + "_"):
            return False
    return True


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


def months_between(start: date, end: date) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


async def _lines(books: Books, path: str) -> Iterable[dict[str, Any]]:
    try:
        raw = await books.storage.read(path)
    except FileNotFoundError:
        return []
    out: list[dict[str, Any]] = []
    for text in raw.decode("utf-8", "replace").splitlines():
        try:
            line = json.loads(text)
        except ValueError:
            continue
        if isinstance(line, dict):
            out.append(line)
    return out


async def _supplier_names(books: Books) -> dict[str, str]:
    """proposal id -> "Screwfix £12.00", for the summaries. Empty when a proposal file cannot be read."""
    try:
        proposals = await books.list_proposals()
    except ValueError:
        log.warning("audit: proposals unreadable; summaries say 'a document'")
        return {}
    return {
        p.id: f"{p.extracted.supplier_name} {money(round(p.extracted.gross_total * 100))}".strip() for p in proposals
    }


async def read(
    books: Books,
    start: date,
    end: date,
    actor: str | None = None,
    kind: str | None = None,
    limit: int = MAX_LIMIT,
) -> AuditPage:
    """Lines dated start..end (London days, inclusive) from both logs, newest first, at most `limit` (capped at 500)."""
    limit = max(1, min(limit, MAX_LIMIT))
    lo = datetime.combine(start, time.min, LONDON).astimezone(UTC)
    hi = datetime.combine(end + timedelta(days=1), time.min, LONDON).astimezone(UTC)
    # Monthly files are keyed by month, so read the months the window touches (older files were keyed by UTC
    # month, newer ones by London month; the window covers both).
    last = (hi - timedelta(microseconds=1)).date()
    months = months_between(lo.date(), last)
    # An action's lines go in the month it was proposed, so one approved just after midnight on the 1st is a
    # month early: read one month more of that log.
    action_months = months_between((lo.replace(day=1) - timedelta(days=1)).date(), last)

    books_lines = [ln for m in months for ln in await _lines(books, f"{AUDIT}/{m}.jsonl")]
    named = any(isinstance(r := ln.get("refs"), dict) and r.get("proposal") for ln in books_lines)
    names = await _supplier_names(books) if named else {}
    entries = [e for ln in books_lines if (e := from_books_line(ln, names))]
    for m in action_months:
        entries += [e for ln in await _lines(books, f"{ACTIONS_AUDIT}/{m}.jsonl") if (e := from_action_line(ln))]

    kept = [e for e in entries if lo <= e.ts < hi and matches(e, actor, kind)]
    kept.sort(key=lambda e: e.ts, reverse=True)
    return AuditPage(start=start, end=end, entries=kept[:limit], truncated=len(kept) > limit)
