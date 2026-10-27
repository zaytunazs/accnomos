"""Microsoft Graph (OneDrive) StorageProvider.

Addressing (paths are relative to the Accnomos books root):

* personal -> the app folder: `/me/drive/special/approot` and `/me/drive/special/approot:/{path}`
* work     -> a plain folder: `/me/drive/root:/Accnomos` and `/me/drive/root:/Accnomos/{path}`

Folders are always created with `POST /me/drive/items/{parentId}/children`: creating children
via `/me/drive/special/approot/children` returns 400 (verified live). Item ids are cached per
instance, and an instance lives for one request, so the cache never goes stale for long.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal
from urllib.parse import quote, unquote

import httpx

from accnomos_connectors.base import ConflictError, FileRef, StorageProvider

GRAPH = "https://graph.microsoft.com/v1.0"
SIMPLE_UPLOAD_MAX = 4 * 1024 * 1024
MAX_RETRIES = 3
MAX_RETRY_AFTER_S = 30.0

AccountKind = Literal["personal", "work"]


class GraphError(RuntimeError):
    """A Graph call failed with a status we do not map to a builtin exception."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Graph {status}: {message}")
        self.status = status


def _join(parent: str, name: str) -> str:
    return f"{parent}/{name}" if parent else name


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _to_ref(item: dict[str, Any], path: str) -> FileRef:
    modified = item.get("lastModifiedDateTime")
    return FileRef(
        id=item["id"],
        path=path,
        name=item.get("name", path.rsplit("/", 1)[-1]),
        size=int(item.get("size") or 0),
        etag=item.get("eTag"),
        modified=datetime.fromisoformat(modified.replace("Z", "+00:00")) if modified else None,
        is_folder="folder" in item,
        web_url=item.get("webUrl"),
    )


class GraphStorageProvider(StorageProvider):
    """OneDrive via Microsoft Graph, with a bearer token supplied per request."""

    def __init__(
        self,
        token: str,
        account_kind: AccountKind = "personal",
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if account_kind not in ("personal", "work"):
            raise ValueError(f"account_kind must be 'personal' or 'work', not {account_kind!r}")
        self.account_kind: AccountKind = account_kind
        self._client = client or httpx.AsyncClient(timeout=60)
        self._owns_client = client is None
        self._auth = {"Authorization": f"Bearer {token}"}
        self._sleep = sleep
        self._folders: dict[str, dict[str, Any]] = {}  # books-relative path -> drive item
        self._root_drive_path: str | None = None  # e.g. '/Apps/Accnomos' once ensure_root has run

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> GraphStorageProvider:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ #
    # URLs and HTTP
    # ------------------------------------------------------------------ #

    def _item_url(self, path: str, action: str = "") -> str:
        """Path-addressed item URL, optionally with an action such as 'content' or 'children'."""
        path = path.strip("/")
        if self.account_kind == "personal":
            base = "/me/drive/special/approot"
            if not path:
                return f"{GRAPH}{base}" + (f"/{action}" if action else "")
            url = f"{GRAPH}{base}:/{quote(path, safe='/')}"
        else:
            url = f"{GRAPH}/me/drive/root:/Accnomos" + (f"/{quote(path, safe='/')}" if path else "")
        return url + (f":/{action}" if action else "")

    def _delta_url(self) -> str:
        if self.account_kind == "personal":
            return f"{GRAPH}/me/drive/special/approot/delta"
        return f"{GRAPH}/me/drive/root:/Accnomos:/delta"

    async def _request(
        self, method: str, url: str, *, auth: bool = True, ok404: bool = False, **kw: Any
    ) -> httpx.Response:
        """Send with retries on 429/503 (honouring Retry-After) and map errors to exceptions."""
        headers = {**(self._auth if auth else {}), **kw.pop("headers", {})}
        for attempt in range(MAX_RETRIES + 1):
            resp = await self._client.request(method, url, headers=headers, **kw)
            if resp.status_code not in (429, 503) or attempt == MAX_RETRIES:
                break
            await self._sleep(self._retry_after(resp))
        if resp.status_code == 404 and not ok404:
            raise FileNotFoundError(url)
        if resp.status_code == 412:
            raise ConflictError(url)
        if resp.status_code == 409:
            raise FileExistsError(url)
        if resp.status_code >= 400 and not (resp.status_code == 404 and ok404):
            raise GraphError(resp.status_code, resp.text[:300])
        return resp

    @staticmethod
    def _retry_after(resp: httpx.Response) -> float:
        try:
            return min(MAX_RETRY_AFTER_S, max(0.0, float(resp.headers.get("Retry-After", "1"))))
        except ValueError:
            return 1.0

    # ------------------------------------------------------------------ #
    # Folders
    # ------------------------------------------------------------------ #

    async def ensure_root(self) -> FileRef:
        if self.account_kind == "personal":
            item = (await self._request("GET", self._item_url(""))).json()  # auto-creates Apps/<app>
        else:
            resp = await self._request("GET", self._item_url(""), ok404=True)
            if resp.status_code == 404:
                drive_root = (await self._request("GET", f"{GRAPH}/me/drive/root")).json()
                item = await self._create_folder(drive_root["id"], "Accnomos")
            else:
                item = resp.json()
        self._folders[""] = item
        parent_path = (item.get("parentReference") or {}).get("path", "")
        if ":" in parent_path:
            self._root_drive_path = unquote(parent_path.split(":", 1)[1]) + "/" + item["name"]
        return _to_ref(item, "")

    async def _create_folder(self, parent_id: str, name: str) -> dict[str, Any]:
        """Create `name` under `parent_id`; if it already exists (409) fetch it instead."""
        body = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
        try:
            return (await self._request("POST", f"{GRAPH}/me/drive/items/{parent_id}/children", json=body)).json()
        except FileExistsError:
            url = f"{GRAPH}/me/drive/items/{parent_id}:/{quote(name, safe='')}"
            return (await self._request("GET", url)).json()

    async def _folder(self, path: str) -> dict[str, Any]:
        """Drive item of the folder at `path`, creating it (and its parents) when missing."""
        path = path.strip("/")
        if path in self._folders:
            return self._folders[path]
        if not path:
            await self.ensure_root()
            return self._folders[""]
        resp = await self._request("GET", self._item_url(path), ok404=True)
        if resp.status_code == 404:
            parent = await self._folder(_parent(path))
            item = await self._create_folder(parent["id"], path.rsplit("/", 1)[-1])
        else:
            item = resp.json()
        self._folders[path] = item
        return item

    async def ensure_folder(self, path: str) -> FileRef:
        path = path.strip("/")
        return _to_ref(await self._folder(path), path)

    # ------------------------------------------------------------------ #
    # Files
    # ------------------------------------------------------------------ #

    async def list(self, path: str) -> list[FileRef]:
        path = path.strip("/")
        url: str | None = self._item_url(path, "children")
        out: list[FileRef] = []
        while url:
            page = (await self._request("GET", url)).json()
            for item in page.get("value", []):
                ref = _to_ref(item, _join(path, item["name"]))
                if ref.is_folder:
                    self._folders[ref.path] = item
                out.append(ref)
            url = page.get("@odata.nextLink")
        return out

    async def read(self, path: str) -> bytes:
        # Graph answers with a 302 to a pre-authenticated download URL; httpx drops the
        # Authorization header on the cross-origin hop.
        resp = await self._request("GET", self._item_url(path, "content"), follow_redirects=True)
        return resp.content

    async def write(self, path: str, data: bytes, *, if_match: str | None = None) -> FileRef:
        path = path.strip("/")
        if _parent(path):
            await self._folder(_parent(path))
        headers = {"If-Match": if_match} if if_match else {}
        if len(data) <= SIMPLE_UPLOAD_MAX:
            resp = await self._request(
                "PUT", self._item_url(path, "content"), content=data,
                headers={**headers, "Content-Type": "application/octet-stream"},
            )
            return _to_ref(resp.json(), path)
        return await self._upload_large(path, data, headers)

    async def _upload_large(self, path: str, data: bytes, headers: dict[str, str]) -> FileRef:
        """Upload session + one PUT of the whole body (Graph accepts fragments up to 60 MiB)."""
        body = {"item": {"@microsoft.graph.conflictBehavior": "replace"}}
        session = (
            await self._request("POST", self._item_url(path, "createUploadSession"), json=body, headers=headers)
        ).json()
        n = len(data)
        resp = await self._request(
            "PUT", session["uploadUrl"], auth=False, content=data,  # upload URL is pre-authenticated
            headers={"Content-Length": str(n), "Content-Range": f"bytes 0-{n - 1}/{n}"},
        )
        return _to_ref(resp.json(), path)

    async def move(self, path: str, new_path: str) -> FileRef:
        path, new_path = path.strip("/"), new_path.strip("/")
        item = (await self._request("GET", self._item_url(path))).json()
        parent = await self._folder(_parent(new_path))
        body = {"parentReference": {"id": parent["id"]}, "name": new_path.rsplit("/", 1)[-1]}
        moved = (await self._request("PATCH", f"{GRAPH}/me/drive/items/{item['id']}", json=body)).json()
        return _to_ref(moved, new_path)

    # ------------------------------------------------------------------ #
    # Change tracking
    # ------------------------------------------------------------------ #

    def _relative_path(self, item: dict[str, Any]) -> str:
        """Best-effort books-relative path from parentReference.path (delta may omit it)."""
        parent = unquote((item.get("parentReference") or {}).get("path", ""))
        anchor, _, rel = parent.partition(":")
        root = self._root_drive_path or ("/Accnomos" if self.account_kind == "work" else None)
        if not anchor.endswith("special/approot") and root and rel.startswith(root):
            rel = rel[len(root):]  # drive-relative -> books-relative
        return _join(rel.strip("/"), item.get("name", ""))

    async def changes(self, cursor: str | None) -> tuple[list[FileRef], str]:
        url: str | None = cursor or self._delta_url()
        changed: list[FileRef] = []
        while url:
            page = (await self._request("GET", url)).json()
            for item in page.get("value", []):
                if "folder" in item or "deleted" in item or "root" in item:
                    continue
                changed.append(_to_ref(item, self._relative_path(item)))
            if "@odata.deltaLink" in page:
                return changed, page["@odata.deltaLink"]
            url = page.get("@odata.nextLink")
        raise GraphError(200, "delta response had neither nextLink nor deltaLink")
