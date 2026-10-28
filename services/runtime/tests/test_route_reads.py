"""The read routes made cheaper in app/cache.py, app/books.py, app/contacts.py, app/dashboard.py and
app/bank_reconcile.py return the same JSON as before, on the seeded demo book (tools/seed_demo.py).

"Before" is the route over the bare storage: no request memo, no per-user cache, every look a round trip.
"After" is the route as the app serves it: a cold first request, then a warm second one by the same user.
The three must be identical (timestamps a route makes up on the spot, `created_at`/`updated_at` of contacts not
saved yet, are dropped). Each route is also held to its round trips: no path is fetched twice in one request.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.encoders import jsonable_encoder

from accnomos_connectors import FakeStorageProvider
from app import bank_reconcile, cache, dashboard
from app import contacts as cb
from app.books import Books
from app.deadlines import recent_periods
from app.reports import monthly_trend, trend_window, vat_summary
from app.routes_invoices import list_invoices
from app.routes_vat import vat_periods
from app.taxyear import uk_tax_year_start
from app.vat_cycle import VatCycle

TOOL = Path(__file__).resolve().parents[3] / "tools" / "seed_demo.py"
TODAY = date(2026, 10, 27)


class Logged(FakeStorageProvider):
    """The seeded files, with every list and read logged as a round trip."""

    def __init__(self, files: dict[str, bytes], folders: set[str]) -> None:
        super().__init__()
        self.files, self.folders = dict(files), set(folders)
        self.trips: list[tuple[str, str]] = []

    async def list(self, path: str):  # noqa: ANN201
        self.trips.append(("list", path.strip("/")))
        return await super().list(path)

    async def read(self, path: str) -> bytes:
        self.trips.append(("read", path.strip("/")))
        return await super().read(path)


@pytest.fixture(scope="module")
def book() -> tuple[Any, FakeStorageProvider]:
    spec = importlib.util.spec_from_file_location("seed_demo", TOOL)
    assert spec and spec.loader
    seed_demo = importlib.util.module_from_spec(spec)
    sys.modules["seed_demo"] = seed_demo  # dataclasses look their module up by name
    spec.loader.exec_module(seed_demo)
    plan = seed_demo.build_plan("Bramblewood Joinery Ltd", TODAY)
    fake = FakeStorageProvider()
    asyncio.run(seed_demo.seed(fake, plan, say=lambda _msg: None))
    return plan, fake


Route = Callable[[Books], Awaitable[Any]]


def _routes(plan: Any) -> dict[str, Route]:
    cycle = VatCycle(start_month=plan.current[0].month, months=3)

    async def home(books: Books) -> Any:
        return await dashboard.build(books, plan.today, cycle.start_month, cycle.months, vat_assumed=cycle.assumed)

    async def periods(books: Books) -> Any:
        return await vat_periods(today=plan.today, cycle=cycle, books=books)

    async def report_vat(books: Books) -> Any:
        spans = recent_periods(plan.today, cycle.start_month, cycle.months, previous=3)
        return vat_summary(await books.list_events(spans[-1][0], spans[0][1]), spans, cycle.months)

    async def trend(books: Books) -> Any:
        return monthly_trend(await books.list_events(*trend_window(plan.today, 12)), plan.today, 12)

    async def aged(books: Books) -> Any:
        found, ledger, _ = await cb.contact_book(books)
        return cb.aged(found, ledger, plan.today)

    async def contacts(books: Books) -> Any:
        found, ledger, saved = await cb.contact_book(books)
        return cb.with_totals(found, ledger, uk_tax_year_start(plan.today), plan.today), saved

    async def statement(books: Books) -> Any:
        found, ledger, _ = await cb.contact_book(books)
        out = []
        for contact in sorted(found, key=lambda c: c.name):
            docs = cb.assign([contact], cb.documents(ledger)).get(contact.id, [])
            out.append(cb.statement(contact, docs, ledger, None, None))
        return out

    async def bank_lines(books: Books) -> Any:
        return await books.list_bank_lines()

    async def reconcile(books: Books) -> Any:
        return await bank_reconcile.reconcile_lines(books, await books.list_bank_lines(), with_ai=False)

    async def invoices(books: Books) -> Any:
        return await list_invoices(status=None, books=books)

    return {
        "dashboard": home,
        "VAT periods": periods,
        "report VAT": report_vat,
        "report trend": trend,
        "report aged": aged,
        "contacts list": contacts,
        "contact statement": statement,
        "bank lines": bank_lines,
        "bank reconcile": reconcile,
        "invoices list": invoices,
    }


def _json(value: Any) -> Any:
    def strip(x: Any) -> Any:
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k not in ("created_at", "updated_at")}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x

    return strip(jsonable_encoder(value))


ROUTES = (
    "dashboard",
    "VAT periods",
    "report VAT",
    "report trend",
    "report aged",
    "contacts list",
    "contact statement",
    "bank lines",
    "bank reconcile",
    "invoices list",
)


def test_every_route_is_checked(book: tuple[Any, FakeStorageProvider]) -> None:
    assert set(ROUTES) == set(_routes(book[0]))


@pytest.mark.parametrize("name", ROUTES)
async def test_same_json_before_and_after(book: tuple[Any, FakeStorageProvider], name: str) -> None:
    plan, fake = book
    run = _routes(plan)[name]
    cache.clear()
    try:
        bare = Logged(fake.files, fake.folders)
        before = _json(await run(Books(bare)))  # no memo, no cache: what a request read before the memo existed

        served = Logged(fake.files, fake.folders)
        cold = _json(await run(Books(served, cache_key=cache.user_cache_key("demo-token"))))
        cold_trips = list(served.trips)
        served.trips.clear()
        warm = _json(await run(Books(served, cache_key=cache.user_cache_key("demo-token"))))
    finally:
        cache.clear()

    assert cold == before
    assert warm == before
    assert before  # the seeded book gives every route something to show
    twice = [trip for trip, n in Counter(cold_trips).items() if n > 1]
    assert twice == [], f"{name} fetched these more than once in one request: {twice[:5]}"
    assert len(cold_trips) <= len(bare.trips)
    assert not [p for kind, p in served.trips if kind == "read" and cache.is_immutable(p)]  # warm: no event re-read


async def test_reconcile_reads_each_missing_file_once(book: tuple[Any, FakeStorageProvider]) -> None:
    """Every open line looks for credit_uses.json, which the seeded book lacks: one round trip, not one per line."""
    plan, fake = book
    served = Logged(fake.files, fake.folders)
    books = Books(served, cache_key=cache.user_cache_key("demo-token"))
    cache.clear()
    try:
        rows = await _routes(plan)["bank reconcile"](books)
    finally:
        cache.clear()
    assert rows
    assert Counter(served.trips)[("read", "_System/Payments/credit_uses.json")] == 1
