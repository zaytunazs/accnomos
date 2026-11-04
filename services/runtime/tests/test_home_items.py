"""Home's to-do list (app/home_items.py) and its per-item wording check (app/ai/home_summary.py `summarise_items`)."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from app import home_items as hi
from app import personal as pf
from app.ai import home_summary as hs
from app.ai.config import AiConfig

TODAY = date(2026, 11, 3)
CFG = AiConfig(mode="local", base_url="http://ollama.invalid", model="stub")


def due(key: str, title: str, d: date) -> SimpleNamespace:
    return SimpleNamespace(key=key, title=title, due=d, days_left=(d - TODAY).days, href="/vat")


def business(**kw):
    base = dict(
        today=TODAY,
        proposed=0,
        needs_a_look=0,
        unmatched_bank_lines=0,
        overdue_invoices=0,
        overdue_pence=0,
        deadlines=[],
        below_zero_on=None,
        lowest_pence=None,
        lowest_on=None,
        bills_overdue_pence=0,
        unclosed_month=None,
        goals=[],
        ytd=None,
        cash=None,
    )
    return hi.business_items(**{**base, **kw})


def test_nothing_for_zero_counts_and_far_deadlines() -> None:
    assert business(deadlines=[due("vat", "VAT return Oct–Dec 2026", date(2027, 2, 7))]) == []


def test_order_priority_then_date_then_money_and_routes() -> None:
    drafts = business(
        proposed=5,
        needs_a_look=1,
        unmatched_bank_lines=16,
        overdue_invoices=2,
        overdue_pence=282000,
        deadlines=[due("vat", "VAT return Jul–Sep 2026", date(2026, 11, 7))],
        below_zero_on=date(2026, 12, 12),
        lowest_pence=-123400,
        lowest_on=date(2026, 12, 20),
        unclosed_month=("2026-10", "October 2026"),
        ytd={"turnover": 2455315, "change_pct": -11, "period": "1 Jan – 3 Nov 2026"},
    )
    items = [d.item for d in drafts]
    assert [(i.id, i.priority) for i in items] == [
        ("vat_due", 1),  # in 4 days: act now, and the soonest date
        ("cash_dip", 1),
        ("overdue_invoices", 1),  # undated: after the dated ones, money first
        ("review", 1),
        ("bank_unmatched", 2),
        ("month_end", 2),
    ]  # at most six: the year-to-date line (information) is cut
    by = {i.id: i for i in items}
    assert (
        by["vat_due"].title == "VAT return Jul–Sep 2026 due 7 Nov"
        and by["vat_due"].detail == "Due 7 Nov 2026, in 4 days."
    )
    assert by["review"].title == "6 items waiting for your approval" and by["review"].detail == "1 needs a closer look."
    assert by["overdue_invoices"].title == "2 invoices overdue: £2,820.00"
    assert by["cash_dip"].title == "Cash may go below £0 from 12 Dec" and by["cash_dip"].tone == "negative"
    assert {i.id: i.action.route for i in items if i.action} == {
        "vat_due": "/vat",
        "cash_dip": "/reports/cashflow",
        "overdue_invoices": "/invoices?filter=overdue",
        "review": "/review",
        "bank_unmatched": "/bank/reconcile",
        "month_end": "/month-end",
    }
    assert hi.headline(items) == "4 things need you now, 2 soon."


def test_late_deadline_is_negative_and_information_comes_last() -> None:
    items = [
        d.item
        for d in business(
            deadlines=[due("vat", "VAT return Jul–Sep 2026", date(2026, 11, 1))],
            ytd={"turnover": 100000, "change_pct": 12, "period": "1 Jan – 3 Nov 2026"},
        )
    ]
    assert [i.id for i in items] == ["vat_due", "trend"]
    assert items[0].tone == "negative" and items[0].detail == "Due 1 Nov 2026, 2 days late."
    assert items[1].title == "Turnover £1,000.00 this year, up 12%" and items[1].tone == "positive"
    assert items[1].action is None


def _month(cats: list[pf.CategorySpend], unc: int = 0) -> pf.MonthlySummary:
    return pf.MonthlySummary(
        month="2026-11",
        lines=10,
        income_pence=268400,
        spent_pence=166935,
        left_pence=101465,
        budget_total_pence=200000,
        categories=cats,
        uncategorised_count=unc,
        uncategorised_pence=4500 if unc else 0,
        notes=[],
    )


def cat(id: str, name: str, spent: int, budget: int) -> pf.CategorySpend:
    remaining, percent, state = pf.spend_vs_budget(spent, budget)
    return pf.CategorySpend(
        id=id,
        name=name,
        spent_pence=spent,
        budget_pence=budget,
        remaining_pence=remaining,
        percent=percent,
        state=state,
    )


def test_household_items_never_mention_business_matters() -> None:
    bill = SimpleNamespace(label="BT BROADBAND", amount_pence=3800, next_due=date(2026, 11, 8), days_until=5)
    hh = SimpleNamespace(
        this_month=_month(
            [cat("housing", "Housing", 159400, 145000), cat("groceries", "Groceries", 30000, 35000)], unc=2
        ),
        last_month=_month([]),
        next_bill=bill,
    )
    drafts = hi.household_items(
        today=TODAY,
        proposed=2,
        needs_a_look=0,
        household=hh,
        this_month_label="November 2026 so far",
        last_month_label="October 2026",
        goals=[],
    )
    items = [d.item for d in drafts]
    assert [(i.id, i.priority) for i in items] == [
        ("budget_over:housing", 1),
        ("review", 1),
        ("bill_due", 2),
        ("budget_near:groceries", 2),
        ("uncategorised", 2),
        ("trend", 3),
    ]
    by = {i.id: i for i in items}
    assert by["budget_over:housing"].title == "Housing over budget by £144.00"
    assert by["review"].title == "2 receipts waiting for your approval"
    assert by["bill_due"].title == "Bt Broadband, about £38.00, due 8 Nov"
    assert all(i.action.route in ("/personal", "/review") for i in items if i.action)
    text = " ".join(f"{i.title} {i.detail or ''}" for i in items).lower()
    assert not any(w in text for w in ("vat", "turnover", "invoice", "profit"))


def _drafts() -> list[hi.Draft]:
    return business(proposed=3, overdue_invoices=1, overdue_pence=40500)


async def test_model_words_each_item_and_a_bad_item_keeps_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def model(messages, cfg, schema, name):
        assert name == "home_summary_items"
        sent = json.loads(messages[1]["content"])
        assert [i["id"] for i in sent["ITEMS"]] == ["overdue_invoices", "review"]
        return json.dumps(
            {
                "headline": "Two things need you now.",
                "items": [
                    {"id": "overdue_invoices", "title": "1 invoice is overdue (£999.00)", "detail": None},  # invented
                    {"id": "review", "title": "3 receipts to approve", "detail": "They are waiting in Review."},
                ],
            }
        )

    monkeypatch.setattr(hs, "call_json_model", model)
    s = await hs.summarise({"kind": "company"}, CFG, _drafts())
    by = {i.id: i for i in s.items}
    assert by["overdue_invoices"].title == "1 invoice overdue: £405.00"  # code's words: £999.00 is not in the books
    assert by["review"].title == "3 receipts to approve" and by["review"].detail == "They are waiting in Review."
    assert by["review"].action is not None and by["review"].action.route == "/review"  # the link is code's, always
    assert s.summary_md == "Two things need you now."
    assert s.fallback_reason == "Code's words kept for 1 of 2 items: the model's did not check out."


async def test_all_clear_headline_and_model_failure_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    async def all_clear(messages, cfg, schema, name):
        return json.dumps({"headline": "All clear, nothing to do!", "items": []})

    monkeypatch.setattr(hs, "call_json_model", all_clear)
    s = await hs.summarise({"kind": "company"}, CFG, _drafts())
    assert s.summary_md == "2 things need you now." and [i.id for i in s.items] == ["overdue_invoices", "review"]

    async def down(messages, cfg, schema, name):
        raise TimeoutError

    monkeypatch.setattr(hs, "call_json_model", down)
    s = await hs.summarise({"kind": "company"}, CFG, _drafts())
    assert s.fallback_reason and "could not word the list" in s.fallback_reason
    assert s.items[0].title == "1 invoice overdue: £405.00"


async def test_no_items_keeps_the_paragraph() -> None:
    s = await hs.summarise({"kind": "company", "today": "3 Nov 2026"}, None, [])
    assert s.items == [] and s.summary_md.startswith("There is no bank balance yet")
