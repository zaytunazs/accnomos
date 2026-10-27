"""Scan 00 Inbox: extract each new document, apply rules, save a proposal and file the document.

Proposals that match an Autopilot rule and pass every check are then posted by Autopilot
(app/autopilot.py); everything else waits in Review.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date

from accnomos_connectors.base import FileRef

from app import autopilot
from app import contacts as contact_book
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError
from app.approve import ApprovalError, approve
from app.books import Books, DocMeta, Rule, now
from app.paths import INBOX
from app.checks import SupplierKnowledge, decide
from app.invoicing import load_profile
from app.journal import with_expense_account
from app.mileage import MileageError, Vehicle, load_vehicles, prefill_vehicle
from app.pipeline import process_image, sha256_hex
from app.schemas import AutopilotDecision, Check, ExtractedDoc, Proposal

log = logging.getLogger(__name__)

IMAGE_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
PDF_MIME = "application/pdf"
ACTOR = "agent:extractor"


def mime_for(name: str) -> str | None:
    """MIME type for the documents we accept, by extension; None for anything else."""
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return IMAGE_MIME.get(ext) or (PDF_MIME if ext == ".pdf" else None)


def pdf_placeholder(name: str, digest: str) -> Proposal:
    """A needs-a-look proposal for a PDF we cannot read yet; the user types the amounts in on approval."""
    check = Check(code="PDF_UNSUPPORTED", ok=False, severity="fail", message="PDFs can't be read yet; please check by hand")
    doc = ExtractedDoc(
        doc_type="purchase_invoice", supplier_name=name.rsplit(".", 1)[0], supplier_vat_number=None,
        customer_name=None, invoice_number=None, date=now().date().isoformat(), currency="GBP", lines=[],
        net_total=0, vat_total=0, gross_total=0, payment_method=None, card_last4=None,
        category_guess="Sundry", confidence=0,
    )
    status, reasons = decide([check])
    return Proposal(
        id=uuid.uuid4().hex, doc_sha256=digest, extracted=doc, checks=[check], status=status, reasons=reasons,
        suggested_filename=name, journal_draft=[], model="none", elapsed_s=0,
    )


def apply_rule(p: Proposal, rule: Rule | None) -> None:
    """Point a purchase's expense legs at the rule's account and note it in the checks."""
    if rule is None or p.extracted.doc_type == "sales_invoice":
        return
    p.account_override = rule.account
    p.journal_draft = with_expense_account(p.journal_draft, rule.account)
    msg = f"Rule /{rule.match.supplier_regex}/ files this to {rule.account}"
    p.checks.append(Check(code="RULE_APPLIED", ok=True, severity="warn", message=msg))


async def _propose(
    books: Books, f: FileRef, mime: str, cfg: AiConfig, known: set[str], rules: list[Rule], business_name: str | None = None,
    vehicles: list[Vehicle] | None = None, period: tuple[date, date] | None = None, vat: VatContext | None = None,
) -> Proposal:
    data = await books.storage.read(f.path)
    if mime == PDF_MIME:
        return pdf_placeholder(f.name, sha256_hex(data))
    start, end = period or (None, None)
    vat = vat or VatContext([], True)
    p = await process_image(
        data, mime, cfg, known_hashes=frozenset(known), business_name=business_name, period_start=start, period_end=end,
        suppliers=vat.knowledge, business_vat_registered=vat.business_registered,
    )
    apply_rule(p, books.match_rule(p.extracted, rules))
    prefill_vehicle(p, vehicles or [])
    return p


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
        p.autopilot = AutopilotDecision(auto_approve=False, reasons=[f"Could not post: {exc}"], supplier_key=rule.supplier_key)
        await books.save_proposal(p)
        return p
    await autopilot.record_hit(books, rule.supplier_key)
    await books.audit_autopilot(autopilot.ACTOR, "approved", {
        "proposal": p.id, "event": posted.event_id, "doc": p.doc_sha256,
        "supplier_key": rule.supplier_key, "gross_pence": autopilot.pence(p.extracted.gross_total),
        "typical_gross_pence": rule.typical_gross_pence, "rule_from_proposal": rule.created_from_proposal_id,
        "reasons": p.autopilot.reasons if p.autopilot else [],
    })
    return posted


async def scan_inbox(
    books: Books, cfg: AiConfig, limit: int = 10, business_name: str | None = None, autopilot_on: bool = True,
    period: tuple[date, date] | None = None,
) -> list[Proposal]:
    """Backwards-compatible wrapper: proposals only."""
    proposals, _ = await scan_inbox_detailed(books, cfg, limit, business_name, autopilot_on, period)
    return proposals


async def scan_inbox_detailed(
    books: Books, cfg: AiConfig, limit: int = 10, business_name: str | None = None, autopilot_on: bool = True,
    period: tuple[date, date] | None = None,
) -> tuple[list[Proposal], list[dict]]:
    """Process up to `limit` documents from the Inbox and return the new proposals.

    A file whose hash we have already seen is not skipped silently: the DUPLICATE check sends it
    to Needs a look, so the Inbox never keeps files the user thinks were handled. Files the
    model cannot read stay in the Inbox for the next scan. `period` is the current VAT period: a document
    dated outside it gets a DATE_IN_PERIOD warning (never a fail; the ledger keeps the document's date).
    """
    await books.ensure_tree()
    known = await books.known_hashes()
    rules = await books.load_rules()
    auto_rules = await autopilot.load_rules(books)
    vehicles = await _vehicles(books)
    vat = await vat_context(books)
    out: list[Proposal] = []
    errors: list[dict] = []
    candidates = [(f, mime) for f in await books.list_files(INBOX) if (mime := mime_for(f.name))]
    for f, mime in candidates[:limit]:  # failures count too: `limit` caps model calls
        try:
            p = await _propose(books, f, mime, cfg, known, rules, business_name, vehicles, period, vat)
        except ExtractionError as exc:
            log.warning("extraction failed for %s: %s", f.path, exc)
            await books.audit(ACTOR, "extract_failed", {"path": f.path, "error": str(exc)[:200]})
            errors.append({"path": f.path, "error": str(exc)[:300]})
            continue
        p.source_name, p.created_at = f.name, now()
        await books.file_document(p, f.path)
        if p.doc_sha256 not in known:
            await books.save_doc(DocMeta(
                sha256=p.doc_sha256, source_name=f.name, mime=mime, size=f.size, proposal_id=p.id, filed_path=p.file_path,
            ))
            known.add(p.doc_sha256)
        rule = autopilot.match(p, auto_rules)
        if rule is not None:
            p.autopilot = autopilot.evaluate(p, rule, autopilot_on)
        await books.save_proposal(p)
        await books.audit(ACTOR, "proposed", {"proposal": p.id, "doc": p.doc_sha256, "status": p.status, "path": p.file_path})
        if rule is not None and p.autopilot and p.autopilot.auto_approve:
            p = await _autopilot_post(books, p, rule)
        out.append(p)
    await books.record_scan(now())
    if any(p.decided_by == autopilot.AUTOPILOT for p in out):
        await books.rebuild_safely(autopilot.ACTOR)
    return out, errors
