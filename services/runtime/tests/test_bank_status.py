"""One bank status on every screen (app/bank_status.py): business books against the ledger, personal books by the
household rules, with each line's household category on GET /books/bank/lines."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from accnomos_ledger.bank import BankLine
from app import bank_status, demo_personal
from app import dashboard as dash
from app.books import Books

DAY = date(2026, 11, 3)
H = {"X-Graph-Token": "tok", "X-User": "sam@example.co.uk"}


def line(n: int, status: str, pence: int = -1000, desc: str = "SHOP") -> BankLine:
    return BankLine(id=f"{n:016x}", date=DAY, amount_pence=pence, description=desc, source_file="x.csv", status=status)  # type: ignore[arg-type]


def test_ledger_status_counts_suggested_lines_as_open() -> None:
    lines = [line(1, "matched"), line(2, "transfer"), line(3, "ignored"), line(4, "suggested"), line(5, "unmatched")]
    s = bank_status.status(lines)
    assert (s.basis, s.total, s.resolved, s.open, s.suggested, s.unmatched) == ("ledger", 5, 3, 2, 1, 1)
    assert s.label == "3 of 5 lines resolved" and s.open_label == "2 lines to match"
    assert bank_status.status(lines[:3]).open_label == "All matched"


@pytest.fixture
async def household_books() -> Books:
    return Books(await demo_personal.build_storage(DAY))


@pytest.fixture
def client(household_books: Books):
    from app.main import app
    from app.routes_books import get_books

    async def override() -> Books:
        return household_books

    app.dependency_overrides[get_books] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


async def test_personal_books_are_sorted_by_household_rules_on_every_screen(
    client: TestClient, household_books: Books
) -> None:
    summary = client.get("/books/bank/summary", headers=H).json()
    assert summary["basis"] == "household" and summary["total"] > 700
    assert summary["open"] == summary["total"] - summary["resolved"]
    assert summary["label"] == f"{summary['resolved']} of {summary['total']} lines sorted"
    statements = client.get("/books/bank/statements", headers=H).json()
    assert sum(s["resolved"] for s in statements) == summary["resolved"]
    assert all(s["basis"] == "household" and s["label"].endswith("lines sorted") for s in statements)
    home = await dash.build(household_books, DAY, 1, 3)
    assert home.attention is not None and home.attention.unmatched_bank_lines == summary["open"]

    lines = client.get("/books/bank/lines", headers=H).json()
    assert len(lines) == summary["total"]
    coffee = next(ln for ln in lines if "COSTA" in ln["description"].upper())
    assert coffee["household_sorted"] is True and coffee["household_source"] == "rule"
    assert coffee["household_category"] and coffee["household_category_id"]
    pay = next(ln for ln in lines if ln["amount_pence"] > 0)
    assert pay["household_category"] == "Income" and pay["household_source"] == "income"
    open_lines = client.get("/books/bank/lines?open=true", headers=H).json()
    assert len(open_lines) == summary["open"]
    assert all(ln["household_sorted"] is False and ln["household_category"] == "Other" for ln in open_lines)
    assert len(client.get("/books/bank/lines?open=false", headers=H).json()) == summary["resolved"]
