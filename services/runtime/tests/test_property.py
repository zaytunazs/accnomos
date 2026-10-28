"""Landlords (app/property.py, /property/*): the register, ownership splits, HMRC categories, the finance cost
credit, replacement of domestic items, Rent a Room, and the Property Business API 6.0 bodies."""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line
from app import property as pr
from app.books import Books, now
from app.paths import REPORTS

USER = "lee@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
TODAY = date(2026, 10, 28)


# --------------------------------------------------------------------------- #
# Pure rules
# --------------------------------------------------------------------------- #


@given(
    amount=st.integers(min_value=-(10**9), max_value=10**9),
    cuts=st.lists(st.integers(min_value=0, max_value=pr.WHOLE), min_size=1, max_size=5),
)
def test_split_always_adds_up_to_the_penny(amount: int, cuts: list[int]) -> None:
    points = sorted(cuts)
    shares = [b - a for a, b in zip([0, *points], [*points, pr.WHOLE], strict=True)]
    parts = pr.split_pence(amount, shares)
    assert sum(parts) == amount
    for part, share in zip(parts, shares, strict=True):
        assert abs(abs(part) * pr.WHOLE - abs(amount) * share) < pr.WHOLE  # within a penny of the exact share


def test_split_examples() -> None:
    assert pr.split_pence(100, [5000, 5000]) == [50, 50]
    assert pr.split_pence(101, [5000, 5000]) == [51, 50]  # the odd penny to the first on a tie
    assert pr.split_pence(100, [3333, 3333, 3334]) == [33, 33, 34]
    assert pr.split_pence(-101, [7000, 3000]) == [-71, -30]
    with pytest.raises(ValueError):
        pr.split_pence(100, [5000, 4000])


def _prop(**kw) -> pr.PropertyIn:
    return pr.PropertyIn.model_validate({"name": "Flat 1", **kw})


def test_spouses_are_taxed_50_50_unless_form_17() -> None:
    owners = [{"name": "Lee", "share_bp": 7000, "me": True}, {"name": "Sam", "share_bp": 3000}]
    shares, note = pr.tax_shares(_prop(joint="spouses", owners=owners))
    assert [s for _, s in shares] == [5000, 5000]
    assert note and "Form 17" in note
    shares, note = pr.tax_shares(_prop(joint="spouses", form17=True, owners=owners))
    assert [s for _, s in shares] == [7000, 3000] and note is None
    shares, note = pr.tax_shares(_prop(joint="other", owners=owners))  # e.g. siblings: actual shares
    assert [s for _, s in shares] == [7000, 3000] and note is None


def test_register_validation() -> None:
    me = {"name": "Lee", "share_bp": 6000, "me": True}
    assert _prop().owners[0].me and _prop().owners[0].share_bp == pr.WHOLE  # sole by default: me, 100 %
    with pytest.raises(ValueError, match="add up to 100"):
        _prop(joint="other", owners=[me, {"name": "Jo", "share_bp": 3000}])
    with pytest.raises(ValueError, match="exactly one owner is you"):
        _prop(joint="other", owners=[{"name": "A", "share_bp": 5000}, {"name": "B", "share_bp": 5000}])
    with pytest.raises(ValueError, match="Form 17"):
        _prop(joint="other", form17=True, owners=[me, {"name": "Jo", "share_bp": 4000}])
    with pytest.raises(ValueError, match="postcode"):
        _prop(postcode="NOT A CODE")
    assert _prop(postcode="ls1  4ap").postcode == "LS1 4AP"


def test_categories_follow_hmrc_mapping_and_the_property_use() -> None:
    assert pr.category_of("4700 Property: rents", "residential").field == "periodAmount"
    assert pr.category_of("7700 Insurance", "residential").box == "24"
    assert pr.category_of("5000 Materials", "residential").key == "repairs"
    assert pr.category_of("7600 Professional fees", "residential").field == "professionalFees"
    assert pr.category_of("1200 Bank", "residential") is None and pr.category_of("2200 VAT control", "x") is None
    # Mortgage interest: restricted on a residential let, a normal expense on a commercial one.
    assert pr.category_of("7920 Mortgage interest", "residential").key == "finance_res"
    assert pr.category_of("7920 Mortgage interest", "commercial").key == "finance_nonres"
    assert pr.category_of("8530 Property: residential finance costs", "commercial").box == "26"
    boxes = {c.key: c.box for c in pr.CATEGORIES}
    assert boxes["finance_res"] == "44" and boxes["domestic_items"] == "36" and boxes["premises"] == "24"


def test_tax_years_quarters_and_the_credit_rate() -> None:
    assert pr.tax_year_of(date(2026, 4, 5)) == "2025-26" and pr.tax_year_of(date(2026, 4, 6)) == "2026-27"
    assert pr.quarter_ends("2026-27") == [date(2026, 7, 5), date(2026, 10, 5), date(2027, 1, 5), date(2027, 4, 5)]
    assert pr.quarter_ends("2026-27", "calendar")[0] == date(2026, 6, 30)
    assert pr.finance_credit_rate("2026-27") == 20 and pr.finance_credit_rate("2027-28") == 22
    with pytest.raises(ValueError):
        pr.tax_year_bounds("2026-28")


def test_finance_credit_is_the_basic_rate_on_the_lowest_limit() -> None:
    # Costs £6,000 + £1,000 brought forward, profits £20,000: all £7,000 relieved, credit £1,400.
    c = pr.finance_credit("2026-27", 600_000, 100_000, 2_000_000, None)
    assert (c.relieved, c.credit, c.carried_forward) == (700_000, 140_000, 0)
    assert "third limit is not applied" in c.note
    # Profits only £5,000: £5,000 relieved, £2,000 carried forward.
    c = pr.finance_credit("2026-27", 600_000, 100_000, 500_000, None)
    assert (c.relieved, c.credit, c.carried_forward) == (500_000, 100_000, 200_000)
    # Income above the personal allowance £3,000 is lower still.
    c = pr.finance_credit("2026-27", 600_000, 0, 2_000_000, 300_000)
    assert (c.relieved, c.credit) == (300_000, 60_000)
    # 2027-28: the property basic rate, 22 %.
    assert pr.finance_credit("2027-28", 100_000, 0, 1_000_000, None).credit == 22_000


# --------------------------------------------------------------------------- #
# Through the routes
# --------------------------------------------------------------------------- #


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
async def books(fake: FakeStorageProvider) -> Books:
    return Books(fake)


@pytest.fixture
def client(books: Books, monkeypatch: pytest.MonkeyPatch):
    from app import routes_property
    from app.main import app
    from app.routes_books import get_books

    async def override() -> Books:
        return books

    monkeypatch.setattr(routes_property, "current_date", lambda: TODAY)
    app.dependency_overrides[get_books] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _add(client: TestClient, **body) -> dict:
    r = client.post("/property/properties", headers=H, json={"name": "Flat 1", **body})
    assert r.status_code == 201, r.text
    return r.json()


def _entry(client: TestClient, pid: str, d: str, cat: str, pence: int, **kw) -> dict:
    r = client.post(
        "/property/entries",
        headers=H,
        json={"property_id": pid, "date": d, "category": cat, "amount_pence": pence, "description": cat, **kw},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_two_properties_split_owners_and_hmrc_bodies(client: TestClient) -> None:
    flat = _add(client, name="Flat 1", postcode="LS6 2AB")
    house = _add(
        client,
        name="12 Oak Road",
        joint="spouses",
        owners=[{"name": "Lee", "share_bp": 7000, "me": True}, {"name": "Sam", "share_bp": 3000}],
    )
    for d in ("2026-04-10", "2026-05-10", "2026-06-10"):
        _entry(client, flat["id"], d, "rents", 95_000)
        _entry(client, house["id"], d, "rents", 120_001)
    _entry(client, flat["id"], "2026-05-02", "repairs", 18_000)
    _entry(client, flat["id"], "2026-05-03", "premises", 32_000)
    _entry(client, house["id"], "2026-06-01", "finance_res", 45_000)  # mortgage interest
    _entry(client, house["id"], "2026-06-02", "domestic_items", 39_999, replacing_existing_item=True)
    _entry(client, house["id"], "2026-08-01", "rents", 120_000)  # after the first quarter

    s = client.get("/property/summary?tax_year=2026-27&to=2026-07-05", headers=H).json()
    by = {p["name"]: p for p in s["properties"]}
    assert by["Flat 1"]["whole"]["income"] == 285_000 and by["Flat 1"]["my_share_bp"] == pr.WHOLE
    oak = by["12 Oak Road"]
    assert oak["my_share_bp"] == 5000  # spouses without Form 17: 50:50 whatever the stated 70/30
    assert sum(o["income"] for o in oak["owners"]) == oak["whole"]["income"] == 360_003
    assert {o["name"]: o["income"] for o in oak["owners"]} == {"Lee": 180_002, "Sam": 180_001}
    assert any("Form 17" in w for w in s["warnings"])
    mine = s["mine"]
    assert mine["income"] == 285_000 + 180_002
    assert mine["expenses"] == 18_000 + 32_000  # finance costs and domestic items are not expenses
    assert mine["finance_res"] == 22_500 and mine["domestic_items"] == 20_000  # 39,999 split 20,000 / 19,999
    assert s["finance"]["credit"] == 4_500  # 20 % of £225
    assert s["finance"]["rate_percent"] == 20

    m = client.get("/property/mtd/2026-27?to=2026-07-05", headers=H).json()
    body = m["cumulative"]
    assert body["fromDate"] == "2026-04-06" and body["toDate"] == "2026-07-05"
    assert body["ukProperty"]["income"] == {"periodAmount": 4650.02}
    exp = body["ukProperty"]["expenses"]
    assert exp == {"premisesRunningCosts": 320.0, "repairsAndMaintenance": 180.0, "residentialFinancialCost": 225.0}
    assert m["annual"] == {"ukProperty": {"allowances": {"costOfReplacingDomesticItems": 200.0}}}
    boxes = {b["box"]: b["pence"] for b in m["sa105"]}
    assert boxes["20"] == 465_002 and boxes["44"] == 22_500 and boxes["36"] == 20_000 and boxes["25"] == 18_000

    # Without `to`, the latest quarter that has ended (TODAY is 28 Oct 2026: the one ending 5 Oct).
    m = client.get("/property/mtd/2026-27", headers=H).json()
    assert m["period_end"] == "2026-10-05" and m["cumulative"]["ukProperty"]["income"]["periodAmount"] == 5250.02


def test_consolidated_expenses_and_brought_forward(client: TestClient) -> None:
    flat = _add(client)
    _entry(client, flat["id"], "2026-04-20", "rents", 100_000)
    _entry(client, flat["id"], "2026-04-21", "repairs", 10_000)
    _entry(client, flat["id"], "2026-04-22", "professional", 5_000)
    _entry(client, flat["id"], "2026-04-23", "finance_res", 30_000)
    r = client.put(
        "/property/settings",
        headers=H,
        json={"landlord_mode": True, "consolidated_expenses": True, "finance_brought_forward": {"2026-27": 12_345}},
    )
    assert r.status_code == 200 and r.json()["landlord_mode"] is True
    m = client.get("/property/mtd/2026-27?to=2026-07-05", headers=H).json()
    assert m["consolidated_allowed"] is True
    assert m["cumulative"]["ukProperty"]["expenses"] == {
        "consolidatedExpenses": 150.0,
        "residentialFinancialCost": 300.0,
        "residentialFinancialCostsCarriedForward": 123.45,
    }
    f = m["summary"]["finance"]
    assert f["relieved"] == 42_345 and f["credit"] == 8_469  # 20 % of £423.45, rounded down to the penny
    assert client.put("/property/settings", headers=H, json={"finance_brought_forward": {"2026": 1}}).status_code == 422


def test_rent_a_room_cap_and_its_expenses(client: TestClient) -> None:
    room = _add(client, name="Spare room", use="rent_a_room")
    for month in range(4, 12):
        _entry(client, room["id"], f"2026-{month:02d}-15", "rent_a_room", 100_000)  # £8,000 in the year
    _entry(client, room["id"], "2026-05-01", "other", 20_000)
    s = client.get("/property/summary?tax_year=2026-27", headers=H).json()
    assert s["mine"]["rent_a_room_rents"] == 800_000 and s["rent_a_room_exempt"] == pr.RENT_A_ROOM_LIMIT
    assert s["mine"]["expenses"] == 0  # relief instead of expenses
    assert any("only that much is exempt" in w for w in s["warnings"])
    exp = client.get("/property/mtd/2026-27?to=2027-04-05", headers=H).json()["cumulative"]["ukProperty"]
    assert exp["income"] == {"rentARoom": {"rentsReceived": 8000.0}}
    assert exp["expenses"] == {"rentARoom": {"amountClaimed": 7500.0}}
    # Rent a Room rents only on a room in your own home.
    flat = _add(client, name="Flat 2")
    bad = {"property_id": flat["id"], "date": "2026-05-01", "category": "rent_a_room", "amount_pence": 1}
    assert client.post("/property/entries", headers=H, json={**bad, "description": "x"}).status_code == 409


def test_domestic_items_must_be_a_replacement_on_a_residential_let(client: TestClient) -> None:
    flat = _add(client)
    shop = _add(client, name="Shop unit", use="commercial")
    body = {"date": "2026-05-01", "category": "domestic_items", "amount_pence": 45_000, "description": "Sofa"}
    first = client.post("/property/entries", headers=H, json={**body, "property_id": flat["id"]})
    assert first.status_code == 409 and "first one" in first.json()["detail"]
    commercial = {**body, "property_id": shop["id"], "replacing_existing_item": True}
    assert client.post("/property/entries", headers=H, json=commercial).status_code == 409
    ok = {**body, "property_id": flat["id"], "replacing_existing_item": True}
    assert client.post("/property/entries", headers=H, json=ok).status_code == 201


def test_commercial_finance_costs_are_an_expense(client: TestClient) -> None:
    shop = _add(client, name="Shop unit", use="commercial")
    _entry(client, shop["id"], "2026-04-30", "rents", 200_000)
    e = _entry(client, shop["id"], "2026-05-01", "finance_res", 50_000)
    assert e["category"] == "finance_nonres"
    m = client.get("/property/mtd/2026-27?to=2026-07-05", headers=H).json()
    assert m["cumulative"]["ukProperty"]["expenses"] == {"financialCosts": 500.0}
    assert m["summary"]["finance"]["credit"] == 0


async def test_receipts_tagged_to_a_property_and_undo_follows_the_tag(client: TestClient, books: Books) -> None:
    flat = _add(client)
    _add(client, name="Flat 2")
    ev = LedgerEvent(
        kind="purchase",
        date=date(2026, 5, 5),
        lines=[Line(account="7700 Insurance", debit=24_000), Line(account="2100 Creditors", credit=24_000)],
        approved_by=USER,
        approved_at=now(),
        net=24_000,
        vat=0,
    )
    await books.post_event(ev)
    # An ordinary receipt is not on a property until it is tagged.
    assert client.get("/property/summary?tax_year=2026-27", headers=H).json()["mine"]["expenses"] == 0
    assert client.get("/property/entries?tax_year=2026-27", headers=H).json() == []
    assert client.put(f"/property/tags/{ev.id}", headers=H, json={"property_id": "nope"}).status_code == 409
    assert client.put("/property/tags/missing", headers=H, json={"property_id": flat["id"]}).status_code == 404
    assert client.put(f"/property/tags/{ev.id}", headers=H, json={"property_id": flat["id"]}).status_code == 204
    s = client.get("/property/summary?tax_year=2026-27", headers=H).json()
    assert s["mine"]["by_category"] == {"premises": 24_000}
    listed = client.get("/property/entries?tax_year=2026-27", headers=H).json()
    assert [(e["event_id"], e["category"], e["amount_pence"]) for e in listed] == [(ev.id, "premises", 24_000)]
    # Re-tag it as repairs (a category override), then undo it: the reversal follows the tag and nets to nil.
    client.put(f"/property/tags/{ev.id}", headers=H, json={"property_id": flat["id"], "category": "repairs"})
    assert client.get("/property/summary?tax_year=2026-27", headers=H).json()["mine"]["by_category"] == {
        "repairs": 24_000
    }
    undo = LedgerEvent(
        kind="reversal",
        date=date(2026, 5, 6),
        lines=[Line(account="2100 Creditors", debit=24_000), Line(account="7700 Insurance", credit=24_000)],
        approved_by=USER,
        approved_at=now(),
        reverses=ev.id,
        net=24_000,
        vat=0,
    )
    await books.post_event(undo)
    s = client.get("/property/summary?tax_year=2026-27", headers=H).json()
    assert s["mine"]["by_category"] == {"repairs": 0}
    assert client.get("/property/entries?tax_year=2026-27", headers=H).json()[0]["undone"] is True
    assert client.put(f"/property/tags/{undo.id}", headers=H, json={"property_id": flat["id"]}).status_code == 409
    assert client.delete(f"/property/tags/{ev.id}", headers=H).status_code == 204


def test_untagged_property_account_entries(client: TestClient, books: Books) -> None:
    a = _add(client, name="A")
    entry = _entry(client, a["id"], "2026-04-30", "rents", 50_000)
    client.delete(f"/property/tags/{entry['event_id']}", headers=H)
    # One property: an untagged entry on a property account goes to it.
    s = client.get("/property/summary?tax_year=2026-27", headers=H).json()
    assert s["properties"][0]["whole"]["income"] == 50_000 and not s["unallocated"]["by_category"]
    # Two properties: it is unallocated, counted as 100 % yours, with a warning.
    _add(client, name="B")
    s = client.get("/property/summary?tax_year=2026-27", headers=H).json()
    assert s["unallocated"]["income"] == 50_000 and s["mine"]["income"] == 50_000
    assert any("not tagged" in w for w in s["warnings"])


def test_years_before_2025_26_and_holiday_lets(client: TestClient) -> None:
    assert client.get("/property/summary?tax_year=2024-25", headers=H).status_code == 422
    assert client.get("/property/mtd/2024-25", headers=H).status_code == 422
    assert client.get("/property/summary?tax_year=2026-28", headers=H).status_code == 422
    _add(client, name="Seaview cottage", holiday_let=True, furnished=True)
    s = client.get("/property/summary?tax_year=2025-26", headers=H).json()
    assert any("6 April 2025" in w for w in s["warnings"])


def test_property_allowance_comparison(client: TestClient) -> None:
    flat = _add(client)
    _entry(client, flat["id"], "2026-04-30", "rents", 400_000)
    _entry(client, flat["id"], "2026-05-01", "other", 30_000)
    a = client.get("/property/summary?tax_year=2026-27", headers=H).json()["allowance"]
    assert a["better"] == "property_allowance" and a["expenses_claimed"] == 30_000
    _entry(client, flat["id"], "2026-05-02", "repairs", 200_000)
    assert client.get("/property/summary?tax_year=2026-27", headers=H).json()["allowance"]["better"] == "expenses"


async def test_export_file_and_sandbox_submission_record(client: TestClient, fake: FakeStorageProvider) -> None:
    flat = _add(client)
    _entry(client, flat["id"], "2026-04-30", "rents", 100_000)
    r = client.post("/property/mtd/2026-27/export", headers=H, json={"to": "2026-07-05"})
    assert r.status_code == 200, r.text
    path = r.json()["path"]
    assert path.startswith(f"{REPORTS}/2026-10-28-uk-property-2026-27-to-2026-07-05")
    doc = json.loads(await fake.read(path))
    assert doc["cumulative_period_summary"]["body"]["ukProperty"]["income"] == {"periodAmount": 1000.0}
    assert doc["cumulative_period_summary"]["path"].endswith("/cumulative/2026-27")
    sent = client.get("/property/mtd/2026-27?to=2026-07-05", headers=H).json()["cumulative"]
    rec = {
        "tax_year": "2026-27",
        "kind": "cumulative",
        "period_end": "2026-07-05",
        "business_id": "XPIS12345678901",
        "sent": sent,
        "status": 204,
        "correlation_id": "c-1",
    }
    out = client.post("/property/submissions", headers=H, json=rec)
    assert out.status_code == 201 and out.json()["matched_books"] is True
    changed = {**rec, "sent": {**sent, "toDate": "2026-07-04"}}
    assert client.post("/property/submissions", headers=H, json=changed).json()["matched_books"] is False
    assert client.post("/property/submissions", headers=H, json={**rec, "sandbox": False}).status_code == 422
    listed = client.get("/property/submissions?tax_year=2026-27", headers=H).json()
    assert [s["matched_books"] for s in listed] == [False, True]
    audit = client.get("/audit?from=2026-01-01&to=2030-01-01", headers=H)
    if audit.status_code == 200:  # the audit route reads London days; the summaries are what matter here
        kinds = {e["event"] for e in audit.json()}
        assert {"property_added", "property_entry", "property_mtd_exported", "property_mtd_submitted"} <= kinds


def test_writes_need_a_user_and_the_register_round_trips(client: TestClient) -> None:
    assert client.post("/property/properties", headers={"X-Graph-Token": "t"}, json={"name": "x"}).status_code == 400
    p = _add(client)
    upd = client.put(f"/property/properties/{p['id']}", headers=H, json={"name": "Flat 1A", "furnished": True})
    assert upd.status_code == 200 and upd.json()["created_at"] == p["created_at"]
    assert client.put("/property/properties/nope", headers=H, json={"name": "x"}).status_code == 404
    assert [x["name"] for x in client.get("/property/properties", headers=H).json()] == ["Flat 1A"]
    assert client.post("/property/properties", headers=H, json={"name": "x", "extra": 1}).status_code == 422
    cats = client.get("/property/categories", headers=H).json()
    assert {c["key"] for c in cats} == set(pr.BY_KEY)
