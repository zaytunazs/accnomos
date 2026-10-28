"""Microsoft Graph: OneDrive StorageProvider, Outlook MailProvider, ContactsProvider and CalendarProvider.

Addressing (paths are relative to the Accnomos books root):

* personal -> the app folder: `/me/drive/special/approot` and `/me/drive/special/approot:/{path}`
* work     -> a plain folder: `/me/drive/root:/Accnomos` and `/me/drive/root:/Accnomos/{path}`
* shared   -> someone else's books folder shared with the caller (an accountant opening a client):
              `/drives/{drive-id}/items/{item-id}` and `/drives/{drive-id}/items/{item-id}:/{path}`, path-addressed
              relative to the shared folder's item id (Microsoft Learn, "Address resources in a drive on OneDrive",
              https://learn.microsoft.com/graph/onedrive-addressing-driveitems, checked 28 Oct 2026). Needs a
              `Files.Read.All` / `Files.ReadWrite.All` token: items in another drive are not reachable otherwise.

Folders are always created with `POST /me/drive/items/{parentId}/children`: creating children
via `/me/drive/special/approot/children` returns 400 (verified live). Item ids are cached per
instance, and an instance lives for one request, so the cache never goes stale for long.
"""

from __future__ import annotations

import asyncio
import base64
import html
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo

import httpx

from accnomos_connectors.base import (
    AddressBookContact,
    CalendarEvent,
    CalendarProvider,
    ConflictError,
    ContactsProvider,
    FileRef,
    Identity,
    MailAttachment,
    MailDraft,
    MailMessage,
    MailProvider,
    MailSender,
    OutgoingMail,
    SharedFolder,
    SharedRoot,
    SharePermission,
    ShareRole,
    SharingProvider,
    StorageProvider,
)

GRAPH_ORIGIN = "https://graph.microsoft.com"
GRAPH = f"{GRAPH_ORIGIN}/v1.0"
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


_ID = re.compile(r"[A-Za-z0-9!._~-]{1,256}")


def _safe_id(value: str, what: str = "id") -> str:
    """A drive or item id goes into the URL path as-is: only the characters Graph ids use (`b!…`, `ABC!123`)."""
    if not _ID.fullmatch(value or ""):
        raise ValueError(f"unsafe {what} {value!r}")
    return value


def _join(parent: str, name: str) -> str:
    return f"{parent}/{name}" if parent else name


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _hash(item: dict[str, Any]) -> str | None:
    """The content hash Graph lists for a file. OneDrive personal gives sha1Hash and quickXorHash, business
    quickXorHash only; sha256Hash is rare. Folders have none."""
    hashes = (item.get("file") or {}).get("hashes") or {}
    for key in ("sha256Hash", "quickXorHash", "sha1Hash"):
        if isinstance(hashes.get(key), str) and hashes[key]:
            return f"{key.removesuffix('Hash')}:{hashes[key]}"
    return None


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
        content_hash=_hash(item),
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

    def set_token(self, token: str) -> None:
        """Use a fresh token from the next request on (a long job outlives the hour a Graph token lasts; the
        signed-in app hands it a new one, see services/runtime/app/sample_books.py)."""
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

    async def _request(
        self, method: str, url: str, *, auth: bool = True, ok404: bool = False, **kw: Any
    ) -> httpx.Response:
        """Send with retries on 429/503 (honouring Retry-After) and map errors to exceptions.

        The user's token only ever goes to Graph: a nextLink, deltaLink or cursor naming any other host is refused
        before anything is sent. Pre-authenticated URLs (upload sessions) are called with auth=False."""
        if auth and not url.startswith(f"{GRAPH_ORIGIN}/"):
            raise ValueError(f"refusing to send the Graph token outside {GRAPH_ORIGIN}")
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
        shared: SharedRoot | None = None,
    ) -> None:
        if account_kind not in ("personal", "work"):
            raise ValueError(f"account_kind must be 'personal' or 'work', not {account_kind!r}")
        super().__init__(token, client=client, sleep=sleep)
        self.account_kind: AccountKind = account_kind
        self.shared = (
            SharedRoot(drive_id=_safe_id(shared.drive_id, "drive id"), item_id=_safe_id(shared.item_id, "item id"))
            if shared
            else None
        )
        self._folders: dict[str, dict[str, Any]] = {}  # books-relative path -> drive item
        self._root_drive_path: str | None = None  # e.g. '/Apps/Accnomos' once ensure_root has run

    # ------------------------------------------------------------------ #
    # URLs
    # ------------------------------------------------------------------ #

    def _item_url(self, path: str, action: str = "") -> str:
        """Path-addressed item URL, optionally with an action such as 'content' or 'children'."""
        path = _safe_path(path.strip("/"))
        if self.shared:
            base = f"{GRAPH}/drives/{self.shared.drive_id}/items/{self.shared.item_id}"
            if not path:
                return base + (f"/{action}" if action else "")
            return f"{base}:/{quote(path, safe='/')}" + (f":/{action}" if action else "")
        if self.account_kind == "personal":
            base = "/me/drive/special/approot"
            if not path:
                return f"{GRAPH}{base}" + (f"/{action}" if action else "")
            url = f"{GRAPH}{base}:/{quote(path, safe='/')}"
        else:
            url = f"{GRAPH}/me/drive/root:/Accnomos" + (f"/{quote(path, safe='/')}" if path else "")
        return url + (f":/{action}" if action else "")

    def _items_url(self) -> str:
        """`.../items` of the drive the books live in: the caller's own, or the shared folder's drive."""
        return f"{GRAPH}/drives/{self.shared.drive_id}/items" if self.shared else f"{GRAPH}/me/drive/items"

    def _delta_url(self) -> str:
        if self.shared:
            return self._item_url("", "delta")
        if self.account_kind == "personal":
            return f"{GRAPH}/me/drive/special/approot/delta"
        return f"{GRAPH}/me/drive/root:/Accnomos:/delta"

    # ------------------------------------------------------------------ #
    # Folders
    # ------------------------------------------------------------------ #

    async def ensure_root(self) -> FileRef:
        if self.shared:  # someone else's folder: never created from here; 404 when it is no longer shared
            item = (await self._request("GET", self._item_url(""))).json()
            self._folders[""] = item
            return _to_ref(item, "")
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
            return (await self._request("POST", f"{self._items_url()}/{parent_id}/children", json=body)).json()
        except FileExistsError:
            url = f"{self._items_url()}/{parent_id}:/{quote(name, safe='')}"
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

    async def write(self, path: str, data: bytes, *, if_match: str | None = None, create_only: bool = False) -> FileRef:
        path = path.strip("/")
        if _parent(path):
            await self._folder(_parent(path))
        headers = {"If-Match": if_match} if if_match else {}
        if len(data) <= SIMPLE_UPLOAD_MAX:
            resp = await self._request(  # conflictBehavior=fail: an existing file -> 409 -> FileExistsError
                "PUT",
                self._item_url(path, "content"),
                content=data,
                params={"@microsoft.graph.conflictBehavior": "fail"} if create_only else None,
                headers={**headers, "Content-Type": "application/octet-stream"},
            )
            return _to_ref(resp.json(), path)
        return await self._upload_large(path, data, headers, create_only)

    async def _upload_large(
        self, path: str, data: bytes, headers: dict[str, str], create_only: bool = False
    ) -> FileRef:
        """Upload session + one PUT of the whole body (Graph accepts fragments up to 60 MiB)."""
        body = {"item": {"@microsoft.graph.conflictBehavior": "fail" if create_only else "replace"}}
        session = (
            await self._request("POST", self._item_url(path, "createUploadSession"), json=body, headers=headers)
        ).json()
        n = len(data)
        resp = await self._request(
            "PUT",
            session["uploadUrl"],
            auth=False,
            content=data,  # upload URL is pre-authenticated
            headers={"Content-Length": str(n), "Content-Range": f"bytes 0-{n - 1}/{n}"},
        )
        return _to_ref(resp.json(), path)

    async def move(self, path: str, new_path: str) -> FileRef:
        path, new_path = path.strip("/"), new_path.strip("/")
        item = (await self._request("GET", self._item_url(path))).json()
        parent = await self._folder(_parent(new_path))
        body = {"parentReference": {"id": parent["id"]}, "name": new_path.rsplit("/", 1)[-1]}
        moved = (await self._request("PATCH", f"{self._items_url()}/{item['id']}", json=body)).json()
        if "folder" in item:  # a renamed folder: cached lookups under the old path are gone
            self._folders = {p: v for p, v in self._folders.items() if p != path and not p.startswith(f"{path}/")}
            self._folders[new_path] = moved
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
            rel = rel[len(root) :]  # drive-relative -> books-relative
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


class GraphSharingProvider(_GraphHttp, SharingProvider):
    """Share the books folder with an accountant, and find the books folders shared with an accountant.

    Microsoft Learn, checked 28 Oct 2026:

    * `POST /drives/{drive-id}/items/{item-id}/invite` with `recipients`, `roles` (`read` | `write`),
      `requireSignIn`, `sendInvitation`, `message` (max 2,000 characters); 200 (or 207 for a partial success) with a
      collection of `permission` objects. Least privileged delegated scope **Files.ReadWrite** (work and personal);
      `Files.ReadWrite.AppFolder` is not listed, and permissions cannot be created on the *root* item of a personal
      drive (the app folder is not the root). https://learn.microsoft.com/graph/api/driveitem-invite
    * `DELETE /drives/{drive-id}/items/{item-id}/permissions/{perm-id}`, 204; only non-inherited permissions;
      Files.ReadWrite. https://learn.microsoft.com/graph/api/permission-delete
    * `GET /me/drive/sharedWithMe` (`?allowexternal=true` for other tenants): driveItems with a `remoteItem` facet;
      needs `Files.Read.All` to open what it lists. **Deprecated: "will operate in a degraded state until November,
      2026, after which it will stop returning data"**, with no documented replacement, so the portal also keeps the
      client links an accountant adds by hand. https://learn.microsoft.com/graph/api/drive-sharedwithme
    """

    async def books_root(self, account_kind: str) -> SharedRoot:
        if account_kind == "personal":
            item = (await self._request("GET", f"{GRAPH}/me/drive/special/approot")).json()
        else:
            resp = await self._request("GET", f"{GRAPH}/me/drive/root:/Accnomos", ok404=True)
            if resp.status_code == 404:
                raise FileNotFoundError("Accnomos")  # the books are made at onboarding, never by sharing
            item = resp.json()
        drive = (item.get("parentReference") or {}).get("driveId")
        if not drive:  # the approot item does not always carry its drive id; the drive itself does
            drive = (await self._request("GET", f"{GRAPH}/me/drive", params={"$select": "id"})).json()["id"]
        return SharedRoot(drive_id=_safe_id(drive, "drive id"), item_id=_safe_id(item["id"], "item id"))

    @staticmethod
    def _item(root: SharedRoot, rest: str = "", path: str = "") -> str:
        """The item, or `path` inside it path-addressed (`.../items/{id}:/{path}:/invite`)."""
        base = f"{GRAPH}/drives/{_safe_id(root.drive_id, 'drive id')}/items/{_safe_id(root.item_id, 'item id')}"
        path = _safe_path(path.strip("/"))
        if path:
            return f"{base}:/{quote(path, safe='/')}:{rest}"
        return base + rest

    async def invite(
        self, root: SharedRoot, email: str, role: ShareRole, message: str, path: str = ""
    ) -> SharePermission:
        if role not in ("read", "write"):
            raise ValueError(f"role must be 'read' or 'write', not {role!r}")
        body = {
            "recipients": [{"email": email}],
            "roles": [role],
            "requireSignIn": True,
            "sendInvitation": True,
            "message": message[:2000],
        }
        page = (await self._request("POST", self._item(root, "/invite", path), json=body)).json()
        perms = page.get("value") or []
        if not perms:
            raise GraphError(200, "invite answered with no permission")
        perm = perms[0]
        if isinstance(perm.get("error"), dict) and not perm.get("id"):
            raise GraphError(207, str(perm["error"].get("message") or perm["error"].get("code")))
        invited = (perm.get("invitation") or {}).get("email") or email
        return SharePermission(id=str(perm["id"]), roles=list(perm.get("roles") or [role]), email=invited)

    async def revoke(self, root: SharedRoot, permission_id: str, path: str = "") -> bool:
        resp = await self._request(
            "DELETE", self._item(root, f"/permissions/{quote(permission_id, safe='')}", path), ok404=True
        )
        return resp.status_code != 404

    async def shared_with_me(self) -> list[SharedFolder]:
        url: str | None = f"{GRAPH}/me/drive/sharedWithMe?allowexternal=true"
        out: list[SharedFolder] = []
        while url:
            page = (await self._request("GET", url)).json()
            for item in page.get("value", []):
                remote = item.get("remoteItem") or {}
                drive = (remote.get("parentReference") or {}).get("driveId")
                if "folder" not in remote or not drive or not remote.get("id"):
                    continue  # files, and anything Graph sent without an address
                if not (_ID.fullmatch(drive) and _ID.fullmatch(remote["id"])):
                    continue
                shared = remote.get("shared") or {}
                owner = (shared.get("owner") or shared.get("sharedBy") or {}).get("user") or {}
                when = shared.get("sharedDateTime")
                out.append(
                    SharedFolder(
                        drive_id=drive,
                        item_id=remote["id"],
                        name=remote.get("name") or item.get("name") or "",
                        owner=owner.get("email") or owner.get("displayName"),
                        shared_at=_iso(when) if when else None,
                        web_url=remote.get("webUrl"),
                    )
                )
            url = page.get("@odata.nextLink")
        return out

    async def folder(self, root: SharedRoot) -> SharedFolder:
        item = (await self._request("GET", self._item(root))).json()
        if "folder" not in item:
            raise FileNotFoundError(root.item_id)
        shared = item.get("shared") or {}
        owner = ((shared.get("owner") or {}).get("user") or {}) or ((item.get("createdBy") or {}).get("user") or {})
        return SharedFolder(
            drive_id=root.drive_id,
            item_id=root.item_id,
            name=item.get("name") or "",
            owner=owner.get("email") or owner.get("displayName"),
            web_url=item.get("webUrl"),
        )

    async def child_names(self, root: SharedRoot) -> set[str]:
        url: str | None = self._item(root, "/children") + "?$select=name,folder"
        names: set[str] = set()
        while url:
            page = (await self._request("GET", url)).json()
            names |= {str(i.get("name")) for i in page.get("value", []) if i.get("name")}
            url = page.get("@odata.nextLink")
        return names

    async def whoami(self) -> Identity:
        me = (
            await self._request("GET", f"{GRAPH}/me", params={"$select": "mail,userPrincipalName,displayName"})
        ).json()
        email = (me.get("mail") or me.get("userPrincipalName") or "").strip().lower()
        if not email:
            raise GraphError(200, "/me has neither mail nor userPrincipalName")
        return Identity(email=email, name=me.get("displayName") or "")


def _iso(dt: str | None) -> datetime:
    return datetime.fromisoformat((dt or "1970-01-01T00:00:00Z").replace("Z", "+00:00"))


_BODY_TAG = re.compile(r"<body[^>]*>", re.IGNORECASE)


def _with_reply_text(body: dict[str, Any], text: str) -> dict[str, Any]:
    """The draft's body with `text` put above the quoted thread that createReply wrote."""
    content = body.get("content") or ""
    if (body.get("contentType") or "").lower() != "html":
        return {"contentType": "text", "content": f"{text}\n\n{content}" if content else text}
    block = "<div>" + html.escape(text).replace("\n", "<br>") + "</div><br>"
    m = _BODY_TAG.search(content)
    merged = content[: m.end()] + block + content[m.end() :] if m else block + content
    return {"contentType": "html", "content": merged}


class GraphMailProvider(_GraphHttp, MailProvider):
    """Outlook mail via Microsoft Graph. Personal and work accounts use the same endpoints.

    Reading needs `Mail.Read` and only sends GET requests. `create_reply_draft` needs `Mail.ReadWrite`,
    which the app asks for only when the user taps *Draft reply*; it saves a draft and never sends.

    `mailbox` reads a shared or delegated mailbox the signed-in user can open: `/users/{address}/...` instead of
    `/me/...`, with a delegated `Mail.Read.Shared` token (work or school accounts only). Microsoft Learn,
    https://learn.microsoft.com/graph/outlook-share-messages-folders and
    https://learn.microsoft.com/graph/permissions-reference#mailreadshared (checked 28 Oct 2026).
    """

    PAGE = 50
    TRIAGE_SELECT = "id,conversationId,subject,from,receivedDateTime,bodyPreview,isRead,webLink"
    WELL_KNOWN = frozenset({"inbox", "archive"})  # folders intake may watch by name; Sent and Drafts never

    def __init__(self, token: str, *, mailbox: str | None = None, **kw: Any) -> None:
        super().__init__(token, **kw)
        self._base = f"{GRAPH}/users/{quote(mailbox.strip(), safe='@')}" if mailbox else f"{GRAPH}/me"
        self._folder_ids: dict[str, str] = {}

    def _message_url(self, message_id: str, rest: str = "") -> str:
        return f"{self._base}/messages/{quote(message_id, safe='')}" + rest

    async def _folder_url(self, folder: str | None, default: str | None) -> str:
        """`{base}/messages` (every folder), `{base}/mailFolders/inbox/messages`, or a top-level folder found by
        its display name (`$filter=displayName eq '...'`); a folder that is not there raises FileNotFoundError."""
        want = default if folder in (None, "", "all") else folder
        if want is None:
            return f"{self._base}/messages"
        if want.lower() in self.WELL_KNOWN:
            return f"{self._base}/mailFolders/{want.lower()}/messages"
        if want not in self._folder_ids:
            name = want.replace("'", "''")
            page = (
                await self._request(
                    "GET",
                    f"{self._base}/mailFolders",
                    params={"$filter": f"displayName eq '{name}'", "$select": "id,displayName"},
                )
            ).json()
            hits = page.get("value") or []
            if not hits:
                raise FileNotFoundError(f"mail folder {want!r}")
            self._folder_ids[want] = hits[0]["id"]
        return f"{self._base}/mailFolders/{quote(self._folder_ids[want], safe='')}/messages"

    async def list_recent(self, since: datetime, max_results: int = 100) -> list[MailMessage]:
        since_utc = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        params: dict[str, str] | None = {
            "$filter": f"receivedDateTime ge {since_utc}",
            "$select": self.TRIAGE_SELECT,
            "$orderby": "receivedDateTime desc",
            "$top": str(min(self.PAGE, max(1, max_results))),
        }
        url: str | None = f"{self._base}/mailFolders/inbox/messages"  # not Junk, Deleted, Drafts or Sent
        out: list[MailMessage] = []
        while url and len(out) < max_results:
            page = (await self._request("GET", url, params=params)).json()
            params = None  # nextLink already carries the query
            for m in page.get("value", []):
                sender = (m.get("from") or {}).get("emailAddress") or {}
                out.append(
                    MailMessage(
                        id=m["id"],
                        received_at=_iso(m.get("receivedDateTime")),
                        from_address=(sender.get("address") or "").lower(),
                        from_name=sender.get("name") or "",
                        subject=m.get("subject") or "",
                        web_link=m.get("webLink"),
                        conversation_id=m.get("conversationId") or m["id"],
                        body_preview=(m.get("bodyPreview") or "")[:255],
                        is_read=bool(m.get("isRead", True)),
                    )
                )
            url = page.get("@odata.nextLink")
        return out[:max_results]

    async def create_reply_draft(self, message_id: str, body_text: str) -> MailDraft:
        """`createReply` (a draft addressed to the sender, thread quoted), then PATCH our text into its body."""
        draft = (await self._request("POST", self._message_url(message_id, "/createReply"), json={})).json()
        body = _with_reply_text(draft.get("body") or {}, body_text)
        patched = (await self._request("PATCH", self._message_url(draft["id"]), json={"body": body})).json()
        return MailDraft(id=draft["id"], web_link=patched.get("webLink") or draft.get("webLink"))

    async def list_messages(
        self, since: datetime, max_results: int = 50, *, folder: str | None = None
    ) -> list[MailMessage]:
        since_utc = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        # $orderby must use the first $filter property, or Graph rejects the query as "InefficientFilter".
        params: dict[str, str] | None = {
            "$filter": f"receivedDateTime ge {since_utc} and hasAttachments eq true",
            "$select": "id,receivedDateTime,from,subject,hasAttachments,webLink",
            "$orderby": "receivedDateTime desc",
            "$top": str(min(self.PAGE, max(1, max_results))),
        }
        url: str | None = await self._folder_url(folder, None)
        out: list[MailMessage] = []
        while url and len(out) < max_results:
            page = (await self._request("GET", url, params=params)).json()
            params = None  # nextLink already carries the query
            for m in page.get("value", []):
                sender = (m.get("from") or {}).get("emailAddress") or {}
                out.append(
                    MailMessage(
                        id=m["id"],
                        received_at=_iso(m.get("receivedDateTime")),
                        from_address=(sender.get("address") or "").lower(),
                        from_name=sender.get("name") or "",
                        subject=m.get("subject") or "",
                        has_attachments=bool(m.get("hasAttachments")),
                        web_link=m.get("webLink"),
                    )
                )
            url = page.get("@odata.nextLink")
        return out[:max_results]

    async def list_without_attachments(
        self, since: datetime, max_results: int = 50, *, folder: str | None = None
    ) -> list[MailMessage]:
        since_utc = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        params: dict[str, str] | None = {
            "$filter": f"receivedDateTime ge {since_utc} and hasAttachments eq false",
            "$select": "id,receivedDateTime,from,subject,hasAttachments,bodyPreview,webLink",
            "$orderby": "receivedDateTime desc",
            "$top": str(min(self.PAGE, max(1, max_results))),
        }
        # not Sent: the user's own invoices are not costs
        url: str | None = await self._folder_url(folder, "inbox")
        out: list[MailMessage] = []
        while url and len(out) < max_results:
            page = (await self._request("GET", url, params=params)).json()
            params = None  # nextLink already carries the query
            for m in page.get("value", []):
                sender = (m.get("from") or {}).get("emailAddress") or {}
                out.append(
                    MailMessage(
                        id=m["id"],
                        received_at=_iso(m.get("receivedDateTime")),
                        from_address=(sender.get("address") or "").lower(),
                        from_name=sender.get("name") or "",
                        subject=m.get("subject") or "",
                        web_link=m.get("webLink"),
                        body_preview=(m.get("bodyPreview") or "")[:255],
                    )
                )
            url = page.get("@odata.nextLink")
        return out[:max_results]

    async def message_text(self, message_id: str) -> str:
        """`Prefer: outlook.body-content-type="text"` makes Graph turn an HTML body into plain text."""
        r = await self._request(
            "GET",
            self._message_url(message_id),
            params={"$select": "body"},
            headers={"Prefer": 'outlook.body-content-type="text"'},
        )
        return ((r.json().get("body") or {}).get("content")) or ""

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
                out.append(
                    MailAttachment(
                        id=a["id"],
                        name=a.get("name") or "attachment",
                        content_type=(a.get("contentType") or "").lower(),
                        size=int(a.get("size") or 0),
                        is_inline=bool(a.get("isInline")),
                    )
                )
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
                out.append(
                    AddressBookContact(
                        id=c["id"],
                        display_name=(c.get("displayName") or "").strip(),
                        company_name=(c.get("companyName") or "").strip(),
                        emails=[e for e in emails if e],
                        business_phones=[p.strip() for p in c.get("businessPhones") or [] if p and p.strip()],
                    )
                )
            url = page.get("@odata.nextLink")
        return out[:max_results]


class GraphMailSender(_GraphHttp, MailSender):
    """`POST /me/sendMail` (`Mail.Send`), saved to the user's Sent Items. Attachments go inline as base64 in one
    JSON request, which Graph limits to 4 MB; an invoice PDF is far smaller. The limit applies to the encoded
    request (base64 is 4/3 of the raw bytes, plus the JSON around it), so it is checked on the bytes actually
    sent. Larger attachments would need a draft and an attachment upload session, which this sender does not do:
    it refuses with a clear error before anything is sent."""

    MAX_REQUEST_BYTES = 4_000_000  # a cautious reading of Graph's "4 MB"

    async def send(self, mail: OutgoingMail) -> None:
        message = {
            "subject": mail.subject,
            "body": {"contentType": "Text", "content": mail.body_text},
            "toRecipients": [{"emailAddress": {"address": mail.to}}],
            "attachments": [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": a.name,
                    "contentType": a.content_type,
                    "contentBytes": base64.b64encode(a.data).decode(),
                }
                for a in mail.attachments
            ],
        }
        content = json.dumps({"message": message, "saveToSentItems": True}, separators=(",", ":")).encode()
        if len(content) > self.MAX_REQUEST_BYTES:
            raw = sum(len(a.data) for a in mail.attachments)
            raise ValueError(
                f"The email is too big to send in one go ({raw / 1_000_000:.1f} MB of attachments; "
                f"about {self.MAX_REQUEST_BYTES * 3 // 4 / 1_000_000:.1f} MB is the most Outlook accepts here)"
            )
        await self._request(
            "POST", f"{GRAPH}/me/sendMail", content=content, headers={"Content-Type": "application/json"}
        )


def _graph_utc(value: dict[str, Any] | None) -> datetime:
    """A Graph dateTimeTimeZone read with `Prefer: outlook.timezone="UTC"` -> aware UTC datetime."""
    raw = ((value or {}).get("dateTime") or "1970-01-01T00:00:00")[:26]  # Graph sends 7 fractional digits
    return datetime.fromisoformat(raw.removesuffix("Z")).replace(tzinfo=UTC)


class GraphCalendarProvider(_GraphHttp, CalendarProvider):
    """Outlook calendar via Microsoft Graph. Reading needs `Calendars.Read`; `create_event` needs
    `Calendars.ReadWrite`, which the app asks for only when the user approves a plan."""

    PAGE = 100
    SELECT = "subject,start,end,location,bodyPreview,isAllDay,showAs,isCancelled"

    async def list_events(self, day: date, tz: str = "Europe/London") -> list[CalendarEvent]:
        zone = ZoneInfo(tz)
        start = datetime.combine(day, time(0), zone).astimezone(UTC)
        end = datetime.combine(day + timedelta(days=1), time(0), zone).astimezone(UTC)
        params: dict[str, str] | None = {
            "startDateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endDateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "$select": self.SELECT,
            "$orderby": "start/dateTime",
            "$top": str(self.PAGE),
        }
        headers = {"Prefer": 'outlook.timezone="UTC"'}
        url: str | None = f"{GRAPH}/me/calendarView"
        out: list[CalendarEvent] = []
        while url:
            page = (await self._request("GET", url, params=params, headers=headers)).json()
            params = None  # nextLink already carries the query
            for e in page.get("value", []):
                if e.get("isCancelled"):
                    continue
                out.append(
                    CalendarEvent(
                        id=e["id"],
                        subject=e.get("subject") or "",
                        start=_graph_utc(e.get("start")),
                        end=_graph_utc(e.get("end")),
                        location=((e.get("location") or {}).get("displayName") or ""),
                        body_preview=e.get("bodyPreview") or "",
                        is_all_day=bool(e.get("isAllDay")),
                        show_as=e.get("showAs") or "busy",
                    )
                )
            url = page.get("@odata.nextLink")
        return sorted(out, key=lambda e: e.start)

    async def create_event(self, subject: str, start: datetime, end: datetime, location: str, body: str) -> str:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")

        def stamp(dt: datetime) -> dict[str, str]:
            return {"dateTime": dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"}

        payload: dict[str, Any] = {
            "subject": subject,
            "start": stamp(start),
            "end": stamp(end),
            "body": {"contentType": "text", "content": body},
            "showAs": "busy",
            "isReminderOn": False,
        }
        if location:
            payload["location"] = {"displayName": location}
        return (await self._request("POST", f"{GRAPH}/me/events", json=payload)).json()["id"]
