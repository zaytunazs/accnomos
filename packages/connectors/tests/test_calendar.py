"""GraphCalendarProvider against httpx.MockTransport (no network), and the in-memory FakeCalendarProvider."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from accnomos_connectors import CalendarEvent, FakeCalendarProvider
from accnomos_connectors.msgraph import GraphCalendarProvider

pytestmark = pytest.mark.asyncio

LONDON = ZoneInfo("Europe/London")
NEXT = "https://graph.microsoft.com/v1.0/me/calendarView?page=2"


def _provider(handler) -> GraphCalendarProvider:
    async def sleep(_s: float) -> None:
        return None

    return GraphCalendarProvider("tok", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), sleep=sleep)


async def test_list_events_asks_for_the_london_day_in_utc_and_maps_fields():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        assert req.method == "GET" and req.headers["Prefer"] == 'outlook.timezone="UTC"'
        if "page=2" in str(req.url):
            return httpx.Response(200, json={"value": [
                {"id": "e3", "subject": "Dentist", "start": {"dateTime": "2026-07-02T08:00:00.0000000", "timeZone": "UTC"},
                 "end": {"dateTime": "2026-07-02T09:00:00.0000000", "timeZone": "UTC"}, "showAs": "busy"},
            ]})
        return httpx.Response(200, json={"@odata.nextLink": NEXT, "value": [
            {"id": "e2", "subject": "Cancelled", "isCancelled": True,
             "start": {"dateTime": "2026-07-02T10:00:00.0000000"}, "end": {"dateTime": "2026-07-02T11:00:00.0000000"}},
            {"id": "e1", "subject": "Quote visit", "start": {"dateTime": "2026-07-02T06:30:00.0000000", "timeZone": "UTC"},
             "end": {"dateTime": "2026-07-02T07:15:00.0000000", "timeZone": "UTC"}, "location": {"displayName": "LS6 2AB"},
             "bodyPreview": "Bring ladder", "isAllDay": False, "showAs": "tentative"},
        ]})

    out = await _provider(handler).list_events(date(2026, 7, 2))
    params = seen[0].url.params
    assert seen[0].url.path == "/v1.0/me/calendarView"
    assert params["startDateTime"] == "2026-07-01T23:00:00Z"  # midnight BST
    assert params["endDateTime"] == "2026-07-02T23:00:00Z"
    assert "startDateTime" not in seen[1].url.params  # the nextLink is followed as-is
    assert [e.id for e in out] == ["e1", "e3"]  # cancelled dropped, earliest first
    first = out[0]
    assert first.start == datetime(2026, 7, 2, 6, 30, tzinfo=UTC)
    assert first.start.astimezone(LONDON).hour == 7
    assert (first.location, first.body_preview, first.show_as) == ("LS6 2AB", "Bring ladder", "tentative")


async def test_list_events_in_winter_uses_gmt():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"value": []})

    assert await _provider(handler).list_events(date(2026, 11, 5)) == []
    assert seen[0].url.params["startDateTime"] == "2026-11-05T00:00:00Z"


async def test_create_event_posts_utc_times_subject_location_and_body():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(201, json={"id": "new-1"})

    start = datetime(2026, 7, 2, 9, 0, tzinfo=LONDON)
    event_id = await _provider(handler).create_event(
        "[Accnomos] Kitchen refit", start, start + timedelta(hours=2), "12 Elm Road, LS6 2AB", "Job 00000000a001",
    )
    assert event_id == "new-1"
    req = seen[0]
    assert req.method == "POST" and req.url.path == "/v1.0/me/events"
    body = json.loads(req.content)
    assert body["subject"] == "[Accnomos] Kitchen refit"
    assert body["start"] == {"dateTime": "2026-07-02T08:00:00", "timeZone": "UTC"}
    assert body["end"] == {"dateTime": "2026-07-02T10:00:00", "timeZone": "UTC"}
    assert body["location"] == {"displayName": "12 Elm Road, LS6 2AB"}
    assert body["body"] == {"contentType": "text", "content": "Job 00000000a001"}


async def test_create_event_refuses_naive_times():
    with pytest.raises(ValueError):
        await _provider(lambda r: httpx.Response(201, json={"id": "x"})).create_event(
            "x", datetime(2026, 7, 2, 9), datetime(2026, 7, 2, 10), "", "",
        )


async def test_fake_calendar_lists_the_day_and_records_created_events():
    day = date(2026, 10, 29)
    inside = CalendarEvent(id="a", subject="Call", start=datetime(2026, 10, 29, 9, tzinfo=LONDON),
                           end=datetime(2026, 10, 29, 10, tzinfo=LONDON))
    other = CalendarEvent(id="b", subject="Other day", start=datetime(2026, 10, 30, 9, tzinfo=LONDON),
                          end=datetime(2026, 10, 30, 10, tzinfo=LONDON))
    cal = FakeCalendarProvider([other, inside])
    assert [e.id for e in await cal.list_events(day)] == ["a"]
    new_id = await cal.create_event("[Accnomos] Visit", datetime(2026, 10, 29, 11, tzinfo=LONDON),
                                    datetime(2026, 10, 29, 12, tzinfo=LONDON), "", "Job x")
    assert [e.id for e in cal.created] == [new_id]
    assert len(await cal.list_events(day)) == 2


async def test_fake_ensure_calendar_is_idempotent_and_upsert_replaces_by_key():
    cal = FakeCalendarProvider()
    cid = await cal.ensure_calendar("Accnomos")
    assert await cal.ensure_calendar("Accnomos") == cid
    assert await cal.ensure_calendar("Other") != cid

    ref = await cal.upsert_all_day_event(cid, "vat-26A3", "2026-11-07", "VAT return due", "first")
    assert await cal.upsert_all_day_event(cid, "vat-26A3", "2026-11-08", "VAT return due", "second") == ref
    assert cal.all_day[cid] == {"vat-26A3": ("2026-11-08", "VAT return due", "second")}


async def test_fake_upsert_into_unknown_calendar_fails():
    with pytest.raises(FileNotFoundError):
        await FakeCalendarProvider().upsert_all_day_event("nope", "k", "2026-11-07", "t", "b")
