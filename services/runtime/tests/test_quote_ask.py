"""Quotes by chat and voice: the quote facts in Ask's pack (and the number check on answers about them), and the
create_quote / convert_quote_to_invoice action cards (app/actions.py, app/facts.py, app/quotes.py)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app import actions
from app import invoicing as inv_
from app import quotes as q_
from app.actions import IntentModelOutput
from app.ai import ask as ask_ai
from app.ai.config import AiConfig
from app.ask_router import pack, route
from app.autopilot import supplier_key
from app.books import Books
from app.books import today as london_today
from app.contacts import CONTACTS, Contact
from app.facts import build_facts, default_period
from app.invoicing import PROFILE, InvoiceCustomer, InvoiceProfile, LineIn
from app.paths import QUOTES
from app.schemas import AskModelOutput, Clarification, ProposedAction

CFG = AiConfig(mode="local", base_url="http://ollama.invalid", model="stub-model")
TOKEN = "graph-token-1"
USER = "sam@example.co.uk"
H = {"X-Graph-Token": TOKEN, "X-User": USER, "X-AI-Mode": "local", "X-AI-Model": "stub-model"}
TODAY = date(2026, 10, 27)


def _contact(name: str, email: str | None) -> dict[str, Any]:
    key = supplier_key(name)
    return Contact(
        id=key.replace("-", "")[:16].ljust(16, "0"),
        kind="customer",
        name=name,
        normalised_key=key,
        email=email,  # type: ignore[arg-type]
    ).model_dump(mode="json")


@pytest.fixture
async def books() -> Books:
    b = Books(FakeStorageProvider())
    await b.write_json(
        CONTACTS, [_contact("JM Trading Ltd", "accounts@jmtrading.example"), _contact("Hartley Builders", None)]
    )
    await b.write_json(
        PROFILE,
        InvoiceProfile.model_validate(
            {"name": "Sam Electrical", "address": "1 High St", "vrn": "GB 123 4567 89"}
        ).model_dump(mode="json"),
    )
    return b


async def _quote(
    books: Books, customer: str, pence: int, *, issue: date, expiry: date, state: str = "draft"
) -> q_.Quote:
    draft = q_.QuoteDraft(
        customer=InvoiceCustomer(name=customer, email=None),
        issue_date=issue,
        expiry_date=expiry,
        lines=[LineIn(description="Work", quantity="1", unit_price_pence=pence, vat_code="S")],  # type: ignore[arg-type]
    )
    q = await q_.create_quote(books, draft, USER)
    if state in ("sent", "accepted"):
        q = await q_.mark_sent(books, q.number, USER)
    if state == "accepted":
        q = await q_.decide(books, q.number, USER, "accepted")
    return q


async def _book_of_quotes(books: Books) -> None:
    t = london_today()
    day = timedelta(days=1)
    await _quote(books, "JM Trading Ltd", 10_000, issue=t - 20 * day, expiry=t + 3 * day, state="sent")  # soon
    await _quote(books, "Hartley Builders", 20_000, issue=t - 5 * day, expiry=t + 20 * day, state="sent")
    await _quote(books, "JM Trading Ltd", 5_000, issue=t - 40 * day, expiry=t - 2 * day, state="sent")  # expired
    await _quote(books, "Hartley Builders", 30_000, issue=t - 9 * day, expiry=t + 21 * day, state="accepted")
    await _quote(books, "JM Trading Ltd", 1_000, issue=t, expiry=t + 30 * day)  # draft


# --------------------------------------------------------------------------- #
# Facts and the number check
# --------------------------------------------------------------------------- #


async def test_quote_facts_are_worked_out_by_code(books: Books):
    await _book_of_quotes(books)
    f = q_.quote_facts(await q_.list_quotes(books), london_today())
    assert f is not None
    assert f["waiting_for_an_answer"]["count"] == 2 and f["waiting_for_an_answer"]["total"] == "360.00"  # type: ignore[index]
    assert [c["number"] for c in f["waiting_for_an_answer"]["quotes"]] == ["QU-0001", "QU-0002"]  # type: ignore[index]
    assert f["waiting_for_an_answer"]["quotes"][0]["days_left"] == 3  # type: ignore[index]
    assert f["expiring_within_7_days"] == {"count": 1, "total": "120.00"}
    assert f["expired_unanswered"]["count"] == 1 and f["expired_unanswered"]["total"] == "60.00"  # type: ignore[index]
    assert f["accepted_not_yet_invoiced"] == {"count": 1, "total": "360.00"}
    assert f["drafts"] == {"count": 1, "total": "12.00"}
    assert q_.quote_facts([], london_today()) is None


async def test_the_facts_pack_carries_quotes_only_when_there_are_some(books: Books):
    period = default_period(london_today())
    assert "quotes" not in await build_facts(books, period)
    await _book_of_quotes(books)
    facts = await build_facts(books, period)
    assert facts["quotes"]["waiting_for_an_answer"]["total"] == "360.00" and f"{QUOTES}/" in facts["sources"]


async def test_an_answer_about_quotes_passes_the_number_check_and_an_invented_figure_does_not(books: Books):
    await _book_of_quotes(books)
    facts = await build_facts(books, default_period(london_today()))
    question = "any outstanding quotes?"
    r = route(question, facts)
    assert r.sections == {"quotes"}
    assert pack(facts, r)["quotes"]["expiring_within_7_days"] == {"count": 1, "total": "120.00"}

    good = AskModelOutput(
        answer_md="You have 2 quotes waiting for an answer, worth £360.00. QU-0001 (£120.00) runs out in 3 days.",
        confidence="high",
        key_numbers=[],
        citations=[],
        suggested_actions=[],
    )
    got = ask_ai.ground(good, facts, "stub", question, r)
    assert got.fallback_reason is None
    assert [k.value for k in got.key_numbers] == ["£360.00", "£120.00", "£360.00"]
    assert got.citations == [f"{QUOTES}/"]

    bad = AskModelOutput(
        answer_md="You have quotes worth £999.00 waiting.",
        confidence="high",
        key_numbers=[],
        citations=[],
        suggested_actions=[],
    )
    fell = ask_ai.ground(bad, facts, "stub", question, r)
    assert fell.fallback_reason and "999.00" in fell.fallback_reason
    assert "£360.00" in fell.answer_md and fell.citations == [f"{QUOTES}/"]  # code's own figures, from the files


# --------------------------------------------------------------------------- #
# Action cards
# --------------------------------------------------------------------------- #


def out(kind: str, **kw: Any) -> IntentModelOutput:
    fields = {f: None for f in IntentModelOutput.model_fields if f != "kind"}
    return IntentModelOutput(kind=kind, **{**fields, **kw})  # type: ignore[arg-type]


def stub_model(monkeypatch: pytest.MonkeyPatch, reply: IntentModelOutput) -> None:
    async def fake(messages: list[dict], cfg: AiConfig, schema: dict, name: str) -> str:
        return reply.model_dump_json()

    monkeypatch.setattr(ask_ai, "call_json_model", fake)


def test_a_question_about_quotes_is_not_an_instruction_but_an_instruction_is():
    assert not actions.looks_like_action("any outstanding quotes?")
    assert not actions.looks_like_action("what quotes are waiting for an answer")
    assert actions.looks_like_action("write a quote for JM Trading for £500")
    assert actions.looks_like_action("turn quote QU-0001 into an invoice")


async def test_create_quote_card_prices_in_code_and_saves_a_draft_on_approval(
    books: Books, monkeypatch: pytest.MonkeyPatch
):
    stub_model(
        monkeypatch,
        out("create_quote", customer_ref="JM Trading", description="boiler install", amount_text="£500", due_days=14),
    )
    card = await actions.propose("write a quote for JM Trading for £500 valid for 14 days", books, CFG, TOKEN, TODAY)
    assert isinstance(card, ProposedAction) and card.kind == "create_quote"
    p = card.preview
    assert (p["net_pence"], p["vat_pence"], p["total_pence"]) == (50_000, 10_000, 60_000)
    assert p["expiry_date"] == "2026-11-10" and p["valid_days"] == 14 and "send" not in p
    assert "£600.00" in card.summary_md and "10 November 2026" in card.summary_md
    assert await q_.list_quotes(books) == []  # nothing exists before Approve

    ctx = actions.Context(books=books, user=USER, graph_token=TOKEN)
    done = await actions.approve(card, ctx)
    assert done.status == "done" and done.result["quote"] == "QU-0001" and done.result["total_pence"] == 60_000
    (q,) = await q_.list_quotes(books)
    assert q.status == "draft" and q.customer.name == "JM Trading Ltd" and q.expiry_date == date(2026, 11, 10)
    again = await actions.approve(card, ctx)
    assert again.status == "already_done" and len(await q_.list_quotes(books)) == 1  # once only


async def test_create_quote_refuses_a_figure_the_user_did_not_say(books: Books, monkeypatch: pytest.MonkeyPatch):
    stub_model(monkeypatch, out("create_quote", customer_ref="JM Trading", amount_text="£5,000"))
    got = await actions.propose("write a quote for JM Trading for £500", books, CFG, TOKEN, TODAY)
    assert isinstance(got, Clarification) and got.kind == "create_quote" and "quote" in got.question_md


async def test_convert_quote_card_makes_a_draft_invoice_with_the_same_totals(
    books: Books, monkeypatch: pytest.MonkeyPatch
):
    q = await _quote(
        books,
        "JM Trading Ltd",
        12_345,
        issue=TODAY - timedelta(days=3),
        expiry=TODAY + timedelta(days=27),
        state="accepted",
    )
    stub_model(monkeypatch, out("convert_quote_to_invoice", quote_ref="quote 1"))
    card = await actions.propose("turn quote 1 into an invoice", books, CFG, TOKEN, TODAY)
    assert isinstance(card, ProposedAction) and card.kind == "convert_quote_to_invoice"
    assert card.preview["quote"] == q.number and card.preview["total_pence"] == q.total_pence
    assert await inv_.list_invoices(books) == []  # nothing exists before Approve

    done = await actions.approve(card, actions.Context(books=books, user=USER, graph_token=TOKEN))
    assert done.result["invoice"] == "INV-0001" and done.result["total_pence"] == q.total_pence
    (inv,) = await inv_.list_invoices(books)
    assert inv.status == "draft" and (inv.net_pence, inv.vat_pence) == (q.net_pence, q.vat_pence)
    assert (await q_.get_quote(books, q.number)).invoice_number == "INV-0001"


async def test_convert_quote_by_customer_asks_when_two_are_open_and_skips_converted_ones(
    books: Books, monkeypatch: pytest.MonkeyPatch
):
    a = await _quote(books, "JM Trading Ltd", 10_000, issue=TODAY, expiry=TODAY + timedelta(days=30), state="sent")
    b = await _quote(books, "JM Trading Ltd", 20_000, issue=TODAY, expiry=TODAY + timedelta(days=30), state="sent")
    stub_model(monkeypatch, out("convert_quote_to_invoice", customer_ref="JM Trading"))
    got = await actions.propose("convert JM Trading's quote to an invoice", books, CFG, TOKEN, TODAY)
    assert isinstance(got, Clarification) and got.candidates == [a.number, b.number]
    await q_.decide(books, b.number, USER, "accepted")  # one accepted: that is the one meant
    got = await actions.propose("convert JM Trading's quote to an invoice", books, CFG, TOKEN, TODAY)
    assert isinstance(got, ProposedAction) and got.preview["quote"] == b.number
    await q_.convert_to_invoice(books, b.number, USER)
    stub_model(monkeypatch, out("convert_quote_to_invoice", quote_ref=b.number))
    gone = await actions.propose(f"convert {b.number} to an invoice", books, CFG, TOKEN, TODAY)
    assert isinstance(gone, Clarification) and "still waiting" in gone.question_md


async def test_a_changed_quote_is_refused_at_approval(books: Books, monkeypatch: pytest.MonkeyPatch):
    q = await _quote(books, "JM Trading Ltd", 10_000, issue=TODAY, expiry=TODAY + timedelta(days=30), state="sent")
    stub_model(monkeypatch, out("convert_quote_to_invoice", quote_ref=q.number))
    card = await actions.propose(f"convert {q.number} to an invoice", books, CFG, TOKEN, TODAY)
    assert isinstance(card, ProposedAction)
    await q_.convert_to_invoice(books, q.number, USER)  # converted by hand before the card was approved
    with pytest.raises(actions.ActionError):
        await actions.approve(card, actions.Context(books=books, user=USER, graph_token=TOKEN))
    assert len(await inv_.list_invoices(books)) == 1  # no second invoice


def test_routes_ask_card_and_approve_for_a_quote(books: Books, monkeypatch: pytest.MonkeyPatch):
    from app.main import app
    from app.routes_books import get_books

    async def override():
        yield books

    stub_model(monkeypatch, out("create_quote", customer_ref="JM Trading", description="rewire", amount_text="£200"))
    app.dependency_overrides[get_books] = override
    try:
        client = TestClient(app)
        r = client.post("/books/ask", json={"question": "write a quote for JM Trading for £200"}, headers=H)
        card = r.json()["proposed_action"]
        assert card["kind"] == "create_quote" and card["preview"]["total_pence"] == 24_000
        ok = client.post("/actions/approve", json={"action": card}, headers=H)
        assert ok.status_code == 200 and ok.json()["result"]["quote"] == "QU-0001", ok.text
        listed = client.get("/quotes", headers=H).json()
    finally:
        app.dependency_overrides.clear()
    assert [(x["number"], x["status"], x["total_pence"]) for x in listed] == [("QU-0001", "draft", 24_000)]
