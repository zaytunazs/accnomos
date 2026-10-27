"""Undo of an entry whose VAT period was already submitted.

An undo is normally dated like the original, so the submitted period nets to
nothing. But when that period already has a submission receipt in
`06 VAT returns/`, the correction must land in the current, open period
instead (dated today), and the response must say so (`dated_today`, `reason`).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode
from app.approve import reversal_of
from app.books import Books
from app.main import app
from app.routes_books import get_books

USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
TODAY = date(2026, 10, 27)  # in Q4, the current period (calendar quarters)


def _purchase(eid: str, when: date, net: int = 10_000, vat: int = 2_000) -> LedgerEvent:
    return LedgerEvent(
        id=eid,
        kind="purchase",
        date=when,
        net=net,
        vat=vat,
        counterparty="Novex",
        lines=[
            Line(account="5100 Tools", debit=net, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", debit=vat),
            Line(account="1200 Bank", credit=net + vat),
        ],
        approved_by=USER,
        approved_at=datetime(2026, 9, 21, 12, 0, tzinfo=UTC),
    )


async def _books(submitted: bool) -> tuple[Books, str]:
    """One Q3 purchase, with a Q3 submission receipt when `submitted`."""
    fake = FakeStorageProvider()
    books = Books(fake)
    await books.ensure_tree()
    event = _purchase("a" * 32, date(2026, 8, 14))
    await books.post_event(event)
    if submitted:
        await fake.write(  # what ConnectHmrc saves after a relay submission
            "06 VAT returns/18A3/return.json",
            json.dumps(
                {
                    "periodKey": "18A3",
                    "obligation": {"start": "2026-07-01", "end": "2026-09-30", "due": "2026-11-07"},
                }
            ).encode(),
        )
    return books, event.id


@pytest.fixture
async def open_books() -> tuple[Books, str]:
    return await _books(submitted=False)


@pytest.fixture
async def submitted_books() -> tuple[Books, str]:
    return await _books(submitted=True)


@pytest.fixture
def client() -> TestClient:
    yield TestClient(app)


def _undo(client: TestClient, books: Books, event_id: str):
    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    try:
        return client.post(f"/books/undo/{event_id}?today={TODAY}", headers=H)
    finally:
        app.dependency_overrides.clear()


def test_reversal_keeps_the_original_date_by_default() -> None:
    event = _purchase("b" * 32, date(2026, 8, 14))
    assert reversal_of(event, USER).date == date(2026, 8, 14)
    assert reversal_of(event, USER, on=TODAY).date == TODAY


def test_undo_in_an_open_period_is_unchanged(client: TestClient, open_books: tuple[Books, str]) -> None:
    books, event_id = open_books
    r = _undo(client, books, event_id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reversal"]["date"] == "2026-08-14"
    assert body["dated_today"] is False and body["reason"] is None
    assert body["submitted_period"] is None and body["current_period"] is None


def test_undo_in_a_submitted_period_lands_in_the_current_period(
    client: TestClient, submitted_books: tuple[Books, str]
) -> None:
    books, event_id = submitted_books
    r = _undo(client, books, event_id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reversal"]["date"] == "2026-10-27"
    assert body["dated_today"] is True
    assert body["reason"] == (
        "Your return for Jul–Sep 2026 was already submitted, so this correction goes in Oct–Dec 2026."
    )
    assert body["submitted_period"] == "Jul–Sep 2026"
    assert body["current_period"] == "Oct–Dec 2026"
    # A second undo is still refused, even dated differently.
    assert _undo(client, books, event_id).status_code == 409


def test_submitted_boxes_keep_the_entry_and_current_boxes_take_the_correction(
    client: TestClient, submitted_books: tuple[Books, str]
) -> None:
    books, event_id = submitted_books
    assert _undo(client, books, event_id).status_code == 200

    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    try:
        submitted = client.get(
            "/books/vat?period_start=2026-07-01&period_end=2026-09-30&period_key=26A3", headers=H
        ).json()
        current = client.get(
            "/books/vat?period_start=2026-10-01&period_end=2026-12-31&period_key=26A4", headers=H
        ).json()
    finally:
        app.dependency_overrides.clear()
    by_box = {b["box"]: b for b in submitted["boxes"]}
    assert by_box[4]["amount"] == "20.00"  # the purchase still counts: nothing reverses it in Q3
    assert by_box[4]["entries"] == 1 and submitted["undone_in_period"] == 0
    now_box = {b["box"]: b for b in current["boxes"]}
    assert now_box[4]["amount"] == "-20.00"  # the correction lands here
    assert current["events_in_period"] == 1 and current["undone_in_period"] == 1


def test_open_boxes_net_to_nothing_as_before(client: TestClient, open_books: tuple[Books, str]) -> None:
    books, event_id = open_books
    assert _undo(client, books, event_id).status_code == 200

    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    try:
        submitted = client.get(
            "/books/vat?period_start=2026-07-01&period_end=2026-09-30&period_key=26A3", headers=H
        ).json()
    finally:
        app.dependency_overrides.clear()
    by_box = {b["box"]: b for b in submitted["boxes"]}
    assert by_box[4]["amount"] == "0.00" and by_box[4]["entries"] == 2
    assert submitted["undone_in_period"] == 1
