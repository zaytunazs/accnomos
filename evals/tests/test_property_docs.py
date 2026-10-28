"""property_docs harness: cases, expectations, a full stub run and resuming. No model, no network."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from pathlib import Path

from harness import property_docs


def _args(out: Path, **kw: object) -> argparse.Namespace:
    base = {
        "base": "http://127.0.0.1:1",  # nothing listens here: the stub must never reach it
        "model": "muse-glimmer:30b",
        "limit": 0,
        "dry_run": False,
        "stub": True,
        "fresh": False,
        "show": 0,
        "out": str(out),
    }
    return argparse.Namespace(**{**base, **kw})


def test_cases_cover_every_landlord_document() -> None:
    cases = property_docs.load_cases()
    assert len(cases) == 108
    assert Counter(c.kind for c in cases) == {
        "letting_statement": 72,
        "insurance": 6,
        "mortgage_statement": 6,
        "invoice": 24,
    }
    assert Counter(c.landlord for c in cases) == {f"landlord_{n}": 18 for n in (7, 8, 9, 10, 11, 12)}
    assert len({c.id for c in cases}) == len(cases)
    by_id = {c.id: c for c in cases}
    flat_apr = by_id["landlord_7/2026-04_flat"]
    assert [c for c, _ in flat_apr.figures] == ["rents", "professional"]
    assert dict(flat_apr.figures) == {"rents": 78000, "professional": 9360}
    mortgage = next(c for c in cases if c.kind == "mortgage_statement" and c.landlord == "landlord_7")
    assert dict(mortgage.figures) == {"finance_res": 234192}


def test_headline_totals_on_landlord_7() -> None:
    """Payout for statements; printed Total, largest `of which` line, or the sum of positives for bills."""
    by_id = {c.id: c for c in property_docs.load_cases() if c.landlord == "landlord_7"}
    flat_apr = by_id["landlord_7/2026-04_flat"]
    assert flat_apr.kind == "letting_statement" and flat_apr.amount_pence == 68640
    assert flat_apr.categories == {"Sales"} and flat_apr.date == "2026-04-28"
    by_kind_date = {(c.kind, c.date): c for c in by_id.values()}
    assert by_kind_date[("insurance", "2026-04-20")].amount_pence == 22425
    assert by_kind_date[("mortgage_statement", "2026-10-05")].amount_pence == 393600
    assert by_kind_date[("invoice", "2026-05-14")].amount_pence == 9100  # gas safety, one line
    assert by_kind_date[("invoice", "2026-08-03")].amount_pence == 22980  # boiler repair, printed Total
    assert by_kind_date[("invoice", "2026-06-22")].amount_pence == 40799  # washing machine, cost + disposal
    assert by_kind_date[("invoice", "2026-06-24")].amount_pence == 111800  # ground rent + service charge


def test_invoice_categories_follow_the_gold_figure() -> None:
    by_id = {c.id: c for c in property_docs.load_cases() if c.landlord == "landlord_7"}
    by_kind_date = {(c.kind, c.date): c for c in by_id.values()}
    assert by_kind_date[("invoice", "2026-08-03")].categories == {"Tools & small equipment", "Materials"}
    assert by_kind_date[("invoice", "2026-05-14")].categories == {"Sundry"}
    assert by_kind_date[("insurance", "2026-04-20")].categories == {"Insurance"}
    assert "Bank charges" in by_kind_date[("mortgage_statement", "2026-10-05")].categories


def test_register_matches_by_address_tokens() -> None:
    props = property_docs.landlord_properties("landlord_7")
    assert [p.id for p in props] == ["flat", "house"]
    cases = {c.id: c for c in property_docs.load_cases() if c.landlord == "landlord_7"}
    flat = cases["landlord_7/2026-04_flat"]
    assert property_docs.prop_read_mod.match_property(props, flat.text) is not None
    assert property_docs.prop_read_mod.match_property(props, flat.text).id == "flat"
    assert property_docs.prop_read_mod.match_property(props, "99 Unknown Road, Nowhere XX1 1QQ") is None


def test_score_figures_counts_vat_with_net() -> None:
    """A VAT-separate invoice line (net in amount, VAT in vat) scores against the gross gold figure."""
    from datetime import datetime

    mod = property_docs.prop_read_mod
    reading = mod.Reading(
        id="vat-case",
        path="bills/16_invoice.txt",
        sha256="",
        kind="invoice",
        lines=[
            mod.ReadLine(description="net", category="repairs", amount_pence=14900, vat_pence=2980),
            mod.ReadLine(description="Total", category="repairs", amount_pence=17880, info=True),
        ],
        total_pence=17880,
        created_at=datetime(2026, 8, 3),
    )
    fields, got, _ = property_docs.score_figures(reading, [("repairs", 17880)])
    assert fields == {"cat:repairs": True, "amt:repairs": True}
    assert got == {"repairs": 178.8}


def test_dry_run_calls_nothing_and_writes_nothing(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    out = tmp_path / "o"
    assert asyncio.run(property_docs.main_async(_args(out, dry_run=True, show=3))) is None
    assert not out.exists()
    assert "documents" in capsys.readouterr().out


def test_stub_run_writes_report_and_resumes(tmp_path: Path) -> None:
    import httpx as httpx_mod

    original = httpx_mod.AsyncClient
    out = tmp_path / "o"
    s = asyncio.run(property_docs.main_async(_args(out, limit=24)))
    assert httpx_mod.AsyncClient is original  # the wrapper is always taken off again
    assert s is not None and s["stub"] and s["docs"] == 24 and s["reader"] == "property"
    report = (out / "report.md").read_text(encoding="utf-8")
    assert report.startswith("# Property documents eval")
    assert "generic" in report.lower()  # the generic reader is kept as a baseline column
    assert "## Worst 10 misses" in report
    assert s["baseline"]["reader"] == "generic"
    assert set(s["per_field"]) == {"kind", "property", "line_category", "line_amount"}
    first = (out / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(first) == 24
    # a kill part-way: keep 10 lines (and a torn one), the next run asks only the rest
    (out / "results.jsonl").write_text("\n".join(first[:10]) + "\n" + first[10][:20], encoding="utf-8")
    s2 = asyncio.run(property_docs.main_async(_args(out, limit=24)))
    assert s2 is not None and s2["docs"] == 24
    rows = property_docs.read_results(out / "results.jsonl")  # the torn line is skipped
    assert len({r["id"] for r in rows}) == 24


def test_stub_faults_are_counted_not_crashed(tmp_path: Path) -> None:
    s = asyncio.run(property_docs.main_async(_args(tmp_path / "o")))
    assert s is not None
    assert s["docs"] == 108 and s["answered"] + s["refusals"] == 108
    assert s["refusals"] > 0  # the invalid-JSON fault
    assert 0 < s["all_exact_pct"] < 100
    assert set(s["per_field"]) == {"kind", "property", "line_category", "line_amount"}
    assert set(s["by_kind"]) == {"letting_statement", "insurance", "mortgage_statement", "invoice"}
    assert all({"baseline_exact", "baseline_pct"} <= set(v) for v in s["by_kind"].values())
    assert 1 <= len(s["worst"]) <= 10
    assert all(w["wrong_fields"] for w in s["worst"])
    assert s["latency_s"]["p50"] <= s["latency_s"]["p95"]
