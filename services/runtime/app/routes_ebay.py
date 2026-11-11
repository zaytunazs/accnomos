"""Connect eBay (app/ebay_sync.py): sign in at eBay, and fetch sales, refunds, fees, postage labels and payouts as
proposals for Review. Same headers as /books/*.

    GET  /books/ebay                 configured?, connected?, last sync and its summary, payouts seen
    POST /books/ebay/connect         {redirect_to, binding_hash} -> {url}: eBay's consent page, with a signed state
    GET  /books/ebay/callback        eBay sends the browser here (the RuName's accept URL); checks the state and
                                     forwards to the Bank page with code/state in the fragment
    POST /books/ebay/complete        {code, state, binding}: exchange the code and keep the sealed refresh token
    POST /books/ebay/sync            {days?}: fetch the last `days` days (90 by default) and propose what is new
    PUT  /books/ebay/settings        {fee_vat_number}: the VAT number on eBay's fee invoices (reclaim fee VAT)
    POST /books/ebay/disconnect      {confirm: true}: forget the connection here
    GET|POST /ebay/account-deletion  eBay's marketplace account deletion notifications (docs/EBAY_SETUP.md)

A demo session (app/demo.py) never reaches eBay: refused with a sentence (403). Books kept outside the UK: 404 with a
sentence (require_uk), like bank feeds; the card is UK-only.
"""

from __future__ import annotations

import hashlib
import os
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field, StrictBool

from app import demo
from app import ebay_sync as es
from app.billing import gauges
from app.books import Books
from app.region import rules_for
from app.routes_books import get_books, require_uk, require_user
from app.validation import StrictBody

router = APIRouter(prefix="/books/ebay", tags=["ebay"])
public = APIRouter(tags=["ebay"])


def not_in_demo(request: Request) -> None:
    if demo.is_demo_request(request):
        raise HTTPException(status_code=403, detail=es.DEMO_OFF)


CALLS_EBAY = [Depends(not_in_demo), require_uk()]


def _http(exc: es.EbaySyncError) -> HTTPException:
    return HTTPException(status_code=503 if isinstance(exc, es.NotConfigured) else 400, detail=str(exc))


@router.get("", response_model=es.EbayStatus)
async def ebay_status(request: Request, books: Books = Depends(get_books)) -> es.EbayStatus:
    if demo.is_demo_request(request):
        return await es.status(books, demo=True)
    if not (await rules_for(books)).uk:
        return es.EbayStatus(configured=False, reason="Connecting eBay works for UK books only.")
    return await es.status(books)


class StartBody(StrictBody):
    redirect_to: str = Field(max_length=500)
    binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$", max_length=64)


class StartResult(BaseModel):
    url: str


@router.post("/connect", response_model=StartResult, dependencies=CALLS_EBAY)
async def connect(body: StartBody, books: Books = Depends(get_books), user: str = Depends(require_user)) -> StartResult:
    await gauges.marketplace_room(books)  # marketplace connections on the plan (app/billing): 402 when none left
    try:
        return StartResult(url=es.start(body.redirect_to, body.binding_hash, user))
    except es.EbaySyncError as exc:
        raise _http(exc) from exc


@router.get("/callback", include_in_schema=False, response_model=None)
async def callback(
    state: str = "", code: str | None = None, error: str | None = None, error_description: str | None = None
) -> RedirectResponse | PlainTextResponse:
    """eBay's accept URL: `code` and `state` (and `expires_in`); an error or a decline comes back without a code."""
    try:
        st = es.read_state(state, use="callback")
    except (es.StateError, es.EbaySyncError):
        return PlainTextResponse(
            "eBay was not connected: this sign-in link has expired or was already used. Go back to Accnomos, Bank, "
            "and connect eBay again.",
            status_code=400,
        )
    frag = {"feed": "ebay", "state": state}
    frag |= (
        {"code": code}
        if code and not error
        else {"error": error or "missing_code", "error_description": error_description or ""}
    )
    return RedirectResponse(f"{st['redirect_to']}#{urlencode(frag)}", status_code=303)


class CompleteBody(StrictBody):
    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=2048)
    binding: str = Field(min_length=16, max_length=200)


@router.post("/complete", response_model=es.EbayStatus, dependencies=CALLS_EBAY)
async def complete(
    body: CompleteBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> es.EbayStatus:
    try:
        await es.connect(books, body.code, body.state, body.binding, user)
    except es.EbaySyncError as exc:
        raise _http(exc) from exc
    return await es.status(books)


class SyncBody(StrictBody):
    days: int = Field(default=es.DEFAULT_DAYS, ge=1, le=es.MAX_DAYS)


@router.post("/sync", response_model=es.SyncResult, dependencies=CALLS_EBAY)
async def sync(
    body: SyncBody | None = None, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> es.SyncResult:
    try:
        return await es.sync(books, user, (body or SyncBody()).days)
    except es.EbaySyncError as exc:
        raise _http(exc) from exc


class SettingsBody(StrictBody):
    fee_vat_number: str | None = Field(default=None, max_length=20)


@router.put("/settings", response_model=es.EbayStatus, dependencies=CALLS_EBAY)
async def settings(
    body: SettingsBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> es.EbayStatus:
    try:
        await es.set_fee_vat_number(books, (body.fee_vat_number or "").strip() or None, user)
    except es.EbaySyncError as exc:
        raise _http(exc) from exc
    return await es.status(books)


class ConfirmBody(StrictBody):
    confirm: StrictBool = False


class DisconnectResult(BaseModel):
    status: es.EbayStatus
    message: str


@router.post("/disconnect", response_model=DisconnectResult, dependencies=[Depends(not_in_demo)])
async def disconnect(
    body: ConfirmBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> DisconnectResult:
    if body.confirm is not True:
        raise HTTPException(status_code=400, detail="Nothing was changed: confirm in the app first (confirm: true)")
    try:
        message = await es.disconnect(books, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="eBay is not connected") from exc
    return DisconnectResult(status=await es.status(books), message=message)


# --------------------------------------------------------------------------- #
# eBay marketplace account deletion notifications
# https://developer.ebay.com/develop/guides/sell/marketplace-user-account-deletion (read 9 Nov 2026): eBay first
# GETs the endpoint with `challenge_code` and expects {"challengeResponse": sha256(challengeCode + verificationToken
# + endpoint) hex} as application/json; afterwards it POSTs a notification per closed eBay account. This runtime keeps
# no eBay data (each user's books are in their own storage, which it can only open with that user's token), so a
# notification is acknowledged and nothing else is done. Env: EBAY_DELETION_TOKEN, EBAY_DELETION_ENDPOINT.
# --------------------------------------------------------------------------- #


def _deletion_env() -> tuple[str, str] | None:
    token, endpoint = os.getenv("EBAY_DELETION_TOKEN", "").strip(), os.getenv("EBAY_DELETION_ENDPOINT", "").strip()
    return (token, endpoint) if token and endpoint else None


@public.get("/ebay/account-deletion", include_in_schema=False)
async def deletion_challenge(challenge_code: str = "") -> Response:
    env = _deletion_env()
    if env is None or not challenge_code:
        raise HTTPException(status_code=404, detail="Not set up")
    digest = hashlib.sha256((challenge_code + env[0] + env[1]).encode()).hexdigest()
    return JSONResponse({"challengeResponse": digest})


@public.post("/ebay/account-deletion", include_in_schema=False, status_code=204)
async def deletion_notice() -> Response:
    if _deletion_env() is None:
        raise HTTPException(status_code=404, detail="Not set up")
    return Response(status_code=204)
