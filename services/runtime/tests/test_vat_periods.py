"""VAT periods end to end: period ids, the date-in-period warning on scans, GET /books/vat and /books/vat/periods."""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest
from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode
from fastapi.testclient import TestClient

from app import pipeline
from app.ai.config import AiConfig
from app.approve import approve
from app.books import Books
from app.checks import check_date, check_date_in_period, decide
from app.deadlines import period_from_id, period_id, recent_periods
from app.inbox import scan_inbox
from app.main import app
from app.routes_books import get_books
from app.schemas import ExtractedDoc, ExtractedLine

H = {"X-Graph-Token": "t"}
CFG = AiConfig(mode="local", base_url="http://ollama.invalid", model="stub")
OCT_DEC = (date(2026, 10, 1), date(2026, 12, 31))


def _doc(day: str) -> ExtractedDoc:
    return ExtractedDoc.model_validate(dict(
        doc_type="receipt", supplier_name="Novex Office Supplies Ltd", supplier_vat_number="GB 882431902", customer_name=None,
        invoice_number=None, date=day, currency="GBP",
        lines=[ExtractedLine(description="A4 paper", qty=1, unit_price=43.25, net=43.25, vat_rate=20, vat=8.65)],
        net_total=43.25, vat_total=8.65, gross_total=51.90, payment_method="card", card_last4="4821",
        category_guess="Office costs", confidence=0.95,
    ))


# --- the check itself ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("day", "inside"), [
    (date(2026, 9, 30), False), (date(2026, 10, 1), True),  # the start boundary
    (date(2026, 12, 31), True), (date(2027, 1, 1), False),  # the end boundary
])
def test_both_sides_of_the_boundary(day: date, inside: bool) -> None:
    c = check_date_in_period(day, *OCT_DEC)
    assert (c.code, c.ok, c.severity) == ("DATE_IN_PERIOD", inside, "warn")


def test_message_names_the_period_the_document_goes_on() -> None:
    assert check_date_in_period(date(2026, 8, 14), *OCT_DEC).message == (
        "Dated 14 Aug 2026 — falls in the previous period (Jul–Sep 2026); it will go on that return"
    )
    assert "falls in an earlier period (Apr–Jun 2026)" in check_date_in_period(date(2026, 5, 2), *OCT_DEC).message
    assert "is after this VAT period ends (Jan–Mar 2027)" in check_date_in_period(date(2027, 1, 1), *OCT_DEC).message
    # stagger 3 (Sep–Nov): the period is named by its own months, across a year end too
    msg = check_date_in_period(date(2026, 12, 2), date(2026, 9, 1), date(2026, 11, 30)).message
    assert "(Dec 2026–Feb 2027)" in msg
    # monthly
    assert "previous period (Sep 2026)" in check_date_in_period(date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 31)).message


@pytest.mark.parametrize(("start", "end"), [
    (date(2026, 4, 1), date(2026, 6, 30)),  # stagger 1
    (date(2026, 2, 1), date(2026, 4, 30)),  # stagger 2
    (date(2026, 3, 1), date(2026, 5, 31)),  # stagger 3
    (date(2026, 4, 1), date(2026, 4, 30)),  # monthly
])
def test_6_april_tax_year_edge_does_not_split_a_vat_period(start: date, end: date) -> None:
    """The income-tax year turns on 6 April; VAT periods run on whole months, so 5 and 6 April sit together."""
    assert check_date_in_period(date(2026, 4, 5), start, end).ok
    assert check_date_in_period(date(2026, 4, 6), start, end).ok


def test_6_april_after_a_march_period_end() -> None:
    c = check_date_in_period(date(2026, 4, 6), date(2026, 1, 1), date(2026, 3, 31))
    assert not c.ok and "(Apr–Jun 2026)" in c.message


def test_outside_the_period_is_only_a_warning() -> None:
    checks = check_date(_doc("2026-08-14"), *OCT_DEC)
    assert [c.code for c in checks] == ["DATE_VALID", "DATE_IN_PERIOD"]
    status, reasons = decide(checks)
    assert status == "proposed" and reasons[0].startswith("DATE_IN_PERIOD: Dated 14 Aug 2026")


# --- period ids -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("start_month", "months", "pid", "span"), [
    (1, 3, "2026-Q4", (date(2026, 10, 1), date(2026, 12, 31))),
    (2, 3, "2026-Q4", (date(2026, 11, 1), date(2027, 1, 31))),
    (3, 3, "2026-Q4", (date(2026, 12, 1), date(2027, 2, 28))),
    (3, 3, "2026-Q1", (date(2026, 3, 1), date(2026, 5, 31))),
    (1, 1, "2026-11", (date(2026, 11, 1), date(2026, 11, 30))),
])
def test_period_ids_round_trip(start_month: int, months: int, pid: str, span: tuple[date, date]) -> None:
    assert period_from_id(pid, start_month, months) == span
    assert period_id(span[0], months) == pid


@pytest.mark.parametrize(("pid", "months"), [("2026-Q5", 3), ("2026-11", 3), ("2026-Q1", 1), ("26-Q1", 3), ("2026-13", 1)])
def test_bad_period_ids(pid: str, months: int) -> None:
    with pytest.raises(ValueError):
        period_from_id(pid, 1, months)


def test_recent_periods_is_current_then_eight_before() -> None:
    spans = recent_periods(date(2026, 11, 4), 1)
    assert len(spans) == 9 and spans[0] == OCT_DEC and spans[-1] == (date(2024, 10, 1), date(2024, 12, 31))


# --- scan pipeline ---------------------------------------------------------------------------------------------------


@pytest.fixture
def stub_extract(monkeypatch: pytest.MonkeyPatch) -> None:
    by_bytes = {b"aug": _doc("2026-08-14"), b"nov": _doc("2026-11-02")}

    async def fake_extract(data: bytes, mime: str, cfg: AiConfig) -> tuple[ExtractedDoc, dict[str, str]]:
        return by_bytes[data], {"backend": "stub", "model": cfg.model}

    async def no_verifier(*_a: object, **_kw: object) -> None:
        return None

    monkeypatch.setattr(pipeline, "extract_document", fake_extract)
    monkeypatch.setattr(pipeline, "verify", no_verifier)


@pytest.mark.usefixtures("stub_extract")
async def test_scan_warns_but_keeps_the_documents_date() -> None:
    fake = FakeStorageProvider()
    books = Books(fake)
    fake.files.update({"00 Inbox/a.jpg": b"aug", "00 Inbox/b.jpg": b"nov"})
    aug, nov = await scan_inbox(books, CFG, period=OCT_DEC)

    warn = next(c for c in aug.checks if c.code == "DATE_IN_PERIOD")
    assert not warn.ok and warn.severity == "warn" and "previous period (Jul–Sep 2026)" in warn.message
    assert aug.status == "proposed" and aug.extracted.date == "2026-08-14"
    assert next(c for c in nov.checks if c.code == "DATE_IN_PERIOD").ok and not nov.reasons

    await approve(books, aug.id, "sam@example.co.uk", rebuild=False)
    (ev,) = await books.list_events()
    assert ev.date == date(2026, 8, 14)  # the warning never moves the ledger date


@pytest.mark.usefixtures("stub_extract")
async def test_scan_without_a_period_adds_no_period_check() -> None:
    fake = FakeStorageProvider()
    fake.files["00 Inbox/a.jpg"] = b"aug"
    (p,) = await scan_inbox(Books(fake), CFG)
    assert all(c.code != "DATE_IN_PERIOD" for c in p.checks)


# --- routes ----------------------------------------------------------------------------------------------------------


def _purchase(eid: str, when: date, net: int, vat: int) -> LedgerEvent:
    return LedgerEvent(
        id=eid, kind="purchase", date=when, net=net, vat=vat, counterparty="Novex",
        lines=[Line(account="7500 Office", debit=net, vat_code=VatCode.STANDARD), Line(account="2200 VAT control", debit=vat),
               Line(account="1200 Bank", credit=net + vat)],
        approved_by="sam@example.co.uk", approved_at=datetime(2026, 11, 2, 12, 0),
    )


@pytest.fixture
async def client() -> TestClient:
    fake = FakeStorageProvider()
    books = Books(fake)
    await books.ensure_tree()
    await books.post_event(_purchase("a" * 32, date(2026, 11, 2), 4325, 865))  # Oct–Dec 2026
    await books.post_event(_purchase("b" * 32, date(2026, 8, 14), 4325, 865))  # Jul–Sep 2026
    await books.post_event(_purchase("c" * 32, date(2026, 5, 1), 1000, 200))  # Apr–Jun 2026, filed below
    await fake.write("05 VAT returns/18A2/return.json", json.dumps({  # as ConnectHmrc saves it after a relay submission
        "periodKey": "18A2", "obligation": {"start": "2026-04-01", "end": "2026-06-30", "due": "2026-08-07"},
    }).encode())
    await fake.write("05 VAT returns/junk/return.json", b"not json")  # an unreadable receipt is skipped, not a 500

    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_vat_defaults_to_the_current_period_by_settings(client: TestClient) -> None:
    body = client.get("/books/vat?today=2026-11-04", headers=H).json()
    assert (body["period"], body["start"], body["end"], body["label"]) == ("2026-Q4", "2026-10-01", "2026-12-31", "Oct–Dec 2026")
    assert body["current"] and body["can_submit"] and not body["submitted"]
    assert body["boxes"][3]["amount"] == "8.65" and body["boxes"][6]["amount"] == "43"  # Box 4 and Box 7 (whole pounds)

    stag3 = client.get("/books/vat?today=2026-11-04&stagger=3", headers=H).json()  # Sep–Nov: both receipts? no, Aug is out
    assert (stag3["start"], stag3["end"], stag3["events_in_period"]) == ("2026-09-01", "2026-11-30", 1)


def test_vat_takes_a_period_or_dates(client: TestClient) -> None:
    prev = client.get("/books/vat?today=2026-11-04&period=2026-Q3", headers=H).json()
    assert (prev["start"], prev["end"], prev["boxes"][3]["amount"]) == ("2026-07-01", "2026-09-30", "8.65")
    assert prev["can_submit"] and not prev["current"]

    old = client.get("/books/vat?today=2026-11-04&period_start=2026-04-01&period_end=2026-06-30", headers=H).json()
    assert old["period"] == "2026-Q2" and old["submitted"] and not old["can_submit"]

    assert client.get("/books/vat?period=2026-Q3&period_start=2026-07-01&period_end=2026-09-30", headers=H).status_code == 400
    assert client.get("/books/vat?period_start=2026-07-01", headers=H).status_code == 422
    assert client.get("/books/vat?period=2026-Q3&months=1", headers=H).status_code == 422
    assert client.get("/books/vat?stagger=2&start_month=1", headers=H).status_code == 400


def test_vat_periods_lists_current_and_eight_before(client: TestClient) -> None:
    body = client.get("/books/vat/periods?today=2026-11-04", headers=H).json()
    ps = body["periods"]
    assert [p["period"] for p in ps[:3]] == ["2026-Q4", "2026-Q3", "2026-Q2"] and len(ps) == 9
    assert [p["status"] for p in ps[:4]] == ["open", "open", "submitted", "none"]
    assert [p["can_submit"] for p in ps[:3]] == [True, True, False]
    assert ps[2]["hmrc_period_key"] == "18A2" and ps[0]["entries"] == 1 and ps[0]["current"]
    assert ps[1]["deadline"] == "2026-11-07" and ps[1]["label"] == "Jul–Sep 2026"

    monthly = client.get("/books/vat/periods?today=2026-11-04&months=1", headers=H).json()["periods"]
    assert [p["period"] for p in monthly[:2]] == ["2026-11", "2026-10"]
