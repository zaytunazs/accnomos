"""The user's books, as files in their own storage. No database: the folder is the source of truth.

Layout (relative to the books root):

    00 Inbox/                      new documents land here
    01 Receipts/{yyyy-mm}/         filed purchases and receipts
    02 Sales invoices/
    03 Bank statements/
    04 Needs a look/               anything a human should check
    05 VAT returns/  06 Reports/
    _System/docs/{sha256}.json     one per processed document (its hash is the duplicate key)
    _System/proposals/{id}.json    proposals and their decisions
    _System/audit/{yyyy-mm}.jsonl  append-only audit trail
    _System/Ledger/events/{yyyy-mm}/{ts}-{device}-{id}.json   immutable ledger events
    _System/rules.json  _System/cursors.json
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Literal

from accnomos_connectors.base import ConflictError, FileRef, StorageProvider
from accnomos_ledger.events import LedgerEvent
from pydantic import BaseModel, Field

from app.checks import parse_iso_date
from app.schemas import ExtractedDoc, Proposal, ProposalStatus

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
CURSORS = f"{SYSTEM}/cursors.json"

TREE = (INBOX, RECEIPTS, SALES, BANK, NEEDS_A_LOOK, VAT_RETURNS, REPORTS, DOCS, PROPOSALS, AUDIT, EVENTS)
DEVICE = "runtime"


def now() -> datetime:
    return datetime.now(UTC)


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

    async def apply_rules(self, doc: ExtractedDoc) -> str | None:
        """Account a stored rule says `doc` belongs to, or None."""
        rule = self.match_rule(doc, await self.load_rules())
        return rule.account if rule else None

    # ------------------------------------------------------------------ #
    # Documents and proposals
    # ------------------------------------------------------------------ #

    async def known_hashes(self) -> set[str]:
        return {f.name.removesuffix(".json") for f in await self.list_files(DOCS) if f.name.endswith(".json")}

    async def save_doc(self, meta: DocMeta) -> None:
        await self.write_json(f"{DOCS}/{meta.sha256}.json", meta.model_dump(mode="json"))

    async def save_proposal(self, p: Proposal) -> None:
        await self.write_json(f"{PROPOSALS}/{p.id}.json", p.model_dump(mode="json"))

    update_proposal = save_proposal

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

    async def audit(self, actor: str, action: str, refs: dict[str, Any]) -> None:
        """Append one JSON line to _System/audit/{yyyy-mm}.jsonl."""
        ts = now()
        line = json.dumps({"ts": ts.isoformat(), "actor": actor, "action": action, "refs": refs}, ensure_ascii=False)
        await self._update(f"{AUDIT}/{_month(ts)}.jsonl", lambda old: (old or b"") + line.encode() + b"\n")

    async def post_event(self, event: LedgerEvent) -> str:
        """Write an immutable ledger event and return its path. Refuses to overwrite."""
        ts = event.approved_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = f"{EVENTS}/{_month(event.date)}/{ts}-{DEVICE}-{event.id}.json"
        if any(f.name.endswith(f"-{event.id}.json") for f in await self.list_files(_split(path)[0])):
            raise FileExistsError(f"ledger event {event.id} already posted")
        await self.storage.write(path, event.model_dump_json(indent=2).encode())
        return path

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
        """`folder/name`, or 'name (2)', 'name (3)'... when that is taken."""
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
