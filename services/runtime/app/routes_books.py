"""/books/*: proposals stored in the user's own OneDrive.

Every request carries `X-Graph-Token` (and optionally `X-Account-Kind: personal|work`);
approvals and rejections also need `X-User`, the signed-in user's email.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from accnomos_connectors.msgraph import GraphStorageProvider
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel

from app.ai.config import AiConfig, ai_config_from_request
from app.approve import ApprovalError, ProposalStateError, approve, reject
from app.books import Books, now
from app.inbox import scan_inbox_detailed
from app.schemas import Proposal, ProposalStatus

router = APIRouter(prefix="/books", tags=["books"])


async def get_books(request: Request) -> AsyncIterator[Books]:
    """Books over the caller's OneDrive, for this request only. 401 without a token."""
    auth = request.headers.get("X-Graph-Token", "").strip()
    token = auth.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="X-Graph-Token header required")
    kind = (request.headers.get("X-Account-Kind") or "personal").strip().lower()
    if kind not in ("personal", "work"):
        raise HTTPException(status_code=400, detail="X-Account-Kind must be 'personal' or 'work'")
    storage = GraphStorageProvider(token, kind)  # type: ignore[arg-type]
    try:
        yield Books(storage)
    finally:
        await storage.aclose()


def require_user(x_user: str | None = Header(default=None)) -> str:
    if not x_user or not x_user.strip():
        raise HTTPException(status_code=400, detail="X-User header required")
    return x_user.strip()


class ApproveBody(BaseModel):
    edits: dict[str, Any] | None = None
    always: bool = False


class RejectBody(BaseModel):
    reason: str = ""


class Summary(BaseModel):
    proposed: int
    needs_a_look: int
    posted_this_month: int
    last_scan: datetime | None


async def _proposal(books: Books, proposal_id: str) -> Proposal:
    try:
        return await books.get_proposal(proposal_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such proposal") from exc


def _approval_http(exc: ApprovalError) -> HTTPException:
    return HTTPException(status_code=409 if isinstance(exc, ProposalStateError) else 400, detail=str(exc))


class ScanResult(BaseModel):
    proposals: list[Proposal]
    errors: list[dict] = []


@router.post("/scan", response_model=ScanResult)
async def scan(
    limit: int = Query(10, ge=1, le=50),
    books: Books = Depends(get_books),
    cfg: AiConfig = Depends(ai_config_from_request),
) -> ScanResult:
    proposals, errors = await scan_inbox_detailed(books, cfg, limit=limit)
    return ScanResult(proposals=proposals, errors=errors)


@router.get("/proposals", response_model=list[Proposal])
async def proposals(status: ProposalStatus | None = None, books: Books = Depends(get_books)) -> list[Proposal]:
    return await books.list_proposals(status)


@router.get("/proposals/{proposal_id}", response_model=Proposal)
async def proposal(proposal_id: str, books: Books = Depends(get_books)) -> Proposal:
    return await _proposal(books, proposal_id)


@router.post("/proposals/{proposal_id}/approve", response_model=Proposal)
async def approve_route(
    proposal_id: str, body: ApproveBody | None = None,
    books: Books = Depends(get_books), user: str = Depends(require_user),
) -> Proposal:
    body = body or ApproveBody()
    await _proposal(books, proposal_id)
    try:
        return await approve(books, proposal_id, user, body.edits, body.always)
    except ApprovalError as exc:
        raise _approval_http(exc) from exc


@router.post("/proposals/{proposal_id}/reject", response_model=Proposal)
async def reject_route(
    proposal_id: str, body: RejectBody | None = None,
    books: Books = Depends(get_books), user: str = Depends(require_user),
) -> Proposal:
    await _proposal(books, proposal_id)
    try:
        return await reject(books, proposal_id, user, (body or RejectBody()).reason)
    except ApprovalError as exc:
        raise _approval_http(exc) from exc


@router.get("/summary", response_model=Summary)
async def summary(books: Books = Depends(get_books)) -> Summary:
    every = await books.list_proposals()
    month = now().strftime("%Y-%m")
    return Summary(
        proposed=sum(p.status == "proposed" for p in every),
        needs_a_look=sum(p.status == "needs_a_look" for p in every),
        posted_this_month=sum(
            p.status == "posted" and p.decided_at is not None and p.decided_at.strftime("%Y-%m") == month for p in every
        ),
        last_scan=await books.last_scan(),
    )
