"""Goals (app/goals.py, app/ai/goals.py, app/routes_goals.py): progress, status and suggestions worked out by code."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger.bank import BankLine
from app import goals as gm
from app import personal as pf
from app.ai import goals as goals_ai
from app.books import Books
from app.purchases import ItemLine, Purchase

TODAY = date(2026, 11, 15)
USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}


def line(d: str, pence: int, desc: str, n: list[int] = [0]) -> BankLine:  # noqa: B006
    n[0] += 1
    return BankLine(id=f"g{n[0]}", date=date.fromisoformat(d), amount_pence=pence, description=desc, source_file="x")  # type: ignore[arg-type]


def buy(d: str, pence: int, category: str, supplier: str = "Shop", items: tuple[tuple[str, int], ...] = ()) -> Purchase:
    return Purchase(
        event_id=f"e{d}{pence}",
        date=date.fromisoformat(d),
        supplier=supplier,
        category=category,
        net_pence=pence,
        vat_pence=0,
        source="x",
        lines=tuple(ItemLine(description=n, qty=1, unit_price_pence=p, net_pence=p) for n, p in items),
    )


def goal(**kw) -> gm.Goal:
    base = {"name": "G", "kind": "save", "start": date(2026, 11, 1), "end": date(2026, 11, 30), "target_pence": 30000}
    return gm.Goal(**{**base, **kw})


def household(lines: list[BankLine]) -> gm.Ledgerish:
    rules = [
        pf.PersonalRule(match={"op": "contains", "value": "tesco"}, category_id="groceries"),
        pf.PersonalRule(match={"op": "contains", "value": "costa"}, category_id="eating_out"),
    ]
    return gm.Ledgerish(household=True, lines=lines, categories=pf.default_categories(), rules=rules)


# Shape ---------------------------------------------------------------------------------------------------------- #


def test_goal_shape_rules() -> None:
    with pytest.raises(ValueError, match="end date"):
        goal(end=date(2026, 10, 1))
    with pytest.raises(ValueError, match="per cent"):
        goal(kind="spend_less", target_pence=None)
    with pytest.raises(ValueError, match="target"):
        goal(kind="earn", target_pence=None)
    with pytest.raises(ValueError, match="focus"):
        goal(kind="save", focus="coffee")
    assert goal(kind="spend_less", percent=10, target_pence=None, focus="  Groceries ").focus == "Groceries"


# Save ----------------------------------------------------------------------------------------------------------- #


def test_manual_save_on_track_behind_and_reached() -> None:
    data = gm.Ledgerish(household=True)
    # 15 of 30 days gone: an even pace is £150.00 of £300.00
    p = gm.progress(goal(saved_pence=15000), data, TODAY)
    assert p.status == "on_track" and p.plan_to_date_pence == 15000 and p.percent == 50
    p = gm.progress(goal(saved_pence=12000), data, TODAY)
    assert p.status == "at_risk" and p.variance_text == "£30.00 behind plan to date."
    p = gm.progress(goal(saved_pence=5000), data, TODAY)
    assert p.status == "off_track" and p.tone == "negative"
    assert p.needed_text == "£250.00 still to go by 30 Nov 2026."
    p = gm.progress(goal(saved_pence=30000), data, TODAY)
    assert p.status == "reached" and p.suggestions == []
    assert gm.progress(goal(saved_pence=0), data, date(2026, 10, 20)).status == "not_started"
    assert gm.progress(goal(saved_pence=100), data, date(2026, 12, 2)).status == "missed"


def test_net_cash_save_counts_bank_lines_since_start_and_hand_amount() -> None:
    data = household(
        [line("2026-10-30", 99999, "PAY"), line("2026-11-02", 200000, "SALARY"), line("2026-11-03", -185000, "RENT")]
    )
    p = gm.progress(goal(measure="net_cash", saved_pence=1000), data, TODAY)
    assert p.current_pence == 16000  # 2,000 - 1,850 since 1 Nov, plus £10 by hand
    assert p.run_rate_pence == 32000  # an estimate: the same pace to the end


# Spending ------------------------------------------------------------------------------------------------------- #


def test_household_spend_cap_on_a_focus_with_drivers_and_suggestion() -> None:
    lines = [
        # October: the 15 days before 1 Nov (17-31 Oct)
        line("2026-10-20", -1000, "COSTA COFFEE"),
        line("2026-10-21", -6000, "TESCO STORES"),
        # November so far
        line("2026-11-02", -3500, "COSTA COFFEE"),
        line("2026-11-05", -3500, "COSTA COFFEE"),
        line("2026-11-06", -7000, "TESCO STORES"),
        line("2026-11-07", 50000, "SALARY"),
    ]
    data = household(lines)
    g = goal(kind="spend_cap", target_pence=10000, focus="Eating out")
    p = gm.progress(g, data, TODAY)
    assert p.current_pence == 7000 and p.plan_to_date_pence == 5000
    assert p.status == "off_track" and p.variance_text == "£20.00 above plan to date."
    assert p.needed_text == "£30.00 left to spend by 30 Nov 2026."
    assert p.drivers[0].name == "Costa Coffee" and p.drivers[0].change_pence == 6000
    assert p.suggestions[0].startswith("You have spent £70.00 with Costa Coffee so far, £60.00 more")
    assert "would cover the gap of £20.00" in p.suggestions[0]
    # a word, not a category name: matches descriptions
    assert gm.progress(goal(kind="spend_cap", target_pence=10000, focus="tesco"), data, TODAY).current_pence == 7000
    # all spending
    assert gm.progress(goal(kind="spend_cap", target_pence=100000), data, TODAY).current_pence == 14000
    over = gm.progress(goal(kind="spend_cap", target_pence=6000, focus="Eating out"), data, TODAY)
    assert over.status == "over_limit" and over.variance_text == "£10.00 over the limit."


def test_business_spend_less_against_last_year_with_item_drivers() -> None:
    purchases = [
        buy("2025-11-03", 4000, "Meals", "Costa", (("Flat white", 4000),)),
        buy("2026-10-20", 1000, "Meals", "Costa", (("Flat white", 1000),)),
        buy("2026-11-03", 2500, "Meals", "Costa", (("Flat white", 2500),)),
        buy("2026-11-04", 2500, "Meals", "Pret", (("Croissant", 2500),)),
        buy("2026-11-05", 9000, "Travel", "Trainline"),
    ]
    data = gm.Ledgerish(household=False, purchases=purchases)
    g = goal(kind="spend_less", percent=25, target_pence=None, focus="meals", start=date(2026, 11, 1))
    p = gm.progress(g, data, TODAY)
    assert p.baseline_pence == 4000 and p.target_pence == 3000  # last year's £40 cut by 25%
    assert "a year earlier" in (p.baseline_label or "")
    assert p.current_pence == 5000 and p.status == "over_limit"
    names = [d.name for d in p.drivers]
    assert names[0] == "Croissant" and "Flat white" in names  # grew £25, then £15
    # a focus word that is an item, not a category
    coffee = gm.progress(goal(kind="spend_cap", target_pence=5000, focus="flat white"), data, TODAY)
    assert coffee.current_pence == 2500


def test_spend_less_without_anything_to_compare_says_so() -> None:
    data = gm.Ledgerish(household=False, purchases=[buy("2026-11-03", 2500, "Meals")])
    p = gm.progress(goal(kind="spend_less", percent=10, target_pence=None), data, TODAY)
    assert p.status == "no_data" and p.target_pence is None and p.tone == "neutral"


def test_spend_less_falls_back_to_the_span_just_before() -> None:
    purchases = [buy("2026-10-25", 8000, "Meals"), buy("2026-11-03", 5000, "Meals")]
    data = gm.Ledgerish(household=False, purchases=purchases)
    p = gm.progress(goal(kind="spend_less", percent=50, target_pence=None), data, TODAY)
    assert p.baseline_pence == 8000 and p.target_pence == 4000 and "just before" in (p.baseline_label or "")
    assert p.status == "over_limit"


# Earn ----------------------------------------------------------------------------------------------------------- #


def test_household_earn_counts_money_in() -> None:
    data = household([line("2026-11-02", 20000, "INVOICE PAID"), line("2026-11-03", -500, "TESCO")])
    p = gm.progress(goal(kind="earn", target_pence=100000), data, TODAY)
    assert p.current_pence == 20000 and p.status == "off_track"
    assert p.suggestions == ["£800.00 still to go by 30 Nov 2026."]


# Note ----------------------------------------------------------------------------------------------------------- #


async def test_note_falls_back_to_code_and_checks_model_figures(monkeypatch: pytest.MonkeyPatch) -> None:
    data = gm.Ledgerish(household=True)
    progress = [gm.progress(goal(name="School fee", saved_pence=5000), data, TODAY)]
    facts = gm.facts(progress, TODAY)
    n = await goals_ai.note(facts, None)
    assert n.model == "code" and n.note_md.startswith("School fee is off track.")
    assert goals_ai.check("You have saved £50.00 so far.", facts) is None
    assert "not in your books" in (goals_ai.check("You have saved £51.00 so far.", facts) or "")
    assert goals_ai.check("See https://x.example", facts) == "The model's note contained a link."
    assert (await goals_ai.note(gm.facts([], TODAY), None)).note_md == ""


# Routes --------------------------------------------------------------------------------------------------------- #


@pytest.fixture
async def books() -> Books:
    return Books(FakeStorageProvider())


@pytest.fixture
def client(books: Books):
    from app.main import app
    from app.routes_books import get_books, require_user

    async def override() -> Books:
        return books

    app.dependency_overrides[get_books] = override
    app.dependency_overrides[require_user] = lambda: USER
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_routes_add_list_patch_delete(client: TestClient) -> None:
    body = {
        "name": "School fee",
        "kind": "save",
        "start": "2026-11-01",
        "end": "2027-08-31",
        "target_pence": 100000,
        "saved_pence": 10000,
    }
    r = client.post("/books/goals", headers=H, json=body)
    assert r.status_code == 201, r.text
    gid = r.json()["id"]
    assert r.json()["scope"] == "business"
    assert client.post("/books/goals", headers=H, json={**body, "end": "2026-01-01"}).status_code == 422
    view = client.get("/books/goals?today=2026-11-15&note_ai=false", headers=H).json()
    assert view["goals"][0]["current_pence"] == 10000 and view["note"]["model"] == "code"
    assert view["facts"]["goals"][0]["so_far"] == "100.00"
    r = client.patch(f"/books/goals/{gid}", headers=H, json={"saved_pence": 25000})
    assert r.status_code == 200 and r.json()["saved_pence"] == 25000
    assert client.patch(f"/books/goals/{gid}", headers=H, json={"end": "2020-01-01"}).status_code == 422
    assert client.patch("/books/goals/nope", headers=H, json={"saved_pence": 1}).status_code == 404
    assert client.delete(f"/books/goals/{gid}", headers=H).status_code == 204
    assert client.get("/books/goals", headers=H).json()["goals"] == []
