"""/calendar/* (app/routes_calendar.py): read, add and remove events; deadlines into the calendar, idempotent."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from accnomos_connectors import CalendarEvent, FakeCalendarProvider, FakeStorageProvider
from app import demo, routes_calendar
from app.books import Books
from app.routes_books import get_books, require_user
from app.routes_calendar import Wanted
from app.routes_plan import get_calendar

LONDON = ZoneInfo("Europe/London")
TODAY = date(2026, 11, 4)
USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}


@pytest.fixture
def cal() -> FakeCalendarProvider:
    return FakeCalendarProvider(
        [
            CalendarEvent(
                id="theirs",
                subject="Dentist",
                start=datetime(2026, 11, 5, 9, tzinfo=LONDON),
                end=datetime(2026, 11, 5, 10, tzinfo=LONDON),
            )
        ]
    )


@pytest.fixture
def books() -> Books:
    return Books(FakeStorageProvider())


@pytest.fixture
def client(cal: FakeCalendarProvider, books: Books, monkeypatch: pytest.MonkeyPatch):
    from app.main import app

    async def the_books() -> Books:
        return books

    async def the_calendar():
        yield cal

    monkeypatch.setattr(routes_calendar, "london_today", lambda: TODAY)
    app.dependency_overrides[get_books] = the_books
    app.dependency_overrides[require_user] = lambda: USER
    app.dependency_overrides[get_calendar] = the_calendar
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_add_and_remove_events(client: TestClient, cal: FakeCalendarProvider, books: Books) -> None:
    r = client.get("/calendar/events?start=2026-11-04&end=2026-11-10", headers=H)
    assert r.status_code == 200 and [e["subject"] for e in r.json()] == ["Dentist"]
    assert r.json()[0]["accnomos"] is False and r.json()[0]["start"].startswith("2026-11-05T09:00:00")

    r = client.post(
        "/calendar/events",
        headers=H,
        json={"subject": "Call Emily Clarke", "start": "2026-11-06T14:00", "location": "Phone"},
    )
    assert r.status_code == 201, r.text
    made = r.json()
    assert made["accnomos"] is True and made["all_day"] is False
    assert made["start"].startswith("2026-11-06T14:00:00") and made["end"].startswith("2026-11-06T15:00:00")

    r = client.post("/calendar/events", headers=H, json={"subject": "Stock take", "start": "2026-11-09"})
    assert r.status_code == 201 and r.json()["all_day"] is True

    assert client.request("DELETE", f"/calendar/events/{made['id']}", headers=H, json={}).status_code == 422
    assert (
        client.request("DELETE", f"/calendar/events/{made['id']}", headers=H, json={"confirm": True}).status_code == 204
    )
    assert client.request("DELETE", "/calendar/events/nope", headers=H, json={"confirm": True}).status_code == 404
    subjects = [e["subject"] for e in client.get("/calendar/events?start=2026-11-04&end=2026-11-10", headers=H).json()]
    assert subjects == ["Dentist", "Stock take"]


def test_bad_ranges_and_times_are_refused(client: TestClient) -> None:
    assert client.get("/calendar/events?start=2026-11-10&end=2026-11-04", headers=H).status_code == 422
    assert client.get("/calendar/events?start=2026-11-01&end=2027-01-31", headers=H).status_code == 422
    bad = {"subject": "x", "start": "2026-11-06T14:00", "end": "2026-11-06T13:00"}
    assert client.post("/calendar/events", headers=H, json=bad).status_code == 422
    assert client.post("/calendar/events", headers=H, json={"subject": "x", "start": "soon"}).status_code == 422
    assert (
        client.post("/calendar/events", headers=H, json={"subject": "x" * 121, "start": "2026-11-06"}).status_code
        == 422
    )


def test_deadline_sync_is_idempotent_moves_and_removes(
    client: TestClient, cal: FakeCalendarProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    wanted = [
        Wanted(key="deadline:vat:a", title="VAT return Jul–Sep 2026 due", day=date(2026, 11, 7), body="b"),
        Wanted(
            key="invoice:INV-0006",
            title="Invoice INV-0006 due from Hartwell (£739.68 unpaid)",
            day=date(2026, 11, 20),
            body="b",
        ),
    ]

    async def fake_wanted(_books, _day, _cycle):  # noqa: ANN001
        return list(wanted)

    monkeypatch.setattr(routes_calendar, "wanted_deadlines", fake_wanted)
    assert client.post("/calendar/deadlines/sync", headers=H, json={}).status_code == 422
    first = client.post("/calendar/deadlines/sync", headers=H, json={"confirm": True}).json()
    assert (first["added"], first["updated"], first["unchanged"], first["removed"]) == (2, 0, 0, 0)
    ev = next(e for e in cal.events if e.key == "deadline:vat:a")
    assert ev.is_all_day and ev.start.date() == date(2026, 11, 7) and (ev.end - ev.start) == timedelta(days=1)

    again = client.post("/calendar/deadlines/sync", headers=H, json={"confirm": True}).json()
    assert (again["added"], again["updated"], again["unchanged"]) == (0, 0, 2)
    assert sum(1 for e in cal.events if e.key) == 2  # never duplicated

    wanted[0] = wanted[0].model_copy(update={"day": date(2026, 11, 9)})  # the date moved
    wanted.pop()  # the invoice was paid
    third = client.post("/calendar/deadlines/sync", headers=H, json={"confirm": True}).json()
    assert (third["added"], third["updated"], third["unchanged"], third["removed"]) == (0, 1, 0, 1)
    assert [e.start.date() for e in cal.events if e.key] == [date(2026, 11, 9)]
    assert any(e.id == "theirs" for e in cal.events)  # someone else's event is never touched

    status = client.get("/calendar/deadlines/status", headers=H).json()
    assert status["synced"] is True and status["count"] == 1 and status["keep"] is False
    assert client.put("/calendar/deadlines/preference", headers=H, json={"keep": True}).json()["keep"] is True


def test_real_deadlines_from_empty_books(client: TestClient, cal: FakeCalendarProvider) -> None:
    r = client.post("/calendar/deadlines/sync", headers=H, json={"confirm": True})
    assert r.status_code == 200, r.text
    for e in r.json()["events"]:
        assert e["all_day"] and e["accnomos"]


# --------------------------------------------------------------------------- #
# In a demo: the session's own calendar, nothing reaches Microsoft
# --------------------------------------------------------------------------- #


async def _small(day: date) -> demo.Snapshot:
    return demo.Snapshot(day, FakeStorageProvider(), "Bramblewood Joinery Ltd", 0.01)


def test_demo_session_uses_its_own_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.routes_books import router as books_router

    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_SECRET", "s" * 40)
    monkeypatch.delenv("ACCNOMOS_TEST_MODE", raising=False)
    monkeypatch.setattr(demo, "BUILD", _small)
    monkeypatch.setattr(demo, "CREATE_LIMITER", None)
    demo.reset_for_tests()
    try:
        app = FastAPI()
        app.include_router(demo.router)
        app.include_router(books_router)
        app.include_router(routes_calendar.router)
        c = TestClient(app)
        token = c.post("/demo/session").json()["session"]
        h = {demo.HEADER: token, "X-User": demo.USER}
        listed = c.get("/calendar/events", headers=h)
        assert listed.status_code == 200, listed.text
        before = len(listed.json())
        made = c.post("/calendar/events", headers=h, json={"subject": "Quote for Emily", "start": "2026-11-10T11:00"})
        assert made.status_code == 201, made.text
        assert (
            c.request("DELETE", f"/calendar/events/{made.json()['id']}", headers=h, json={"confirm": True}).status_code
            == 204
        )
        assert len(c.get("/calendar/events", headers=h).json()) == before
    finally:
        demo.reset_for_tests()
