"""Scan "00 Inbox": extract each new document, apply rules, save a proposal and file the document."""

from __future__ import annotations

import logging
import uuid

from accnomos_connectors.base import FileRef

from app.ai.config import AiConfig
from app.ai.extract import ExtractionError
from app.books import INBOX, Books, DocMeta, Rule, now
from app.checks import decide
from app.journal import with_expense_account
from app.pipeline import process_image, sha256_hex
from app.schemas import Check, ExtractedDoc, Proposal

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


async def _propose(books: Books, f: FileRef, mime: str, cfg: AiConfig, known: set[str], rules: list[Rule], business_name: str | None = None) -> Proposal:
    data = await books.storage.read(f.path)
    if mime == PDF_MIME:
        return pdf_placeholder(f.name, sha256_hex(data))
    p = await process_image(data, mime, cfg, known_hashes=frozenset(known), business_name=business_name)
    apply_rule(p, books.match_rule(p.extracted, rules))
    return p


async def scan_inbox(books: Books, cfg: AiConfig, limit: int = 10, business_name: str | None = None) -> list[Proposal]:
    """Backwards-compatible wrapper: proposals only."""
    proposals, _ = await scan_inbox_detailed(books, cfg, limit, business_name)
    return proposals


async def scan_inbox_detailed(books: Books, cfg: AiConfig, limit: int = 10, business_name: str | None = None) -> tuple[list[Proposal], list[dict]]:
    """Process up to `limit` documents from the Inbox and return the new proposals.

    A file whose hash we have already seen is not skipped silently: the DUPLICATE check sends it
    to "04 Needs a look", so the Inbox never keeps files the user thinks were handled. Files the
    model cannot read stay in the Inbox for the next scan.
    """
    await books.ensure_tree()
    known = await books.known_hashes()
    rules = await books.load_rules()
    out: list[Proposal] = []
    errors: list[dict] = []
    candidates = [(f, mime) for f in await books.list_files(INBOX) if (mime := mime_for(f.name))]
    for f, mime in candidates[:limit]:  # failures count too: `limit` caps model calls
        try:
            p = await _propose(books, f, mime, cfg, known, rules, business_name)
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
        await books.save_proposal(p)
        await books.audit(ACTOR, "proposed", {"proposal": p.id, "doc": p.doc_sha256, "status": p.status, "path": p.file_path})
        out.append(p)
    await books.record_scan(now())
    return out, errors
