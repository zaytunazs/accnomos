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
    GET  /books/bankfeeds/duplicates               feed lines left out as already in a statement (kept, not counted)
    POST /books/bankfeeds/duplicates/{line}/restore {confirm: true}: "not a duplicate": add it to the bank lines

In a demo session (`X-Demo-Session`, app/demo.py) the same routes work against TrueLayer's sandbox only, with its mock
bank only, into that demo's in-memory books; the signed state names the demo session (by a hash), so the callback's
code connects only in the demo that started it. No sandbox on this server: refused (403) with the reason.
docs/BANK_FEED_SANDBOX_DEMO.md.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field, StrictBool

from app import bank_feeds as bf
from app import demo
from app.billing import gauges
from app.books import Books
from app.region import rules_for
from app.routes_books import get_books, require_uk, require_user
from app.validation import StrictBody

router = APIRouter(prefix="/books/bankfeeds", tags=["bank feeds"])


def sandbox_only_in_demo(request: Request) -> None:
    """A demo session (app/demo.py) may connect, fetch and reconfirm only TrueLayer's sandbox test bank, into the
    demo's own in-memory books (get_books gives a demo its books; the server's real data is never reached). When this
    server has no TrueLayer sandbox (off, or pointed at live banks), it is refused with the reason, as before."""
    if demo.is_demo_request(request) and (why := bf.demo_refusal()) is not None:
        detail = f"Connecting a bank feed is switched off in the demo sandbox. {why}"
        raise HTTPException(status_code=403, detail=detail)


def _demo_session(request: Request) -> str | None:
    """This demo's session id (checked: get_books already refused a forged or ended one), or None outside a demo."""
    s = demo.from_request(request)
    return s.id if s is not None else None


#: Open Banking through TrueLayer reaches UK banks only: books kept in another country upload statements instead.
#: In a demo, TrueLayer's sandbox only (docs/BANK_FEED_SANDBOX_DEMO.md).
CALLS_TRUELAYER = [Depends(sandbox_only_in_demo), require_uk()]
ABROAD = (
    "Connecting a bank works with UK banks only. Upload your bank statement (CSV or PDF) instead: "
    "it is matched the same way."
)


def _http(exc: bf.BankFeedError) -> HTTPException:
    return HTTPException(status_code=503 if isinstance(exc, bf.NotConfigured) else 400, detail=str(exc))


@router.get("", response_model=bf.FeedStatus)
async def feed_status(request: Request, books: Books = Depends(get_books)) -> bf.FeedStatus:
    if not (await rules_for(books)).uk:
        return bf.FeedStatus(available=False, reason=ABROAD)
    return await bf.status(books, demo=demo.is_demo_request(request))


class StartBody(StrictBody):
    redirect_to: str = Field(max_length=500)  # the Bank page on this app's origin
    binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$", max_length=64)  # sha256 of a secret only this browser keeps


class StartResult(BaseModel):
    url: str


@router.post("/start", response_model=StartResult, dependencies=CALLS_TRUELAYER)
async def start(
    body: StartBody,
    request: Request,
    books: Books = Depends(get_books),  # signed in to their books (or a live demo session): no anonymous connections
    user: str = Depends(require_user),
) -> StartResult:
    await gauges.bank_feed_room(books)  # the plan's live bank feeds (app/billing): 402 when all are in use
    try:
        return StartResult(url=bf.start(body.redirect_to, body.binding_hash, user, _demo_session(request)))
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


@router.post("/connect", response_model=bf.FeedStatus, dependencies=CALLS_TRUELAYER)
async def connect(
    body: ConnectBody, request: Request, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> bf.FeedStatus:
    sid = _demo_session(request)
    try:
        await bf.connect(books, body.code, body.state, body.binding, user, sid)
    except bf.BankFeedError as exc:
        raise _http(exc) from exc
    return await bf.status(books, demo=sid is not None)


@router.post("/sync", response_model=bf.SyncResult, dependencies=[Depends(sandbox_only_in_demo)])
async def sync(request: Request, books: Books = Depends(get_books), user: str = Depends(require_user)) -> bf.SyncResult:
    try:
        return await bf.sync(books, user, demo=_demo_session(request) is not None)
    except bf.BankFeedError as exc:
        raise _http(exc) from exc


class ConfirmBody(StrictBody):
    confirm: StrictBool = False  # set by the app only after the user said yes


def _confirmed(body: ConfirmBody) -> None:
    if body.confirm is not True:
        raise HTTPException(status_code=400, detail="Nothing was changed: confirm in the app first (confirm: true)")


async def _display_name(request: Request) -> str | None:
    """Microsoft's display name for the signed-in user (cached by app/identity.py), for TrueLayer's `user` object."""
    from app import identity

    if demo.is_demo_request(request):
        return None
    try:
        me = await identity.verified_identity(
            identity.bearer(request), request.headers.get("X-User"), identity.kind(request)
        )
        return me.name or None
    except HTTPException:
        return None


@router.post(
    "/{connection_id}/reconfirm", response_model=bf.ReconfirmResult, dependencies=[Depends(sandbox_only_in_demo)]
)
async def reconfirm(
    connection_id: str,
    body: ConfirmBody,
    request: Request,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> bf.ReconfirmResult:
    _confirmed(body)
    try:
        return await bf.reconfirm(books, connection_id, user, await _display_name(request))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such bank feed") from exc
    except bf.BankFeedError as exc:
        raise _http(exc) from exc


class DisconnectResult(BaseModel):
    status: bf.FeedStatus
    warning: str | None = None


@router.post("/{connection_id}/disconnect", response_model=DisconnectResult)
async def disconnect(
    connection_id: str,
    body: ConfirmBody,
    request: Request,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> DisconnectResult:
    _confirmed(body)
    try:
        warning = await bf.disconnect(books, connection_id, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such bank feed") from exc
    return DisconnectResult(status=await bf.status(books, demo=demo.is_demo_request(request)), warning=warning)


@router.get("/duplicates", response_model=list[bf.FlaggedDuplicate])
async def duplicates(books: Books = Depends(get_books)) -> list[bf.FlaggedDuplicate]:
    return await bf.list_duplicates(books)


@router.post("/duplicates/{line_id}/restore", response_model=list[bf.FlaggedDuplicate])
async def restore_duplicate(
    line_id: str, body: ConfirmBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> list[bf.FlaggedDuplicate]:
    _confirmed(body)
    try:
        return await bf.restore_duplicate(books, line_id, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such flagged line") from exc
