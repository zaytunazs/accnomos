"""A Google Drive v3 look-alike in memory, served as an httpx MockTransport, for tests.

It answers the calls accnomos_connectors.google_drive makes, and only those: `files.list` with the query grammar that
module writes (`name = '…'`, `'<id>' in parents`, `mimeType =/!= '…'`, `trashed = false`, joined by `and`), files
create/get/update (JSON, multipart and resumable uploads, `alt=media`, add/removeParents), the changes API and OIDC
userinfo. Everything else is a 400 so a test notices a call the fake does not know.

    drive = FakeDrive()
    google_drive.TRANSPORT = drive.transport()
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

FOLDER_MIME = "application/vnd.google-apps.folder"
ROOT_ID = "root-of-my-drive"
_CLAUSE = re.compile(
    r"""\s*(?:
        name\s*=\s*'(?P<name>(?:[^'\\]|\\.)*)'
      | '(?P<parent>(?:[^'\\]|\\.)*)'\s+in\s+parents
      | mimeType\s*(?P<mop>!?=)\s*'(?P<mime>(?:[^'\\]|\\.)*)'
      | trashed\s*=\s*(?P<trashed>true|false)
    )\s*$""",
    re.X,
)


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s)


class FakeDrive:
    """One user's My Drive. `token` is the only access token it accepts (401 otherwise)."""

    def __init__(self, token: str = "google-token", email: str = "owner@example.com", name: str = "Owner") -> None:
        self.token, self.email, self.name = token, email, name
        self.items: dict[str, dict[str, Any]] = {}
        self.content: dict[str, bytes] = {}
        self.change_log: list[str] = []  # file ids, one per change; the page token is an index into it
        self.sessions: dict[str, tuple[str, str | None, dict[str, Any]]] = {}  # upload id -> (method, file id, meta)
        self.calls: list[str] = []
        self.fail_next: list[int] = []  # statuses to answer the next requests with (429 retry tests)
        self._n = 0
        self._clock = datetime(2026, 11, 1, tzinfo=UTC)

    # ------------------------------------------------------------------ helpers

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _id(self) -> str:
        self._n += 1
        return f"f{self._n:04d}"

    def _tick(self) -> str:
        self._clock += timedelta(seconds=1)
        return self._clock.isoformat().replace("+00:00", "Z")

    def _changed(self, fid: str) -> None:
        self.change_log.append(fid)

    def add(self, name: str, parent: str = ROOT_ID, data: bytes | None = None, mime: str | None = None) -> str:
        """Seed an item directly (e.g. a duplicate name made by another device). Returns its id."""
        fid = self._id()
        now = self._tick()
        self.items[fid] = {
            "id": fid,
            "name": name,
            "mimeType": mime or (FOLDER_MIME if data is None else "application/octet-stream"),
            "parents": [parent],
            "trashed": False,
            "version": "1",
            "createdTime": now,
            "modifiedTime": now,
            "webViewLink": f"https://drive.google.com/file/d/{fid}/view",
        }
        if data is not None:
            self.content[fid] = data
        self._changed(fid)
        return fid

    def path_of(self, fid: str) -> str:
        parts: list[str] = []
        while fid in self.items:
            parts.append(self.items[fid]["name"])
            fid = self.items[fid]["parents"][0]
        return "/".join(reversed(parts))

    def find(self, path: str) -> dict[str, Any] | None:
        """Test helper: the oldest item at a My Drive path such as 'Accnomos/00 Inbox/a.jpg'."""
        parent = ROOT_ID
        item = None
        for seg in path.split("/"):
            kids = [i for i in self.items.values() if parent in i["parents"] and i["name"] == seg and not i["trashed"]]
            if not kids:
                return None
            item = min(kids, key=lambda i: i["createdTime"])
            parent = item["id"]
        return item

    def _view(self, item: dict[str, Any]) -> dict[str, Any]:
        out = dict(item)
        if item["id"] in self.content:
            data = self.content[item["id"]]
            out["size"] = str(len(data))
            out["md5Checksum"] = hashlib.md5(data).hexdigest()  # noqa: S324  Drive's own checksum
        return out

    def _match(self, item: dict[str, Any], q: str) -> bool:
        for clause in re.split(r"\s+and\s+", q):
            m = _CLAUSE.match(clause)
            if not m:
                raise ValueError(f"fake drive cannot parse {clause!r}")
            if m["name"] is not None and item["name"] != _unescape(m["name"]):
                return False
            if m["parent"] is not None:
                want = _unescape(m["parent"])
                if (ROOT_ID if want == "root" else want) not in item["parents"]:
                    return False
            if m["mime"] is not None and (item["mimeType"] == _unescape(m["mime"])) != (m["mop"] == "="):
                return False
            if m["trashed"] is not None and item["trashed"] != (m["trashed"] == "true"):
                return False
        return True

    @staticmethod
    def _json(status: int, body: Any = None, headers: dict[str, str] | None = None) -> httpx.Response:
        return httpx.Response(status, json=body if body is not None else {}, headers=headers)

    def _err(self, status: int, message: str) -> httpx.Response:
        return self._json(status, {"error": {"code": status, "message": message}})

    # ------------------------------------------------------------------ dispatch

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        params = {k: v[-1] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
        self.calls.append(f"{request.method} {url.path}")
        if request.headers.get("Authorization") != f"Bearer {self.token}":
            return self._err(401, "Invalid Credentials")
        if self.fail_next:
            status = self.fail_next.pop(0)
            return httpx.Response(status, json={"error": {"code": status}}, headers={"Retry-After": "0"})
        host, path = url.netloc, url.path
        if host == "openidconnect.googleapis.com" and path == "/v1/userinfo":
            return self._json(200, {"sub": "1234", "email": self.email, "email_verified": True, "name": self.name})
        if host != "www.googleapis.com":
            return self._err(400, f"unknown host {host}")
        if path == "/drive/v3/changes/startPageToken":
            return self._json(200, {"startPageToken": str(len(self.change_log))})
        if path == "/drive/v3/changes":
            return self._changes(params)
        if path == "/drive/v3/files" and request.method == "GET":
            return self._list(params)
        if path == "/drive/v3/files" and request.method == "POST":
            return self._create(json.loads(request.content or b"{}"), None)
        if m := re.fullmatch(r"/drive/v3/files/([^/]+)", path):
            return self._file(request, m.group(1), params)
        if path == "/upload/drive/v3/files" or re.fullmatch(r"/upload/drive/v3/files/[^/]+", path):
            fid = path.rsplit("/", 1)[-1] if path.count("/") == 5 else None
            return self._upload(request, fid, params)
        return self._err(400, f"fake drive does not know {request.method} {path}")

    # ------------------------------------------------------------------ files

    def _list(self, params: dict[str, str]) -> httpx.Response:
        try:
            hits = [i for i in self.items.values() if self._match(i, params.get("q", ""))]
        except ValueError as exc:
            return self._err(400, str(exc))
        order = params.get("orderBy", "")
        if order.startswith("folder"):
            hits.sort(key=lambda i: (i["mimeType"] != FOLDER_MIME, i["name"], i["createdTime"]))
        else:
            hits.sort(key=lambda i: i["createdTime"])
        size = int(params.get("pageSize", "100"))
        start = int(params.get("pageToken", "0"))
        page = hits[start : start + size]
        body: dict[str, Any] = {"files": [self._view(i) for i in page]}
        if start + size < len(hits):
            body["nextPageToken"] = str(start + size)
        return self._json(200, body)

    def _create(self, meta: dict[str, Any], data: bytes | None) -> httpx.Response:
        parents = meta.get("parents") or [ROOT_ID]
        parents = [ROOT_ID if p == "root" else p for p in parents]
        if any(p != ROOT_ID and p not in self.items for p in parents):
            return self._err(404, "parent not found")
        fid = self.add(meta["name"], parents[0], data, meta.get("mimeType") if data is None else None)
        if data is None and meta.get("mimeType") != FOLDER_MIME:
            self.items[fid]["mimeType"] = meta.get("mimeType") or "application/octet-stream"
            self.content[fid] = b""
        return self._json(200, self._view(self.items[fid]))

    def _bump(self, fid: str) -> None:
        item = self.items[fid]
        item["version"] = str(int(item["version"]) + 1)
        item["modifiedTime"] = self._tick()
        self._changed(fid)

    def _file(self, request: httpx.Request, fid: str, params: dict[str, str]) -> httpx.Response:
        item = self.items.get(fid)
        if item is None:
            return self._err(404, "File not found")
        if request.method == "GET":
            if params.get("alt") == "media":
                if item["mimeType"] == FOLDER_MIME:
                    return self._err(403, "fileNotDownloadable")
                return httpx.Response(200, content=self.content.get(fid, b""))
            return self._json(200, self._view(item))
        if request.method == "PATCH":
            meta = json.loads(request.content or b"{}")
            if "name" in meta:
                item["name"] = meta["name"]
            for p in filter(None, params.get("removeParents", "").split(",")):
                item["parents"] = [x for x in item["parents"] if x != p]
            for p in filter(None, params.get("addParents", "").split(",")):
                if p not in self.items and p != ROOT_ID:
                    return self._err(404, "parent not found")
                item["parents"].append(p)
            self._bump(fid)
            return self._json(200, self._view(item))
        return self._err(400, f"fake drive does not know {request.method} on a file")

    def _upload(self, request: httpx.Request, fid: str | None, params: dict[str, str]) -> httpx.Response:
        kind = params.get("uploadType")
        if fid is not None and fid not in self.items:
            return self._err(404, "File not found")
        if kind == "multipart":
            meta, data = self._multipart(request)
            return self._store(request.method, fid, meta, data)
        if kind == "resumable" and "upload_id" not in params:
            upload_id = f"u{len(self.sessions) + 1}"
            self.sessions[upload_id] = (request.method, fid, json.loads(request.content or b"{}"))
            loc = f"https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id={upload_id}"
            return self._json(200, {}, {"Location": loc})
        if kind == "resumable":
            method, sfid, meta = self.sessions.pop(params["upload_id"])
            return self._store(method, sfid, meta, request.content)
        if kind == "media" and fid is not None:
            return self._store("PATCH", fid, {}, request.content)
        return self._err(400, f"uploadType {kind!r}")

    def _store(self, method: str, fid: str | None, meta: dict[str, Any], data: bytes) -> httpx.Response:
        if method == "POST":
            return self._create({**meta, "mimeType": "application/octet-stream"}, data)
        assert fid is not None
        self.content[fid] = data
        if "name" in meta:
            self.items[fid]["name"] = meta["name"]
        self._bump(fid)
        return self._json(200, self._view(self.items[fid]))

    @staticmethod
    def _multipart(request: httpx.Request) -> tuple[dict[str, Any], bytes]:
        ctype = request.headers.get("Content-Type", "")
        boundary = ctype.split("boundary=", 1)[1].encode()
        parts = request.content.split(b"--" + boundary)
        meta_part, data_part = parts[1], parts[2]
        meta = json.loads(meta_part.split(b"\r\n\r\n", 1)[1].rstrip(b"\r\n"))
        data = data_part.split(b"\r\n\r\n", 1)[1]
        return meta, data.removesuffix(b"\r\n")

    # ------------------------------------------------------------------ changes

    def _changes(self, params: dict[str, str]) -> httpx.Response:
        start = int(params["pageToken"])
        size = int(params.get("pageSize", "100"))
        ids = self.change_log[start : start + size]
        changes = []
        for fid in ids:
            item = self.items.get(fid)
            changes.append({"fileId": fid, "removed": item is None, **({"file": self._view(item)} if item else {})})
        body: dict[str, Any] = {"changes": changes}
        if start + size < len(self.change_log):
            body["nextPageToken"] = str(start + size)
        else:
            body["newStartPageToken"] = str(len(self.change_log))
        return self._json(200, body)
