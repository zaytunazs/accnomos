"""GET /books/home and Home's summary: facts by code, words checked, code fallback. No real model.

The books are test_dashboard.py's: one Monzo statement with a matched sale, a Starling statement nothing matched on,
one overdue invoice, one proposal and one needs-a-look, VAT on calendar quarters.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_dashboard import TODAY, books, client, fake  # noqa: F401  shared fixtures (pytest puts tests/ on the path)

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger.bank import BankLine
from app import home_overview as ho
from app import profile as profile_mod
from app.ai import home_summary as hs
from app.ai.ask import KnownNumbers
from app.ai.config import AiConfig
from app.books import Books

H = {"X-Graph-Token": "tok"}
CFG = AiConfig(mode="local", base_url="http://ollama.invalid", model="stub")


def _line(d: date, pence: int, status: str = "unmatched") -> BankLine:
    return BankLine(
        id=f"{d:%Y%m%d}{pence:+}", date=d, amount_pence=pence, description="x", source_file="s.csv", status=status
    )  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Pure pieces
# --------------------------------------------------------------------------- #


def test_money_in_and_out_leaves_out_transfers_and_ignored_lines() -> None:
    lines = [
        _line(date(2026, 10, 2), 10000),
        _line(date(2026, 10, 3), -2500),
        _line(date(2026, 10, 4), -9999, "transfer"),
        _line(date(2026, 10, 5), 7777, "ignored"),
        _line(date(2026, 9, 30), 5000),
        _line(date(2026, 9, 1), -1200, "matched"),
        _line(date(2026, 8, 31), 99999),  # before last month
        _line(date(2026, 10, 28), 4242),  # after today
    ]
    m = ho.money(lines, date(2026, 10, 27))
    assert (m.this_month.label, m.this_month.money_in_pence, m.this_month.money_out_pence) == (
        "October 2026",
        10000,
        2500,
    )
    assert (m.last_month.label, m.last_month.money_in_pence, m.last_month.money_out_pence) == (
        "September 2026",
        5000,
        1200,
    )
    assert m.last_month.start == date(2026, 9, 1) and m.last_month.end == date(2026, 9, 30)


@pytest.mark.parametrize(
    ("today", "end", "due"),
    [
        (date(2026, 4, 6), date(2026, 4, 5), date(2026, 5, 7)),  # last year's Q4 is still ahead
        (date(2026, 5, 8), date(2026, 7, 5), date(2026, 8, 7)),
        (date(2026, 8, 7), date(2026, 7, 5), date(2026, 8, 7)),  # due today
        (date(2026, 10, 27), date(2026, 10, 5), date(2026, 11, 7)),
        (date(2026, 11, 8), date(2027, 1, 5), date(2027, 2, 7)),
        (date(2027, 2, 8), date(2027, 4, 5), date(2027, 5, 7)),
    ],
)
def test_next_income_tax_update_follows_gov_uk_deadlines(today: date, end: date, due: date) -> None:
    i = ho.next_itsa(today)
    assert (i.period_end, i.due, i.days_left) == (end, due, (due - today).days)


def test_self_assessment_is_31_january() -> None:
    assert ho.self_assessment_due(date(2026, 10, 27)) == date(2027, 1, 31)
    assert ho.self_assessment_due(date(2027, 1, 31)) == date(2027, 1, 31)
    assert ho.self_assessment_due(date(2027, 2, 1)) == date(2028, 1, 31)


# --------------------------------------------------------------------------- #
# The summary
# --------------------------------------------------------------------------- #

FACTS: dict[str, Any] = {
    "today": "27 Oct 2026",
    "kind": "company",
    "cash": {"balance": "£5,400.00", "as_of": "24 Oct 2026"},
    "money": {
        "this_month": {"label": "October 2026 so far", "in": "£405.00", "out": "£55.00"},
        "last_month": {"label": "September 2026", "in": "£0.00", "out": "£0.00"},
    },
    "this_week": {"in": "£405.00", "out": "£55.00", "approved": 1, "proposed": 1},
    "needs_doing": {"in_review": 2, "unmatched_bank_lines": 3, "overdue_invoices": 1},
    "overdue": {"invoices": 1, "amount": "£405.00"},
    "next_deadline": {"what": "VAT return Jul–Sep 2026", "due": "7 Nov 2026", "days_left": 11},
}


def _figures(text: str) -> list[str]:
    return [t for t in re.findall(r"£[\d,]+(?:\.\d+)?|\d[\d,]*(?:\.\d+)?", text) if not re.fullmatch(r"\d{1,2}", t)]


def test_fallback_says_each_thing_in_order_and_only_quotes_facts() -> None:
    text = hs.fallback_summary(FACTS)
    assert text == (
        "You had £5,400.00 in the bank on 24 Oct 2026. "
        "October 2026 so far, £405.00 came in and £55.00 went out, against £0.00 in and £0.00 out in September 2026. "
        "To do: 2 items waiting in Review, 3 bank lines to match and 1 invoice overdue (£405.00). "
        "Next deadline: VAT return Jul–Sep 2026, due 7 Nov 2026 (in 11 days)."
    )
    assert 2 <= len(re.findall(r"[.!?](?:\s|$)", text)) <= 4
    known = KnownNumbers(FACTS)
    assert all(known.knows(f) for f in _figures(text))  # no invented numbers, even in code's own words


def test_fallback_for_empty_personal_books() -> None:
    text = hs.fallback_summary({"today": "27 Oct 2026", "kind": "personal", "needs_doing": {"in_review": 0}})
    assert text == (
        "There is no bank balance yet: import a bank statement and match a line to see one. "
        "Nothing is waiting for you in Review."
    )


def test_ground_rejects_invented_figures_links_and_false_all_clear() -> None:
    assert hs.ground("You have £5,400.00 in the bank and 2 items in Review.", FACTS) is None
    assert hs.ground("You have £5,400 in the bank.", FACTS) is None  # whole-pound rounding of a fact
    assert "not in your books" in (hs.ground("You made £1,234.56 profit this month.", FACTS) or "")
    assert "not in your books" in (hs.ground("Cash is up 350% on September.", FACTS) or "")
    assert hs.ground("See www.example.com", FACTS) == "The model's summary contained a link."
    assert hs.ground("All clear: nothing needs doing.", FACTS) == "The model said nothing needs doing; something does."
    assert hs.ground("", FACTS) == "The model returned an empty summary."


async def test_summary_uses_the_models_words_when_they_check_out(monkeypatch: pytest.MonkeyPatch) -> None:
    async def good(*_a: Any, **_k: Any) -> str:
        return json.dumps({"summary_md": "£5,400.00 in the bank; 2 items wait in Review."})

    monkeypatch.setattr(hs, "call_json_model", good)
    got = await hs.summarise(FACTS, CFG)
    assert (got.summary_md, got.model, got.fallback_reason) == (
        "£5,400.00 in the bank; 2 items wait in Review.",
        "stub",
        None,
    )
    assert got.facts == FACTS


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (json.dumps({"summary_md": "You made £9,999.99 this month."}), "9,999.99"),
        ("not json at all", "not in the expected format"),
    ],
)
async def test_summary_falls_back_to_code(monkeypatch: pytest.MonkeyPatch, reply: str, reason: str) -> None:
    async def model(*_a: Any, **_k: Any) -> str:
        return reply

    monkeypatch.setattr(hs, "call_json_model", model)
    got = await hs.summarise(FACTS, CFG)
    assert got.fallback_reason and reason in got.fallback_reason
    assert got.summary_md == hs.fallback_summary(FACTS)


async def test_summary_survives_a_model_that_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    async def down(*_a: Any, **_k: Any) -> str:
        raise ConnectionError("down")

    monkeypatch.setattr(hs, "call_json_model", down)
    got = await hs.summarise(FACTS, CFG)
    assert got.fallback_reason == "Your AI (local) could not write the summary (ConnectionError)."


async def test_no_ai_means_code_writes_it() -> None:
    got = await hs.summarise(FACTS, None)
    assert (got.model, got.fallback_reason) == ("code", "No AI is set up, so code wrote this.")


# --------------------------------------------------------------------------- #
# The route
# --------------------------------------------------------------------------- #


def test_home_payload(client: TestClient, fake: FakeStorageProvider) -> None:  # noqa: F811
    before = dict(fake.files)
    r = client.get(f"/books/home?stagger=1&today={TODAY}&summary_ai=false", headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    assert fake.files == before  # reads only
    assert d["kind"] == "company" and d["unavailable"] == []
    # 24 Oct: -5.00, +405.00 (the ignored -10.00 left out); 25 and 26 Oct: -20.00, -30.00.
    assert d["money"]["this_month"]["money_in_pence"] == 40500
    assert d["money"]["this_month"]["money_out_pence"] == 5500
    assert d["money"]["last_month"]["money_in_pence"] == 0
    assert d["week"] == {
        "start": "2026-10-21",
        "end": "2026-10-27",
        "money_in_pence": 40500,
        "money_out_pence": 5500,
        "approved": 1,
        "proposed": 1,
    }
    # The Aged report's own figures (the card links there): INV-0001, and INV-0002, marked paid by hand with no payment
    # recorded, which the report still counts (the Today tile does not; docs/reviews/dashboard-ui/REVIEW.md, risks).
    assert d["aged"]["debtors"]["total_pence"] == 81000 and d["aged"]["debtors"]["documents"] == 2
    assert d["itsa"] is None and d["property"] is None and d["cis"] is None  # a company with neither
    assert [x["key"] for x in d["deadlines"]] == ["vat"]
    assert d["deadlines"][0] == {
        "key": "vat",
        "title": "VAT return Jul–Sep 2026",
        "due": "2026-11-07",
        "days_left": 11,
        "href": "/vat",
        "source_url": None,
    }
    s = d["summary"]
    assert s["model"] == "code"  # summary_ai=false: code writes it
    assert s["facts"]["cash"] == {"balance": "£5,400.00", "as_of": "24 Oct 2026"}
    assert s["facts"]["needs_doing"] == {"in_review": 2, "unmatched_bank_lines": 3, "overdue_invoices": 1}
    assert s["summary_md"].startswith("You had £5,400.00 in the bank on 24 Oct 2026.")
    known = KnownNumbers(s["facts"])
    assert all(known.knows(f) for f in _figures(s["summary_md"]))


@pytest.mark.parametrize(
    ("kind", "settings", "itsa", "sa"),
    [("sole_trader", {"vat_registered": False}, True, True), ("personal", {}, False, False)],
)
def test_sections_follow_the_profile_kind(
    client: TestClient,  # noqa: F811
    books: Books,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    settings: dict[str, Any],
    itsa: bool,
    sa: bool,
) -> None:
    p = profile_mod.default_profile().model_copy(
        update={"kind": kind, "features": profile_mod.features_for(kind, settings)}
    )

    async def load(_b: Books) -> profile_mod.Profile:
        return p

    monkeypatch.setattr(profile_mod, "load", load)
    d = client.get(f"/books/home?today={TODAY}", headers=H).json()
    assert d["kind"] == kind
    assert (d["itsa"] is not None) is itsa
    assert ("self_assessment" in [x["key"] for x in d["deadlines"]]) is sa
    assert "vat" not in [x["key"] for x in d["deadlines"]]  # neither is VAT-registered
    if itsa:
        assert d["itsa"]["due"] == "2026-11-07"
    assert d["payroll"] is None and "VAT" not in d["summary"]["summary_md"]
