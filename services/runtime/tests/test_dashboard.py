"""GET /books/dashboard against FakeStorageProvider: cash, owed, VAT, attention, activity and last runs. No model."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode
from accnomos_ledger.bank import BankLine
from fastapi.testclient import TestClient

from app import dashboard
from app import invoicing as inv_
from app.approve import reversal_of
from app.books import AUDIT, AUTOPILOT_AUDIT, BANK_LINES, Books
from app.schemas import ExtractedDoc, Proposal

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok"}
TODAY = date(2026, 10, 27)
PROFILE = inv_.InvoiceProfile.model_validate({
    "name": "Sam Builds Ltd", "address": "1 High Street\nLeeds LS1 1AA",
    "bank": {"account_name": "Sam Builds Ltd", "sort_code": "12 34 56", "account_number": "12345678"},
})
STATEMENT_A = "03 Bank statements/2026-10-26_starling.csv"  # later, but nothing matched on it
STATEMENT_B = "03 Bank statements/2026-10-24_monzo.csv"


def _proposal(pid: str, supplier: str, status: str, gross: float = 12.0) -> Proposal:
    doc = ExtractedDoc(
        doc_type="purchase_invoice", supplier_name=supplier, supplier_vat_number=None, customer_name=None,
        invoice_number=None, date="2026-10-01", currency="GBP", lines=[], net_total=gross / 1.2,
        vat_total=gross - gross / 1.2, gross_total=gross, payment_method=None, card_last4=None,
        category_guess="Materials", confidence=0.9,
    )
    return Proposal(id=pid, doc_sha256="cd" * 32, extracted=doc, checks=[], status=status, reasons=[],  # type: ignore[arg-type]
                    suggested_filename="x.pdf", journal_draft=[], model="stub", elapsed_s=1.0)


def _purchase(eid: str, gross: int, when: date, who: str, proposal_id: str | None = None) -> LedgerEvent:
    net = round(gross / 1.2)
    return LedgerEvent(
        id=eid, kind="purchase", date=when, net=net, vat=gross - net, counterparty=who, approved_by=USER,
        approved_at=datetime(2026, 10, 1, tzinfo=UTC), proposal_id=proposal_id,
        lines=[Line(account="5000 Materials", debit=net, vat_code=VatCode.STANDARD),
               Line(account="2200 VAT control", debit=gross - net), Line(account="2100 Creditors", credit=gross)],
    )


async def _invoice(b: Books, number: str, issue: date, status: str) -> inv_.Invoice:
    draft = inv_.InvoiceDraft.model_validate({
        "customer": {"name": "Acme Kitchens Ltd"}, "issue_date": issue.isoformat(),
        "lines": [{"description": "Labour", "quantity": "7.5", "unit": "hours", "unit_price_pence": 4500}],
    })
    inv = inv_.build_invoice(number, draft, PROFILE, USER)
    event = inv_.sale_event(inv, USER, [])
    await b.post_event(event)
    inv.status, inv.event_id = status, event.id  # type: ignore[assignment]
    await inv_.save_invoice(b, inv)
    return inv


def _line(lid: str, when: date, amount: int, balance: int | None, src: str, **kw) -> dict:
    return BankLine(id=lid, date=when, amount_pence=amount, description="x", balance_pence=balance, source_file=src,
                    **kw).model_dump(mode="json")


def _audit_line(ts: str, actor: str, action: str, **refs) -> str:
    return json.dumps({"ts": ts, "actor": actor, "action": action, "refs": refs})


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
async def books(fake: FakeStorageProvider) -> Books:
    b = Books(fake)
    howdens = _proposal("a" * 16, "Howdens Joinery Ltd", "posted", 240.0)
    for p in [howdens, _proposal("b" * 16, "Screwfix", "proposed"), _proposal("c" * 16, "Travis Perkins", "needs_a_look")]:
        await b.save_proposal(p)
    await b.post_event(_purchase("d" * 32, 24000, date(2026, 9, 30), "Howdens Joinery Ltd", howdens.id))
    undone = _purchase("e" * 32, 9999, date(2026, 9, 2), "Wickes")
    await b.post_event(undone)
    await b.post_event(reversal_of(undone, USER))

    await _invoice(b, "INV-0001", date(2026, 9, 1), "sent")  # due 1 Oct: 26 days overdue
    await _invoice(b, "INV-0002", date(2026, 9, 15), "paid")  # marked paid by hand, no bank line
    inv3 = await _invoice(b, "INV-0003", date(2026, 10, 20), "sent")  # paid: a bank line is matched to it

    # Statement B is stored newest first, as some banks export: the closing balance is 5,400.00, not 5,405.00.
    await b.write_json(f"{BANK_LINES}/{'1' * 64}.json", [
        _line("0000000000000003", date(2026, 10, 24), -500, 540000, STATEMENT_B),
        _line("0000000000000002", date(2026, 10, 24), 40500, 540500, STATEMENT_B,
              status="matched", matched_event_id=inv3.event_id, matched_event_ids=[inv3.event_id]),
        _line("0000000000000001", date(2026, 10, 23), -1000, 500000, STATEMENT_B, status="ignored"),
    ])
    await b.write_json(f"{BANK_LINES}/{'2' * 64}.json", [
        _line("0000000000000004", date(2026, 10, 25), -2000, 100000, STATEMENT_A),
        _line("0000000000000005", date(2026, 10, 26), -3000, 97000, STATEMENT_A),
    ])

    old = [_audit_line("2026-08-01T09:00:00+00:00", "agent:intake", "mail_scanned", saved=9, candidates=9)]
    sep = [_audit_line(f"2026-09-{d:02d}T09:00:00+00:00", f"user:{USER}", "job_created") for d in range(1, 9)]
    oct_ = [
        _audit_line("2026-10-26T09:10:00+00:00", "agent:intake", "mail_scanned", saved=2, candidates=3),
        "not json",
        _audit_line("2026-10-26T17:41:00+00:00", "agent:extractor", "proposed", proposal="c" * 16, status="needs_a_look"),
        _audit_line("2026-10-26T17:42:00+00:00", "autopilot", "approved", proposal="a" * 16),
        _audit_line("2026-10-26T18:00:00+00:00", "agent:triage", "mail_triaged", threads=4),
    ]
    fake.files[f"{AUDIT}/2026-08.jsonl"] = ("\n".join(old) + "\n").encode()
    fake.files[f"{AUDIT}/2026-09.jsonl"] = ("\n".join(sep) + "\n").encode()
    fake.files[f"{AUDIT}/2026-10.jsonl"] = ("\n".join(oct_) + "\n").encode()
    fake.files[f"{AUTOPILOT_AUDIT}/2026-10.jsonl"] = (json.dumps({
        "ts": "2026-10-26T17:42:00+00:00", "action": "approved", "supplier_key": "howdens-joinery", "gross_pence": 24000,
    }) + "\n").encode()
    await b.record_scan(datetime(2026, 10, 26, 17, 40, tzinfo=UTC))
    return b


@pytest.fixture
def client(books: Books):
    from app.main import app
    from app.routes_books import get_books

    async def over() -> Books:
        return books

    app.dependency_overrides[get_books] = over
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_dashboard_payload(client: TestClient, fake: FakeStorageProvider) -> None:
    before = dict(fake.files)
    r = client.get(f"/books/dashboard?stagger=1&today={TODAY}", headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    assert fake.files == before  # reads only
    assert d["unavailable"] == []

    assert d["cash"] == {"balance_pence": 540000, "as_of": "2026-10-24", "bank": "monzo", "statement": STATEMENT_B,
                         "reconciled_to": "2026-10-23"}
    # INV-0001 only: INV-0002 was marked paid, INV-0003 has a matched bank line.
    assert d["owed_to_you"] == {"total_pence": 40500, "documents": 1, "oldest_days": 56,
                                "overdue": 1, "overdue_pence": 40500, "most_overdue_days": 26}
    assert d["owed_by_you"] == {"total_pence": 24000, "documents": 1, "oldest_days": 27}  # the reversed one is gone

    assert d["vat"]["current"]["label"] == "Oct–Dec 2026" and d["vat"]["current"]["box5"] == "67.50"
    assert d["vat"]["due"]["label"] == "Jul–Sep 2026" and d["vat"]["due"]["deadline"] == "2026-11-07"
    assert d["vat"]["due"]["days_remaining"] == 11

    assert d["attention"] == {"proposed": 1, "needs_a_look": 1, "unmatched_bank_lines": 3, "overdue_invoices": 1,
                              "total": 6}

    activity = d["activity"]
    assert len(activity) == 10  # the last ten of the last two months; August is not read
    assert [(a["actor"], a["text"], a["tone"]) for a in activity[:4]] == [
        ("Triage", "Mail triaged", "ok"),
        ("Autopilot", "Posted Howdens Joinery Ltd £240.00 to the ledger", "ok"),
        ("Extractor", "Moved Travis Perkins £12.00 to Needs a look", "warn"),
        ("Intake", "Checked Outlook: 2 saved from 3 candidates", "ok"),
    ]
    assert {a["actor"] for a in activity[4:]} == {"You"}

    runs = d["runs"]
    assert runs["scan"]["at"].startswith("2026-10-26T17:40")
    assert runs["autopilot"]["summary"] == "Posted howdens-joinery £240.00"
    assert runs["intake"] == {"at": "2026-10-26T09:10:00Z", "summary": "2 imported from Outlook"}
    assert runs["triage"]["at"] == "2026-10-26T18:00:00Z"


def test_broken_invoice_file_leaves_the_rest(client: TestClient, fake: FakeStorageProvider) -> None:
    fake.files[f"{inv_.INVOICES}/INV-0009.json"] = b'{"number": "INV-0009"}'  # hand-edited, missing fields
    d = client.get(f"/books/dashboard?today={TODAY}", headers=H).json()
    assert d["unavailable"] == ["invoices"]
    assert d["owed_to_you"]["overdue"] is None and d["attention"]["overdue_invoices"] is None
    # Without the invoices, INV-0002's hand-marked payment is unknown, so it still counts as owed.
    assert d["owed_to_you"]["total_pence"] == 81000 and d["cash"]["balance_pence"] == 540000


def test_empty_books_and_auth(fake: FakeStorageProvider) -> None:
    from app.main import app
    from app.routes_books import get_books

    assert TestClient(app).get("/books/dashboard").status_code == 401

    async def over() -> Books:
        return Books(fake)

    app.dependency_overrides[get_books] = over
    try:
        c = TestClient(app)
        d = c.get("/books/dashboard", headers=H).json()
        assert d["cash"]["balance_pence"] is None and d["owed_to_you"]["total_pence"] == 0
        assert d["attention"]["total"] == 0 and d["activity"] == []
        assert d["runs"] == {"scan": None, "autopilot": None, "intake": None, "triage": None}
        assert c.get("/books/dashboard?stagger=1&start_month=2", headers=H).status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_closing_line_follows_the_running_balance() -> None:
    src = STATEMENT_B
    a = BankLine(id="a" * 16, date=TODAY, amount_pence=100, description="a", balance_pence=1100, source_file=src)
    b = BankLine(id="b" * 16, date=TODAY, amount_pence=-50, description="b", balance_pence=1050, source_file=src)
    assert dashboard.closing_line([a, b]) == b and dashboard.closing_line([b, a]) == b
    assert dashboard.closing_line([a.model_copy(update={"balance_pence": None})]) is None
    # Nothing matched on any statement: no cash figure, as the tile cannot vouch for it.
    assert dashboard.cash_position([a, b]).balance_pence is None
