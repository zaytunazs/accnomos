"""HMRC obligations drive "submitted": a return filed elsewhere must not show as open.

POST /books/vat/obligations stores the relay's obligations list; /books/vat/periods
(and /books/vat) then mark a period submitted when HMRC says fulfilled (F), keep
counting our own receipts when there are no obligations, and warn in plain English
when our periods do not match the ones HMRC holds.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode
from app.books import Books
from app.main import app
from app.routes_books import get_books

H = {"X-Graph-Token": "t"}

FULFILLED_Q3 = {
    "periodKey": "26A3",
    "start": "2026-07-01",
    "end": "2026-09-30",
    "due": "2026-11-07",
    "status": "F",
    "received": "2026-10-05",
}
OPEN_Q4 = {
    "periodKey": "26A4",
    "start": "2026-10-01",
    "end": "2026-12-31",
    "due": "2027-02-07",
    "status": "O",
}


@pytest.fixture
async def client() -> TestClient:
    fake = FakeStorageProvider()
    books = Books(fake)
    await books.ensure_tree()
    await books.post_event(
        LedgerEvent(
            id="a" * 32,
            kind="purchase",
            date=date(2026, 8, 14),
            net=4325,
            vat=865,
            counterparty="Novex",
            lines=[
                Line(account="7500 Office", debit=4325, vat_code=VatCode.STANDARD),
                Line(account="2200 VAT control", debit=865),
                Line(account="1200 Bank", credit=5190),
            ],
            approved_by="sam@example.co.uk",
            approved_at=datetime(2026, 11, 2, 12, 0),
        )
    )

    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _periods(client: TestClient) -> list[dict]:
    body = client.get("/books/vat/periods?today=2026-11-04", headers=H).json()
    return body["periods"], body


def test_obligations_are_stored_and_validated(client: TestClient) -> None:
    r = client.post("/books/vat/obligations", json={"obligations": [FULFILLED_Q3, OPEN_Q4]}, headers=H)
    assert r.status_code == 201, r.text
    assert r.json() == {"stored": 2}

    bad_status = dict(FULFILLED_Q3, status="X")
    assert client.post("/books/vat/obligations", json={"obligations": [bad_status]}, headers=H).status_code == 422
    backwards = dict(FULFILLED_Q3, start="2026-09-30", end="2026-07-01")
    assert client.post("/books/vat/obligations", json={"obligations": [backwards]}, headers=H).status_code == 422
    bad_key = dict(FULFILLED_Q3, periodKey="nope!")
    assert client.post("/books/vat/obligations", json={"obligations": [bad_key]}, headers=H).status_code == 422
    missing_due = {k: v for k, v in FULFILLED_Q3.items() if k != "due"}
    assert client.post("/books/vat/obligations", json={"obligations": [missing_due]}, headers=H).status_code == 422

    # the rejected posts stored nothing new: the good list is still what counts
    periods, _ = _periods(client)
    q3 = next(p for p in periods if p["period"] == "2026-Q3")
    assert (q3["status"], q3["submitted_source"]) == ("submitted", "hmrc")


def test_fulfilled_marks_submitted_with_hmrc_key_and_no_submit(client: TestClient) -> None:
    client.post("/books/vat/obligations", json={"obligations": [FULFILLED_Q3, OPEN_Q4]}, headers=H)
    periods, _ = _periods(client)
    q3 = next(p for p in periods if p["period"] == "2026-Q3")
    assert q3["status"] == "submitted"
    assert q3["submitted_source"] == "hmrc"
    assert q3["hmrc_period_key"] == "26A3"  # HMRC's key, not the runtime placeholder
    assert q3["deadline"] == "2026-11-07"  # HMRC's due date
    assert q3["received"] == "2026-10-05"
    assert q3["can_submit"] is False  # already filed: the web offers no submit

    view = client.get("/books/vat?today=2026-11-04&period=2026-Q3", headers=H).json()
    assert view["submitted"] is True and view["submitted_source"] == "hmrc"
    assert view["received"] == "2026-10-05" and view["period_key"] == "26A3"
    assert view["can_submit"] is False


def test_open_obligation_leaves_the_period_open(client: TestClient) -> None:
    client.post("/books/vat/obligations", json={"obligations": [OPEN_Q4]}, headers=H)
    periods, _ = _periods(client)
    q4 = next(p for p in periods if p["period"] == "2026-Q4")
    assert q4["status"] == "open" and q4["submitted_source"] is None and q4["can_submit"] is True


def test_mismatched_dates_warn_in_plain_english(client: TestClient) -> None:
    stagger_two = dict(FULFILLED_Q3, start="2026-08-01", end="2026-10-31")  # not one of our quarters
    client.post("/books/vat/obligations", json={"obligations": [stagger_two]}, headers=H)
    periods, body = _periods(client)
    assert body["warnings"] and len(body["warnings"]) == 1
    (warning,) = body["warnings"]
    assert "does not match your VAT periods" in warning and "Settings" in warning
    assert "HMRC" in warning and "26A3" not in warning  # dates, not keys: plain English
    # our own quarters are untouched by the foreign dates
    assert all(p["submitted_source"] is None for p in periods)


async def test_receipt_still_marks_submitted_with_no_obligations() -> None:
    """No obligations stored at all: our own receipt still counts (source accnomos)."""
    fake = FakeStorageProvider()
    books = Books(fake)
    await books.ensure_tree()
    await fake.write(
        "06 VAT returns/26A3/return.json",
        json.dumps(
            {
                "periodKey": "26A3",
                "obligation": {"start": "2026-07-01", "end": "2026-09-30", "due": "2026-11-07"},
            }
        ).encode(),
    )

    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    try:
        body = TestClient(app).get("/books/vat/periods?today=2026-11-04", headers=H).json()
    finally:
        app.dependency_overrides.clear()
    assert body["warnings"] == []
    q3 = next(p for p in body["periods"] if p["period"] == "2026-Q3")
    assert q3["status"] == "submitted" and q3["submitted_source"] == "accnomos"
    assert q3["hmrc_period_key"] == "26A3" and q3["can_submit"] is False
