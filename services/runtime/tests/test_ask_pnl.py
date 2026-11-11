"""Ask's profit-and-loss and "what did we buy for this job" answers (app/ask_pnl.py, app/ask_router.py), on a fixture
ledger and on the company demo's books (app/demo_recent.py: recent trading up to the demo's today)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

import pytest

from accnomos_ledger import LedgerEvent, compute_vat_return
from accnomos_ledger.events import Line, VatCode
from app import actions, ask_more, ask_pnl, demo_recent
from app import demo_personal as dp
from app.actions import IntentModelOutput
from app.ai import ask as ask_ai
from app.ai.config import AiConfig
from app.ask_router import pnl_intent, pnl_span
from app.books import Books
from app.routes_vat import box_amounts
from app.schemas import AskPeriod, ProposedAction

DAY = date(2026, 11, 4)  # a Wednesday: the stage day
PERIOD = AskPeriod(start=date(2026, 10, 1), end=date(2026, 12, 31))
CFG = AiConfig(mode="local", base_url="http://ollama.invalid", model="stub-model")


# --------------------------------------------------------------------------- #
# Which questions, which span
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("question", "pnl"),
    [
        ("How much profit did we make yesterday?", True),
        ("What is our profit this quarter?", True),
        ("What was our profit last quarter?", True),
        ("what's our margin this month", True),
        ("What were our total sales last month?", True),
        ("How much did we spend this week?", True),
        ("sales in October", True),
        ("What were my sales this quarter?", False),  # whole VAT quarter: the VAT facts pack
        ("How much VAT do I owe this quarter?", False),
        ("what profit is in box 6?", False),
        ("Who owes me the most?", False),
    ],
)
def test_pnl_intent(question: str, pnl: bool) -> None:
    assert pnl_intent(question) is pnl


@pytest.mark.parametrize(
    ("question", "start", "end", "name"),
    [
        ("profit today", DAY, DAY, "today"),
        ("profit yesterday", date(2026, 11, 3), date(2026, 11, 3), "yesterday"),
        ("profit this week", date(2026, 11, 2), DAY, "this week so far"),
        ("profit last week", date(2026, 10, 26), date(2026, 11, 1), "last week"),
        ("profit this month", date(2026, 11, 1), DAY, "this month so far"),
        ("profit last month", date(2026, 10, 1), date(2026, 10, 31), "last month"),
        ("profit this quarter", date(2026, 10, 1), DAY, "this quarter so far"),
        ("profit last quarter", date(2026, 7, 1), date(2026, 9, 30), "last quarter"),
        ("profit this tax year", date(2026, 4, 6), DAY, "this tax year so far"),
        ("profit last tax year", date(2025, 4, 6), date(2026, 4, 5), "last tax year"),
        ("profit in September", date(2026, 9, 1), date(2026, 9, 30), "September 2026"),
        ("profit in December", date(2025, 12, 1), date(2025, 12, 31), "December 2025"),  # the latest December
        ("profit so far", date(2026, 1, 1), DAY, "this year so far"),
    ],
)
def test_pnl_span(question: str, start: date, end: date, name: str) -> None:
    s = pnl_span(question, DAY)
    assert (s.start, s.end, s.name) == (start, end, name)


def _ev(kind: Literal["sale", "purchase"], day: date, account: str, net: int, vat: int = 0) -> LedgerEvent:
    sale = kind == "sale"

    def ln(acct: str, pence: int, credit: bool, code: VatCode | None = None) -> Line:
        return Line(account=acct, debit=0 if credit else pence, credit=pence if credit else 0, vat_code=code)

    lines = [ln(account, net, sale, VatCode.STANDARD), ln("1100 Debtors" if sale else "1200 Bank", net + vat, not sale)]
    if vat:
        lines.append(ln("2200 VAT control", vat, sale))
    return LedgerEvent(
        kind=kind, date=day, lines=lines, approved_by="t", approved_at=datetime.now(UTC), net=net, vat=vat
    )


LEDGER = [
    _ev("sale", date(2026, 9, 29), "4000 Sales", 100_000, 20_000),  # last quarter
    _ev("sale", date(2026, 10, 14), "4000 Sales", 240_000, 48_000),
    _ev("purchase", date(2026, 10, 20), "5000 Materials", 30_550, 6_110),
    _ev("sale", date(2026, 11, 3), "4000 Sales", 48_000, 9_600),  # yesterday
    _ev("purchase", date(2026, 11, 3), "5000 Materials", 10_660, 2_132),
]


@pytest.mark.parametrize(
    ("question", "income", "costs", "profit", "margin"),
    [
        ("How much profit did we make yesterday?", "£480.00", "£106.60", "£373.40", "77.8"),
        ("What is our profit this quarter?", "£2,880.00", "£412.10", "£2,467.90", "85.7"),
        ("What was our profit last quarter?", "£1,000.00", "£0.00", "£1,000.00", "100.0"),
        ("profit today", "£0.00", "£0.00", "£0.00", None),
    ],
)
def test_pnl_facts_on_a_fixture_ledger(question: str, income: str, costs: str, profit: str, margin: str | None) -> None:
    f = ask_pnl.pnl_facts(LEDGER, pnl_span(question, DAY))
    assert (f["income"], f["costs"], f["profit"], f.get("margin_percent")) == (income, costs, profit, margin)
    text = ask_pnl.pnl_code_text(f)
    assert not ask_ai.KnownNumbers(f).unknown(text, all_tokens=False)  # code's words quote only the facts
    if f["entries"]:
        assert f"income was {income}" in text and f"of {profit}" in text
    else:
        assert text.startswith("Nothing was recorded for today (4 Nov 2026)")


def test_pnl_model_words_must_quote_the_facts() -> None:
    f = ask_pnl.pnl_facts(LEDGER, pnl_span("profit yesterday", DAY))
    shown = {k: v for k, v in f.items() if not k.startswith("_")}
    assert ask_more.check("You made £373.40 profit yesterday.", shown) is None
    assert "£999.00" in (ask_more.check("You made £999.00 profit yesterday.", shown) or "")


def test_loss_and_no_margin_without_income() -> None:
    f = ask_pnl.pnl_facts(LEDGER[2:3], pnl_span("profit in October", DAY))
    assert f["result"] == "loss" and f["profit"] == "-£305.50" and "margin_percent" not in f


# --------------------------------------------------------------------------- #
# The company demo: recent trading up to its today
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def company() -> Books:
    from app import demo

    return Books(asyncio.run(demo.build_full(DAY)).storage)


async def test_demo_vat_jul_sep_unchanged_and_oct_dec_sensible(company: Books) -> None:
    events = await company.list_events()
    q3 = box_amounts(compute_vat_return(events, "26A3", date(2026, 7, 1), date(2026, 9, 30)))
    assert (q3[1], q3[4], q3[5], q3[6], q3[7]) == ("3857.63", "50.30", "3807.33", "19288", "1698")  # as filed
    q4 = box_amounts(compute_vat_return(events, "26A4", date(2026, 10, 1), date(2026, 12, 31)))
    # the recent sales and costs, and the three bills to pay through PayPal (input VAT £19.00 + £25.60 + £21.00)
    assert (q4[1], q4[4], q4[5], q4[6]) == ("646.00", "213.78", "432.22", "3230")
    review = [p for p in await company.list_proposals() if p.status != "posted"]
    assert len(review) == 6  # Review still shows "6 waiting for you": the recent documents are all approved


async def test_demo_profit_yesterday_and_this_quarter(company: Books) -> None:
    y = await ask_pnl.pnl_answer("How much profit did we make yesterday?", company, None, PERIOD, DAY)
    assert y.answer_md.startswith("For yesterday (3 Nov 2026), income was £480.00 and costs were £106.60")
    assert [(k.label, k.value) for k in y.key_numbers[:3]] == [
        ("Income, yesterday", "£480.00"),
        ("Costs, yesterday", "£106.60"),
        ("Profit, yesterday", "£373.40"),
    ]
    assert y.citations == ["_System/Ledger/events/2026-11/"] and y.period.start == date(2026, 11, 3)
    q = await ask_pnl.pnl_answer("What is our profit this quarter?", company, None, PERIOD, DAY)
    assert "this quarter so far (1 Oct 2026 – 4 Nov 2026), income was £3,230.00" in q.answer_md
    last = await ask_pnl.pnl_answer("What was our profit last quarter?", company, None, PERIOD, DAY)
    assert "income was £19,288.15" in last.answer_md  # box 6 of the Jul–Sep return, to the penny


async def test_demo_recent_dates_follow_the_day() -> None:
    from types import SimpleNamespace

    from app import sample_books

    seed = sample_books.seed_module()
    early = demo_recent.planned(seed, SimpleNamespace(current=(date(2027, 1, 1), date(2027, 3, 31)),
                                                      business="B"), date(2027, 1, 2))  # fmt: skip
    assert early and all(d.date >= date(2027, 1, 1) for d in early)  # never inside the finished quarter
    assert {d.date for d in early} == {date(2027, 1, 1), date(2027, 1, 2)}


@pytest.mark.parametrize(
    ("question", "start"),
    [
        ("Which colour tiles did we order for the Kitchen fit-out, Harrogate job?",
         "For Kitchen fit-out, Harrogate you bought Matt white metro tiles 300×100, 8 m² from Harrogate Tile & Stone "
         "Ltd on 23 Oct 2026 (£196.00)"),
        ("What items did we order for the Kitchen fit-out, Harrogate job?",
         "For Kitchen fit-out, Harrogate you have 5 purchases, £2,028.80 before VAT"),
        ("what did we buy for the kitchen job?", "For Kitchen fit-out, Harrogate you have 5 purchases"),
    ],
)  # fmt: skip
async def test_demo_what_was_bought_for_a_job(company: Books, question: str, start: str) -> None:
    a = await ask_pnl.job_items_answer(question, company, None, PERIOD)
    assert a is not None and a.answer_md.startswith(start), a and a.answer_md
    if "items" in question:
        for item in ("Oak worktop 3 m", "Brushed brass handles ×12", "Matt white metro tiles 300×100, 8 m²"):
            assert item in a.answer_md
    assert a.citations and all(c.startswith("_System/Ledger/events/") for c in a.citations)
    assert a.key_numbers[0].label == "Bought for Kitchen fit-out, Harrogate (before VAT)"


async def test_job_items_leaves_other_questions_alone(company: Books) -> None:
    assert await ask_pnl.job_items_answer("What did I spend on fuel in March?", company, None, PERIOD) is None
    assert await ask_pnl.job_items_answer("How much VAT do I owe?", company, None, PERIOD) is None
    said = "Remember to order 2-inch bolts for the Kitchen fit-out, Harrogate job."  # an instruction: shopping list
    assert await ask_pnl.job_items_answer(said, company, None, PERIOD) is None
    unknown = await ask_pnl.job_items_answer("what did we order for the Leeds loft job?", company, None, PERIOD)
    assert unknown is not None and "couldn't find a job" in unknown.answer_md


async def test_demo_ellie_two_hours_with_one_overtime(company: Books, monkeypatch: pytest.MonkeyPatch) -> None:
    reply = IntentModelOutput.model_validate(
        {f: None for f in IntentModelOutput.model_fields}
        | {
            "kind": "log_timesheet",
            "staff_ref": "Ellie",
            "job_ref": "Kitchen fit-out, Harrogate job",
            "hours_text": "2",
        }
    )

    async def fake(messages: list[dict[str, Any]], cfg: AiConfig, schema: dict[str, Any], name: str) -> str:
        return reply.model_dump_json()

    monkeypatch.setattr(ask_ai, "call_json_model", fake)
    q = "Add 2 hours for Ellie on the Kitchen fit-out, Harrogate job, including 1 hour overtime at double rate"
    card = await actions.propose(q, company, CFG, "tok", DAY)
    assert isinstance(card, ProposedAction), card
    assert card.preview["staff_name"] == "Ellie Hale" and card.preview["job_name"] == "Kitchen fit-out, Harrogate"
    assert [(ln["hours"], ln["multiplier"], ln["cost_pence"]) for ln in card.preview["lines"]] == [
        ("1", "1", 1100),
        ("1", "2", 2200),
    ]
    assert card.preview["cost_pence"] == 3300 and card.tap_only
    assert Decimal(card.preview["hours"]) == 2


async def test_household_yesterday_and_this_week() -> None:
    books = Books(await dp.build_storage(DAY))
    a = await ask_more.household_answer("How much did we spend yesterday?", books, None, PERIOD, DAY)
    assert a.answer_md.startswith("Yesterday (3 Nov 2026), £") and "went out" in a.answer_md
    assert a.key_numbers[0].label == "Money out, yesterday (3 Nov 2026)"
    w = await ask_more.household_answer("what did we spend this week?", books, None, PERIOD, DAY)
    assert w.answer_md.startswith("This week so far (2 Nov 2026 – 4 Nov 2026)")


@pytest.mark.parametrize(
    ("question", "start"),
    [
        ("How much profit did we make yesterday?", "For yesterday (3 Nov 2026), income was £480.00"),
        ("What is our profit this quarter?", "For this quarter so far (1 Oct 2026 – 4 Nov 2026), income was £3,230.00"),
        ("What was our profit last quarter?", "For last quarter (1 Jul 2026 – 30 Sep 2026), income was £19,288.15"),
        ("Which colour tiles did we order for the Kitchen fit-out, Harrogate job?",
         "For Kitchen fit-out, Harrogate you bought Matt white metro tiles 300×100, 8 m²"),
    ],
)  # fmt: skip
def test_demo_questions_through_the_ask_route(
    company: Books, monkeypatch: pytest.MonkeyPatch, question: str, start: str
) -> None:
    from fastapi.testclient import TestClient

    from app import routes_ask
    from app.ai.config import ai_config_from_request
    from app.main import app
    from app.routes_actions import graph_token
    from app.routes_books import get_books

    async def override():  # noqa: ANN202
        yield company

    monkeypatch.setattr(routes_ask, "today", lambda *_a: DAY)
    app.dependency_overrides[get_books] = override
    app.dependency_overrides[ai_config_from_request] = lambda: None
    app.dependency_overrides[graph_token] = lambda: "t"
    try:
        r = TestClient(app).post("/books/ask", headers={"X-Graph-Token": "t"}, json={"question": question})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    assert r.json()["answer_md"].startswith(start), r.json()["answer_md"]
