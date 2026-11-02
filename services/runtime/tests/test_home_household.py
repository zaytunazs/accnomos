"""Home for a household (personal books): the summary's facts are the month, budgets, what needs doing and the next
regular bill (app/home_overview.py `household`, `household_facts`; app/ai/home_summary.py `household_summary`)."""

from __future__ import annotations

import re
from datetime import date

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger.bank import BankLine
from app import dashboard as dash
from app import home_overview as ho
from app import personal as pf
from app.ai import home_summary as hs
from app.ai.ask import KnownNumbers
from app.books import Books

TODAY = date(2026, 11, 20)


def line(d: str, pence: int, desc: str, n: list[int] = [0]) -> BankLine:  # noqa: B006
    n[0] += 1
    return BankLine(id=f"h{n[0]}", date=date.fromisoformat(d), amount_pence=pence, description=desc, source_file="s")  # type: ignore[arg-type]


LINES = [
    *[line(f"2026-{m:02d}-05", -1099, "NETFLIX.COM") for m in range(6, 12)],  # monthly, next due ~5 Dec
    line("2026-10-01", 250000, "SALARY"),
    line("2026-10-08", -30000, "TESCO STORES"),
    line("2026-11-01", 250000, "SALARY"),
    line("2026-11-03", -38000, "TESCO STORES"),  # over a £350 groceries budget
    line("2026-11-04", -4500, "MYSTERY SHOP"),  # no category
]


async def household() -> ho.Household:
    books = Books(FakeStorageProvider())
    await pf.save_budgets(books, pf.BudgetsIn(budgets={"groceries": 35000, "subscriptions": 1200}), "u")
    await pf.add_rule(
        books, pf.PersonalRuleIn(match={"op": "contains", "value": "tesco"}, category_id="groceries"), "u"
    )
    await pf.add_rule(
        books, pf.PersonalRuleIn(match={"op": "contains", "value": "netflix"}, category_id="subscriptions"), "u"
    )
    return await ho.household(books, LINES, TODAY)


async def test_household_month_budgets_and_next_bill() -> None:
    h = await household()
    assert (h.this_month.income_pence, h.this_month.spent_pence) == (250000, 43599)
    assert h.last_month.month == "2026-10" and h.last_month.spent_pence == 31099
    assert h.next_bill is not None and h.next_bill.label.upper().startswith("NETFLIX")
    f = ho.household_facts(h, TODAY)
    assert f["this_month"] == {
        "label": "November 2026 so far",
        "in": "£2,500.00",
        "out": "£435.99",
        "left": "£2,064.01",
    }
    assert f["over_budget"] == [{"category": "Groceries", "spent": "£380.00", "budget": "£350.00", "over_by": "£30.00"}]
    assert f["near_budget"][0]["category"] == "Subscriptions"  # £10.99 of £12.00
    assert f["uncategorised_lines"] == 1
    assert f["next_bill"]["usual_amount"] == "£10.99" and f["next_bill"]["estimate"] is True


async def test_summary_facts_and_code_summary_for_a_household() -> None:
    h = await household()
    d = dash.Dashboard.model_construct(
        today=TODAY,
        cash=None,
        attention=dash.Attention(proposed=2, needs_a_look=0, unmatched_bank_lines=7, overdue_invoices=None, total=2),
        owed_to_you=None,
    )
    o = {"kind": "personal", "money": None, "week": None, "aged": None, "deadlines": [], "household": h}
    facts = ho.summary_facts(d, o)
    assert facts["needs_doing"] == {"in_review": 2, "uncategorised_bank_lines": 1}  # no ledger matching for a household
    assert "money" not in facts and "overdue" not in facts
    text = hs.fallback_summary(facts)
    assert text.startswith("November 2026 so far, £2,500.00 came in and £435.99 went out, leaving £2,064.01;")
    assert "Groceries is over budget: £380.00 spent of £350.00." in text
    assert "To do: 2 receipts waiting in Review and 1 bank line with no category." in text
    assert "an estimate" in text
    assert not re.search(r"VAT|turnover|profit|invoice", text)
    known = KnownNumbers(facts)
    assert all(known.knows(t) for t in re.findall(r"£[\d,]+\.\d\d|\b\d+\b", text))
    assert hs.ground(text, facts) is None


def test_household_summary_when_more_went_out() -> None:
    facts = {
        "kind": "personal",
        "household": {
            "this_month": {"label": "November 2026 so far", "in": "£0.00", "out": "£40.00", "left": "-£40.00"},
            "last_month": {"label": "October 2026", "in": "£10.00", "out": "£5.00", "left": "£5.00"},
            "over_budget": [],
            "near_budget": [],
            "uncategorised_lines": 0,
        },
        "needs_doing": {"in_review": 0, "uncategorised_bank_lines": 0},
    }
    assert hs.fallback_summary(facts) == (
        "November 2026 so far, £0.00 came in and £40.00 went out, £40.00 more went out than came in; "
        "in October 2026 £10.00 came in and £5.00 went out."
    )
