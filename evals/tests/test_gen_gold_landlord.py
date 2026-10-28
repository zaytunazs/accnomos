"""gen_gold_landlord (letting statements and property bills) against the stub Qwen: the label, figures fixed by
code, the 50:50 split, and the same answers from the runtime's own property code (app/property.py)."""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

GOLD = Path(__file__).resolve().parents[1] / "gold"
if str(GOLD) not in sys.path:
    sys.path.insert(0, str(GOLD))

import gen_gold_landlord as gl  # noqa: E402
from spark_gen import LABEL, QwenError, StubQwen  # noqa: E402


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict, dict]:
    out = tmp_path_factory.mktemp("landlord") / "landlord_7"
    names, world = gl.make_landlord(StubQwen(gl.stub_handlers()), out, 7, False)
    gl.write_landlord(names, world, out)
    return out, names, world


def test_every_file_has_the_exact_label(made: tuple[Path, dict, dict]) -> None:
    out, _, world = made
    exact = "SAMPLE — FICTIONAL COMPANY".encode()
    assert LABEL.encode() == exact
    files = [p for p in out.rglob("*") if p.is_file()]
    assert len(files) == len(world["documents"]) + 3  # documents + expectations, names, README
    for p in files:
        raw = p.read_bytes()
        assert exact in raw and b"???" not in raw, p
    for p in out.glob("statements/*.txt"):
        assert p.read_text(encoding="utf-8").splitlines()[0] == LABEL


def test_statements_add_up_and_figures_are_whole_pence(made: tuple[Path, dict, dict]) -> None:
    _, _, world = made
    statements = [d for d in world["documents"] if d["kind"] == "letting_statement"]
    assert len(statements) == 12  # six months, two properties
    for d in statements:
        *charges, (label, net) = d["lines"]
        assert label == "Paid to landlord" and net == sum(p for _, p in charges)
        fee = next(p for t, p in charges if t.startswith("Management fee"))
        vat = next(p for t, p in charges if t.startswith("VAT"))
        rent = charges[0][1]
        assert -fee == rent // 10 and -vat == (-fee * 20 * 2 + 100) // 200
    for d in world["documents"]:
        for f in d["figures"]:
            assert isinstance(f["pence"], int) and f["pence"] > 0
            assert (f["field"], f["box"]) == gl.CATEGORY[f["category"]]
    mortgage = next(d for d in world["documents"] if d["kind"] == "mortgage_statement")
    (_, paid), (_, interest), (_, capital) = mortgage["lines"]
    assert paid == interest + capital and mortgage["figures"][0]["pence"] == interest  # capital is never a cost
    machine = next(d for d in world["documents"] if "washing machine" in d["title"])
    assert machine["figures"][0]["pence"] == sum(p for _, p in machine["lines"])  # cost + disposal − trade-in


def test_owners_split_and_expectations(made: tuple[Path, dict, dict]) -> None:
    out, _, world = made
    e = json.loads((out / "expectations.json").read_text(encoding="utf-8"))
    assert e["label"] == LABEL and e["tax_year"] == "2026-27"
    for prop, owners in e["per_owner"].items():
        for cat, whole in e["whole"][prop].items():
            assert sum(o[cat] for o in owners.values()) == whole
    house = list(e["per_owner"]["house"].values())
    assert all(abs(house[0][c] - house[1][c]) <= 1 for c in house[0])  # spouses, no Form 17: 50:50
    assert (
        e["mine"]["rents"]
        == e["whole"]["flat"]["rents"] + e["per_owner"]["house"][world["owners"]["house"][0]["name"]]["rents"]
    )
    assert e["cumulative_body"]["ukProperty"]["income"]["periodAmount"] == e["mine"]["rents"] / 100


def test_the_runtime_gives_the_same_answers(made: tuple[Path, dict, dict]) -> None:
    from accnomos_ledger import LedgerEvent, Line
    from app import property as pr

    _, names, world = made
    props = {
        "flat": pr.Property(**pr.PropertyIn(name=names["flat"]["address"]).model_dump(), id="flat", created_at=""),
        "house": pr.Property(
            **pr.PropertyIn(
                name=names["house"]["address"],
                joint="spouses",
                owners=[pr.Owner(**o) for o in world["owners"]["house"]],
            ).model_dump(),
            id="house",
            created_at="",
        ),
    }
    events, tags = [], {}
    for d in world["documents"]:
        for f in d["figures"]:
            cat = pr.BY_KEY[f["category"]]
            side = [Line(account="1200 Bank", debit=f["pence"]), Line(account=cat.account, credit=f["pence"])]
            if cat.group != "income":
                side = [Line(account=cat.account, debit=f["pence"]), Line(account="1200 Bank", credit=f["pence"])]
            ev = LedgerEvent(
                kind="sale" if cat.group == "income" else "purchase",
                date=date.fromisoformat(d["date"]),
                lines=side,
                approved_by="gold",
                approved_at=datetime(2026, 10, 6, tzinfo=UTC),
            )
            events.append(ev)
            tags[ev.id] = pr.Tag(property_id=d["property"])
    s = pr.summarise(events, list(props.values()), tags, pr.PropertySettings(), "2026-27", gl.PERIOD_END)
    e = world["expectations"]
    assert {k: v for k, v in s.mine.by_category.items() if v} == e["mine"]
    assert s.mine.profit == e["mine_profit"] and s.finance.credit == e["finance_credit_pence"]
    assert pr.cumulative_body(s, pr.PropertySettings()) == e["cumulative_body"]
    assert pr.annual_body(s) == e["annual_body"]


def test_bad_replies_are_re_asked_never_repaired() -> None:
    good = gl.stub_handlers()["names"]({"seed": 1})
    real = json.loads(json.dumps(good))
    real["names"][2]["name"] = "Screwfix Lettings"
    assert "real name" in (gl.check_names(real) or "")
    bad_pc = json.loads(json.dumps(good))
    bad_pc["flat"]["postcode"] = "NOT A CODE"
    assert "postcode" in (gl.check_names(bad_pc) or "")
    assert gl.check_names(good) is None
    calls = iter([real, good])
    client = StubQwen({"names": lambda h: next(calls)})
    names = gl.build_names(client, None, 1, True)
    assert client.calls == 2 and names["people"]["agent"] == good["names"][2]["name"]
    with pytest.raises(QwenError):
        gl.build_names(StubQwen({"names": lambda h: real}), None, 1, True)


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    assert gl.main(["--dry-run", "--landlords", "1", "--out", str(tmp_path / "x")]) == 0
    assert not (tmp_path / "x").exists()
    assert gl.main(["--stub", "--landlords", "1", "--out", str(tmp_path / "y")]) == 0
    assert (tmp_path / "y" / "landlord_7" / "expectations.json").exists()
