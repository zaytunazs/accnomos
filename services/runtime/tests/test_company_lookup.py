"""Companies House and the VAT check (app/company_lookup.py, /lookup/*, POST /contacts/vat-check), all faked."""

from __future__ import annotations

import base64
import json
from datetime import UTC, date, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode
from app import company_lookup as lookup
from app import contacts as cb
from app.books import Books

H = {"X-Graph-Token": "tok", "X-User": "sam@example.co.uk"}
KEY = "ch-test-key-not-real"
SEARCH = {
    "items": [
        {
            "title": "HOWDENS JOINERY LTD",
            "company_number": "01234567",
            "company_status": "active",
            "company_type": "ltd",
            "date_of_creation": "1987-01-01",
            "address": {
                "premises": "40",
                "address_line_1": "Portman Square",
                "locality": "London",
                "postal_code": "W1H 6LT",
                "country": "United Kingdom",
            },  # noqa: E501
        },
        {"title": "NO NUMBER", "company_number": ""},
    ]
}
PROFILE = {
    "company_name": "HOWDENS JOINERY LTD",
    "company_number": "00000006",
    "company_status": "active",
    "type": "ltd",
    "registered_office_address": {"address_line_1": "1 High St", "locality": "Leeds", "postal_code": "LS1 1AA"},
}
RELAY_OK = {
    "vrn": "GB123456789",
    "registered": True,
    "name": "HOWDENS JOINERY LIMITED",
    "address": "40 Portman Square, London, W1H 6LT",
    "consultation_number": None,
    "checked_at": "2026-10-27T09:00:00+00:00",
    "source": "hmrc-sandbox",
    "checksum_ok": False,
}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    lookup.reset()
    for k in ("COMPANIES_HOUSE_API_KEY", "HMRC_RELAY_URL", "ACCNOMOS_TEST_MODE", "COMPANIES_HOUSE_BASE"):
        monkeypatch.delenv(k, raising=False)
    yield
    lookup.reset()


def fake_upstream(monkeypatch, routes: dict[str, tuple[int, dict]]) -> list[httpx.Request]:
    log: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        log.append(req)
        status, body = routes[req.url.path]
        return httpx.Response(status, json=body)

    monkeypatch.setattr(lookup, "_transport", httpx.MockTransport(handler))
    return log


def _purchase(gross: int, who: str) -> LedgerEvent:
    net = round(gross / 1.2)
    return LedgerEvent(
        id="d" * 32,
        kind="purchase",
        date=date(2026, 9, 30),
        lines=[
            Line(account="5000 Materials", debit=net, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", debit=gross - net),
            Line(account="2100 Creditors", credit=gross),
        ],
        net=net,
        vat=gross - net,
        counterparty=who,
        approved_by=H["X-User"],
        approved_at=datetime(2026, 10, 25, tzinfo=UTC),
    )


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
async def books(fake: FakeStorageProvider) -> Books:
    b = Books(fake)
    await b.post_event(_purchase(24000, "Howdens Joinery Ltd"))
    return b


@pytest.fixture
def client(books: Books):
    from app.main import app
    from app.routes_books import get_books

    async def override_books() -> Books:
        return books

    app.dependency_overrides[get_books] = override_books
    yield TestClient(app)
    app.dependency_overrides.clear()


# --- Companies House -----------------------------------------------------------------------------------------


def test_no_key_is_503_and_status_says_so(client: TestClient, monkeypatch) -> None:
    fake_upstream(monkeypatch, {})  # any call would KeyError
    r = client.get("/lookup/companies?q=howdens", headers=H)
    assert r.status_code == 503 and r.json()["error"] == "companies_house_not_configured"
    assert client.get("/lookup/companies/01234567", headers=H).json()["error"] == "companies_house_not_configured"
    s = client.get("/lookup/status").json()
    assert s == {"companies_house": False, "vat_check": False, "sample": False}


def test_signed_out_is_401(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", KEY)
    assert client.get("/lookup/companies?q=howdens").status_code == 401
    assert client.get("/lookup/vat/GB123456789").status_code == 401


def test_search_basic_auth_mapping_and_cache(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", KEY)
    log = fake_upstream(monkeypatch, {"/search/companies": (200, SEARCH)})
    r = client.get("/lookup/companies?q=Howdens  joinery", headers=H)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items == [
        {
            "company_number": "01234567",
            "name": "HOWDENS JOINERY LTD",
            "status": "active",
            "type": "ltd",
            "address": "40 Portman Square, London, W1H 6LT",
            "date_of_creation": "1987-01-01",
            "source": "companies-house",
            "sample": False,
        }
    ]
    req = log[0]
    assert str(req.url).startswith("https://api.company-information.service.gov.uk/search/companies?")
    assert req.url.params["q"] == "Howdens joinery" and req.url.params["items_per_page"] == "10"
    # HTTP Basic: the key as the username, an empty password
    assert req.headers["authorization"] == "Basic " + base64.b64encode(f"{KEY}:".encode()).decode()
    assert client.get("/lookup/companies?q=howdens JOINERY", headers=H).status_code == 200
    assert len(log) == 1  # cached in process


def test_profile_by_number_and_errors(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", KEY)
    routes = {"/company/00000006": (200, PROFILE), "/company/SC999999": (404, {}), "/search/companies": (429, {})}
    log = fake_upstream(monkeypatch, routes)
    r = client.get("/lookup/companies/6", headers=H)
    assert r.status_code == 200 and r.json()["address"] == "1 High St, Leeds, LS1 1AA"
    assert client.get("/lookup/companies?q=00000006", headers=H).json()["items"][0]["company_number"] == "00000006"
    assert [q.url.path for q in log].count("/company/00000006") == 1  # the search by number used the cache
    assert client.get("/lookup/companies/sc999999", headers=H).json()["error"] == "not_found"
    assert client.get("/lookup/companies/bad!", headers=H).json()["error"] == "bad_query"
    r = client.get("/lookup/companies?q=busy", headers=H)
    assert r.status_code == 429 and r.headers["retry-after"] == "60"


def test_polite_rate_limit_stops_before_companies_house(monkeypatch) -> None:
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", KEY)
    log = fake_upstream(monkeypatch, {"/search/companies": (200, {"items": []})})
    monkeypatch.setattr(lookup, "_bucket", lookup.TokenBucket(2))
    import asyncio

    async def go() -> list[str]:
        out = []
        for q in ("aa", "bb", "cc"):
            try:
                await lookup.search(q)
                out.append("ok")
            except lookup.RateLimited:
                out.append("429")
        return out

    assert asyncio.run(go()) == ["ok", "ok", "429"]
    assert len(log) == 2


def test_cache_expires_after_a_day(monkeypatch) -> None:
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", KEY)
    log = fake_upstream(monkeypatch, {"/company/00000006": (200, PROFILE)})
    now = [1000.0]
    monkeypatch.setattr(lookup, "_clock", lambda: now[0])
    import asyncio

    asyncio.run(lookup.profile("00000006"))
    now[0] += lookup.CACHE_TTL_S - 1
    asyncio.run(lookup.profile("00000006"))
    assert len(log) == 1
    now[0] += 2
    asyncio.run(lookup.profile("00000006"))
    assert len(log) == 2


# --- test mode fakes -----------------------------------------------------------------------------------------


def test_test_mode_fakes_need_no_network(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", "1")
    fake_upstream(monkeypatch, {})  # any network call would fail
    assert client.get("/lookup/status").json() == {"companies_house": True, "vat_check": True, "sample": True}
    items = client.get("/lookup/companies?q=novex office", headers=H).json()["items"]
    assert [i["name"] for i in items] == ["NOVEX OFFICE SUPPLIES LIMITED", "NOVEX OFFICE FURNITURE LTD"]
    assert all(i["sample"] and i["source"] == "sample" and i["company_number"].startswith("ZZ") for i in items)
    assert client.get("/lookup/companies/zz000003", headers=H).json()["name"] == "JM TRADING LTD"
    gold = client.get("/lookup/vat/GB 882 431 902", headers=H).json()  # gold 001's fictional supplier
    assert gold["registered"] and gold["name"] == "NOVEX OFFICE SUPPLIES LTD" and gold["source"] == "sample"
    assert client.get("/lookup/vat/GB123456782", headers=H).json()["registered"] is False


# --- VAT check through the relay -----------------------------------------------------------------------------


def test_vat_check_needs_the_relay(client: TestClient) -> None:
    r = client.get("/lookup/vat/GB123456789", headers=H)
    assert r.status_code == 503 and r.json()["error"] == "vat_check_not_configured"


def test_vat_check_calls_the_relay_and_caches(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("HMRC_RELAY_URL", "http://relay:8787/")
    log = fake_upstream(monkeypatch, {"/hmrc/vat-check/123456789": (200, RELAY_OK)})
    r = client.get("/lookup/vat/gb 123 4567 89", headers=H)
    assert r.status_code == 200 and r.json()["name"] == "HOWDENS JOINERY LIMITED"
    assert str(log[0].url) == "http://relay:8787/hmrc/vat-check/123456789"
    client.get("/lookup/vat/GB123456789", headers=H)
    assert len(log) == 1
    assert client.get("/lookup/vat/GB12", headers=H).json()["error"] == "bad_query"


def test_relay_without_hmrc_credentials_is_503(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("HMRC_RELAY_URL", "http://relay:8787")
    fake_upstream(monkeypatch, {"/hmrc/vat-check/123456789": (503, {"detail": "not configured"})})
    assert client.get("/lookup/vat/GB123456789", headers=H).json()["error"] == "vat_check_not_configured"


def test_contact_keeps_the_vat_check(client: TestClient, fake: FakeStorageProvider, monkeypatch) -> None:
    monkeypatch.setenv("HMRC_RELAY_URL", "http://relay:8787")
    log = fake_upstream(monkeypatch, {"/hmrc/vat-check/123456789": (200, RELAY_OK)})
    howdens = client.get("/contacts", headers=H).json()["contacts"][0]
    assert howdens["company_number"] is None and howdens["vat_check"] is None
    assert client.put(f"/contacts/{howdens['id']}", headers=H, json={"vrn": "GB123456789"}).status_code == 200

    r = client.post("/contacts/vat-check", headers=H, json={"vrn": "GB123456789", "name": "Howdens Joinery Ltd"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["contact_id"] == howdens["id"] and body["cached"] is False and body["name_differs"] is False
    stored = {c["id"]: c for c in json.loads(fake.files[cb.CONTACTS])}[howdens["id"]]
    assert stored["vat_check"]["name"] == "HOWDENS JOINERY LIMITED"
    assert stored["vat_status"] == "unknown"  # the VAT status stays the user's call

    lookup.reset()  # even with the process cache gone, the contact's copy answers
    again = client.post("/contacts/vat-check", headers=H, json={"vrn": "GB123456789", "name": "Someone Else Ltd"})
    assert again.json()["cached"] is True and again.json()["name_differs"] is True
    assert len(log) == 1
    assert client.post("/contacts/vat-check", headers=H, json={"vrn": "123", "name": "x"}).status_code == 422
    assert client.post("/contacts/vat-check", headers=H, json={"vrn": "GBXX3456789"}).status_code == 400

    # a different VAT number drops the old result
    r = client.put(f"/contacts/{howdens['id']}", headers=H, json={"vrn": "GB123456782"})
    assert r.json()["vat_check"] is None


def test_vat_check_for_an_unknown_number_keeps_nothing(client: TestClient, fake: FakeStorageProvider, monkeypatch):
    monkeypatch.setenv("HMRC_RELAY_URL", "http://relay:8787")
    nf = {**RELAY_OK, "vrn": "GB123456782", "registered": False, "name": None, "address": None}
    fake_upstream(monkeypatch, {"/hmrc/vat-check/123456782": (200, nf)})
    r = client.post("/contacts/vat-check", headers=H, json={"vrn": "GB123456782", "name": "New Supplier Ltd"})
    assert r.json()["contact_id"] is None and r.json()["check"]["registered"] is False
    assert cb.CONTACTS not in fake.files


# --- the contact's new fields ---------------------------------------------------------------------------------


def test_old_contact_files_still_load() -> None:
    old = {"id": "0123456789abcdef", "kind": "supplier", "name": "Howdens", "normalised_key": "howdens"}
    c = cb.Contact.model_validate(old)
    assert c.company_number is None and c.vat_check is None and c.verified_vat_name() is None


def test_company_number_edit_is_normalised_and_checked() -> None:
    c = cb.Contact(id="0123456789abcdef", kind="supplier", name="Howdens", normalised_key="howdens")
    cb.apply_edit(c, {"company_number": " sc 123456 "}, [])
    assert c.company_number == "SC123456" and "company_number" in c.edited
    cb.apply_edit(c, {"company_number": "6"}, [])
    assert c.company_number == "00000006"
    with pytest.raises(cb.ContactEditError):
        cb.apply_edit(c, {"company_number": "12-34"}, [])
    cb.apply_edit(c, {"company_number": ""}, [])
    assert c.company_number is None


def test_verified_vat_name_only_for_the_current_number() -> None:
    check = lookup.VatCheck.model_validate(RELAY_OK)
    c = cb.Contact(
        id="0123456789abcdef", kind="supplier", name="Howdens", normalised_key="howdens", vrn="GB123456789",
        vat_check=check,
    )  # fmt: skip
    assert c.verified_vat_name() == "HOWDENS JOINERY LIMITED"
    c.vrn = "GB123456782"
    assert c.verified_vat_name() is None


@pytest.mark.parametrize(
    ("ours", "theirs", "differs"),
    [
        ("Novex Office Supplies Ltd", "NOVEX OFFICE SUPPLIES LIMITED", False),
        ("Screwfix", "SCREWFIX DIRECT LIMITED", False),
        ("B&Q", "B AND Q LIMITED", False),
        ("Novex Office Supplies Ltd", "BRAMBLEWOOD JOINERY LTD", True),
        ("Howdens Joinery", "HOWDEN JOINERY GROUP PLC", False),
        (None, "ANY LTD", False),
    ],
)
def test_names_differ(ours, theirs, differs) -> None:
    assert lookup.names_differ(ours, theirs) is differs
