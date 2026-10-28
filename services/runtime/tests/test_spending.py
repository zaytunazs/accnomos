"""Spending summary: the facts code computes (categories, suppliers, items, changes, recurring, one-offs), the
number check on the model's words (Ask's KnownNumbers and wrong_period), the fallback, the route and Ask's entry."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app import spending
from app.ai import ask as ask_ai
from app.ai import spending as spending_ai
from app.ai.config import AiConfig
from app.books import Books
from app.sample_purchases import seed_purchases
from app.schemas import AskPeriod

CFG = AiConfig(mode="local", base_url="http://ollama.invalid", model="stub-model")
OCT = AskPeriod(start=date(2026, 10, 1), end=date(2026, 10, 31))
H = {"X-Graph-Token": "tok", "X-User": "sam@example.co.uk", "X-AI-Mode": "local", "X-AI-Model": "stub-model"}


@pytest.fixture
async def books() -> Books:
    b = Books(FakeStorageProvider())
    await seed_purchases(b)
    return b


@pytest.fixture
async def facts(books: Books) -> dict[str, Any]:
    return await spending.build(books, OCT, "Sam Builds Ltd")


def reply(monkeypatch: pytest.MonkeyPatch, text: str | Exception) -> list:
    seen: list = []

    async def fake(messages, cfg, schema, name):  # noqa: ANN001, ANN202
        seen.append((messages, name))
        if isinstance(text, Exception):
            raise text
        return text

    monkeypatch.setattr(ask_ai, "call_json_model", fake)
    return seen


def explanation(md: str) -> str:
    import json

    return json.dumps({"answer_md": md, "confidence": "high"})


# --------------------------------------------------------------------------- #
# Facts
# --------------------------------------------------------------------------- #


async def test_summary_facts(facts: dict[str, Any]):
    t, prev, ch = facts["this_period"], facts["previous_period"], facts["change"]
    assert (t["label"], prev["label"]) == ("Oct 2026", "Sep 2026")
    # Oct: Cloudnine 12 + Parcelworks 36.60 + Boxmart 28.40 + Brightwater 38 + Harbour 289
    assert (t["spent"], t["purchases"], t["vat"]) == ("404.00", 5, "73.20")
    # Sep: Cloudnine 12 + Parcelworks 11.40 + Brightwater 38
    assert (prev["spent"], prev["purchases"]) == ("61.40", 3)
    assert ch == {"spent_vs_previous": "342.60", "spent_change_pct": "558.0"}
    cats = {c["name"]: c for c in t["by_category"]}
    assert cats["Materials"]["net"] == "65.00" and cats["Materials"]["change_vs_previous"] == "53.60"
    assert cats["Utilities"]["change_pct"] == "0.0" and cats["Tools & small equipment"]["change_pct"] is None
    assert [s["name"] for s in t["by_supplier"]][:2] == ["Harbour Tools Ltd", "Brightwater Utilities Ltd"]
    assert t["top_items"][0] == {
        "item": "Mitre saw 254mm",
        "net": "289.00",
        "quantity": "1",
        "suppliers": ["Harbour Tools Ltd"],
    }
    assert t["with_line_items"] == 5


async def test_recurring_and_unusual(facts: dict[str, Any]):
    regular = {r["supplier"]: r for r in facts["recurring"]}
    assert regular["Cloudnine Software Ltd"] == {
        "supplier": "Cloudnine Software Ltd",
        "kind": "subscription",
        "category": "Software & subscriptions",
        "months_seen": 5,
        "usual_month": "12.00",
        "this_period": "12.00",
    }
    assert regular["Brightwater Utilities Ltd"]["kind"] == "utility"
    assert regular["Parcelworks Supplies Ltd"]["kind"] == "regular"  # bought in 4 months
    assert "Boxmart Ltd" not in regular  # two months, not a regular kind of cost
    [one_off] = facts["unusual"]
    assert one_off["supplier"] == "Harbour Tools Ltd" and one_off["net"] == "289.00"
    assert "new to your books" in one_off["why"] and float(one_off["times_usual_purchase"]) >= 3


def test_no_history_flags_no_one_offs():
    big = spending.Purchase("e", date(2026, 10, 2), "A", "Materials", 50_000, 0, "x")
    assert spending.unusual([big], OCT, set()) == []


async def test_credit_notes_reduce_spend(books: Books):
    from datetime import UTC, datetime

    from accnomos_ledger import LedgerEvent, Line, VatCode

    await books.post_event(  # a supplier's credit note: a reversal with no `reverses`
        LedgerEvent(
            kind="reversal",
            date=date(2026, 10, 22),
            lines=[
                Line(account="2100 Creditors", debit=12_000),
                Line(account="5100 Tools & small equipment", credit=10_000, vat_code=VatCode.STANDARD),
                Line(account="2200 VAT control", credit=2_000),
            ],
            net=10_000,
            vat=2_000,
            counterparty="Harbour Tools Ltd",
            approved_by="sam@example.co.uk",
            approved_at=datetime(2026, 10, 22, tzinfo=UTC),
        )
    )
    f = await spending.build(books, OCT)
    assert f["this_period"]["spent"] == "304.00"
    assert {c["name"]: c["net"] for c in f["this_period"]["by_category"]}["Tools & small equipment"] == "189.00"


async def test_empty_books():
    f = await spending.build(Books(FakeStorageProvider()), OCT)
    assert f["this_period"]["purchases"] == 0 and f["recurring"] == [] and f["unusual"] == []
    text, by, why = await spending_ai.summarise(f, CFG)  # no model call for nothing
    assert by == "code" and why is None and text == "No approved purchases in Oct 2026 yet."


# --------------------------------------------------------------------------- #
# The model's words, checked
# --------------------------------------------------------------------------- #


def test_code_summary_passes_its_own_check(facts: dict[str, Any]):
    text = spending.code_summary(facts)
    assert "£404.00" in text and "up £342.60 on Sep 2026 (558.0%)" in text and "Harbour Tools Ltd" in text
    assert spending_ai.check(text, facts) is None


@pytest.mark.parametrize(
    ("words", "problem"),
    [
        ("You spent £404.00 in Oct 2026, mostly on tools.", None),
        ("You spent £404 in Oct 2026, up £342.60 (558%).", None),  # whole-pound and whole-percent roundings
        ("You spent £404.00, compared with £61.40 in Sep 2026.", None),  # the previous figure, named
        ("You spent £410.00 this month.", "not in your books (£410.00)"),  # invented
        ("Your average purchase was £80.80.", "not in your books"),  # the model did maths
        ("You spent £61.40 on purchases.", "a figure for Sep 2026"),  # last month's total as this month's
    ],
)
def test_number_check(facts: dict[str, Any], words: str, problem: str | None):
    why = spending_ai.check(words, facts)
    assert (why is None) if problem is None else (why is not None and problem in why), why


async def test_summarise_uses_checked_words(facts: dict[str, Any], monkeypatch: pytest.MonkeyPatch):
    seen = reply(monkeypatch, explanation("You spent £404.00 in Oct 2026; Cloudnine Software Ltd is a regular cost."))
    text, by, why = await spending_ai.summarise(facts, CFG)
    assert (by, why) == ("model", None) and text.startswith("You spent £404.00")
    messages, name = seen[0]
    assert name == "spending_summary" and messages[0]["content"] == spending_ai.SYSTEM_PROMPT
    assert '"spent":"404.00"' in messages[1]["content"]


async def test_summarise_falls_back_to_code(facts: dict[str, Any], monkeypatch: pytest.MonkeyPatch):
    reply(monkeypatch, explanation("You spent about £400 more than usual."))
    text, by, why = await spending_ai.summarise(facts, CFG)
    assert by == "code" and "not in your books" in (why or "") and text == spending.code_summary(facts)
    reply(monkeypatch, "not json")
    assert (await spending_ai.summarise(facts, CFG))[1:] == (
        "code",
        "The model's reply was not in the expected format.",
    )
    reply(monkeypatch, httpx.ConnectError("refused"))
    text, by, why = await spending_ai.summarise(facts, CFG)
    assert by == "code" and "could not be reached" in (why or "")


def test_asks_for_summary():
    for q in ("Summarise my spending this month", "spending summary", "Where did my money go?", "what did I spend on"):
        assert spending.asks_for_summary(q), q
    for q in ("How much VAT do I owe?", "What did I spend with Screwfix?", "Who owes me money?"):
        assert not spending.asks_for_summary(q), q


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


def _client(books: Books):  # noqa: ANN202
    from app.main import app
    from app.routes_books import get_books

    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    return app, TestClient(app)


def test_spending_route(books: Books, monkeypatch: pytest.MonkeyPatch):
    from app import routes_spending

    monkeypatch.setattr(routes_spending, "today", lambda: date(2026, 10, 27))
    reply(monkeypatch, explanation("You spent £404.00 in Oct 2026."))
    app, client = _client(books)
    try:
        default = client.get("/books/spending", headers=H)
        quarter = client.get("/books/spending?start=2026-07-01&end=2026-09-30", headers=H)
        half = client.get("/books/spending?start=2026-07-01", headers=H)
        backwards = client.get("/books/spending?start=2026-09-01&end=2026-08-01", headers=H)
    finally:
        app.dependency_overrides.clear()
    assert default.status_code == 200, default.text
    body = default.json()
    assert body["period"] == {"start": "2026-10-01", "end": "2026-10-31"}
    assert body["previous"] == {"start": "2026-09-01", "end": "2026-09-30"}
    assert body["summary_by"] == "model" and body["model"] == "stub-model"
    assert quarter.json()["facts"]["this_period"]["label"] == "Jul–Sep 2026"
    assert quarter.json()["summary_by"] == "code"  # the stub's £404.00 is not a Jul-Sep figure
    assert half.status_code == 422 and backwards.status_code == 422


def test_ask_summarise_my_spending(books: Books, monkeypatch: pytest.MonkeyPatch):
    reply(monkeypatch, explanation("You spent £404.00 in Oct 2026."))
    app, client = _client(books)
    try:
        r = client.post(
            "/books/ask",
            json={"question": "Summarise my spending", "period": {"start": "2026-10-01", "end": "2026-10-31"}},
            headers=H,
        )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer_md"] == "You spent £404.00 in Oct 2026."
    assert body["key_numbers"][0] == {
        "label": "Spent before VAT, Oct 2026",
        "value": "£404.00",
        "source": "_System/Ledger/events/2026-10/",
    }
    assert body["suggested_actions"] == [{"label": "Open Spending", "kind": "open_spending", "arg": None}]
