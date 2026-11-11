"""POST /ai/grid-filter (the Power grid's ledger explorer): the model only proposes; code keeps what is allowed."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app.ai import grid_filter as gf
from app.ai.config import AiConfig
from app.books import Books

TODAY = date(2026, 11, 11)
CFG = AiConfig(mode="local", base_url="http://127.0.0.1:1", model="stub-model")


def stub(monkeypatch: pytest.MonkeyPatch, reply: Any) -> list[list[dict[str, str]]]:
    seen: list[list[dict[str, str]]] = []

    async def fake(messages: list[dict[str, str]], cfg: AiConfig, schema: dict[str, Any], name: str) -> str:
        seen.append(messages)
        assert name == "grid_filter" and schema["additionalProperties"] is False
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply)

    monkeypatch.setattr(gf, "call_json_model", fake)
    return seen


PAYPAL_FEES = {
    "conditions": [
        {"column": "counterparty", "op": "contains", "value": "PayPal", "value_to": None},
        {"column": "amount", "op": "greaterThan", "value": "5", "value_to": None},
        {"column": "date", "op": "inRange", "value": "2026-10-01", "value_to": "2026-10-31"},
    ],
    "sort": [{"column": "amount", "direction": "desc"}],
    "summary": "PayPal lines over £5 in October 2026, biggest first.",
}


async def test_paypal_fees_over_5_in_october(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = stub(monkeypatch, PAYPAL_FEES)
    r = await gf.grid_filter("ledger", "PayPal fees over £5 in October", TODAY, ["7900 Bank charges"], CFG)
    assert r.fallback_reason is None and r.quick_filter is None and r.model == "stub-model"
    assert r.filter_model == {
        "counterparty": {"filterType": "text", "type": "contains", "filter": "PayPal"},
        "amount": {"filterType": "number", "type": "greaterThan", "filter": 5},
        "date": {
            "filterType": "date",
            "type": "inRange",
            "dateFrom": "2026-10-01 00:00:00",
            "dateTo": "2026-10-31 00:00:00",
        },
    }
    assert r.sort == [{"colId": "amount", "sort": "desc"}]
    assert "TODAY: 2026-11-11" in seen[0][1]["content"] and "7900 Bank charges" in seen[0][1]["content"]


async def test_unknown_columns_operators_and_values_are_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    stub(
        monkeypatch,
        {
            "conditions": [
                {"column": "password", "op": "contains", "value": "x", "value_to": None},
                {"column": "amount", "op": "regex", "value": ".*", "value_to": None},
                {"column": "amount", "op": "greaterThan", "value": "lots", "value_to": None},
                {"column": "date", "op": "inRange", "value": "2026-10-31", "value_to": "2026-10-01"},
                {"column": "date", "op": "equals", "value": "2026-02-30", "value_to": None},
                {"column": "memo", "op": "greaterThan", "value": "5", "value_to": None},
                {"column": "vat_code", "op": "equals", "value": "S", "value_to": None},
            ],
            "sort": [{"column": "__proto__", "direction": "asc"}, {"column": "date", "direction": "asc"}],
            "summary": "x",
        },
    )
    r = await gf.grid_filter("ledger", "anything", TODAY, [], CFG)
    assert r.filter_model == {"vat_code": {"filterType": "text", "type": "equals", "filter": "S"}}
    assert r.sort == [{"colId": "date", "sort": "asc"}]
    assert len(r.dropped) == 7  # six conditions and one sort


async def test_two_conditions_on_a_column_combine_and_a_third_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    cond = {"column": "amount", "op": "greaterThan", "value": "5", "value_to": None}
    stub(
        monkeypatch, {"conditions": [cond, {**cond, "op": "lessThan", "value": "50"}, cond], "sort": [], "summary": "s"}
    )
    r = await gf.grid_filter("ledger", "between 5 and 50", TODAY, [], CFG)
    assert r.filter_model["amount"]["operator"] == "AND" and len(r.filter_model["amount"]["conditions"]) == 2
    assert r.dropped == ["amount (more than 2 conditions)"]


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (RuntimeError("down"), "could not be reached"),
        ("not json", "not in the expected format"),
        ({"conditions": [], "sort": [], "summary": ""}, "found no filter"),
    ],
)
async def test_any_model_trouble_falls_back_to_a_plain_search(
    monkeypatch: pytest.MonkeyPatch, reply: Any, reason: str
) -> None:
    stub(monkeypatch, reply)
    r = await gf.grid_filter("ledger", "  PayPal fees  ", TODAY, [], CFG)
    assert r.filter_model == {} and r.sort == [] and r.quick_filter == "PayPal fees"
    assert reason in (r.fallback_reason or "")


async def test_no_ai_is_a_plain_search() -> None:
    r = await gf.grid_filter("ledger", "PayPal", TODAY, [], None)
    assert r.model == "code" and r.quick_filter == "PayPal" and r.filter_model == {}


# Route ---------------------------------------------------------------------------------------------------------- #


@pytest.fixture
def client():
    from app.main import app
    from app.routes_books import get_books
    from app.routes_plan import optional_ai

    async def books() -> Books:
        return Books(FakeStorageProvider())

    app.dependency_overrides[get_books] = books
    app.dependency_overrides[optional_ai] = lambda: CFG
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_route_returns_the_checked_filter(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    stub(monkeypatch, PAYPAL_FEES)
    r = client.post(
        "/ai/grid-filter", json={"grid": "ledger", "text": "PayPal fees over £5 in October", "today": "2026-11-11"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["filter_model"]["amount"]["filter"] == 5 and r.json()["sort"][0]["colId"] == "amount"


def test_route_refuses_bad_bodies(client: TestClient) -> None:
    assert client.post("/ai/grid-filter", json={"grid": "payroll", "text": "x"}).status_code == 422
    assert client.post("/ai/grid-filter", json={"grid": "ledger", "text": ""}).status_code == 422
    assert client.post("/ai/grid-filter", json={"grid": "ledger", "text": "x" * 301}).status_code == 422
    assert client.post("/ai/grid-filter", json={"grid": "ledger", "text": "x", "write": True}).status_code == 422


def test_route_needs_the_callers_books() -> None:
    from app.main import app

    assert TestClient(app).post("/ai/grid-filter", json={"grid": "ledger", "text": "x"}).status_code in (400, 401, 403)


def test_test_mode_stub_reply_passes_the_checks() -> None:
    from app import testmode

    out = gf.ModelOutput.model_validate(
        testmode.grid_filter_reply("TODAY: 2026-11-11\nACCOUNTS: []\nREQUEST: PayPal fees over £5 in October")
    )
    model, sort, dropped = gf.build("ledger", out)
    assert set(model) == {"counterparty", "amount", "date"} and dropped == [] and sort == []
