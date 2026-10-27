"""POST /extract: upload one receipt/invoice image, get a `Proposal` back.

Needs `python-multipart` installed for `UploadFile`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.ai.config import AiConfig, ai_config_from_request
from app.ai.extract import SUPPORTED_MIME, ExtractionError
from app.books import today
from app.pipeline import process_image
from app.routes_books import business_name
from app.schemas import Proposal
from app.vat_cycle import VatCycle, vat_cycle

MAX_BYTES = 15 * 1024 * 1024

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
    if mime == "image/jpg":
        mime = "image/jpeg"
    if mime not in SUPPORTED_MIME:
        raise HTTPException(status_code=415, detail=f"Send JPEG, PNG or WebP (got {mime or 'unknown'})")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image over 15 MB")
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    try:
        start, end = cycle.current(today())
        proposal = await process_image(
            data, mime, cfg, known_hashes=frozenset(_SEEN_HASHES), business_name=business, period_start=start, period_end=end,
        )
    except ExtractionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _SEEN_HASHES.add(proposal.doc_sha256)
    return proposal
