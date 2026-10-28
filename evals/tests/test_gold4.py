"""gen_gold4 (price-history gold) against the stub Qwen: integrity, the by-construction expectations, resuming."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

GOLD = Path(__file__).resolve().parents[1] / "gold"
if str(GOLD) not in sys.path:
    sys.path.insert(0, str(GOLD))

import gen_gold4 as g4  # noqa: E402
import spark_gen  # noqa: E402
from spark_gen import LABEL, QwenError, StubQwen  # noqa: E402

EM_DASH = "—"


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("g4")
    cat, files, exp = g4.generate(StubQwen(g4.stub_handlers()), out, 120, g4.SEED, False, False)
    assert g4.write_all(cat, files, exp, out, False) == 120
    return out


def _receipts(out: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((out / "receipts").glob("*.json"))]


def test_label_is_the_real_em_dash() -> None:
    assert f"SAMPLE {EM_DASH} FICTIONAL COMPANY" == LABEL and EM_DASH == "\u2014"
    for path in sorted(GOLD.glob("gen_*.py")) + [GOLD / "spark_gen.py"]:
        src = path.read_bytes()
        assert b"SAMPLE ?" not in src, path  # the accident: the dash replaced by question marks
        if path.name in ("gen_gold4.py", "gen_personal.py", "spark_gen.py"):
            assert "SAMPLE \u2014 FICTIONAL COMPANY".encode() in src, path


def test_every_generated_file_contains_the_exact_label(built: Path) -> None:
    exact = f"SAMPLE {EM_DASH} FICTIONAL COMPANY".encode()
    files = [p for p in built.rglob("*") if p.is_file()]
    assert len(files) >= 120 + 4
    for p in files:
        raw = p.read_bytes()
        assert exact in raw, p
        assert b"???" not in raw and b"SAMPLE -" not in raw, p
    for g in _receipts(built):
        assert g["label"] == LABEL and g["printed_text"].rstrip().endswith(LABEL)


def test_label_guard_refuses_a_mangled_label(tmp_path: Path) -> None:
    with pytest.raises(spark_gen.LabelError):
        spark_gen.write_text(tmp_path / "x.txt", "SAMPLE ??? FICTIONAL COMPANY")
    with pytest.raises(spark_gen.LabelError):
        spark_gen.write_json(tmp_path / "x.json", {"label": "SAMPLE - FICTIONAL COMPANY"})
    spark_gen.write_json(tmp_path / "ok.json", {"label": LABEL})
    assert LABEL in (tmp_path / "ok.json").read_text(encoding="utf-8")


def test_schema_matches_existing_receipt_gold(built: Path) -> None:
    existing = json.loads((GOLD / "receipts" / "071_utility.json").read_text(encoding="utf-8"))
    for g in _receipts(built):
        assert set(existing) - {"damage"} <= set(g)
        assert set(existing["lines"][0]) <= set(g["lines"][0])
        assert g["side"] == "purchase" and g["currency"] == "GBP" and g["customer"]["name"] == spark_gen.BIZ


def test_arithmetic_in_pence_and_vat_rules(built: Path) -> None:
    cat = json.loads((built / "catalogue.json").read_text(encoding="utf-8"))
    for g in _receipts(built):
        assert sum(x["net_pence"] for x in g["lines"]) == g["net_pence"]
        assert sum(x["vat_pence"] for x in g["lines"]) == g["vat_pence"]
        assert g["net_pence"] + g["vat_pence"] == g["gross_pence"]
        assert round(g["gross_total"] * 100) == g["gross_pence"]
        style = cat["suppliers"][g["supplier_index"]]["style"]
        for x in g["lines"]:
            assert x["qty"] >= 1 and x["net_pence"] > 0
            if style == "cash":
                assert x["vat_pence"] == 0 and x["vat_rate"] == 0 and not g["supplier"]["vat_number"]
            elif style == "invoice":
                assert x["vat_pence"] == spark_gen.vat_pence(x["net_pence"])
            else:  # till: the printed shelf price includes VAT, so gross = qty x (net price x 1.2)
                assert (
                    abs(x["net_pence"] + x["vat_pence"] - x["qty"] * ((x["net_pence"] // x["qty"]) * 1.2))
                    < x["qty"] * 2
                )
        if style != "cash":
            assert re.fullmatch(r"GB \d{3} \d{4} \d{2}", g["supplier"]["vat_number"])
            assert spark_gen.vat_ok(g["supplier"]["vat_number"])
        status = "needs_a_look" if (g["vat_pence"] and not g["supplier"]["vat_number"]) else None
        assert status is None or g["expected_status"] == status


def test_receipts_use_the_price_table(built: Path) -> None:
    """Independent of the expectations: every invoice-style line is qty x the table's price for that month."""
    cat = json.loads((built / "catalogue.json").read_text(encoding="utf-8"))
    for g in _receipts(built):
        si = g["supplier_index"]
        mo = g4.month_index(__import__("datetime").date.fromisoformat(g["date"]))
        for x in g["lines"]:
            pack_net = cat["prices"][x["item_key"]][str(si)][f"{x['pack_units']:g}"][mo]
            if cat["suppliers"][si]["style"] != "till":
                assert x["net_pence"] == x["qty"] * pack_net
            assert abs(x["unit_net_pence"] - x["net_pence"] / x["qty"] / x["pack_units"]) < 1e-3


def test_history_depth_and_stockists(built: Path) -> None:
    exp = json.loads((built / "expectations.json").read_text(encoding="utf-8"))
    assert len(_receipts(built)) == 120
    assert len(exp["items"]) == len(g4.ARCHETYPES) == 18
    for key, it in exp["items"].items():
        assert 3 <= len(it["suppliers"]) <= 4, key
        for s, v in it["suppliers"].items():
            months = {r["date"][:7] for r in v["observations"]}
            assert v["n"] >= 3 and len(months) >= 2, (key, s)
    dates = [g["date"] for g in _receipts(built)]
    assert min(dates) >= "2026-04-01" and max(dates) <= "2026-09-30" and dates == sorted(dates)
    assert {d[:7] for d in dates} == {f"2026-{m:02d}" for m in range(4, 10)}


def test_expectations_recomputed_from_the_receipts(built: Path) -> None:
    exp = json.loads((built / "expectations.json").read_text(encoding="utf-8"))
    seen: dict[tuple[str, str], list[tuple[str, str, float]]] = {}
    for p in sorted((built / "receipts").glob("*.json")):
        g = json.loads(p.read_text(encoding="utf-8"))
        for x in g["lines"]:
            per_unit = x["net_pence"] / x["qty"] / x["pack_units"]
            seen.setdefault((x["item_key"], g["supplier"]["name"]), []).append((g["date"], p.name, per_unit))
    cheapest_suppliers = set()
    for key, it in exp["items"].items():
        latest, mean = {}, {}
        for s, v in it["suppliers"].items():
            rows = sorted(seen[(key, s)])
            latest[s] = rows[-1][2]
            mean[s] = sum(r[2] for r in rows) / len(rows)
            assert v["latest_unit_net_pence"] == pytest.approx(latest[s], abs=1e-3)
            assert v["mean_unit_net_pence"] == pytest.approx(mean[s], abs=1e-3)
        ranked = sorted(latest.values())
        assert it["cheapest_latest"] == min(latest, key=latest.get)
        assert it["cheapest_mean"] == min(mean, key=mean.get)
        assert ranked[1] > ranked[0] * (1 + g4.TIE), f"{key} latest is a near tie"
        ranked_m = sorted(mean.values())
        assert ranked_m[1] > ranked_m[0] * (1 + g4.TIE), f"{key} mean is a near tie"
        cheapest_suppliers.add(it["cheapest_latest"])
    assert len(cheapest_suppliers) >= 3  # no supplier is simply the cheapest at everything


def test_cheaper_elsewhere_hints_use_only_what_was_known_at_the_time(built: Path) -> None:
    exp = json.loads((built / "expectations.json").read_text(encoding="utf-8"))
    by_line = {(h["file"], h["line"]): h for h in exp["line_hints"]}
    assert len(by_line) == sum(len(g["lines"]) for g in _receipts(built))
    first_seen: dict[str, str] = {}
    for h in sorted(exp["line_hints"], key=lambda h: (h["file"], h["line"])):
        first_seen.setdefault(h["item"], h["supplier"])
    # the first purchase of a product can never have a cheaper-elsewhere hint
    firsts = {}
    for h in sorted(exp["line_hints"], key=lambda h: (h["file"], h["line"])):
        firsts.setdefault(h["item"], h)
    assert all(not h["cheaper_elsewhere"] for h in firsts.values())
    assert any(h["cheaper_elsewhere"] for h in exp["line_hints"])
    for h in exp["line_hints"]:
        if h["cheaper_elsewhere"]:
            assert h["cheapest_known_elsewhere"] == h["cheaper_elsewhere"][0] and h["saving_pct"] > 0
            assert h["supplier"] not in h["cheaper_elsewhere"]


def test_resume_makes_no_qwen_calls_and_keeps_receipts(built: Path) -> None:
    before = {p: p.stat().st_mtime_ns for p in (built / "receipts").glob("*.json")}
    client = StubQwen(g4.stub_handlers())
    cat, files, exp = g4.generate(client, built, 120, g4.SEED, False, False)
    assert client.calls == 0
    assert g4.write_all(cat, files, exp, built, False) == 0
    assert before == {p: p.stat().st_mtime_ns for p in (built / "receipts").glob("*.json")}


def test_a_failed_qwen_step_keeps_progress_and_resumes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spark_gen.time, "sleep", lambda _s: None)
    handlers = g4.stub_handlers()
    real = handlers["listings"]

    def flaky(h: dict) -> dict:
        if h["supplier"] == 3:
            raise QwenError("vLLM went away")
        return real(h)

    with pytest.raises(QwenError):
        g4.generate(StubQwen({**handlers, "listings": flaky}), tmp_path, 120, g4.SEED, False, False)
    saved = json.loads((tmp_path / "catalogue.json").read_text(encoding="utf-8"))
    assert set(saved["listings"]) == {"0", "1", "2"} and len(saved["products"]) == 18
    client = StubQwen(handlers)
    g4.generate(client, tmp_path, 120, g4.SEED, False, False)
    assert client.calls == 2  # only the two suppliers still missing


def test_invalid_qwen_replies_are_rejected_not_repaired() -> None:
    sup = {
        "name": "Corbel Supply",
        "street": "1 A St",
        "town": "Derby",
        "postcode": "DE1 3CC",
        "phone": "01332 555 010",
    }
    good = {"suppliers": [{**sup, "name": f"Fenmoor Supply {i}"} for i in range(5)]}
    assert g4.check_suppliers(good) is None
    assert g4.check_suppliers({"suppliers": good["suppliers"][:4]})
    real = {"suppliers": [{**sup, "name": "Screwfix Direct"}, *good["suppliers"][1:]]}
    assert g4.check_suppliers(real)
    assert g4.check_suppliers({"suppliers": [{**sup, "postcode": "NOTAPOSTCODE"}, *good["suppliers"][1:]]})
    keys = ["tape_masking_38"]
    ok = {"products": [{"key": keys[0], "name": "Larchwell Masking Tape 38mm", "alt_name": "Masking 38mm"}]}
    assert g4.check_products(keys)(ok) is None
    bad = {"products": [{"key": keys[0], "name": "Larchwell Masking Tape", "alt_name": "Masking 38mm"}]}
    assert g4.check_products(keys)(bad)
    brand = {"products": [{"key": keys[0], "name": "Scotch Masking Tape 38mm", "alt_name": "Masking 38mm"}]}
    assert g4.check_products(keys)(brand)


def test_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(sys, "argv", ["gen_gold4.py", "--dry-run", "--out", str(tmp_path / "o"), "120"])
    g4.main()
    assert not (tmp_path / "o").exists()
    assert "dry run: nothing written" in capsys.readouterr().out


def test_gold4_works_with_the_extraction_harness(built: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A perfect reading of every ledger4 receipt scores all-true in run_extraction.score, and --gold-dir is wired."""
    import argparse
    import asyncio

    from harness import run_extraction as rx

    monkeypatch.setenv("VERIFIER", "off")  # main_async sets it; the monkeypatch restores the environment

    for g in _receipts(built):
        proposal = {
            "extracted": {
                "supplier_name": g["supplier"]["name"],
                "supplier_vat_number": g["supplier"]["vat_number"],
                "date": g["date"],
                "net_total": g["net_total"],
                "vat_total": g["vat_total"],
                "gross_total": g["gross_total"],
                "lines": g["lines"],
                "doc_type": "receipt" if g["doc_type"] == "receipt" else "purchase_invoice",
            },
            "status": rx.expected_status(g),
        }
        assert all(rx.score(g, proposal).values()), g["invoice_number"]
    empty = tmp_path / "empty"
    empty.mkdir()
    args = argparse.Namespace(
        mode="local", model=None, verify=False, out=str(tmp_path / "o"), gold_dir=str(empty), case=None,
        limit=0, concurrency=1, messy=False, business_name=None,
    )  # fmt: skip
    with pytest.raises(SystemExit, match="no gold"):
        asyncio.run(rx.main_async(args))
