"""AI search in Ask (app/ai_search.py): the AI reads the words into a query, code checks it, searches the books, Sync
PayPal and PayPal's own history, and writes the answer with every figure in pence. The owner's two examples run on
the demo books (typed and spoken); the model is stubbed per call name."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger.events import LedgerEvent, Line
from app import ai_search as s
from app import demo, paypal_sync
from app.ai import ask as ask_ai
from app.ai.config import AiConfig
from app.books import Books
from app.schemas import AskPeriod, AskTurn

DAY = date(2026, 11, 11)
PERIOD = AskPeriod(start=date(2026, 10, 1), end=date(2026, 12, 31))
CFG = AiConfig(mode="local", base_url="http://ollama.invalid", model="stub-model")
QA = "Did that client pay all the arrears? They had around £500 overdue — check PayPal."
QB = "There was a payment via PayPal last month, probably around £100 for stationery — how much exactly was it?"
H = {"X-Graph-Token": "t", "X-User": "sam@example.co.uk", "X-AI-Mode": "local", "X-AI-Model": "stub-model"}


@pytest.fixture(autouse=True)
def _no_live_paypal(monkeypatch: pytest.MonkeyPatch):
    for k in ("ACCNOMOS_TEST_MODE", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_DIRECT", "PAYPAL_BASE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(s, "_today", lambda: DAY)


@pytest.fixture(scope="module")
def storage() -> FakeStorageProvider:
    return asyncio.run(demo.build_full(DAY)).storage


@pytest.fixture
def company(storage: FakeStorageProvider) -> Books:
    copy = FakeStorageProvider()
    copy.files = dict(storage.files)
    copy.folders = set(storage.folders)
    return Books(copy)


def stub(monkeypatch: pytest.MonkeyPatch, reply: dict[str, Any] | None) -> list[str]:
    """The AI's query reply (None: the AI cannot be reached). Returns the names of the calls made."""
    calls: list[str] = []

    async def fake(messages: list[dict], cfg: AiConfig, schema: dict, name: str) -> str:
        calls.append(name)
        if reply is None or name != "ai_search":
            raise httpx.ConnectError("offline")
        return json.dumps(reply)

    monkeypatch.setattr(ask_ai, "call_json_model", fake)
    return calls


def query(**kw: Any) -> dict[str, Any]:
    base = {
        "kind": "payment_search",
        "counterparty_hint": "",
        "amount_pence": None,
        "amount_tolerance_pct": None,
        "direction": "any",
        "date_range": "none",
        "month": None,
        "keywords": [],
        "sources": "both",
    }
    return {**base, **kw}


# --------------------------------------------------------------------------- #
# Intent and the query (code)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("q", "kind"),
    [
        (QA, "customer_paid_check"),
        (QB, "payment_search"),
        ("has JM Trading paid?", "customer_paid_check"),
        ("did I pay Screwfix in October?", "payment_search"),
        ("who owes me money?", None),
        ("what did PayPal cost me this quarter?", None),
        ("how much is sitting in PayPal?", None),
        ("what is waiting in Sync PayPal?", None),
        ("what profit did I make last month?", None),
        ("how much did I spend on stationery last month?", None),
        ("send a PayPal reminder to everyone who owes me", None),
        ("how do I connect PayPal?", None),
    ],
)
def test_intent(q: str, kind: str | None) -> None:
    assert s.intent(q) == kind


def test_amounts_and_last_month_across_the_year_boundary() -> None:
    assert s.amounts_said("around £100, or £1,250.50, maybe £2k or 40 pounds") == [10000, 125050, 200000, 4000]
    q = s.code_query(QB, "payment_search", date(2026, 1, 5))
    assert (q.start, q.end) == (date(2025, 12, 1), date(2025, 12, 31))
    assert q.amount_pence == 10000 and q.tolerance_pct == 20 and q.direction == "out" and q.sources == "paypal"
    assert "stationery" in q.keywords and "office supplies" in q.keywords
    # the model may only name a range; code works out the dates
    out = s.ModelQuery.model_validate(query(date_range="last_month", amount_pence=10000))
    got = s.check_query(out, "a payment of about £100?", "", "payment_search", date(2026, 1, 5))
    assert (got.start, got.end) == (date(2025, 12, 1), date(2025, 12, 31))


def test_code_keeps_the_model_honest() -> None:
    out = s.ModelQuery.model_validate(
        query(amount_pence=99999, amount_tolerance_pct=95, counterparty_hint="Acme Widgets", keywords=["!!", "pens"])
    )
    got = s.check_query(out, "did we pay about £100 for pens?", "", "payment_search", DAY)
    assert got.amount_pence == 10000  # the question's amount, not the model's
    assert got.tolerance_pct == s.MAX_TOLERANCE
    assert got.counterparty is None  # not in the question or the conversation
    assert got.keywords == ["pens"]
    named = s.check_query(
        s.ModelQuery.model_validate(query(counterparty_hint="Oak & Ash Interiors")),
        "did they pay?",
        "What does Oak & Ash Interiors owe me?",
        "payment_search",
        DAY,
    )
    assert named.counterparty == "Oak & Ash Interiors"


# --------------------------------------------------------------------------- #
# The owner's two examples, on the demo books
# --------------------------------------------------------------------------- #


async def test_example_a_that_client_paid_the_arrears_through_paypal(company: Books, monkeypatch) -> None:
    calls = stub(monkeypatch, query(kind="customer_paid_check", amount_pence=50000, direction="in", sources="paypal"))
    a = await s.answer(QA, [], company, CFG, PERIOD, DAY, demo=True)
    assert a is not None and calls == ["ai_search"] and a.fallback_reason is None
    assert a.answer_md.startswith("I took that client to be Wrenfield Dental Studio, whose £492.00 overdue")
    assert "Yes, the arrears look paid in full: **£492.00**" in a.answer_md
    assert "not in your books yet" in a.answer_md and "(/invoices#paypal-sync)" in a.answer_md
    assert "Oak & Ash Interiors Ltd has £600.00 overdue" in a.answer_md
    assert [k.value for k in a.key_numbers] == ["£492.00", "£492.00", "£492.00"]
    assert any(c.startswith("paypal:") for c in a.citations) and "invoice:INV-0007" in a.citations
    assert a.model == "code"


async def test_example_a_with_the_client_named_earlier(company: Books, monkeypatch) -> None:
    stub(monkeypatch, None)
    owed = "Oak & Ash Interiors Ltd owes you £600.00, all of it overdue."
    history = [AskTurn(role="user", text="Who owes me money?"), AskTurn(role="assistant", text=owed)]
    a = await s.answer(QA, history, company, CFG, PERIOD, DAY, demo=True)
    assert a is not None and a.answer_md.startswith(
        "No: £600.00 is still overdue from Oak & Ash Interiors Ltd on INV-0005"
    )
    assert a.fallback_reason and "Code read your question" in a.fallback_reason


async def test_example_b_stationery_paid_through_paypal_last_month(company: Books, monkeypatch) -> None:
    stub(monkeypatch, query(amount_pence=10000, direction="out", date_range="last_month", keywords=["stationery"],
                            sources="paypal"))  # fmt: skip
    a = await s.answer(QB, [], company, CFG, PERIOD, DAY, demo=True)
    assert a is not None
    assert a.answer_md.startswith("It was **£97.79** on 14 Oct 2026 to Quillstone Office Supplies Ltd through PayPal")
    assert "not in your books yet" in a.answer_md and "1 Oct 2026 to 31 Oct 2026" in a.answer_md
    assert a.key_numbers[0].value == "£97.79"


async def test_model_failure_falls_back_to_code_and_still_answers(company: Books, monkeypatch) -> None:
    stub(monkeypatch, None)
    a = await s.answer(QB, [], company, CFG, PERIOD, DAY, demo=True)
    assert a is not None and "**£97.79**" in a.answer_md
    assert "could not be reached" in (a.fallback_reason or "")
    off = await s.answer(QB, [], company, None, PERIOD, DAY, demo=True)
    assert off is not None and "**£97.79**" in off.answer_md and "No AI is set up" in (off.fallback_reason or "")


async def test_ambiguous_client_asks_which(company: Books, monkeypatch) -> None:
    stub(monkeypatch, None)
    a = await s.answer("Did that client pay? check PayPal", [], company, None, PERIOD, DAY, demo=True)
    assert a is not None and a.answer_md.startswith("Which customer do you mean?")
    assert a.answer_md.count("overdue)") == 3


async def test_amount_tolerance_and_nothing_found(company: Books, monkeypatch) -> None:
    stub(monkeypatch, None)
    a = await s.answer(
        "There was a PayPal payment last month, exactly £150 for stationery — how much exactly was it?",
        [], company, None, PERIOD, DAY, demo=True,
    )  # fmt: skip
    assert a is not None and a.answer_md.startswith("I found no payment that fits.")
    assert "£142.50 to £157.50 (within 5% of £150.00)" in a.answer_md and "1 Oct 2026 to 31 Oct 2026" in a.answer_md
    assert a.key_numbers == [] and a.citations == []


# --------------------------------------------------------------------------- #
# Books, Sync PayPal and PayPal together
# --------------------------------------------------------------------------- #


def _bought(day: date, pence: int, who: str) -> LedgerEvent:
    net, vat = pence * 5 // 6, pence - pence * 5 // 6
    return LedgerEvent(
        kind="purchase",
        date=day,
        lines=[
            Line(account="7500 Office supplies", debit=net, memo="Printer paper"),
            Line(account="2200 VAT control", debit=vat),
            Line(account="1200 Bank", credit=pence),
        ],
        approved_by="sam@example.co.uk",
        approved_at=datetime(2026, 11, 1, 9, 0),
        counterparty=who,
        net=net,
        vat=vat,
    )


async def test_books_match_with_vat_and_account_and_two_close_ones_listed(monkeypatch) -> None:
    books = Books(FakeStorageProvider())
    await books.post_event(_bought(date(2026, 10, 3), 10200, "Penbury Stationers"))
    await books.post_event(_bought(date(2026, 10, 20), 11500, "Inkwell & Co"))
    a = await s.answer("did we pay about £100 for stationery last month? how much exactly", [], books, None, PERIOD,
                       DAY)  # fmt: skip
    assert a is not None and a.answer_md.startswith("2 payments fit")
    assert "**£102.00** on 3 Oct 2026 to Penbury Stationers" in a.answer_md
    assert "in your books; posted to 7500 Office supplies, VAT £17.00" in a.answer_md
    assert "The closest is the first: £102.00 to Penbury Stationers." in a.answer_md
    assert all(c.startswith("_System/Ledger/events/2026-10/") for c in a.citations)


async def test_waiting_in_sync_paypal_is_said_and_not_posted(monkeypatch) -> None:
    books = Books(FakeStorageProvider())
    item = paypal_sync.SyncItem(
        transaction_id="9AB12345CD678901E",
        date=date(2026, 10, 14),
        kind="expense",
        status="proposed",
        event_code="T0006",
        name="Quillstone Office Supplies Ltd",
        items=["A4 copier paper"],
        gross_pence=-9779,
        net_pence=-9779,
        account="7500 Office supplies",
        found_at=datetime(2026, 11, 1, 9, 0),
    )
    await books.write_json(
        paypal_sync.SYNC, paypal_sync.SyncState(items={item.transaction_id: item}).model_dump(mode="json")
    )
    a = await s.answer(QB, [], books, None, PERIOD, DAY)
    assert a is not None and "**£97.79** on 14 Oct 2026" in a.answer_md
    assert "it is in [Sync PayPal](/invoices#paypal-sync), waiting for your approval" in a.answer_md
    assert "PayPal itself was not searched" in a.answer_md  # not connected, not a demo
    assert await books.list_events() == []


# --------------------------------------------------------------------------- #
# Through the Ask route: typed and spoken take the same path
# --------------------------------------------------------------------------- #


def _client(books: Books):
    from app.main import app
    from app.routes_books import get_books

    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    return app, TestClient(app)


def test_typed_and_spoken_on_the_route(company: Books, monkeypatch) -> None:
    from app.ai import stt, voice
    from app.schemas import Transcription

    stub(monkeypatch, None)
    monkeypatch.setattr(demo, "is_demo_request", lambda request: True)

    class Heard:
        text = QA
        by = Transcription(provider="local", label="speech-to-text on our server", model="whisper-stub")

    async def fake_transcribe(wav, providers, **_):
        return Heard()

    async def fake_wav(data, ctype, name):
        return b"RIFF"

    monkeypatch.setattr(stt, "chain", lambda cfg: ["local"])
    monkeypatch.setattr(stt, "transcribe", fake_transcribe)
    monkeypatch.setattr(voice, "require_ffmpeg", lambda: None)
    monkeypatch.setattr(voice, "to_wav", fake_wav)
    monkeypatch.setattr("app.routes_ask.today", lambda tz=None: DAY)
    app, client = _client(company)
    try:
        typed = client.post("/books/ask", json={"question": QB}, headers=H)
        spoken = client.post("/books/ask/voice", files={"audio": ("q.webm", b"\x1a\x45", "audio/webm")}, headers=H)
    finally:
        app.dependency_overrides.clear()
    assert typed.status_code == 200, typed.text
    assert typed.json()["answer_md"].startswith("It was **£97.79** on 14 Oct 2026")
    assert spoken.status_code == 200, spoken.text
    body = spoken.json()
    assert body["transcript"] == QA and "Yes, the arrears look paid in full: **£492.00**" in body["answer_md"]


def test_last_month_day_is_in_the_month_before() -> None:
    from app.online_fakes import _last_month_day

    assert _last_month_day(date(2026, 1, 5)) == date(2025, 12, 14)
    assert _last_month_day(date(2026, 3, 1)) == date(2026, 2, 14)
    assert _last_month_day(date(2026, 11, 11)) - timedelta(days=0) == date(2026, 10, 14)


def test_test_mode_stub_reply_is_a_valid_query() -> None:
    from app import testmode

    for q in (QA, QB):
        raw = testmode.ai_search_reply(f"TODAY: 2026-11-04\nHISTORY: []\nQUESTION: {q}")
        out = s.ModelQuery.model_validate(raw)
        got = s.check_query(out, q, "", s.intent(q) or "payment_search", date(2026, 11, 4))
        assert got.amount_pence in (50000, 10000) and got.read_by == "model"
    b = s.check_query(s.ModelQuery.model_validate(testmode.ai_search_reply(f"TODAY: 2026-11-04\nQUESTION: {QB}")), QB,
                      "", "payment_search", date(2026, 11, 4))  # fmt: skip
    assert (b.start, b.end) == (date(2026, 10, 1), date(2026, 10, 31)) and "stationery" in b.keywords


def test_code_settles_money_out_when_the_model_says_in() -> None:
    """Live 11 Nov: the model read "a payment via PayPal … for stationery" as money in and the search missed it."""
    from app import ai_search

    q = "There was a payment via PayPal last month, probably around £100 for stationery — how much exactly was it?"
    assert ai_search._direction("in", q) == "out"
    assert ai_search._direction("in", "Did we receive anything from Wrenfield?") in {"in", "any"}
