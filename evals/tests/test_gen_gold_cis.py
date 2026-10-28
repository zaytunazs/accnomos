"""gen_gold_cis (CIS statements and reverse-charge invoices) against the stub Qwen: the exact label, figures that
the runtime's own CIS code agrees with, the distractors flagged, re-asking bad names, resuming, the Qwen defaults."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

GOLD = Path(__file__).resolve().parents[1] / "gold"
if str(GOLD) not in sys.path:
    sys.path.insert(0, str(GOLD))

import gen_gold_cis as gc  # noqa: E402
from spark_gen import LABEL, Qwen, QwenError, StubQwen  # noqa: E402

from app import cis  # noqa: E402  (the runtime, installed in the workspace venv)
from app import cis_readings as cr  # noqa: E402
from app.ai.cis_read import CisReading  # noqa: E402


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[dict]]:
    out = tmp_path_factory.mktemp("cis")
    docs = gc.build(StubQwen(gc.stub_handlers()), 27, 30, 11, out, log=lambda _m: None)
    gc.write_all(docs, out, 11, "stub")
    return out, docs


def test_every_file_carries_the_exact_label(made: tuple[Path, list[dict]]) -> None:
    out, docs = made
    exact = "SAMPLE — FICTIONAL COMPANY".encode()
    assert LABEL.encode() == exact and "—" in LABEL
    files = [p for p in out.rglob("*") if p.is_file()]
    assert len(files) == 2 * len(docs) + 3  # document + expected per doc, manifest, README, names
    for p in files:
        raw = p.read_bytes()
        assert exact in raw, p
        assert b"???" not in raw, p
    for d in docs:
        assert (out / d["id"] / "document.txt").read_text(encoding="utf-8").splitlines()[0] == LABEL


def test_statement_figures_agree_with_the_runtime(made: tuple[Path, list[dict]]) -> None:
    _, docs = made
    statements = [d for d in docs if d["kind"] == "cis_statement"]
    assert {d["rate"] for d in statements} == {0, 20, 30}
    assert any(d["expect_check_fail"] for d in statements)
    for d in statements:
        p = d["pence"]
        assert p["correct_deduction"] == cis.deduction(p["gross"] - p["materials"], d["rate"])
        assert gc.deduction(p["gross"] - p["materials"], d["rate"]) == p["correct_deduction"]
        settings = cis.CisSettings(subcontractor=True, status=d["status"], utr=d["expected"]["subcontractor_utr"])
        reading, problems = cr.from_reading(CisReading(**d["expected"], confidence=1), "x", settings)
        assert not problems and reading.statement is not None
        st = reading.statement
        assert (st.gross_pence, st.materials_pence, st.deduction_pence) == (p["gross"], p["materials"], p["deduction"])
        assert st.tax_month_end.day == 5
        failed = sorted(c.code for c in reading.checks if not c.ok)
        assert failed == d["expect_check_fail"], (d["id"], reading.checks)
        if d["rate"] == 30:
            assert d["expected"]["verification_number"] and "Verification number" in d["text"]


def test_invoice_figures_agree_with_the_runtime(made: tuple[Path, list[dict]]) -> None:
    _, docs = made
    invoices = [d for d in docs if d["kind"] == "reverse_charge_invoice"]
    assert {d["rate"] for d in invoices} == {5, 20}
    for d in invoices:
        p = d["pence"]
        assert p["net"] == p["labour"] + p["materials"]
        reading, problems = cr.from_reading(CisReading(**d["expected"], confidence=1), "x", cis.CisSettings())
        assert not problems and reading.bill is not None
        assert reading.bill.net_pence == p["net"]
        assert reading.bill.reverse_charge_vat_pence == p["reverse_charge_vat"]
        failed = sorted(c.code for c in reading.checks if not c.ok)
        assert failed == d["expect_check_fail"], (d["id"], reading.checks)
        if d["expect_check_fail"]:
            assert "Section 55A" not in d["text"]
        else:
            assert gc.REVERSE_CHARGE_WORDING in d["text"] and f"£{gc.m(p['reverse_charge_vat'])}" in d["text"]
        assert f"£{gc.m(p['net'])}" in d["text"]


def test_printed_figures_match_the_expected_reading(made: tuple[Path, list[dict]]) -> None:
    out, docs = made
    for d in docs:
        text = (out / d["id"] / "document.txt").read_text(encoding="utf-8")
        exp = json.loads((out / d["id"] / "expected.json").read_text(encoding="utf-8"))["expected"]
        for key in ("gross_amount", "materials", "deduction", "net"):
            if exp.get(key) is not None:
                assert f"£{exp[key]:,.2f}" in text, (d["id"], key)


def test_real_names_are_re_asked_never_kept() -> None:
    replies = iter(
        [
            {
                "contractors": [{"name": "Screwfix Direct Ltd", "address": "1 Road, Leeds LS1", "site": "A site"}] * 3,
                "subcontractors": [],
            },
            gc.stub_handlers()["names"]({"contractors": 3, "subcontractors": 4}),
        ]
    )
    client = StubQwen({"names": lambda _h: next(replies)})
    got = gc.get_names(client, None, 3, 4, log=lambda _m: None)
    assert client.calls == 2 and not any("Screwfix" in c["name"] for c in got["contractors"])
    assert gc.check_names({"contractors": [], "subcontractors": []}, 1, 1) == "too few names"


def test_names_are_resumed(tmp_path: Path) -> None:
    gc.build(StubQwen(gc.stub_handlers()), 5, 5, 1, tmp_path, log=lambda _m: None)
    assert (tmp_path / "names.json").exists()
    never = StubQwen({})  # any call would raise
    docs = gc.build(never, 5, 5, 1, tmp_path, log=lambda _m: None)
    assert never.calls == 0 and len(docs) == 10


def test_defaults_point_at_the_spark_and_dry_run_writes_nothing(tmp_path: Path, capsys) -> None:
    q = Qwen()
    assert q.url == "http://127.0.0.1:8000/v1/chat/completions" and q.model == "qwen3.8-27b"
    assert gc.main(["--dry-run", "--statements", "3", "--invoices", "3", "--out", str(tmp_path)]) == 0
    assert list(tmp_path.iterdir()) == [] and "nothing written" in capsys.readouterr().out
    assert gc.main(["--stub", "--statements", "2", "--invoices", "2", "--out", str(tmp_path / "o")]) == 0
    assert (tmp_path / "o" / "manifest.json").exists()


def test_qwen_unreachable_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    q = Qwen(url="http://127.0.0.1:9/v1/chat/completions", timeout=1)
    with pytest.raises(QwenError):
        q.ask("hi")
