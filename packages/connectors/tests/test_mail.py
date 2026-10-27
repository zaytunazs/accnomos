"""GraphMailProvider against httpx.MockTransport (no network), and the fake mailbox."""

from __future__ import annotations

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
        "id": f"AAMk{i}=", "receivedDateTime": f"2026-10-2{i % 10}T10:00:00Z", "subject": f"Invoice {i}",
        "hasAttachments": True, "webLink": f"https://outlook.live.com/owa/?ItemID={i}",
        "from": {"emailAddress": {"name": "Screwfix", "address": "Orders@Screwfix.com"}},
    }


async def test_list_messages_query_and_paging():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        assert req.method == "GET" and req.headers["Authorization"] == "Bearer tok"
        if "page=2" in str(req.url):
            return httpx.Response(200, json={"value": [_msg(3)]})
        return httpx.Response(200, json={"value": [_msg(1), _msg(2)], "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?page=2"})

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
        return httpx.Response(200, json={"value": [_msg(1), _msg(2)], "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?page=2"})

    assert len(await _provider(handler).list_messages(SINCE, max_results=2)) == 2


async def test_attachments_file_only_and_download():
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.raw_path.decode().split("?")[0]
        if path == "/v1.0/me/messages/AAMk1%3D/attachments":
            assert req.url.params["$select"] == "id,name,contentType,size,isInline"
            return httpx.Response(200, json={"value": [
                {"@odata.type": "#microsoft.graph.fileAttachment", "id": "A1", "name": "inv.pdf",
                 "contentType": "application/PDF", "size": 51200, "isInline": False},
                {"@odata.type": "#microsoft.graph.itemAttachment", "id": "A2", "name": "Fwd", "size": 9},
                {"@odata.type": "#microsoft.graph.fileAttachment", "id": "A3", "name": "image001.png",
                 "contentType": "image/png", "size": 3000, "isInline": True},
            ]})
        if path == "/v1.0/me/messages/AAMk1%3D/attachments/A1/$value":
            return httpx.Response(200, content=b"%PDF-1.7")
        return httpx.Response(404)

    g = _provider(handler)
    atts = await g.list_attachments("AAMk1=")
    assert [(a.id, a.content_type, a.is_inline) for a in atts] == [("A1", "application/pdf", False), ("A3", "image/png", True)]
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
