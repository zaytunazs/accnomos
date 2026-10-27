"""The user's books, as files in their own storage. No database: the folder is the source of truth.

Layout (relative to the books root):

    00 Inbox/                      new documents land here
    01 Receipts/{yyyy-mm}/         filed purchases and receipts
    02 Sales invoices/
    03 Bank statements/            imported bank statement CSVs, "{last date}_{bank}.csv"
    04 Needs a look/               anything a human should check
    05 VAT returns/  06 Reports/
    _System/docs/{sha256}.json     one per processed document (its hash is the duplicate key)
    _System/proposals/{id}.json    proposals and their decisions
    _System/audit/{yyyy-mm}.jsonl  append-only audit trail
    _System/Ledger/events/{yyyy-mm}/{ts}-{device}-{id}.json   immutable ledger events
    _System/bank/{sha256}.json     bank lines parsed from one statement (matches recorded on them)
    _System/rules.json  _System/cursors.json
    _System/Rules/rules.json       Autopilot rules, one per supplier (app/autopilot.py)
    _System/audit/autopilot/{yyyy-mm}.jsonl   one line per Autopilot decision that posted something
    _System/Jobs/jobs.json  _System/Staff/staff.json  _System/Timesheets/{yyyy-mm}.jsonl   (app/jobs.py)
    _System/Contacts/contacts.json customers and suppliers (app/contacts.py); no money is stored there
    _System/Vehicles/vehicles.json  _System/Mileage/{tax-year}.jsonl   vehicles and business journeys (app/mileage.py)
    _System/Payroll/runs/{yyyy-mm}.json   pay runs (estimates) prepared from timesheets (app/payroll.py)
    04 Payroll/{yyyy-mm}.csv       pay run exports for the payroll provider
    Books.xlsx                     read-only spreadsheet projection, rebuilt after every decision
The folder layout (every path, who writes it, which files are append-only) is in docs/ARCHITECTURE.md;
tests/test_integration.py checks that everything written fits it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Literal

from accnomos_connectors.base import ConflictError, FileRef, StorageProvider
from accnomos_ledger.bank import BankLine, BankLineStatus, BankName, detect_bank, parse_bank_csv
from accnomos_ledger.events import LedgerEvent
from accnomos_ledger.matching import Match, suggest_matches
from pydantic import BaseModel, Field

from app.ai.config import is_test_mode
from app.checks import parse_iso_date
from app.schemas import ExtractedDoc, Proposal, ProposalStatus
from app.validation import check_name

INBOX = "00 Inbox"
RECEIPTS = "01 Receipts"
SALES = "02 Sales invoices"
BANK = "03 Bank statements"
NEEDS_A_LOOK = "04 Needs a look"
VAT_RETURNS = "05 VAT returns"
REPORTS = "06 Reports"
SYSTEM = "_System"
DOCS = f"{SYSTEM}/docs"
PROPOSALS = f"{SYSTEM}/proposals"
AUDIT = f"{SYSTEM}/audit"
EVENTS = f"{SYSTEM}/Ledger/events"
RULES = f"{SYSTEM}/rules.json"
AUTOPILOT_RULES = f"{SYSTEM}/Rules/rules.json"
# OneDrive paths are case-insensitive, so this is the same folder as "_System/Audit/autopilot".
AUTOPILOT_AUDIT = f"{AUDIT}/autopilot"
CURSORS = f"{SYSTEM}/cursors.json"
BANK_LINES = f"{SYSTEM}/bank"
WORKBOOK = "Books.xlsx"
WORKBOOK_LIMIT = 4 * 1024 * 1024  # simple-upload size; bigger books still upload, but we say so in the log

TREE = (INBOX, RECEIPTS, SALES, BANK, NEEDS_A_LOOK, VAT_RETURNS, REPORTS, DOCS, PROPOSALS, AUDIT, EVENTS, BANK_LINES)
DEVICE = "runtime"
log = logging.getLogger(__name__)


def now() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    """Today, for "the current period" defaults. Test mode (app/testmode.py) pins it with ACCNOMOS_TEST_TODAY."""
    if is_test_mode() and (pinned := os.getenv("ACCNOMOS_TEST_TODAY")):
        return date.fromisoformat(pinned)
    return date.today()


class RuleMatch(BaseModel):
    supplier_regex: str


class Rule(BaseModel):
    """'Always file this supplier to that account.' Matched case-insensitively with re.search."""

    match: RuleMatch
    account: str
    vat_code: str | None = None
    source: Literal["user", "agent"] = "user"
    created_at: datetime = Field(default_factory=now)

    def matches(self, doc: ExtractedDoc) -> bool:
        try:
            return re.search(self.match.supplier_regex, doc.supplier_name, re.IGNORECASE) is not None
        except re.error:  # a hand-edited rules.json must not break scanning
            return False


class DocMeta(BaseModel):
    """What we know about one processed document; stored as _System/docs/{sha256}.json."""

    sha256: str
    source_name: str
    mime: str
    size: int
    proposal_id: str
    filed_path: str | None = None
    saved_at: datetime = Field(default_factory=now)


def _split(path: str) -> tuple[str, str]:
    parent, _, name = path.rpartition("/")
    return parent, name


def _with_suffix(name: str, n: int) -> str:
    """'a.jpg' -> 'a (2).jpg'."""
    stem, dot, ext = name.rpartition(".")
    return f"{stem} ({n}).{ext}" if dot and stem else f"{name} ({n})"


def _month(d: date | datetime) -> str:
    return f"{d.year:04d}-{d.month:02d}"


class BankMatchError(ValueError):
    """A bank line cannot be matched (or unmatched) as asked."""


_DONE = {"matched": "matched", "transfer": "marked as a transfer", "ignored": "ignored"}


class BankImport(BaseModel):
    sha256: str
    filed_path: str | None
    lines: int
    new_lines: int
    duplicate_file: bool = False
    bank: BankName = "bank"


class BankStatement(BaseModel):
    """One imported statement file, summarised from its stored lines."""

    path: str
    bank: str
    first_date: date
    last_date: date
    lines: int
    resolved: int  # matched, transfer or ignored
    money_in_pence: int
    money_out_pence: int  # negative


def bank_of(path: str) -> str:
    """'03 Bank statements/2026-10-20_starling (2).csv' -> 'starling'; older names give 'bank'."""
    m = re.match(r"\d{4}-\d{2}-\d{2}_([a-z]+)", _split(path)[1])
    return m.group(1) if m else "bank"


class Books:
    """Typed operations on the books folder over any StorageProvider."""

    def __init__(self, storage: StorageProvider) -> None:
        self.storage = storage

    # ------------------------------------------------------------------ #
    # Low-level helpers
    # ------------------------------------------------------------------ #

    async def ensure_tree(self) -> None:
        await self.storage.ensure_root()
        for folder in TREE:
            await self.storage.ensure_folder(folder)

    async def list_files(self, folder: str) -> list[FileRef]:
        """Files (not folders) in `folder`; empty when the folder does not exist yet."""
        try:
            return [f for f in await self.storage.list(folder) if not f.is_folder]
        except FileNotFoundError:
            return []

    async def _stat(self, path: str) -> FileRef | None:
        parent, name = _split(path)
        return next((f for f in await self.list_files(parent) if f.name == name), None)

    async def exists(self, path: str) -> bool:
        return await self._stat(path) is not None

    async def read_json(self, path: str, default: Any) -> Any:
        try:
            return json.loads(await self.storage.read(path))
        except FileNotFoundError:
            return default

    async def write_json(self, path: str, obj: Any) -> FileRef:
        return await self.storage.write(path, json.dumps(obj, indent=2, ensure_ascii=False).encode())

    async def _update(self, path: str, change: Callable[[bytes | None], bytes]) -> FileRef:
        """Read-modify-write guarded by If-Match; retried once if someone else wrote in between."""
        for attempt in range(2):
            ref = await self._stat(path)
            current = await self.storage.read(path) if ref else None
            try:
                return await self.storage.write(path, change(current), if_match=ref.etag if ref else None)
            except ConflictError:
                if attempt:
                    raise
        raise AssertionError("unreachable")

    async def _update_json(self, path: str, default: Any, change: Callable[[Any], Any]) -> FileRef:
        def apply(raw: bytes | None) -> bytes:
            obj = json.loads(raw) if raw else default
            return json.dumps(change(obj), indent=2, ensure_ascii=False).encode()

        return await self._update(path, apply)

    # ------------------------------------------------------------------ #
    # Rules
    # ------------------------------------------------------------------ #

    async def load_rules(self) -> list[Rule]:
        return [Rule.model_validate(r) for r in await self.read_json(RULES, [])]

    async def save_rules(self, rules: list[Rule]) -> None:
        payload = [r.model_dump(mode="json") for r in rules]
        await self._update_json(RULES, [], lambda _old: payload)

    async def add_rule(self, rule: Rule) -> None:
        """Append `rule`, replacing any existing rule with the same supplier pattern."""
        new = rule.model_dump(mode="json")

        def change(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
            kept = [r for r in rules if r.get("match", {}).get("supplier_regex") != rule.match.supplier_regex]
            return [*kept, new]

        await self._update_json(RULES, [], change)

    @staticmethod
    def match_rule(doc: ExtractedDoc, rules: list[Rule]) -> Rule | None:
        """Matching rule (the most recently added wins), or None."""
        return next((r for r in reversed(rules) if r.matches(doc)), None)

    # ------------------------------------------------------------------ #
    # Documents and proposals
    # ------------------------------------------------------------------ #

    async def known_hashes(self) -> set[str]:
        return {f.name.removesuffix(".json") for f in await self.list_files(DOCS) if f.name.endswith(".json")}

    async def save_doc(self, meta: DocMeta) -> None:
        await self.write_json(f"{DOCS}/{meta.sha256}.json", meta.model_dump(mode="json"))

    async def save_proposal(self, p: Proposal) -> None:
        await self.write_json(f"{PROPOSALS}/{p.id}.json", p.model_dump(mode="json"))

    async def get_proposal(self, proposal_id: str) -> Proposal:
        """Raises FileNotFoundError (also for ids that are not plain hex, to keep paths inside _System)."""
        if not re.fullmatch(r"[0-9a-f]{8,64}", proposal_id):
            raise FileNotFoundError(proposal_id)
        return Proposal.model_validate_json(await self.storage.read(f"{PROPOSALS}/{proposal_id}.json"))

    async def list_proposals(self, status: ProposalStatus | None = None) -> list[Proposal]:
        out: list[Proposal] = []
        for f in await self.list_files(PROPOSALS):
            if f.name.endswith(".json"):
                p = Proposal.model_validate_json(await self.storage.read(f.path))
                if status is None or p.status == status:
                    out.append(p)
        return sorted(out, key=lambda p: p.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)

    # ------------------------------------------------------------------ #
    # Audit, ledger, cursors
    # ------------------------------------------------------------------ #

    async def audit(self, actor: str, action: str, refs: dict[str, Any], folder: str = AUDIT) -> None:
        """Append one line {"ts", "actor", "action", "refs"} to {folder}/{yyyy-mm}.jsonl (_System/audit by default).

        `actor` is "user:{email}" for something a person did, or "agent:{name}" for something done for them.
        """
        ts = now()
        line = json.dumps({"ts": ts.isoformat(), "actor": actor, "action": action, "refs": refs}, ensure_ascii=False)
        await self._update(f"{folder}/{_month(ts)}.jsonl", lambda old: (old or b"") + line.encode() + b"\n")

    async def audit_autopilot(self, actor: str, action: str, refs: dict[str, Any]) -> None:
        """The same line in _System/audit/autopilot/{yyyy-mm}.jsonl: Autopilot's own record, with its reasons."""
        await self.audit(actor, action, refs, folder=AUTOPILOT_AUDIT)

    async def post_event(self, event: LedgerEvent) -> str:
        """Write an immutable ledger event and return its path. Refuses to overwrite."""
        ts = event.approved_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = f"{EVENTS}/{_month(event.date)}/{ts}-{DEVICE}-{event.id}.json"
        if any(f.name.endswith(f"-{event.id}.json") for f in await self.list_files(_split(path)[0])):
            raise FileExistsError(f"ledger event {event.id} already posted")
        await self.storage.write(path, event.model_dump_json(indent=2).encode())
        return path

    async def list_events(self, start: date | None = None, end: date | None = None) -> list[LedgerEvent]:
        """All posted ledger events (optionally within [start, end] by event date), oldest first."""
        return [ev for _path, ev in await self.list_event_entries(start, end)]

    async def list_event_entries(
        self, start: date | None = None, end: date | None = None
    ) -> list[tuple[str, LedgerEvent]]:
        """(path, event) for posted ledger events within [start, end], oldest first.

        Months are folders, so only the months overlapping the range are read.
        """
        try:
            months = [f.name for f in await self.storage.list(EVENTS) if f.is_folder]
        except FileNotFoundError:
            return []
        if start:
            months = [m for m in months if m >= start.strftime("%Y-%m")]
        if end:
            months = [m for m in months if m <= end.strftime("%Y-%m")]
        entries: list[tuple[str, LedgerEvent]] = []
        for m in sorted(months):
            for f in await self.list_files(f"{EVENTS}/{m}"):
                if not f.name.endswith(".json"):
                    continue
                ev = LedgerEvent.model_validate_json(await self.storage.read(f.path))
                if (start is None or ev.date >= start) and (end is None or ev.date <= end):
                    entries.append((f.path, ev))
        entries.sort(key=lambda pe: (pe[1].date, pe[1].approved_at))
        return entries

    async def get_event(self, event_id: str) -> LedgerEvent:
        """One posted event by id. Raises FileNotFoundError (also for ids that are not plain hex)."""
        if not re.fullmatch(r"[0-9a-f]{8,64}", event_id):
            raise FileNotFoundError(event_id)
        ev = next((e for e in await self.list_events() if e.id == event_id), None)
        if ev is None:
            raise FileNotFoundError(event_id)
        return ev

    async def record_scan(self, when: datetime) -> None:
        await self._update_json(CURSORS, {}, lambda c: {**c, "last_scan": when.isoformat()})

    async def last_scan(self) -> datetime | None:
        raw = (await self.read_json(CURSORS, {})).get("last_scan")
        return datetime.fromisoformat(raw) if raw else None

    # ------------------------------------------------------------------ #
    # Filing
    # ------------------------------------------------------------------ #

    @staticmethod
    def filing_folder(doc: ExtractedDoc) -> str:
        """Where a document belongs once it is in order."""
        if doc.doc_type == "sales_invoice":
            return SALES
        d = parse_iso_date(doc.date) or now().date()
        return f"{RECEIPTS}/{_month(d)}"

    @classmethod
    def destination_folder(cls, p: Proposal) -> str:
        return NEEDS_A_LOOK if p.status == "needs_a_look" else cls.filing_folder(p.extracted)

    async def free_path(self, folder: str, name: str) -> str:
        """`folder/name`, or 'name (2)', 'name (3)'... when that is taken. Raises UnsafeName for a name that
        is not a plain file name (every filed document and statement passes through here)."""
        check_name(name)
        taken = {f.name for f in await self.list_files(folder)}
        candidate, n = name, 1
        while candidate in taken:
            n += 1
            candidate = _with_suffix(name, n)
        return f"{folder}/{candidate}"

    async def file_document(self, p: Proposal, src_path: str, folder: str | None = None) -> str:
        """Move the document to where `p` says it belongs; records and returns the new path."""
        folder = folder or self.destination_folder(p)
        if _split(src_path)[0] == folder:
            p.file_path = src_path
            return src_path
        await self.storage.ensure_folder(folder)
        dest = await self.free_path(folder, p.suggested_filename)
        await self.storage.move(src_path, dest)
        p.file_path = dest
        return dest

    # ------------------------------------------------------------------ #
    # Bank statements and matching (F7). Matching posts nothing: the bank
    # movement is already in each event's settlement line; we only record
    # which event a bank line pays for.
    # ------------------------------------------------------------------ #

    async def _bank_files(self) -> list[FileRef]:
        return [f for f in await self.list_files(BANK_LINES) if f.name.endswith(".json")]

    async def _read_bank_file(self, path: str) -> list[BankLine]:
        return [BankLine.model_validate(x) for x in await self.read_json(path, [])]

    async def stored_bank_lines(self) -> list[BankLine]:
        """Every imported bank line as stored, oldest first."""
        out: list[BankLine] = []
        for f in await self._bank_files():
            out += await self._read_bank_file(f.path)
        return sorted(out, key=lambda ln: (ln.date, ln.id))

    async def import_bank_csv(self, data: bytes, name: str, user: str = "user") -> BankImport:
        """Parse, file the statement as "03 Bank statements/{last date}_{bank}.csv" and store its lines.

        Re-importing the same file (same sha256) changes nothing; lines already imported from another
        statement (overlapping date ranges) are skipped. Raises accnomos_ledger.bank.BankCsvError.
        """
        sha = hashlib.sha256(data).hexdigest()
        store = f"{BANK_LINES}/{sha}.json"
        name = _split(name.replace("\\", "/"))[1] or "statement.csv"
        lines = parse_bank_csv(data, name)
        bank = detect_bank(data)
        if await self.exists(store):
            return BankImport(sha256=sha, filed_path=None, lines=len(lines), new_lines=0, duplicate_file=True, bank=bank)
        known = {ln.id for ln in await self.stored_bank_lines()}
        fresh = [ln for ln in lines if ln.id not in known]
        last = max((ln.date for ln in lines), default=now().date())
        filed = await self.free_path(BANK, f"{last.isoformat()}_{bank}.csv")
        await self.storage.write(filed, data)
        for ln in fresh:
            ln.source_file = filed
        await self.write_json(store, [ln.model_dump(mode="json") for ln in fresh])
        await self.audit(f"user:{user}", "bank_imported", {
            "sha256": sha, "path": filed, "uploaded_as": name, "bank": bank, "lines": len(lines), "new": len(fresh),
        })
        return BankImport(sha256=sha, filed_path=filed, lines=len(lines), new_lines=len(fresh), bank=bank)

    async def bank_statements(self) -> list[BankStatement]:
        """Imported statements, newest last date first, summarised from their stored lines."""
        by_file: dict[str, list[BankLine]] = {}
        for ln in await self.stored_bank_lines():
            by_file.setdefault(ln.source_file, []).append(ln)
        out = [
            BankStatement(
                path=path, bank=bank_of(path), first_date=min(ln.date for ln in lines),
                last_date=max(ln.date for ln in lines), lines=len(lines), resolved=sum(ln.resolved for ln in lines),
                money_in_pence=sum(ln.amount_pence for ln in lines if ln.amount_pence > 0),
                money_out_pence=sum(ln.amount_pence for ln in lines if ln.amount_pence < 0),
            )
            for path, lines in by_file.items()
        ]
        return sorted(out, key=lambda s: (s.last_date, s.path), reverse=True)

    async def card_hints(self) -> dict[str, str]:
        """Event id -> card last 4 digits, from the documents behind posted proposals."""
        return {
            p.event_id: p.extracted.card_last4
            for p in await self.list_proposals("posted") if p.event_id and p.extracted.card_last4
        }

    async def bank_suggestions(self, lines: list[BankLine] | None = None) -> list[Match]:
        lines = await self.stored_bank_lines() if lines is None else lines
        if all(ln.resolved for ln in lines):
            return []
        return suggest_matches(lines, await self.live_events(), await self.card_hints())

    async def live_events(self) -> list[LedgerEvent]:
        """Posted events that still stand: not a reversal, and not undone by one."""
        events = await self.list_events()
        reversed_ids = {e.reverses for e in events if e.reverses}
        return [e for e in events if e.kind != "reversal" and e.id not in reversed_ids]

    async def list_bank_lines(self, status: BankLineStatus | None = None) -> list[BankLine]:
        """Bank lines; open lines with a current suggestion show as "suggested" with the suggested event(s)."""
        lines = await self.stored_bank_lines()
        suggested = {m.line_id: m for m in await self.bank_suggestions(lines)}
        for ln in lines:
            if not ln.resolved and (m := suggested.get(ln.id)):
                ln.status, ln.matched_event_id, ln.matched_event_ids = "suggested", m.event_id, m.event_ids
        return [ln for ln in lines if status is None or ln.status == status]

    async def _find_line(self, line_id: str) -> tuple[str, BankLine]:
        """(bank file path, line). Raises FileNotFoundError, also for ids that are not 16 hex digits."""
        if not re.fullmatch(r"[0-9a-f]{16}", line_id):
            raise FileNotFoundError(line_id)
        for f in await self._bank_files():
            for ln in await self._read_bank_file(f.path):
                if ln.id == line_id:
                    return f.path, ln
        raise FileNotFoundError(line_id)

    async def _set_line(self, path: str, line_id: str, update: dict[str, Any]) -> None:
        def change(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [{**r, **update} if r.get("id") == line_id else r for r in rows]

        await self._update_json(path, [], change)

    async def confirm_match(self, line_id: str, event_ids: str | list[str], user: str) -> BankLine:
        """Record that bank line `line_id` pays for the event(s). Raises FileNotFoundError / BankMatchError."""
        ids = [event_ids] if isinstance(event_ids, str) else list(dict.fromkeys(event_ids))
        path, line = await self._find_line(line_id)
        if line.resolved:
            raise BankMatchError(f"This bank line is already {_DONE[line.status]}; undo that first")
        if not ids:
            raise BankMatchError("Choose the ledger entry this payment is for")
        posted = {e.id for e in await self.live_events()}
        if missing := [i for i in ids if i not in posted]:
            raise BankMatchError(f"No posted ledger entry {missing[0]} (or it has been undone)")
        taken = {i for ln in await self.stored_bank_lines() if ln.status == "matched" for i in ln.event_ids()}
        if clash := [i for i in ids if i in taken]:
            raise BankMatchError(f"Ledger entry {clash[0]} is already matched to another bank line")
        update: dict[str, Any] = {"status": "matched", "matched_event_id": ids[0], "matched_event_ids": ids}
        await self._set_line(path, line_id, update)
        await self.audit(f"user:{user}", "bank_matched", {"line": line_id, "events": ids, "file": path})
        await self.rebuild_safely(f"user:{user}")
        return line.model_copy(update=update)

    async def unmatch(self, line_id: str, user: str) -> BankLine:
        """Reopen a line: undo a match, a "transfer" or an "ignore"."""
        path, line = await self._find_line(line_id)
        if not line.resolved:
            raise BankMatchError("This bank line is still open; there is nothing to undo")
        update: dict[str, Any] = {"status": "unmatched", "matched_event_id": None, "matched_event_ids": []}
        await self._set_line(path, line_id, update)
        await self.audit(f"user:{user}", "bank_unmatched", {
            "line": line_id, "was": line.status, "events": line.event_ids(), "file": path,
        })
        await self.rebuild_safely(f"user:{user}")
        return line.model_copy(update=update)

    async def mark_line(self, line_id: str, status: Literal["transfer", "ignored"], user: str) -> BankLine:
        """Settle an open line without a ledger entry: money between own accounts, or nothing to book."""
        path, line = await self._find_line(line_id)
        if line.resolved:
            raise BankMatchError(f"This bank line is already {_DONE[line.status]}; undo that first")
        await self._set_line(path, line_id, {"status": status})
        await self.audit(f"user:{user}", f"bank_{status}", {"line": line_id, "file": path})
        await self.rebuild_safely(f"user:{user}")
        return line.model_copy(update={"status": status})

    async def link_proposal(self, line_id: str, proposal_id: str) -> None:
        path, _ = await self._find_line(line_id)
        await self._set_line(path, line_id, {"proposal_id": proposal_id})

    async def find_bank_line(self, line_id: str) -> BankLine:
        """Raises FileNotFoundError."""
        return (await self._find_line(line_id))[1]

    # ------------------------------------------------------------------ #
    # Books.xlsx projection (H25: written as a file, no Graph workbook API)
    # ------------------------------------------------------------------ #

    async def rebuild(self) -> FileRef:
        """Regenerate Books.xlsx at the root from the events, bank lines, open proposals, contacts, jobs, vehicles and pay runs."""
        from app import mileage, payroll
        from app.contacts import contact_book, load_ledger
        from app.jobs import summaries
        from app.projection import build_books_xlsx

        ledger = await load_ledger(self)
        contacts, _, _ = await contact_book(self, ledger)
        every = list(ledger.proposals.values())
        try:
            jobs = await summaries(self, ledger.events, [p for p in every if p.status == "posted"])
        except ValueError:  # a hand-edited jobs/staff/timesheet file must not stop the rest of the workbook
            log.exception("Jobs sheet left empty: a jobs file could not be read")
            jobs = []
        try:
            vehicles = await mileage.summary(self, mileage.tax_year_of(now().date()))
        except mileage.MileageError:  # a hand-edited vehicles or mileage file must not stop the rest of the workbook
            log.exception("Vehicles sheet left empty: a vehicles or mileage file could not be read")
            vehicles = None
        try:
            runs, names = await payroll.list_runs(self), await payroll.staff_names(self)
        except ValueError:  # a hand-edited pay run or staff file must not stop the rest of the workbook
            log.exception("Payroll sheet left empty: a pay run file could not be read")
            runs, names = [], {}
        proposals = [p for p in every if p.status in ("proposed", "needs_a_look")]
        proposals.sort(key=lambda p: p.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        data = build_books_xlsx(ledger.events, await self.list_bank_lines(), proposals,
                                jobs=jobs, contacts=contacts, ledger=ledger, mileage=vehicles,
                                payroll=runs, staff_names=names)
        if len(data) > WORKBOOK_LIMIT:
            log.warning("Books.xlsx is %d bytes, over the %d byte simple-upload size", len(data), WORKBOOK_LIMIT)
        return await self.storage.write(WORKBOOK, data)

    async def rebuild_safely(self, actor: str) -> FileRef | None:
        """rebuild(), but never fails the user's action: errors are logged and audited."""
        try:
            return await self.rebuild()
        except Exception as exc:  # noqa: BLE001  the spreadsheet is a convenience copy of the books
            log.exception("Books.xlsx rebuild failed")
            try:
                await self.audit(actor, "books_rebuild_failed", {"error": f"{type(exc).__name__}: {exc}"})
            except Exception:  # noqa: BLE001
                log.exception("could not audit the failed Books.xlsx rebuild")
            return None

    async def workbook_ref(self) -> FileRef | None:
        return next((f for f in await self.list_files("") if f.name == WORKBOOK), None)
