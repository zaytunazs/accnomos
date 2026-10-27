"""The gold bank statements (evals/gold/bank/): four UK exports in the three column layouts."""

import json
from datetime import date, datetime
from pathlib import Path

import pytest
from accnomos_ledger import LedgerEvent, Line, VatCode
from accnomos_ledger.bank import detect_bank, parse_bank_csv, suggest_action
from accnomos_ledger.matching import suggest_matches

GOLD = Path(__file__).resolve().parents[3] / "evals" / "gold" / "bank"
EXPECTED = json.loads((GOLD / "expected.json").read_text())
FILES = sorted(EXPECTED["statements"])


def gold_event(spec: dict) -> LedgerEvent:
    gross = spec["gross_pence"]
    when = date.fromisoformat(spec["date"])
    if spec["kind"] == "sale":
        lines = [
            Line(account="1100 Debtors", debit=gross),
            Line(account="4000 Sales", credit=gross, vat_code=VatCode.STANDARD),
        ]
    else:
        lines = [
            Line(account="7999 Sundry expenses", debit=gross, vat_code=VatCode.STANDARD),
            Line(account="1200 Bank", credit=gross),
        ]
    return LedgerEvent(
        id=spec["id"],
        kind=spec["kind"],
        date=when,
        lines=lines,
        net=gross,
        vat=0,
        counterparty=spec["counterparty"],
        evidence=["ab" * 32],
        approved_by="gold@example.co.uk",
        approved_at=datetime(2026, 10, 26),
    )


EVENTS = [gold_event(e) for e in EXPECTED["events"]]


@pytest.mark.parametrize("name", FILES)
def test_gold_statement_parses_and_names_its_bank(name: str) -> None:
    want = EXPECTED["statements"][name]
    data = (GOLD / name).read_bytes()
    lines = parse_bank_csv(data, name)
    assert detect_bank(data) == want["bank"]
    assert [(ln.description, ln.amount_pence) for ln in lines] == [
        (w["description"], w["amount_pence"]) for w in want["lines"]
    ]
    assert max(ln.date for ln in lines).isoformat() == want["last_date"]


@pytest.mark.parametrize("name", FILES)
def test_gold_matches_and_suggested_actions(name: str) -> None:
    want = EXPECTED["statements"][name]["lines"]
    lines = parse_bank_csv((GOLD / name).read_bytes(), name)
    matches = {m.line_id: m for m in suggest_matches(lines, EVENTS)}
    for line, w in zip(lines, want, strict=True):
        m = matches.get(line.id)
        if "match" in w:
            assert m is not None, f"{w['description']}: no match"
            assert (m.event_id, m.kind) == (w["match"], w["kind"]), (w["description"], m.reasons, m.score)
        else:
            assert m is None, f"{w['description']}: unexpected match {m}"
            assert suggest_action(line).action == w["action"], w["description"]


def test_all_statements_together_match_each_event_once() -> None:
    lines = [ln for name in FILES for ln in parse_bank_csv((GOLD / name).read_bytes(), name)]
    matches = suggest_matches(lines, EVENTS)
    assert sorted(m.event_id for m in matches) == sorted(e["id"] for e in EXPECTED["events"])
