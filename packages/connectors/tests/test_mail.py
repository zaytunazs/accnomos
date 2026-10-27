"""GraphMailProvider against httpx.MockTransport (no network), and the fake mailbox."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from accnomos_connectors import FakeMailProvider, MailAttachment, MailMessage
from accnomos_connectors.msgraph import GraphError, GraphMailProvider

pytestmark = pytest.mark.asyncio

SINCE = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)


def _provider(handler) -> GraphMailProvider:
    async def sleep(_s: float) -> None:
        return None

    return GraphMailProvider("tok", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), sleep=sleep)


def _msg(i: int) -> dict:
    return {
        "id": f"AAMk{i}=",
        "receivedDateTime": f"2026-10-2{i % 10}T10:00:00Z",
        "subject": f"Invoice {i}",
        "hasAttachments": True,
        "webLink": f"https://outlook.live.com/owa/?ItemID={i}",
        "from": {"emailAddress": {"name": "Screwfix", "address": "Orders@Screwfix.com"}},
    }


async def test_list_messages_query_and_paging():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        assert req.method == "GET" and req.headers["Authorization"] == "Bearer tok"
        if "page=2" in str(req.url):
            return httpx.Response(200, json={"value": [_msg(3)]})
        return httpx.Response(
            200,
            json={
                "value": [_msg(1), _msg(2)],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?page=2",
            },
        )

    out = await _provider(handler).list_messages(SINCE, max_results=10)
    q = seen[0].url.params
    assert seen[0].url.path == "/v1.0/me/messages"
    assert q["$filter"] == "receivedDateTime ge 2026-10-13T09:30:00Z and hasAttachments eq true"
    assert q["$orderby"] == "receivedDateTime desc" and q["$top"] == "10"
    assert q["$select"] == "id,receivedDateTime,from,subject,hasAttachments,webLink"
    assert "$filter" not in seen[1].url.params  # the nextLink is followed as-is
    assert [m.id for m in out] == ["AAMk1=", "AAMk2=", "AAMk3="]
    assert out[0].from_address == "orders@screwfix.com" and out[0].from_name == "Screwfix"
    assert out[0].received_at == datetime(2026, 10, 21, 10, tzinfo=UTC)


async def test_list_messages_stops_at_max_results():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [_msg(1), _msg(2)],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?page=2",
            },
        )

    assert len(await _provider(handler).list_messages(SINCE, max_results=2)) == 2


async def test_attachments_file_only_and_download():
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.raw_path.decode().split("?")[0]
        if path == "/v1.0/me/messages/AAMk1%3D/attachments":
            assert req.url.params["$select"] == "id,name,contentType,size,isInline"
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "@odata.type": "#microsoft.graph.fileAttachment",
                            "id": "A1",
                            "name": "inv.pdf",
                            "contentType": "application/PDF",
                            "size": 51200,
                            "isInline": False,
                        },
                        {"@odata.type": "#microsoft.graph.itemAttachment", "id": "A2", "name": "Fwd", "size": 9},
                        {
                            "@odata.type": "#microsoft.graph.fileAttachment",
                            "id": "A3",
                            "name": "image001.png",
                            "contentType": "image/png",
                            "size": 3000,
                            "isInline": True,
                        },
                    ]
                },
            )
        if path == "/v1.0/me/messages/AAMk1%3D/attachments/A1/$value":
            return httpx.Response(200, content=b"%PDF-1.7")
        return httpx.Response(404)

    g = _provider(handler)
    atts = await g.list_attachments("AAMk1=")
    assert [(a.id, a.content_type, a.is_inline) for a in atts] == [
        ("A1", "application/pdf", False),
        ("A3", "image/png", True),
    ]
    assert await g.download_attachment("AAMk1=", "A1") == b"%PDF-1.7"


async def test_forbidden_raises_graph_error():
    g = _provider(lambda req: httpx.Response(403, json={"error": {"code": "ErrorAccessDenied"}}))
    with pytest.raises(GraphError) as exc:
        await g.list_messages(SINCE)
    assert exc.value.status == 403


async def test_fake_mailbox_filters_by_date_and_attachments():
    fake = FakeMailProvider()
    old = MailMessage(id="old", received_at=SINCE - timedelta(days=1))
    new = MailMessage(id="new", received_at=SINCE + timedelta(days=1))
    bare = MailMessage(id="bare", received_at=SINCE + timedelta(days=2))
    att = MailAttachment(id="a", name="r.pdf", content_type="application/pdf", size=20_000)
    fake.add(old, (att, b"x"))
    fake.add(new, (att, b"y"))
    fake.add(bare)
    assert [m.id for m in await fake.list_messages(SINCE)] == ["new"]
    assert await fake.download_attachment("new", "a") == b"y"


async def test_list_without_attachments_reads_the_inbox_folder_only():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        assert req.method == "GET"
        m = _msg(1) | {"hasAttachments": False, "bodyPreview": "Total £18.40 " + "x" * 400}
        return httpx.Response(200, json={"value": [m]})

    out = await _provider(handler).list_without_attachments(SINCE, max_results=20)
    url = seen[0].url
    assert url.path == "/v1.0/me/mailFolders/inbox/messages"
    assert url.params["$filter"] == "receivedDateTime ge 2026-10-13T09:30:00Z and hasAttachments eq false"
    assert url.params["$select"] == "id,receivedDateTime,from,subject,hasAttachments,bodyPreview,webLink"
    assert out[0].body_preview.startswith("Total £18.40") and len(out[0].body_preview) == 255


async def test_message_text_asks_graph_for_plain_text():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"body": {"contentType": "text", "content": "Total £18.40"}})

    assert await _provider(handler).message_text("AAMk1=") == "Total £18.40"
    req = seen[0]
    assert req.method == "GET" and req.url.raw_path.decode().split("?")[0] == "/v1.0/me/messages/AAMk1%3D"
    assert req.url.params["$select"] == "body"
    assert req.headers["Prefer"] == 'outlook.body-content-type="text"'


async def test_fake_mailbox_lists_bare_messages_and_their_bodies():
    fake = FakeMailProvider()
    att = MailAttachment(id="a", name="r.pdf", content_type="application/pdf", size=20_000)
    fake.add(MailMessage(id="with", received_at=SINCE + timedelta(days=1)), (att, b"y"))
    fake.add(MailMessage(id="bare", received_at=SINCE + timedelta(days=2)), body="Total £5.00")
    assert [m.id for m in await fake.list_without_attachments(SINCE)] == ["bare"]
    assert await fake.message_text("bare") == "Total £5.00"
    with pytest.raises(FileNotFoundError):
        await fake.message_text("gone")


# ---------------------------------------------------------------------- #
# Inbox triage: list_recent and create_reply_draft
# ---------------------------------------------------------------------- #


async def test_list_recent_reads_the_inbox_folder_with_the_triage_fields_only():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        assert req.method == "GET"
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "m1",
                        "conversationId": "c1",
                        "receivedDateTime": "2026-10-26T08:00:00Z",
                        "subject": "Quote",
                        "isRead": False,
                        "bodyPreview": "x" * 400,
                        "webLink": "https://outlook.live.com/owa/?ItemID=m1",
                        "from": {"emailAddress": {"name": "Jo", "address": "Jo@Client.co.uk"}},
                    }
                ]
            },
        )

    async with _provider(handler) as p:
        out = await p.list_recent(SINCE, 30)
    url = seen[0].url
    assert url.path == "/v1.0/me/mailFolders/inbox/messages"
    assert url.params["$select"] == "id,conversationId,subject,from,receivedDateTime,bodyPreview,isRead,webLink"
    assert url.params["$filter"] == "receivedDateTime ge 2026-10-13T09:30:00Z"  # no hasAttachments filter
    assert url.params["$top"] == "30"
    m = out[0]
    assert (m.conversation_id, m.from_address, m.is_read, len(m.body_preview)) == ("c1", "jo@client.co.uk", False, 255)


async def test_create_reply_draft_is_create_reply_then_patch_and_never_send():
    seen: list[tuple[str, str, bytes]] = []
    quoted = '<html><body dir="ltr"><hr>On Monday Jo wrote…</body></html>'

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.raw_path.decode(), req.content))
        if req.url.path.endswith("/createReply"):
            return httpx.Response(
                201,
                json={
                    "id": "draft/1",
                    "webLink": "https://outlook.live.com/owa/?ItemID=draft1&exvsurl=1",
                    "body": {"contentType": "html", "content": quoted},
                },
            )
        return httpx.Response(200, json={"id": "draft/1", "webLink": "https://outlook.live.com/owa/?ItemID=draft1"})

    async with _provider(handler) as p:
        draft = await p.create_reply_draft("AAMk/1=", "Hi Jo,\nThursday works <fine>.")
    assert [(m, path) for m, path, _ in seen] == [
        ("POST", "/v1.0/me/messages/AAMk%2F1%3D/createReply"),
        ("PATCH", "/v1.0/me/messages/draft%2F1"),
    ]
    patched = json.loads(seen[1][2])["body"]
    assert patched["contentType"] == "html"
    assert patched["content"] == (
        '<html><body dir="ltr"><div>Hi Jo,<br>Thursday works'
        " &lt;fine&gt;.</div><br><hr>On Monday Jo wrote…</body></html>"
    )
    assert draft.id == "draft/1" and draft.web_link == "https://outlook.live.com/owa/?ItemID=draft1"
    assert not any("send" in path.lower() for _, path, _ in seen)


async def test_create_reply_draft_plain_text_body():
    seen: list[bytes] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.content)
        if req.url.path.endswith("/createReply"):
            return httpx.Response(201, json={"id": "d", "body": {"contentType": "text", "content": "> quoted"}})
        return httpx.Response(200, json={"id": "d"})

    async with _provider(handler) as p:
        draft = await p.create_reply_draft("m", "Thanks")
    assert json.loads(seen[1])["body"] == {"contentType": "text", "content": "Thanks\n\n> quoted"}
    assert draft.web_link is None


async def test_fake_mailbox_lists_recent_and_records_drafts():
    fake = FakeMailProvider()
    fake.add(MailMessage(id="old", received_at=SINCE - timedelta(days=1)))
    fake.add(MailMessage(id="new", received_at=SINCE + timedelta(hours=1), conversation_id="c"))
    assert [m.id for m in await fake.list_recent(SINCE)] == ["new"]  # attachments not required
    draft = await fake.create_reply_draft("new", "Hello")
    assert fake.drafts == [{"id": draft.id, "reply_to": "new", "body": "Hello"}]
    with pytest.raises(FileNotFoundError):
        await fake.create_reply_draft("gone", "Hello")
