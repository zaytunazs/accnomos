"""Image in, `Proposal` out: hash -> crop -> extract -> checks -> decide -> verify (if passed) -> journal -> filename."""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from datetime import date

from app.ai.config import AiConfig
from app.ai.crop import crop_document
from app.ai.extract import extract_document
from app.ai.verify import verify
from app.checks import decide, run_checks
from app.journal import draft_journal
from app.repair import repair
from app.schemas import Check, ExtractedDoc, Proposal, Verification

_FIELD_LABEL = {
    "supplier_name": "supplier",
    "supplier_vat_number": "VAT number",
    "date": "date",
    "net_total": "net",
    "vat_total": "VAT",
    "gross_total": "total",
}

_EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_SYMBOL = {"GBP": "£", "EUR": "€", "USD": "$"}
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def suggested_filename(doc: ExtractedDoc, mime: str) -> str:
    """e.g. '2026-10-21 Screwfix £38.47.jpg' (filesystem-safe, supplier max 40 chars)."""
    supplier = re.sub(r"\s+", " ", _UNSAFE.sub(" ", doc.supplier_name)).strip()[:40].strip() or "Unknown"
    symbol = _SYMBOL.get(doc.currency, f"{doc.currency} ")
    return f"{doc.date} {supplier} {symbol}{doc.gross_total:.2f}{_EXT.get(mime.lower(), '.jpg')}"


def _shown(v: object) -> str:
    if v is None or v == "":
        return "none"
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def verification_check(v: Verification) -> Check:
    """Disagreement is a hard fail showing both readings; a verifier that could not run is only a warning."""
    if v.error:
        return Check(code="VERIFIER_AGREES", ok=False, severity="warn", message=f"Second reading unavailable ({v.model})")
    if v.agree_all:
        return Check(code="VERIFIER_AGREES", ok=True, severity="fail", message=f"Verifier agrees · all {len(v.fields)} fields match")
    diffs = [
        f"{_FIELD_LABEL.get(name, name)} {_shown(f.extractor)} vs {_shown(f.verifier)}"
        for name, f in v.fields.items()
        if not f.agree
    ]
    return Check(code="VERIFIER_AGREES", ok=False, severity="fail", message="Second reading differs: " + "; ".join(diffs))


async def process_image(
    image_bytes: bytes,
    mime: str,
    cfg: AiConfig,
    known_hashes: frozenset[str] | set[str] = frozenset(),
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    business_name: str | None = None,
) -> Proposal:
    """Turn one document image into a reviewable `Proposal`. Raises `ExtractionError`."""
    t0 = time.perf_counter()
    digest = sha256_hex(image_bytes)  # of the original file: duplicate detection must not depend on cropping
    cropped = await crop_document(image_bytes, cfg)
    doc, meta = await extract_document(cropped.image_bytes, mime, cfg)
    repairs = repair(doc, business_name)
    checks = repairs + run_checks(
        doc, known_hashes=known_hashes, this_hash=digest, period_start=period_start, period_end=period_end
    )
    if cropped.box is not None:  # ok=True: shown as a chip, never a reason
        checks.append(Check(code="CROP", ok=True, severity="warn", message=f"{cropped.note} {list(cropped.box)}"))
    status, reasons = decide(checks)
    verification = None
    if status == "proposed":  # only spend a second model call on readings that passed every check
        verification = await verify(image_bytes, doc, cfg, mime=mime)
        if verification is not None:
            checks.append(verification_check(verification))
            status, reasons = decide(checks)
    return Proposal(
        id=uuid.uuid4().hex,
        doc_sha256=digest,
        extracted=doc,
        checks=checks,
        status=status,
        reasons=reasons,
        suggested_filename=suggested_filename(doc, mime),
        journal_draft=draft_journal(doc),
        model=f"{meta['backend']}:{meta['model']}",
        verification=verification,
        elapsed_s=round(time.perf_counter() - t0, 3),
        crop=cropped.public(),
    )
