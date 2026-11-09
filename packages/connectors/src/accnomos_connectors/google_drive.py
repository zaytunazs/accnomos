"""Google Drive (v3) StorageProvider, and who a Google token belongs to.

The books live in a folder named `Accnomos` at the top of the user's My Drive. The token carries
`https://www.googleapis.com/auth/drive.file` only (a non-sensitive scope): the app sees just the files and folders it
created or the user opened with it, never the rest of the drive. A folder called "Accnomos" that the user made by hand
is therefore invisible here, and the app makes its own.

Drive addresses everything by id and allows several items with the same name in one folder, so paths
(POSIX, relative to the books root, as in base.py) are resolved one segment at a time:

* lookups ask `files.list` for `name = '<segment>' and '<parent id>' in parents and trashed = false`, ordered by
  `createdTime`: when names are duplicated, the **oldest** item wins, so every reader picks the same one;
* folder ids are cached per instance (an instance lives for one request, so the cache cannot go stale for long);
  files are always looked up afresh, because their version (and so their etag) changes with every write.

Optimistic concurrency is emulated, because Drive v3 offers no reliable If-Match on content updates:

* `etag` is derived from the file's `version` (Drive bumps it on every change, content or metadata), as `"v<n>"`.
* `write(if_match=...)` reads the current version and raises ConflictError when it differs, then updates. **Race
  window**: another writer that lands between that read and our update is overwritten. It is one round trip wide.
* Creating anything (a file, a folder, the root) is check-then-create, so two writers can both create the same name.
  Every create is therefore **settled** straight after: the name is listed again, and if ours is not the oldest
  (createdTime, then id) ours goes to the bin and the oldest is used. A losing folder first has whatever was put in it
  moved into the winner. A losing `write(create_only=True)` raises FileExistsError, so exactly one claim wins (the
  ledger's `Books.post_event` depends on it); a losing plain write replaces the winner's content instead.
  Remaining window: Drive's listing is not guaranteed to show a just-created item at once; if it lags, both writers
  can each see only their own and both "win". Rare, but not impossible.
* `write(if_match=...)` on a file that is no longer there raises ConflictError (it never re-creates it).

Change tracking uses the Drive changes API. `changes(None)` lists every file under the root and returns the
`startPageToken` taken *before* that listing (so nothing written meanwhile is missed); later calls page through
`changes.list` from the cursor. Changes outside the books root (other files this app made) are dropped.

`content_hash` is `md5:<hex>` (Drive's `md5Checksum`). Tests point the module-level `TRANSPORT` at a fake
(accnomos_connectors.fake_drive), as services/runtime/app/truelayer.py does.

Google docs, checked 9 Nov 2026: files.list/create/update/get, changes.getStartPageToken/list, and the upload guide
(multipart up to 5 MB, resumable above) at https://developers.google.com/workspace/drive/api/reference/rest/v3 and
https://developers.google.com/workspace/drive/api/guides/manage-uploads.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import httpx

from accnomos_connectors.base import ConflictError, FileRef, Identity, StorageProvider
from accnomos_connectors.msgraph import GraphError, _join, _parent, _safe_path

DRIVE_ORIGIN = "https://www.googleapis.com"
DRIVE = f"{DRIVE_ORIGIN}/drive/v3"
UPLOAD = f"{DRIVE_ORIGIN}/upload/drive/v3"
USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
ALLOWED_ORIGINS = (f"{DRIVE_ORIGIN}/", "https://openidconnect.googleapis.com/")
FOLDER_MIME = "application/vnd.google-apps.folder"
ROOT_NAME = "Accnomos"
SIMPLE_UPLOAD_MAX = 5 * 1024 * 1024
MAX_RETRIES = 3
MAX_RETRY_AFTER_S = 30.0
MAX_DEPTH = 32
FILE_FIELDS = "id,name,mimeType,size,md5Checksum,version,modifiedTime,createdTime,parents,webViewLink,trashed"

# Tests set this to an httpx.MockTransport (accnomos_connectors.fake_drive.FakeDrive.transport()).
TRANSPORT: httpx.AsyncBaseTransport | None = None


class GoogleDriveError(GraphError):
    """A Google call failed with a status we do not map to a builtin exception.

    A GraphError subclass on purpose: the runtime maps GraphError 401/403 to "sign in again" and the rest to 502, and
    that is exactly right for Google too."""

    def __init__(self, status: int, message: str) -> None:
        RuntimeError.__init__(self, f"Google {status}: {message}")
        self.status = status


def _q(value: str) -> str:
    """A string literal for a Drive query: backslash and single quote escaped."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _etag(item: dict[str, Any]) -> str | None:
    if item.get("mimeType") == FOLDER_MIME:
        return None
    if item.get("version") is not None:
        return f'"v{item["version"]}"'
    return f'"md5:{item["md5Checksum"]}"' if item.get("md5Checksum") else None


def _to_ref(item: dict[str, Any], path: str) -> FileRef:
    modified = item.get("modifiedTime")
    is_folder = item.get("mimeType") == FOLDER_MIME
    return FileRef(
        id=item["id"],
        path=path,
        name=item.get("name", path.rsplit("/", 1)[-1]),
        size=int(item.get("size") or 0),
        etag=_etag(item),
        modified=datetime.fromisoformat(modified.replace("Z", "+00:00")) if modified else None,
        is_folder=is_folder,
        web_url=item.get("webViewLink"),
        content_hash=f"md5:{item['md5Checksum']}" if item.get("md5Checksum") and not is_folder else None,
    )


class _GoogleHttp:
    """Bearer token, retries on 429/503 (and Drive's rate-limit 403s) and error mapping."""

    def __init__(
        self,
        token: str,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=60, transport=TRANSPORT)
        self._owns_client = client is None
        self._auth = {"Authorization": f"Bearer {token.strip().removeprefix('Bearer ').strip()}"}
        self._sleep = sleep

    def set_token(self, token: str) -> None:
        """Use a fresh token from the next request on (a long job outlives the hour a Google token lasts)."""
        if not token.strip():
            raise ValueError("empty token")
        self._auth = {"Authorization": f"Bearer {token.strip()}"}

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> Any:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    @staticmethod
    def _rate_limited(resp: httpx.Response) -> bool:
        if resp.status_code in (429, 503):
            return True
        if resp.status_code != 403:
            return False
        try:
            errors = (resp.json().get("error") or {}).get("errors") or []
        except ValueError:
            return False
        return any(e.get("reason") in ("rateLimitExceeded", "userRateLimitExceeded") for e in errors)

    async def _request(self, method: str, url: str, *, ok404: bool = False, **kw: Any) -> httpx.Response:
        """The token only ever goes to Google's API hosts: any other URL is refused before anything is sent."""
        if not url.startswith(ALLOWED_ORIGINS):
            raise ValueError("refusing to send the Google token outside googleapis.com")
        headers = {**self._auth, **kw.pop("headers", {})}
        for attempt in range(MAX_RETRIES + 1):
            resp = await self._client.request(method, url, headers=headers, **kw)
            if not self._rate_limited(resp) or attempt == MAX_RETRIES:
                break
            await self._sleep(self._retry_after(resp, attempt))
        if resp.status_code == 404:
            if ok404:
                return resp
            raise FileNotFoundError(url)
        if resp.status_code == 412:
            raise ConflictError(url)
        if resp.status_code == 409:
            raise FileExistsError(url)
        if resp.status_code >= 400:
            raise GoogleDriveError(resp.status_code, resp.text[:300])
        return resp

    @staticmethod
    def _retry_after(resp: httpx.Response, attempt: int) -> float:
        try:
            return min(MAX_RETRY_AFTER_S, max(0.0, float(resp.headers["Retry-After"])))
        except (KeyError, ValueError):
            return min(MAX_RETRY_AFTER_S, float(2**attempt))


class GoogleIdentity(_GoogleHttp):
    """Who a Google access token belongs to (OpenID Connect userinfo; needs the `openid email profile` scopes)."""

    async def whoami(self) -> Identity:
        info = (await self._request("GET", USERINFO)).json()
        email = str(info.get("email") or "").strip().lower()
        if not email:
            raise GoogleDriveError(401, "Google did not say which account this is (no email scope)")
        return Identity(email=email, name=str(info.get("name") or ""))


class GoogleDriveStorageProvider(_GoogleHttp, StorageProvider):
    """The books folder in the user's Google Drive, with a bearer token supplied per request (drive.file scope)."""

    account_kind = "google"

    def __init__(
        self,
        token: str,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__(token, client=client, sleep=sleep)
        self._folders: dict[str, dict[str, Any]] = {}  # books-relative path -> folder metadata
        self._id_paths: dict[str, str | None] = {}  # folder id -> books-relative path (None: outside the books)

    # ------------------------------------------------------------------ #
    # Lookups
    # ------------------------------------------------------------------ #

    def _remember(self, path: str, item: dict[str, Any]) -> dict[str, Any]:
        self._folders[path] = item
        self._id_paths[item["id"]] = path
        return item

    async def _query(self, q: str, order: str = "createdTime") -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        token: str | None = None
        while True:
            params = {
                "q": q,
                "fields": f"nextPageToken,files({FILE_FIELDS})",
                "orderBy": order,
                "pageSize": "1000",
                "spaces": "drive",
            }
            if token:
                params["pageToken"] = token
            page = (await self._request("GET", f"{DRIVE}/files", params=params)).json()
            out.extend(page.get("files") or [])
            token = page.get("nextPageToken")
            if not token:
                return out

    async def _child(self, parent_id: str, name: str, want: str | None = None) -> dict[str, Any] | None:
        """The oldest non-trashed child called `name`; `want` = "folder" or "file" narrows it."""
        q = f"name = {_q(name)} and {_q(parent_id)} in parents and trashed = false"
        if want == "folder":
            q += f" and mimeType = {_q(FOLDER_MIME)}"
        elif want == "file":
            q += f" and mimeType != {_q(FOLDER_MIME)}"
        hits = await self._query(q)
        return hits[0] if hits else None

    async def _create_folder(self, parent_id: str, name: str) -> dict[str, Any]:
        _safe_path(name)
        body = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        return (await self._request("POST", f"{DRIVE}/files", params={"fields": FILE_FIELDS}, json=body)).json()

    async def _oldest(self, parent_id: str, name: str, want: str) -> dict[str, Any] | None:
        """The item every reader resolves `name` to: oldest createdTime, ties broken by id."""
        q = f"name = {_q(name)} and {_q(parent_id)} in parents and trashed = false"
        q += f" and mimeType {'=' if want == 'folder' else '!='} {_q(FOLDER_MIME)}"
        hits = await self._query(q)
        return min(hits, key=lambda i: (i.get("createdTime") or "", i["id"])) if hits else None

    async def _trash(self, file_id: str) -> None:
        """Move an item this app made to the bin (drive.file allows it for our own items; nothing is deleted)."""
        await self._request("PATCH", f"{DRIVE}/files/{file_id}", params={"fields": "id"}, json={"trashed": True})

    async def _settle_folder(self, parent_id: str, mine: dict[str, Any]) -> dict[str, Any]:
        """After creating a folder: if another writer created one with the same name first, ours loses. Anything
        already put into ours is moved into the winner, ours goes to the bin, and the winner is used."""
        winner = await self._oldest(parent_id, mine["name"], "folder")
        if winner is None or winner["id"] == mine["id"]:
            return mine
        for item in await self._query(f"{_q(mine['id'])} in parents and trashed = false"):
            params = {"addParents": winner["id"], "removeParents": mine["id"], "fields": "id"}
            await self._request("PATCH", f"{DRIVE}/files/{item['id']}", params=params, json={})
        await self._trash(mine["id"])
        return winner

    async def ensure_root(self) -> FileRef:
        if "" in self._folders:
            return _to_ref(self._folders[""], "")
        item = await self._child("root", ROOT_NAME, "folder")
        if item is None:
            item = await self._settle_folder("root", await self._create_folder("root", ROOT_NAME))
        return _to_ref(self._remember("", item), "")

    async def _root_id(self) -> str:
        await self.ensure_root()
        return self._folders[""]["id"]

    async def _find_folder(self, path: str) -> dict[str, Any] | None:
        """The folder at `path`, or None; never creates anything."""
        path = _safe_path(path.strip("/"))
        if path in self._folders:
            return self._folders[path]
        if not path:
            await self.ensure_root()
            return self._folders[""]
        parent = await self._find_folder(_parent(path))
        if parent is None:
            return None
        item = await self._child(parent["id"], path.rsplit("/", 1)[-1], "folder")
        return self._remember(path, item) if item else None

    async def _folder(self, path: str) -> dict[str, Any]:
        """The folder at `path`, creating it (and its parents) when missing."""
        path = _safe_path(path.strip("/"))
        if (found := await self._find_folder(path)) is not None:
            return found
        parent = await self._folder(_parent(path))
        mine = await self._create_folder(parent["id"], path.rsplit("/", 1)[-1])
        return self._remember(path, await self._settle_folder(parent["id"], mine))

    async def _find(self, path: str) -> dict[str, Any] | None:
        """The file or folder at `path` (a file wins over a folder of the same name), or None."""
        path = _safe_path(path.strip("/"))
        if not path:
            return await self._find_folder("")
        parent = await self._find_folder(_parent(path))
        if parent is None:
            return None
        name = path.rsplit("/", 1)[-1]
        item = await self._child(parent["id"], name, "file")
        if item is None and (item := await self._child(parent["id"], name, "folder")) is not None:
            self._remember(path, item)
        return item

    async def ensure_folder(self, path: str) -> FileRef:
        path = path.strip("/")
        return _to_ref(await self._folder(path), path)

    # ------------------------------------------------------------------ #
    # Files
    # ------------------------------------------------------------------ #

    async def list(self, path: str) -> list[FileRef]:
        path = path.strip("/")
        folder = await self._find_folder(path)
        if folder is None:
            raise FileNotFoundError(path)
        items = await self._query(f"{_q(folder['id'])} in parents and trashed = false", order="folder,name")
        out: list[FileRef] = []
        seen: set[tuple[str, bool]] = set()
        for item in sorted(items, key=lambda i: (i.get("mimeType") != FOLDER_MIME, i.get("name", ""))):
            ref = _to_ref(item, _join(path, item["name"]))
            if (ref.name, ref.is_folder) in seen:
                continue  # a duplicate name: the oldest one is the one paths resolve to (see the module docstring)
            seen.add((ref.name, ref.is_folder))
            if ref.is_folder and ref.path not in self._folders:
                self._remember(ref.path, item)
            out.append(ref)
        return out

    async def read(self, path: str) -> bytes:
        item = await self._find(path)
        if item is None or item.get("mimeType") == FOLDER_MIME:
            raise FileNotFoundError(path)
        resp = await self._request("GET", f"{DRIVE}/files/{item['id']}", params={"alt": "media"})
        return resp.content

    async def write(self, path: str, data: bytes, *, if_match: str | None = None, create_only: bool = False) -> FileRef:
        path = _safe_path(path.strip("/"))
        if not path:
            raise ValueError("cannot write the books root")
        parent = await self._folder(_parent(path))
        name = path.rsplit("/", 1)[-1]
        existing = await self._child(parent["id"], name, "file")
        if existing is not None and create_only:
            raise FileExistsError(path)
        if if_match is not None and (existing is None or _etag(existing) != if_match):
            raise ConflictError(path)  # emulated If-Match (gone, or changed): see the module docstring
        if existing is not None:
            item = await self._upload("PATCH", f"{UPLOAD}/files/{existing['id']}", {}, data)
            return _to_ref(item, path)
        item = await self._upload("POST", f"{UPLOAD}/files", {"name": name, "parents": [parent["id"]]}, data)
        winner = await self._oldest(parent["id"], name, "file")
        if winner is None or winner["id"] == item["id"]:
            return _to_ref(item, path)
        # Another writer created this name first: every reader resolves to theirs, so ours goes to the bin.
        await self._trash(item["id"])
        if create_only:
            raise FileExistsError(path)  # the claim was theirs (Books.post_event relies on this)
        item = await self._upload("PATCH", f"{UPLOAD}/files/{winner['id']}", {}, data)  # a plain write: ours last
        return _to_ref(item, path)

    async def _upload(self, method: str, url: str, meta: dict[str, Any], data: bytes) -> dict[str, Any]:
        """Multipart (metadata + bytes in one request) up to 5 MB, a resumable session above."""
        if len(data) <= SIMPLE_UPLOAD_MAX:
            boundary = f"accnomos-{uuid.uuid4().hex}"
            body = (
                (
                    f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
                    f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n"
                ).encode()
                + data
                + f"\r\n--{boundary}--\r\n".encode()
            )
            resp = await self._request(
                method,
                url,
                params={"uploadType": "multipart", "fields": FILE_FIELDS},
                content=body,
                headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            )
            return resp.json()
        start = await self._request(
            method,
            url,
            params={"uploadType": "resumable", "fields": FILE_FIELDS},
            json=meta,
            headers={"X-Upload-Content-Type": "application/octet-stream", "X-Upload-Content-Length": str(len(data))},
        )
        session = start.headers.get("Location", "")
        resp = await self._request("PUT", session, content=data, headers={"Content-Length": str(len(data))})
        return resp.json()

    async def move(self, path: str, new_path: str) -> FileRef:
        path, new_path = _safe_path(path.strip("/")), _safe_path(new_path.strip("/"))
        if not path or not new_path:
            raise ValueError("cannot move the books root")
        item = await self._find(path)
        if item is None:
            raise FileNotFoundError(path)
        is_folder = item.get("mimeType") == FOLDER_MIME
        if is_folder and (new_path == path or new_path.startswith(f"{path}/")):
            raise ValueError(f"cannot move {path} into itself")
        if await self._find(new_path) is not None:
            raise FileExistsError(new_path)
        target = await self._folder(_parent(new_path))
        old_parents = ",".join(item.get("parents") or [])
        params = {"addParents": target["id"], "fields": FILE_FIELDS}
        if old_parents and old_parents != target["id"]:
            params["removeParents"] = old_parents
        elif old_parents == target["id"]:
            params.pop("addParents")
        body = {"name": new_path.rsplit("/", 1)[-1]}
        moved = (await self._request("PATCH", f"{DRIVE}/files/{item['id']}", params=params, json=body)).json()
        if is_folder:  # cached lookups under the old path are gone
            stale = [p for p in self._folders if p == path or p.startswith(f"{path}/")]
            for p in stale:
                self._id_paths.pop(self._folders.pop(p)["id"], None)
            self._remember(new_path, moved)
        return _to_ref(moved, new_path)

    # ------------------------------------------------------------------ #
    # Change tracking
    # ------------------------------------------------------------------ #

    async def _path_of_folder(self, folder_id: str, depth: int = 0) -> str | None:
        """Books-relative path of a folder id, walking up its parents; None when it is not under the books root."""
        root_id = await self._root_id()
        if folder_id == root_id:
            return ""
        if folder_id in self._id_paths:
            return self._id_paths[folder_id]
        if depth > MAX_DEPTH:
            return None
        resp = await self._request(
            "GET", f"{DRIVE}/files/{folder_id}", params={"fields": "id,name,mimeType,parents,trashed"}, ok404=True
        )
        if resp.status_code == 404:  # the drive root itself, or a folder outside what drive.file lets us see
            self._id_paths[folder_id] = None
            return None
        item = resp.json()
        parents = item.get("parents") or []
        above = await self._path_of_folder(parents[0], depth + 1) if parents and not item.get("trashed") else None
        path = None if above is None else _join(above, item["name"])
        self._id_paths[folder_id] = path
        if path is not None:
            self._folders.setdefault(path, item)
        return path

    async def _everything(self, path: str) -> list[FileRef]:
        out: list[FileRef] = []
        for ref in await self.list(path):
            out.extend(await self._everything(ref.path) if ref.is_folder else [ref])
        return out

    async def changes(self, cursor: str | None) -> tuple[list[FileRef], str]:
        if cursor is None:
            start = (await self._request("GET", f"{DRIVE}/changes/startPageToken")).json()["startPageToken"]
            await self.ensure_root()
            return await self._everything(""), str(start)
        changed: dict[str, FileRef] = {}
        token = cursor
        while True:
            params = {
                "pageToken": token,
                "fields": f"nextPageToken,newStartPageToken,changes(fileId,removed,file({FILE_FIELDS}))",
                "includeRemoved": "true",
                "spaces": "drive",
                "pageSize": "1000",
            }
            page = (await self._request("GET", f"{DRIVE}/changes", params=params)).json()
            for change in page.get("changes") or []:
                item = change.get("file") or {}
                if change.get("removed") or not item or item.get("trashed") or item.get("mimeType") == FOLDER_MIME:
                    changed.pop(str(change.get("fileId")), None)
                    continue
                parents = item.get("parents") or []
                folder = await self._path_of_folder(parents[0]) if parents else None
                if folder is None:
                    continue  # another file this app made, outside the books
                changed.pop(item["id"], None)  # latest change last
                changed[item["id"]] = _to_ref(item, _join(folder, item["name"]))
            if page.get("newStartPageToken"):
                return list(changed.values()), str(page["newStartPageToken"])
            token = page.get("nextPageToken")
            if not token:
                raise GoogleDriveError(200, "changes response had neither nextPageToken nor newStartPageToken")
