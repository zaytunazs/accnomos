"""A small Microsoft Graph look-alike over an in-memory `FakeStorageProvider`.

The browser makes a handful of Graph calls of its own (apps/web/src/lib/graph.ts: folder setup, Files, "Add a
receipt", the Review preview). Two runtimes answer them here instead of Microsoft, each over its own fake storage:

* test mode (app/testmode.py, `/__test/graph/v1.0`): one fake OneDrive per Playwright worker;
* the demo sandbox (app/demo.py, `/demo/graph/v1.0`): one fake OneDrive per demo visitor.

Path-addressed under the books root (`me/drive/special/approot` or `me/drive/root:/Accnomos`), plus id-addressed
folder creation (`me/drive/items/{id}/children`). Nothing here talks to Microsoft.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from accnomos_connectors import FakeStorageProvider
from accnomos_connectors.base import FileRef

GRAPH_ROOT_ID = "t-root"
_ROOTS = ("me/drive/special/approot", "me/drive/root:/Accnomos")
_MIME = {  # a listed file's mimeType
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "pdf": "application/pdf",
    "json": "application/json",
    "txt": "text/plain",
}
_CONTENT = {  # a file's content
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "pdf": "application/pdf",
}


def item_id(path: str) -> str:
    return "t-" + base64.urlsafe_b64encode(path.encode()).decode().rstrip("=") if path else GRAPH_ROOT_ID


def path_of(value: str) -> str:
    if value == GRAPH_ROOT_ID:
        return ""
    if not value.startswith("t-"):
        raise ValueError(value)
    raw = value.removeprefix("t-")
    return base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True).decode()


def drive_item(st: FakeStorageProvider, ref: FileRef, web_base: str | None) -> dict[str, Any]:
    path = ref.path.strip("/")
    item: dict[str, Any] = {
        "id": item_id(path),
        "name": ref.name or "Accnomos",
        "eTag": ref.etag,
        "lastModifiedDateTime": (ref.modified or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
    }
    if web_base is not None:
        item["webUrl"] = f"{web_base}/{path}"
    if ref.is_folder:
        prefix = f"{path}/" if path else ""
        item["size"] = sum(len(v) for k, v in st.files.items() if k.startswith(prefix))
        children = {k[len(prefix) :].split("/", 1)[0] for k in [*st.files, *st.folders] if k and k.startswith(prefix)}
        item["folder"] = {"childCount": len(children)}
    else:
        item["size"] = ref.size
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        item["file"] = {"mimeType": _MIME.get(ext, "application/octet-stream")}
    return item


def not_found(path: str) -> JSONResponse:
    return JSONResponse({"error": {"code": "itemNotFound", "message": f"Item does not exist: {path}"}}, status_code=404)


async def respond(
    st: FakeStorageProvider,
    rest: str,
    request: Request,
    web_base: str | None,
    put: Callable[[str, bytes], Awaitable[FileRef]] | None = None,
) -> Response:
    """Answer one Graph call against `st`. `put` (path, bytes) replaces a plain `st.write` for uploads, so the demo
    can apply its size limits."""

    def item(ref: FileRef) -> dict[str, Any]:
        return drive_item(st, ref, web_base)

    method = request.method
    if rest == "me/drive/root/children" and method == "POST":  # work account: create /Accnomos
        return JSONResponse(item(FileRef(id="", path="", name="Accnomos", is_folder=True)), status_code=201)
    if m := re.fullmatch(r"me/drive/items/([^/]+)/children", rest):
        if method != "POST":
            return JSONResponse({"error": {"code": "notSupported"}}, status_code=400)
        try:
            parent = path_of(m.group(1))
        except ValueError:  # not an id this look-alike handed out (binascii.Error and UnicodeDecodeError included)
            return not_found(m.group(1))
        name = (await request.json()).get("name")
        if not isinstance(name, str) or not name.strip("/"):
            return JSONResponse({"error": {"code": "invalidRequest", "message": "name required"}}, status_code=400)
        if parent and parent not in st.folders:
            return not_found(parent)
        path = f"{parent}/{name}".strip("/")
        if path in st.folders or path in st.files:
            return JSONResponse({"error": {"code": "nameAlreadyExists"}}, status_code=409)
        return JSONResponse(item(await st.ensure_folder(path)), status_code=201)
    root = next((r for r in _ROOTS if rest == r or rest.startswith(r + ":/") or rest.startswith(r + "/")), None)
    if root is None:
        return not_found(rest)
    tail = rest[len(root) :]
    action = ""
    if tail in ("/children", ":/children"):
        rel, action = "", "children"
    else:
        tail = tail.removeprefix(":/").removeprefix("/")
        for suffix in (":/children", ":/content"):
            if tail.endswith(suffix):
                tail, action = tail[: -len(suffix)], suffix[2:]
        rel = tail.strip("/")
    if action == "content" and method == "PUT":
        data = await request.body()
        ref = await (put or st.write)(rel, data)
        return JSONResponse(item(ref), status_code=201)
    if action == "content":
        if rel not in st.files:
            return not_found(rel)
        ext = rel.rsplit(".", 1)[-1].lower()  # the Review preview reads the filed receipt
        return Response(st.files[rel], media_type=_CONTENT.get(ext, "application/octet-stream"))
    if action == "children":
        if rel not in st.folders:
            return not_found(rel)
        return JSONResponse({"value": [item(r) for r in await st.list(rel)]})
    if rel in st.folders:
        return JSONResponse(item(FileRef(id="", path=rel, name=rel.rsplit("/", 1)[-1], is_folder=True)))
    if rel in st.files:
        return JSONResponse(item(st._ref(rel)))
    return not_found(rel)
