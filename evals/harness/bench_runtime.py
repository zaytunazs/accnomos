#!/usr/bin/env python3
"""Runtime speed on a real-sized book, measured on fakes with Graph-like latency.

Seeds an in-memory OneDrive with ``tools/seed_demo.py``'s full plan (59 ledger
events, the same book the demo runs), wraps it to count every storage call and
sleep ``--latency-ms`` per read/list (default 120 ms, like a Graph round trip),
then times the main read routes one by one.

    uv run python evals/harness/bench_runtime.py --mode before [--latency-ms 120]
    uv run python evals/harness/bench_runtime.py --mode after

Each run writes ``evals/runs/bench_runtime/run_<mode>.json``; when both
``run_before.json`` and ``run_after.json`` exist, ``report.md`` is rewritten
with the before/after table. A ``dashboard-revisit`` row re-runs the dashboard
without clearing the process cache, showing what a second page view by the same
user saves once immutable files are cached.

The numbers are honest about what they are: fakes plus a sleep, not OneDrive.
See ``docs/HONESTY.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _p in ("packages/connectors/src", "packages/ledger/src", "services/runtime", "evals"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

from accnomos_connectors import FakeStorageProvider  # noqa: E402
from accnomos_connectors.base import FileRef, StorageProvider  # noqa: E402

TODAY = date(2026, 10, 27)
BUSINESS = "Bramblewood Joinery Ltd"
OUT = ROOT / "evals" / "runs" / "bench_runtime"


def load_seed_demo():  # noqa: ANN201
    """tools/seed_demo.py loaded by path (the evals package does not depend on tools)."""
    tool = ROOT / "tools" / "seed_demo.py"
    spec = importlib.util.spec_from_file_location("seed_demo", tool)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["seed_demo"] = mod  # its dataclasses look their module up by name
    spec.loader.exec_module(mod)
    return mod


class CountedStorage(StorageProvider):
    """Count every storage call and sleep `latency_s` on each read/list, like a Graph round trip."""

    def __init__(self, inner: StorageProvider, latency_s: float) -> None:
        self.inner = inner
        self.latency_s = latency_s
        self.calls: dict[str, int] = {"list": 0, "read": 0, "write": 0, "move": 0, "ensure": 0}
        self.event_reads = 0  # reads of immutable ledger event files: what the per-user cache should absorb

    def reset(self) -> None:
        for k in self.calls:
            self.calls[k] = 0
        self.event_reads = 0

    def total_reads(self) -> int:
        return self.calls["list"] + self.calls["read"]

    async def _wait(self) -> None:
        if self.latency_s > 0:
            await asyncio.sleep(self.latency_s)

    async def ensure_root(self) -> FileRef:
        self.calls["ensure"] += 1
        return await self.inner.ensure_root()

    async def ensure_folder(self, path: str) -> FileRef:
        self.calls["ensure"] += 1
        return await self.inner.ensure_folder(path)

    async def list(self, path: str) -> list[FileRef]:
        self.calls["list"] += 1
        await self._wait()
        return await self.inner.list(path)

    async def read(self, path: str) -> bytes:
        self.calls["read"] += 1
        if path.strip("/").startswith("_System/Ledger/events/"):
            self.event_reads += 1
        await self._wait()
        return await self.inner.read(path)

    async def write(self, path: str, data: bytes, *, if_match: str | None = None, create_only: bool = False) -> FileRef:
        self.calls["write"] += 1
        return await self.inner.write(path, data, if_match=if_match, create_only=create_only)

    async def move(self, path: str, new_path: str) -> FileRef:
        self.calls["move"] += 1
        return await self.inner.move(path, new_path)

    async def changes(self, cursor: str | None) -> tuple[list[FileRef], str]:
        return await self.inner.changes(cursor)


def make_books(storage: StorageProvider):  # noqa: ANN201
    """A Books over `storage` for one request, with the per-user cache key when the app supports it."""
    from app.books import Books

    try:
        return Books(storage, cache_key="bench")  # type: ignore[call-arg]
    except TypeError:
        return Books(storage)


def clear_process_cache() -> None:
    try:
        from app import cache

        cache.clear()
    except (ImportError, AttributeError):
        pass


async def build_routes(seed_demo: Any, plan: Any) -> list[tuple[str, Callable[[], Awaitable[Any]]]]:
    """(name, run) for each timed route. Each run builds its own Books: one request, one Books."""
    from app import audit_view, bank_reconcile, dashboard
    from app import contacts as cb
    from app import invoicing as inv_
    from app import payments as pay_
    from app import reports as rp
    from app.deadlines import recent_periods
    from app.routes_books import proposals as review_list
    from app.routes_invoices import list_invoices as invoices_route
    from app.routes_vat import vat_periods, vat_return
    from app.taxyear import uk_tax_year_start
    from app.vat_cycle import VatCycle

    storage = build_routes.storage  # type: ignore[attr-defined]
    cycle = VatCycle(start_month=plan.current[0].month, months=3)
    cur_start, cur_end = cycle.current(plan.today)

    async def home() -> Any:
        return await dashboard.build(
            make_books(storage), plan.today, cycle.start_month, cycle.months, vat_assumed=cycle.assumed
        )

    async def review() -> Any:
        return await review_list(status=None, books=make_books(storage))

    async def vat() -> Any:
        return await vat_return(
            period_start=None,
            period_end=None,
            period=None,
            start=None,
            end=None,
            period_key=None,
            today=plan.today,
            cycle=cycle,
            books=make_books(storage),
        )

    async def periods() -> Any:
        return await vat_periods(today=plan.today, cycle=cycle, books=make_books(storage))

    async def pl() -> Any:
        books = make_books(storage)
        events = await books.list_events(cur_start, cur_end)
        return rp.profit_and_loss(events, cur_start, cur_end)

    async def aged() -> Any:
        books = make_books(storage)
        contacts, ledger, _ = await cb.contact_book(books)
        return cb.aged(contacts, ledger, plan.today)

    async def vat_summary() -> Any:
        books = make_books(storage)
        spans = recent_periods(plan.today, cycle.start_month, cycle.months, previous=3)
        events = await books.list_events(spans[-1][0], spans[0][1])
        return rp.vat_summary(events, spans, cycle.months)

    async def trend() -> Any:
        books = make_books(storage)
        events = await books.list_events(*rp.trend_window(plan.today, 12))
        return rp.monthly_trend(events, plan.today, 12)

    async def contacts() -> Any:
        books = make_books(storage)
        found, ledger, saved = await cb.contact_book(books)
        start = uk_tax_year_start(plan.today)
        return cb.with_totals(found, ledger, start, plan.today), saved

    async def statement() -> Any:
        books = make_books(storage)
        found, ledger, _ = await cb.contact_book(books)
        contact = sorted(found, key=lambda c: c.name)[0]
        docs = cb.assign([contact], cb.documents(ledger)).get(contact.id, [])
        return cb.statement(contact, docs, ledger, None, None)

    async def bank_lines() -> Any:
        return await make_books(storage).list_bank_lines()

    async def reconcile() -> Any:
        books = make_books(storage)
        return await bank_reconcile.reconcile_lines(books, await books.list_bank_lines(), with_ai=False)

    async def invoices() -> Any:
        return await invoices_route(status=None, books=make_books(storage))

    async def audit_day() -> Any:
        return await audit_view.read(make_books(storage), plan.today, plan.today)

    # Touch the ledgers the routes read so names below are honest about what ran.
    assert inv_ is not None and pay_ is not None
    return [
        ("dashboard", home),
        ("review list", review),
        ("VAT return", vat),
        ("VAT periods", periods),
        ("report P&L", pl),
        ("report aged", aged),
        ("report VAT", vat_summary),
        ("report trend", trend),
        ("contacts list", contacts),
        ("contact statement", statement),
        ("bank lines", bank_lines),
        ("bank reconcile", reconcile),
        ("invoices list", invoices),
        ("audit day", audit_day),
    ]


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", default="before", help="labels the run file: run_<mode>.json")
    ap.add_argument("--latency-ms", type=float, default=120, help="simulated per-call latency in ms")
    ap.add_argument("--routes", nargs="*", default=None, help="only these route names (for a quick smoke run)")
    args = ap.parse_args()

    seed_demo = load_seed_demo()
    plan = seed_demo.build_plan(BUSINESS, TODAY)
    print(f"seeding {BUSINESS} ({plan.event_count} ledger events)...", flush=True)
    raw = FakeStorageProvider()
    t0 = time.perf_counter()
    await seed_demo.seed(raw, plan, say=lambda _m: None)
    print(f"seeded in {time.perf_counter() - t0:.1f}s", flush=True)

    storage = CountedStorage(raw, args.latency_ms / 1000)
    build_routes.storage = storage  # type: ignore[attr-defined]
    routes = await build_routes(seed_demo, plan)
    by_name = dict(routes)
    if args.routes:
        wanted = set(args.routes)
        routes = [(n, r) for n, r in routes if n in wanted]
        if not routes and "dashboard-revisit" not in wanted:
            print(f"no routes match {sorted(wanted)}")
            return 1

    OUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}
    for name, run in routes:
        clear_process_cache()
        storage.reset()
        t0 = time.perf_counter()
        out = await run()
        seconds = time.perf_counter() - t0
        calls = dict(storage.calls)
        results[name] = {
            "calls": calls,
            "round_trips": calls["list"] + calls["read"],
            "event_reads": storage.event_reads,
            "seconds": round(seconds, 2),
        }
        size = len(out) if hasattr(out, "__len__") else 1
        print(f"{name:18s} {results[name]['round_trips']:5d} round trips  {seconds:7.2f}s  (rows {size})", flush=True)

    # Same user opens the dashboard again: the process cache stays warm for this one row. It is primed by a
    # dashboard run of its own first: the loop above clears the cache before every row, so by now it holds only
    # what the last row read (the audit day reads no events), and a revisit straight after it was cold.
    if args.routes is None or "dashboard-revisit" in args.routes:
        clear_process_cache()
        await by_name["dashboard"]()
        storage.reset()
        t0 = time.perf_counter()
        await by_name["dashboard"]()
        seconds = time.perf_counter() - t0
        calls = dict(storage.calls)
        results["dashboard-revisit (warm)"] = {
            "calls": calls,
            "round_trips": calls["list"] + calls["read"],
            "event_reads": storage.event_reads,
            "seconds": round(seconds, 2),
        }
        print(
            f"{'dashboard-revisit (warm)':18s} {results['dashboard-revisit (warm)']['round_trips']:5d}"
            f" round trips  {seconds:7.2f}s",
            flush=True,
        )

    payload = {
        "mode": args.mode,
        "latency_ms": args.latency_ms,
        "business": BUSINESS,
        "today": TODAY.isoformat(),
        "events": plan.event_count,
        "routes": results,
    }
    (OUT / f"run_{args.mode}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_report()
    return 0


def write_report() -> None:
    """report.md from run_before.json alone, or the before/after table when both runs exist."""
    before_p, after_p = OUT / "run_before.json", OUT / "run_after.json"
    if not before_p.exists():
        return
    before = json.loads(before_p.read_text(encoding="utf-8"))
    after = json.loads(after_p.read_text(encoding="utf-8")) if after_p.exists() else None

    lines = [
        "# Runtime speed on a real-sized book",
        "",
        f"Book: {before['business']} as seeded by `tools/seed_demo.py`"
        f" ({before['events']} ledger events, {before['today']}).",
        f"Storage: in-memory fake OneDrive; every `list`/`read` sleeps"
        f" {before['latency_ms']} ms, standing in for a Graph round trip.",
        "Each row is one request (its own `Books`); the process cache is cleared",
        "between rows, except `dashboard-revisit (warm)`, which is the same user",
        "opening the dashboard again straight after a first view (only the immutable",
        "ledger event files carry over; everything else is read again).",
        "**These numbers are on fakes with simulated latency, not on OneDrive**",
        "(`docs/HONESTY.md`). They compare code paths, not the network.",
        "VAT return and report P&L default to the current period, which holds no posted events",
        "in the seeded book (its events are in the two previous periods): those rows show the",
        "cheap default, while VAT periods / VAT summary / trend cover the heavy event reads.",
        "",
    ]
    if after is None:
        lines += [
            f"Run: `{before['mode']}` only so far — re-run with `--mode after` once the",
            "fix lands and this report gains the before/after table.",
            "",
            "| route | round trips | seconds |",
            "|---|---|---|",
        ]
        for name, r in before["routes"].items():
            lines.append(f"| {name} | {r['round_trips']} | {r['seconds']:.2f} |")
    else:
        assert after["latency_ms"] == before["latency_ms"], "compare runs with the same --latency-ms"
        lines += [
            "| route | before: trips | before: s | after: trips | after: s | trips saved | time saved |",
            "|---|---|---|---|---|---|---|",
        ]
        t_b = t_a = 0.0
        for name, b in before["routes"].items():
            a = after["routes"].get(name)
            if a is None:
                lines.append(f"| {name} | {b['round_trips']} | {b['seconds']:.2f} | — | — | — | — |")
                t_b += b["seconds"]
                continue
            lines.append(
                f"| {name} | {b['round_trips']} | {b['seconds']:.2f} |"
                f" {a['round_trips']} | {a['seconds']:.2f} |"
                f" {b['round_trips'] - a['round_trips']} | {b['seconds'] - a['seconds']:.2f} s |"
            )
            t_b += b["seconds"]
            t_a += a["seconds"]
        lines += [
            "",
            f"Total page-load time across these routes: {t_b:.1f} s before, {t_a:.1f} s after"
            f" (simulated {before['latency_ms']} ms per round trip).",
        ]
    lines.append("")
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
