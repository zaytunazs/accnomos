"""Shopping list: lookup in the price history (options, or spec fields), live offers when a search is on, the list
in _System/shopping_list.json, the add_to_shopping_list chat action (card, approve once), and the routes."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app import actions, price_search, shopping
from app.actions import IntentModelOutput
from app.ai import ask as ask_ai
from app.books import Books
from app.sample_purchases import TAPE_BROWN, TAPE_CLEAR, seed_purchases
from app.schemas import Clarification, ProposedAction
from app.shopping import SHOPPING_LIST, ShoppingIn, ShoppingSpec

TODAY = date(2026, 10, 27)
TOKEN = "graph-token-1"
USER = "sam@example.co.uk"
H = {"X-Graph-Token": TOKEN, "X-User": USER, "X-AI-Mode": "local", "X-AI-Model": "stub-model"}
BROWN = "packing tape tesa|w=50|l=66|c=brown"
CLEAR = "packing tape|w=48|l=66|c=clear"


@pytest.fixture(autouse=True)
def search_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(price_search.ENV, raising=False)


@pytest.fixture
async def books() -> Books:
    b = Books(FakeStorageProvider())
    await seed_purchases(b)
    return b


# --------------------------------------------------------------------------- #
# Lookup
# --------------------------------------------------------------------------- #


async def test_lookup_offers_what_was_bought_before(books: Books):
    found = await shopping.lookup(books, "packing tape", TODAY)
    assert [o.key for o in found.options] == [CLEAR, BROWN]  # newest first
    clear, brown = found.options
    assert clear.label == "Packing Tape Clear 48mm x 66m, £1.65 each from Boxmart Ltd (14 Oct 2026)"
    assert brown.unit_price == "2.10" and brown.supplier == "Parcelworks Supplies Ltd"
    # the cheapest for brown tape in the books is the 6-pack, £0.0288 a metre (not yet joined with the clear tape)
    assert brown.cheapest is not None and brown.cheapest.per_measure == "0.0288"
    assert found.question_md.startswith("Which one? Last time: Packing Tape Clear 48mm x 66m, £1.65 each")
    assert found.fields == [] and found.live_offers == [] and not found.web_search.enabled


async def test_lookup_with_sizes_narrows_and_exact_name_picks_one(books: Books):
    assert [o.key for o in (await shopping.lookup(books, "packing tape 48mm", TODAY)).options] == [CLEAR]
    assert [o.key for o in (await shopping.lookup(books, "brown tape", TODAY)).options] == [BROWN]
    assert [o.key for o in (await shopping.lookup(books, TAPE_BROWN, TODAY)).options] == [BROWN]
    assert (await shopping.lookup(books, "packing tape 25mm", TODAY)).options == []


async def test_lookup_asks_for_specs_as_fields_when_nothing_matches(books: Books):
    found = await shopping.lookup(books, "masking tape", TODAY)
    assert found.options == [] and [f.name for f in found.fields] == ["width_mm", "length_m", "colour", "quantity"]
    assert "can't find “masking tape”" in found.question_md
    assert next(f for f in found.fields if f.name == "quantity").required


async def test_lookup_adds_live_offers_after_the_history(books: Books, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", "1")
    monkeypatch.setenv(price_search.ENV, "fake")
    found = await shopping.lookup(books, "packing tape 48mm x 66m", TODAY)
    assert [o.key for o in found.options] == [CLEAR]
    assert found.web_search.enabled and found.web_search.provider == "Test fake"
    best = found.live_offers[0]
    assert (
        best.supplier == "Example Packaging (test fake)" and best.per_measure == "0.0174" and best.source == "Test fake"
    )


# --------------------------------------------------------------------------- #
# The list
# --------------------------------------------------------------------------- #


async def test_add_tick_remove(books: Books):
    item = await shopping.add_item(
        books, ShoppingIn(text="packing tape", option_key=BROWN, quantity=Decimal(6)), USER, TODAY
    )
    assert item.description == TAPE_BROWN and item.quantity == Decimal(6) and item.item_key == BROWN
    assert item.suggested is not None and item.suggested.supplier == "Parcelworks Supplies Ltd"
    assert item.suggested.per_measure == "0.0288" and "lowest price per metre" in item.suggested.basis
    spec = await shopping.add_item(
        books,
        ShoppingIn(text="masking tape", spec=ShoppingSpec(width_mm=Decimal(25), length_m=Decimal(50), colour="any")),
        USER,
        TODAY,
    )
    assert spec.description == "masking tape 25mm x 50m" and spec.suggested is None and spec.item_key is None
    stored = json.loads(await books.storage.read(SHOPPING_LIST))
    assert [r["id"] for r in stored] == [item.id, spec.id]
    done = await shopping.set_done(books, item.id, True, USER)
    assert done.done and done.done_at is not None
    listed = await shopping.list_items(books)
    assert [i.id for i in listed] == [spec.id, item.id]  # open items first
    await shopping.remove_item(books, spec.id, USER)
    assert [i.id for i in await shopping.list_items(books)] == [item.id]
    with pytest.raises(KeyError):
        await shopping.set_done(books, "nope", True, USER)
    audit = (await books.storage.read(f"_System/audit/{date.today():%Y-%m}.jsonl")).decode()
    assert '"shopping_added"' in audit and '"shopping_ticked"' in audit and '"shopping_removed"' in audit


async def test_spec_that_names_a_known_item_gets_its_supplier(books: Books):
    item = await shopping.add_item(
        books,
        ShoppingIn(text="packing tape", spec=ShoppingSpec(width_mm=Decimal(48), length_m=Decimal(66), colour="clear")),
        USER,
        TODAY,
    )
    assert item.item_key == CLEAR and item.suggested and item.suggested.supplier == "Boxmart Ltd"


async def test_the_supplier_comes_from_code_not_the_client(books: Books):
    with pytest.raises(ValueError):
        ShoppingIn.model_validate({"text": "tape", "suggested": {"supplier": "Me"}})  # strict body
    item = await shopping.add_item(books, ShoppingIn(text="tape", option_key="made up"), USER, TODAY)
    assert item.suggested is None and item.description == "tape"


async def test_a_full_or_broken_list_is_refused(books: Books):
    await books.write_json(SHOPPING_LIST, {"not": "a list"})
    with pytest.raises(shopping.ShoppingError):
        await shopping.list_items(books)
    await books.storage.write(SHOPPING_LIST, b"[" + b",".join([b"{}"] * shopping.ITEMS_MAX) + b"]")
    with pytest.raises(shopping.ShoppingError):
        await shopping.add_item(books, ShoppingIn(text="tape"), USER, TODAY)


def test_describe():
    assert shopping.describe("tape", None) == "tape"
    spec = ShoppingSpec(width_mm=Decimal("48.0"), length_m=Decimal(66), colour="Clear", pack=6)
    assert shopping.describe("packing tape", spec) == "packing tape 48mm x 66m clear pack of 6"


# --------------------------------------------------------------------------- #
# The chat action
# --------------------------------------------------------------------------- #


def intent(**kw: Any) -> IntentModelOutput:
    fields = {f: None for f in IntentModelOutput.model_fields if f != "kind"}
    return IntentModelOutput(kind="add_to_shopping_list", **{**fields, **kw})  # type: ignore[arg-type]


def stub_model(monkeypatch: pytest.MonkeyPatch, reply: IntentModelOutput) -> None:
    async def fake(messages, cfg, schema, name):  # noqa: ANN001, ANN202
        return reply.model_dump_json()

    monkeypatch.setattr(ask_ai, "call_json_model", fake)


def test_parse_shopping_intent():
    got = actions.parse_intent(
        intent(item_text="packing tape", quantity_text="6"), "add 6 packing tape to my list", TODAY
    )
    assert isinstance(got, actions.ShoppingIntent) and got.quantity == 6 and got.item_text == "packing tape"
    unsaid = actions.parse_intent(intent(item_text="tape", quantity_text="12"), "add tape to my shopping list", TODAY)
    assert isinstance(unsaid, Clarification) and unsaid.field == "quantity"  # a figure the user did not say
    empty = actions.parse_intent(intent(item_text=" "), "add to my shopping list", TODAY)
    assert isinstance(empty, Clarification) and empty.field == "item"
    assert actions.looks_like_action("add packing tape to my shopping list")


async def test_several_matches_ask_which_one(books: Books):
    got = await actions.resolve_shopping(books, actions.ShoppingIntent(item_text="packing tape"), TODAY)
    assert isinstance(got, Clarification) and got.field == "item" and got.ref == "packing tape"
    assert got.candidates == [TAPE_CLEAR, TAPE_BROWN] and got.question_md.startswith("Which one?")


async def test_nothing_matches_asks_for_spec_fields(books: Books):
    got = await actions.resolve_shopping(
        books, actions.ShoppingIntent(item_text="masking tape", quantity=Decimal(3)), TODAY
    )
    assert isinstance(got, Clarification) and got.field == "spec"
    assert [f["name"] for f in got.spec_fields] == ["width_mm", "length_m", "colour", "quantity"]
    assert got.spec_fields[-1]["value"] == "3"


async def test_card_then_approve_once(books: Books):
    draft = await actions.resolve_shopping(
        books, actions.ShoppingIntent(item_text=TAPE_BROWN, quantity=Decimal(6)), TODAY
    )
    assert isinstance(draft, actions.Draft) and draft.kind == "add_to_shopping_list"
    assert draft.summary_md.startswith(f"**Add 6 × {TAPE_BROWN}** to your shopping list.")
    assert "Cheapest in your books: £11.40 from Parcelworks Supplies Ltd (8 September 2026)" in draft.summary_md
    assert await shopping.list_items(books) == []  # nothing before Approve
    action = actions.new_action(draft, TOKEN)
    ctx = actions.Context(books=books, user=USER, graph_token=TOKEN)
    first = await actions.approve(action, ctx)
    again = await actions.approve(action, ctx)
    assert first.status == "done" and again.status == "already_done"
    [item] = await shopping.list_items(books)
    assert item.description == TAPE_BROWN and item.quantity == 6 and item.added_by == USER


def test_ask_route_card_and_spec_route(books: Books, monkeypatch: pytest.MonkeyPatch):
    from app.main import app
    from app.routes_books import get_books

    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    try:
        client = TestClient(app)
        stub_model(monkeypatch, intent(item_text="packing tape"))
        which = client.post("/books/ask", json={"question": "add packing tape to my shopping list"}, headers=H)
        stub_model(monkeypatch, intent(item_text=TAPE_CLEAR))
        card = client.post("/books/ask", json={"question": f"add {TAPE_CLEAR} to my shopping list"}, headers=H)
        spec = client.post(
            "/shopping/propose",
            json={"text": "masking tape", "spec": {"width_mm": "25", "length_m": "50"}, "quantity": "3"},
            headers=H,
        )
        approved = client.post("/actions/approve", json={"action": spec.json()}, headers=H)
        listed = client.get("/shopping", headers=H)
        item_id = listed.json()["items"][0]["id"]
        ticked = client.patch(f"/shopping/{item_id}", json={"done": True}, headers=H)
        missing = client.patch("/shopping/nope", json={"done": True}, headers=H)
        added = client.post("/shopping", json={"text": "packing tape", "option_key": CLEAR, "quantity": 6}, headers=H)
        looked = client.post("/shopping/lookup", json={"text": "packing tape"}, headers=H)
        gone = client.delete(f"/shopping/{item_id}", headers=H)
        no_user = client.post("/shopping", json={"text": "tape"}, headers={"X-Graph-Token": TOKEN})
    finally:
        app.dependency_overrides.clear()
    assert which.status_code == 200 and which.json()["clarification"]["candidates"] == [TAPE_CLEAR, TAPE_BROWN]
    assert card.json()["proposed_action"]["kind"] == "add_to_shopping_list", card.text
    ProposedAction.model_validate(spec.json())
    assert spec.json()["preview"]["description"] == "masking tape 25mm x 50m"
    assert approved.status_code == 200 and approved.json()["status"] == "done", approved.text
    body = listed.json()
    assert body["web_search"]["enabled"] is False and "purchase_order" in body["future_steps"]
    assert body["items"][0]["quantity"] == "3"
    assert ticked.json()["done"] is True and missing.status_code == 404
    assert added.status_code == 201 and added.json()["suggested"]["supplier"] == "Boxmart Ltd"
    assert len(looked.json()["options"]) == 2
    assert gone.status_code == 200 and no_user.status_code == 400
