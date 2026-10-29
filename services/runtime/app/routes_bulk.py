"""/books/bulk/*: the bulk-upload batch jobs (app/bulk.py).

Same headers as /books/*; starting a job and confirming one need X-User and are
audited. Confirming only files documents to their normal folders and updates
their proposals; posting to the ledger still happens one card at a time in Review.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.ai.config import AiConfig, ai_config_from_request
from app.books import Books
from app.bulk import BulkJob, confirm_job, load_job, start_job
from app.routes_books import business_name, get_books, require_user
from app.validation import StrictBody
from app.vat_cycle import VatCycle, vat_cycle

router = APIRouter(prefix="/books/bulk", tags=["books"])


class ConfirmBody(StrictBody):
    edits: dict[str, str] = Field(default_factory=dict, max_length=50)  # bulk path -> corrected doc_type


class JobList(BaseModel):
    jobs: list[BulkJob]


@router.post("/jobs", response_model=BulkJob)
async def start(
    limit: int = Query(50, ge=1, le=200),
    books: Books = Depends(get_books),
    cfg: AiConfig = Depends(ai_config_from_request),
    business: str | None = Depends(business_name),
    cycle: VatCycle = Depends(vat_cycle),
    user: str = Depends(require_user),
) -> BulkJob:
    """Unpack the zips in 01 Bulk upload, classify what is there (two at a time) and return the batch summary."""
    del business, cycle  # the batch classifies now; periods and names apply when each card is approved
    try:
        job = await start_job(books, cfg, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await books.audit(f"user:{user}", "bulk_started", {"job": job.id, "rows": len(job.rows)})
    return job


@router.get("/jobs/{job_id}", response_model=BulkJob)
async def get_job(job_id: str, books: Books = Depends(get_books)) -> BulkJob:
    """One batch job: its summary and one row per document."""
    try:
        return await load_job(books, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such bulk job") from exc


@router.post("/jobs/{job_id}/confirm", response_model=BulkJob)
async def confirm(
    job_id: str,
    body: ConfirmBody | None = None,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> BulkJob:
    """Confirm all: apply per-row type corrections, then file every ready document to its normal folder."""
    try:
        job = await confirm_job(books, job_id, (body or ConfirmBody()).edits)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such bulk job") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await books.audit(
        f"user:{user}",
        "bulk_confirmed",
        {"job": job.id, "routed": sum(r.status == "routed" for r in job.rows)},
    )
    return job
