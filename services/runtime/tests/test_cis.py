"""CIS and the VAT domestic reverse charge (app/cis.py, app/cis_readings.py, app/routes_cis.py) on fake storage, a fake
mailbox and a faked model. Every figure is integer pence, worked out on paper in the test. Sources: app/cis.py."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeMailSender, FakeStorageProvider
from accnomos_ledger.vat import compute_vat_return
from app import cis
from app import cis_readings as cr
from app import invoicing as inv_
from app import payments as pay_
from app.ai import cis_read
from app.ai.cis_read import CisReading
from app.ai.config import AiConfig
from app.books import Books
from app.invoicing import PROFILE, InvoiceDraft, InvoiceError, InvoiceProfile
from app.paths import INBOX
from app.pdf import render_invoice

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
PROFILE_JSON = {
    "name": "Sam Builds Ltd",
    "address": "1 High Street\nLeeds LS1 1AA",
    "vrn": "GB 123 4567 89",
    "bank": {"account_name": "Sam Builds Ltd", "sort_code": "12 34 56", "account_number": "12345678"},
}
CONTRACTOR = {
    "name": "Northgate Construction Ltd",
    "email": "accounts@northgate.example",
    "address": "2 Low Road\nYork",
    "vrn": "GB 987 6543 21",
}
LABOUR = {"description": "Second fix labour", "quantity": "20", "unit": "hours", "unit_price_pence": 5000}  # £1,000
TRAVEL = {"description": "Travel", "quantity": "1", "unit_price_pence": 5000}  # £50: CIS counts travel as labour
MATERIALS = {"description": "Cable and boxes", "quantity": "1", "unit_price_pence": 20000, "materials": True}  # £200


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
async def books(fake: FakeStorageProvider) -> Books:
    b = Books(fake)
    await b.write_json(PROFILE, InvoiceProfile.model_validate(PROFILE_JSON).model_dump(mode="json"))
    return b


@pytest.fixture
def sender() -> FakeMailSender:
    return FakeMailSender()


async def _subcontractor(books: Books, status: cis.Status = "net", **kw: Any) -> cis.CisSettings:
    return await cis.save_settings(books, cis.CisSettings(subcontractor=True, status=status, **kw), USER)


async def _contractor(books: Books) -> cis.CisSettings:
    return await cis.save_settings(
        books,
        cis.CisSettings(contractor=True, contractor_utr="1234567890", accounts_office_ref="123PA00045678"),
        USER,
    )


def _draft(lines: list[dict], **kw: Any) -> InvoiceDraft:
    return InvoiceDraft.model_validate({"customer": CONTRACTOR, "issue_date": "2026-10-20", "lines": lines, **kw})


async def _send(books: Books, sender: FakeMailSender, draft: InvoiceDraft) -> inv_.Invoice:
    inv = await inv_.create_invoice(books, draft, USER)
    return await inv_.send_invoice(books, sender, inv.number, USER, render_invoice(inv, await inv_.load_profile(books)))


def _pdf_text(data: bytes) -> str:
    doc = pdfium.PdfDocument(data)
    try:
        return "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
    finally:
        doc.close()


# --------------------------------------------------------------------------- rules


def test_rates_and_sources() -> None:
    assert cis.RATES == {"gross": 0, "net": 20, "unverified": 30}
    assert cis.SOURCE_URL.startswith("https://www.gov.uk/")
    assert "does not submit" in cis.NOT_SUBMITTED


def test_hmrc_worked_example_cisr61230() -> None:
    """CISR61230: payments £2,567.00 less materials £367.00 = £2,200; 20% is £440.00, 30% is £660.00."""
    liable = 256_700 - 36_700
    assert cis.deduction(liable, 20) == 44_000
    assert cis.deduction(liable, 30) == 66_000
    assert cis.deduction(liable, 0) == 0


def test_deduction_rounds_down_to_the_penny() -> None:
    assert cis.deduction(333, 20) == 66  # 66.6p -> 66p: never more than the rate
    assert cis.deduction(-100, 20) == 0


@pytest.mark.parametrize(
    ("day", "start", "end"),
    [
        (date(2026, 11, 5), date(2026, 10, 6), date(2026, 11, 5)),
        (date(2026, 11, 6), date(2026, 11, 6), date(2026, 12, 5)),
        (date(2026, 1, 3), date(2025, 12, 6), date(2026, 1, 5)),
        (date(2026, 12, 25), date(2026, 12, 6), date(2027, 1, 5)),
        (date(2026, 4, 6), date(2026, 4, 6), date(2026, 5, 5)),
    ],
)
def test_tax_months_run_6th_to_5th(day: date, start: date, end: date) -> None:
    assert cis.tax_month(day) == (start, end)


def test_deadlines_and_tax_year() -> None:
    end = date(2026, 6, 5)  # GOV.UK's example: the month to 5 June is due by 19 June
    assert cis.return_due(end) == date(2026, 6, 19)
    assert cis.payment_due(end) == date(2026, 6, 22)
    assert cis.tax_year_label(date(2026, 4, 5)) == "2025-26"
    assert cis.tax_year_label(date(2026, 4, 6)) == "2026-27"
    assert cis.tax_year_bounds("2026-27") == (date(2026, 4, 6), date(2027, 4, 5))
    with pytest.raises(cis.CisError):
        cis.tax_year_bounds("2026-28")
    with pytest.raises(cis.CisError):
        cis.tax_month_of_end(date(2026, 6, 6))


def test_settings_validate_utrs() -> None:
    assert cis.CisSettings(utr="12345 67890").utr == "1234567890"
    with pytest.raises(ValueError):
        cis.CisSettings(utr="12345")


# --------------------------------------------------------------------------- invoices and quotes


async def test_cis_invoice_deducts_on_labour_only_never_vat_or_materials(books: Books) -> None:
    await _subcontractor(books)
    inv = await inv_.create_invoice(books, _draft([LABOUR, TRAVEL, MATERIALS], cis=True), USER)
    # net 1,000 + 50 + 200 = 1,250; VAT 20% = 250; total 1,500
    assert (inv.net_pence, inv.vat_pence, inv.total_pence) == (125_000, 25_000, 150_000)
    assert inv.cis is not None
    assert inv.cis.labour_pence == 105_000 and inv.cis.materials_pence == 20_000
    assert inv.cis.deduction_pence == 21_000  # 20% of £1,050
    assert inv.cis.payable_pence == 129_000


async def test_cis_rate_follows_the_status(books: Books) -> None:
    await _subcontractor(books, "unverified")
    inv = await inv_.create_invoice(books, _draft([LABOUR], cis=True), USER)
    assert inv.cis and inv.cis.rate == 30 and inv.cis.deduction_pence == 30_000
    await _subcontractor(books, "gross")
    inv = await inv_.create_invoice(books, _draft([LABOUR], cis=True), USER)
    assert inv.cis and inv.cis.deduction_pence == 0 and inv.cis.payable_pence == inv.total_pence


async def test_cis_invoice_needs_cis_switched_on(books: Books) -> None:
    with pytest.raises(InvoiceError, match="Settings › CIS"):
        await inv_.create_invoice(books, _draft([LABOUR], cis=True), USER)
    with pytest.raises(InvoiceError, match="materials"):
        await inv_.create_invoice(books, _draft([LABOUR, MATERIALS]), USER)


async def test_reverse_charge_invoice_charges_no_vat_and_posts_net_only(books: Books, sender: FakeMailSender) -> None:
    cable = {k: v for k, v in MATERIALS.items() if k != "materials"}
    inv = await _send(books, sender, _draft([LABOUR, cable], reverse_charge=True))
    assert inv.reverse_charge and inv.vat_pence == 0 and inv.total_pence == 120_000
    assert inv.reverse_charge_vat_pence == 24_000  # the customer accounts for 20% of £1,200
    assert all(r.vat_pence == 0 for r in inv.vat_summary)
    events = await books.list_events()
    sale = next(e for e in events if e.kind == "sale")
    assert sale.vat == 0 and sale.reverse_charge_vat == 24_000 and sale.net == 120_000
    assert not any(ln.account.startswith("2200") for ln in sale.lines)
    ret = compute_vat_return(events, "26A4", date(2026, 10, 1), date(2026, 12, 31))
    assert ret.vat_due_sales == 0 and ret.total_sales_ex_vat == 1200  # box 6 only
    assert "reverse charge" in sender.sent[-1].body_text.lower()


async def test_reverse_charge_needs_vat_numbers_and_a_rated_line(books: Books, sender: FakeMailSender) -> None:
    no_vrn = {k: v for k, v in CONTRACTOR.items() if k != "vrn"}
    inv = await inv_.create_invoice(
        books, InvoiceDraft.model_validate({"customer": no_vrn, "lines": [LABOUR], "reverse_charge": True}), USER
    )
    problems = inv_.send_problems(inv, await inv_.load_profile(books), no_vrn["email"])
    assert any("customer's VAT number" in p for p in problems)
    zero = {**LABOUR, "vat_code": "Z"}
    with pytest.raises(InvoiceError, match="20% or 5%"):
        await inv_.create_invoice(books, _draft([zero], reverse_charge=True), USER)


async def test_reverse_charge_and_cis_together_on_the_pdf(books: Books) -> None:
    await _subcontractor(books)
    inv = await inv_.create_invoice(books, _draft([LABOUR, MATERIALS], cis=True, reverse_charge=True), USER)
    assert inv.cis and inv.cis.deduction_pence == 20_000 and inv.cis.payable_pence == 100_000
    text = _pdf_text(render_invoice(inv, await inv_.load_profile(books)))
    assert "Section 55A" in text and "Customer to pay the VAT to HMRC" in text
    assert "Payable after CIS" in text and "£1,000.00" in text and "(materials)" in text
    assert "£240.00" in text  # the VAT the customer accounts for


async def test_no_credit_note_against_a_reverse_charge_invoice(books: Books, sender: FakeMailSender) -> None:
    from app import credit_notes as cn_

    inv = await _send(books, sender, _draft([LABOUR], reverse_charge=True))
    with pytest.raises(InvoiceError, match="reverse charge"):
        await cn_.create_credit_note(books, inv.number, cn_.CreditNoteDraft(reason="x"), USER)


# --------------------------------------------------------------------------- paid net of the deduction


async def test_payment_net_of_cis_settles_the_invoice_in_full(books: Books, sender: FakeMailSender) -> None:
    await _subcontractor(books)
    inv = await _send(books, sender, _draft([LABOUR, MATERIALS], cis=True))
    assert inv.cis and inv.cis.deduction_pence == 20_000 and inv.total_pence == 144_000
    rec = await pay_.record_payment(
        books,
        pay_.PaymentIn(
            side="sale",
            date=date(2026, 11, 2),
            amount_pence=124_000,  # what reached the bank
            cis_deduction_pence=20_000,
            allocations=[pay_.AllocationIn(event_id=inv.event_id or "", amount_pence=144_000)],
        ),
        USER,
    )
    assert rec.amount_pence == 144_000 and rec.cis_deduction_pence == 20_000
    ev = await books.get_event(rec.event_id or "")
    assert {(ln.account, ln.debit, ln.credit) for ln in ev.lines} == {
        ("1200 Bank", 124_000, 0),
        (cis.CIS_SUFFERED, 20_000, 0),
        ("1100 Debtors", 0, 144_000),
    }
    m = pay_.invoice_money(await inv_.get_invoice(books, inv.number), await pay_.load_ledger(books))
    assert m and m.payment_status == "paid" and m.balance_pence == 0
    # the bank line to match is the money, not the settled amount
    me = pay_.money_events(await pay_.load_ledger(books))[ev.id]
    assert me.bank_pence == 124_000
    # removing it reverses the deduction too
    await pay_.remove_payment(books, rec.id, USER)
    events = await books.list_events()
    assert sum(cis.suffered_in(events, date(2026, 10, 6), date(2026, 11, 5)).values()) == 0


async def test_cis_deduction_is_capped_and_needs_a_cis_invoice(books: Books, sender: FakeMailSender) -> None:
    await _subcontractor(books)
    inv = await _send(books, sender, _draft([LABOUR], cis=True))
    plain = await _send(books, sender, _draft([LABOUR]))

    def body(event_id: str, cut: int) -> pay_.PaymentIn:
        return pay_.PaymentIn(
            side="sale",
            date=date(2026, 11, 2),
            amount_pence=inv.total_pence - cut,
            cis_deduction_pence=cut,
            allocations=[pay_.AllocationIn(event_id=event_id, amount_pence=inv.total_pence)],
        )

    with pytest.raises(pay_.PaymentError, match="30%"):
        await pay_.record_payment(books, body(inv.event_id or "", 30_001), USER)
    with pytest.raises(pay_.PaymentError, match="CIS invoice"):
        await pay_.record_payment(books, body(plain.event_id or "", 20_000), USER)
    ok = await pay_.record_payment(books, body(inv.event_id or "", 30_000), USER)  # the higher rate is allowed
    assert ok.cis_deduction_pence == 30_000


# --------------------------------------------------------------------------- statements and the year


def _statement(**kw: Any) -> cis.StatementIn:
    base = {
        "contractor_name": "Northgate Construction Ltd",
        "tax_month_end": "2026-11-05",
        "gross_pence": 120_000,
        "materials_pence": 20_000,
        "deduction_pence": 20_000,
    }
    return cis.StatementIn.model_validate({**base, **kw})


async def test_statement_checks(books: Books) -> None:
    settings = await _subcontractor(books, utr="1234567890")
    assert all(c.ok for c in cis.statement_checks(_statement(), settings))
    thirty = cis.statement_checks(_statement(deduction_pence=30_000), settings)
    assert any(c.code == "RATE" and not c.ok and "30%" in c.message for c in thirty)
    odd = cis.statement_checks(_statement(deduction_pence=12_345, tax_month_end="2026-11-04"), settings)
    assert {c.code for c in odd if not c.ok} == {"RATE", "TAX_MONTH"}
    other = cis.statement_checks(_statement(subcontractor_utr="9999999999"), settings)
    assert any(c.code == "UTR" and not c.ok for c in other)
    with pytest.raises(ValueError):
        _statement(materials_pence=130_000)
    with pytest.raises(ValueError):
        _statement(deduction_pence=100_001)


async def test_statements_reconcile_against_recorded_deductions(books: Books, sender: FakeMailSender) -> None:
    settings = await _subcontractor(books)
    inv = await _send(books, sender, _draft([LABOUR, MATERIALS], cis=True))
    await pay_.record_payment(
        books,
        pay_.PaymentIn(
            side="sale",
            date=date(2026, 11, 2),
            amount_pence=124_000,
            cis_deduction_pence=20_000,
            allocations=[pay_.AllocationIn(event_id=inv.event_id or "", amount_pence=144_000)],
        ),
        USER,
    )
    await cis.add_statement(books, _statement(), USER)
    with pytest.raises(cis.CisError, match="already in"):
        await cis.add_statement(books, _statement(), USER)
    [view] = cis.statement_views(await cis.statements(books), await books.list_events(), settings)
    assert view.recorded_pence == 20_000 and view.difference_pence == 0
    assert view.liable_pence == 100_000 and view.net_paid_pence == 100_000


async def test_year_totals_for_the_tax_return(books: Books, sender: FakeMailSender) -> None:
    settings = await _subcontractor(books)
    await cis.add_statement(books, _statement(), USER)
    await cis.add_statement(
        books,
        _statement(tax_month_end="2026-12-05", gross_pence=50_000, materials_pence=0, deduction_pence=10_000),
        USER,
    )
    await cis.add_statement(
        books,
        _statement(
            contractor_name="Other Build Ltd",
            tax_month_end="2026-04-05",
            gross_pence=10_000,
            materials_pence=0,
            deduction_pence=2_000,
        ),
        USER,
    )
    y = cis.year_totals("2026-27", await cis.statements(books), [], settings, [])
    assert (y.gross_pence, y.materials_pence, y.deduction_pence) == (170_000, 20_000, 30_000)  # April 5 is 2025-26
    assert [c.contractor_name for c in y.by_contractor] == ["Northgate Construction Ltd"]
    assert "box 38 is £300.00" in y.where_it_goes[0] and "box 81 is £300.00" in y.where_it_goes[1]
    assert y.difference_pence == 30_000  # nothing recorded in the books yet
    company = cis.year_totals(
        "2026-27", await cis.statements(books), [], settings.model_copy(update={"entity": "company"}), []
    )
    assert "Employer Payment Summary" in company.where_it_goes[0] and "Corporation" in company.where_it_goes[0]
    # a deduction recorded with no statement for its month is flagged
    inv = await _send(books, sender, _draft([LABOUR], cis=True, issue_date="2027-01-10"))
    await pay_.record_payment(
        books,
        pay_.PaymentIn(
            side="sale",
            date=date(2027, 1, 20),
            amount_pence=inv.total_pence - 20_000,
            cis_deduction_pence=20_000,
            allocations=[pay_.AllocationIn(event_id=inv.event_id or "", amount_pence=inv.total_pence)],
        ),
        USER,
    )
    y = cis.year_totals("2026-27", await cis.statements(books), await books.list_events(), settings, [])
    assert y.months_missing == ["2027-02-05"] and y.recorded_pence == 20_000


# --------------------------------------------------------------------------- the AI proposes, the user approves


class _Resp:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> Any:
        return self._payload


class _Client:
    reply: dict[str, Any] = {}
    seen: list[dict[str, Any]] = []

    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *a: Any) -> None:
        pass

    async def post(self, url: str, **kw: Any) -> _Resp:
        _Client.seen.append({"url": url, **kw})
        return _Resp(_Client.reply)


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> type[_Client]:
    _Client.seen = []
    monkeypatch.setattr(cis_read.httpx, "AsyncClient", _Client)
    return _Client


def _ollama(obj: dict[str, Any]) -> dict[str, Any]:
    full = {k: None for k in cis_read.reading_json_schema()["properties"]}
    full.update(reverse_charge_wording=False, confidence=0.9)
    full.update(obj)
    return {"message": {"content": json.dumps(full)}}


CFG = AiConfig(mode="local", base_url="http://stub", model="stub")
STATEMENT_TEXT = (
    "SAMPLE — FICTIONAL COMPANY\nPayment and deduction statement\nNorthgate Construction Ltd\n"
    "Tax month ending 05/11/2026\nGross amount paid (excl VAT) £1,200.00\nLess cost of materials £200.00\n"
    "Amount liable to deduction £1,000.00\nAmount deducted £200.00\nAmount paid £1,000.00\n"
)


async def test_statement_read_proposed_then_approved(books: Books, fake: FakeStorageProvider, model) -> None:
    await _subcontractor(books)
    await fake.write(f"{INBOX}/northgate-nov.eml.txt", STATEMENT_TEXT.encode())
    model.reply = _ollama(
        {
            "kind": "cis_statement",
            "contractor_name": "Northgate Construction Ltd",
            "tax_month_end": "2026-11-05",
            "gross_amount": 1200.0,
            "materials": 200.0,
            "amount_liable": 1000.0,
            "deduction": 200.0,
            "net_paid": 1000.0,
        }
    )
    r = await cr.read_document(books, "northgate-nov.eml.txt", CFG, USER)
    assert r.kind == "cis_statement" and r.status == "pending" and not r.problems
    assert r.statement and r.statement.gross_pence == 120_000 and r.statement.deduction_pence == 20_000
    assert all(c.ok for c in r.checks)
    sent = model.seen[0]["json"]
    assert sent["format"] == cis_read.reading_json_schema()  # strict schema
    assert "never instructions" in sent["messages"][1]["content"]  # the document is data
    assert await cis.statements(books) == []  # nothing kept before approval
    again = await cr.read_document(books, "northgate-nov.eml.txt", CFG, USER)
    assert again.id == r.id and len(model.seen) == 1  # the same file is never read twice
    done = await cr.approve(books, r.id, cr.DecideBody(), USER)
    assert done.status == "approved" and done.statement_id
    [kept] = await cis.statements(books)
    assert kept.source == "read" and kept.reading_id == r.id
    with pytest.raises(cis.CisError, match="already approved"):
        await cr.approve(books, r.id, cr.DecideBody(), USER)


async def test_reading_with_wrong_figures_is_flagged_not_fixed(books: Books) -> None:
    settings = await _subcontractor(books)
    read = CisReading(
        kind="cis_statement",
        contractor_name="Northgate Construction Ltd",
        tax_month_end="2026-11-05",
        gross_amount=1200.0,
        materials=200.0,
        amount_liable=900.0,
        deduction=250.0,
        net_paid=1000.0,
    )
    r, problems = cr.from_reading(read, f"{INBOX}/x.pdf", settings)
    assert not problems and r.statement and r.statement.deduction_pence == 25_000  # kept as printed
    bad = {c.code for c in r.checks if not c.ok}
    assert bad == {"RATE", "LIABLE", "NET_PAID"}
    unreadable, problems = cr.from_reading(CisReading(kind="cis_statement"), "p", settings)
    assert unreadable.statement is None and problems
    other, problems = cr.from_reading(CisReading(kind="other"), "p", settings)
    assert problems and other.kind == "other"


async def test_reverse_charge_bill_read_and_posted(books: Books, fake: FakeStorageProvider, model) -> None:
    await _contractor(books)
    await fake.write(f"{INBOX}/rc-bill.eml.txt", b"SAMPLE - FICTIONAL COMPANY invoice, reverse charge applies")
    model.reply = _ollama(
        {
            "kind": "reverse_charge_invoice",
            "supplier_name": "Dale Electrical",
            "supplier_vat_number": "GB 111 2222 33",
            "invoice_number": "DE-104",
            "invoice_date": "2026-11-02",
            "net": 2500.0,
            "vat_rate": 20,
            "reverse_charge_vat": 500.0,
            "reverse_charge_wording": True,
        }
    )
    r = await cr.read_document(books, "rc-bill.eml.txt", CFG, USER)
    assert r.bill and r.bill.net_pence == 250_000 and r.bill.reverse_charge_vat_pence == 50_000
    assert all(c.ok for c in r.checks)
    done = await cr.approve(books, r.id, cr.DecideBody(), USER)
    ev = await books.get_event(done.event_id or "")
    assert ev.kind == "purchase" and ev.vat == 0 and ev.reverse_charge_vat == 50_000 and ev.evidence == [r.sha256]
    ret = compute_vat_return(await books.list_events(), "26A4", date(2026, 10, 1), date(2026, 12, 31))
    assert str(ret.vat_due_sales) == "500.00" and str(ret.vat_reclaimed) == "500.00"
    assert ret.total_purchases_ex_vat == 2500 and ret.total_sales_ex_vat == 0


async def test_rejected_reading_keeps_nothing(books: Books) -> None:
    settings = await _subcontractor(books)
    r, _ = cr.from_reading(CisReading(kind="other"), f"{INBOX}/a.pdf", settings)
    await cr.save_reading(books, r)
    with pytest.raises(cis.CisError, match="reject"):
        await cr.approve(books, r.id, cr.DecideBody(), USER)
    out = await cr.reject(books, r.id, USER)
    assert out.status == "rejected" and await books.list_events() == []
    with pytest.raises(FileNotFoundError):
        await cr.get_reading(books, "../../etc")


def test_bill_checks_flag_missing_wording_and_wrong_vat() -> None:
    b = cr.ReverseChargeBillIn(supplier_name="X", invoice_date=date(2026, 11, 2), net_pence=100_000)
    checks = {c.code: c.ok for c in cr.bill_checks(b, 19_000, False)}
    assert checks == {"RC_WORDING": False, "SUPPLIER_VRN": False, "RC_VAT": False}


# --------------------------------------------------------------------------- contractor side and the CIS300


SUB = {"name": "Dale Electrical", "utr": "1111122222", "status": "net", "vat_registered": True}


async def test_subcontractors_validate(books: Books) -> None:
    await _contractor(books)
    s = await cis.save_subcontractor(books, cis.SubcontractorIn.model_validate(SUB), USER)
    with pytest.raises(cis.CisError, match="UTR"):
        await cis.save_subcontractor(books, cis.SubcontractorIn.model_validate(SUB), USER)
    with pytest.raises(ValueError):
        cis.SubcontractorIn.model_validate({**SUB, "utr": "123"})
    with pytest.raises(ValueError):
        cis.SubcontractorIn.model_validate({**SUB, "verification_number": "nope"})
    edited = await cis.save_subcontractor(
        books, cis.SubcontractorIn.model_validate({**SUB, "status": "gross"}), USER, s.id
    )
    assert edited.id == s.id and edited.status == "gross" and len(await cis.subcontractors(books)) == 1


async def test_paying_a_subcontractor_under_the_reverse_charge(books: Books) -> None:
    await _contractor(books)
    s = await cis.save_subcontractor(books, cis.SubcontractorIn.model_validate(SUB), USER)
    p = await cis.record_contractor_payment(
        books,
        cis.ContractorPaymentIn(
            subcontractor_id=s.id, date=date(2026, 10, 20), gross_pence=100_000, materials_pence=20_000
        ),
        USER,
    )
    # 20% of (£1,000 - £200) = £160 deducted; no VAT paid (reverse charge); £840 paid
    assert (p.deduction_pence, p.vat_pence, p.paid_pence) == (16_000, 20_000, 84_000)
    ev = await books.get_event(p.event_id or "")
    assert {(ln.account, ln.debit, ln.credit) for ln in ev.lines} == {
        (cis.SUBCONTRACTORS_ACCOUNT, 100_000, 0),
        ("1200 Bank", 0, 84_000),
        (cis.CIS_OWED, 0, 16_000),
    }
    events = await books.list_events()
    ret = compute_vat_return(events, "26A4", date(2026, 10, 1), date(2026, 12, 31))
    assert (
        str(ret.vat_due_sales) == "200.00" and str(ret.vat_reclaimed) == "200.00" and ret.total_purchases_ex_vat == 1000
    )
    assert cis.owed_to_hmrc(events, date(2026, 11, 5)) == 16_000


async def test_standard_vat_and_unverified_subcontractors(books: Books) -> None:
    await _contractor(books)
    s = await cis.save_subcontractor(books, cis.SubcontractorIn.model_validate(SUB), USER)
    p = await cis.record_contractor_payment(
        books,
        cis.ContractorPaymentIn(
            subcontractor_id=s.id, date=date(2026, 10, 20), gross_pence=100_000, vat_treatment="standard"
        ),
        USER,
    )
    assert (p.deduction_pence, p.vat_pence, p.paid_pence) == (20_000, 20_000, 100_000)  # £1,000 + £200 VAT - £200
    u = await cis.save_subcontractor(
        books,
        cis.SubcontractorIn.model_validate(
            {**SUB, "utr": "3333344444", "status": "unverified", "vat_registered": False}
        ),
        USER,
    )
    body = cis.ContractorPaymentIn(
        subcontractor_id=u.id, date=date(2026, 10, 21), gross_pence=50_000, vat_treatment="none"
    )
    with pytest.raises(cis.CisError, match="verification number"):
        await cis.record_contractor_payment(books, body, USER)
    await cis.save_subcontractor(
        books,
        cis.SubcontractorIn.model_validate(
            {
                **SUB,
                "utr": "3333344444",
                "status": "unverified",
                "vat_registered": False,
                "verification_number": "V1234567890AB",
            }
        ),
        USER,
        u.id,
    )
    q = await cis.record_contractor_payment(books, body, USER)
    assert q.rate == 30 and q.deduction_pence == 15_000 and q.paid_pence == 35_000
    with pytest.raises(cis.CisError, match="No VAT"):
        await cis.record_contractor_payment(books, body.model_copy(update={"vat_treatment": "standard"}), USER)


async def test_paying_a_bill_already_in_the_books_settles_it(books: Books) -> None:
    await _contractor(books)
    s = await cis.save_subcontractor(books, cis.SubcontractorIn.model_validate(SUB), USER)
    bill = cr.ReverseChargeBillIn(
        supplier_name="Dale Electrical",
        supplier_vat_number="GB111222233",
        invoice_number="DE-1",
        invoice_date=date(2026, 10, 15),
        net_pence=100_000,
    )
    bill_id = await cr.post_bill(books, bill, USER, cr.typed_bill_key(bill), [])
    p = await cis.record_contractor_payment(
        books,
        cis.ContractorPaymentIn(
            subcontractor_id=s.id, date=date(2026, 10, 20), gross_pence=100_000, bill_event_id=bill_id
        ),
        USER,
    )
    assert p.payment_record_id and p.paid_pence == 80_000 and p.deduction_pence == 20_000
    ledger = await pay_.load_ledger(books)
    assert ledger.settlement().outstanding(bill_id) == 0
    ev = await books.get_event(p.event_id or "")
    assert {(ln.account, ln.debit, ln.credit) for ln in ev.lines} == {
        ("2100 Creditors", 100_000, 0),
        ("1200 Bank", 0, 80_000),
        (cis.CIS_OWED, 0, 20_000),
    }
    # the bill's reverse-charge VAT was counted once, on the bill
    ret = compute_vat_return(await books.list_events(), "26A4", date(2026, 10, 1), date(2026, 12, 31))
    assert str(ret.vat_due_sales) == "200.00" and ret.total_purchases_ex_vat == 1000
    removed = await cis.remove_contractor_payment(books, p.id, USER)
    assert removed.removed_at and (await pay_.load_ledger(books)).settlement().outstanding(bill_id) == 100_000


async def test_monthly_return_and_its_file(books: Books, fake: FakeStorageProvider) -> None:
    settings = await _contractor(books)
    a = await cis.save_subcontractor(books, cis.SubcontractorIn.model_validate(SUB), USER)
    b = await cis.save_subcontractor(
        books,
        cis.SubcontractorIn.model_validate(
            {"name": "=Bad Name", "utr": "5555566666", "status": "unverified", "verification_number": "V0000000001AB"}
        ),
        USER,
    )
    for day, gross, mat in ((date(2026, 10, 6), 100_000, 20_000), (date(2026, 11, 5), 50_000, 0)):
        await cis.record_contractor_payment(
            books,
            cis.ContractorPaymentIn(subcontractor_id=a.id, date=day, gross_pence=gross, materials_pence=mat),
            USER,
        )
    await cis.record_contractor_payment(
        books,
        cis.ContractorPaymentIn(
            subcontractor_id=b.id, date=date(2026, 10, 30), gross_pence=10_000, vat_treatment="none"
        ),
        USER,
    )
    outside = await cis.record_contractor_payment(
        books, cis.ContractorPaymentIn(subcontractor_id=a.id, date=date(2026, 11, 6), gross_pence=99_900), USER
    )
    ret = cis.monthly_return(date(2026, 11, 5), settings, await cis.contractor_payments(books))
    assert ret.tax_month_start == date(2026, 10, 6) and ret.return_due == date(2026, 11, 19)
    assert not ret.nil_return and not ret.problems
    by = {ln.utr: ln for ln in ret.lines}
    assert (by["1111122222"].total_payments_pence, by["1111122222"].materials_pence) == (150_000, 20_000)
    assert by["1111122222"].deduction_pence == 16_000 + 10_000 and by["1111122222"].verification_number is None
    assert by["5555566666"].deduction_pence == 3_000 and by["5555566666"].verification_number == "V0000000001AB"
    assert ret.total_deductions_pence == 29_000
    text = cis.return_csv(ret)
    assert "NOT submitted to HMRC" in text and "'=Bad Name" in text and "1500.00" in text
    paths = await cis.export_return(books, ret, USER)
    saved = (await fake.read(paths[0])).decode("utf-8-sig")
    assert saved == text and json.loads(await fake.read(paths[1]))["total_deductions_pence"] == 29_000
    await cis.remove_contractor_payment(books, outside.id, USER)
    nil = cis.monthly_return(date(2026, 12, 5), settings, await cis.contractor_payments(books))
    assert nil.nil_return and nil.lines == []
    with pytest.raises(cis.CisError, match="already removed"):
        await cis.remove_contractor_payment(books, outside.id, USER)


async def test_contractor_side_needs_switching_on(books: Books) -> None:
    await _subcontractor(books)
    with pytest.raises(cis.CisError, match="Settings › CIS"):
        await cis.record_contractor_payment(
            books, cis.ContractorPaymentIn(subcontractor_id="x", date=date(2026, 10, 20), gross_pence=1), USER
        )
    no_refs = cis.monthly_return(date(2026, 11, 5), cis.CisSettings(contractor=True), [])
    assert len(no_refs.problems) == 2


# --------------------------------------------------------------------------- routes


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


def test_routes_end_to_end(client: TestClient, books: Books) -> None:
    r = client.get("/cis?today=2026-11-10", headers=H)
    assert r.status_code == 200 and r.json()["settings"]["subcontractor"] is False
    assert r.json()["tax_month"]["tax_month_end"] == "2026-12-05"
    assert r.json()["last_tax_month"]["return_due"] == "2026-11-19"
    r = client.put(
        "/cis/settings",
        headers=H,
        json={
            "subcontractor": True,
            "status": "net",
            "contractor": True,
            "contractor_utr": "1234567890",
            "accounts_office_ref": "123PA00045678",
        },
    )
    assert r.status_code == 200, r.text
    assert client.put("/cis/settings", headers=H, json={"utr": "1"}).status_code == 422
    r = client.post("/cis/statements", headers=H, json=_statement().model_dump(mode="json"))
    assert r.status_code == 200, r.text
    assert client.post("/cis/statements", headers=H, json=_statement().model_dump(mode="json")).status_code == 400
    views = client.get("/cis/statements", headers=H).json()
    assert views[0]["difference_pence"] == 20_000
    y = client.get("/cis/year?tax_year=2026-27", headers=H).json()
    assert y["deduction_pence"] == 20_000
    assert client.get("/cis/year?tax_year=bad", headers=H).status_code == 400
    sub = client.post("/cis/subcontractors", headers=H, json=SUB).json()
    r = client.post(
        "/cis/payments",
        headers=H,
        json={"subcontractor_id": sub["id"], "date": "2026-10-20", "gross_pence": 100_000, "materials_pence": 20_000},
    )
    assert r.status_code == 200, r.text
    ret = client.get("/cis/returns/2026-11-05", headers=H).json()
    assert ret["total_deductions_pence"] == 16_000 and ret["owed_to_hmrc_pence"] == 16_000 and not ret["sample"]
    assert client.get("/cis/returns/2026-11-06", headers=H).status_code == 400
    exp = client.post("/cis/returns/2026-11-05/export", headers=H).json()
    assert exp["paths"][0].endswith("CIS300 2026-11-05.csv")
    q = client.post(
        "/cis/quote",
        headers=H,
        json={"draft": {"customer": CONTRACTOR, "issue_date": "2026-10-20", "lines": [LABOUR, MATERIALS], "cis": True}},
    )
    assert q.status_code == 200 and q.headers["content-type"] == "application/pdf"
    text = _pdf_text(q.content)
    assert "QUOTE" in text and "Valid until" in text and "Payable after CIS" in text
    assert q.headers["x-quote-path"].startswith("03 Sales/quotes/Q-20261020-")
    guide = client.get("/cis/reverse-charge").json()
    assert "box 6" in guide["boxes_supplier"] and "section 55A" in guide["end_user_wording"]
    bill = {
        "supplier_name": "Dale Electrical",
        "invoice_date": "2026-11-02",
        "net_pence": 10_000,
        "invoice_number": "D1",
    }
    first = client.post("/cis/reverse-charge/bills", headers=H, json=bill).json()
    again = client.post("/cis/reverse-charge/bills", headers=H, json=bill).json()
    assert first["event_id"] == again["event_id"] and first["reverse_charge_vat_pence"] == 2_000
    assert client.post("/cis/read", headers=H, json={"name": "../x"}).status_code == 404
    assert client.get("/cis/readings", headers=H).json() == []
    assert client.post("/cis/readings/0123456789abcdef/approve", headers=H, json={}).status_code == 404
    pay_id = client.get("/cis/payments", headers=H).json()[0]["id"]
    assert client.delete(f"/cis/payments/{pay_id}", headers=H).json()["removed_at"]
    st_id = views[0]["statement"]["id"]
    assert client.delete(f"/cis/statements/{st_id}", headers=H).status_code == 200
    assert client.delete(f"/cis/statements/{st_id}", headers=H).status_code == 404


def test_writes_need_a_user(client: TestClient) -> None:
    assert client.put("/cis/settings", headers={"X-Graph-Token": "tok"}, json={}).status_code in (400, 401)


def test_invoice_record_payment_route_takes_the_cis_deduction(client: TestClient, books: Books) -> None:
    client.put("/cis/settings", headers=H, json={"subcontractor": True, "status": "net"})
    body = {"customer": CONTRACTOR, "issue_date": "2026-10-20", "lines": [LABOUR, MATERIALS], "cis": True}
    inv = client.post("/invoices", headers=H, json=body).json()
    assert inv["cis"]["deduction_pence"] == 20_000
    r = client.post(f"/invoices/{inv['number']}/send", headers=H, json={"confirm": True})
    assert r.status_code == 200, r.text
    r = client.post(f"/invoices/{inv['number']}/payments", headers=H, json={"cis_deduction_pence": 20_000})
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["status"] == "paid" and row["money"]["balance_pence"] == 0
    [p] = row["money"]["payments"]
    assert p["amount_pence"] == 144_000 and p["cis_deduction_pence"] == 20_000 and "net of CIS" in p["description"]
