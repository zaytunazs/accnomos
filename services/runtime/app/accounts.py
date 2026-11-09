"""Which cloud a request's token belongs to, and the providers for it.

`X-Account-Kind` says whose token `X-Graph-Token` carries (the header keeps its historical name for every kind):

| Kind | Token | Books | Mail, calendar, contacts |
|---|---|---|---|
| `personal` (default) | Microsoft account | OneDrive app folder | Outlook via Graph |
| `work` | Microsoft work or school account | OneDrive `/Accnomos` | Outlook via Graph |
| `google` | Google OAuth access token | Google Drive `My Drive/Accnomos` | Gmail, Google Calendar, People |

A Google client may send its token as `Authorization: Bearer <token>` instead (the shared Android/web contract);
`GoogleTokenAlias` below copies it into `X-Graph-Token` before any route reads it, for `X-Account-Kind: google` only,
so the Graph routes never see a stray Authorization header as a Graph token.

Gmail, Calendar and Contacts for Google live in `accnomos_connectors.google_workspace`, which lands separately: until
it is there, those routes answer 501 for a Google account (`google_class`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from fastapi import HTTPException, Request

from accnomos_connectors.base import StorageProvider

KINDS = ("personal", "work", "google")
GOOGLE = "google"
NO_SHARING = (
    "Sharing books with an accountant needs a Microsoft account for now: Google Drive books cannot be shared "
    "from Accnomos yet."
)


def kind_of(request: Request) -> str:
    """The request's account kind; 400 for anything else."""
    kind = (request.headers.get("X-Account-Kind") or "personal").strip().lower()
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail="X-Account-Kind must be 'personal', 'work' or 'google'")
    return kind


def is_google(request: Request) -> bool:
    return (request.headers.get("X-Account-Kind") or "").strip().lower() == GOOGLE


def storage_for(token: str, kind: str) -> StorageProvider:
    """The caller's own books storage for this token (the caller closes it)."""
    if kind == GOOGLE:
        from accnomos_connectors.google_drive import GoogleDriveStorageProvider

        return GoogleDriveStorageProvider(token)
    from accnomos_connectors.msgraph import GraphStorageProvider

    return GraphStorageProvider(token, kind)  # type: ignore[arg-type]


def is_cloud_storage(storage: object) -> bool:
    """A real provider (Graph or Google), not one of test mode's in-memory fakes."""
    from accnomos_connectors.google_drive import GoogleDriveStorageProvider
    from accnomos_connectors.msgraph import GraphStorageProvider

    return isinstance(storage, GraphStorageProvider | GoogleDriveStorageProvider)


def refuse_sharing(request: Request) -> None:
    """Accountant sharing (shared roots, invitations, the portal) is Graph-only: 400 for a Google account."""
    if is_google(request):
        raise HTTPException(status_code=400, detail=NO_SHARING)


def google_class(name: str) -> Any:
    """`accnomos_connectors.google_workspace.<name>`, or 501 while that module is not in this build."""
    try:
        from accnomos_connectors import google_workspace  # type: ignore[attr-defined]
    except ImportError:
        google_workspace = None
    cls = getattr(google_workspace, name, None) if google_workspace is not None else None
    if cls is None:
        raise HTTPException(
            status_code=501,
            detail="Gmail, Google Calendar and Google Contacts are not available on this server yet.",
        )
    return cls


def mail_provider(token: str, request: Request) -> Any:
    if is_google(request):
        return google_class("GoogleMailProvider")(token)
    from accnomos_connectors.msgraph import GraphMailProvider

    return GraphMailProvider(token)


def mail_sender(token: str, request: Request | None) -> Any:
    if request is not None and is_google(request):
        return google_class("GoogleMailSender")(token)
    from accnomos_connectors.msgraph import GraphMailSender

    return GraphMailSender(token)


def calendar_provider(token: str, request: Request) -> Any:
    if is_google(request):
        return google_class("GoogleCalendarProvider")(token)
    from accnomos_connectors.msgraph import GraphCalendarProvider

    return GraphCalendarProvider(token)


def contacts_provider(token: str, request: Request) -> Any:
    if is_google(request):
        return google_class("GoogleContactsProvider")(token)
    from accnomos_connectors.msgraph import GraphContactsProvider

    return GraphContactsProvider(token)


Scope = MutableMapping[str, Any]
ASGIApp = Callable[[Scope, Callable[[], Awaitable[Any]], Callable[[Any], Awaitable[None]]], Awaitable[None]]


class GoogleTokenAlias:
    """Pure ASGI: with `X-Account-Kind: google`, no `X-Graph-Token` and `Authorization: Bearer <t>`, add
    `X-Graph-Token: <t>` to the request, so every route reads the Google token the way it reads a Graph one."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            headers: list[tuple[bytes, bytes]] = list(scope.get("headers") or [])
            names = {k.lower(): v for k, v in headers}
            kind = names.get(b"x-account-kind", b"").strip().lower()
            auth = names.get(b"authorization", b"").strip()
            if kind == b"google" and not names.get(b"x-graph-token", b"").strip() and auth[:7].lower() == b"bearer ":
                scope = {**scope, "headers": [*headers, (b"x-graph-token", auth[7:].strip())]}
        await self.app(scope, receive, send)
