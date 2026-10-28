"""Sharing the books folder (accountant access) against httpx.MockTransport, with the response shapes from the
Microsoft Learn pages for driveItem: invite, permission: delete and drive: sharedWithMe (checked 28 Oct 2026)."""

from __future__ import annotations

import json

import httpx
import pytest

from accnomos_connectors.base import Identity, SharedRoot
from accnomos_connectors.fake import FakeSharingProvider, FakeSharingWorld, FakeStorageProvider
from accnomos_connectors.msgraph import GraphError, GraphSharingProvider, GraphStorageProvider

pytestmark = pytest.mark.asyncio

ROOT = SharedRoot(drive_id="1991210caf", item_id="1991210caf!192")


def _sharing(handler) -> GraphSharingProvider:
    return GraphSharingProvider("tok", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


# Example 1 of https://learn.microsoft.com/graph/api/driveitem-invite (password/expiry dropped: we never send them).
INVITE_RESPONSE = {
    "value": [
        {
            "grantedToV2": {"user": {"id": "42F177F1", "displayName": "Robin Danielsen"}},
            "id": "CCFC7CA3-7A19-4D57-8CEF-149DB9DDFA62",
            "invitation": {"email": "robin@contoso.com", "signInRequired": True},
            "roles": ["write"],
        }
    ]
}


async def test_invite_posts_the_documented_body_to_the_drive_item():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=INVITE_RESPONSE)

    perm = await _sharing(handler).invite(ROOT, "robin@contoso.com", "write", "Sam's books" + "x" * 3000)
    req = seen[0]
    assert req.method == "POST"
    assert req.url.raw_path.decode() == "/v1.0/drives/1991210caf/items/1991210caf!192/invite"
    body = json.loads(req.content)
    assert body["recipients"] == [{"email": "robin@contoso.com"}]
    assert body["roles"] == ["write"]
    assert body["requireSignIn"] is True and body["sendInvitation"] is True
    assert len(body["message"]) == 2000  # the documented maximum
    assert perm.id == "CCFC7CA3-7A19-4D57-8CEF-149DB9DDFA62" and perm.roles == ["write"]
    assert perm.email == "robin@contoso.com"


async def test_invite_with_a_failed_recipient_in_a_207_raises():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            207, json={"value": [{"error": {"code": "notAllowed", "message": "Account verification"}}]}
        )

    with pytest.raises(GraphError):
        await _sharing(handler).invite(ROOT, "helga@contoso.com", "read", "")


async def test_invite_refusal_maps_to_graph_error_and_bad_role_is_refused():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"code": "accessDenied", "message": "Access denied"}})

    with pytest.raises(GraphError) as exc:
        await _sharing(handler).invite(ROOT, "a@b.example", "read", "")
    assert exc.value.status == 403
    with pytest.raises(ValueError):
        await _sharing(handler).invite(ROOT, "a@b.example", "owner", "")  # type: ignore[arg-type]


async def test_revoke_deletes_the_permission_and_a_missing_one_is_not_an_error():
    seen: list[tuple[str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.raw_path.decode()))
        return httpx.Response(204 if "perm-1" in req.url.path else 404)

    s = _sharing(handler)
    assert await s.revoke(ROOT, "perm-1") is True
    assert await s.revoke(ROOT, "perm-2") is False
    assert seen[0] == ("DELETE", "/v1.0/drives/1991210caf/items/1991210caf!192/permissions/perm-1")


async def test_shared_with_me_keeps_folders_with_an_address_and_follows_next_link():
    page1 = {
        "value": [
            {  # a file, as in the documented example: skipped
                "id": "1312abc",
                "remoteItem": {
                    "id": "1991210caf!192",
                    "name": "March Proposal.docx",
                    "file": {},
                    "parentReference": {"driveId": "1991210caf", "id": "1991210caf!104"},
                },
            },
            {
                "id": "1312def",
                "remoteItem": {
                    "id": "987def!654",
                    "name": "Accnomos",
                    "folder": {"childCount": 9},
                    "parentReference": {"driveId": "987def", "id": "987def!321"},
                    "shared": {
                        "owner": {"user": {"displayName": "Sam Builder", "email": "sam@sambuilds.example"}},
                        "sharedDateTime": "2026-10-20T09:00:00Z",
                    },
                },
            },
            {"id": "x", "remoteItem": {"id": "../evil", "folder": {}, "parentReference": {"driveId": "d"}}},
        ],
        "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/drive/sharedWithMe?$skiptoken=2",
    }
    page2 = {
        "value": [
            {
                "id": "y",
                "remoteItem": {"id": "b!q!1", "name": "Books", "folder": {}, "parentReference": {"driveId": "b!q"}},
            }
        ]
    }
    urls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        urls.append(str(req.url))
        return httpx.Response(200, json=page2 if "skiptoken" in str(req.url) else page1)

    folders = await _sharing(handler).shared_with_me()
    assert "allowexternal=true" in urls[0]
    assert [(f.drive_id, f.item_id, f.name) for f in folders] == [
        ("987def", "987def!654", "Accnomos"),
        ("b!q", "b!q!1", "Books"),
    ]
    assert folders[0].owner == "sam@sambuilds.example" and folders[0].shared_at is not None


async def test_shared_with_me_never_sends_the_token_to_another_host():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": [], "@odata.nextLink": "https://evil.example/next"})

    with pytest.raises(ValueError):
        await _sharing(handler).shared_with_me()


async def test_books_root_personal_reads_the_app_folder_and_its_drive():
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.raw_path.decode()
        if path == "/v1.0/me/drive/special/approot":
            return httpx.Response(200, json={"id": "ABC!7", "name": "Accnomos", "folder": {}, "parentReference": {}})
        if path.startswith("/v1.0/me/drive?"):
            return httpx.Response(200, json={"id": "ABC"})
        return httpx.Response(404)

    assert await _sharing(handler).books_root("personal") == SharedRoot(drive_id="ABC", item_id="ABC!7")


async def test_books_root_work_never_creates_the_folder():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        return httpx.Response(404)

    with pytest.raises(FileNotFoundError):
        await _sharing(handler).books_root("work")


async def test_whoami_prefers_mail_then_upn():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"mail": None, "userPrincipalName": "Ana@Firm.example", "displayName": "Ana"})

    assert await _sharing(handler).whoami() == Identity(email="ana@firm.example", name="Ana")


async def test_unsafe_ids_are_refused_before_any_call():
    def handler(req: httpx.Request) -> httpx.Response:  # pragma: no cover - never reached
        raise AssertionError("no call expected")

    with pytest.raises(ValueError):
        await _sharing(handler).invite(SharedRoot(drive_id="d/../me", item_id="1"), "a@b.example", "read", "")
    with pytest.raises(ValueError):
        GraphStorageProvider("tok", shared=SharedRoot(drive_id="d", item_id="1?x=1"))


async def test_storage_over_a_shared_folder_is_path_addressed_from_its_item_id():
    seen: list[tuple[str, str]] = []
    root = {"id": "987def!654", "name": "Accnomos", "folder": {}}

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.raw_path.decode()
        seen.append((req.method, path))
        if path == "/v1.0/drives/987def/items/987def!654":
            return httpx.Response(200, json=root)
        if path.endswith(":/children"):
            return httpx.Response(200, json={"value": [{"id": "f1", "name": "a.json", "size": 2}]})
        if path.endswith(":/content") and req.method == "GET":
            return httpx.Response(200, content=b"{}")
        if req.method == "POST" and path.endswith("/children"):
            return httpx.Response(201, json={"id": "new", "name": json.loads(req.content)["name"], "folder": {}})
        if req.method == "PUT":
            return httpx.Response(201, json={"id": "w", "name": "q.json", "size": 2})
        return httpx.Response(404)

    g = GraphStorageProvider(
        "tok",
        "work",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        shared=SharedRoot(drive_id="987def", item_id="987def!654"),
    )
    assert (await g.ensure_root()).name == "Accnomos"
    assert [f.name for f in await g.list("_System/queries")] == ["a.json"]
    assert await g.read("_System/queries/a.json") == b"{}"
    await g.write("_System/queries/q.json", b"{}")
    paths = [p for _, p in seen]
    assert "/v1.0/drives/987def/items/987def!654:/_System/queries:/children" in paths
    assert "/v1.0/drives/987def/items/987def!654:/_System/queries/a.json:/content" in paths
    # Folders are created under the shared drive, never under /me/drive.
    assert all("/me/" not in p for p in paths)
    assert any(m == "POST" and p.startswith("/v1.0/drives/987def/items/") for m, p in seen)


async def test_fake_world_shares_revokes_and_lists():
    world = FakeSharingWorld()
    client_books = FakeStorageProvider()
    await client_books.ensure_folder("_System")
    root = world.add_folder("sam@sambuilds.example", "D1", "D1!1", "Accnomos", client_books)
    sam = FakeSharingProvider(world, Identity(email="sam@sambuilds.example"), own=root)
    ana = FakeSharingProvider(world, Identity(email="ana@firm.example"))

    assert await ana.shared_with_me() == []
    perm = await sam.invite(root, "Ana@Firm.example", "read", "")
    listed = await ana.shared_with_me()
    assert [(f.drive_id, f.item_id) for f in listed] == [("D1", "D1!1")]
    assert "_System" in await ana.child_names(root)
    assert world.role_of(root, "ana@firm.example") == "read"
    with pytest.raises(PermissionError):
        await ana.revoke(root, perm.id)  # only the owner unshares
    assert await sam.revoke(root, perm.id) is True
    assert await ana.shared_with_me() == []
    with pytest.raises(FileNotFoundError):
        await ana.folder(root)


async def test_invite_and_revoke_on_a_subfolder_are_path_addressed():
    seen: list[tuple[str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.raw_path.decode()))
        return httpx.Response(204) if req.method == "DELETE" else httpx.Response(200, json=INVITE_RESPONSE)

    s = _sharing(handler)
    await s.invite(ROOT, "robin@contoso.com", "write", "", path="_System/queries")
    await s.revoke(ROOT, "p1", path="_System/queries")
    assert seen == [
        ("POST", "/v1.0/drives/1991210caf/items/1991210caf!192:/_System/queries:/invite"),
        ("DELETE", "/v1.0/drives/1991210caf/items/1991210caf!192:/_System/queries:/permissions/p1"),
    ]
    with pytest.raises(ValueError):
        await s.invite(ROOT, "a@b.example", "write", "", path="../other")


async def test_fake_world_inherits_permissions_downwards_only():
    world = FakeSharingWorld()
    root = world.add_folder("sam@x.example", "D", "D!1", "Accnomos", FakeStorageProvider())
    sam = FakeSharingProvider(world, Identity(email="sam@x.example"), own=root)
    await sam.invite(root, "ana@f.example", "read", "")
    await sam.invite(root, "ana@f.example", "write", "", path="_System/queries")
    assert world.role_of(root, "ana@f.example") == "read"
    assert world.role_of(root, "ana@f.example", "_System/queries/q1.json") == "write"
    assert world.role_of(root, "ana@f.example", "_System/queriesX") == "read"
