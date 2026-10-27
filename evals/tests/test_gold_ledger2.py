"""Data integrity of the ledger2 gold set (credit notes, part-paid invoices, overlapping bank pairs). No model calls."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

L2 = Path(__file__).resolve().parents[1] / "gold" / "ledger2"
LABEL = "SAMPLE — FICTIONAL COMPANY"
CREDIT_NOTES = sorted((L2 / "credit_notes").glob("*.json"))
PART_PAID = sorted((L2 / "part_paid").glob("*.json"))
METAS = sorted((L2 / "bank_pairs").glob("*_meta.json"))


def _p(x: float) -> int:
    return round(x * 100)


def _vat_pence(net: float, rate: int) -> int:
    # round half away from zero on pence, as the generator's own check does (tolerance 1p)
    return round(_p(net) * rate / 100)


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def test_counts() -> None:
    assert (len(CREDIT_NOTES), len(PART_PAID), len(METAS)) == (40, 40, 10)


@pytest.mark.parametrize("path", CREDIT_NOTES, ids=lambda p: p.stem)
def test_credit_note_is_negative_and_adds_up(path: Path) -> None:
    d = _load(path)
    assert d["label"] == LABEL and d["doc_type"] == "credit_note"
    assert d["original_invoice_number"] and d["credit_note_number"]
    assert d["lines"], "a credit note has lines"
    for ln in d["lines"]:
        assert ln["net"] < 0 and ln["vat"] <= 0
        assert ln["vat_rate"] in (0, 5, 20)
        assert abs(_p(ln["vat"]) - _vat_pence(ln["net"], ln["vat_rate"])) <= 1, ln
    net = sum(_p(ln["net"]) for ln in d["lines"])
    vat = sum(_p(ln["vat"]) for ln in d["lines"])
    assert (_p(d["net_total"]), _p(d["vat_total"])) == (net, vat)
    assert _p(d["gross_total"]) == net + vat < 0


@pytest.mark.parametrize("path", PART_PAID, ids=lambda p: p.stem)
def test_part_paid_expected_matches_payments(path: Path) -> None:
    d = _load(path)
    assert d["label"] == LABEL and d["doc_type"] == "sales_invoice"
    for ln in d["lines"]:
        assert ln["net"] > 0 and abs(_p(ln["vat"]) - _vat_pence(ln["net"], ln["vat_rate"])) <= 1
    net = sum(_p(ln["net"]) for ln in d["lines"])
    vat = sum(_p(ln["vat"]) for ln in d["lines"])
    gross = _p(d["gross_total"])
    assert (_p(d["net_total"]), _p(d["vat_total"]), gross) == (net, vat, net + vat)
    paid = sum(_p(p["amount"]) for p in d["payments"])
    e = d["expected"]
    assert _p(e["paid"]) == paid and _p(e["outstanding"]) == gross - paid
    want = "overpaid" if paid > gross else "paid" if paid == gross else "part_paid" if paid else "open"
    assert e["status"] == want
    case = d["gold_case"]
    assert case in ("part", "part_open", "over", "exact")
    assert {"part": "paid", "part_open": "part_paid", "over": "overpaid", "exact": "paid"}[case] == want
    assert all(p["date"] >= d["date"] for p in d["payments"])
    assert (len(d["payments"]) > 1) == (case == "part")


def _rows(p: Path) -> list[dict]:
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("meta_path", METAS, ids=lambda p: p.name[:3])
def test_bank_pair_overlaps_and_balances_run(meta_path: Path) -> None:
    meta = _load(meta_path)
    assert meta["label"] == LABEL
    a, b = _rows(L2 / "bank_pairs" / meta["first"]), _rows(L2 / "bank_pairs" / meta["second"])
    n = meta["overlap"]
    assert (len(a), len(b)) == (meta["lines_a"], meta["lines_b"]) and n > 0
    assert b[:n] == a[-n:]
    assert len(a) + len(b) - n == meta["expected_unique_lines"]
    for rows in (a, b):
        for prev, cur in zip(rows, rows[1:], strict=False):
            assert _p(float(cur["Balance"])) == _p(float(prev["Balance"])) + _p(float(cur["Amount"])), cur
        assert [r["Date"] for r in rows] == sorted(r["Date"] for r in rows)
    assert _p(float(b[-1]["Balance"])) == _p(meta["closing_balance"])


def test_bank_csvs_carry_no_label_line_but_meta_does() -> None:
    for c in (L2 / "bank_pairs").glob("*.csv"):
        assert c.read_text(encoding="utf-8").splitlines()[0] == "Date,Description,Amount,Balance"
    assert all(_load(m)["label"] == LABEL for m in METAS)
