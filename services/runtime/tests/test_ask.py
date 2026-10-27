"""Ask your books: facts pack on FakeStorageProvider, the grounding validator with a fake model, and the route."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any

import httpx
import pytest
from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode
from fastapi.testclient import TestClient

from app.ai import ask as ask_ai
from app.ai.config import AiConfig
from app.ask_router import PACK_TOKENS, PREV, THIS, approx_tokens, pack, route
from app.books import EVENTS, PROPOSALS, Books
from app.facts import FACTS_MAX_BYTES, build_facts, default_period, previous_period
from app.schemas import AskModelOutput, AskPeriod
from app.vat_cycle import VatCycle

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
    assert default_period(date(2026, 10, 27)) == AskPeriod(start=date(2026, 10, 1), end=date(2026, 12, 31))  # the current period
    assert default_period(date(2026, 10, 27), VatCycle(start_month=2)) == AskPeriod(start=date(2026, 8, 1), end=date(2026, 10, 31))
    assert previous_period(Q3) == AskPeriod(start=date(2026, 4, 1), end=date(2026, 6, 30))
    jan = AskPeriod(start=date(2026, 1, 1), end=date(2026, 3, 31))
    assert previous_period(jan) == AskPeriod(start=date(2025, 10, 1), end=date(2025, 12, 31))
    odd = AskPeriod(start=date(2026, 9, 10), end=date(2026, 9, 19))
    assert previous_period(odd) == AskPeriod(start=date(2026, 8, 31), end=date(2026, 9, 9))


def test_an_undone_sale_counts_against_sales():
    """The facts use the same side as the VAT return for what approve.undo actually posts."""
    from app.approve import reversal_of
    from app.facts import side

    sale = _ev("sale", date(2026, 9, 1), 10000, 2000, "Hollins Ltd")
    buy = _ev("purchase", date(2026, 9, 2), 5000, 1000, "Screwfix")
    assert side(sale) == ("sales", 1) and side(reversal_of(sale, "sam@example.co.uk")) == ("sales", -1)
    assert side(buy) == ("purchases", 1) and side(reversal_of(buy, "sam@example.co.uk")) == ("purchases", -1)


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
    assert "C:/secret/elsewhere.xlsx" not in got.citations and set(got.citations) <= set(facts["sources"])  # invented path stripped
    assert "_System/Ledger/events/2026-08/" in got.citations
    assert got.key_numbers[1].source in facts["sources"]  # made-up source replaced
    assert [a.arg for a in got.suggested_actions] == [None, "Howdens"]  # unknown supplier dropped
    assert got.period == Q3


async def test_ground_accepts_roundings_and_absolute_deltas(facts: dict):
    text = "About £2,082 to pay, roughly 160% more than Q2. Purchases fell by £0 — no, Box 7 is £2,142."
    got = ask_ai.ground(_out(answer_md=text), facts, "m")
    assert got.fallback_reason is None


async def test_ground_accepts_a_figure_from_the_question(facts: dict):
    text = "Your books start later than March 2025, so I can't tell what you spent on fuel then."
    assert ask_ai.ground(_out(answer_md=text), facts, "m").fallback_reason  # 2025 is not in the facts
    got = ask_ai.ground(_out(answer_md=text), facts, "m", "What did I spend on fuel in March 2025?")
    assert got.fallback_reason is None and got.answer_md == text


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
    values = [k["value"] for k in got["key_numbers"]]
    assert values[0] == "+£1,281.59" and "£2,081.59" in values and "£800.00" in values  # a comparison: the change first
    assert "C:/secret/elsewhere.xlsx" not in got["citations"]
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
    assert "plan_day" not in {a.kind for a in ask_ai.ground(out, facts, "m").suggested_actions}


# --------------------------------------------------------------------------- #
# The router and the pack the model sees
# --------------------------------------------------------------------------- #

def test_route_picks_sections_and_the_period(facts: dict):
    r = route("How much VAT did I reclaim last quarter?", facts)
    assert r.sections == {"vat"} and r.periods == {PREV} and r.boxes == (4,) and not r.compare
    r = route("By how much has my VAT bill changed since last quarter?", facts)
    assert r.periods == {THIS, PREV} and r.compare
    r = route("How much did I spend with Howdens this quarter?", facts)
    assert {"suppliers", "transactions"} <= r.sections and r.names == ("Howdens",) and r.periods == {THIS}
    assert route("What did I spend in May?", facts).periods == {PREV}  # a month inside the previous period
    assert route("What did I spend in March 2025?", facts).periods == {THIS}  # outside both: the default
    assert route("What is my bank balance?", facts).sections == frozenset()  # not in the facts: summary only
    assert not route("Tell me something", facts).matched  # nothing matched: every section


def test_pack_leaves_out_the_other_period_and_stays_in_budget(facts: dict):
    p = pack(facts, route("How much VAT did I reclaim last quarter?", facts))
    assert p["previous_period"]["vat"]["box4"] == "200.00" and p["previous_period"]["label"] == "Apr–Jun 2026"
    assert "vat" not in p["this_period"] and "totals" not in p["this_period"] and "418.41" not in json.dumps(p)
    assert all(f"{EVENTS}/2026-0{m}" not in s for s in p["sources"] for m in "789")  # only the asked period's files
    assert "derived" not in p and approx_tokens(p) < approx_tokens(facts)
    both = pack(facts, route("Why is my VAT higher than last quarter?", facts))
    assert both["this_period"]["vat"]["box5"] == "2081.59" and both["derived"]["box5_delta_vs_prev"] == "1281.59"
    assert "sales_net_delta_vs_prev" not in both["derived"]  # VAT only: the totals' changes are not needed
    assert approx_tokens(pack(facts, route("Tell me everything", facts))) <= PACK_TOKENS


async def test_pack_fits_the_budget_on_big_books():
    b = Books(FakeStorageProvider())
    for i in range(80):
        await b.post_event(_ev("purchase", date(2026, 7 + i % 3, 1 + i % 28), 10_000 + i, 2_000, f"Supplier with a long trading name {i}"))
        await b.post_event(_ev("sale", date(2026, 7 + i % 3, 1 + i % 28), 50_000 + i, 10_000, f"Customer with a long trading name {i}"))
    facts = await build_facts(b, Q3)
    p = pack(facts, route("Give me the full picture of suppliers, customers and the largest transactions", facts))
    assert approx_tokens(p) <= PACK_TOKENS and p["this_period"]["entries"] == 160


def test_code_key_numbers_follow_the_question(facts: dict):
    def shown(q: str) -> dict[str, str]:
        return {k.label: k.value for k in ask_ai.code_key_numbers(facts, route(q, facts))}

    assert shown("How much VAT do I owe this quarter?") == {
        "Net VAT (Box 5), 26A3": "£2,081.59", "VAT on sales (Box 1), 26A3": "£2,500.00", "VAT reclaimed (Box 4), 26A3": "£418.41"}
    assert shown("How much VAT did I reclaim last quarter?")["VAT reclaimed (Box 4), 26A2"] == "£200.00"
    assert shown("By how much has my VAT bill changed since last quarter?")["Change in Net VAT (Box 5) vs 26A2"] == "+£1,281.59"
    assert shown("How much did I spend with Howdens this quarter?")["Spent with Howdens, 26A3"] == "£2,060.00"
    assert shown("What is my bank balance?") == {}


# --------------------------------------------------------------------------- #
# Period-aware grounding: a real figure from the wrong period
# --------------------------------------------------------------------------- #

LAST_Q = "How much VAT did I reclaim last quarter?"


async def test_ground_replaces_a_figure_from_the_wrong_period(facts: dict):
    planted = _out(answer_md="You reclaimed **£418.41** in VAT last quarter.", key_numbers=[], citations=[], suggested_actions=[])
    got = ask_ai.ground(planted, facts, "m", LAST_Q)
    assert got.confidence == "low" and "418.41" in (got.fallback_reason or "") and "Jul–Sep 2026" in (got.fallback_reason or "")
    assert "£418.41" not in got.answer_md and "£200.00" in got.answer_md  # the asked period's Box 4 instead
    assert got.key_numbers[0].label == "VAT reclaimed (Box 4), 26A2" and got.key_numbers[0].value == "£200.00"
    assert got.citations and all(c.startswith(tuple(f"{EVENTS}/2026-0{m}" for m in "456")) for c in got.citations)


async def test_ground_checks_the_period_of_key_numbers_too(facts: dict):
    bad = [{"label": "VAT reclaimed", "value": "£418.41", "source": "_System/Ledger/events/2026-08/"}]
    got = ask_ai.ground(_out(answer_md="Here is what you reclaimed.", key_numbers=bad), facts, "m", LAST_Q)
    assert got.fallback_reason and "418.41" in got.fallback_reason
    labelled = [{"label": "VAT reclaimed, Jul–Sep 2026", "value": "£418.41", "source": "_System/Ledger/events/2026-08/"}]
    assert ask_ai.ground(_out(answer_md="See below.", key_numbers=labelled), facts, "m", LAST_Q).fallback_reason is None


async def test_ground_accepts_the_other_period_when_the_sentence_says_so(facts: dict):
    text = "Last quarter you reclaimed £200.00. This quarter it is £418.41."
    assert ask_ai.ground(_out(answer_md=text, key_numbers=[]), facts, "m", LAST_Q).fallback_reason is None
    text = "You owe £2,081.59, up from £800.00 in Apr–Jun 2026."
    assert ask_ai.ground(_out(answer_md=text), facts, "m", "How much VAT do I owe?").fallback_reason is None
    both = "Your VAT is £2,081.59 now against £800.00 before."  # a comparison asks about both periods
    assert ask_ai.ground(_out(answer_md=both), facts, "m", "Why is my VAT higher than last quarter?").fallback_reason is None


async def test_ground_flags_last_quarters_figure_quoted_for_this_quarter(facts: dict):
    got = ask_ai.ground(_out(answer_md="You owe £800.00 this time."), facts, "m", "How much VAT do I owe this quarter?")
    assert got.fallback_reason and "Apr–Jun 2026" in got.fallback_reason and "£2,081.59" in got.answer_md


# --------------------------------------------------------------------------- #
# Streaming
# --------------------------------------------------------------------------- #

def test_answer_text_unescapes_across_chunks():
    text = 'VAT is **£2,081.59**.\n"Box 5" — café ✓ 😀'
    reply = json.dumps({"answer_md": text, "confidence": "high"}, ensure_ascii=True)
    reader = ask_ai.AnswerText()
    assert "".join(reader.feed(reply[i:i + 3]) for i in range(0, len(reply), 3)) == text and reader.done


async def _events(facts: dict, chunks: list[str] | Exception, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    async def fake_stream(messages: list[dict], cfg: AiConfig) -> AsyncIterator[str]:
        if isinstance(chunks, Exception):
            raise chunks
        for c in chunks:
            yield c

    monkeypatch.setattr(ask_ai, "_stream_model", fake_stream)
    return [e async for e in ask_ai.answer_stream("How much VAT do I owe this quarter?", facts, [], CFG)]


async def test_answer_stream_sends_code_figures_first_then_words_then_the_checked_answer(facts: dict, monkeypatch: pytest.MonkeyPatch):
    reply = json.dumps({"answer_md": "You owe £2,081.59 for Jul–Sep 2026.", "confidence": "high"})
    events = await _events(facts, [reply[i:i + 7] for i in range(0, len(reply), 7)], monkeypatch)
    kinds = [k for k, _ in events]
    assert kinds[0] == "start" and kinds[-1] == "answer" and set(kinds[1:-1]) == {"token"}
    start, final = events[0][1], events[-1][1]
    assert start["key_numbers"][0] == {"label": "Net VAT (Box 5), 26A3", "value": "£2,081.59", "source": f"{EVENTS}/2026-07/"}
    assert "".join(t for k, t in events if k == "token") == "You owe £2,081.59 for Jul–Sep 2026."
    assert final.fallback_reason is None and final.answer_md == "You owe £2,081.59 for Jul–Sep 2026."
    assert [k.model_dump() for k in final.key_numbers] == start["key_numbers"] and final.citations == start["citations"]


async def test_answer_stream_replaces_words_that_fail_the_check(facts: dict, monkeypatch: pytest.MonkeyPatch):
    events = await _events(facts, ['{"answer_md":"You owe £9,999.00.","confidence":"high"}'], monkeypatch)
    assert ("token", "You owe £9,999.00.") in events
    assert events[-1][1].fallback_reason and "£9,999.00" not in events[-1][1].answer_md


async def test_a_reply_cut_off_by_the_length_cap_keeps_its_whole_sentences(facts: dict, monkeypatch: pytest.MonkeyPatch):
    events = await _events(facts, ['{"answer_md":"You owe £2,081.59. That is up on last quar'], monkeypatch)
    final = events[-1][1]
    assert final.fallback_reason is None and final.answer_md == "You owe £2,081.59." and final.confidence == "medium"


async def test_a_stalled_model_gets_the_fallback_not_an_error(facts: dict, monkeypatch: pytest.MonkeyPatch):
    events = await _events(facts, ask_ai.AiStalled(20), monkeypatch)
    assert [k for k, _ in events] == ["start", "answer"] and "stopped replying for 20 s" in events[-1][1].fallback_reason


async def test_the_timeout_is_per_chunk_not_per_answer(monkeypatch: pytest.MonkeyPatch):
    class Slow:
        def __init__(self, gaps: list[float]) -> None:
            self.gaps = gaps

        async def aiter_lines(self) -> AsyncIterator[str]:
            for i, gap in enumerate(self.gaps):
                await asyncio.sleep(gap)
                yield f"line {i}"

    monkeypatch.setattr(ask_ai, "FIRST_CHUNK_S", 0.3)
    monkeypatch.setattr(ask_ai, "TOKEN_GAP_S", 0.1)
    steady = [line async for line in ask_ai._lines(Slow([0.2] + [0.05] * 12))]  # 0.8 s in all, but no long gap
    assert len(steady) == 13
    with pytest.raises(ask_ai.AiStalled):
        _ = [line async for line in ask_ai._lines(Slow([0.05, 0.05, 0.2]))]


def _transport(monkeypatch: pytest.MonkeyPatch, body: str, seen: list[httpx.Request]) -> None:
    """Every httpx client the backends open answers with `body` (the wire format of a streamed reply)."""
    real = httpx._client.AsyncClient  # not the name a previous call may have patched

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=body)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


async def test_stream_json_model_reads_both_wire_formats(monkeypatch: pytest.MonkeyPatch):
    seen: list[httpx.Request] = []
    ollama = "\n".join(json.dumps({"message": {"content": c}, "done": False}) for c in ('{"answer_md":"Hi', '."}'))
    _transport(monkeypatch, ollama + "\n" + json.dumps({"message": {"content": ""}, "done": True}) + "\n", seen)
    got = [t async for t in ask_ai.stream_json_model([], CFG, {}, "n", 320)]
    assert got == ['{"answer_md":"Hi', '."}'] and seen[-1].url.path == "/api/chat"
    assert json.loads(seen[-1].content)["options"]["num_predict"] == 320

    sse = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n\n" for c in ("a", "b")) + "data: [DONE]\n\n"
    _transport(monkeypatch, sse, seen)
    key = AiConfig(mode="key", base_url="http://api.invalid/v1", model="m", api_key="k")
    assert [t async for t in ask_ai.stream_json_model([], key, {}, "n", 1500)] == ["a", "b"]
    assert seen[-1].url.path == "/v1/chat/completions" and json.loads(seen[-1].content)["max_tokens"] == 1500


async def test_a_garbled_chunk_gets_the_fallback_not_an_error(facts: dict, monkeypatch: pytest.MonkeyPatch):
    _transport(monkeypatch, '{"message":{"content":"{\\"answer_md\\""}}\nnot json\n', [])
    got = await ask_ai.answer("How much VAT do I owe this quarter?", facts, [], CFG)
    assert got.fallback_reason == "Your AI (local) sent a reply that could not be read." and "£2,081.59" in got.answer_md
    events = [e async for e in ask_ai.answer_stream("How much VAT do I owe this quarter?", facts, [], CFG)]
    assert [k for k, _ in events] == ["start", "answer"] and events[-1][1].fallback_reason


async def test_ask_route_streams_server_sent_events(books: Books, monkeypatch: pytest.MonkeyPatch):
    from app.main import app
    from app.routes_books import get_books

    async def fake_stream(messages: list[dict], cfg: AiConfig) -> AsyncIterator[str]:
        for c in ('{"answer_md":"You owe ', "£2,081.59", '.","confidence":"high"}'):
            yield c

    async def override():
        yield books

    monkeypatch.setattr(ask_ai, "_stream_model", fake_stream)
    app.dependency_overrides[get_books] = override
    try:
        headers = {"X-Graph-Token": "t", "X-AI-Mode": "local", "X-AI-Model": "muse-glimmer:30b"}
        body = {"question": "How much VAT do I owe this quarter?", "period": {"start": "2026-07-01", "end": "2026-09-30"}}
        r = TestClient(app).post("/books/ask?stream=1", json=body, headers=headers)
        plan = TestClient(app).post("/books/ask?stream=1", json={"question": "Plan my Thursday"}, headers=headers)
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = [(b.split("\n")[0].removeprefix("event: "), json.loads(b.split("\n")[1].removeprefix("data: ")))
              for b in r.text.strip().split("\n\n")]
    assert [e for e, _ in events] == ["start", "token", "token", "token", "answer"]
    assert events[0][1]["key_numbers"][0]["value"] == "£2,081.59"
    assert events[-1][1]["answer_md"] == "You owe £2,081.59." and events[-1][1]["fallback_reason"] is None
    assert plan.text.startswith("event: answer\n") and '"plan_day"' in plan.text  # no model call: just the answer
