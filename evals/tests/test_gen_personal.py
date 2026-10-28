"""gen_personal (household statements) against the stub Qwen: label, importer round trip, expectations, resuming."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import pytest

GOLD = Path(__file__).resolve().parents[1] / "gold"
if str(GOLD) not in sys.path:
    sys.path.insert(0, str(GOLD))

import gen_personal as gp  # noqa: E402
import spark_gen  # noqa: E402
from spark_gen import LABEL, QwenError, StubQwen  # noqa: E402

from harness.check_bank_mail import parse_bank_csv  # noqa: E402  (also puts this repo's ledger on sys.path)

LAYOUTS = ("starling", "tide", "barclays")


def _make(tmp: Path, layout: str, seed: int = 3) -> tuple[Path, dict]:
    h = gp.make_household(StubQwen(gp.stub_handlers()), tmp / "pending", seed, layout, False, False)
    out = tmp / f"{layout}_{seed}"
    gp.write_household(h, out)
    return out, h


@pytest.fixture(scope="module")
def houses(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[Path, dict]]:
    root = tmp_path_factory.mktemp("personal")
    return {layout: _make(root / layout, layout) for layout in LAYOUTS}


def test_every_generated_file_contains_the_exact_label(houses: dict) -> None:
    exact = "SAMPLE — FICTIONAL COMPANY".encode()
    assert LABEL.encode() == exact
    for out, _ in houses.values():
        files = [p for p in out.rglob("*") if p.is_file()]
        assert {p.name for p in files} >= {"statement.csv", "expectations.json", "names.json", "README.md"}
        for p in files:
            raw = p.read_bytes()
            assert exact in raw, p
            assert b"???" not in raw, p
        assert (out / "statement.csv").read_text(encoding="utf-8").splitlines()[0] == LABEL


@pytest.mark.parametrize("layout", LAYOUTS)
def test_importer_reads_every_row_and_balance(houses: dict, layout: str) -> None:
    out, h = houses[layout]
    lines = parse_bank_csv((out / "statement.csv").read_bytes(), "statement.csv")
    rows = json.loads((out / "expectations.json").read_text(encoding="utf-8"))["rows"]
    assert len(lines) == len(rows) > 300
    for ln, r in zip(lines, rows, strict=True):
        assert ln.date.isoformat() == r["date"] and ln.amount_pence == r["amount_pence"]
        if layout != "barclays":  # Barclays exports carry no balance
            assert ln.balance_pence == r["balance_pence"]
    assert lines[0].date >= gp.START and lines[-1].date <= gp.END


def test_balance_never_overdrawn_and_totals_close(houses: dict) -> None:
    exp = json.loads((houses["starling"][0] / "expectations.json").read_text(encoding="utf-8"))
    assert min(r["balance_pence"] for r in exp["rows"]) >= 15000
    assert exp["opening_balance_pence"] + sum(r["amount_pence"] for r in exp["rows"]) == exp["closing_balance_pence"]
    t = exp["totals"]
    assert t["income_pence"] - t["spending_pence"] - t["savings_transfers_pence"] == t["net_change_pence"]


def test_category_totals_recomputed_from_the_csv(houses: dict) -> None:
    out, _ = houses["tide"]
    exp = json.loads((out / "expectations.json").read_text(encoding="utf-8"))
    lines = parse_bank_csv((out / "statement.csv").read_bytes(), "statement.csv")
    total: dict[str, int] = defaultdict(int)
    by_month: dict[tuple[str, str], int] = defaultdict(int)
    for ln, r in zip(lines, exp["rows"], strict=True):  # the category of each row comes from the expectations
        total[r["category"]] += abs(ln.amount_pence)
        by_month[(r["category"], ln.date.strftime("%Y-%m"))] += abs(ln.amount_pence)
    assert set(total) == set(exp["categories"])
    for cat, c in exp["categories"].items():
        assert c["total_pence"] == total[cat], cat
        assert sum(c["by_month"].values()) == c["total_pence"]
        for month, v in c["by_month"].items():
            assert by_month[(cat, month)] == v
        assert c["type"] == {"income": "income", "savings": "transfer"}.get(cat, "spending")
    assert {"groceries", "transport", "utilities", "telecoms", "subscriptions", "rent", "income"} <= set(total)


def test_recurring_series_match_the_rows(houses: dict) -> None:
    exp = json.loads((houses["starling"][0] / "expectations.json").read_text(encoding="utf-8"))
    by_id: dict[str, list[dict]] = defaultdict(list)
    for r in exp["rows"]:
        if r["recurring_id"]:
            by_id[r["recurring_id"]].append(r)
    assert {s["id"] for s in exp["recurring"]} == set(by_id)
    for s in exp["recurring"]:
        rows = by_id[s["id"]]
        assert s["count"] == len(rows) >= 3
        assert [r["date"] for r in rows] == s["dates"] == sorted(s["dates"])
        assert [abs(r["amount_pence"]) for r in rows] == s["amounts_pence"]
        gaps = {(a - b).days for a, b in zip(map(_d, s["dates"][1:]), map(_d, s["dates"][:-1]), strict=True)}
        if s["cadence"] == "weekly":
            assert gaps == {7}
        elif s["cadence"] == "four_weekly":
            assert gaps == {28}
        else:
            assert all(24 <= g <= 38 for g in gaps), (s["id"], gaps)
        for c in s["amount_changes"]:
            assert c["old_pence"] != c["new_pence"] and c["from_date"] in s["dates"]
    ids = {s["id"]: s for s in exp["recurring"]}
    assert ids["energy"]["amount_changes"] and ids["video"]["amount_changes"] and ids["broadband"]["amount_changes"]
    assert ids["news"]["ended_early"] and ids["news"]["count"] == 3 and ids["news"]["last_date"] < "2026-07-01"
    assert ids["mealkit"]["started_late"] and ids["mealkit"]["first_date"] >= "2026-07-01"
    assert ids["music"]["reference_varies"] and ids["salary"]["direction"] == "in"
    assert ids["cleaner"]["cadence"] == "weekly" and ids["groomer"]["cadence"] == "four_weekly"


def _d(s: str):
    from datetime import date

    return date.fromisoformat(s)


def test_distractors_are_never_in_a_series_and_have_fewer_than_three_or_vary(houses: dict) -> None:
    exp = json.loads((houses["starling"][0] / "expectations.json").read_text(encoding="utf-8"))
    series_payees = {s["payee"] for s in exp["recurring"]}
    for n in exp["not_recurring"]:
        assert n["payee"] not in series_payees
    quarterly = next(n for n in exp["not_recurring"] if n["id"] == "drainage_quarterly")
    annual = next(n for n in exp["not_recurring"] if n["id"] == "travel_insurance_annual")
    assert quarterly["count"] == 2 and annual["count"] == 1
    varying = [n for n in exp["not_recurring"] if n["count"] >= 3]
    assert varying
    amounts: dict[str, set[int]] = defaultdict(set)
    for r in exp["rows"]:
        if not r["recurring_id"]:
            amounts[r["payee"]].add(abs(r["amount_pence"]))
    for n in varying:
        assert len(amounts[n["payee"]]) >= max(2, n["count"] // 2), n  # amounts vary


def test_direct_debits_fall_on_working_days(houses: dict) -> None:
    exp = json.loads((houses["starling"][0] / "expectations.json").read_text(encoding="utf-8"))
    for s in exp["recurring"]:
        if s["method"] in ("direct_debit", "standing_order", "internal_transfer"):
            for d in map(_d, s["dates"]):
                assert d.weekday() < 5 and d not in gp.BANK_HOLIDAYS, (s["id"], d)


def test_committed_total_is_the_latest_monthly_outgoings(houses: dict) -> None:
    exp = json.loads((houses["starling"][0] / "expectations.json").read_text(encoding="utf-8"))
    want = sum(
        s["amounts_pence"][-1]
        for s in exp["recurring"]
        if s["cadence"] == "monthly" and s["direction"] == "out" and s["category"] != "savings" and not s["ended_early"]
    )
    assert exp["monthly_committed_outgoings_pence"] == want > 100000


def test_only_fictional_names_and_each_household_differs(tmp_path: Path) -> None:
    a = gp.make_household(StubQwen(gp.stub_handlers()), tmp_path / "a", 3, "starling", False, False)
    b = gp.make_household(StubQwen(gp.stub_handlers()), tmp_path / "b", 4, "starling", False, False)
    assert a["exp"]["household"] != b["exp"]["household"]
    assert [r["amount_pence"] for r in a["exp"]["rows"]] != [r["amount_pence"] for r in b["exp"]["rows"]]
    for p in a["names"]["payees"].values():
        assert not spark_gen.is_real(p["name"])


def test_invalid_qwen_replies_are_rejected_not_repaired() -> None:
    slots = ["employer", "client"]
    ok = {"payees": [{"slot": "employer", "name": "Larkfield Works", "reference": "EMP-4411"},
                     {"slot": "client", "name": "Brindle Studio", "reference": "CL-9021"}]}  # fmt: skip
    assert gp.check_payees(slots)(ok) is None
    assert gp.check_payees(slots)({"payees": ok["payees"][:1]})
    real = {"payees": [{**ok["payees"][0], "name": "Tesco Stores"}, ok["payees"][1]]}
    assert gp.check_payees(slots)(real)
    same = {"payees": [ok["payees"][0], {**ok["payees"][1], "name": "larkfield works"}]}
    assert gp.check_payees(slots)(same)
    short = {"payees": [{**ok["payees"][0], "reference": "x"}, ok["payees"][1]]}
    assert gp.check_payees(slots)(short)
    assert gp.check_household({"surname": "Ashdown", "nickname": "ashdown"}) is None
    assert gp.check_household({"surname": "Ashdown", "nickname": "ash down 2"})


def test_resume_reuses_saved_names_and_skips_written_households(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(spark_gen.time, "sleep", lambda _s: None)
    handlers = gp.stub_handlers()
    real = handlers["payees"]
    calls = {"n": 0}

    def flaky(h: dict) -> dict:
        calls["n"] += 1
        if "council" in h["slots"] or calls["n"] > 3 and "bus" in h["slots"]:
            raise QwenError("vLLM went away")
        return real(h)

    path = tmp_path / "names.json"
    with pytest.raises(QwenError):
        gp.build_names(StubQwen({**handlers, "payees": flaky}), path, 3, False)
    handlers2 = gp.stub_handlers()
    first = StubQwen(handlers2)
    gp.build_names(first, path, 3, False)
    assert first.calls == 6  # the household was saved before the failure; all six batches are asked
    again = StubQwen(handlers2)
    gp.build_names(again, path, 3, False)
    assert again.calls == 0


def test_main_stub_run_then_rerun_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    argv = ["gen_personal.py", "--stub", "--out", str(tmp_path / "o"), "--households", "1", "--layout", "tide"]
    monkeypatch.setattr(sys, "argv", argv)
    gp.main()
    made = sorted((tmp_path / "o").glob("*/statement.csv"))
    assert len(made) == 1 and not list((tmp_path / "o").glob("_pending_*"))
    gp.main()
    assert "already written, skipped" in capsys.readouterr().out


def test_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(
        sys, "argv", ["gen_personal.py", "--dry-run", "--out", str(tmp_path / "o"), "--households", "1"]
    )
    gp.main()
    assert not (tmp_path / "o").exists()
    assert "dry run: nothing written" in capsys.readouterr().out
