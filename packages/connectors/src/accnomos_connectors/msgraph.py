"""Microsoft Graph: OneDrive StorageProvider and Outlook MailProvider.

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
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import quote, unquote

import httpx

from accnomos_connectors.base import (
    AddressBookContact,
    ConflictError,
    ContactsProvider,
    FileRef,
    MailAttachment,
    MailMessage,
    MailProvider,
    StorageProvider,
)

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


def _safe_path(path: str) -> str:
    """Refuse '.'/'..' segments and control characters: every path stays inside the books root."""
    for segment in path.split("/"):
        if (segment and not segment.strip(" .")) or any(ord(c) < 0x20 or ord(c) == 0x7F for c in segment):
            raise ValueError(f"unsafe storage path {path!r}")
    return path


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


class _GraphHttp:
    """Bearer token, retries on 429/503 and error mapping shared by the Graph providers."""

    def __init__(
        self,
        token: str,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=60)
        self._owns_client = client is None
        self._auth = {"Authorization": f"Bearer {token}"}
        self._sleep = sleep

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> Any:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

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


class GraphStorageProvider(_GraphHttp, StorageProvider):
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
        super().__init__(token, client=client, sleep=sleep)
        self.account_kind: AccountKind = account_kind
        self._folders: dict[str, dict[str, Any]] = {}  # books-relative path -> drive item
        self._root_drive_path: str | None = None  # e.g. '/Apps/Accnomos' once ensure_root has run

    # ------------------------------------------------------------------ #
    # URLs
    # ------------------------------------------------------------------ #

    def _item_url(self, path: str, action: str = "") -> str:
        """Path-addressed item URL, optionally with an action such as 'content' or 'children'."""
        path = _safe_path(path.strip("/"))
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
        _safe_path(name)
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


def _iso(dt: str | None) -> datetime:
    return datetime.fromisoformat((dt or "1970-01-01T00:00:00Z").replace("Z", "+00:00"))


class GraphMailProvider(_GraphHttp, MailProvider):
    """Outlook mail via Microsoft Graph (`Mail.Read`). Personal and work accounts use the same endpoints.

    Read-only by construction: only GET requests are ever sent.
    """

    PAGE = 50

    @staticmethod
    def _message_url(message_id: str, rest: str = "") -> str:
        return f"{GRAPH}/me/messages/{quote(message_id, safe='')}" + rest

    async def list_messages(self, since: datetime, max_results: int = 50) -> list[MailMessage]:
        since_utc = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        # $orderby must use the first $filter property, or Graph rejects the query as "InefficientFilter".
        params: dict[str, str] | None = {
            "$filter": f"receivedDateTime ge {since_utc} and hasAttachments eq true",
            "$select": "id,receivedDateTime,from,subject,hasAttachments,webLink",
            "$orderby": "receivedDateTime desc",
            "$top": str(min(self.PAGE, max(1, max_results))),
        }
        url: str | None = f"{GRAPH}/me/messages"
        out: list[MailMessage] = []
        while url and len(out) < max_results:
            page = (await self._request("GET", url, params=params)).json()
            params = None  # nextLink already carries the query
            for m in page.get("value", []):
                sender = (m.get("from") or {}).get("emailAddress") or {}
                out.append(MailMessage(
                    id=m["id"], received_at=_iso(m.get("receivedDateTime")),
                    from_address=(sender.get("address") or "").lower(), from_name=sender.get("name") or "",
                    subject=m.get("subject") or "", has_attachments=bool(m.get("hasAttachments")),
                    web_link=m.get("webLink"),
                ))
            url = page.get("@odata.nextLink")
        return out[:max_results]

    async def list_attachments(self, message_id: str) -> list[MailAttachment]:
        url: str | None = self._message_url(message_id, "/attachments")
        params: dict[str, str] | None = {"$select": "id,name,contentType,size,isInline"}
        out: list[MailAttachment] = []
        while url:
            page = (await self._request("GET", url, params=params)).json()
            params = None
            for a in page.get("value", []):
                if a.get("@odata.type", "#microsoft.graph.fileAttachment") != "#microsoft.graph.fileAttachment":
                    continue  # forwarded messages (itemAttachment) and cloud links (referenceAttachment)
                out.append(MailAttachment(
                    id=a["id"], name=a.get("name") or "attachment", content_type=(a.get("contentType") or "").lower(),
                    size=int(a.get("size") or 0), is_inline=bool(a.get("isInline")),
                ))
            url = page.get("@odata.nextLink")
        return out

    async def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        url = self._message_url(message_id, f"/attachments/{quote(attachment_id, safe='')}/$value")
        return (await self._request("GET", url, follow_redirects=True)).content


class GraphContactsProvider(_GraphHttp, ContactsProvider):
    """Outlook contacts via Microsoft Graph (`Contacts.Read`). Read-only: only GET requests are ever sent."""

    PAGE = 100
    SELECT = "displayName,emailAddresses,businessPhones,companyName"

    async def list_contacts(self, max_results: int = 1000) -> list[AddressBookContact]:
        url: str | None = f"{GRAPH}/me/contacts"
        params: dict[str, str] | None = {"$select": self.SELECT, "$top": str(min(self.PAGE, max(1, max_results)))}
        out: list[AddressBookContact] = []
        while url and len(out) < max_results:
            page = (await self._request("GET", url, params=params)).json()
            params = None  # nextLink already carries the query
            for c in page.get("value", []):
                emails = [(e.get("address") or "").strip() for e in c.get("emailAddresses") or []]
                out.append(AddressBookContact(
                    id=c["id"], display_name=(c.get("displayName") or "").strip(),
                    company_name=(c.get("companyName") or "").strip(), emails=[e for e in emails if e],
                    business_phones=[p.strip() for p in c.get("businessPhones") or [] if p and p.strip()],
                ))
            url = page.get("@odata.nextLink")
        return out[:max_results]
