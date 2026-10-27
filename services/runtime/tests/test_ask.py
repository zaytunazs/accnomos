"""Ask your books: facts pack on FakeStorageProvider, the grounding validator with a fake model, and the route."""

from __future__ import annotations

import json
from datetime import date, datetime

import httpx
import pytest
from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode
from fastapi.testclient import TestClient

from app.ai import ask as ask_ai
from app.ai.config import AiConfig
from app.books import EVENTS, PROPOSALS, Books
from app.facts import FACTS_MAX_BYTES, build_facts, default_period, previous_period
from app.schemas import AskModelOutput, AskPeriod

CFG = AiConfig(mode="local", base_url="http://ollama.invalid", model="stub-model")
Q3 = AskPeriod(start=date(2026, 7, 1), end=date(2026, 9, 30))


def _ev(kind: str, d: date, net: int, vat: int, who: str, code: VatCode = VatCode.STANDARD) -> LedgerEvent:
    gross = net + vat
    if kind == "sale":
        lines = [Line(account="1200 Bank", debit=gross), Line(account="4000 Sales", credit=net, vat_code=code)]
        if vat:
            lines.append(Line(account="2200 VAT control", credit=vat))
    else:
        lines = [Line(account="5100 Materials", debit=net, vat_code=code), Line(account="1200 Bank", credit=gross)]
        if vat:
            lines.insert(1, Line(account="2200 VAT control", debit=vat))
    return LedgerEvent(
        kind=kind, date=d, net=net, vat=vat, counterparty=who, lines=lines,  # type: ignore[arg-type]
        approved_by="sam@example.co.uk", approved_at=datetime(d.year, d.month, d.day, 12, 0),
    )


SYNTHETIC = [
    _ev("sale", date(2026, 8, 4), 1_000_000, 200_000, "Hartley"),
    _ev("sale", date(2026, 9, 12), 250_000, 50_000, "Moss & Co"),
    _ev("purchase", date(2026, 7, 20), 206_000, 41_200, "Howdens"),
    _ev("purchase", date(2026, 9, 21), 3_206, 641, "Screwfix"),
    _ev("purchase", date(2026, 9, 22), 5_000, 0, "Booksellers", VatCode.ZERO),
    _ev("sale", date(2026, 5, 2), 500_000, 100_000, "Hartley"),
    _ev("purchase", date(2026, 6, 3), 100_000, 20_000, "Howdens"),
]


@pytest.fixture
async def books() -> Books:
    b = Books(FakeStorageProvider())
    await b.ensure_tree()
    for ev in SYNTHETIC:
        await b.post_event(ev)
    await b.write_json(f"{PROPOSALS}/abcdef01.json", {"id": "abcdef01", "status": "proposed"})
    await b.write_json(f"{PROPOSALS}/abcdef02.json", {"id": "abcdef02", "status": "posted"})
    return b


@pytest.fixture
async def facts(books: Books) -> dict:
    return await build_facts(books, Q3, "Bramblewood Joinery Ltd")


def _out(**kw: object) -> AskModelOutput:
    base: dict[str, object] = dict(
        answer_md="Your VAT bill is **£2,081.59**, up £1,281.59 on last quarter.\n\n- Sales VAT rose to £2,500.00\n- Howdens was your biggest supplier",
        key_numbers=[
            {"label": "Net VAT (Box 5)", "value": "£2,081.59", "source": "_System/Ledger/events/2026-08/"},
            {"label": "Change vs Q2", "value": "+£1,281.59", "source": "made/up/path.json"},
        ],
        citations=["_System/Ledger/events/2026-08/", "C:/secret/elsewhere.xlsx"],
        suggested_actions=[
            {"label": "Open the VAT return", "kind": "open_vat", "arg": None},
            {"label": "Chase Acme", "kind": "chase_supplier", "arg": "Acme Widgets"},
            {"label": "Chase Howdens", "kind": "chase_supplier", "arg": "Howdens"},
        ],
        confidence="high",
    )
    base.update(kw)
    return AskModelOutput.model_validate(base)


# --------------------------------------------------------------------------- #
# Periods and the facts pack
# --------------------------------------------------------------------------- #

def test_periods():
    assert default_period(date(2026, 10, 27)) == Q3
    assert previous_period(Q3) == AskPeriod(start=date(2026, 4, 1), end=date(2026, 6, 30))
    jan = AskPeriod(start=date(2026, 1, 1), end=date(2026, 3, 31))
    assert previous_period(jan) == AskPeriod(start=date(2025, 10, 1), end=date(2025, 12, 31))
    odd = AskPeriod(start=date(2026, 9, 10), end=date(2026, 9, 19))
    assert previous_period(odd) == AskPeriod(start=date(2026, 8, 31), end=date(2026, 9, 9))


async def test_facts_pack(facts: dict):
    this, prev, d = facts["this_period"], facts["previous_period"], facts["derived"]
    assert this["vat"]["box1"] == "2500.00" and this["vat"]["box4"] == "418.41" and this["vat"]["box5"] == "2081.59"
    assert this["vat"]["box6"] == "12500" and this["vat"]["box7"] == "2142" and this["entries"] == 5
    assert prev["vat"]["box5"] == "800.00" and prev["start"] == "2026-04-01"
    assert d["box5_delta_vs_prev"] == "1281.59" and d["box5_change_pct_vs_prev"] == "160.2"
    assert d["box6_delta_vs_prev"] == "7500" and d["vat_position"] == "pay HMRC"
    assert this["totals"]["sales"] == {"net": "12500.00", "vat": "2500.00", "count": 2}
    assert this["totals"]["by_vat_code"]["purchases:Z"] == {"net": "50.00", "vat": "0.00", "count": 1}
    assert facts["top_suppliers"][0] == {"name": "Howdens", "net": "2060.00", "count": 1}
    assert facts["top_customers"][0]["name"] == "Hartley"
    biggest = facts["largest_transactions"][0]
    assert biggest["counterparty"] == "Hartley" and biggest["gross"] == "12000.00"
    assert biggest["source"].startswith(f"{EVENTS}/2026-08/") and biggest["source"] in facts["sources"]
    assert facts["pending_proposals"] == {"proposed": 1, "needs_a_look": 0}
    assert f"{EVENTS}/2026-05/" in facts["sources"] and f"{PROPOSALS}/" in facts["sources"]
    assert "Books.xlsx" not in facts["sources"]  # never rebuilt in this test, so not cited
    assert len(json.dumps(facts, separators=(",", ":")).encode()) <= FACTS_MAX_BYTES


async def test_facts_pack_stays_small():
    b = Books(FakeStorageProvider())
    for i in range(80):
        await b.post_event(_ev("purchase", date(2026, 7 + i % 3, 1 + i % 28), 10_000 + i, 2_000, f"Supplier with a long trading name {i}"))
        await b.post_event(_ev("sale", date(2026, 7 + i % 3, 1 + i % 28), 50_000 + i, 10_000, f"Customer with a long trading name {i}"))
    facts = await build_facts(b, Q3)
    assert len(json.dumps(facts, separators=(",", ":"), ensure_ascii=False).encode()) <= FACTS_MAX_BYTES
    assert facts["this_period"]["vat"]["box5"] and facts["this_period"]["entries"] == 160


async def test_facts_pack_empty_books():
    facts = await build_facts(Books(FakeStorageProvider()), Q3)
    assert facts["this_period"]["vat"]["box5"] == "0.00" and facts["sources"] == [f"{EVENTS}/"]
    assert facts["derived"]["box5_change_pct_vs_prev"] is None


# --------------------------------------------------------------------------- #
# The validator (fake model output)
# --------------------------------------------------------------------------- #

async def test_ground_keeps_a_faithful_answer(facts: dict):
    got = ask_ai.ground(_out(), facts, "stub-model")
    assert got.fallback_reason is None and got.confidence == "high" and got.model == "stub-model"
    assert got.answer_md.startswith("Your VAT bill is **£2,081.59**")
    assert got.citations == ["_System/Ledger/events/2026-08/"]  # the invented path is stripped
    assert got.key_numbers[1].source in facts["sources"]  # made-up source replaced
    assert [a.arg for a in got.suggested_actions] == [None, "Howdens"]  # unknown supplier dropped
    assert got.period == Q3


async def test_ground_accepts_roundings_and_absolute_deltas(facts: dict):
    text = "About £2,082 to pay, roughly 160% more than Q2. Purchases fell by £0 — no, Box 7 is £2,142."
    got = ask_ai.ground(_out(answer_md=text), facts, "m")
    assert got.fallback_reason is None


async def test_ground_replaces_an_invented_number(facts: dict):
    got = ask_ai.ground(_out(answer_md="Your bill is £3,140.00, up £620 on Q2."), facts, "m")
    assert got.confidence == "low" and got.fallback_reason and "3,140.00" in got.fallback_reason
    assert "£3,140" not in got.answer_md and "£2,081.59" in got.answer_md and "£800.00" in got.answer_md
    assert got.key_numbers[0].value == "£2,081.59" and set(got.citations) <= set(facts["sources"])
    assert {a.kind for a in got.suggested_actions} == {"open_vat", "open_review"}


async def test_ground_checks_key_numbers_strictly(facts: dict):
    bad = [{"label": "Q4 forecast", "value": "£9,999.99", "source": "Books.xlsx"}, {"label": "x", "value": "£2,081.59", "source": ""}]
    got = ask_ai.ground(_out(key_numbers=bad), facts, "m")
    assert got.fallback_reason and got.confidence == "low"


async def test_ground_pads_key_numbers_and_clips_text(facts: dict):
    got = ask_ai.ground(_out(key_numbers=[], citations=[], answer_md="Word " * 400), facts, "m")
    assert len(got.answer_md) <= 1200 and got.answer_md.endswith("…")
    assert len(got.key_numbers) == 2 and got.key_numbers[0].value == "£2,081.59"
    assert got.citations and set(got.citations) <= set(facts["sources"])


async def test_answer_with_fake_model(facts: dict, monkeypatch: pytest.MonkeyPatch):
    seen: list[list[dict]] = []

    async def fake(messages: list[dict], cfg: AiConfig) -> str:
        seen.append(messages)
        return "```json\n" + _out().model_dump_json() + "\n```"

    monkeypatch.setattr(ask_ai, "_call_model", fake)
    got = await ask_ai.answer("Why is my VAT up?", facts, [], CFG)
    assert got.fallback_reason is None
    assert seen[0][0]["role"] == "system" and '"box5":"2081.59"' in seen[0][-1]["content"]


@pytest.mark.parametrize(
    "reply, reason",
    [("not json", "expected format"), ('{"answer_md": "hi"}', "expected format"), (httpx.ConnectError("down"), "could not be reached")],
)
async def test_answer_falls_back_on_model_trouble(facts: dict, monkeypatch: pytest.MonkeyPatch, reply: object, reason: str):
    async def fake(messages: list[dict], cfg: AiConfig) -> str:
        if isinstance(reply, Exception):
            raise reply
        return str(reply)

    monkeypatch.setattr(ask_ai, "_call_model", fake)
    got = await ask_ai.answer("q", facts, [], CFG)
    assert got.confidence == "low" and reason in (got.fallback_reason or "")


# --------------------------------------------------------------------------- #
# The route
# --------------------------------------------------------------------------- #

async def test_ask_route(books: Books, monkeypatch: pytest.MonkeyPatch):
    from app.main import app
    from app.routes_books import get_books

    seen: list[list[dict]] = []

    async def fake(messages: list[dict], cfg: AiConfig) -> str:
        seen.append(messages)
        return _out().model_dump_json()

    async def override():
        yield books

    monkeypatch.setattr(ask_ai, "_call_model", fake)
    app.dependency_overrides[get_books] = override
    try:
        client = TestClient(app)
        headers = {"X-Graph-Token": "t", "X-AI-Mode": "local", "X-AI-Model": "muse-glimmer:30b"}
        history = [{"role": "user", "text": f"earlier {i}"} for i in range(9)]
        body = {"question": "Why is my VAT higher than last quarter?", "period": {"start": "2026-07-01", "end": "2026-09-30"}, "history": history}
        r = client.post("/books/ask", json=body, headers=headers)
        bad = client.post("/books/ask", json={"question": ""}, headers=headers)
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["model"] == "muse-glimmer:30b" and got["fallback_reason"] is None
    assert got["period"] == {"start": "2026-07-01", "end": "2026-09-30"}
    assert got["key_numbers"][0]["value"] == "£2,081.59" and "C:/secret/elsewhere.xlsx" not in got["citations"]
    assert len(seen[0]) == 1 + 6 + 1  # system, the last six turns, the question with facts
    assert bad.status_code == 422


def test_ask_route_needs_a_token():
    from app.main import app

    r = TestClient(app).post("/books/ask", json={"question": "hi"})
    assert r.status_code == 401


async def test_ask_plan_my_thursday_offers_a_day_plan_without_the_model(books: Books, monkeypatch: pytest.MonkeyPatch):
    from app.main import app
    from app.routes_books import get_books

    async def boom(*_a: object, **_k: object) -> str:
        raise AssertionError("the model must not be called for a day plan")

    async def override():
        yield books

    monkeypatch.setattr(ask_ai, "_call_model", boom)
    app.dependency_overrides[get_books] = override
    try:
        headers = {"X-Graph-Token": "t", "X-AI-Mode": "local"}
        r = TestClient(app).post("/books/ask", json={"question": "Plan my Thursday"}, headers=headers)
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    action = r.json()["suggested_actions"][0]
    assert action["kind"] == "plan_day" and action["label"].startswith("Plan Thursday")
    assert date.fromisoformat(action["arg"]).weekday() == 3


def test_ground_drops_a_plan_day_action_from_the_model(facts: dict):
    out = _out(suggested_actions=[{"label": "Plan", "kind": "plan_day", "arg": "2026-10-29"}])
    assert ask_ai.ground(out, facts, "m").suggested_actions == []
