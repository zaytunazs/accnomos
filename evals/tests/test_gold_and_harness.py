"""Offline checks on the gold set, bank/mail fixtures and the harness scoring/rendering rules. No model calls."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest
from PIL import Image

from harness.check_bank_mail import parse_bank_csv  # also puts this repo's ledger first on sys.path
from harness.render import render_receipt
from harness.run_extraction import FIELDS, GOLD_DIR, expected_status, gold_side, score

GOLD = GOLD_DIR.parent
LABEL = "SAMPLE — FICTIONAL COMPANY"
BRAMBLEWOOD_VRN = "GB 123 4567 89"  # kept from the first set; documented as not checksum-valid
NEW = [p for p in sorted(GOLD_DIR.glob("*.json")) if int(p.name[:3]) >= 61]


def _vrn_ok(v: str) -> bool:
    d = re.sub(r"\D", "", v)
    w = sum(int(c) * k for c, k in zip(d[:7], range(8, 1, -1), strict=False)) + int(d[7:])
    return len(d) == 9 and (w % 97 == 0 or (w + 55) % 97 == 0)


def test_manifest_lists_every_document() -> None:
    m = json.loads((GOLD / "manifest.json").read_text(encoding="utf-8"))
    files = sorted(p.name for p in GOLD_DIR.glob("*.json"))
    assert m["count"] == len(m["items"]) == len(files) == 200
    assert sorted(i["file"] for i in m["items"]) == files


@pytest.mark.parametrize("path", NEW, ids=lambda p: p.stem)
def test_new_gold_is_labelled_and_adds_up_in_pence(path: Path) -> None:
    g = json.loads(path.read_text(encoding="utf-8"))
    assert g["label"] == LABEL and LABEL in g["printed_text"]
    assert g["net_pence"] + g["vat_pence"] == g["gross_pence"]
    assert (round(g["net_total"] * 100), round(g["vat_total"] * 100), round(g["gross_total"] * 100)) == (
        g["net_pence"],
        g["vat_pence"],
        g["gross_pence"],
    )
    assert abs(sum(round(ln["net"] * 100) for ln in g["lines"]) - g["net_pence"]) <= 1
    assert g["side"] in ("purchase", "sale") and g["expected_status"] in ("proposed", "needs_a_look")
    assert (g["side"] == "sale") == g["supplier"]["name"].startswith("Bramblewood")
    vrn = g["supplier"].get("vat_number")
    if vrn and vrn.startswith("GB") and vrn != BRAMBLEWOOD_VRN:
        assert _vrn_ok(vrn), vrn


def test_gold_side_uses_explicit_side_else_supplier() -> None:
    assert gold_side({"side": "sale", "supplier": {"name": "Anyone"}}) == "sale"
    assert gold_side({"supplier": {"name": "Bramblewood Joinery Ltd"}}) == "sale"
    # 001-060: a mislabelled doc_type must not decide the side
    assert gold_side({"doc_type": "sales_invoice", "supplier": {"name": "Oakfield Timber"}}) == "purchase"


def test_expected_status_explicit_overrides_rules() -> None:
    assert expected_status({"expected_status": "proposed", "currency": "EUR"}) == "proposed"
    assert expected_status({"currency": "EUR"}) == "needs_a_look"
    assert expected_status({"gold_case": "no_vat_number"}) == "needs_a_look"
    assert expected_status({}) == "proposed"


def test_score_side_and_status() -> None:
    gold = json.loads(next(p for p in NEW if "_sales" in p.name).read_text(encoding="utf-8"))
    ex = {
        "supplier_name": gold["supplier"]["name"],
        "supplier_vat_number": gold["supplier"]["vat_number"],
        "date": gold["date"],
        "net_total": gold["net_total"],
        "vat_total": gold["vat_total"],
        "gross_total": gold["gross_total"] + 0.01,
        "lines": gold["lines"],
        "doc_type": "sales_invoice",
    }
    s = score(gold, {"extracted": ex, "status": gold["expected_status"]})
    assert tuple(s) == FIELDS and all(s.values())  # 1p tolerance on money
    s = score(gold, {"extracted": ex | {"doc_type": "purchase_invoice"}, "status": "needs_a_look"})
    assert not s["side"] and s["status"] == (gold["expected_status"] == "needs_a_look")


@pytest.mark.parametrize("damage", [None, "faded", "torn"])
@pytest.mark.parametrize("messy", [False, True])
def test_render_damage_modes_are_rgb_and_deterministic(damage: str | None, messy: bool) -> None:
    text = "CAFE\n~Tea 2.50\n~TOTAL 2.50\n" + LABEL
    png = render_receipt(text, messy=messy, seed=3, damage=damage)
    assert png == render_receipt(text, messy=messy, seed=3, damage=damage)
    img = Image.open(io.BytesIO(png))
    assert img.mode == "RGB" and img.width >= 600


def test_handwriting_marker_only_affects_marked_lines() -> None:
    assert render_receipt("~A\nB", seed=1) != render_receipt("A\nB", seed=1)
    assert not any(
        ln.startswith("~")
        for p in sorted(GOLD_DIR.glob("0[0-5]*.json"))
        for ln in json.loads(p.read_text(encoding="utf-8"))["printed_text"].splitlines()
    )


def test_bank_csvs_parse_and_match_truth() -> None:
    truth = json.loads((GOLD / "bank" / "expected_matches.json").read_text(encoding="utf-8"))
    # The bank-ui gold set (barclays.csv …, truth in expected.json) shares this folder; only the six two-month exports are ours.
    csvs = sorted(p for p in (GOLD / "bank").glob("*.csv") if p.name in {r["file"] for r in truth["rows"]})
    assert len(csvs) == 6
    for p in csvs:
        rows = [r for r in truth["rows"] if r["file"] == p.name]
        lines = parse_bank_csv(p.read_bytes(), p.name)
        assert [(ln.date.isoformat(), ln.amount_pence) for ln in lines] == [
            (r["date"], r["amount_pence"]) for r in rows
        ], p.name


def test_mail_fixtures_reference_real_files() -> None:
    mails = sorted((GOLD / "mail").glob("M*.json"))
    assert len(mails) == 20
    for p in mails:
        m = json.loads(p.read_text(encoding="utf-8"))
        for a in m["attachments"]:
            f = GOLD / "mail" / a["path"]
            assert f.stat().st_size == a["size"] and a["size"] < 2 * 1024 * 1024, (p.name, a["name"])
            if f.suffix == ".png":
                assert a["size"] <= 300 * 1024, (p.name, a["name"])
            if a["gold"]:
                assert (GOLD_DIR / a["gold"]).exists()
        assert {e["attachment"] for e in m["expected"]["intake"]} == {a["name"] for a in m["attachments"]}, p.name
