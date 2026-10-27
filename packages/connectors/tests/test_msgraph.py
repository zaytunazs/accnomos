"""GraphStorageProvider against httpx.MockTransport (no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from accnomos_connectors.base import ConflictError
from accnomos_connectors.msgraph import GRAPH, GraphError, GraphStorageProvider

pytestmark = pytest.mark.asyncio

APPROOT = "/v1.0/me/drive/special/approot"


def _item(id_: str, name: str, folder: bool = False, **extra: object) -> dict:
    out: dict = {"id": id_, "name": name, "eTag": f'"{{{id_}}},1"', "size": 0, **extra}
    if folder:
        out["folder"] = {"childCount": 0}
    return out


def _provider(handler, kind: str = "personal", slept: list[float] | None = None) -> GraphStorageProvider:
    async def sleep(s: float) -> None:
        (slept if slept is not None else []).append(s)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GraphStorageProvider("tok", kind, client=client, sleep=sleep)  # type: ignore[arg-type]


async def test_folder_creation_posts_to_parent_item_ids():
    calls: list[tuple[str, str]] = []
    existing = {APPROOT: _item("ROOT", "Accnomos", True)}
    next_id = iter(range(1, 100))

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["Authorization"] == "Bearer tok"
        path = req.url.raw_path.decode()
        calls.append((req.method, path))
        if req.method == "GET":
            return httpx.Response(200, json=existing[path]) if path in existing else httpx.Response(404)
        if req.method == "POST" and path.startswith("/v1.0/me/drive/items/") and path.endswith("/children"):
            body = json.loads(req.content)
            assert body["folder"] == {} and body["@microsoft.graph.conflictBehavior"] == "fail"
            return httpx.Response(201, json=_item(f"F{next(next_id)}", body["name"], True))
        return httpx.Response(400, json={"error": "unexpected"})

    g = _provider(handler)
    await g.ensure_folder("01 Receipts/2026-10")
    posts = [p for m, p in calls if m == "POST"]
    assert posts == ["/v1.0/me/drive/items/ROOT/children", "/v1.0/me/drive/items/F1/children"]
    # Ids are cached: ensuring again makes no calls at all.
    calls.clear()
    await g.ensure_folder("01 Receipts/2026-10")
    assert calls == []


async def test_work_account_paths_and_root_creation():
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.raw_path.decode()
        seen.append(f"{req.method} {path}")
        if path == "/v1.0/me/drive/root:/Accnomos":
            return httpx.Response(404)
        if path == "/v1.0/me/drive/root":
            return httpx.Response(200, json=_item("DRIVEROOT", "root", True))
        if req.method == "POST" and path == "/v1.0/me/drive/items/DRIVEROOT/children":
            return httpx.Response(201, json=_item("ACC", "Accnomos", True, parentReference={"path": "/drive/root:"}))
        return httpx.Response(400)

    ref = await _provider(handler, "work").ensure_root()
    assert ref.id == "ACC" and ref.is_folder
    assert "POST /v1.0/me/drive/items/DRIVEROOT/children" in seen


async def test_write_412_raises_conflict_and_sends_if_match():
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.raw_path.decode()
        if req.method == "GET" and path == f"{APPROOT}:/_System":
            return httpx.Response(200, json=_item("SYS", "_System", True))
        if req.method == "PUT":
            assert path == f"{APPROOT}:/_System/rules.json:/content"
            return httpx.Response(412) if req.headers.get("If-Match") == '"old"' else httpx.Response(
                200, json=_item("R", "rules.json")
            )
        return httpx.Response(400)

    g = _provider(handler)
    assert (await g.write("_System/rules.json", b"[]")).id == "R"
    with pytest.raises(ConflictError):
        await g.write("_System/rules.json", b"[]", if_match='"old"')


@pytest.mark.parametrize("link", [
    "https://evil.example/v1.0/me/drive/root/delta?token=x",
    "http://graph.microsoft.com/v1.0/me/drive/root/delta",      # downgraded scheme
    "https://graph.microsoft.com.evil.example/v1.0/x",          # look-alike host
    "https://graph.microsoft.com@evil.example/v1.0/x",          # userinfo trick
])
async def test_the_token_never_follows_a_link_off_graph(link: str):
    """A nextLink or delta cursor is followed with the bearer token, so only Graph's own origin is accepted."""
    hosts: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        hosts.append(req.url.host)
        return httpx.Response(200, json={"value": [], "@odata.nextLink": link})

    g = _provider(handler)
    with pytest.raises(ValueError, match="outside https://graph.microsoft.com"):
        await g.changes(None)
    with pytest.raises(ValueError):
        await g.changes(link)
    assert hosts == ["graph.microsoft.com"]  # only the first, genuine page was requested


async def test_create_only_asks_graph_to_fail_on_an_existing_file():
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.raw_path.decode()
        if req.method == "GET" and path == f"{APPROOT}:/_System":
            return httpx.Response(200, json=_item("SYS", "_System", True))
        if req.method == "PUT":
            seen.append(req.url.params.get("@microsoft.graph.conflictBehavior", ""))
            return httpx.Response(409, json={"error": {"code": "nameAlreadyExists"}})
        return httpx.Response(400)

    with pytest.raises(FileExistsError):
        await _provider(handler).write("_System/rules.json", b"[]", create_only=True)
    assert seen == ["fail"]


async def test_large_upload_uses_session_without_auth():
    data = b"x" * (4 * 1024 * 1024 + 10)
    seen: dict[str, httpx.Request] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.raw_path.decode()
        if req.method == "GET" and path == f"{APPROOT}:/00%20Inbox":
            return httpx.Response(200, json=_item("IN", "00 Inbox", True))
        if req.method == "POST" and path.endswith(":/createUploadSession"):
            seen["session"] = req
            return httpx.Response(200, json={"uploadUrl": "https://upload.example/abc"})
        if req.url.host == "upload.example":
            seen["upload"] = req
            return httpx.Response(201, json=_item("BIG", "big.pdf"))
        return httpx.Response(400)

    ref = await _provider(handler).write("00 Inbox/big.pdf", data)
    assert ref.id == "BIG"
    up = seen["upload"]
    assert "Authorization" not in up.headers
    assert up.headers["Content-Range"] == f"bytes 0-{len(data) - 1}/{len(data)}"


async def test_path_encoding_and_404_maps_to_file_not_found():
    name = "01 Receipts/2026-10/2026-10-21 Screwfix £38.47.jpg"
    urls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        urls.append(req.url.raw_path.decode())
        if req.url.host == "dl.example":
            assert "Authorization" not in req.headers
            return httpx.Response(200, content=b"jpeg")
        if urls[-1].endswith("Screwfix%20%C2%A338.47.jpg:/content"):
            return httpx.Response(302, headers={"Location": "https://dl.example/file"})
        return httpx.Response(404)

    g = _provider(handler)
    assert await g.read(name) == b"jpeg"
    assert urls[0] == f"{APPROOT}:/01%20Receipts/2026-10/2026-10-21%20Screwfix%20%C2%A338.47.jpg:/content"
    with pytest.raises(FileNotFoundError):
        await g.read("00 Inbox/missing.jpg")


async def test_move_patches_item_with_parent_id_and_name():
    patched: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.raw_path.decode()
        if req.method == "GET" and path == f"{APPROOT}:/00%20Inbox/IMG_1.jpg":
            return httpx.Response(200, json=_item("IMG", "IMG_1.jpg"))
        if req.method == "GET" and path == f"{APPROOT}:/04%20Needs%20a%20look":
            return httpx.Response(200, json=_item("NAL", "04 Needs a look", True))
        if req.method == "PATCH" and path == "/v1.0/me/drive/items/IMG":
            patched.append(json.loads(req.content))
            return httpx.Response(200, json=_item("IMG", "x.jpg"))
        return httpx.Response(400)

    ref = await _provider(handler).move("00 Inbox/IMG_1.jpg", "04 Needs a look/x.jpg")
    assert patched == [{"parentReference": {"id": "NAL"}, "name": "x.jpg"}]
    assert ref.path == "04 Needs a look/x.jpg"


async def test_renaming_a_folder_patches_its_name_and_forgets_cached_paths_under_it():
    patched: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.raw_path.decode()
        if req.method == "GET" and path == APPROOT:
            return httpx.Response(200, json=_item("ROOT", "Accnomos", True))
        if req.method == "GET" and path == f"{APPROOT}:/03%20Bank%20statements":
            return httpx.Response(200, json=_item("OLD", "03 Bank statements", True))
        if req.method == "PATCH" and path == "/v1.0/me/drive/items/OLD":
            patched.append(json.loads(req.content))
            return httpx.Response(200, json=_item("OLD", "04 Bank statements", True))
        return httpx.Response(400)

    g = _provider(handler)
    g._folders["03 Bank statements/2026"] = _item("SUB", "2026", True)  # looked up earlier
    ref = await g.move("03 Bank statements", "04 Bank statements")
    assert patched == [{"parentReference": {"id": "ROOT"}, "name": "04 Bank statements"}]
    assert ref.is_folder and ref.path == "04 Bank statements"
    assert not [p for p in g._folders if p.startswith("03 Bank statements")]
    assert g._folders["04 Bank statements"]["id"] == "OLD"


async def test_delta_follows_next_link_and_skips_folders_and_deletions():
    page2 = f"{GRAPH}/me/drive/special/approot/delta?token=p2"
    final = f"{GRAPH}/me/drive/special/approot/delta?token=done"
    parent = {"path": "/drive/special/approot:/00%20Inbox"}

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url == f"{GRAPH}/me/drive/special/approot/delta":
            return httpx.Response(200, json={
                "value": [
                    _item("ROOT", "Accnomos", True, root={}),
                    _item("IN", "00 Inbox", True),
                    _item("A", "a.jpg", parentReference=parent),
                ],
                "@odata.nextLink": page2,
            })
        if url == page2:
            return httpx.Response(200, json={
                "value": [_item("B", "b.jpg", deleted={"state": "deleted"}), _item("C", "c.pdf", parentReference=parent)],
                "@odata.deltaLink": final,
            })
        return httpx.Response(400)

    changed, cursor = await _provider(handler).changes(None)
    assert [(c.id, c.path) for c in changed] == [("A", "00 Inbox/a.jpg"), ("C", "00 Inbox/c.pdf")]
    assert cursor == final


async def test_work_delta_url_and_list_pagination():
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if req.url.raw_path.decode() == "/v1.0/me/drive/root:/Accnomos:/delta":
            return httpx.Response(200, json={"value": [], "@odata.deltaLink": "D"})
        if req.url.raw_path.decode() == "/v1.0/me/drive/root:/Accnomos/00%20Inbox:/children":
            return httpx.Response(200, json={"value": [_item("1", "a.jpg")], "@odata.nextLink": f"{url}?p=2"})
        if url.endswith("?p=2"):
            return httpx.Response(200, json={"value": [_item("2", "b.jpg")]})
        return httpx.Response(400)

    g = _provider(handler, "work")
    assert await g.changes(None) == ([], "D")
    assert [f.path for f in await g.list("00 Inbox")] == ["00 Inbox/a.jpg", "00 Inbox/b.jpg"]


async def test_429_retries_with_retry_after_then_gives_up():
    attempts = {"n": 0}
    slept: list[float] = []

    def handler(req: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, content=b"ok")

    assert await _provider(handler, slept=slept).read("a.txt") == b"ok"
    assert slept == [2.0, 2.0]

    with pytest.raises(GraphError) as exc:
        await _provider(lambda r: httpx.Response(503), slept=slept).read("a.txt")
    assert exc.value.status == 503
