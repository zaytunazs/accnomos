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


def _mail_with(n: int) -> OutgoingMail:
    att = OutgoingAttachment(name="x.pdf", content_type="application/pdf", data=b"x" * n)
    return MAIL.model_copy(update={"attachments": [att]})


async def test_send_checks_the_encoded_request_not_the_raw_bytes():
    """Graph's 4 MB applies to the base64 JSON body: 3.1 MB raw (the old 3 MiB cap let it through) is about
    4.2 MB once encoded and is refused; 2.9 MB raw (about 3.9 MB encoded) still goes."""
    calls: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        calls.append(r)
        return httpx.Response(202)

    sender = _sender(handler)
    await sender.send(_mail_with(2_900_000))
    assert len(calls) == 1 and len(calls[0].content) <= GraphMailSender.MAX_REQUEST_BYTES
    with pytest.raises(ValueError, match="too big"):
        await sender.send(_mail_with(3_100_000))
    assert len(calls) == 1  # nothing was sent for the second


async def test_send_boundary_is_exact_on_the_request_size():
    seen: list[int] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(len(r.content))
        return httpx.Response(202)

    sender = _sender(handler)
    await sender.send(_mail_with(30_000))  # 30,000 is a multiple of 3: base64 grows by exactly 4 per 3 bytes
    sender.MAX_REQUEST_BYTES = seen[0]  # the limit is now exactly this request's size
    await sender.send(_mail_with(30_000))  # at the limit: sent
    assert seen == [seen[0], seen[0]]
    with pytest.raises(ValueError):
        await sender.send(_mail_with(30_003))  # one more base64 quad: one byte-group over
    assert len(seen) == 2


async def test_fake_sender_records_and_can_fail():
    fake = FakeMailSender()
    await fake.send(MAIL)
    assert fake.sent == [MAIL]
    fake.fail = RuntimeError("offline")
    with pytest.raises(RuntimeError):
        await fake.send(MAIL)
    assert len(fake.sent) == 1
