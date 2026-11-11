"""Sync PayPal (app/paypal_sync.py). Same headers as /books/*.

GET  /payments/paypal/sync                       what was synced, waiting or decided; whether sync is possible
POST /payments/paypal/sync                       {days?, ai?}: read PayPal and propose each new transaction
GET  /payments/paypal/tieout                     PayPal's balance against 1240 PayPal clearing
POST /payments/paypal/sync/{id}/approve          {confirm: true, account?, vat_code?}: post it
POST /payments/paypal/sync/{id}/reject           {reason?}
GET  /payments/paypal/fees?start=&end=           PayPal's fees for the dates (synced history and the ledger)
"""

from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, StrictBool

from app import demo
from app import paypal_sync as ps
from app.ai.config import AiConfig
from app.books import Books, today
from app.invoicing import InvoiceError, InvoiceStateError
from app.routes_books import get_books, require_user
from app.validation import StrictBody

router = APIRouter(tags=["paypal sync"])
TID = r"^[A-Za-z0-9-]{1,64}$"


def _http(exc: InvoiceError) -> HTTPException:
    if isinstance(exc, ps.NotReady):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=409 if isinstance(exc, InvoiceStateError) else 400, detail=str(exc))


@router.get("/payments/paypal/sync", response_model=ps.SyncView)
async def sync_view(request: Request, books: Books = Depends(get_books)) -> ps.SyncView:
    return await ps.view(books, demo.is_demo_request(request))


class SyncBody(StrictBody):
    days: int | None = Field(default=None, ge=1, le=ps.MAX_DAYS)  # read this far back (default: since the last sync)
    ai: StrictBool = True  # ask the user's AI to code purchases no rule codes


def _ai(request: Request) -> AiConfig | None:
    try:
        return AiConfig.from_headers(request.headers)
    except ValueError:  # no usable AI settings: rules and code still code the purchases
        return None


@router.post("/payments/paypal/sync", response_model=ps.SyncResult)
async def run_sync(
    request: Request,
    body: SyncBody | None = None,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> ps.SyncResult:
    body = body or SyncBody()
    source, merchant, why = await ps.source_for(books, demo.is_demo_request(request))
    if source is None:
        raise HTTPException(status_code=503, detail=why)
    if source == "paypal":
        fetch = ps.paypal_fetch(merchant)
    else:
        hint, more = await ps.sample_hints(books)
        fetch = ps.sample_fetch(today(), hint, more)
    try:
        return await ps.sync(books, user, fetch, source, days=body.days, cfg=_ai(request) if body.ai else None)
    except InvoiceError as exc:
        raise _http(exc) from exc


class ApproveBody(StrictBody):
    confirm: StrictBool = False  # set by the app only after the user said yes
    account: str | None = Field(default=None, max_length=120)
    vat_code: str | None = Field(default=None, max_length=2)


@router.post("/payments/paypal/sync/{tid}/approve", response_model=ps.SyncItem)
async def approve(
    tid: str,
    body: ApproveBody,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> ps.SyncItem:
    if body.confirm is not True:
        raise HTTPException(status_code=400, detail="Nothing was posted: approve in the app first (confirm: true)")
    try:
        return await ps.approve(books, _tid(tid), user, account=body.account, vat_code=body.vat_code)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such synced PayPal transaction") from exc
    except InvoiceError as exc:
        raise _http(exc) from exc


class RejectBody(StrictBody):
    reason: str | None = Field(default=None, max_length=300)


@router.post("/payments/paypal/sync/{tid}/reject", response_model=ps.SyncItem)
async def reject(
    tid: str,
    body: RejectBody | None = None,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> ps.SyncItem:
    try:
        return await ps.reject(books, _tid(tid), user, (body or RejectBody()).reason)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such synced PayPal transaction") from exc
    except InvoiceError as exc:
        raise _http(exc) from exc


@router.get("/payments/paypal/tieout", response_model=ps.TieOut)
async def tieout(request: Request, books: Books = Depends(get_books)) -> ps.TieOut:
    """PayPal's own balance against 1240 PayPal clearing, with the gap explained. Read-only."""
    return await ps.tie_out(books, demo.is_demo_request(request))


@router.get("/payments/paypal/fees", response_model=ps.FeeSummary)
async def fees(start: date, end: date, books: Books = Depends(get_books)) -> ps.FeeSummary:
    try:
        return await ps.fee_summary(books, start, end)
    except InvoiceError as exc:
        raise _http(exc) from exc


def _tid(tid: str) -> str:
    if not re.fullmatch(TID, tid):
        raise HTTPException(status_code=404, detail="No such synced PayPal transaction")
    return tid
