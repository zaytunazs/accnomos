"""/accountant/* and /queries/*: accountant collaboration (app/accountant.py, app/portal.py, app/queries.py).

* Client, own books: `GET /accountant`, `PUT /accountant/profile`, `POST /accountant/invitations`,
  `POST /accountant/invitations/{id}/revoke`, `POST /accountant/team` (opt in), `DELETE /accountant/team`.
  Refused (403) in books opened through sharing: only the owner decides who sees their books.
* Accountant: `GET /accountant/portal`, `POST /accountant/portal/clients`, `DELETE /accountant/portal/clients/{code}`.
  The token needs `Files.Read.All` (or `Files.ReadWrite.All`) to open what others shared.
* Both: `/queries` in whichever books the request is for (a client's, with the X-Books-* headers of app/sharing.py).

Writes need `X-User`, as everywhere (the audit line); in a client's books the audit line carries the accountant's
Graph identity instead.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from accnomos_connectors.base import SharedRoot, SharingProvider
from accnomos_connectors.msgraph import GraphError, GraphStorageProvider
from app import accountant, portal, queries, sharing
from app.ai.config import is_test_mode
from app.books import Books
from app.books import today as london_today
from app.routes_books import _shared_books, get_books, require_user

router = APIRouter(tags=["accountant"])


def _token(request: Request) -> str:
    token = request.headers.get("X-Graph-Token", "").strip().removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="X-Graph-Token header required")
    return token


def _kind(request: Request) -> str:
    return (request.headers.get("X-Account-Kind") or "personal").strip().lower()


async def get_sharing(request: Request) -> AsyncIterator[SharingProvider]:
    provider = await sharing.sharing_for(_token(request), request.headers.get("X-User"))
    try:
        yield provider
    finally:
        close = getattr(provider, "aclose", None)
        if close is not None:
            await close()


def _owner_only(books: Books) -> None:
    if books.accountant:
        raise HTTPException(status_code=403, detail="Only the owner of these books can change who can see them.")


SHARE_REFUSED = (
    "Microsoft did not let Accnomos share your books folder ({status}). With a personal Microsoft account the "
    "books are in OneDrive › Apps › Accnomos: you can share that folder yourself in OneDrive (Share › enter your "
    "accountant's email) and then record it here with “I shared it myself”. A work or school account keeps the "
    "books in a plain /Accnomos folder, which can be shared from here."
)


# --------------------------------------------------------------------------- #
# Client: Settings › Your accountant
# --------------------------------------------------------------------------- #


@router.get("/accountant", response_model=accountant.Settings)
async def accountant_settings(books: Books = Depends(get_books)) -> accountant.Settings:
    _owner_only(books)
    return await accountant.settings(books)


@router.put("/accountant/profile", response_model=accountant.ClientProfile)
async def accountant_profile(
    body: accountant.ClientProfile, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> accountant.ClientProfile:
    _owner_only(books)
    return await accountant.save_profile(books, body, user)


@router.post("/accountant/invitations", response_model=accountant.Invitation, status_code=201)
async def accountant_invite(
    body: accountant.InviteIn,
    request: Request,
    books: Books = Depends(get_books),
    provider: SharingProvider = Depends(get_sharing),
    user: str = Depends(require_user),
) -> accountant.Invitation:
    _owner_only(books)
    try:
        return await accountant.invite(books, provider, _kind(request), body, user)
    except accountant.AccountantError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GraphError as exc:
        raise HTTPException(status_code=409, detail=SHARE_REFUSED.format(status=exc.status)) from exc
    except PermissionError as exc:  # the fake's "not the owner"
        raise HTTPException(status_code=409, detail=SHARE_REFUSED.format(status=403)) from exc


@router.post("/accountant/invitations/{invitation_id}/revoke", response_model=accountant.Invitation)
async def accountant_revoke(
    invitation_id: str,
    request: Request,
    books: Books = Depends(get_books),
    provider: SharingProvider = Depends(get_sharing),
    user: str = Depends(require_user),
) -> accountant.Invitation:
    _owner_only(books)
    try:
        return await accountant.revoke(books, provider, _kind(request), invitation_id, user)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No such invitation") from exc


@router.post("/accountant/team", response_model=accountant.Invitation, status_code=201)
async def accountant_team_opt_in(
    body: accountant.TeamOptIn,
    request: Request,
    books: Books = Depends(get_books),
    provider: SharingProvider = Depends(get_sharing),
    user: str = Depends(require_user),
) -> accountant.Invitation:
    _owner_only(books)
    try:
        return await accountant.team_opt_in(books, provider, _kind(request), body, user)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except accountant.AccountantError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GraphError as exc:
        raise HTTPException(status_code=409, detail=SHARE_REFUSED.format(status=exc.status)) from exc


@router.delete("/accountant/team", response_model=accountant.Invitation)
async def accountant_team_opt_out(
    request: Request,
    books: Books = Depends(get_books),
    provider: SharingProvider = Depends(get_sharing),
    user: str = Depends(require_user),
) -> accountant.Invitation:
    _owner_only(books)
    try:
        return await accountant.team_opt_out(books, provider, _kind(request), user)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="You have not opted in to reviews by Accnomos accountants") from exc


# --------------------------------------------------------------------------- #
# Accountant: the portal
# --------------------------------------------------------------------------- #


@router.get("/accountant/portal", response_model=portal.Portal)
async def accountant_portal(
    request: Request,
    books: Books = Depends(get_books),
    provider: SharingProvider = Depends(get_sharing),
) -> portal.Portal:
    """Your clients: their books are opened read-only, one at a time per client, never cached together."""
    if books.accountant:
        raise HTTPException(status_code=400, detail="Open the portal from your own account, not inside a client.")
    token, kind = _token(request), _kind(request)
    me = await sharing.identity(token, request.headers.get("X-User"))
    async with AsyncExitStack() as stack:

        async def open_client(root: SharedRoot) -> Books:
            if is_test_mode():
                from app import testmode

                inner, _role = (await testmode.state()).world.storage_for(root, me)
                return _shared_books(inner, True, me, token, root, testmode.tenant())
            storage = GraphStorageProvider(token, kind, shared=root)  # type: ignore[arg-type]
            stack.push_async_callback(storage.aclose)
            return _shared_books(storage, True, me, token, root)

        return await portal.list_clients(books, provider, open_client, me, london_today())


@router.post("/accountant/portal/clients", response_model=portal.ClientLink, status_code=201)
async def accountant_add_client(
    body: portal.AddClientIn,
    books: Books = Depends(get_books),
    provider: SharingProvider = Depends(get_sharing),
    user: str = Depends(require_user),
) -> portal.ClientLink:
    if books.accountant:
        raise HTTPException(status_code=400, detail="Add clients from your own account, not inside a client.")
    try:
        return await portal.add_link(books, provider, body, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=sharing_note()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def sharing_note() -> str:
    return "Those books are not shared with the Microsoft account you are signed in with."


@router.delete("/accountant/portal/clients/{code}")
async def accountant_remove_client(
    code: str, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> dict[str, bool]:
    try:
        root = portal.parse_code(code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not await portal.remove_link(books, root, user):
        raise HTTPException(status_code=404, detail="That client was not added by code")
    return {"removed": True}


# --------------------------------------------------------------------------- #
# Queries: both sides
# --------------------------------------------------------------------------- #


@router.get("/queries", response_model=list[queries.Query])
async def queries_list(
    status: str | None = Query(None, pattern="^(open|resolved)$"),
    waiting_on: str | None = Query(None, pattern="^(client|accountant)$"),
    books: Books = Depends(get_books),
) -> list[queries.Query]:
    return await queries.list_queries(books, status, waiting_on)


@router.get("/queries/{query_id}", response_model=queries.Query)
async def queries_get(query_id: str, books: Books = Depends(get_books)) -> queries.Query:
    try:
        return await queries.get_query(books, query_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No such query") from exc


@router.post("/queries", response_model=queries.Query, status_code=201)
async def queries_open(
    body: queries.QueryIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> queries.Query:
    return await queries.open_query(books, body, user)


@router.post("/queries/{query_id}/messages", response_model=queries.Query)
async def queries_reply(
    query_id: str, body: queries.ReplyIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> queries.Query:
    try:
        return await queries.reply(books, query_id, body, user)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No such query") from exc
    except queries.QueryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/queries/{query_id}/resolve", response_model=queries.Query)
async def queries_resolve(
    query_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> queries.Query:
    try:
        return await queries.resolve(books, query_id, user)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No such query") from exc
