"""Document in, `Proposal` out.

hash -> crop -> extract -> repair -> checks -> (second read if unsure) -> decide -> verify (if passed) -> journal
-> filename.

`process_document` takes any accepted file once `app.formats.prepare` has made it readable (a PDF's first page and
its text, a HEIC as JPEG, an email body as text); `process_image` is the image path it shares.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from collections.abc import Callable
from datetime import date

from app.ai.config import AiConfig
from app.ai.crop import CropResult, crop_document, reread_image
from app.ai.extract import ExtractionError, extract_document
from app.ai.verify import verify
from app.checks import UNKNOWN_SUPPLIER, SupplierKnowledge, decide, run_checks
from app.formats import Prepared
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

_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
}
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
    image_bytes: bytes | None,
    mime: str | None,
    cfg: AiConfig,
    known_hashes: frozenset[str] | set[str] = frozenset(),
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    business_name: str | None = None,
    suppliers: Callable[[ExtractedDoc], SupplierKnowledge] | None = None,
    business_vat_registered: bool = True,
    text: str | None = None,
    digest: str | None = None,
    crop: bool = True,
    file_mime: str | None = None,
) -> Proposal:
    """Turn one document image (and/or its text) into a reviewable `Proposal`. Raises `ExtractionError`.

    `suppliers` looks the reading's supplier up in the books (app/contacts.py `supplier_knowledge`); without it
    every supplier is one the books don't know yet. `text` goes to the model with the image (or alone, when
    `image_bytes` is None); `digest` is the original file's hash when the image was made from it (a PDF page);
    `file_mime` is the filed file's type, for the suggested name's extension."""
    t0 = time.perf_counter()
    # Of the original file: duplicate detection must not depend on cropping
    digest = digest or sha256_hex(image_bytes or (text or "").encode())
    if image_bytes is not None and crop:
        cropped = await crop_document(image_bytes, cfg)
    else:
        cropped = CropResult(image_bytes or b"", None, "none", "not a photo" if image_bytes else "no image")
    page = cropped.image_bytes if image_bytes is not None else None

    async def read(img: bytes | None) -> tuple[ExtractedDoc, dict, list[Check], list[Check]]:
        if text is None:
            doc, meta = await extract_document(img, mime, cfg)
        else:
            doc, meta = await extract_document(img, mime, cfg, text=text)
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

    doc, meta, repairs, checks = await read(page)
    # At most one retry, and only on an image: the same text reads the same twice
    if page is not None and (why := second_read_reason(doc, checks)):
        try:
            second = await read(await reread_image(page))
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
        if text is None:
            verification = await verify(image_bytes, doc, cfg, mime=mime)
        else:
            verification = await verify(image_bytes, doc, cfg, mime=mime, text=text)
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
        suggested_filename=suggested_filename(doc, file_mime or mime or "image/jpeg"),
        journal_draft=draft_journal(doc),
        model=f"{meta['backend']}:{meta['model']}",
        verification=verification,
        repaired_by_code=[c.message for c in repairs if c.code in REPAIR_CODES],
        elapsed_s=round(time.perf_counter() - t0, 3),
        crop=cropped.public(),
    )


async def process_document(
    prep: Prepared,
    cfg: AiConfig,
    known_hashes: frozenset[str] | set[str] = frozenset(),
    *,
    digest: str,
    period_start: date | None = None,
    period_end: date | None = None,
    business_name: str | None = None,
    suppliers: Callable[[ExtractedDoc], SupplierKnowledge] | None = None,
    business_vat_registered: bool = True,
) -> Proposal:
    """A prepared file (app/formats.py) through the same checks and the same card. `digest` is the hash of the file
    that will be filed. Raises `ExtractionError`."""
    p = await process_image(
        prep.image,
        prep.mime,
        cfg,
        known_hashes,
        period_start=period_start,
        period_end=period_end,
        business_name=business_name,
        suppliers=suppliers,
        business_vat_registered=business_vat_registered,
        text=prep.text,
        digest=digest,
        crop=prep.kind == "image",  # a rendered PDF page is already the page
        file_mime=prep.source_mime,
    )
    if prep.note:  # ok=True: shown as a chip, never a reason
        p.checks.append(Check(code="SOURCE", ok=True, severity="warn", message=prep.note))
    return p
