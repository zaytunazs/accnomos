"""The personal demo (app/demo_personal.py) and the company demo's goals: real household books, fast, labelled
fictional, with a mix of goal statuses; and the sandbox (app/demo.py) handing out either kind."""

from __future__ import annotations

import time
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app import demo, demo_personal
from app import goals as gm
from app import personal as pf
from app import profile as profile_mod
from app.books import Books
from app.routes_books import router as books_router
from app.routes_goals import router as goals_router
from app.routes_personal import router as personal_router

DAY = date(2026, 11, 20)
SECRET = "s" * 40


async def test_household_books_are_personal_fictional_and_quick() -> None:
    started = time.perf_counter()
    st = await demo_personal.build_storage(DAY)
    assert time.perf_counter() - started < 10
    books = Books(st)
    prof = await profile_mod.load(books)
    assert prof.kind == "personal" and "fictional" in prof.name and "vat" not in prof.features
    lines = await books.stored_bank_lines()
    assert len(lines) > 500 and min(ln.date for ln in lines) == date(2025, 1, 1) and max(ln.date for ln in lines) <= DAY
    cats = {c.name for c in await pf.load_categories(books)}
    assert demo_personal.COFFEE in cats
    s = pf.summarise_month(
        "2026-10",
        lines,
        await pf.load_categories(books),
        await pf.load_budgets(books),
        await pf.load_rules(books),
        await pf.load_overrides(books),
    )
    spent = {c.name: c.spent_pence for c in s.categories}
    assert spent[demo_personal.COFFEE] > 0 and spent["Groceries"] > 25_000 and spent["Housing"] > 140_000
    assert s.uncategorised_count <= 2  # nearly every line is categorised


@pytest.mark.parametrize("day", [date(2026, 11, 2), DAY, date(2027, 3, 15), date(2027, 8, 30)])
async def test_household_goals_have_mixed_statuses_on_any_day(day: date) -> None:
    books = Books(await demo_personal.build_storage(day))
    goals = await gm.load_goals(books)
    data = await gm.load_data(books, goals, True, day)
    statuses = {g.name: gm.progress(g, data, day).status for g in goals}
    assert len(goals) == 5
    assert statuses["Rainy-day fund"] == "on_track"
    assert statuses["Summer holiday pot"] == "at_risk"
    assert statuses["School fees"] == "off_track"
    assert statuses["Spend less on coffee"] in ("over_limit", "off_track")


async def test_company_goals_are_sized_from_the_books() -> None:
    st = FakeStorageProvider()
    goals = await demo_personal.add_company_goals(st, DAY)
    assert [g.kind for g in goals] == ["earn", "spend_cap", "save"]
    assert goals[0].name == "November sales" and goals[0].target_pence and goals[0].target_pence >= 100_000
    books = Books(st)
    data = await gm.load_data(books, goals, False, DAY)
    assert gm.progress(goals[2], data, DAY).status == "off_track"  # the VAT pot is half its pace


# --------------------------------------------------------------------------- #
# The sandbox hands out either demo
# --------------------------------------------------------------------------- #


async def small_company(day: date) -> demo.Snapshot:
    st = FakeStorageProvider()
    await st.write("README.txt", b"SAMPLE - FICTIONAL COMPANY")
    return demo.Snapshot(day, st, "Bramblewood Joinery Ltd", 0.01)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_SECRET", SECRET)
    monkeypatch.delenv("ACCNOMOS_TEST_MODE", raising=False)
    monkeypatch.setattr(demo, "BUILD", small_company)
    monkeypatch.setattr(demo, "CREATE_LIMITER", None)
    monkeypatch.setattr(demo, "current_date", lambda: DAY)
    demo.reset_for_tests()
    app = FastAPI()
    for r in (demo.router, books_router, goals_router, personal_router):
        app.include_router(r)
    yield TestClient(app)
    demo.reset_for_tests()


def test_a_personal_session_has_household_books_and_goals(client: TestClient) -> None:
    r = client.post("/demo/session?kind=personal")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "personal" and body["label"] == "SAMPLE — FICTIONAL HOUSEHOLD"
    assert body["business"] == demo_personal.HOUSEHOLD
    h = {demo.HEADER: body["session"], "X-User": demo.USER}
    assert client.get("/demo/session", headers=h).json()["kind"] == "personal"
    view = client.get(f"/books/goals?today={DAY}&note_ai=false", headers=h).json()
    assert view["household"] is True
    statuses = {g["status"] for g in view["goals"]}
    assert {"on_track", "at_risk", "off_track"} <= statuses
    assert view["note"]["note_md"]
    s = client.get("/personal/summary?month=2026-10", headers=h)
    assert s.status_code == 200 and s.json()["spent_pence"] > 0


def test_company_is_still_the_default_and_switching_drops_the_old_session(client: TestClient) -> None:
    company = client.post("/demo/session").json()
    assert company["kind"] == "company" and company["label"] == "SAMPLE — FICTIONAL COMPANY"
    personal = client.post("/demo/session?kind=personal", headers={demo.HEADER: company["session"]}).json()
    assert personal["kind"] == "personal"
    assert client.get("/demo/session", headers={demo.HEADER: company["session"]}).status_code == 401
    assert client.post("/demo/session?kind=shop").status_code == 422


def test_health_reports_both_kinds(client: TestClient) -> None:
    first = demo.status()
    assert first["kinds"] == {"company": False, "personal": False}
    (b,) = demo._builds.values()
    assert b.done.wait(30)
    demo.status()  # company ready: this check starts the household books
    (p,) = demo._pbuilds.values()
    assert p.done.wait(30)
    assert demo.status()["kinds"] == {"company": True, "personal": True}
