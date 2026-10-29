"""classify harness: cases, labels, a stub run and resuming. No model, no network."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

from app.ai import classify as classify_mod
from harness import classify


def _args(out: Path, **kw: object) -> argparse.Namespace:
    base = {
        "limit": 0,
        "dry_run": False,
        "stub": True,
        "fresh": False,
        "show": 0,
        "base": "http://127.0.0.1:1",  # nothing listens here: the stub must never reach it
        "model": "muse-glimmer:30b",
        "out": str(out),
    }
    return argparse.Namespace(**{**base, **kw})


def test_cases_cover_every_gold_source() -> None:
    cases = classify.load_cases()
    assert Counter(c.source for c in cases) == {"receipts": 200, "cis": 120, "landlord": 108, "bank_csv": 6}
    assert len({c.id for c in cases}) == len(cases)
    assert all(c.label in classify_mod.KINDS for c in cases)
    assert all(c.text.strip() for c in cases)


def test_receipt_labels_follow_gold_doc_type_and_side() -> None:
    by_id = {c.id: c for c in classify.load_cases()}
    assert by_id["receipts/001_standard"].label == "receipt"
    assert by_id["receipts/007_full_invoice"].label == "sales_invoice"
    assert by_id["receipts/008_sales_invoice"].label == "sales_invoice"
    assert by_id["receipts/010_foreign"].label == "purchase_invoice"
    assert by_id["receipts/062_sales"].label == "sales_invoice"
    assert by_id["receipts/061_credit_note"].label == "credit_note"
    assert by_id["receipts/067_utility"].label == "purchase_invoice"
    assert by_id["receipts/068_pi_subcontractor"].label == "purchase_invoice"
    assert by_id["receipts/182_edge_reverse_charge"].label == "purchase_invoice"


def test_cis_and_landlord_labels_use_the_classifier_type_set() -> None:
    by_id = {c.id: c for c in classify.load_cases()}
    assert by_id["cis/S001"].label == "other"
    assert by_id["cis/R001"].label == "purchase_invoice"
    assert by_id["landlord/landlord_7/2026-04_flat"].label == "other"
    assert by_id["landlord/landlord_7/13_insurance"].label == "purchase_invoice"
    assert by_id["landlord/landlord_7/14_mortgage_statement"].label == "bank_statement"
    assert by_id["landlord/landlord_7/15_invoice"].label == "purchase_invoice"
    assert Counter(c.label for c in classify.load_cases() if c.source == "cis") == {
        "other": 60,
        "purchase_invoice": 60,
    }
    assert Counter(c.label for c in classify.load_cases() if c.source == "landlord") == {
        "other": 72,
        "purchase_invoice": 30,
        "bank_statement": 6,
    }


def test_bank_csvs_are_seed_layout_statements() -> None:
    text = classify.bank_csv_text(1001)
    assert "SAMPLE" in text and "Counter Party" in text and "Amount (GBP)" in text
    assert classify.bank_csv_text(1001) == text  # deterministic per seed
    assert classify.bank_csv_text(1002) != text


def test_default_config_prefers_meta_key_over_local() -> None:
    import os

    env = dict(os.environ)
    try:
        os.environ["META_API_KEY"] = "k"
        cfg = classify.default_config()
        assert (cfg.mode, cfg.provider) == ("key", "key")
        del os.environ["META_API_KEY"]
        os.environ["OLLAMA_URL"] = "http://127.0.0.1:11434/api/tags"
        cfg = classify.default_config()
        assert (cfg.mode, cfg.base_url) == ("local", "http://127.0.0.1:11434")
    finally:
        os.environ.clear()
        os.environ.update(env)


def test_dry_run_calls_nothing_and_writes_nothing(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    out = tmp_path / "o"
    assert asyncio.run(classify.main_async(_args(out, dry_run=True, show=3))) is None
    assert not out.exists()
    assert "documents" in capsys.readouterr().out


def test_stub_run_writes_report_and_resumes(tmp_path: Path) -> None:
    import httpx as httpx_mod

    original = httpx_mod.AsyncClient
    out = tmp_path / "o"
    s = asyncio.run(classify.main_async(_args(out, limit=24)))
    assert httpx_mod.AsyncClient is original  # the wrapper is always taken off again
    assert s is not None and s["stub"] and s["docs"] == 24
    assert (out / "report.md").read_text(encoding="utf-8").startswith("# Document-type classifier eval")
    assert "## Confusion matrix" in (out / "report.md").read_text(encoding="utf-8")
    first = (out / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(first) == 24
    # a kill part-way: keep 10 lines (and a torn one), the next run asks only the rest
    (out / "results.jsonl").write_text("\n".join(first[:10]) + "\n" + first[10][:20], encoding="utf-8")
    s2 = asyncio.run(classify.main_async(_args(out, limit=24)))
    assert s2 is not None and s2["docs"] == 24
    rows = classify.read_results(out / "results.jsonl")  # the torn line is skipped
    assert len({r["id"] for r in rows}) == 24


def test_stub_faults_are_counted_not_crashed(tmp_path: Path) -> None:
    s = asyncio.run(classify.main_async(_args(tmp_path / "o")))
    assert s is not None
    assert s["docs"] == 434 and s["answered"] + s["refusals"] == 434
    assert s["fallback_used"] > 0  # the invalid-JSON fault: code's by_words guessed
    assert s["csv_by_code"] == 6  # the seed-layout CSVs never reach the model
    assert 0 < s["accuracy_pct"] < 100
    assert set(s["per_type"]) == set(classify_mod.KINDS)
    assert set(s["by_source"]) == {"receipts", "cis", "landlord", "bank_csv"}
    for kind, cells in s["confusion"].items():  # each gold row scores every answered document
        assert sum(cells.values()) == s["per_type"][kind]["gold"]
    assert s["latency_s"]["p50"] <= s["latency_s"]["p95"]
    assert 1 <= len(s["worst"]) <= 10


def test_no_server_without_key_is_exit_2(tmp_path: Path) -> None:
    import os

    env = dict(os.environ)
    try:
        os.environ.pop("META_API_KEY", None)
        args = _args(tmp_path / "o", stub=False, base="http://127.0.0.1:1")
        assert classify.main(["--base", "http://127.0.0.1:1", "--out", str(tmp_path / "o")]) == 2
        _ = args
    finally:
        os.environ.clear()
        os.environ.update(env)


def test_report_never_leaks_a_key(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("META_API_KEY", "super-secret-key")
    asyncio.run(classify.main_async(_args(tmp_path / "o", limit=4)))
    every = (tmp_path / "o" / "report.md").read_text(encoding="utf-8")
    every += (tmp_path / "o" / "summary.json").read_text(encoding="utf-8")
    every += (tmp_path / "o" / "results.jsonl").read_text(encoding="utf-8")
    assert "super-secret-key" not in every
    assert json.loads((tmp_path / "o" / "summary.json").read_text(encoding="utf-8"))["stub"]
