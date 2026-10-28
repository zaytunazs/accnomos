"""Bank feeds (app/bank_feeds.py): connect a bank through TrueLayer, reconfirm the 90-day consent, and fetch its
transactions into the bank lines. Same headers as /books/*.

    GET  /books/bankfeeds                          is the feature on, the connections and their consent dates
    POST /books/bankfeeds/start                    {redirect_to, binding_hash} -> {url} to send the browser to
    GET  /books/bankfeeds/callback                 TrueLayer sends the browser here (no token); checks the state and
                                                   forwards to the Bank page with code/state in the fragment
    POST /books/bankfeeds/connect                  {code, state, binding}: exchange and save the connection
    POST /books/bankfeeds/sync                     fetch new transactions (the call made when the app opens)
    POST /books/bankfeeds/{id}/reconfirm           {confirm: true}: the user reconfirmed; extend the consent
    POST /books/bankfeeds/{id}/disconnect          {confirm: true}: forget it here and end it at TrueLayer
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field, StrictBool

from app import bank_feeds as bf
from app import demo
from app.books import Books
from app.routes_books import get_books, require_user
from app.validation import StrictBody

router = APIRouter(prefix="/books/bankfeeds", tags=["bank feeds"])
#: Connecting reaches the provider with the server's credentials: never from a demo sandbox (app/demo.py).
NOT_IN_DEMO = [Depends(demo.refuse_external("Connecting a bank feed"))]


def _http(exc: bf.BankFeedError) -> HTTPException:
    return HTTPException(status_code=503 if isinstance(exc, bf.NotConfigured) else 400, detail=str(exc))


@router.get("", response_model=bf.FeedStatus)
async def feed_status(books: Books = Depends(get_books)) -> bf.FeedStatus:
    return await bf.status(books)


class StartBody(StrictBody):
    redirect_to: str = Field(max_length=500)  # the Bank page on this app's origin
    binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$", max_length=64)  # sha256 of a secret only this browser keeps


class StartResult(BaseModel):
    url: str


@router.post("/start", response_model=StartResult, dependencies=NOT_IN_DEMO)
async def start(
    body: StartBody,
    books: Books = Depends(get_books),  # signed in to their books: no anonymous connections
    user: str = Depends(require_user),
) -> StartResult:
    try:
        return StartResult(url=bf.start(body.redirect_to, body.binding_hash, user))
    except bf.BankFeedError as exc:
        raise _http(exc) from exc


@router.get("/callback", include_in_schema=False, response_model=None)
async def callback(
    state: str = "", code: str | None = None, error: str | None = None, error_description: str | None = None
) -> RedirectResponse | PlainTextResponse:
    """TrueLayer sends the browser here with `code` and `state`, or `error`."""
    try:
        st = bf.read_state(state, use="callback")
    except (bf.StateError, bf.BankFeedError):
        return PlainTextResponse(
            "This bank sign-in link has expired or was already used. Go back to Accnomos, Bank, and connect again.",
            status_code=400,
        )
    frag = {"feed": "truelayer", "state": state}
    frag |= (
        {"code": code}
        if code and not error
        else {"error": error or "missing_code", "error_description": error_description or ""}
    )
    return RedirectResponse(f"{st['redirect_to']}#{urlencode(frag)}", status_code=303)


class ConnectBody(StrictBody):
    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=2048)
    binding: str = Field(min_length=16, max_length=200)


@router.post("/connect", response_model=bf.FeedStatus, dependencies=NOT_IN_DEMO)
async def connect(
    body: ConnectBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> bf.FeedStatus:
    try:
        await bf.connect(books, body.code, body.state, body.binding, user)
    except bf.BankFeedError as exc:
        raise _http(exc) from exc
    return await bf.status(books)


@router.post("/sync", response_model=bf.SyncResult)
async def sync(books: Books = Depends(get_books), user: str = Depends(require_user)) -> bf.SyncResult:
    try:
        return await bf.sync(books, user)
    except bf.BankFeedError as exc:
        raise _http(exc) from exc


class ConfirmBody(StrictBody):
    confirm: StrictBool = False  # set by the app only after the user said yes


def _confirmed(body: ConfirmBody) -> None:
    if body.confirm is not True:
        raise HTTPException(status_code=400, detail="Nothing was changed: confirm in the app first (confirm: true)")


@router.post("/{connection_id}/reconfirm", response_model=bf.ReconfirmResult)
async def reconfirm(
    connection_id: str, body: ConfirmBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> bf.ReconfirmResult:
    _confirmed(body)
    try:
        return await bf.reconfirm(books, connection_id, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such bank feed") from exc
    except bf.BankFeedError as exc:
        raise _http(exc) from exc


class DisconnectResult(BaseModel):
    status: bf.FeedStatus
    warning: str | None = None


@router.post("/{connection_id}/disconnect", response_model=DisconnectResult)
async def disconnect(
    connection_id: str, body: ConfirmBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> DisconnectResult:
    _confirmed(body)
    try:
        warning = await bf.disconnect(books, connection_id, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such bank feed") from exc
    return DisconnectResult(status=await bf.status(books), warning=warning)
