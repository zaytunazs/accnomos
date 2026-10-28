"""cis_read harness: cases, scoring, a full stub run and resuming. No model, no network."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from pathlib import Path

from harness import cis_read


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


def test_cases_cover_every_gold_cis_document() -> None:
    cases = cis_read.load_cases()
    assert len(cases) == 120
    assert Counter(c.kind for c in cases) == {"cis_statement": 60, "reverse_charge_invoice": 60}
    assert len({c.id for c in cases}) == len(cases)
    assert {c.id for c in cases} == {f"S{i:03d}" for i in range(1, 61)} | {f"R{i:03d}" for i in range(1, 61)}


def test_statement_and_invoice_score_different_fields() -> None:
    by_id = {c.id: c for c in cis_read.load_cases()}
    assert [f for f, _ in by_id["S001"].fields] == [f for f, _ in cis_read.STATEMENT_FIELDS]
    assert [f for f, _ in by_id["R001"].fields] == [f for f, _ in cis_read.INVOICE_FIELDS]
    assert by_id["S001"].expect_fail == []
    assert by_id["S009"].expect_fail == ["RATE"]
    assert by_id["R010"].expect_fail == ["RC_WORDING"]


def test_gold_rates_cover_all_payment_statuses() -> None:
    by_id = {c.id: c for c in cis_read.load_cases()}
    assert by_id["S001"].rate == 20 and by_id["S002"].rate == 30
    # statements: the CIS deduction rate (0/20/30 -> the settings status the checks run under)
    assert {c.rate for c in by_id.values() if c.kind == "cis_statement"} == {0, 20, 30}
    # invoices: the VAT rate (the settings status does not touch invoice checks)
    assert {c.rate for c in by_id.values() if c.kind == "reverse_charge_invoice"} == {5, 20}


def test_code_checks_match_expect_check_fail_on_gold_readings() -> None:
    """A perfect model reading must fail exactly the gold's expected checks (S009/R010 are distractors)."""
    from app import cis as cis_mod
    from app.ai.cis_read import CisReading
    from app.cis_readings import from_reading

    by_id = {c.id: c for c in cis_read.load_cases()}
    for cid in ("S001", "S002", "S009", "R001", "R010"):
        case = by_id[cid]
        reading = CisReading.model_validate({**case.expected, "confidence": 1.0})
        settings = cis_mod.CisSettings(status=cis_read.RATE_STATUS[case.rate])  # type: ignore[arg-type]
        code_reading, problems = from_reading(reading, case.id, settings)
        assert problems == [], (cid, problems)
        failing = sorted(c.code for c in code_reading.checks if not c.ok)
        assert failing == sorted(case.expect_fail), (cid, failing)


def test_field_comparators() -> None:
    eq = cis_read.field_eq
    assert eq(cis_read.NAME, "Aldermore Structures Ltd", "aldermore structures ltd")
    assert not eq(cis_read.NAME, "Aldermore", "Someone Else Entirely")
    assert eq(cis_read.UTR, "8159083016", "8159083016") and eq(cis_read.UTR, "81 590 83016", "8159083016")
    assert not eq(cis_read.UTR, "8159083016", "8159083017")
    assert eq(cis_read.VRN, "GB021167321", "GB 021 1673 21")
    assert eq(cis_read.MONEY, 5575.0, 5575.0) and eq(cis_read.MONEY, 5575.005, 5575.0)
    assert not eq(cis_read.MONEY, 5575.02, 5575.0)
    assert eq(cis_read.MONEY, None, None) and not eq(cis_read.MONEY, 1.0, None)
    assert eq(cis_read.DATE, "2026-10-05", "2026-10-05") and not eq(cis_read.DATE, "2026-10-06", "2026-10-05")
    assert eq(cis_read.BOOL, True, True) and not eq(cis_read.BOOL, False, True)
    assert eq(cis_read.RATE, 20.0, 20)


def test_dry_run_calls_nothing_and_writes_nothing(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    out = tmp_path / "o"
    assert asyncio.run(cis_read.main_async(_args(out, dry_run=True, show=3))) is None
    assert not out.exists()
    assert "documents" in capsys.readouterr().out


def test_stub_run_writes_report_and_resumes(tmp_path: Path) -> None:
    import httpx as httpx_mod

    original = httpx_mod.AsyncClient
    out = tmp_path / "o"
    s = asyncio.run(cis_read.main_async(_args(out, limit=24)))
    assert httpx_mod.AsyncClient is original  # the wrapper is always taken off again
    assert s is not None and s["stub"] and s["docs"] == 24
    assert (out / "report.md").read_text(encoding="utf-8").startswith("# CIS reader eval")
    assert "## Worst 10 misses" in (out / "report.md").read_text(encoding="utf-8")
    first = (out / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(first) == 24
    # a kill part-way: keep 10 lines (and a torn one), the next run asks only the rest
    (out / "results.jsonl").write_text("\n".join(first[:10]) + "\n" + first[10][:20], encoding="utf-8")
    s2 = asyncio.run(cis_read.main_async(_args(out, limit=24)))
    assert s2 is not None and s2["docs"] == 24
    rows = cis_read.read_results(out / "results.jsonl")  # the torn line is skipped
    assert len({r["id"] for r in rows}) == 24


def test_stub_faults_are_counted_not_crashed(tmp_path: Path) -> None:
    s = asyncio.run(cis_read.main_async(_args(tmp_path / "o")))
    assert s is not None
    assert s["docs"] == 120 and s["answered"] + s["refusals"] == 120
    assert s["refusals"] > 0  # the invalid-JSON fault
    assert 0 < s["all_exact_pct"] < 100
    assert set(s["per_field"]) >= {"kind", "gross_amount", "net", "reverse_charge_wording"}
    assert set(s["by_kind"]) == {"cis_statement", "reverse_charge_invoice"}
    assert 1 <= len(s["worst"]) <= 10
    assert all(w["wrong_fields"] or w["checks_want"] != w["checks_got"] for w in s["worst"])
    assert s["latency_s"]["p50"] <= s["latency_s"]["p95"]
