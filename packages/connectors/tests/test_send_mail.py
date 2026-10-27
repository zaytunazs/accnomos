"""GraphMailSender against httpx.MockTransport (no network), and the fake sender."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from accnomos_connectors import FakeMailSender, OutgoingAttachment, OutgoingMail
from accnomos_connectors.msgraph import GraphError, GraphMailSender

pytestmark = pytest.mark.asyncio

PDF = b"%PDF-1.4 invoice"
MAIL = OutgoingMail(
    to="accounts@customer.co.uk",
    subject="Invoice INV-0001",
    body_text="Please find attached.",
    attachments=[OutgoingAttachment(name="INV-0001.pdf", content_type="application/pdf", data=PDF)],
)


def _sender(handler) -> GraphMailSender:
    async def sleep(_s: float) -> None:
        return None

    return GraphMailSender("tok", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), sleep=sleep)


async def test_send_posts_one_message_with_the_pdf():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(202)

    await _sender(handler).send(MAIL)
    assert len(seen) == 1
    req = seen[0]
    assert req.method == "POST" and req.url.path == "/v1.0/me/sendMail"
    assert req.headers["Authorization"] == "Bearer tok"
    body = json.loads(req.content)
    assert body["saveToSentItems"] is True
    msg = body["message"]
    assert msg["toRecipients"] == [{"emailAddress": {"address": "accounts@customer.co.uk"}}]
    assert msg["body"] == {"contentType": "Text", "content": "Please find attached."}
    (att,) = msg["attachments"]
    assert att["@odata.type"] == "#microsoft.graph.fileAttachment" and att["name"] == "INV-0001.pdf"
    assert base64.b64decode(att["contentBytes"]) == PDF


async def test_send_without_consent_raises_graph_error():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"code": "ErrorAccessDenied"}})

    with pytest.raises(GraphError) as err:
        await _sender(handler).send(MAIL)
    assert err.value.status == 403


async def test_send_refuses_attachments_over_3mb():
    calls: list[httpx.Request] = []
    big = MAIL.model_copy(
        update={
            "attachments": [
                OutgoingAttachment(name="x.pdf", content_type="application/pdf", data=b"x" * (3 * 1024 * 1024 + 1))
            ]
        }
    )
    with pytest.raises(ValueError):
        await _sender(lambda r: calls.append(r) or httpx.Response(202)).send(big)
    assert calls == []


async def test_fake_sender_records_and_can_fail():
    fake = FakeMailSender()
    await fake.send(MAIL)
    assert fake.sent == [MAIL]
    fake.fail = RuntimeError("offline")
    with pytest.raises(RuntimeError):
        await fake.send(MAIL)
    assert len(fake.sent) == 1
