"""The ledger2 gold set (evals/gold/ledger2) driven through the real runtime on fake storage: part and over
payments through the payments route, overlapping bank re-exports through the bank import, supplier credit notes
through propose -> approve into the VAT return. Every figure is pence."""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeMailSender, FakeStorageProvider
from accnomos_ledger.vat import compute_vat_return
from app import contacts as cb
from app import invoicing as inv_
from app import payments as pay_
from app.approve import approve
from app.books import Books, now
from app.invoicing import PROFILE, InvoiceDraft, InvoiceProfile
from app.journal import draft_journal
from app.pdf import render_invoice
from app.schemas import ExtractedDoc, ExtractedLine, Proposal

L2 = Path(__file__).resolve().parents[3] / "evals" / "gold" / "ledger2"
USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
PROFILE_JSON = {
    "name": "Bramblewood Joinery Ltd",
    "address": "1 High Street\nLeeds LS1 1AA",
    "vrn": "GB 123 4567 89",
    "bank": {"account_name": "Bramblewood Joinery Ltd", "sort_code": "12 34 56", "account_number": "12345678"},
}


def _p(x: float) -> int:
    return round(x * 100)


def _gold(folder: str, pattern: str = "*.json") -> list[Path]:
    return sorted((L2 / folder).glob(pattern))


@pytest.fixture
async def books() -> Books:
    b = Books(FakeStorageProvider())
    await b.write_json(PROFILE, InvoiceProfile.model_validate(PROFILE_JSON).model_dump(mode="json"))
    return b


@pytest.fixture
def sender() -> FakeMailSender:
    return FakeMailSender()


@pytest.fixture
def client(books: Books, sender: FakeMailSender):
    from app.main import app
    from app.routes_books import get_books
    from app.routes_invoices import get_sender

    async def over_books() -> Books:
        return books

    async def over_sender() -> FakeMailSender:
        return sender

    app.dependency_overrides[get_books] = over_books
    app.dependency_overrides[get_sender] = over_sender
    yield TestClient(app)
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# a. part-paid and overpaid sales invoices
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", _gold("part_paid"), ids=lambda p: p.stem)
async def test_payments_reach_the_expected_balance(path: Path, books: Books, sender: FakeMailSender, client):
    g = json.loads(path.read_text(encoding="utf-8"))
    gross = _p(g["gross_total"])
    draft = InvoiceDraft.model_validate(
        {
            "customer": {"name": g["customer"]["name"], "email": "accounts@fictional.example"},
            "issue_date": g["date"],
            "lines": [
                {"description": ln["description"][:300], "quantity": "1", "unit_price_pence": _p(ln["net"])}
                for ln in g["lines"]
            ],
        }
    )
    inv = await inv_.create_invoice(books, draft, USER)
    assert inv.total_pence == gross  # same figure the gold computed
    inv = await inv_.send_invoice(books, sender, inv.number, USER, render_invoice(inv, await inv_.load_profile(books)))

    for p in g["payments"]:
        r = client.post(
            f"/invoices/{inv.number}/payments",
            headers=H,
            json={"amount_pence": _p(p["amount"]), "paid_on": p["date"], "payment_ref": p["reference"]},
        )
        assert r.status_code == 200, r.text

    m = pay_.invoice_money(await inv_.get_invoice(books, inv.number), await pay_.load_ledger(books))
    assert m is not None
    exp = g["expected"]
    paid = sum(p.amount_pence for p in m.payments)
    assert paid == _p(exp["paid"])
    assert m.paid_pence + m.overpaid_pence == paid
    assert m.balance_pence - m.overpaid_pence == _p(exp["outstanding"])
    assert m.payment_status == exp["status"]
    contacts, ledger, _ = await cb.contact_book(books)
    mine = next(c for c in contacts if c.name == g["customer"]["name"])
    t = cb.totals(cb.assign(contacts, cb.documents(ledger))[mine.id], ledger, date(2026, 4, 6), date(2027, 4, 5))
    if exp["status"] == "overpaid":
        assert m.overpaid_pence == -_p(exp["outstanding"]) > 0
        assert t.customer_credit_pence == m.overpaid_pence
    else:
        assert m.overpaid_pence == 0 and t.customer_credit_pence == 0
    assert t.open_receivable_pence == max(0, _p(exp["outstanding"]))


# --------------------------------------------------------------------------- #
# b. overlapping bank statements
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("meta_path", _gold("bank_pairs", "*_meta.json"), ids=lambda p: p.name[:3])
async def test_overlapping_bank_exports_import_each_line_once(meta_path: Path, books: Books):
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    a = (L2 / "bank_pairs" / meta["first"]).read_bytes()
    b = (L2 / "bank_pairs" / meta["second"]).read_bytes()
    n_b = len(list(csv.DictReader(io.StringIO(b.decode("utf-8")))))

    first = await books.import_bank_csv(a, meta["first"], USER)
    assert first.new_lines == meta["lines_a"] and not first.duplicate_file
    second = await books.import_bank_csv(b, meta["second"], USER)
    assert second.new_lines == n_b - meta["overlap"]
    stored = await books.stored_bank_lines()
    assert len(stored) == meta["expected_unique_lines"]
    assert len({ln.id for ln in stored}) == len(stored)
    # Same files again change nothing
    assert (await books.import_bank_csv(b, meta["second"], USER)).new_lines == 0
    assert len(await books.stored_bank_lines()) == meta["expected_unique_lines"]


# --------------------------------------------------------------------------- #
# c. supplier credit notes
# --------------------------------------------------------------------------- #


def _doc(g: dict, doc_type: str = "credit_note") -> ExtractedDoc:
    return ExtractedDoc(
        doc_type=doc_type,  # type: ignore[arg-type]
        supplier_name=g["supplier"]["name"],
        supplier_vat_number=g["supplier"].get("vat_number"),
        customer_name=g["customer"]["name"],
        invoice_number=g["credit_note_number"],
        date=g["date"],
        currency="GBP",
        lines=[
            ExtractedLine(
                description=ln["description"],
                qty=ln["qty"],
                unit_price=ln["unit_price"],
                net=ln["net"],
                vat_rate=ln["vat_rate"],
                vat=ln["vat"],
            )
            for ln in g["lines"]
        ],
        net_total=g["net_total"],
        vat_total=g["vat_total"],
        gross_total=g["gross_total"],
        payment_method=None,
        card_last4=None,
        category_guess="Materials",
        confidence=0.95,
    )


async def _post(books: Books, doc: ExtractedDoc):
    p = Proposal(
        id=uuid.uuid4().hex,
        doc_sha256=uuid.uuid4().hex * 2,
        extracted=doc,
        checks=[],
        status="proposed",
        reasons=[],
        suggested_filename="x.pdf",
        journal_draft=draft_journal(doc),
        model="stub",
        elapsed_s=0.0,
        created_at=now(),
    )
    await books.save_proposal(p)
    return await approve(books, p.id, USER)


def _quarter(d: date) -> tuple[date, date]:
    start_month = 3 * ((d.month - 1) // 3) + 1
    end_month = start_month + 2
    last = {3: 31, 6: 30, 9: 30, 12: 31}[end_month]
    return date(d.year, start_month, 1), date(d.year, end_month, last)


@pytest.mark.parametrize("path", _gold("credit_notes"), ids=lambda p: p.stem)
async def test_supplier_credit_note_nets_the_vat_return(path: Path, books: Books):
    g = json.loads(path.read_text(encoding="utf-8"))
    day = date.fromisoformat(g["date"])
    start, end = _quarter(day)
    # A bill of whole pounds in the same period, so the credit note's effect is a clean difference
    base = _doc(g, "purchase_invoice").model_copy(
        update={
            "invoice_number": "BASE-1",
            "lines": [ExtractedLine(description="Base", qty=1, unit_price=5000.0, net=5000.0, vat_rate=20, vat=1000.0)],
            "net_total": 5000.0,
            "vat_total": 1000.0,
            "gross_total": 6000.0,
        }
    )
    await _post(books, base)
    before = compute_vat_return(await books.list_events(), "q", start, end)

    cn = await _post(books, _doc(g))
    ev = await books.get_event(cn.event_id or "")
    assert ev.kind == "reversal" and ev.is_credit_note
    assert (ev.net, ev.vat) == (abs(_p(g["net_total"])), abs(_p(g["vat_total"])))

    after = compute_vat_return(await books.list_events(), "q", start, end)
    assert before.vat_reclaimed - after.vat_reclaimed == Decimal(abs(_p(g["vat_total"]))) / 100  # box 4
    assert before.total_purchases_ex_vat == 5000  # box 7 is whole pounds, rounded down
    assert after.total_purchases_ex_vat == (500_000 - abs(_p(g["net_total"]))) // 100
