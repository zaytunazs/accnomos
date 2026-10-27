"""POST /extract: upload one receipt/invoice (photo, HEIC, PDF), get a `Proposal` back.

Needs `python-multipart` installed for `UploadFile`.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.ai.config import AiConfig, ai_config_from_request
from app.ai.extract import SUPPORTED_MIME, ExtractionError
from app.books import today
from app.formats import HEIC_MIME, MAX_BYTES, PDF_MIME, FormatError, prepare
from app.pipeline import process_document, sha256_hex
from app.routes_books import business_name
from app.schemas import Proposal
from app.vat_cycle import VatCycle, vat_cycle

ACCEPTED_MIME = SUPPORTED_MIME | {"image/jpg", PDF_MIME, HEIC_MIME, "image/heif"}

router = APIRouter(tags=["extract"])

# Demo-grade duplicate memory (per process). Replace with ledger-backed hashes.
_SEEN_HASHES: set[str] = set()


@router.post("/extract", response_model=Proposal)
async def extract(
    file: UploadFile = File(...),
    cfg: AiConfig = Depends(ai_config_from_request),
    business: str | None = Depends(business_name),
    cycle: VatCycle = Depends(vat_cycle),
) -> Proposal:
    mime = (file.content_type or "").lower()
    if mime not in ACCEPTED_MIME:
        raise HTTPException(status_code=415, detail=f"Send a PDF, JPEG, PNG, WebP or HEIC (got {mime or 'unknown'})")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"File over {MAX_BYTES // (1024 * 1024)} MB")
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    try:
        prep = await asyncio.to_thread(prepare, data, mime)
    except FormatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # A converted HEIC is the JPEG the caller would file; anything else is the file as sent
    digest = sha256_hex(prep.image if prep.converted_from and prep.image else data)
    try:
        start, end = cycle.current(today())
        proposal = await process_document(
            prep,
            cfg,
            known_hashes=frozenset(_SEEN_HASHES),
            digest=digest,
            business_name=business,
            period_start=start,
            period_end=end,
        )
    except ExtractionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _SEEN_HASHES.add(proposal.doc_sha256)
    return proposal
