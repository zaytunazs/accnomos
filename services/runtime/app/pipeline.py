"""Image in, `Proposal` out: hash -> crop -> extract -> checks -> decide -> journal -> filename."""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from datetime import date

from app.ai.config import AiConfig
from app.ai.crop import crop_document
from app.ai.extract import extract_document
from app.checks import decide, run_checks
from app.journal import draft_journal
from app.repair import repair
from app.schemas import Check, ExtractedDoc, Proposal

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
        elapsed_s=round(time.perf_counter() - t0, 3),
        crop=cropped.public(),
    )
