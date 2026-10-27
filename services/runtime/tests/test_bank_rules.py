"""Bank rules and reconciliation, against FakeStorageProvider."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode
from app.approve import approve
from app.bank_reconcile import proposal_for_coding
from app.bank_rules import BankRule, check_regex_safe, first_match, normalise_description
from app.books import BANK_LINES, Books

USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}

OCT = b"""Date,Description,Amount,Balance\r
21/10/2026,CARD PAYMENT SCREWFIX 1234,-38.47,961.53\r
22/10/2026,ACME KITCHENS INV-0042,1200.00,2161.53\r
23/10/2026,COFFEE,-2.50,2159.03\r
"""

NOV = b"""Date,Description,Amount,Balance\r
22/10/2026,  acme kitchens   inv-0042 ,1200.00,2161.53\r
23/10/2026,coffee,-2.50,2159.03\r
24/10/2026,TOOLSTATION 0412,-12.00,2147.03\r
"""


def _rule(**kw) -> dict:
    body = {
        "name": "test",
        "match": {"op": "contains", "value": "screwfix"},
        "direction": "out",
        "action": {"account": "5100 Tools & small equipment", "vat_code": "N", "contact": "Screwfix"},
    }
    body.update(kw)
    return body


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
async def books(fake: FakeStorageProvider) -> Books:
    return Books(fake)


@pytest.fixture
def client(fake: FakeStorageProvider, books: Books):
    from app.main import app
    from app.routes_books import get_books

    async def override() -> Books:
        return books

    app.dependency_overrides[get_books] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _rules(client: TestClient) -> list[dict]:
    r = client.get("/books/bank/rules", headers=H)
    assert r.status_code == 200, r.text
    return r.json()


# Rule order: first match wins -------------------------------------------- #


def test_first_match_wins_in_order() -> None:
    wide = BankRule(match={"op": "contains", "value": "screwfix"}, action={"account": "7999 Sundry expenses"})
    narrow = BankRule(match={"op": "contains", "value": "screwfix direct"}, action={"account": "5100 Tools"})
    assert first_match([wide, narrow], description="Screwfix Direct", amount_pence=-100) == wide
    assert first_match([narrow, wide], description="Screwfix Direct", amount_pence=-100) == narrow
    assert first_match([wide], description="Someone else", amount_pence=-100) is None


def test_rules_crud_and_reorder(client: TestClient) -> None:
    a = client.post("/books/bank/rules", headers=H, json=_rule()).json()
    b = client.post("/books/bank/rules", headers=H, json=_rule(name="second", match={"op": "equals", "value": "coffee"})).json()
    assert [r["id"] for r in _rules(client)] == [a["id"], b["id"]]

    bad = client.post("/books/bank/rules/reorder", headers=H, json={"ids": [a["id"]]})
    assert bad.status_code == 400
    r = client.post("/books/bank/rules/reorder", headers=H, json={"ids": [b["id"], a["id"]]})
    assert r.status_code == 200, r.text
    assert [x["id"] for x in r.json()] == [b["id"], a["id"]]

    edit = client.put(f"/books/bank/rules/{a['id']}", headers=H, json=_rule(name="edited"))
    assert edit.status_code == 200 and edit.json()["name"] == "edited" and edit.json()["id"] == a["id"]

    gone = client.delete(f"/books/bank/rules/{a['id']}", headers=H)
    assert gone.status_code == 200
    assert client.delete(f"/books/bank/rules/{a['id']}", headers=H).status_code == 404
    assert [x["id"] for x in _rules(client)] == [b["id"]]


def test_rule_validation(client: TestClient) -> None:
    assert client.post("/books/bank/rules", headers=H, json=_rule(amount_min_pence=5, amount_max_pence=1)).status_code == 400
    assert client.post("/books/bank/rules", headers=H,
                       json=_rule(action={"account": "5100 Tools", "vat_code": "Q"})).status_code == 400
    assert client.post("/books/bank/rules", headers=H,
                       json=_rule(action={"account": "5100 Tools", "job_id": "nope"})).status_code == 400
    # Invalid regex is a 422 from the model validator.
    assert client.post("/books/bank/rules", headers=H,
                       json=_rule(match={"op": "regex", "value": "(a+)+"})).status_code == 422


# The regex guard ---------------------------------------------------------- #


def test_regex_guard_refuses_nested_quantifiers_and_backreferences() -> None:
    import pytest as _pytest

    for bad in ("(a+)+", "(a*)+", "(a|b*)*", "(\\w+)+", "x{2,3}{2}", "(a)\\1", "(?P<x>a)(?P=x)"):
        with _pytest.raises(ValueError):
            check_regex_safe(bad)
    # The safe subset still works: groups, alternation, single quantifiers, classes.
    for ok in (r"screwfix\s+\d+", r"(screwfix|toolstation)", r"inv[- ]?\d{4}", r"fee|charge", r"[A-Z]{2}\d+"):
        check_regex_safe(ok)
    with _pytest.raises(ValueError):
        check_regex_safe("(unclosed")


def test_normalise_description() -> None:
    assert normalise_description("  ACME   Kitchens\tINV-0042 ") == "acme kitchens inv-0042"


# Overlap de-dup ----------------------------------------------------------- #


def test_overlap_reexport_adds_only_new_lines(client: TestClient, fake: FakeStorageProvider) -> None:
    first = client.post("/books/bank/import", headers=H, files={"file": ("oct.csv", OCT, "text/csv")}).json()
    assert first["new_lines"] == 3 and not first["duplicate_file"]

    second = client.post("/books/bank/import", headers=H, files={"file": ("nov.csv", NOV, "text/csv")}).json()
    # Two lines overlap (one with different case/whitespace); only TOOLSTATION is new.
    assert second["new_lines"] == 1 and not second["duplicate_file"], second

    statements = client.get("/books/bank/statements", headers=H).json()
    assert sorted(s["lines"] for s in statements) == [1, 3]
    assert sum(s["lines"] for s in statements) == 4

    # A re-export with nothing new files nothing and leaves the statements alone.
    third = client.post("/books/bank/import", headers=H, files={"file": ("nov.csv", NOV, "text/csv")}).json()
    assert third["duplicate_file"] and third["new_lines"] == 0 and third["filed_path"] is None
    assert sum(s["lines"] for s in client.get("/books/bank/statements", headers=H).json()) == 4
    assert len([p for p in fake.files if p.startswith(f"{BANK_LINES}/")]) == 2


def test_genuine_duplicate_payments_in_one_file_both_kept(client: TestClient) -> None:
    twice = b"""Date,Description,Amount\r\n21/10/2026,COFFEE,-2.50\r\n21/10/2026,COFFEE,-2.50\r\n"""
    r = client.post("/books/bank/import", headers=H, files={"file": ("twice.csv", twice, "text/csv")}).json()
    assert r["new_lines"] == 2, r


# Reconcile: exact match ---------------------------------------------------- #


def _purchase(eid: str, gross: int, when: date, who: str, proposal_id: str | None = None) -> LedgerEvent:
    net = round(gross / 1.2)
    return LedgerEvent(
        id=eid,
        kind="purchase",
        date=when,
        lines=[
            Line(account="2100 Creditors", debit=0, credit=gross),
            Line(account="5100 Tools & small equipment", debit=net, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", debit=gross - net),
        ],
        net=net,
        vat=gross - net,
        counterparty=who,
        evidence=["ab" * 32],
        approved_by=USER,
        approved_at=datetime(2026, 10, 25, tzinfo=UTC),
        proposal_id=proposal_id,
    )


async def _bill(books: Books, proposal_id: str, number: str, gross: int) -> LedgerEvent:
    from app.schemas import ExtractedDoc, Proposal

    doc = ExtractedDoc.model_validate({
        "doc_type": "receipt", "supplier_name": "Acme Kitchens", "supplier_vat_number": None,
        "customer_name": None, "invoice_number": number, "date": "2026-10-22", "currency": "GBP",
        "lines": [], "net_total": 1000.0, "vat_total": 0.0, "gross_total": 1000.0,
        "payment_method": None, "card_last4": None, "category_guess": "Sundry", "confidence": 0.9,
    })
    await books.save_proposal(Proposal(id=proposal_id, doc_sha256="cd" * 32, extracted=doc, checks=[],
                                       status="posted", reasons=[], suggested_filename="x.png",
                                       journal_draft=[], model="t", elapsed_s=0.0))
    event = _purchase("b" * 32, gross, date(2026, 10, 22), "Acme Kitchens", proposal_id)
    await books.post_event(event)
    return event


async def test_reconcile_exact_bill_match_and_approve(client: TestClient, books: Books) -> None:
    await _bill(books, "d" * 32, "INV-0099", 50000)
    bill_csv = b"""Date,Description,Amount\r\n24/10/2026,ACME SUPPLIES INV-0099 BGC,-500.00\r\n25/10/2026,COFFEE,-2.50\r\n"""
    client.post("/books/bank/import", headers=H, files={"file": ("bill.csv", bill_csv, "text/csv")})

    rows = client.get("/books/bank/reconcile", headers=H).json()
    by_line = {r["line_id"]: r for r in rows}
    acme = next(r for r in rows if r["exact"] is not None)
    assert acme["exact"]["event_ids"] == ["b" * 32]
    assert "INV-0099" in acme["exact"]["reasons"][0]
    # No reference on the other line, so no exact match for it.
    assert all(r["exact"] is None for lid, r in by_line.items() if lid != acme["line_id"])

    before = len(await books.list_events())
    r = client.post(f"/books/bank/lines/{acme['line_id']}/approve", headers=H, json={"kind": "exact"})
    assert r.status_code == 200, r.text
    assert r.json()["event_id"] is None  # matching never posts
    assert len(await books.list_events()) == before


async def test_reconcile_exact_open_invoice(client: TestClient, books: Books) -> None:
    from app import invoicing as inv_

    event = _purchase("c" * 32, 120000, date(2026, 10, 22), "Acme Kitchens")
    await books.post_event(event)
    inv = inv_.Invoice(
        number="INV-0042", status="sent",
        customer=inv_.InvoiceCustomer(name="Acme Kitchens"),
        issue_date=date(2026, 10, 22), due_date=date(2026, 11, 22), lines=[],
        vat_summary=[], net_pence=100000, vat_pence=20000, total_pence=120000,
        created_by=USER, event_id="c" * 32,
    )
    await inv_.save_invoice(books, inv)
    client.post("/books/bank/import", headers=H, files={"file": ("oct.csv", OCT, "text/csv")})

    rows = client.get("/books/bank/reconcile", headers=H).json()
    acme = next(r for r in rows if r["exact"] is not None)
    assert acme["exact"]["event_ids"] == ["c" * 32]


# Reconcile: rule approve posts the same events as Review approve ----------- #


async def test_rule_approve_posts_review_events(client: TestClient, books: Books) -> None:
    client.post("/books/bank/rules", headers=H, json=_rule())
    two = b"""Date,Description,Amount\r\n21/10/2026,SCREWFIX DIRECT,-38.47\r\n21/10/2026,SCREWFIX DIRECT,-38.47\r\n"""
    client.post("/books/bank/import", headers=H, files={"file": ("two.csv", two, "text/csv")})
    lines = client.get("/books/bank/lines", headers=H).json()
    assert len(lines) == 2

    rows = client.get("/books/bank/reconcile", headers=H).json()
    assert len(rows) == 2 and all(r["rule"] is not None and r["exact"] is None for r in rows)

    first, second = lines[0]["id"], lines[1]["id"]
    r = client.post(f"/books/bank/lines/{first}/approve", headers=H, json={"kind": "rule"})
    assert r.status_code == 200, r.text
    posted_event_id = r.json()["event_id"]
    assert posted_event_id

    # The same coding approved on Review posts the same ledger lines.
    line2 = await books.find_bank_line(second)
    manual = proposal_for_coding(line2, account="5100 Tools & small equipment", vat_code="N", contact="Screwfix")
    await books.save_proposal(manual)
    posted_manual = await approve(books, manual.id, USER, {"account": "5100 Tools & small equipment"})

    got = (await books.get_event(posted_event_id)).lines
    want = (await books.get_event(posted_manual.event_id)).lines
    assert [(l.account, l.debit, l.credit, l.vat_code) for l in got] == [
        (l.account, l.debit, l.credit, l.vat_code) for l in want
    ]

    # "Create rule from this" pre-fills from the approved line.
    draft = client.get(f"/books/bank/lines/{first}/rule-draft", headers=H,
                       params={"account": "5100 Tools & small equipment"}).json()
    assert draft["match"] == {"op": "contains", "value": "SCREWFIX DIRECT"}
    assert draft["direction"] == "out"


async def test_ai_suggestion_uses_model_then_validates(books: Books, monkeypatch) -> None:
    import json

    from app.ai.config import AiConfig
    from app.bank_reconcile import suggest_ai
    from app import bank_reconcile as rec

    async def fake_call(messages, cfg, schema, name):
        assert messages[0]["content"] == rec.BANK_SUGGEST_PROMPT
        return json.dumps({"account": "5100 Tools & small equipment", "vat_code": "S",
                           "contact": "Screwfix", "reason": "says Screwfix"})

    async def fake_fail(messages, cfg, schema, name):
        raise ConnectionError("model down")

    import app.ai.ask as ask_ai

    monkeypatch.setattr(ask_ai, "call_json_model", fake_call)
    got = await suggest_ai(_FakeLine(), AiConfig(mode="local", base_url="http://x", model="m"),
                           ["5100 Tools & small equipment", "7999 Sundry expenses"])
    assert got is not None and got.account == "5100 Tools & small equipment" and got.by == "suggested by AI"

    monkeypatch.setattr(ask_ai, "call_json_model", fake_fail)
    assert await suggest_ai(_FakeLine(), AiConfig(mode="local", base_url="http://x", model="m"), ["a"]) is None


class _FakeLine:
    date = date(2026, 10, 21)
    description = "SCREWFIX DIRECT"
    reference = None
    amount_pence = -3847


async def test_rule_order_first_match_wins_on_reconcile(client: TestClient, books: Books) -> None:
    client.post("/books/bank/rules", headers=H, json=_rule(name="wide"))
    client.post("/books/bank/rules", headers=H, json=_rule(
        name="narrow", match={"op": "contains", "value": "screwfix direct"},
        action={"account": "7999 Sundry expenses", "vat_code": "N"}))
    client.post("/books/bank/import", headers=H, files={"file": ("oct.csv", OCT, "text/csv")})
    rows = client.get("/books/bank/reconcile", headers=H).json()
    screwfix = next(r for r in rows if r["rule"] is not None)
    assert screwfix["rule"]["account"] == "5100 Tools & small equipment"  # the first rule, not the narrower second
