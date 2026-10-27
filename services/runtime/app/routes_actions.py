"""POST /actions/approve and /actions/reject: the user's answer to an action Ask proposed (app/actions.py).

The body carries the proposal exactly as /books/ask returned it; the runtime keeps nothing between the two
calls. Same headers as /books/* (`X-Graph-Token`, `X-Account-Kind`, `X-User`). Approving with the token the
proposal was made with is required: a proposal from another session fails its signature check.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import actions
from app.books import Books
from app.routes_books import get_books, require_user
from app.schemas import ProposedAction

router = APIRouter(prefix="/actions", tags=["actions"])


def graph_token(request: Request) -> str:
    token = request.headers.get("X-Graph-Token", "").strip().removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="X-Graph-Token header required")
    return token


def _mail_sender(token: str) -> Any:
    """() -> a Graph mail sender, or None on a build without sending (it lands with invoicing)."""

    def make() -> Any:
        try:
            from accnomos_connectors.msgraph import GraphMailSender  # type: ignore[attr-defined]
        except ImportError:
            return None
        return GraphMailSender(token)

    return make


class ApproveBody(BaseModel):
    action: ProposedAction


class RejectBody(BaseModel):
    action: ProposedAction
    reason: str | None = Field(None, max_length=300)


class Rejected(BaseModel):
    action_id: str
    status: str = "rejected"


@router.post("/approve", response_model=actions.ActionResult)
async def approve(
    body: ApproveBody, books: Books = Depends(get_books), user: str = Depends(require_user), token: str = Depends(graph_token),
) -> actions.ActionResult:
    """Execute the action once. Approving the same action again returns the first result (status already_done)."""
    ctx = actions.Context(books=books, user=user, graph_token=token, mail_sender=_mail_sender(token))
    try:
        return await actions.approve(body.action, ctx)
    except actions.ActionError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except (ValueError, LookupError) as exc:  # the module refused (closed job, unknown staff, bad invoice)
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/reject", response_model=Rejected)
async def reject(
    body: RejectBody, books: Books = Depends(get_books), user: str = Depends(require_user), token: str = Depends(graph_token),
) -> Rejected:
    """Record the no in the actions audit log. Nothing else changes."""
    try:
        await actions.reject(body.action, actions.Context(books=books, user=user, graph_token=token), body.reason)
    except actions.ActionError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return Rejected(action_id=body.action.id)
