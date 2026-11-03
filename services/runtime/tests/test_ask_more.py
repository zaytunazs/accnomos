"""Ask's aged-balance and household answers (app/ask_more.py), on the demo books: the same figures as Home."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import ask_more
from app import contacts as cb
from app import demo_personal as dp
from app.books import Books
from app.schemas import AskPeriod

DAY = date(2026, 11, 3)
PERIOD = AskPeriod(start=date(2026, 10, 1), end=date(2026, 12, 31))


@pytest.mark.parametrize(
    ("question", "side"),
    [
        ("Who owes me the most?", "debtors"),
        ("which customers haven't paid?", "debtors"),
        ("show my overdue invoices", "debtors"),
        ("Who do I owe the most?", "creditors"),
        ("any unpaid bills?", "creditors"),
        ("how much VAT do I owe?", None),
        ("what do I owe HMRC?", None),
        ("what were my sales last quarter?", None),
    ],
)
def test_owed_intent(question: str, side: str | None) -> None:
    assert ask_more.owed_intent(question) == side


@pytest.fixture(scope="module")
def company() -> Books:
    import asyncio

    from app import demo

    return Books(asyncio.run(demo.build_full(DAY)).storage)


async def test_who_owes_me_matches_the_aged_balances(company: Books) -> None:
    contacts, ledger, _ = await cb.contact_book(company)
    table = cb.aged(contacts, ledger, DAY).debtors
    top = max(table.rows, key=lambda r: r.total_pence)
    a = await ask_more.owed_answer("Who owes me the most?", "debtors", company, None, PERIOD, DAY)
    assert a.model == "code" and a.fallback_reason == "No AI is set up, so code wrote this."
    assert a.answer_md.startswith(f"{top.name} owes you the most: £{top.total_pence / 100:,.2f}")
    assert a.key_numbers[0].value == f"£{table.total_pence / 100:,.2f}"
    assert "VAT" not in a.answer_md


async def test_household_spending_question_uses_bank_lines_never_vat() -> None:
    books = Books(await dp.build_storage(DAY))
    a = await ask_more.household_answer("How much did I spend on coffee this month?", books, None, PERIOD, DAY)
    assert a.answer_md.startswith("You spent £") and "on coffee in November 2026 so far" in a.answer_md
    assert "October 2026" in a.answer_md and "VAT" not in a.answer_md and "Box" not in a.answer_md
    general = await ask_more.household_answer("how am I doing this month?", books, None, PERIOD, DAY)
    assert general.answer_md.startswith("In November 2026 so far,") and "VAT" not in general.answer_md
    nothing = await ask_more.household_answer("how much on skydiving?", books, None, PERIOD, DAY)
    assert "Nothing on your bank statements matches" in nothing.answer_md


def test_focus_words() -> None:
    names = ["Groceries", "Eating out", "Coffee & snacks"]
    assert ask_more.focus_of("How much did I spend on coffee this month?", names) == "coffee"
    assert ask_more.focus_of("what did I spend on eating out last month", names) == "Eating out"
    assert ask_more.focus_of("how much at Tesco?", names) == "Tesco"
    assert ask_more.focus_of("how am I doing?", names) is None


def test_model_words_are_checked() -> None:
    facts = {"total_outstanding": "£1,234.50"}
    assert ask_more.check("Customers owe you £1,234.50.", facts) is None
    assert "not in your books" in (ask_more.check("Customers owe you £1,999.00.", facts) or "")
    assert ask_more.check("See https://x.example", facts) == "The model's answer contained a link."


def test_ask_route_sends_a_household_question_to_its_bank_lines() -> None:
    import asyncio

    from app.ai.config import ai_config_from_request
    from app.main import app
    from app.routes_actions import graph_token
    from app.routes_books import get_books

    books = Books(asyncio.run(dp.build_storage(DAY)))

    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    app.dependency_overrides[ai_config_from_request] = lambda: None
    app.dependency_overrides[graph_token] = lambda: "t"
    try:
        r = TestClient(app).post(
            "/books/ask",
            headers={"X-Graph-Token": "t"},
            json={"question": "How much did I spend on coffee this month?"},
        )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    body = r.json()
    assert "coffee" in body["answer_md"] and "VAT" not in body["answer_md"]
