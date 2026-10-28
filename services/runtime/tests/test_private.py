"""Private spending on bank lines: a 0 % business-use proposal approved through Review.

Approving posts Dr Drawings (sole trader) or Dr Director's loan (company, read from the invoice
profile) against Cr 1200 Bank: nothing to expenses, never any VAT.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app.books import Books
from app.invoicing import InvoiceProfile, save_profile
from app.journal import DRAWINGS, OWNER_LOAN

USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}

CSV = (
    "Date,Description,Reference,Amount (GBP),Balance (GBP)\n"
    "2026-10-21,Tesco Superstore,groceries,-38.47,1000.00\n"
    "2026-10-22,Acme payroll,october pay,1200.00,2200.00\n"
)


@pytest.fixture
async def books() -> Books:
    return Books(FakeStorageProvider())


@pytest.fixture
def client(books: Books):
    from app.main import app
    from app.routes_books import get_books

    async def override() -> Books:
        return books

    app.dependency_overrides[get_books] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _import(client: TestClient) -> None:
    r = client.post("/books/bank/import", headers=H, files={"file": ("statement.csv", CSV, "text/csv")})
    assert r.status_code == 200, r.text


def _money_out(client: TestClient) -> dict:
    r = client.get("/books/bank/lines", headers=H)
    assert r.status_code == 200, r.text
    return next(ln for ln in r.json() if ln["amount_pence"] < 0)


def _money_in(client: TestClient) -> dict:
    r = client.get("/books/bank/lines", headers=H)
    assert r.status_code == 200, r.text
    return next(ln for ln in r.json() if ln["amount_pence"] > 0)


def _approve(client: TestClient, proposal_id: str) -> dict:
    r = client.post(f"/books/proposals/{proposal_id}/approve", headers=H, json={})
    assert r.status_code == 200, r.text
    return r.json()


def test_private_posts_to_drawings_with_no_vat(client: TestClient) -> None:
    """Sole trader (no company number in the profile): Dr 3000 Drawings, Cr 1200 Bank, no VAT."""
    _import(client)
    line = _money_out(client)
    r = client.post(f"/books/bank/lines/{line['id']}/private-proposal", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["business_use_percent"] == 0
    posted = _approve(client, r.json()["id"])
    assert posted["status"] == "posted"
    journal = {j["account"]: j for j in posted["journal_draft"]}
    assert set(journal) == {DRAWINGS, "1200 Bank"}
    assert journal[DRAWINGS]["debit_pence"] == 3847
    assert journal["1200 Bank"]["credit_pence"] == 3847
    assert sum(j["debit_pence"] for j in posted["journal_draft"]) == sum(
        j["credit_pence"] for j in posted["journal_draft"]
    )


async def test_private_company_posts_to_directors_loan(books: Books, client: TestClient) -> None:
    """Company number set in the invoice profile: Dr 2300 Owner / director loan instead."""
    await save_profile(books, InvoiceProfile(name="Acme Ltd", company_number="12345678"), USER)
    _import(client)
    line = _money_out(client)
    r = client.post(f"/books/bank/lines/{line['id']}/private-proposal", headers=H)
    assert r.status_code == 200, r.text
    posted = _approve(client, r.json()["id"])
    journal = {j["account"]: j for j in posted["journal_draft"]}
    assert set(journal) == {OWNER_LOAN, "1200 Bank"}
    assert journal[OWNER_LOAN]["debit_pence"] == 3847


def test_private_money_in_is_refused(client: TestClient) -> None:
    _import(client)
    line = _money_in(client)
    r = client.post(f"/books/bank/lines/{line['id']}/private-proposal", headers=H)
    assert r.status_code == 409, r.text


def test_private_settled_line_is_refused(client: TestClient) -> None:
    _import(client)
    line = _money_out(client)
    r = client.post(f"/books/bank/lines/{line['id']}/transfer", headers=H)
    assert r.status_code == 200, r.text
    r = client.post(f"/books/bank/lines/{line['id']}/private-proposal", headers=H)
    assert r.status_code == 409, r.text


def test_private_asking_twice_returns_the_first(client: TestClient) -> None:
    _import(client)
    line = _money_out(client)
    first = client.post(f"/books/bank/lines/{line['id']}/private-proposal", headers=H)
    second = client.post(f"/books/bank/lines/{line['id']}/private-proposal", headers=H)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
