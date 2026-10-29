"""Scan 00 Inbox: extract each new document, apply rules, save a proposal and file the document.

Photos (JPEG/PNG/WebP/HEIC), PDFs and email bodies saved as text (`.eml.txt`) are read; app/formats.py says how.
A HEIC photo is swapped for a JPEG in the Inbox (the HEIC is kept in `_System/Originals`), so the card can show it.
A file over 25 MB is not read and stays in the Inbox, reported as an error; any other file that cannot be read
(too many pixels or pages, damaged, password-protected) becomes a needs-a-look card that says why.

A document Outlook intake copied in carries the mailbox it came from (`source_mailbox`, from intake's seen-list
by content hash) on its proposal and its `proposed` audit line.

Proposals that match an Autopilot rule and pass every check are then posted by Autopilot
(app/autopilot.py); everything else waits in Review.

Every document has a time budget (SCAN_DOC_TIMEOUT_S, default 180 s) and every AI call within it a cap
(AI_CALL_TIMEOUT_S, default 90 s; app/ai/chain.py `limits`). A document that runs out of time stays in the Inbox and
is reported with a plain sentence, so one slow or silent provider can no longer hold a scan for many minutes.
The web app and the phone no longer wait on this route: they start a background job (app/scan_jobs.py) and poll it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from accnomos_connectors.base import FileRef
from app import autopilot
from app import contacts as contact_book
from app.ai import chain
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError
from app.approve import ApprovalError, approve
from app.books import SYSTEM, Books, DocMeta, Rule, now
from app.books import today as london_today
from app.checks import SupplierKnowledge, decide
from app.formats import MAX_BYTES, FormatError, guess_mime, prepare
from app.intake import SEEN
from app.invoicing import load_profile
from app.journal import with_expense_account
from app.mileage import MileageError, Vehicle, load_vehicles, prefill_vehicle
from app.paths import INBOX
from app.pipeline import process_document, sha256_hex
from app.schemas import AutopilotDecision, Check, ExtractedDoc, Proposal

log = logging.getLogger(__name__)

ACTOR = "agent:extractor"
ORIGINALS = f"{SYSTEM}/Originals"  # HEIC photos, once their JPEG is in the Inbox


def _env_s(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


DOC_TIMEOUT_S = _env_s("SCAN_DOC_TIMEOUT_S", 180)  # one document, every AI call included
AI_CALL_TIMEOUT_S = _env_s("AI_CALL_TIMEOUT_S", 90)  # one AI attempt, whoever serves it
GRACE_S = 10.0  # after the budget, the hard stop (a call that ignores its own cap)


class DocTimeout(ExtractionError):
    """The document used up its time budget. It stays in the Inbox."""


def timeout_message(seconds: float) -> str:
    return (
        f"The AI did not finish reading this within {seconds:.0f} seconds, so it was stopped. "
        "It stays in 00 Inbox: try again later, or type it in by hand."
    )


async def bounded[T](coro: Coroutine[Any, Any, T], seconds: float | None = None) -> T:
    """`coro` within the document budget: each AI call capped, a hard stop just after. Raises `DocTimeout`."""
    budget = DOC_TIMEOUT_S if seconds is None else seconds
    with chain.limits(call_s=AI_CALL_TIMEOUT_S, deadline=time.monotonic() + budget):
        try:
            return await asyncio.wait_for(coro, budget + GRACE_S)
        except TimeoutError:
            raise DocTimeout(timeout_message(budget)) from None


def unreadable_placeholder(name: str, digest: str, reason: str) -> Proposal:
    """A needs-a-look proposal for a file we cannot read; the user types the amounts in on approval."""
    return placeholder(name, digest, f"Not read: {reason}. Please check it by hand")


def placeholder(name: str, digest: str, message: str, code: str = "UNREADABLE") -> Proposal:
    """A needs-a-look card with no figures, saying `message`: the user types the amounts in, or rejects it."""
    check = Check(code=code, ok=False, severity="fail", message=message)
    doc = ExtractedDoc(
        doc_type="purchase_invoice",
        supplier_name=name.rsplit(".", 1)[0],
        supplier_vat_number=None,
        customer_name=None,
        invoice_number=None,
        date=london_today().isoformat(),
        currency="GBP",
        lines=[],
        net_total=0,
        vat_total=0,
        gross_total=0,
        payment_method=None,
        card_last4=None,
        category_guess="Sundry",
        confidence=0,
    )
    status, reasons = decide([check])
    return Proposal(
        id=uuid.uuid4().hex,
        doc_sha256=digest,
        extracted=doc,
        checks=[check],
        status=status,
        reasons=reasons,
        suggested_filename=name,
        journal_draft=[],
        model="none",
        elapsed_s=0,
    )


def apply_rule(p: Proposal, rule: Rule | None) -> None:
    """Point a purchase's expense legs at the rule's account and note it in the checks."""
    if rule is None or p.extracted.doc_type == "sales_invoice":
        return
    p.account_override = rule.account
    p.journal_draft = with_expense_account(p.journal_draft, rule.account)
    msg = f"Rule /{rule.match.supplier_regex}/ files this to {rule.account}"
    p.checks.append(Check(code="RULE_APPLIED", ok=True, severity="warn", message=msg))


async def _swap_for_jpeg(books: Books, f: FileRef, jpeg: bytes) -> FileRef:
    """Put the JPEG made from a HEIC photo in the Inbox in its place. The HEIC is moved, never deleted."""
    stem = f.name.rsplit(".", 1)[0]
    dest = await books.free_path(INBOX, f"{stem}.jpg")
    ref = await books.storage.write(dest, jpeg, create_only=True)
    await books.storage.ensure_folder(ORIGINALS)
    await books.storage.move(f.path, await books.free_path(ORIGINALS, f.name))
    return FileRef(id=ref.id, path=dest, name=dest.rsplit("/", 1)[-1], size=len(jpeg), etag=ref.etag)


async def _propose(
    books: Books,
    f: FileRef,
    mime: str,
    cfg: AiConfig,
    known: set[str],
    rules: list[Rule],
    business_name: str | None = None,
    vehicles: list[Vehicle] | None = None,
    period: tuple[date, date] | None = None,
    vat: VatContext | None = None,
) -> tuple[Proposal, FileRef, str]:
    """The proposal, the file to file (a HEIC's JPEG, else `f`) and that file's MIME type."""
    data = await books.storage.read(f.path)
    try:
        prep = await asyncio.to_thread(prepare, data, f.name)
    except FormatError as exc:
        return unreadable_placeholder(f.name, sha256_hex(data), str(exc)), f, mime
    if prep.converted_from and prep.image is not None:
        f, data = await _swap_for_jpeg(books, f, prep.image), prep.image
    start, end = period or (None, None)
    vat = vat or VatContext([], True)
    p = await bounded(
        process_document(
            prep,
            cfg,
            known_hashes=frozenset(known),
            digest=sha256_hex(data),
            business_name=business_name,
            period_start=start,
            period_end=end,
            suppliers=vat.knowledge,
            business_vat_registered=vat.business_registered,
        )
    )
    apply_rule(p, books.match_rule(p.extracted, rules))
    prefill_vehicle(p, vehicles or [])
    return p, f, prep.source_mime


@dataclass
class VatContext:
    """What the VAT number check needs from the books: the contacts (suppliers' VAT status) and whether the
    user's business is VAT-registered (Settings › Business)."""

    contacts: list[contact_book.Contact]
    business_registered: bool

    def knowledge(self, doc: ExtractedDoc) -> SupplierKnowledge:
        return contact_book.supplier_knowledge(self.contacts, doc)


async def vat_context(books: Books) -> VatContext:
    """Saved contacts only (the ledger is not re-read on every scan: approvals keep contacts.json up to date). A broken
    contacts or profile file only means every supplier is treated as new and the business as registered."""
    try:
        contacts = await contact_book.stored_contacts(books)
    except ValueError:
        log.warning("contacts file unreadable; scanning as if every supplier were new")
        contacts = []
    try:
        registered = (await load_profile(books)).is_vat_registered
    except ValueError:
        log.warning("invoice profile unreadable; scanning as a VAT-registered business")
        registered = True
    return VatContext(contacts, registered)


async def _vehicles(books: Books) -> list[Vehicle]:
    """The user's vehicles; a broken vehicles file only means no vehicle is pre-filled."""
    try:
        return await load_vehicles(books)
    except MileageError:
        log.warning("vehicles file unreadable; scanning without vehicle tagging")
        return []


async def _autopilot_post(books: Books, p: Proposal, rule: autopilot.AutopilotRule) -> Proposal:
    """Post `p` as Autopilot through the normal approve path, with an audit line; on failure leave it in Review."""
    try:
        posted = await approve(books, p.id, autopilot.AUTOPILOT, autopilot.edits_for(rule), rebuild=False)
    except ApprovalError as exc:
        p.autopilot = AutopilotDecision(
            auto_approve=False, reasons=[f"Could not post: {exc}"], supplier_key=rule.supplier_key
        )
        await books.save_proposal(p)
        return p
    await autopilot.record_hit(books, rule.supplier_key)
    await books.audit_autopilot(
        autopilot.ACTOR,
        "approved",
        {
            "proposal": p.id,
            "event": posted.event_id,
            "doc": p.doc_sha256,
            "supplier_key": rule.supplier_key,
            "gross_pence": autopilot.pence(p.extracted.gross_total),
            "typical_gross_pence": rule.typical_gross_pence,
            "rule_from_proposal": rule.created_from_proposal_id,
            "reasons": p.autopilot.reasons if p.autopilot else [],
        },
    )
    return posted


async def mailbox_sources(books: Books) -> dict[str, str]:
    """Content hash -> the address of the mailbox Outlook intake copied it from (newest copy wins)."""
    seen = await books.read_json(SEEN, [])
    return {s["sha256"]: s["mailbox"] for s in seen if isinstance(s, dict) and s.get("sha256") and s.get("mailbox")}


async def scan_inbox(
    books: Books,
    cfg: AiConfig,
    limit: int = 10,
    business_name: str | None = None,
    autopilot_on: bool = True,
    period: tuple[date, date] | None = None,
) -> list[Proposal]:
    """Backwards-compatible wrapper: proposals only."""
    proposals, _ = await scan_inbox_detailed(books, cfg, limit, business_name, autopilot_on, period)
    return proposals


@dataclass
class Waiting:
    """A document in the Inbox the next scan would read."""

    path: str
    name: str
    size: int


async def waiting(books: Books) -> list[Waiting]:
    """Readable documents in the Inbox, in the order a scan takes them (oldest name first, as listed). Reads only."""
    return [
        Waiting(path=f.path, name=f.name, size=f.size)
        for f in await books.list_files(INBOX)
        if guess_mime(f.name) and f.size <= MAX_BYTES
    ]


@dataclass
class ScanContext:
    """What every document of one scan is checked against, read once per scan."""

    known: set[str]
    rules: list[Rule]
    auto_rules: list[autopilot.AutopilotRule]
    vehicles: list[Vehicle]
    vat: VatContext
    business_name: str | None = None
    autopilot_on: bool = True
    period: tuple[date, date] | None = None
    sources: dict[str, str] | None = None  # intake's seen-list, read once and only when a file is filed
    earlier: list[Proposal] | None = None  # proposals already in the books, for Autopilot's same-document condition
    posted_by_autopilot: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # filing and saving: one document at a time


async def scan_context(
    books: Books,
    business_name: str | None = None,
    autopilot_on: bool = True,
    period: tuple[date, date] | None = None,
) -> ScanContext:
    await books.ensure_tree()
    return ScanContext(
        known=await books.known_hashes(),
        rules=await books.load_rules(),
        auto_rules=await autopilot.load_rules(books),
        vehicles=await _vehicles(books),
        vat=await vat_context(books),
        business_name=business_name,
        autopilot_on=autopilot_on,
        period=period,
    )


async def read_one(
    books: Books, f: FileRef, mime: str, cfg: AiConfig, ctx: ScanContext
) -> tuple[Proposal, FileRef, str]:
    """Read one Inbox file into a proposal (nothing saved yet). Raises `ExtractionError` (`DocTimeout` too)."""
    return await _propose(
        books, f, mime, cfg, ctx.known, ctx.rules, ctx.business_name, ctx.vehicles, ctx.period, ctx.vat
    )


async def commit(books: Books, ctx: ScanContext, p: Proposal, f: FileRef, mime: str) -> Proposal:
    """File the document, save its proposal with an audit line, and let Autopilot post it when a rule says so."""
    async with ctx.lock:
        p.source_name, p.created_at = f.name, now()
        if ctx.sources is None:
            ctx.sources = await mailbox_sources(books)
        p.source_mailbox = p.source_mailbox or ctx.sources.get(p.doc_sha256)
        await books.file_document(p, f.path)
        if p.doc_sha256 not in ctx.known:
            await books.save_doc(
                DocMeta(
                    sha256=p.doc_sha256,
                    source_name=f.name,
                    mime=mime,
                    size=f.size,
                    proposal_id=p.id,
                    filed_path=p.file_path,
                )
            )
            ctx.known.add(p.doc_sha256)
        rule = autopilot.match(p, ctx.auto_rules)
        if rule is not None:
            if ctx.earlier is None:  # read once per scan, and only when a rule could post something
                ctx.earlier = await books.list_proposals()
            p.autopilot = autopilot.evaluate(p, rule, ctx.autopilot_on, ctx.earlier)
        await books.save_proposal(p)
        if ctx.earlier is not None:
            ctx.earlier.append(p)
        refs = {"proposal": p.id, "doc": p.doc_sha256, "status": p.status, "path": p.file_path}
        if p.source_mailbox:
            refs["mailbox"] = p.source_mailbox
        await books.audit(ACTOR, "proposed", refs)
        if rule is not None and p.autopilot and p.autopilot.auto_approve:
            p = await _autopilot_post(books, p, rule)
            ctx.posted_by_autopilot = True
        return p


async def finish(books: Books, ctx: ScanContext) -> None:
    """After the last document: the scan time, and Books.xlsx when Autopilot posted anything."""
    await books.record_scan(now())
    if ctx.posted_by_autopilot:
        await books.rebuild_safely(autopilot.ACTOR)


def inbox_candidates(files: list[FileRef], errors: list[dict] | None = None) -> list[tuple[FileRef, str]]:
    """The Inbox files the reader takes, with their types; one over the size limit is reported, never downloaded."""
    out: list[tuple[FileRef, str]] = []
    for f in files:
        if not (mime := guess_mime(f.name)):
            continue
        if f.size > MAX_BYTES:  # never downloaded; stays in the Inbox until the user replaces it
            if errors is not None:
                errors.append({"path": f.path, "error": f"File is over {MAX_BYTES // (1024 * 1024)} MB; not read"})
            continue
        out.append((f, mime))
    return out


async def scan_inbox_detailed(
    books: Books,
    cfg: AiConfig,
    limit: int = 10,
    business_name: str | None = None,
    autopilot_on: bool = True,
    period: tuple[date, date] | None = None,
    skip: frozenset[str] = frozenset(),
) -> tuple[list[Proposal], list[dict]]:
    """Process up to `limit` documents from the Inbox and return the new proposals.

    A file whose hash we have already seen is not skipped silently: the DUPLICATE check sends it
    to Needs a look, so the Inbox never keeps files the user thinks were handled. Files the
    model cannot read (or not in time) stay in the Inbox for the next scan. `period` is the current VAT period: a
    document dated outside it gets a DATE_IN_PERIOD warning (never a fail; the ledger keeps the document's date).
    `skip`: Inbox paths a background job is reading now (app/scan_jobs.py), left to it.
    """
    ctx = await scan_context(books, business_name, autopilot_on, period)
    out: list[Proposal] = []
    errors: list[dict] = []
    candidates = [c for c in inbox_candidates(await books.list_files(INBOX), errors) if c[0].path not in skip]
    for i, (f, mime) in enumerate(candidates[:limit]):  # failures count too: `limit` caps model calls
        t0 = time.perf_counter()
        try:
            p, f, mime = await read_one(books, f, mime, cfg, ctx)
        except ExtractionError as exc:
            log.warning("scan: document %d of %d not read (%s)", i + 1, min(limit, len(candidates)), type(exc).__name__)
            await books.audit(ACTOR, "extract_failed", {"path": f.path, "error": str(exc)[:200]})
            errors.append({"path": f.path, "error": str(exc)[:300]})
            continue
        out.append(await commit(books, ctx, p, f, mime))
        log.info("scan: document %d of %d read in %.1f s", i + 1, min(limit, len(candidates)), time.perf_counter() - t0)
    await finish(books, ctx)
    return out, errors
