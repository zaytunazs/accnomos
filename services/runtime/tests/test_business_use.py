"""Business-use percent: only the business share stays on the expense account, VAT reclaimed on it alone.

The rest is personal spending to Drawings (sole trader) or the Director's loan (company): pence, with
the parts adding up exactly to the totals and the draft still balancing.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app.approve import ApprovalError, apply_edits
from app.books import Books
from app.invoicing import InvoiceProfile, save_profile
from app.journal import DRAWINGS, OWNER_LOAN, VAT_CONTROL, draft_journal, is_balanced, split_business_use
from app.schemas import ExtractedDoc, ExtractedLine, JournalLine, Proposal

USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}

CSV = (
    "Date,Description,Reference,Amount (GBP),Balance (GBP)\n"
    "2026-10-21,02 Mobile,phone bill,-120.00,1000.00\n"
)


@pytest.fixture
async def books() -> Books:
    return Books(FakeStorageProvider())


@pytest.fixture
def client(books: Books):
    from app.main import app
    from app.routes_books import get_books

    async def override() -> Books:
        return books

    app.dependency_overrides[get_books] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _receipt(net: float, vat: float, gross: float, **kw: object) -> ExtractedDoc:
    base: dict[str, object] = dict(
        doc_type="receipt",
        supplier_name="02 Mobile",
        supplier_vat_number="GB 123 4567 89",
        customer_name=None,
        invoice_number=None,
        date="2026-10-21",
        currency="GBP",
        lines=[ExtractedLine(description="Phone", qty=1, unit_price=gross, net=net, vat_rate=20, vat=vat)],
        net_total=net,
        vat_total=vat,
        gross_total=gross,
        payment_method="card",
        card_last4=None,
        category_guess="Telephone & internet",
        confidence=0.9,
    )
    base.update(kw)
    return ExtractedDoc.model_validate(base)


def _proposal(doc: ExtractedDoc) -> Proposal:
    return Proposal(
        id=uuid.uuid4().hex,
        doc_sha256="ab" * 32,
        extracted=doc,
        checks=[],
        status="proposed",
        reasons=[],
        suggested_filename="phone",
        journal_draft=draft_journal(doc),
        model="test",
        elapsed_s=0.0,
    )


async def _approve_direct(books: Books, doc: ExtractedDoc, edits: dict) -> Proposal:
    from app.approve import approve

    p = _proposal(doc)
    await books.save_proposal(p)
    return await approve(books, p.id, USER, edits)


async def test_sixty_percent_splits_net_and_reclaims_vat_only_on_it(books: Books) -> None:
    """Phone £100 net + £20 VAT at 60 %: £60 expense, £12 VAT, £48 Drawings, £120 bank."""
    posted = await _approve_direct(books, _receipt(100.0, 20.0, 120.0), {"business_use_percent": 60})
    assert posted.status == "posted"
    by_account = {j.account: j for j in posted.journal_draft}
    assert by_account["7550 Telephone & internet"].debit_pence == 6000
    assert by_account[VAT_CONTROL].debit_pence == 1200
    assert by_account[DRAWINGS].debit_pence == 4800
    assert by_account["1200 Bank"].credit_pence == 12000
    assert is_balanced(posted.journal_draft)


async def test_no_vat_number_folds_unreclaimed_vat_into_drawings(books: Books) -> None:
    """Code N: the VAT is part of the cost, so the private share takes its slice of the gross."""
    doc = _receipt(100.0, 20.0, 120.0, supplier_vat_number=None)
    posted = await _approve_direct(books, doc, {"business_use_percent": 60})
    by_account = {j.account: j for j in posted.journal_draft}
    assert VAT_CONTROL not in by_account
    assert by_account["7550 Telephone & internet"].debit_pence == 7200
    assert by_account[DRAWINGS].debit_pence == 4800
    assert by_account["1200 Bank"].credit_pence == 12000


async def test_rounding_parts_add_up_exactly() -> None:
    """Across every percent, the pence shares add up exactly to the totals and balance."""
    doc = _receipt(10.01, 2.0, 12.01)
    journal = draft_journal(doc)
    for percent in range(0, 101):
        split = split_business_use(journal, percent, DRAWINGS)
        assert is_balanced(split), percent
        assert sum(j.debit_pence for j in split) == 1201, percent
        vat = sum(j.debit_pence for j in split if j.account == VAT_CONTROL)
        assert vat == (200 * percent + 50) // 100, (percent, vat)


async def test_zero_percent_posts_everything_to_drawings(books: Books) -> None:
    posted = await _approve_direct(books, _receipt(100.0, 20.0, 120.0), {"business_use_percent": 0})
    accounts = {j.account for j in posted.journal_draft}
    assert accounts == {DRAWINGS, "1200 Bank"}


async def test_company_percent_posts_remainder_to_directors_loan(books: Books) -> None:
    await save_profile(books, InvoiceProfile(name="Acme Ltd", company_number="12345678"), USER)
    posted = await _approve_direct(books, _receipt(100.0, 20.0, 120.0), {"business_use_percent": 60})
    by_account = {j.account: j for j in posted.journal_draft}
    assert by_account[OWNER_LOAN].debit_pence == 4800
    assert DRAWINGS not in by_account


async def test_bad_percents_are_refused(books: Books) -> None:
    for bad in (101, -1, 60.5, True, "60"):
        p = _proposal(_receipt(100.0, 20.0, 120.0))
        with pytest.raises(ApprovalError):
            apply_edits(p, {"business_use_percent": bad})


async def test_sales_cannot_have_business_use(books: Books) -> None:
    doc = _receipt(100.0, 20.0, 120.0, doc_type="sales_invoice", customer_name="A customer")
    p = _proposal(doc)
    await books.save_proposal(p)
    with pytest.raises(ApprovalError):
        from app.approve import approve

        await approve(books, p.id, USER, {"business_use_percent": 60})


def _import(client: TestClient) -> None:
    r = client.post("/books/bank/import", headers=H, files={"file": ("statement.csv", CSV, "text/csv")})
    assert r.status_code == 200, r.text


def test_bank_line_expense_with_business_use(client: TestClient) -> None:
    """A bank rule coding approved with 60 % claims £72 and puts £48 to Drawings (no VAT number on a line)."""
    _import(client)
    r = client.post(
        "/books/bank/rules",
        headers=H,
        json={
            "name": "phone",
            "match": {"op": "contains", "value": "02 mobile"},
            "direction": "out",
            "action": {"account": "7550 Telephone & internet", "vat_code": "S"},
        },
    )
    assert r.status_code == 201, r.text
    lines = client.get("/books/bank/lines", headers=H).json()
    line = next(ln for ln in lines if ln["amount_pence"] < 0)
    r = client.post(f"/books/bank/lines/{line['id']}/approve", headers=H, json={"kind": "rule", "business_use_percent": 60})
    assert r.status_code == 200, r.text
    proposal_id = r.json()["proposal_id"]
    proposal = client.get(f"/books/proposals/{proposal_id}", headers=H).json()
    by_account = {j["account"]: j for j in proposal["journal_draft"]}
    assert by_account["7550 Telephone & internet"]["debit_pence"] == 7200
    assert by_account[DRAWINGS]["debit_pence"] == 4800
    assert by_account["1200 Bank"]["credit_pence"] == 12000


def test_bank_line_exact_match_with_business_use_is_refused(client: TestClient) -> None:
    _import(client)
    lines = client.get("/books/bank/lines", headers=H).json()
    line = next(ln for ln in lines if ln["amount_pence"] < 0)
    r = client.post(f"/books/bank/lines/{line['id']}/approve", headers=H, json={"kind": "exact", "business_use_percent": 60})
    assert r.status_code == 400, r.text


def _journal(accounts: list[tuple[str, int]]) -> list[JournalLine]:
    """A purchase journal from (account, debit pence) legs plus the balancing bank credit."""
    legs = [JournalLine(account=a, debit_pence=d) for a, d in accounts]
    legs.append(JournalLine(account="1200 Bank", credit_pence=sum(d for _, d in accounts)))
    return legs


def test_split_largest_remainder_across_lines() -> None:
    """Three £1.01 lines at 33 %: shares of 33/33/34... in some order, totalling £1.00."""
    journal = _journal([("5000 Materials", 101), ("5000 Materials", 101), ("5000 Materials", 101)])
    split = split_business_use(journal, 33, DRAWINGS)
    business = sorted(j.debit_pence for j in split if j.account == "5000 Materials")
    assert business == [33, 33, 34]
    assert sum(j.debit_pence for j in split) == 303
