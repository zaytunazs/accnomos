"""Opening a client's books folder that was shared with an accountant, and the sharing provider for a request.

An accountant's browser sends the usual `X-Graph-Token` (their own, with `Files.Read.All` or `Files.ReadWrite.All`)
plus three headers naming the client's folder, read once here and in `routes_books.get_books`:

| Header | Meaning |
|---|---|
| `X-Books-Drive-Id`, `X-Books-Item-Id` | the client's books folder (`/drives/{drive}/items/{item}`); both or neither |
| `X-Books-Access` | `read` (default) or `edit`: what the accountant chose to open it as |

Rules kept here:

* **Path safety.** Ids must look like Graph ids (`_safe_id` in the connector) and every path stays relative to the
  shared folder: `GraphStorageProvider` addresses `/drives/{drive}/items/{item}:/{path}` only.
* **Never mix clients.** A `Books` over a shared folder gets its own cache key: hash of (token, drive, item), so the
  immutable ledger-event cache of client A is never read for client B, nor for the accountant's own books.
* **Read-only means read-only.** Opened as `read` (or when the client gave only view access), every write is refused
  here with 403 before Graph is asked, except under `_System/queries/`, where a view-only accountant has write access
  of its own (the client's invitation grants it; `app/accountant.py`).
* **Who did it.** Lines the accountant causes are audited as `accountant:<email>`; the email comes from Graph `/me`
  for the token (test mode: `X-User`), not from the client-supplied `X-User` header.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Literal

from fastapi import HTTPException, Request

from accnomos_connectors.base import FileRef, SharedRoot, SharingProvider, StorageProvider
from app.ai.config import is_test_mode
from app.books import QUERIES

DRIVE_HEADER = "X-Books-Drive-Id"
ITEM_HEADER = "X-Books-Item-Id"
ACCESS_HEADER = "X-Books-Access"
Access = Literal["read", "edit"]

_ID = re.compile(r"[A-Za-z0-9!._~-]{1,256}")


class ReadOnlyBooks(PermissionError):
    """A write to a client's books opened read-only (mapped to 403 in app.main)."""


def _writable(path: str) -> bool:
    path = path.strip("/")
    return path == QUERIES or path.startswith(f"{QUERIES}/")


class ReadOnlyStorage(StorageProvider):
    """Reads pass through; writes, moves and new folders are refused, except the client-query folder."""

    def __init__(self, inner: StorageProvider) -> None:
        self.inner = inner

    async def ensure_root(self) -> FileRef:
        return await self.inner.ensure_root()

    async def ensure_folder(self, path: str) -> FileRef:
        if not _writable(path):
            raise ReadOnlyBooks(f"read-only: cannot create {path}")
        return await self.inner.ensure_folder(path)

    async def list(self, path: str) -> list[FileRef]:
        return await self.inner.list(path)

    async def read(self, path: str) -> bytes:
        return await self.inner.read(path)

    async def write(self, path: str, data: bytes, *, if_match: str | None = None, create_only: bool = False) -> FileRef:
        if not _writable(path):
            raise ReadOnlyBooks(f"read-only: cannot write {path}")
        return await self.inner.write(path, data, if_match=if_match, create_only=create_only)

    async def move(self, path: str, new_path: str) -> FileRef:
        raise ReadOnlyBooks(f"read-only: cannot move {path}")

    async def changes(self, cursor: str | None) -> tuple[list[FileRef], str]:
        return await self.inner.changes(cursor)


def shared_root(request: Request) -> SharedRoot | None:
    """The client folder this request is for, or None for the caller's own books. 400 for half or odd ids."""
    drive = (request.headers.get(DRIVE_HEADER) or "").strip()
    item = (request.headers.get(ITEM_HEADER) or "").strip()
    if not drive and not item:
        return None
    if not (drive and item):
        raise HTTPException(400, f"{DRIVE_HEADER} and {ITEM_HEADER} go together")
    if not (_ID.fullmatch(drive) and _ID.fullmatch(item)):
        raise HTTPException(400, "not a OneDrive drive or item id")
    return SharedRoot(drive_id=drive, item_id=item)


def access(request: Request) -> Access:
    raw = (request.headers.get(ACCESS_HEADER) or "read").strip().lower()
    if raw not in ("read", "edit"):
        raise HTTPException(400, f"{ACCESS_HEADER} must be 'read' or 'edit'")
    return raw  # type: ignore[return-value]


def client_cache_key(token: str, root: SharedRoot, tenant: str = "") -> str:
    """The cache key of one client's books for one accountant: never the same as theirs or another client's."""
    from app.cache import user_cache_key

    return user_cache_key(token, f"{tenant}\x00shared\x00{root.drive_id}\x00{root.item_id}")


async def sharing_for(token: str, user: str | None = None) -> SharingProvider:
    """Graph sharing for this token; in test mode the tenant's FakeSharingWorld seen as `user` (X-User)."""
    if is_test_mode():
        from app import testmode

        return await testmode.sharing(user)
    from accnomos_connectors.msgraph import GraphSharingProvider

    return GraphSharingProvider(token)


_IDENTITIES: OrderedDict[str, str] = OrderedDict()  # hash of the token -> its /me email (no token is kept)
_IDENTITIES_MAX = 256


async def identity(token: str, user: str | None) -> str:
    """The accountant's email, from Graph /me for this token (remembered by token hash for the hour it lives)."""
    if is_test_mode():
        if not user:
            raise HTTPException(400, "X-User header required")
        return user.strip().lower()
    from app.cache import user_cache_key

    key = user_cache_key(token, "identity")
    if key in _IDENTITIES:
        _IDENTITIES.move_to_end(key)
        return _IDENTITIES[key]
    provider = await sharing_for(token)
    try:
        email = (await provider.whoami()).email
    finally:
        await provider.aclose()  # type: ignore[attr-defined]
    _IDENTITIES[key] = email
    while len(_IDENTITIES) > _IDENTITIES_MAX:
        _IDENTITIES.popitem(last=False)
    return email
