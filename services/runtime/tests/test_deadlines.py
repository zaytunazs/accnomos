"""VAT periods, deadlines and GET /books/deadlines."""

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode
from app.books import Books
from app.deadlines import filing_deadline, period_containing, period_label, previous_period, stagger_of
from app.main import app
from app.routes_books import get_books

H = {"X-Graph-Token": "t"}
APPROVED = dict(approved_by="sam@example.co.uk", approved_at=datetime(2026, 10, 1, 12, 0))


@pytest.mark.parametrize(
    ("end", "due"),
    [
        (date(2026, 9, 30), date(2026, 11, 7)),
        (date(2026, 10, 31), date(2026, 12, 7)),
        (date(2026, 12, 31), date(2027, 2, 7)),
        (date(2027, 1, 31), date(2027, 3, 7)),  # February is short: 28 Feb + 7
        (date(2028, 1, 31), date(2028, 3, 7)),  # and in a leap year: 29 Feb + 7
        (date(2026, 11, 30), date(2027, 1, 7)),
    ],
)
def test_filing_deadline_is_one_month_and_seven_days(end: date, due: date) -> None:
    assert filing_deadline(end) == due


def test_periods_for_each_stagger() -> None:
    day = date(2026, 10, 27)
    assert period_containing(day, 1) == (date(2026, 10, 1), date(2026, 12, 31))  # stagger 1
    assert period_containing(day, 2) == (date(2026, 8, 1), date(2026, 10, 31))  # stagger 2
    assert period_containing(day, 3) == (date(2026, 9, 1), date(2026, 11, 30))  # stagger 3
    assert period_containing(date(2027, 1, 15), 3) == (date(2026, 12, 1), date(2027, 2, 28))  # across a year end
    assert period_containing(day, 7) == period_containing(day, 1)  # a custom start month is one of the staggers
    assert period_containing(day, 1, months=1) == (date(2026, 10, 1), date(2026, 10, 31))
    assert previous_period(date(2026, 1, 1)) == (date(2025, 10, 1), date(2025, 12, 31))
    assert [stagger_of(m) for m in (1, 4, 2, 11, 3, 12)] == [1, 1, 2, 2, 3, 3]
    assert period_label(date(2026, 12, 1), date(2027, 2, 28)) == "Dec 2026–Feb 2027"
    assert period_label(date(2026, 7, 1), date(2026, 9, 30)) == "Jul–Sep 2026"


def _purchase(eid: str, when: date, net: int, vat: int) -> LedgerEvent:
    return LedgerEvent(
        id=eid,
        kind="purchase",
        date=when,
        net=net,
        vat=vat,
        counterparty="Screwfix",
        lines=[
            Line(account="5100 Tools", debit=net, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", debit=vat),
            Line(account="1200 Bank", credit=net + vat),
        ],
        **APPROVED,
    )


def _sale(eid: str, when: date, net: int, vat: int) -> LedgerEvent:
    return LedgerEvent(
        id=eid,
        kind="sale",
        date=when,
        net=net,
        vat=vat,
        counterparty="Acme",
        lines=[
            Line(account="1100 Debtors", debit=net + vat),
            Line(account="4000 Sales", credit=net, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", credit=vat),
        ],
        **APPROVED,
    )


@pytest.fixture
def client():
    books = Books(FakeStorageProvider())

    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    try:
        yield TestClient(app), books
    finally:
        app.dependency_overrides.clear()


async def test_deadlines_route_stagger_1(client) -> None:
    tc, books = client
    await books.post_event(_sale("s" * 32, date(2026, 8, 31), 100000, 20000))  # Jul–Sep
    await books.post_event(_purchase("p" * 32, date(2026, 9, 21), 3206, 641))  # Jul–Sep
    await books.post_event(_purchase("q" * 32, date(2026, 10, 2), 5000, 1000))  # Oct–Dec so far: a reclaim
    r = tc.get("/books/deadlines?stagger=1&today=2026-10-27", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stagger"] == 1 and body["months"] == 3
    due, cur = body["due"], body["current"]
    assert (due["start"], due["end"], due["deadline"]) == ("2026-07-01", "2026-09-30", "2026-11-07")
    assert due["days_remaining"] == 11 and due["period_key"] == "26A3" and due["label"] == "Jul–Sep 2026"
    assert due["box5"] == "193.59" and due["box5_direction"] == "pay" and due["entries"] == 2
    assert (cur["end"], cur["deadline"], cur["days_to_end"], cur["days_remaining"]) == (
        "2026-12-31",
        "2027-02-07",
        65,
        103,
    )
    assert cur["box5"] == "10.00" and cur["box5_direction"] == "reclaim" and cur["entries"] == 1


async def test_deadlines_route_custom_start_month_and_no_return_due(client) -> None:
    tc, books = client
    # Stagger 2 via a custom start month (May): on 27 Oct we are in Aug–Oct; May–Jul was due 7 Sep, so nothing is due.
    body = tc.get("/books/deadlines?start_month=5&today=2026-10-27", headers=H).json()
    assert body["stagger"] == 2 and body["start_month"] == 2 and body["due"] is None
    assert body["current"]["end"] == "2026-10-31" and body["current"]["deadline"] == "2026-12-07"
    assert body["current"]["box5"] == "0.00" and body["current"]["box5_direction"] == "nil"
    assert body["current"]["period_key"] is None  # not a calendar quarter; HMRC obligations carry the key

    monthly = tc.get("/books/deadlines?months=1&today=2026-11-03", headers=H).json()
    assert monthly["due"]["end"] == "2026-10-31" and monthly["due"]["deadline"] == "2026-12-07"
    assert monthly["current"]["label"] == "Nov 2026" and monthly["stagger"] is None

    assert tc.get("/books/deadlines?stagger=1&start_month=2", headers=H).status_code == 400
    assert tc.get("/books/deadlines?stagger=4", headers=H).status_code == 422
    assert tc.get("/books/deadlines?months=2", headers=H).status_code == 422


def test_deadlines_needs_a_token() -> None:
    assert TestClient(app).get("/books/deadlines").status_code == 401
