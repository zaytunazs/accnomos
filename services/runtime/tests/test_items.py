"""Products and services: the catalogue, filling a line from an item, CSV import and export (app/items.py)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app import items as it_
from app.books import AUDIT, Books
from app.items import ItemError, ItemIn

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
ITEM = {
    "code": "lab-01",
    "name": "Labour",
    "description": "Labour, per hour",
    "unit": "hours",
    "sale_price_pence": 4500,
    "purchase_price_pence": 2500,
    "vat_code": "S",
    "income_account": "4000 Sales",
    "expense_account": "5000 Materials",
}


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
def books(fake: FakeStorageProvider) -> Books:
    return Books(fake)


@pytest.fixture
def client(books: Books):
    from app.main import app
    from app.routes_books import get_books

    async def over_books() -> Books:
        return books

    app.dependency_overrides[get_books] = over_books
    yield TestClient(app)
    app.dependency_overrides.clear()


def _audit(fake: FakeStorageProvider) -> list[str]:
    return [
        json.loads(x)["action"]
        for p, d in sorted(fake.files.items())
        if p.startswith(f"{AUDIT}/") and p.endswith(".jsonl")
        for x in d.decode().splitlines()
    ]


async def test_create_normalises_the_code_and_lists_by_code(books: Books, fake: FakeStorageProvider):
    await it_.create_item(books, ItemIn(**{**ITEM, "code": "zz-9"}), USER)
    made = await it_.create_item(books, ItemIn(**ITEM), USER)
    assert made.code == "LAB-01"
    assert [i.code for i in await it_.load_items(books)] == ["LAB-01", "ZZ-9"]
    assert _audit(fake).count("item_created") == 2


async def test_duplicate_code_is_refused(books: Books):
    await it_.create_item(books, ItemIn(**ITEM), USER)
    with pytest.raises(ItemError, match="already an item"):
        await it_.create_item(books, ItemIn(**{**ITEM, "code": "LAB-01", "name": "Other"}), USER)


def test_bad_accounts_and_codes_are_refused():
    for bad in ({"code": "has space"}, {"income_account": "7500 Office supplies"}, {"expense_account": "1200 Bank"}):
        with pytest.raises(ValueError):
            ItemIn(**{**ITEM, **bad})


async def test_picking_an_item_fills_the_line_for_each_side(books: Books):
    item = await it_.create_item(books, ItemIn(**ITEM), USER)
    sale = it_.fill_line(item, "sale", "2.5")
    assert (sale.description, sale.unit, sale.quantity, sale.unit_price_pence, sale.vat_code, sale.account) == (
        "Labour, per hour",
        "hours",
        "2.5",
        4500,
        "S",
        "4000 Sales",
    )
    buy = it_.fill_line(item, "purchase")
    assert (buy.unit_price_pence, buy.account, buy.item_code) == (2500, "5000 Materials", "LAB-01")


async def test_an_item_without_a_price_for_that_side_leaves_it_blank(books: Books):
    item = await it_.create_item(books, ItemIn(**{**ITEM, "purchase_price_pence": None, "description": None}), USER)
    fill = it_.fill_line(item, "purchase")
    assert fill.unit_price_pence is None
    assert fill.description == "Labour"  # the name when there is no description


async def test_edit_keeps_created_at_and_cannot_change_the_code(books: Books):
    item = await it_.create_item(books, ItemIn(**ITEM), USER)
    changed = await it_.update_item(books, "lab-01", ItemIn(**{**ITEM, "sale_price_pence": 5000}), USER)
    assert changed.sale_price_pence == 5000 and changed.created_at == item.created_at
    with pytest.raises(ItemError, match="cannot change"):
        await it_.update_item(books, "LAB-01", ItemIn(**{**ITEM, "code": "OTHER"}), USER)


async def test_archived_items_are_hidden_until_asked_for_and_can_be_restored(books: Books):
    await it_.create_item(books, ItemIn(**ITEM), USER)
    await it_.archive_item(books, "LAB-01", USER)
    assert await it_.load_items(books, include_archived=False) == []
    assert (await it_.get_item(books, "LAB-01")).archived is True
    await it_.archive_item(books, "LAB-01", USER, archived=False)
    assert len(await it_.load_items(books, include_archived=False)) == 1


async def test_csv_round_trip_keeps_every_penny(books: Books):
    await it_.create_item(books, ItemIn(**ITEM), USER)
    await it_.create_item(
        books,
        ItemIn(**{**ITEM, "code": "BOLT", "name": "=Bolt, M8", "sale_price_pence": 7, "purchase_price_pence": None}),
        USER,
    )
    text = it_.export_csv(await it_.load_items(books))
    assert text.splitlines()[0] == ",".join(it_.COLUMNS)
    assert "0.07" in text and "45.00" in text
    # a fresh book reading our own export gets the same items (the formula guard's apostrophe stays on the name)
    other = Books(FakeStorageProvider())
    res = await it_.import_csv(other, text, USER)
    assert (res.created, res.updated, res.skipped) == (2, 0, 0)
    got = {i.code: i for i in await it_.load_items(other)}
    assert (
        got["LAB-01"].model_dump(exclude={"created_at", "updated_at"})
        == ItemIn(**{**ITEM, "code": "LAB-01"}).model_dump()
    )
    assert got["BOLT"].sale_price_pence == 7 and got["BOLT"].purchase_price_pence is None


async def test_import_reads_a_xero_inventory_export_and_reports_bad_rows(books: Books, fake: FakeStorageProvider):
    xero = (
        "*ItemCode,ItemName,PurchasesDescription,PurchasesUnitPrice,PurchasesAccount,PurchasesTaxRate,"
        "SalesDescription,SalesUnitPrice,SalesAccount,SalesTaxRate\r\n"
        "PAINT-5L,Paint 5L,Paint,12.50,5000 Materials,20% (VAT on Expenses),"
        "White paint 5L,24.99,4000 Sales,20% (VAT on Income)\r\n"
        "BOOK,Book,,,,,A book,10,,Zero Rated\r\n"
        ",No code,,,,,,,,\r\n"
        "BAD-PRICE,Bad,,,,,,1.234,,\r\n"
    )
    res = await it_.import_csv(books, xero, USER)
    assert (res.created, res.updated, res.skipped) == (2, 0, 2)
    assert [(e.line, e.code) for e in res.errors] == [(4, None), (5, "BAD-PRICE")]
    paint = await it_.get_item(books, "paint-5l")
    assert (paint.sale_price_pence, paint.purchase_price_pence, paint.vat_code) == (2499, 1250, "S")
    assert paint.description == "White paint 5L"
    assert (await it_.get_item(books, "BOOK")).vat_code == "Z"
    assert "items_imported" in _audit(fake)


async def test_import_updates_or_skips_existing_codes(books: Books):
    await it_.create_item(books, ItemIn(**ITEM), USER)
    text = "code,name,sale_price\nLAB-01,Labour (new),50.00\nNEW-1,New thing,1.00\n"
    res = await it_.import_csv(books, text, USER, update_existing=False)
    assert (res.created, res.updated, res.skipped) == (1, 0, 1)
    assert (await it_.get_item(books, "LAB-01")).sale_price_pence == 4500
    res = await it_.import_csv(books, text, USER)
    assert (res.created, res.updated) == (0, 2)
    assert (await it_.get_item(books, "LAB-01")).name == "Labour (new)"


async def test_import_refuses_a_file_that_is_not_an_item_list(books: Books):
    with pytest.raises(ItemError, match="name the columns"):
        await it_.import_csv(books, "foo,bar\n1,2\n", USER)
    with pytest.raises(ItemError, match="empty"):
        await it_.import_csv(books, "", USER)


def test_routes_create_list_fill_export_import_archive(client: TestClient):
    r = client.post("/items", headers=H, json=ITEM)
    assert r.status_code == 200 and r.json()["code"] == "LAB-01"
    assert client.post("/items", headers=H, json=ITEM).status_code == 400
    assert client.post("/items", json=ITEM).status_code in (400, 401, 422)  # X-User is required
    assert [i["code"] for i in client.get("/items", headers=H).json()] == ["LAB-01"]
    fill = client.get("/items/lab-01/line?side=purchase&quantity=3", headers=H).json()
    assert (fill["quantity"], fill["unit_price_pence"], fill["account"]) == ("3", 2500, "5000 Materials")
    assert client.get("/items/lab-01/line?quantity=0", headers=H).status_code == 400
    assert client.get("/items/lab-01/line?quantity=1.2345", headers=H).status_code == 400
    assert client.get("/items/NOPE", headers=H).status_code == 404
    exported = client.get("/items/export", headers=H).json()
    assert exported["filename"].startswith("accnomos-items-") and "LAB-01" in exported["csv"]
    imported = client.post("/items/import", headers=H, json={"csv": "code,name\nA-1,Alpha\n"}).json()
    assert imported["created"] == 1
    assert client.post("/items/import", headers=H, json={"csv": "nope"}).status_code == 400
    assert client.delete("/items/A-1", headers=H).json()["archived"] is True
    assert [i["code"] for i in client.get("/items", headers=H).json()] == ["LAB-01"]
    assert [i["code"] for i in client.get("/items?archived=true", headers=H).json()] == ["A-1", "LAB-01"]
    assert client.put("/items/LAB-01", headers=H, json={**ITEM, "sale_price_pence": 12.5}).status_code == 422
