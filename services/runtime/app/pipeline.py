"""Image in, `Proposal` out.

hash -> crop -> extract -> repair -> checks -> (second read if unsure) -> decide -> verify (if passed) -> journal
-> filename.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from collections.abc import Callable
from datetime import date

from app.ai.config import AiConfig
from app.ai.crop import crop_document, reread_image
from app.ai.extract import ExtractionError, extract_document
from app.ai.verify import verify
from app.checks import UNKNOWN_SUPPLIER, SupplierKnowledge, decide, run_checks
from app.journal import draft_journal
from app.repair import REPAIR_CODES, repair
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

    def clean(text: str, limit: int) -> str:  # every part comes from the model, i.e. from the document
        return re.sub(r"\s+", " ", _UNSAFE.sub(" ", text)).strip(" .")[:limit].strip()

    supplier = clean(doc.supplier_name, 40) or "Unknown"
    symbol = _SYMBOL.get(doc.currency) or f"{clean(doc.currency, 3) or 'XXX'} "
    return (
        f"{clean(doc.date, 10) or 'undated'} {supplier} {symbol}{doc.gross_total:.2f}{_EXT.get(mime.lower(), '.jpg')}"
    )


def _shown(v: object) -> str:
    if v is None or v == "":
        return "none"
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def verification_check(v: Verification) -> Check:
    """Disagreement is a hard fail showing both readings; a verifier that could not run is only a warning."""
    if v.error:
        return Check(
            code="VERIFIER_AGREES", ok=False, severity="warn", message=f"Second reading unavailable ({v.model})"
        )
    if v.agree_all:
        return Check(
            code="VERIFIER_AGREES",
            ok=True,
            severity="fail",
            message=f"Verifier agrees · all {len(v.fields)} fields match",
        )
    diffs = [
        f"{_FIELD_LABEL.get(name, name)} {_shown(f.extractor)} vs {_shown(f.verifier)}"
        for name, f in v.fields.items()
        if not f.agree
    ]
    return Check(
        code="VERIFIER_AGREES", ok=False, severity="fail", message="Second reading differs: " + "; ".join(diffs)
    )


SECOND_READ_CONFIDENCE = 0.6  # Glimmer's "unsure" value is exactly 0.6 (it never reported lower on the 200-doc eval)
_ARITH_CODES = ("ARITH_TOTALS", "ARITH_LINES", "VAT_MATH")


def second_read_reason(doc: ExtractedDoc, checks: list[Check]) -> str | None:
    """Why the first reading deserves a second look at higher resolution, or None."""
    if any(not c.ok and c.severity == "fail" and c.code in _ARITH_CODES for c in checks):
        return "arithmetic did not add up"
    if doc.confidence <= SECOND_READ_CONFIDENCE:
        return f"model confidence {doc.confidence:.2f}"
    return None


def _check_score(checks: list[Check]) -> tuple[int, int]:
    """(failed, warned) counts; lower is better. Notes (ok=True) never count."""
    return (
        sum(not c.ok and c.severity == "fail" for c in checks),
        sum(not c.ok and c.severity == "warn" for c in checks),
    )


async def process_image(
    image_bytes: bytes,
    mime: str,
    cfg: AiConfig,
    known_hashes: frozenset[str] | set[str] = frozenset(),
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    business_name: str | None = None,
    suppliers: Callable[[ExtractedDoc], SupplierKnowledge] | None = None,
    business_vat_registered: bool = True,
) -> Proposal:
    """Turn one document image into a reviewable `Proposal`. Raises `ExtractionError`.

    `suppliers` looks the reading's supplier up in the books (app/contacts.py `supplier_knowledge`); without it
    every supplier is one the books don't know yet."""
    t0 = time.perf_counter()
    digest = sha256_hex(image_bytes)  # of the original file: duplicate detection must not depend on cropping
    cropped = await crop_document(image_bytes, cfg)

    async def read(img: bytes) -> tuple[ExtractedDoc, dict, list[Check], list[Check]]:
        doc, meta = await extract_document(img, mime, cfg)
        repairs = repair(doc, business_name)
        supplier = suppliers(doc) if suppliers else UNKNOWN_SUPPLIER  # after repair: it may swap the parties
        checks = run_checks(
            doc,
            known_hashes=known_hashes,
            this_hash=digest,
            period_start=period_start,
            period_end=period_end,
            supplier=supplier,
            business_vat_registered=business_vat_registered,
        )
        return doc, meta, repairs, repairs + checks

    doc, meta, repairs, checks = await read(cropped.image_bytes)
    if why := second_read_reason(doc, checks):  # at most one retry
        try:
            second = await read(await reread_image(cropped.image_bytes))
        except ExtractionError as exc:
            checks.append(
                Check(
                    code="SECOND_READ",
                    ok=True,
                    severity="warn",
                    message=f"Re-read ({why}) failed: {exc}; first reading kept",
                )
            )
        else:
            first_score, second_score = _check_score(checks), _check_score(second[3])
            if second_score < first_score:
                doc, meta, repairs, checks = second
            kept = "second" if second_score < first_score else "first"
            checks.append(
                Check(
                    code="SECOND_READ",
                    ok=True,
                    severity="warn",
                    message=(
                        f"Re-read at higher resolution ({why}); kept the {kept} reading "
                        f"(checks not passed: first {first_score[0]} failed, {first_score[1]} warned; "
                        f"second {second_score[0]} failed, {second_score[1]} warned)"
                    ),
                )
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
        repaired_by_code=[c.message for c in repairs if c.code in REPAIR_CODES],
        elapsed_s=round(time.perf_counter() - t0, 3),
        crop=cropped.public(),
    )
