"""Personal finances (app/personal.py, /personal/*): budgets, recurring detection, goals and categorisation."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger.bank import BankLine
from app import personal as p
from app.books import Books

USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
TODAY = date(2026, 10, 28)


def line(d: str, pence: int, desc: str, n: list[int] = [0], status: str = "unmatched") -> BankLine:  # noqa: B006
    n[0] += 1
    return BankLine(
        id=f"l{n[0]}",
        date=date.fromisoformat(d),
        amount_pence=pence,
        description=desc,
        source_file="x.csv",
        status=status,
    )  # type: ignore[arg-type]


def rule(value: str, cat: str, **kw) -> p.PersonalRule:
    return p.PersonalRule(match={"op": "contains", "value": value}, category_id=cat, **kw)


CATS = p.default_categories()
KNOWN = {c.id for c in CATS}


# Categorisation ----------------------------------------------------------- #


def test_first_matching_rule_wins_and_only_money_out_is_categorised() -> None:
    rules = [rule("tesco express", "eating_out"), rule("tesco", "groceries")]
    assert p.categorise(line("2026-10-01", -450, "TESCO EXPRESS 1234"), rules, {}, KNOWN) == ("eating_out", "rule")
    assert p.categorise(line("2026-10-01", -4500, "TESCO STORES 4321"), rules, {}, KNOWN) == ("groceries", "rule")
    assert p.categorise(line("2026-10-01", 4500, "TESCO REFUND"), rules, {}, KNOWN) == ("other", "none")
    assert p.categorise(line("2026-10-01", -100, "UNKNOWN SHOP"), rules, {}, KNOWN) == ("other", "none")


def test_hand_set_beats_rules_and_a_missing_category_falls_back_to_other() -> None:
    ln = line("2026-10-01", -450, "TESCO")
    assert p.categorise(ln, [rule("tesco", "groceries")], {ln.id: "health"}, KNOWN) == ("health", "hand")
    assert p.categorise(ln, [rule("tesco", "gone")], {ln.id: "gone"}, KNOWN) == ("other", "none")


def test_amount_range_and_regex_rules() -> None:
    small = rule("uber", "transport", amount_max_pence=-1)
    big_only = p.PersonalRule(
        match={"op": "regex", "value": r"^gym\b"}, category_id="health", amount_min_pence=-5000, amount_max_pence=-1000
    )
    assert p.categorise(line("2026-10-01", -2000, "GYM CLUB"), [big_only], {}, KNOWN)[0] == "health"
    assert p.categorise(line("2026-10-01", -9000, "GYM CLUB"), [big_only], {}, KNOWN)[0] == "other"
    assert p.categorise(line("2026-10-01", -900, "UBER TRIP"), [small], {}, KNOWN)[0] == "transport"


# Budgets and the monthly summary ------------------------------------------ #


@pytest.mark.parametrize(
    ("spent", "budget", "expected"),
    [
        (0, None, (None, None, "none")),
        (0, 0, (None, None, "none")),
        (7999, 10000, (2001, 79, "ok")),
        (8000, 10000, (2000, 80, "near")),
        (10000, 10000, (0, 100, "near")),
        (10001, 10000, (-1, 100, "over")),
        (25000, 10000, (-15000, 250, "over")),
    ],
)
def test_spend_vs_budget(spent: int, budget: int | None, expected: tuple) -> None:
    assert p.spend_vs_budget(spent, budget) == expected


def test_summary_totals_exclude_transfers_other_months_and_count_uncategorised() -> None:
    lines = [
        line("2026-10-01", 250000, "SALARY ACME LTD"),
        line("2026-10-02", -120000, "RENT LANDLORD"),
        line("2026-10-03", -4510, "TESCO STORES 1"),
        line("2026-10-04", -2490, "TESCO STORES 2"),
        line("2026-10-05", -999, "MYSTERY SHOP"),
        line("2026-10-06", -50000, "TO SAVINGS", status="transfer"),
        line("2026-10-07", -111, "IGNORED THING", status="ignored"),
        line("2026-09-30", -77700, "TESCO LAST MONTH"),
    ]
    rules = [rule("rent", "housing"), rule("tesco", "groceries")]
    s = p.summarise_month("2026-10", lines, CATS, {"groceries": 8000, "housing": 120000}, rules, {})
    by = {c.id: c for c in s.categories}
    assert s.lines == 5
    assert s.income_pence == 250000
    assert s.spent_pence == 120000 + 4510 + 2490 + 999
    assert s.left_pence == 250000 - s.spent_pence
    assert by["groceries"].spent_pence == 7000 and by["groceries"].state == "near" and by["groceries"].percent == 87
    assert by["housing"].remaining_pence == 0 and by["housing"].state == "near"
    assert by["other"].spent_pence == 999 and by["other"].budget_pence is None
    assert (s.uncategorised_count, s.uncategorised_pence) == (1, 999)
    assert s.budget_total_pence == 128000
    assert any("did not match a rule" in n for n in s.notes)


def test_empty_month_says_so() -> None:
    s = p.summarise_month("2026-10", [], CATS, {}, [], {})
    assert s.lines == 0 and s.spent_pence == 0 and "No bank lines" in s.notes[0]


# Recurring ---------------------------------------------------------------- #


def monthly(desc: str, pence: int, days: list[str]) -> list[BankLine]:
    return [line(d, pence, desc.replace("#", str(i))) for i, d in enumerate(days)]


def test_payee_key_drops_dates_and_digits() -> None:
    a = p.payee_key("NETFLIX.COM 12345 ON 03 OCT CD 1234")
    assert a == p.payee_key("Netflix.com  67890 on 03 Nov CD 1234") == "netflix com"
    assert p.payee_key("1234 5678") == ""


def test_monthly_subscription_found_with_next_due_and_status() -> None:
    lines = monthly("NETFLIX.COM #", -1099, ["2026-07-03", "2026-08-03", "2026-09-03", "2026-10-03"])
    [item] = p.detect_recurring(lines, CATS, [rule("netflix", "subscriptions")], {}, TODAY)
    assert (item.cadence, item.amount_pence, item.occurrences) == ("monthly", 1099, 4)
    assert item.next_due == date(2026, 11, 3) and item.days_until == 6 and item.status == "upcoming"
    assert item.category_id == "subscriptions" and item.monthly_equivalent_pence == 1099 and item.estimate


def test_end_of_month_stepping_clamps_to_short_months() -> None:
    lines = monthly("GYM #", -3000, ["2026-10-31", "2026-11-30", "2026-12-31"])
    [item] = p.detect_recurring(lines, CATS, [], {}, date(2026, 12, 31))
    assert item.next_due == date(2027, 1, 31)
    assert p.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert p.add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_weekly_fortnightly_quarterly_annual() -> None:
    weekly = monthly("CLEANER #", -2000, ["2026-10-01", "2026-10-08", "2026-10-15", "2026-10-22"])
    fort = monthly("PAYPAL CLUB #", -500, ["2026-09-10", "2026-09-24", "2026-10-08", "2026-10-22"])
    quarter = monthly("WATER #", -9000, ["2026-01-05", "2026-04-05", "2026-07-05"])
    annual = monthly("AA BREAKDOWN #", -15000, ["2025-11-12", "2026-11-12"])
    got = {i.key: i for i in p.detect_recurring(weekly + fort + quarter + annual, CATS, [], {}, TODAY)}
    assert got["cleaner"].cadence == "weekly" and got["cleaner"].next_due == date(2026, 10, 29)
    assert got["paypal club"].cadence == "fortnightly" and got["paypal club"].next_due == date(2026, 11, 5)
    assert got["water"].cadence == "quarterly" and got["water"].next_due == date(2026, 10, 5)
    assert got["water"].status == "overdue" and got["water"].monthly_equivalent_pence == 3000
    assert got["aa breakdown"].cadence == "annually" and got["aa breakdown"].monthly_equivalent_pence == 1250


def test_not_recurring_when_irregular_or_amounts_differ_or_too_few() -> None:
    irregular = monthly("PUB #", -2000, ["2026-08-01", "2026-08-04", "2026-09-20", "2026-10-02"])
    amounts = monthly("TESCO #", -4000, ["2026-07-03", "2026-08-03", "2026-09-03"])
    amounts[1] = amounts[1].model_copy(update={"amount_pence": -9500})
    amounts[2] = amounts[2].model_copy(update={"amount_pence": -1200})
    twice = monthly("NEW SUB #", -999, ["2026-09-03", "2026-10-03"])
    income = monthly("SALARY #", 250000, ["2026-08-01", "2026-09-01", "2026-10-01"])
    transfer = [line(d, -5000, "TO SAVINGS", status="transfer") for d in ["2026-08-01", "2026-09-01", "2026-10-01"]]
    assert p.detect_recurring(irregular + amounts + twice + income + transfer, CATS, [], {}, TODAY) == []


def test_variable_monthly_bill_is_kept_and_marked_varies() -> None:
    lines = [
        line(d, a, "BRITISH GAS DD")
        for d, a in [("2026-07-15", -8000), ("2026-08-15", -9500), ("2026-09-15", -7200), ("2026-10-15", -10100)]
    ]
    [item] = p.detect_recurring(lines, CATS, [], {}, TODAY)
    assert item.amount_varies and item.amount_pence == 8750


def test_stopped_when_more_than_a_cycle_late_and_same_day_pair_counts_once() -> None:
    lines = monthly("OLD GYM #", -2500, ["2026-03-01", "2026-04-01", "2026-05-01"])
    [item] = p.detect_recurring(lines, CATS, [], {}, TODAY)
    assert item.status == "stopped"
    dup = [*monthly("SUB #", -999, ["2026-08-03", "2026-09-03", "2026-10-03"]), line("2026-10-03", -999, "SUB X")]
    [one] = p.detect_recurring(dup, CATS, [], {}, TODAY)
    assert one.occurrences == 3


# Goals -------------------------------------------------------------------- #


def goal(**kw) -> p.Goal:
    base = {"name": "Holiday", "target_pence": 120000, "target_date": date(2027, 10, 28), "saved_pence": 0}
    return p.Goal(**{**base, **kw})


def test_monthly_needed_is_remaining_over_months_rounded_up() -> None:
    plan = p.plan_goal(goal(), TODAY)  # 365 days = 11.99 -> 12 payments
    assert (plan.months_left, plan.monthly_needed_pence, plan.status, plan.percent) == (12, 10000, "plan_needed", 0)
    plan = p.plan_goal(goal(saved_pence=20000, target_pence=100001), TODAY)
    assert plan.remaining_pence == 80001 and plan.monthly_needed_pence == 6667  # 80001/12 = 6666.75 -> up


def test_part_month_counts_as_one_and_target_date_passed() -> None:
    plan = p.plan_goal(goal(target_date=date(2026, 11, 2), target_pence=5000), TODAY)
    assert (plan.months_left, plan.monthly_needed_pence) == (1, 5000)
    late = p.plan_goal(goal(target_date=date(2026, 10, 1), target_pence=5000, saved_pence=1000), TODAY)
    assert (late.status, late.monthly_needed_pence) == ("date_passed", 4000)


def test_on_track_behind_projected_and_reached() -> None:
    assert p.plan_goal(goal(planned_monthly_pence=10000), TODAY).status == "on_track"
    behind = p.plan_goal(goal(planned_monthly_pence=9999), TODAY)
    assert behind.status == "behind" and behind.projected_date == date(2027, 11, 28)  # 13 payments of £99.99
    assert p.plan_goal(goal(planned_monthly_pence=5000), TODAY).projected_date == date(2028, 10, 28)  # 24 months
    done = p.plan_goal(goal(saved_pence=150000), TODAY)
    assert (done.status, done.percent, done.monthly_needed_pence, done.months_left) == ("reached", 100, 0, 0)


# Routes ------------------------------------------------------------------- #

CSV = b"""Date,Description,Amount,Balance\r
03/07/2026,NETFLIX.COM 11111 ON 03 JUL,-10.99,0\r
03/08/2026,NETFLIX.COM 22222 ON 03 AUG,-10.99,0\r
03/09/2026,NETFLIX.COM 33333 ON 03 SEP,-10.99,0\r
03/10/2026,NETFLIX.COM 44444 ON 03 OCT,-10.99,0\r
01/10/2026,SALARY ACME LTD,2500.00,0\r
02/10/2026,RENT LANDLORD,-1200.00,0\r
05/10/2026,TESCO STORES 1234,-45.10,0\r
06/10/2026,MYSTERY SHOP,-9.99,0\r
"""


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
async def books(fake: FakeStorageProvider) -> Books:
    return Books(fake)


@pytest.fixture
def client(books: Books, monkeypatch: pytest.MonkeyPatch):
    from app import routes_personal
    from app.main import app
    from app.routes_books import get_books

    async def override() -> Books:
        return books

    monkeypatch.setattr(routes_personal, "today", lambda: TODAY)
    app.dependency_overrides[get_books] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


async def test_defaults_budgets_rules_summary_end_to_end(client: TestClient, books: Books) -> None:
    await books.import_bank_csv(CSV, "personal.csv", USER)
    cats = client.get("/personal/categories", headers=H).json()
    assert [c["name"] for c in cats][:3] == ["Housing", "Utilities", "Groceries"] and cats[-1]["id"] == "other"

    assert (
        client.put("/personal/budgets", headers=H, json={"budgets": {"groceries": 8000, "nope": 1}}).status_code == 409
    )
    ok = client.put("/personal/budgets", headers=H, json={"budgets": {"groceries": 8000, "housing": 120000}})
    assert ok.json() == {"groceries": 8000, "housing": 120000}
    assert client.put("/personal/budgets", headers=H, json={"budgets": {"groceries": 12.5}}).status_code == 422

    added = client.post("/personal/rules/starter", headers=H).json()
    assert any(r["match"]["value"] == "tesco" for r in added)
    assert client.post("/personal/rules/starter", headers=H).json() == []  # nothing twice
    r = client.post(
        "/personal/rules",
        headers=H,
        json={"match": {"op": "contains", "value": "rent landlord"}, "category_id": "housing"},
    )
    assert r.status_code == 201

    s = client.get("/personal/summary?month=2026-10", headers=H).json()
    by = {c["id"]: c for c in s["categories"]}
    assert s["income_pence"] == 250000 and by["housing"]["spent_pence"] == 120000
    assert by["groceries"]["spent_pence"] == 4510 and by["groceries"]["percent"] == 56
    assert by["subscriptions"]["spent_pence"] == 1099 and by["other"]["spent_pence"] == 999
    assert s["uncategorised_count"] == 1

    # one line by hand, and handing it back
    mystery = next(ln for ln in await books.list_bank_lines() if "MYSTERY" in ln.description)
    assert (
        client.post(f"/personal/lines/{mystery.id}/category", headers=H, json={"category_id": "health"}).status_code
        == 204
    )
    s = client.get("/personal/summary?month=2026-10", headers=H).json()
    assert {c["id"]: c for c in s["categories"]}["health"]["spent_pence"] == 999 and s["uncategorised_count"] == 0
    assert client.post("/personal/lines/zzz/category", headers=H, json={"category_id": "health"}).status_code == 404
    assert (
        client.post(f"/personal/lines/{mystery.id}/category", headers=H, json={"category_id": "x"}).status_code == 409
    )

    assert client.get("/personal/summary?month=2026-13", headers=H).status_code == 422


async def test_recurring_route_and_business_rules_untouched(client: TestClient, books: Books) -> None:
    await books.import_bank_csv(CSV, "personal.csv", USER)
    out = client.get("/personal/recurring", headers=H).json()
    assert [i["key"] for i in out["items"]] == ["netflix com"]
    assert out["items"][0]["next_due"] == "2026-11-03" and out["monthly_total_pence"] == 1099
    assert "Estimates" in out["note"]
    assert not await books.exists("_System/bank_rules.json")  # personal rules are a separate set


async def test_category_edit_rename_remove_and_guards(client: TestClient) -> None:
    cats = client.get("/personal/categories", headers=H).json()
    renamed = [
        {"id": c["id"], "name": "Eating and drinking out" if c["id"] == "eating_out" else c["name"]} for c in cats
    ]
    out = client.put("/personal/categories", headers=H, json={"categories": [*renamed, {"name": "Pets"}]}).json()
    assert {"id": "pets", "name": "Pets"} in out and {"id": "eating_out", "name": "Eating and drinking out"} in out
    assert (
        client.put(
            "/personal/categories", headers=H, json={"categories": [{"id": "housing", "name": "Home"}]}
        ).status_code
        == 409
    )
    dup = [*renamed, {"name": "pets"}, {"name": "Pets"}]
    assert client.put("/personal/categories", headers=H, json={"categories": dup}).status_code == 409

    client.put("/personal/budgets", headers=H, json={"budgets": {"pets": 3000}})
    client.post("/personal/rules", headers=H, json={"match": {"op": "contains", "value": "vet"}, "category_id": "pets"})
    without = [c for c in out if c["id"] != "pets"]
    assert (
        client.put("/personal/categories", headers=H, json={"categories": without}).status_code == 409
    )  # a rule uses it
    rid = client.get("/personal/rules", headers=H).json()[0]["id"]
    assert client.delete(f"/personal/rules/{rid}", headers=H).status_code == 204
    assert client.put("/personal/categories", headers=H, json={"categories": without}).status_code == 200
    assert client.get("/personal/budgets", headers=H).json() == {}  # its budget went with it


def test_rule_validation(client: TestClient) -> None:
    bad = client.post(
        "/personal/rules", headers=H, json={"match": {"op": "regex", "value": "(a+)+"}, "category_id": "housing"}
    )
    assert bad.status_code == 422
    nocat = client.post(
        "/personal/rules", headers=H, json={"match": {"op": "contains", "value": "x"}, "category_id": "zz"}
    )
    assert nocat.status_code == 409
    assert client.delete("/personal/rules/nope", headers=H).status_code == 404
    assert (
        client.post(
            "/personal/rules", json={"match": {"op": "contains", "value": "x"}, "category_id": "housing"}
        ).status_code
        == 400
    )  # no X-User


def test_goals_routes(client: TestClient) -> None:
    body = {"name": "Holiday", "target_pence": 120000, "target_date": "2027-10-28", "saved_pence": 20000}
    made = client.post("/personal/goals", headers=H, json=body)
    assert made.status_code == 201, made.text
    plan = made.json()
    assert plan["monthly_needed_pence"] == 8334 and plan["estimate"] and plan["percent"] == 16  # 100000/12 up
    gid = plan["goal"]["id"]
    got = client.patch(f"/personal/goals/{gid}", headers=H, json={"saved_pence": 120000}).json()
    assert got["status"] == "reached"
    assert client.patch(f"/personal/goals/{gid}", headers=H, json={"saved_pence": None}).status_code == 409
    assert client.patch("/personal/goals/nope", headers=H, json={"name": "x"}).status_code == 404
    assert client.post("/personal/goals", headers=H, json={**body, "target_pence": 0}).status_code == 422
    assert client.post("/personal/goals", headers=H, json={**body, "target_date": "tomorrow"}).status_code == 422
    assert len(client.get("/personal/goals", headers=H).json()) == 1
    assert client.delete(f"/personal/goals/{gid}", headers=H).status_code == 204
    assert client.get("/personal/goals", headers=H).json() == []
