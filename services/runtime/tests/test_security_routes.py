"""Second security pass (docs/SECURITY.md): invariants over every registered route, so a new router cannot skip them.

* every JSON body forbids unknown fields, and every free-text string in it has a length cap;
* dates in bodies are YYYY-MM-DD only, money is whole pence as an integer.
"""

from __future__ import annotations

import typing
from collections.abc import Iterator
from typing import Any

import pytest
from accnomos_connectors import FakeStorageProvider
from annotated_types import MaxLen
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from app.books import Books
from app.invoicing import InvoiceDraft
from app.main import app
from app.routes_books import get_books
from app.validation import Day, Pence

H = {"X-Graph-Token": "graph-token-" + "t" * 20, "X-User": "sam@example.co.uk"}


@pytest.fixture
def books() -> Books:
    return Books(FakeStorageProvider())


@pytest.fixture
def client(books: Books) -> Iterator[TestClient]:
    """The real app over in-memory storage: nothing here reaches Graph."""
    async def fake_books() -> Any:
        yield books

    app.dependency_overrides[get_books] = fake_books
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def routes() -> Iterator[APIRoute]:
    def walk(items: list[Any]) -> Iterator[APIRoute]:
        for r in items:
            if hasattr(r, "original_router"):  # FastAPI keeps included routers as a wrapper
                yield from walk(r.original_router.routes)
            elif isinstance(r, APIRoute):
                yield r

    return walk(app.routes)


def body_models(tp: Any, seen: set[type] | None = None) -> Iterator[type[BaseModel]]:
    seen = set() if seen is None else seen
    if typing.get_origin(tp) is not None:
        for a in typing.get_args(tp):
            yield from body_models(a, seen)
        return
    if isinstance(tp, type) and issubclass(tp, BaseModel) and tp not in seen:
        seen.add(tp)
        yield tp
        for f in tp.model_fields.values():
            yield from body_models(f.annotation, seen)


def all_body_models() -> dict[type[BaseModel], set[str]]:
    out: dict[type[BaseModel], set[str]] = {}
    for r in routes():
        for p in r.dependant.body_params:
            for m in body_models(p.field_info.annotation):
                out.setdefault(m, set()).add(f"{'/'.join(sorted(r.methods))} {r.path}")
    return out


def test_the_walk_sees_the_new_routers():
    paths = {r.path for r in routes()}
    assert {"/invoices", "/actions/approve", "/plan/day/apply", "/mail/draft-reply", "/todos", "/payroll/runs/prepare",
            "/vehicles", "/mileage", "/jobs", "/contacts/{contact_id}", "/books/dashboard"} <= paths


def test_every_request_body_forbids_unknown_fields():
    loose = {f"{m.__module__}.{m.__qualname__}": sorted(where) for m, where in all_body_models().items()
             if m.model_config.get("extra") != "forbid"}
    assert loose == {}


def _unbounded_str(tp: Any) -> bool:
    """A `str` somewhere in `tp` without a MaxLen on its own Annotated wrapper (dict keys and Literals excepted)."""
    if tp is str:
        return True
    origin = typing.get_origin(tp)
    if origin is typing.Literal:
        return False
    if origin is typing.Annotated:
        inner, *meta = typing.get_args(tp)
        capped = any(isinstance(x, MaxLen) or any(isinstance(y, MaxLen) for y in getattr(x, "metadata", [])) for x in meta)
        return False if capped else _unbounded_str(inner)
    if origin is dict:
        return _unbounded_str(typing.get_args(tp)[1])
    return any(_unbounded_str(a) for a in typing.get_args(tp))


def test_every_free_text_field_in_a_body_has_a_length_cap():
    missing = sorted(
        f"{m.__module__}.{m.__qualname__}.{name}"
        for m in all_body_models() for name, f in m.model_fields.items()
        if _unbounded_str(f.annotation) and not any(isinstance(x, MaxLen) for x in f.metadata)
    )
    assert missing == []


class _Money(BaseModel):
    day: Day
    pence: Pence


@pytest.mark.parametrize("raw", [
    '{"day": 1793059200, "pence": 1}',             # a Unix timestamp
    '{"day": "2026-10-27T00:00:00", "pence": 1}',  # a datetime
    '{"day": "27/10/2026", "pence": 1}',
    '{"day": "2026-02-30", "pence": 1}',           # not a real day
    '{"day": "2026-10-27", "pence": 12.0}',        # float pence
    '{"day": "2026-10-27", "pence": "12"}',
    '{"day": "2026-10-27", "pence": true}',
])
def test_dates_and_money_are_parsed_strictly(raw: str):
    with pytest.raises(ValidationError):
        _Money.model_validate_json(raw)


def test_strict_dates_and_pence_still_take_the_normal_forms():
    from datetime import date

    assert _Money.model_validate_json('{"day": "2026-10-27", "pence": -5}').day == date(2026, 10, 27)
    assert _Money.model_validate({"day": date(2026, 10, 27), "pence": 0}).pence == 0


@pytest.mark.parametrize("change", [
    {"issue_date": 1793059200},
    {"lines": [{"description": "x", "quantity": 1, "unit_price_pence": 1000.5}]},
    {"lines": [{"description": "x", "quantity": 1, "unit_price_pence": "1000"}]},
    {"lines": [{"description": "x" * 301, "quantity": 1, "unit_price_pence": 1000}]},
    {"notes": "x" * 1001},
    {"customer": {"name": "JM Trading", "address": "x" * 1001}},
])
def test_invoice_drafts_refuse_loose_dates_money_and_long_text(change: dict[str, Any]):
    ok = {"customer": {"name": "JM Trading"}, "lines": [{"description": "Work", "quantity": 1, "unit_price_pence": 1000}]}
    InvoiceDraft.model_validate(ok)
    with pytest.raises(ValidationError):
        InvoiceDraft.model_validate({**ok, **change})


@pytest.mark.parametrize(("method", "path", "body"), [
    ("post", "/actions/approve", {"action": {}, "extra": 1}),
    ("post", "/invoices/INV-0001/send", {"confirm": True, "bcc": "x@example.com"}),
    ("post", "/invoices/INV-0001/mark-paid", {"paid_on": "2026-10-27", "amount": 1}),
    ("post", "/plan/day/apply", {"date": "2026-10-27", "plan": [], "force": True}),
    ("put", "/payroll/runs/2026-10", {"lines": [{"staff_id": "a", "hours": 1, "rate_pence": 1, "bonus": 1}]}),
])
def test_unknown_fields_on_the_new_routes_are_a_422(client: TestClient, method: str, path: str, body: dict[str, Any]):
    r = getattr(client, method)(path, json=body, headers=H)
    assert r.status_code == 422
    assert any(e["type"] == "extra_forbidden" for e in r.json()["detail"])
