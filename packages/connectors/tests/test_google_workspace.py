"""Gmail, Google Calendar and People providers against httpx.MockTransport (no network)."""

from __future__ import annotations

import base64
import email
import json
from datetime import UTC, date, datetime
from email import policy
from zoneinfo import ZoneInfo

import httpx
import pytest

from accnomos_connectors import google_workspace as gw
from accnomos_connectors.base import ConflictError, NewCalendarEvent, OutgoingAttachment, OutgoingMail
from accnomos_connectors.google_workspace import (
    GoogleCalendarProvider,
    GoogleContactsProvider,
    GoogleError,
    GoogleMailProvider,
    GoogleMailSender,
)

pytestmark = pytest.mark.asyncio

SINCE = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)
LONDON = ZoneInfo("Europe/London")
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _nosleep(_s: float) -> None:
    return None


def _make(cls, handler):
    return cls("tok", client=_client(handler), sleep=_nosleep)


def _b64(data: bytes | str) -> str:
    raw = data.encode() if isinstance(data, str) else data
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _meta(i: int, labels=("INBOX", "UNREAD")) -> dict:
    return {
        "id": f"m{i}",
        "threadId": f"t{i}",
        "labelIds": list(labels),
        "snippet": "Your invoice &amp; receipt",
        "internalDate": str(int(datetime(2026, 10, 20, 10, i, tzinfo=UTC).timestamp() * 1000)),
        "payload": {
            "headers": [
                {"name": "From", "value": '"Screwfix" <Orders@Screwfix.com>'},
                {"name": "Subject", "value": f"=?UTF-8?Q?Invoice_=C2=A3{i}?="},
            ]
        },
    }


def _full(html_only: bool = False) -> dict:
    plain = {"partId": "0", "mimeType": "text/plain", "filename": "", "body": {"data": _b64("Hello plain")}}
    html = {
        "partId": "1",
        "mimeType": "text/html",
        "filename": "",
        "body": {"data": _b64("<style>p{}</style><p>Hello&nbsp;<b>html</b></p><div>Line two</div>")},
    }
    pdf = {
        "partId": "2",
        "mimeType": "application/pdf",
        "filename": "inv.pdf",
        "headers": [{"name": "Content-Disposition", "value": 'attachment; filename="inv.pdf"'}],
        "body": {"attachmentId": "ATT1", "size": 1234},
    }
    logo = {
        "partId": "3",
        "mimeType": "image/png",
        "filename": "logo.png",
        "headers": [{"name": "Content-ID", "value": "<logo>"}],
        "body": {"attachmentId": "ATT2", "size": 10},
    }
    tiny = {"partId": "4", "mimeType": "text/csv", "filename": "a.csv", "body": {"data": _b64("a,b"), "size": 3}}
    parts = ([html] if html_only else [plain, html]) + [pdf, logo, tiny]
    return {
        **_meta(1),
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "Jo <jo@example.com>"},
                {"name": "Reply-To", "value": "Billing <billing@example.com>"},
                {"name": "Subject", "value": "Invoice 1"},
                {"name": "Message-ID", "value": "<orig@example.com>"},
                {"name": "References", "value": "<older@example.com>"},
            ],
            "parts": parts,
        },
    }


async def test_list_messages_query_labels_and_mapping():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        assert req.headers["authorization"] == "Bearer tok"
        if req.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "m1"}, {"id": "m2"}]})
        return httpx.Response(200, json=_meta(int(req.url.path[-1])))

    msgs = await _make(GoogleMailProvider, handler).list_messages(SINCE, 10)
    lst = seen[0].url.params
    assert lst["q"] == f"after:{int(SINCE.timestamp())} has:attachment"
    assert "labelIds" not in lst and lst["maxResults"] == "10"
    got = seen[1].url.params
    assert got["format"] == "metadata" and got.get_list("metadataHeaders") == ["From", "Subject"]
    m = msgs[0]
    assert (m.id, m.from_address, m.from_name, m.subject) == ("m1", "orders@screwfix.com", "Screwfix", "Invoice £1")
    assert m.has_attachments and m.conversation_id == "" and m.body_preview == ""
    assert m.received_at == datetime(2026, 10, 20, 10, 1, tzinfo=UTC)
    assert m.web_link == "https://mail.google.com/mail/u/0/#all/m1"


async def test_list_messages_folders_inbox_archive_and_user_label():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path.endswith("/labels"):
            return httpx.Response(
                200,
                json={
                    "labels": [
                        {"id": "Label_7", "name": "Receipts", "type": "user"},
                        {"id": "INBOX", "name": "INBOX", "type": "system"},
                    ]
                },
            )
        return httpx.Response(200, json={})

    p = _make(GoogleMailProvider, handler)
    await p.list_messages(SINCE, folder="inbox")
    await p.list_messages(SINCE, folder="archive")
    await p.list_messages(SINCE, folder="receipts")
    await p.list_messages(SINCE, folder="Receipts")  # label id cached: one labels call
    lists = [r for r in seen if r.url.path.endswith("/messages")]
    assert lists[0].url.params["labelIds"] == "INBOX"
    assert "-in:inbox" in lists[1].url.params["q"] and "-in:sent" in lists[1].url.params["q"]
    assert lists[2].url.params["labelIds"] == "Label_7"
    assert sum(r.url.path.endswith("/labels") for r in seen) == 2  # "receipts" and "Receipts" are cached separately
    with pytest.raises(FileNotFoundError):
        await p.list_messages(SINCE, folder="Nope")


async def test_list_messages_pages_and_skips_vanished_messages():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/messages"):
            if req.url.params.get("pageToken") == "P2":
                return httpx.Response(200, json={"messages": [{"id": "m3"}]})
            return httpx.Response(200, json={"messages": [{"id": "m1"}, {"id": "m2"}], "nextPageToken": "P2"})
        if req.url.path.endswith("m2"):
            return httpx.Response(404, json={"error": {"code": 404}})
        return httpx.Response(200, json=_meta(int(req.url.path[-1])))

    msgs = await _make(GoogleMailProvider, handler).list_messages(SINCE, 100)
    assert [m.id for m in msgs] == ["m1", "m3"]


async def test_list_without_attachments_defaults_to_inbox_with_preview():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "m4"}]})
        return httpx.Response(200, json=_meta(4))

    (m,) = await _make(GoogleMailProvider, handler).list_without_attachments(SINCE)
    assert "-has:attachment" in seen[0].url.params["q"] and seen[0].url.params["labelIds"] == "INBOX"
    assert m.has_attachments is False and m.body_preview == "Your invoice & receipt"


async def test_list_recent_fills_triage_fields():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "m1"}, {"id": "m2"}]})
        n = int(req.url.path[-1])
        return httpx.Response(200, json=_meta(n, ("INBOX",) if n == 2 else ("INBOX", "UNREAD")))

    msgs = await _make(GoogleMailProvider, handler).list_recent(SINCE)
    assert seen[0].url.params["labelIds"] == "INBOX"
    assert [(m.conversation_id, m.is_read) for m in msgs] == [("t1", False), ("t2", True)]
    assert msgs[0].body_preview == "Your invoice & receipt"


async def test_message_text_prefers_plain_then_strips_html():
    def handler(html_only):
        def h(req: httpx.Request) -> httpx.Response:
            assert req.url.params["format"] == "full"
            return httpx.Response(200, json=_full(html_only))

        return h

    assert await _make(GoogleMailProvider, handler(False)).message_text("m1") == "Hello plain"
    assert await _make(GoogleMailProvider, handler(True)).message_text("m1") == "Hello html\nLine two"


async def test_list_and_download_attachments():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/attachments/ATT1"):
            return httpx.Response(200, json={"size": 5, "data": _b64(b"%PDF-")})
        return httpx.Response(200, json=_full())

    p = _make(GoogleMailProvider, handler)
    atts = await p.list_attachments("m1")
    assert [(a.id, a.name, a.content_type, a.size, a.is_inline) for a in atts] == [
        ("ATT1", "inv.pdf", "application/pdf", 1234, False),
        ("ATT2", "logo.png", "image/png", 10, True),
        ("part:4", "a.csv", "text/csv", 3, False),
    ]
    assert await p.download_attachment("m1", "ATT1") == b"%PDF-"
    assert await p.download_attachment("m1", "part:4") == b"a,b"
    with pytest.raises(FileNotFoundError):
        await p.download_attachment("m1", "part:99")


async def test_create_reply_draft_threads_and_never_sends():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.method == "GET":
            return httpx.Response(200, json=_full())
        return httpx.Response(200, json={"id": "r99", "message": {"id": "gm99", "threadId": "t1"}})

    d = await _make(GoogleMailProvider, handler).create_reply_draft("m1", "Thanks, paid.")
    posts = [r for r in seen if r.method == "POST"]
    assert len(posts) == 1 and posts[0].url.path.endswith("/drafts") and not any("send" in r.url.path for r in seen)
    body = json.loads(posts[0].content)
    assert body["message"]["threadId"] == "t1"
    mime = email.message_from_bytes(base64.urlsafe_b64decode(body["message"]["raw"]), policy=policy.default)
    assert mime["To"] == "Billing <billing@example.com>" and mime["Subject"] == "Re: Invoice 1"
    assert mime["In-Reply-To"] == "<orig@example.com>"
    assert mime["References"] == "<older@example.com> <orig@example.com>"
    text = mime.get_content().replace("\r\n", "\n")
    assert text.startswith("Thanks, paid.\n\nOn ") and "> Hello plain" in text
    assert (d.id, d.web_link) == ("r99", "https://mail.google.com/mail/u/0/#drafts?compose=gm99")


async def test_mail_errors_and_retry():
    calls = {"n": 0}

    def flaky(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={})

    assert await _make(GoogleMailProvider, flaky).list_messages(SINCE) == []
    assert calls["n"] == 3

    quota = httpx.Response(403, json={"error": {"errors": [{"reason": "rateLimitExceeded"}]}})
    n = {"n": 0}

    def rate(req: httpx.Request) -> httpx.Response:
        n["n"] += 1
        return quota if n["n"] == 1 else httpx.Response(200, json={})

    await _make(GoogleMailProvider, rate).list_messages(SINCE)
    assert n["n"] == 2

    with pytest.raises(GoogleError) as ei:
        await _make(GoogleMailProvider, lambda r: httpx.Response(401, text="bad token")).list_messages(SINCE)
    assert ei.value.status == 401
    with pytest.raises(FileNotFoundError):
        await _make(GoogleMailProvider, lambda r: httpx.Response(404)).message_text("x")
    with pytest.raises(ConflictError):
        await _make(GoogleMailProvider, lambda r: httpx.Response(412)).message_text("x")


async def test_token_is_never_sent_outside_google_and_set_token():
    p = _make(GoogleMailProvider, lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        await p._request("GET", "https://evil.example.com/x")
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers["authorization"])
        return httpx.Response(200, json={})

    p = _make(GoogleMailProvider, handler)
    p.set_token(" fresh ")
    await p.list_messages(SINCE)
    assert seen == ["Bearer fresh"]
    with pytest.raises(ValueError):
        p.set_token("  ")


async def test_module_transport_hook(monkeypatch):
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(200, json={})

    monkeypatch.setattr(gw, "TRANSPORT", httpx.MockTransport(handler))
    async with GoogleMailProvider("tok") as p:
        await p.list_messages(SINCE)
    assert seen and seen[0].startswith(GMAIL)


# ---------------------------------------------------------------------- #
# Sender
# ---------------------------------------------------------------------- #


async def test_send_posts_raw_mime_with_attachment():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"id": "sent1"})

    mail = OutgoingMail(
        to="client@example.com",
        subject="Invoice\r\nBcc: x@evil.test",
        body_text="Please find attached.",
        attachments=[OutgoingAttachment(name="inv.pdf", content_type="application/pdf", data=b"%PDF-1.4 hi")],
    )
    await _make(GoogleMailSender, handler).send(mail)
    (req,) = seen
    assert req.method == "POST" and req.url.path == "/gmail/v1/users/me/messages/send"
    mime = email.message_from_bytes(base64.urlsafe_b64decode(json.loads(req.content)["raw"]), policy=policy.default)
    assert mime["To"] == "client@example.com" and mime["Bcc"] is None
    assert mime["Subject"] == "Invoice Bcc: x@evil.test"
    body, att = list(mime.iter_parts())
    assert body.get_content().strip() == "Please find attached."
    assert (att.get_filename(), att.get_content_type(), att.get_content()) == (
        "inv.pdf",
        "application/pdf",
        b"%PDF-1.4 hi",
    )


async def test_send_refuses_oversize_before_any_request():
    def handler(req: httpx.Request) -> httpx.Response:
        raise AssertionError("must not be called")

    big = OutgoingAttachment(name="big.bin", content_type="application/octet-stream", data=b"x" * 3_100_000)
    with pytest.raises(ValueError, match="too big"):
        await _make(GoogleMailSender, handler).send(
            OutgoingMail(to="a@b.co", subject="s", body_text="b", attachments=[big])
        )


# ---------------------------------------------------------------------- #
# Contacts
# ---------------------------------------------------------------------- #


async def test_list_contacts_maps_and_pages():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        assert req.url.host == "people.googleapis.com" and req.method == "GET"
        if req.url.params.get("pageToken") == "P2":
            return httpx.Response(200, json={"connections": [{"resourceName": "people/c3"}]})
        return httpx.Response(
            200,
            json={
                "connections": [
                    {
                        "resourceName": "people/c1",
                        "names": [{"displayName": " Ann Plumber "}],
                        "organizations": [{"name": "Ann's Plumbing"}],
                        "emailAddresses": [{"value": "ann@x.co"}, {"value": " "}],
                        "phoneNumbers": [
                            {"value": "020 7946 0000", "type": "work"},
                            {"value": "07700 900000", "type": "mobile"},
                            {"value": "07700 900001", "type": "workMobile"},
                        ],
                    },
                    {"resourceName": "people/c2", "emailAddresses": [{"value": "b@y.co"}]},
                ],
                "nextPageToken": "P2",
            },
        )

    cs = await _make(GoogleContactsProvider, handler).list_contacts()
    p = seen[0].url.params
    assert p["personFields"] == "names,emailAddresses,phoneNumbers,organizations" and p["pageSize"] == "1000"
    assert [c.id for c in cs] == ["people/c1", "people/c2", "people/c3"]
    a = cs[0]
    assert (a.display_name, a.company_name, a.emails) == ("Ann Plumber", "Ann's Plumbing", ["ann@x.co"])
    assert a.business_phones == ["020 7946 0000", "07700 900001"]
    assert cs[1].display_name == "" and cs[1].emails == ["b@y.co"]


async def test_list_contacts_respects_max_results():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["pageSize"] == "2"
        return httpx.Response(
            200,
            json={"connections": [{"resourceName": f"people/c{i}"} for i in range(2)], "nextPageToken": "more"},
        )

    cs = await _make(GoogleContactsProvider, handler).list_contacts(2)
    assert len(cs) == 2


# ---------------------------------------------------------------------- #
# Calendar
# ---------------------------------------------------------------------- #

EV = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def _ev(**kw) -> dict:
    return {
        "id": "e1",
        "summary": "Call HMRC",
        "start": {"dateTime": "2026-10-20T10:00:00+01:00"},
        "end": {"dateTime": "2026-10-20T10:30:00+01:00"},
        "location": "Phone",
        "description": "Quarter-end VAT",
        "htmlLink": "https://calendar.google.com/event?eid=abc",
        **kw,
    }


async def test_list_events_asks_for_the_london_day_in_utc_and_maps_fields():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.params.get("pageToken") == "P2":
            return httpx.Response(
                200,
                json={
                    "items": [
                        _ev(
                            id="e0",
                            start={"dateTime": "2026-10-20T08:00:00Z"},
                            end={"dateTime": "2026-10-20T09:00:00Z"},
                        )
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    _ev(),
                    _ev(id="gone", status="cancelled"),
                    {
                        "id": "e2",
                        "summary": "Deadline",
                        "start": {"date": "2026-10-20"},
                        "end": {"date": "2026-10-21"},
                        "transparency": "transparent",
                        "extendedProperties": {"private": {"accnomosKey": "vat-q3"}},
                    },
                    _ev(id="e3", status="tentative"),
                ],
                "nextPageToken": "P2",
            },
        )

    events = await _make(GoogleCalendarProvider, handler).list_events(date(2026, 10, 20))
    p = seen[0].url.path, seen[0].url.params
    assert p[0] == "/calendar/v3/calendars/primary/events"
    assert p[1]["timeMin"] == "2026-10-19T23:00:00Z" and p[1]["timeMax"] == "2026-10-20T23:00:00Z"
    assert p[1]["singleEvents"] == "true" and p[1]["orderBy"] == "startTime"
    assert [e.id for e in events] == ["e2", "e0", "e1", "e3"] or [e.id for e in events] == ["e0", "e2", "e1", "e3"]
    by = {e.id: e for e in events}
    assert "gone" not in by
    e1 = by["e1"]
    assert e1.start == datetime(2026, 10, 20, 9, 0, tzinfo=UTC) and e1.end == datetime(2026, 10, 20, 9, 30, tzinfo=UTC)
    assert (e1.subject, e1.location, e1.body_preview, e1.show_as, e1.is_all_day, e1.key) == (
        "Call HMRC",
        "Phone",
        "Quarter-end VAT",
        "busy",
        False,
        None,
    )
    assert e1.web_link.endswith("eid=abc")
    assert by["e2"].is_all_day and by["e2"].show_as == "free" and by["e2"].key == "vat-q3"
    assert by["e2"].start == datetime(2026, 10, 19, 23, 0, tzinfo=UTC)  # London midnight (BST) in UTC
    assert by["e3"].show_as == "tentative"


async def test_list_range_covers_inclusive_days():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"items": []})

    await _make(GoogleCalendarProvider, handler).list_range(date(2026, 10, 24), date(2026, 10, 26), "Europe/London")
    # BST ends 25 Oct 2026: 24th midnight is +01:00, the day after the 26th is +00:00
    assert seen[0].url.params["timeMin"] == "2026-10-23T23:00:00Z"
    assert seen[0].url.params["timeMax"] == "2026-10-27T00:00:00Z"


async def test_create_event_payload_and_id():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"id": "new1"})

    start = datetime(2026, 10, 20, 10, 0, tzinfo=LONDON)
    eid = await _make(GoogleCalendarProvider, handler).create_event(
        "Meet", start, start.replace(hour=11), "Office", "Notes"
    )
    body = json.loads(seen[0].content)
    assert eid == "new1" and seen[0].method == "POST"
    assert body["start"] == {"dateTime": "2026-10-20T09:00:00Z", "timeZone": "UTC"}
    assert body["summary"] == "Meet" and body["location"] == "Office" and body["description"] == "Notes"
    with pytest.raises(ValueError):
        await _make(GoogleCalendarProvider, handler).create_event(
            "x", datetime(2026, 1, 1), datetime(2026, 1, 2), "", ""
        )


async def test_add_event_all_day_with_key_and_timed_with_reminder():
    bodies: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json={**_ev(), "id": "n"})

    p = _make(GoogleCalendarProvider, handler)
    out = await p.add_event(
        NewCalendarEvent(
            subject="VAT due",
            start=datetime(2026, 11, 7, tzinfo=LONDON),
            end=datetime(2026, 11, 8, tzinfo=LONDON),
            is_all_day=True,
            key="vat-q3",
            body="b",
        )
    )
    b = bodies[0]
    assert b["start"] == {"date": "2026-11-07"} and b["end"] == {"date": "2026-11-08"}
    assert b["transparency"] == "transparent" and b["extendedProperties"] == {"private": {"accnomosKey": "vat-q3"}}
    assert b["reminders"] == {"useDefault": False}
    assert out.key == "vat-q3"  # falls back to the key we sent when the response omits it

    await p.add_event(
        NewCalendarEvent(
            subject="Call",
            start=datetime(2026, 11, 9, 9, 0, tzinfo=UTC),
            end=datetime(2026, 11, 9, 9, 30, tzinfo=UTC),
            reminder_minutes=15,
        )
    )
    b = bodies[1]
    assert b["start"] == {"dateTime": "2026-11-09T09:00:00Z", "timeZone": "UTC"} and b["transparency"] == "opaque"
    assert b["reminders"] == {"useDefault": False, "overrides": [{"method": "popup", "minutes": 15}]}
    assert "extendedProperties" not in b


async def test_update_and_move_patch_and_delete():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.method == "DELETE":
            return httpx.Response(410 if req.url.path.endswith("gone") else 204)
        return httpx.Response(200, json=_ev())

    p = _make(GoogleCalendarProvider, handler)
    ev = NewCalendarEvent(
        subject="Call", start=datetime(2026, 11, 9, 9, tzinfo=UTC), end=datetime(2026, 11, 9, 10, tzinfo=UTC)
    )
    await p.update_event("e/1", ev)
    assert seen[-1].method == "PATCH" and seen[-1].url.raw_path.endswith(b"/events/e%2F1")
    assert json.loads(seen[-1].content)["start"]["date"] is None  # a timed event clears any all-day date

    moved = await p.move_event("e1", datetime(2026, 11, 9, 11, tzinfo=UTC), datetime(2026, 11, 9, 12, tzinfo=UTC))
    body = json.loads(seen[-1].content)
    assert set(body) == {"start", "end"} and body["end"]["dateTime"] == "2026-11-09T12:00:00Z"
    assert moved.id == "e1"
    with pytest.raises(ValueError):
        await p.move_event("e1", datetime(2026, 1, 1), datetime(2026, 1, 2))

    await p.delete_event("e1")
    assert seen[-1].method == "DELETE"
    with pytest.raises(FileNotFoundError):
        await p.delete_event("gone")


async def test_calendar_unimplemented_extras_and_error_mapping():
    p = _make(GoogleCalendarProvider, lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(NotImplementedError):
        await p.ensure_calendar("Accnomos")
    with pytest.raises(GoogleError) as ei:
        await p.list_events(date(2026, 10, 20))
    assert ei.value.status == 500
