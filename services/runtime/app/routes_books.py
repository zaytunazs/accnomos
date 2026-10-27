"""/books/*: proposals stored in the user's own OneDrive.

Every request carries `X-Graph-Token` (and optionally `X-Account-Kind: personal|work`);
approvals, rejections and undos also need `X-User`, the signed-in user's email.
`X-Autopilot: off` on a scan skips auto-approval (docs/AUTOPILOT.md).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from accnomos_connectors.msgraph import GraphStorageProvider
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from accnomos_ledger.events import LedgerEvent

from app import autopilot, layout
from app.ai.config import AiConfig, ai_config_from_request, is_test_mode
from app.approve import ApprovalError, ProposalStateError, approve, reject, undo
from app.books import Books, now, today
from app.inbox import scan_inbox_detailed
from app.schemas import Proposal, ProposalStatus
from app.validation import StrictBody
from app.vat_cycle import VatCycle, vat_cycle

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
    if is_test_mode():
        from app import testmode

        books = Books((await testmode.state()).storage)
        await layout.on_first_contact(books, token, cache=False)  # fake storage is reset between tests
        yield books
        return
    storage = GraphStorageProvider(token, kind)  # type: ignore[arg-type]
    try:
        books = Books(storage)
        await layout.on_first_contact(books, token)  # old folder names -> current ones, once (app/layout.py)
        yield books
    finally:
        await storage.aclose()


# Settings travel as headers on every call (apps/web runtimeHeaders(), apps/mobile RuntimeClient._headers):
# X-Graph-Token + X-Account-Kind (get_books), X-AI-* + X-Meta-Api-Key (app.ai.config.ai_config_from_request),
# X-User (require_user / optional_user), X-Business-Name (business_name). Read them only through these.


def require_user(x_user: str | None = Header(default=None)) -> str:
    if not x_user or not x_user.strip():
        raise HTTPException(status_code=400, detail="X-User header required")
    return x_user.strip()


def optional_user(x_user: str | None = Header(default=None)) -> str | None:
    return (x_user or "").strip() or None


def business_name(x_business_name: str | None = Header(default=None)) -> str | None:
    """The user's business name, so the reader can tell their sales invoices from purchases."""
    return (x_business_name or "").strip() or None


class ApproveBody(StrictBody):
    edits: dict[str, Any] | None = Field(None, max_length=50)
    always: bool = False
    remember: bool = False  # "Always do this for <supplier>"; same as `always`


class RejectBody(StrictBody):
    reason: str = Field("", max_length=1000)


class Summary(BaseModel):
    proposed: int
    needs_a_look: int
    posted_this_month: int
    last_scan: datetime | None
    books_url: str | None = None  # Books.xlsx in the user's storage, when the provider gives a web link


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
    business: str | None = Depends(business_name),
    x_autopilot: str | None = Header(default=None),
    cycle: VatCycle = Depends(vat_cycle),
) -> ScanResult:
    """VAT settings (`stagger`/`start_month`/`months`, as for /books/deadlines) set the period dates are checked against."""
    autopilot_on = (x_autopilot or "on").strip().lower() != "off"
    period = cycle.current(today())
    proposals, errors = await scan_inbox_detailed(books, cfg, limit, business, autopilot_on, period)
    return ScanResult(proposals=proposals, errors=errors)


@router.get("/proposals", response_model=list[Proposal])
async def proposals(status: ProposalStatus | None = None, books: Books = Depends(get_books)) -> list[Proposal]:
    return await books.list_proposals(status)


@router.get("/proposals/{proposal_id}", response_model=Proposal)
async def proposal(proposal_id: str, books: Books = Depends(get_books)) -> Proposal:
    return await _proposal(books, proposal_id)


@router.post("/proposals/{proposal_id}/approve", response_model=Proposal)
@router.post("/approve/{proposal_id}", response_model=Proposal)
async def approve_route(
    proposal_id: str,
    body: ApproveBody | None = None,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> Proposal:
    body = body or ApproveBody()
    await _proposal(books, proposal_id)
    try:
        return await approve(books, proposal_id, user, body.edits, body.always or body.remember)
    except ApprovalError as exc:
        raise _approval_http(exc) from exc


@router.post("/proposals/{proposal_id}/reject", response_model=Proposal)
async def reject_route(
    proposal_id: str,
    body: RejectBody | None = None,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> Proposal:
    await _proposal(books, proposal_id)
    try:
        return await reject(books, proposal_id, user, (body or RejectBody()).reason)
    except ApprovalError as exc:
        raise _approval_http(exc) from exc


class UndoResult(BaseModel):
    reversal: LedgerEvent
    proposal: Proposal | None


@router.post("/undo/{event_id}", response_model=UndoResult)
async def undo_route(event_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> UndoResult:
    """Reverse a posted entry (a new reversal event; nothing is deleted) and put its proposal back in Review."""
    try:
        reversal, p = await undo(books, event_id, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such ledger entry") from exc
    except ApprovalError as exc:
        raise _approval_http(exc) from exc
    return UndoResult(reversal=reversal, proposal=p)


@router.get("/rules", response_model=list[autopilot.AutopilotRule])
async def rules(books: Books = Depends(get_books)) -> list[autopilot.AutopilotRule]:
    return await autopilot.load_rules(books)


@router.delete("/rules/{supplier_key}", response_model=autopilot.AutopilotRule)
async def delete_rule(
    supplier_key: str,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> autopilot.AutopilotRule:
    """Stop Autopilot for this supplier, and drop the account rule that was saved with it."""
    gone = await autopilot.remove_rule(books, supplier_key) if autopilot.KEY_RE.fullmatch(supplier_key) else None
    if gone is None:
        raise HTTPException(status_code=404, detail="No such rule")
    account_rules = await books.load_rules()
    kept = [
        r
        for r in account_rules
        if autopilot.supplier_key(re.sub(r"\\(.)", r"\1", r.match.supplier_regex)) != supplier_key
    ]
    if len(kept) != len(account_rules):
        await books.save_rules(kept)
    await books.audit(
        f"user:{user}",
        "rule_removed",
        {"supplier_key": supplier_key, "account_rules_removed": len(account_rules) - len(kept)},
    )
    return gone


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
        books_url=workbook.web_url if (workbook := await books.workbook_ref()) else None,
    )


class RebuildResult(BaseModel):
    path: str
    size: int
    books_url: str | None


@router.post("/rebuild", response_model=RebuildResult)
async def rebuild(books: Books = Depends(get_books)) -> RebuildResult:
    """Regenerate Books.xlsx now (it is also rebuilt after every approve, reject and bank match)."""
    ref = await books.rebuild()
    return RebuildResult(path=ref.path, size=ref.size, books_url=ref.web_url)


@router.get("/layout", response_model=layout.LayoutStatus)
async def folder_layout(books: Books = Depends(get_books)) -> layout.LayoutStatus:
    """Old-named folders, checked now: `moved` is what this call renamed (usually nothing, because get_books has
    already done it), `conflicts` are old and new folders side by side, which the Files page shows."""
    return await layout.migrate(books)
