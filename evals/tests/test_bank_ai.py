"""bank_ai harness: expectations, failure classification, a full stub run and resuming. No model, no network."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import pytest

from harness import bank_ai


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


def test_cases_cover_every_gold_bank_source() -> None:
    cases = bank_ai.load_cases()
    groups = {c.group for c in cases}
    assert groups == {"hand-written", "two-month", "ledger2"}
    assert len({c.id for c in cases}) == len(cases)
    assert 400 < len(cases) < 600
    assert 0.4 < sum(c.scored for c in cases) / len(cases) < 0.9


def test_expected_accounts_are_on_the_runtime_list() -> None:
    for c in bank_ai.load_cases():
        assert set(c.accounts) <= set(bank_ai.ACCOUNTS), c


def test_known_expectations() -> None:
    by_desc = {c.line.description: c for c in bank_ai.load_cases() if c.group == "hand-written"}
    assert by_desc["SCREWFIX DIRECT ON 30 SEP CLP"].accounts[0] == "5100 Tools & small equipment"
    assert by_desc["BUSINESS ACCOUNT FEE"].accounts == ["7900 Bank charges"]
    assert not by_desc["ACME KITCHENS LTD INV-0042 BGC"].scored  # money in
    assert not by_desc["TO SAVINGS 40-11-22 87654321 TFR"].scored  # a transfer


def test_money_in_and_tax_are_never_scored() -> None:
    for c in bank_ai.load_cases():
        if c.line.amount_pence >= 0:
            assert not c.scored, c.line.description
        if "HMRC" in c.line.description.upper():
            assert not c.scored


def test_gold_document_rows_use_the_document_category() -> None:
    docs = [c for c in bank_ai.load_cases() if c.origin == "gold_doc" and c.scored]
    assert len(docs) > 40
    assert {a for c in docs for a in c.accounts} <= set(bank_ai.ACCOUNTS)


@pytest.mark.parametrize(
    ("raw", "error", "want"),
    [
        (None, "ConnectError: refused", "transport_error"),
        ("", None, "empty_reply"),
        ("here you go: not json", None, "invalid_json"),
        ('{"account": 5}', None, "invalid_shape"),
        ('{"account": "9999 Nope", "vat_code": "N", "reason": "x"}', None, "invalid_account"),
        ('{"account": "7999 Sundry expenses", "vat_code": "Q", "reason": "x"}', None, "invalid_vat_code"),
    ],
)
def test_classify_failure(raw: str | None, error: str | None, want: str) -> None:
    assert bank_ai.classify_failure(raw, error) == want


def test_dry_run_calls_nothing_and_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "o"
    assert asyncio.run(bank_ai.main_async(_args(out, dry_run=True, show=3))) is None
    assert not out.exists()
    assert "lines (" in capsys.readouterr().out


def test_stub_run_writes_report_and_resumes(tmp_path: Path) -> None:
    from app.ai import ask as ask_mod

    original = ask_mod.call_json_model
    out = tmp_path / "o"
    s = asyncio.run(bank_ai.main_async(_args(out, limit=60)))
    assert ask_mod.call_json_model is original  # the wrapper is always taken off again
    assert s is not None and s["stub"] and s["lines"] == 60
    assert (out / "report.md").read_text(encoding="utf-8").startswith("# Bank-rule AI coding eval")
    first = (out / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(first) == 60
    # a kill part-way: keep 25 lines (and a torn one), the next run asks only the rest
    (out / "results.jsonl").write_text("\n".join(first[:25]) + "\n" + first[25][:20], encoding="utf-8")
    s2 = asyncio.run(bank_ai.main_async(_args(out, limit=60)))
    assert s2 is not None and s2["lines"] == 60
    rows = bank_ai.read_results(out / "results.jsonl")  # the torn line is skipped
    assert len({r["id"] for r in rows}) == 60


def test_stub_faults_are_counted_not_crashed(tmp_path: Path) -> None:
    s = asyncio.run(bank_ai.main_async(_args(tmp_path / "o")))
    assert s is not None
    assert s["invalid_json"] > 0 and s["invalid_account"] > 0 and s["invalid_vat_code"] > 0
    assert s["refusals"] == s["invalid_json"] + s["invalid_account"] + s["invalid_vat_code"] + s["transport_errors"]
    assert 0 < s["accuracy_pct"] <= 100
