"""Part payments, one payment for several documents, overpayments and credit notes (app/settlement.py,
app/payments.py, app/credit_notes.py) against fake storage and a fake mailbox. Every figure is pence, by code."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeMailSender, FakeStorageProvider
from accnomos_ledger.vat import compute_vat_return
from app import contacts as cb
from app import credit_notes as cn_
from app import invoicing as inv_
from app import payments as pay_
from app.approve import approve, undo
from app.books import Books, now
from app.credit_notes import CreditLineIn, CreditNoteDraft
from app.invoicing import PROFILE, InvoiceDraft, InvoiceError, InvoiceProfile, InvoiceStateError
from app.journal import draft_journal
from app.pdf import render_invoice
from app.schemas import ExtractedDoc, ExtractedLine, Proposal

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
PROFILE_JSON = {
    "name": "Sam Builds Ltd",
    "address": "1 High Street\nLeeds LS1 1AA",
    "vrn": "GB 123 4567 89",
    "bank": {"account_name": "Sam Builds Ltd", "sort_code": "12 34 56", "account_number": "12345678"},
}
ACME = {"name": "Acme Kitchens Ltd", "email": "accounts@acme.example", "address": "2 Low Road\nYork"}
LABOUR = {"description": "Kitchen refit labour", "quantity": "7.5", "unit": "hours", "unit_price_pence": 4500}
FIXINGS = {"description": "Fixings", "quantity": "10", "unit": "boxes", "unit_price_pence": 250}


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


async def _sent(
    books: Books, sender: FakeMailSender, day: date = date(2026, 9, 10), lines: list[dict] | None = None, **cust
) -> inv_.Invoice:
    draft = InvoiceDraft.model_validate(
        {"customer": {**ACME, **cust}, "issue_date": day.isoformat(), "lines": lines or [LABOUR]}
    )
    inv = await inv_.create_invoice(books, draft, USER)
    return await inv_.send_invoice(books, sender, inv.number, USER, render_invoice(inv, await inv_.load_profile(books)))


async def _money(books: Books, number: str) -> pay_.InvoiceMoney:
    m = pay_.invoice_money(await inv_.get_invoice(books, number), await pay_.load_ledger(books))
    assert m is not None
    return m


async def _acme(books: Books) -> tuple[cb.Contact, cb.Statement, cb.ContactTotals]:
    contacts, ledger, _ = await cb.contact_book(books)
    acme = next(c for c in contacts if c.name == "Acme Kitchens Ltd")
    docs = cb.assign(contacts, cb.documents(ledger)).get(acme.id, [])
    return acme, cb.statement(acme, docs, ledger), cb.totals(docs, ledger, date(2026, 4, 6), date(2026, 12, 31))


# --------------------------------------------------------------------------- #
# Part payments
# --------------------------------------------------------------------------- #


async def test_a_part_payment_posts_to_the_bank_and_leaves_the_balance_owed(books: Books, sender: FakeMailSender):
    inv = await _sent(books, sender)  # 7.5 h x £45 = £337.50 + £67.50 VAT = £405.00
    part = await inv_.mark_paid(books, inv.number, USER, amount_pence=10000, paid_on=date(2026, 9, 20))
    assert (part.status, part.paid_pence, part.balance_pence) == ("sent", 10000, 30500)
    assert part.payment_status == "part_paid"

    pay = next(e for e in await books.list_events() if e.kind == "bank")
    assert {ln.account: (ln.debit, ln.credit) for ln in pay.lines} == {
        "1200 Bank": (10000, 0),
        "1100 Debtors": (0, 10000),
    }
    assert (pay.net, pay.vat, pay.date) == (0, 0, date(2026, 9, 20))  # a payment never reaches the VAT boxes
    ret = compute_vat_return(await books.list_events(), "x", date(2026, 7, 1), date(2026, 9, 30))
    assert str(ret.vat_due_sales) == "67.50" and ret.total_sales_ex_vat == 337

    # Contacts and ageing see what is still owed, not the invoice total
    _, st, t = await _acme(books)
    assert [(ln.kind, ln.amount_pence, ln.paid_pence, ln.balance_pence) for ln in st.lines] == [
        ("invoice", 40500, 0, 40500),
        ("payment", 0, -10000, 30500),
    ]
    assert t.open_receivable_pence == 30500 and t.balance_pence == 30500
    contacts, ledger, _ = await cb.contact_book(books)
    aged = cb.aged(contacts, ledger, date(2026, 10, 27))
    (doc,) = aged.debtors.rows[0].documents
    assert (doc.amount_pence, doc.gross_pence, doc.due_date, doc.age_days) == (30500, 40500, date(2026, 10, 10), 17)

    rest = await inv_.mark_paid(books, inv.number, USER, paid_on=date(2026, 10, 1))  # the balance by default
    assert (rest.status, rest.paid_pence, rest.balance_pence, rest.paid_at) == ("paid", 40500, 0, date(2026, 10, 1))
    m = await _money(books, inv.number)
    assert [p.applied_pence for p in m.payments] == [10000, 30500] and m.payment_status == "paid"
    contacts, ledger, _ = await cb.contact_book(books)
    assert cb.aged(contacts, ledger, date(2026, 10, 27)).debtors.rows == []


async def test_removing_a_payment_reverses_it_and_the_invoice_is_owed_again(books: Books, sender: FakeMailSender):
    inv = await _sent(books, sender)
    await inv_.mark_paid(books, inv.number, USER)
    (p,) = (await _money(books, inv.number)).payments
    await pay_.remove_payment(books, p.id, USER)
    events = await books.list_events()
    assert [e.kind for e in events] == ["sale", "bank", "reversal"] and events[2].reverses == events[1].id
    back = await inv_.get_invoice(books, inv.number)
    assert (back.status, back.balance_pence, back.payment_status) == ("sent", 40500, "open")
    with pytest.raises(InvoiceStateError, match="already been removed"):
        await pay_.remove_payment(books, p.id, USER)
    ret = compute_vat_return(events, "x", date(2026, 7, 1), date(2026, 12, 31))
    assert str(ret.vat_due_sales) == "67.50" and ret.warnings == []  # the payment and its undo stay off the return


async def test_a_paid_invoice_is_voided_only_after_its_payments_are_removed(books: Books, sender: FakeMailSender):
    inv = await _sent(books, sender)
    await inv_.mark_paid(books, inv.number, USER, amount_pence=20000)
    await inv_.mark_paid(books, inv.number, USER)
    with pytest.raises(InvoiceStateError, match=r"£405.00 of payments against it \(2 payments\)\. Remove them first"):
        await inv_.void_invoice(books, inv.number, USER, "wrong customer")
    for p in (await _money(books, inv.number)).payments:
        await pay_.remove_payment(books, p.id, USER)
    voided = await inv_.void_invoice(books, inv.number, USER, "wrong customer")
    assert voided.status == "void"
    ret = compute_vat_return(await books.list_events(), "x", date(2026, 7, 1), date(2026, 12, 31))
    assert str(ret.vat_due_sales) == "0.00"


async def test_an_invoice_marked_paid_before_payments_were_recorded_still_counts_as_paid(
    books: Books, sender: FakeMailSender
):
    inv = await _sent(books, sender)
    old = await inv_.get_invoice(books, inv.number)
    old.status, old.paid_at = "paid", date(2026, 9, 30)  # how the earlier Mark paid left it: no amount, no posting
    await inv_.save_invoice(books, old)
    m = await _money(books, inv.number)
    assert (m.payment_status, m.paid_pence, [p.source for p in m.payments]) == ("paid", 40500, ["marked"])
    with pytest.raises(InvoiceStateError, match="marked paid"):
        await inv_.void_invoice(books, inv.number, USER, "x")
    back = await inv_.unmark_paid(books, inv.number, USER)
    assert back.status == "sent"
    assert (await inv_.void_invoice(books, inv.number, USER, "x")).status == "void"


# --------------------------------------------------------------------------- #
# One bank line, two invoices; overpayments
# --------------------------------------------------------------------------- #


async def test_one_bank_line_pays_two_invoices(books: Books, sender: FakeMailSender):
    a = await _sent(books, sender, date(2026, 9, 1))  # £405.00
    b = await _sent(books, sender, date(2026, 9, 5), lines=[FIXINGS])  # £25.00 + £5.00 = £30.00
    csv = b"Date,Description,Amount\n03/10/2026,ACME KITCHENS INV1 INV2,435.00\n"
    await books.import_bank_csv(csv, "oct.csv", USER)
    (line,) = await books.stored_bank_lines()
    await books.confirm_match(line.id, [a.event_id, b.event_id], USER)  # on the Bank page: nothing is posted
    for n in (a.number, b.number):
        m = await _money(books, n)
        assert (m.payment_status, m.balance_pence, m.payments[0].source) == ("paid", 0, "bank_line")
        assert (await inv_.get_invoice(books, n)).status == "paid"  # the match refreshed the invoice files
    _, st, t = await _acme(books)
    assert [ln.kind for ln in st.lines] == ["invoice", "invoice", "payment"] and st.lines[-1].paid_pence == -43500
    assert st.closing_balance_pence == 0 and t.open_receivable_pence == 0
    assert [e.kind for e in await books.list_events()] == ["sale", "sale"]

    # Unmatching it (Remove on the invoice) makes both owed again
    await pay_.remove_payment(books, line.id, USER)
    assert [(await inv_.get_invoice(books, n)).status for n in (a.number, b.number)] == ["sent", "sent"]


async def test_one_recorded_payment_split_across_two_invoices_from_a_bank_line(books: Books, sender: FakeMailSender):
    a = await _sent(books, sender, date(2026, 9, 1))
    b = await _sent(books, sender, date(2026, 9, 5), lines=[FIXINGS])
    await books.import_bank_csv(b"Date,Description,Amount\n03/10/2026,ACME KITCHENS,235.00\n", "oct.csv", USER)
    (line,) = await books.stored_bank_lines()
    body = pay_.PaymentIn(
        side="sale",
        allocations=[
            pay_.AllocationIn(event_id=a.event_id, amount_pence=20500),
            pay_.AllocationIn(event_id=b.event_id, amount_pence=3000),
        ],
        bank_line_id=line.id,
    )
    rec = await pay_.record_payment(books, body, USER)
    assert (rec.amount_pence, rec.date) == (23500, date(2026, 10, 3))  # from the bank line
    assert ((await _money(books, a.number)).balance_pence, (await _money(books, b.number)).balance_pence) == (20000, 0)
    (matched,) = await books.stored_bank_lines()
    assert matched.status == "matched" and matched.event_ids() == [rec.event_id]
    # Taking it back reverses the entry and reopens the line
    await pay_.remove_payment(books, rec.id, USER)
    (reopened,) = await books.stored_bank_lines()
    assert reopened.status == "unmatched" and (await _money(books, a.number)).balance_pence == 40500


def _pay(side: str, amount: int, *allocs: tuple[str | None, int]) -> pay_.PaymentIn:
    return pay_.PaymentIn(
        side=side,  # type: ignore[arg-type]
        amount_pence=amount,
        allocations=[pay_.AllocationIn(event_id=e or "", amount_pence=n) for e, n in allocs],
    )


async def test_split_checks(books: Books, sender: FakeMailSender):
    a = await _sent(books, sender)
    other = await _sent(books, sender, name="Bloggs & Co", email="b@bloggs.example")
    with pytest.raises(InvoiceError, match="has £405.00 left to pay"):
        await pay_.record_payment(
            books,
            _pay("sale", 50000, (a.event_id, 50000)),
            USER,
        )
    with pytest.raises(InvoiceError, match="one customer"):
        await pay_.record_payment(
            books,
            pay_.PaymentIn(
                side="sale",
                amount_pence=2000,
                allocations=[
                    pay_.AllocationIn(event_id=a.event_id, amount_pence=1000),
                    pay_.AllocationIn(event_id=other.event_id, amount_pence=1000),
                ],
            ),
            USER,
        )
    with pytest.raises(InvoiceError, match="more than the payment"):
        await pay_.record_payment(
            books,
            _pay("sale", 100, (a.event_id, 200)),
            USER,
        )
    with pytest.raises(InvoiceError, match="No open bill"):
        await pay_.record_payment(
            books,
            _pay("purchase", 100, (a.event_id, 100)),
            USER,
        )
    assert [e.kind for e in await books.list_events()] == ["sale", "sale"]  # nothing posted by a refused payment


async def test_an_overpayment_leaves_a_credit_on_the_customer(books: Books, sender: FakeMailSender):
    inv = await _sent(books, sender)
    paid = await inv_.mark_paid(books, inv.number, USER, amount_pence=50000, paid_on=date(2026, 9, 30))
    assert (paid.status, paid.payment_status, paid.balance_pence) == ("paid", "overpaid", 0)
    m = await _money(books, inv.number)
    assert (m.paid_pence, m.overpaid_pence, m.payments[0].amount_pence) == (40500, 9500, 50000)
    _, st, t = await _acme(books)
    assert st.closing_balance_pence == -9500 and st.credit_pence == 9500  # the user owes Acme £95.00
    assert (t.open_receivable_pence, t.customer_credit_pence, t.balance_pence) == (0, 9500, -9500)
    pay = next(e for e in await books.list_events() if e.kind == "bank")
    assert sum(ln.debit for ln in pay.lines if ln.account == "1200 Bank") == 50000  # all of it went to the bank


# --------------------------------------------------------------------------- #
# Bills: the purchase mirror
# --------------------------------------------------------------------------- #


def _bill(gross: float, vat: float, day: str = "2026-09-02", doc_type: str = "purchase_invoice") -> ExtractedDoc:
    net = round(gross - vat, 2)
    return ExtractedDoc(
        doc_type=doc_type,  # type: ignore[arg-type]
        supplier_name="Howdens Joinery",
        supplier_vat_number="GB 232 4567 89",
        customer_name="Sam Builds Ltd",
        invoice_number="H-77" if doc_type != "credit_note" else "HC-12",
        date=day,
        currency="GBP",
        lines=[ExtractedLine(description="Doors", qty=1, unit_price=net, net=net, vat_rate=20, vat=vat)],
        net_total=net,
        vat_total=vat,
        gross_total=gross,
        payment_method=None,  # on account
        card_last4=None,
        category_guess="Materials",
        confidence=0.95,
    )


async def _post(books: Books, doc: ExtractedDoc) -> Proposal:
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


async def test_paying_a_bill_posts_creditors_against_the_bank(books: Books):
    bill = await _post(books, _bill(240.00, 40.00))
    rec = await pay_.record_payment(
        books,
        pay_.PaymentIn(
            side="purchase",
            date=date(2026, 9, 30),
            amount_pence=10000,
            allocations=[pay_.AllocationIn(event_id=bill.event_id or "", amount_pence=10000)],
        ),
        USER,
    )
    pay = await books.get_event(rec.event_id or "")
    assert {ln.account: (ln.debit, ln.credit) for ln in pay.lines} == {
        "2100 Creditors": (10000, 0),
        "1200 Bank": (0, 10000),
    }
    contacts, ledger, _ = await cb.contact_book(books)
    howdens = next(c for c in contacts if c.name == "Howdens Joinery")
    t = cb.totals(cb.assign(contacts, cb.documents(ledger))[howdens.id], ledger, date(2026, 4, 6), date(2026, 12, 31))
    assert (t.open_payable_pence, t.balance_pence) == (14000, -14000)
    (open_bill,) = pay_.open_documents(ledger, "purchase")
    assert (open_bill.reference, open_bill.outstanding_pence) == ("H-77", 14000)


async def test_a_supplier_credit_note_is_proposed_like_a_bill_and_posted_as_a_reversal(books: Books):
    await _post(books, _bill(240.00, 40.00))
    cn = await _post(books, _bill(-60.00, -10.00, day="2026-10-05", doc_type="credit_note"))  # printed negative
    ev = await books.get_event(cn.event_id or "")
    assert ev.kind == "reversal" and ev.is_credit_note and (ev.net, ev.vat) == (5000, 1000)
    assert {ln.account: (ln.debit, ln.credit) for ln in ev.lines} == {
        "2100 Creditors": (6000, 0),
        "5000 Materials": (0, 5000),
        "2200 VAT control": (0, 1000),
    }
    q4 = compute_vat_return(await books.list_events(), "x", date(2026, 10, 1), date(2026, 12, 31))
    assert str(q4.vat_reclaimed) == "-10.00" and q4.total_purchases_ex_vat == -50  # in the credit note's quarter
    q3 = compute_vat_return(await books.list_events(), "x", date(2026, 7, 1), date(2026, 9, 30))
    assert str(q3.vat_reclaimed) == "40.00"

    contacts, ledger, _ = await cb.contact_book(books)
    howdens = next(c for c in contacts if c.name == "Howdens Joinery")
    docs = cb.assign(contacts, cb.documents(ledger))[howdens.id]
    t = cb.totals(docs, ledger, date(2026, 4, 6), date(2026, 12, 31))
    assert (t.open_payable_pence, t.supplier_credit_pence, t.balance_pence) == (24000, 6000, -18000)
    assert t.ytd_purchases_vat_pence == 3000
    st = cb.statement(howdens, docs, ledger)
    assert [(ln.details, ln.amount_pence) for ln in st.lines] == [("Purchase", -24000), ("Supplier credit note", 6000)]

    # Undo works on a credit note too, and puts the VAT back
    await undo(books, cn.event_id or "", USER)
    q4 = compute_vat_return(await books.list_events(), "x", date(2026, 10, 1), date(2026, 12, 31))
    assert str(q4.vat_reclaimed) == "0.00" and q4.total_purchases_ex_vat == 0


# --------------------------------------------------------------------------- #
# Credit notes to customers
# --------------------------------------------------------------------------- #


async def test_a_credit_note_in_the_next_quarter_nets_off_there(books: Books, sender: FakeMailSender):
    inv = await _sent(books, sender, date(2026, 9, 10), lines=[LABOUR, FIXINGS])  # £337.50 + £25.00 net, 20%
    cn = await cn_.create_credit_note(
        books,
        inv.number,
        CreditNoteDraft(
            lines=[CreditLineIn(line=0, quantity=Decimal("2"))], issue_date=date(2026, 10, 2), reason="2 hours not done"
        ),
        USER,
    )
    assert (cn.number, cn.net_pence, cn.vat_pence, cn.total_pence) == ("CN-0001", 9000, 1800, 10800)
    ev = await books.get_event(cn.event_id or "")
    assert ev.kind == "reversal" and ev.credits == inv.event_id and ev.reverses is None and ev.date == date(2026, 10, 2)
    assert {(ln.account, ln.debit, ln.credit, ln.vat_code) for ln in ev.lines} == {
        ("4000 Sales", 9000, 0, "S"),
        ("2200 VAT control", 1800, 0, "S"),
        ("1100 Debtors", 0, 10800, None),
    }
    events = await books.list_events()
    q3 = compute_vat_return(events, "q3", date(2026, 7, 1), date(2026, 9, 30))
    q4 = compute_vat_return(events, "q4", date(2026, 10, 1), date(2026, 12, 31))
    assert (str(q3.vat_due_sales), q3.total_sales_ex_vat) == ("72.50", 362)  # the invoice's quarter is untouched
    assert (str(q4.vat_due_sales), q4.total_sales_ex_vat) == ("-18.00", -90)  # the credit note's quarter nets it off

    m = await _money(books, inv.number)
    assert (m.credited_pence, m.balance_pence, m.payment_status) == (10800, 32700, "part_paid")
    assert [(c.number, c.applied_pence) for c in m.credit_notes] == [("CN-0001", 10800)]
    _, st, t = await _acme(books)
    assert [(ln.details, ln.reference, ln.amount_pence) for ln in st.lines] == [
        ("Sales invoice", inv.number, 43500),
        ("Credit note", "CN-0001", -10800),
    ]
    assert t.open_receivable_pence == 32700 and t.ytd_sales_vat_pence == 7250 - 1800

    # What is left of the line can still be credited; more cannot
    with pytest.raises(InvoiceError, match="Line 1 has 5.5 left to credit"):
        await cn_.create_credit_note(
            books, inv.number, CreditNoteDraft(lines=[CreditLineIn(line=0, quantity=Decimal("6"))], reason="x"), USER
        )
    rest = await cn_.create_credit_note(books, inv.number, CreditNoteDraft(reason="cancelled"), USER)
    assert rest.number == "CN-0002" and rest.total_pence == 43500 - 10800
    assert (await inv_.get_invoice(books, inv.number)).status == "paid"  # nothing left to pay
    with pytest.raises(InvoiceError, match="credited in full"):
        await cn_.create_credit_note(books, inv.number, CreditNoteDraft(reason="again"), USER)
    with pytest.raises(InvoiceStateError, match="CN-0002, CN-0001"):
        await inv_.void_invoice(books, inv.number, USER, "x")


async def test_a_credit_note_on_a_paid_invoice_leaves_a_credit_and_voiding_it_puts_the_vat_back(
    books: Books, sender: FakeMailSender
):
    inv = await _sent(books, sender)
    await inv_.mark_paid(books, inv.number, USER)
    cn = await cn_.create_credit_note(
        books, inv.number, CreditNoteDraft(issue_date=date(2026, 10, 2), reason="goodwill"), USER
    )
    _, st, t = await _acme(books)
    assert (t.customer_credit_pence, st.closing_balance_pence) == (40500, -40500)  # a refund is due
    voided = await cn_.void_credit_note(books, cn.number, USER, "issued in error")
    assert voided.status == "void"
    q4 = compute_vat_return(await books.list_events(), "q4", date(2026, 10, 1), date(2026, 12, 31))
    assert (str(q4.vat_due_sales), q4.total_sales_ex_vat) == ("0.00", 0)
    _, st, t = await _acme(books)
    assert (t.customer_credit_pence, st.closing_balance_pence) == (0, 0)


async def test_drafts_cannot_be_credited(books: Books):
    draft = await inv_.create_invoice(books, InvoiceDraft.model_validate({"customer": ACME, "lines": [LABOUR]}), USER)
    with pytest.raises(InvoiceStateError, match="only a sent invoice"):
        await cn_.create_credit_note(books, draft.number, CreditNoteDraft(reason="x"), USER)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


async def test_routes_record_payment_and_credit_note(
    books: Books, sender: FakeMailSender, client: TestClient, fake: FakeStorageProvider
):
    inv = await _sent(books, sender)
    r = client.post(f"/invoices/{inv.number}/payments", headers=H, json={"amount_pence": 5000, "paid_on": "2026-09-20"})
    assert r.status_code == 200, r.text
    row = r.json()
    assert (row["status"], row["money"]["paid_pence"], row["money"]["balance_pence"]) == ("sent", 5000, 35500)
    assert row["money"]["payment_status"] == "part_paid" and len(row["money"]["payments"]) == 1
    assert client.post(f"/invoices/{inv.number}/payments", headers=H, json={"amount_pence": 1.5}).status_code == 422
    assert client.post(f"/invoices/{inv.number}/payments", json={"amount_pence": 5}).status_code == 400  # no X-User

    listed = client.get("/invoices", headers=H).json()
    assert listed[0]["money"]["balance_pence"] == 35500

    # A credit note needs the confirmation tick
    body = {"reason": "Fixings returned", "lines": [{"line": 0, "quantity": "1"}]}
    assert client.post(f"/invoices/{inv.number}/credit-notes", headers=H, json=body).status_code == 400
    r = client.post(f"/invoices/{inv.number}/credit-notes", headers=H, json={**body, "confirm": True})
    assert r.status_code == 200, r.text
    cn = r.json()
    assert (cn["number"], cn["total_pence"], cn["invoice"]) == ("CN-0001", 5400, inv.number)
    pdf = client.post("/credit-notes/CN-0001/pdf", headers=H).json()
    assert pdf["path"] == "03 Sales/credit-notes/CN-0001.pdf" and pdf["email"]["to"] == "accounts@acme.example"
    assert fake.files["03 Sales/credit-notes/CN-0001.pdf"].startswith(b"%PDF")
    assert client.post("/credit-notes/CN-0001/send", headers=H, json={}).status_code == 400  # no confirm
    sent = client.post("/credit-notes/CN-0001/send", headers=H, json={"confirm": True}).json()
    assert sent["sent_to"] == "accounts@acme.example" and sender.sent[-1].attachments[0].name == "CN-0001.pdf"
    assert [c["number"] for c in client.get(f"/credit-notes?invoice={inv.number}", headers=H).json()] == ["CN-0001"]

    m = client.get(f"/invoices/{inv.number}", headers=H).json()["money"]
    assert (m["balance_pence"], m["credited_pence"]) == (40500 - 5000 - 5400, 5400)

    # Void while a payment stands: a clear 409; remove it, then void the credit note and the invoice
    pid = m["payments"][0]["id"]
    r = client.post(f"/invoices/{inv.number}/void", headers=H, json={"reason": "wrong job"})
    assert r.status_code == 409 and "Remove it first" in r.json()["detail"]
    r = client.delete(f"/invoices/{inv.number}/payments/{pid}", headers=H)
    assert r.status_code == 200 and r.json()["money"]["paid_pence"] == 0
    assert client.delete(f"/invoices/{inv.number}/payments/{pid}", headers=H).status_code == 404
    r = client.post(f"/invoices/{inv.number}/void", headers=H, json={"reason": "wrong job"})
    assert r.status_code == 409 and "CN-0001" in r.json()["detail"]
    assert client.post("/credit-notes/CN-0001/void", headers=H, json={"reason": "wrong job"}).status_code == 200
    r = client.post(f"/invoices/{inv.number}/void", headers=H, json={"reason": "wrong job"})
    assert r.json()["status"] == "void"

    payments = client.get("/payments", headers=H).json()
    assert payments == []  # the one recorded payment was removed
    assert client.get("/payments/open?side=sale", headers=H).json() == []


async def test_contact_statement_route_lists_payments_and_credits(
    books: Books, sender: FakeMailSender, client: TestClient
):
    inv = await _sent(books, sender)
    client.post(f"/invoices/{inv.number}/payments", headers=H, json={"amount_pence": 45000, "paid_on": "2026-09-25"})
    contacts = client.get("/contacts", headers=H).json()["contacts"]
    acme = next(c for c in contacts if c["name"] == "Acme Kitchens Ltd")
    assert acme["totals"]["customer_credit_pence"] == 4500 and acme["totals"]["balance_pence"] == -4500
    st = client.get(f"/contacts/{acme['id']}/statement", headers=H).json()
    assert [(ln["kind"], ln["details"], ln["paid_pence"]) for ln in st["lines"]] == [
        ("invoice", "Sales invoice", 0),
        ("payment", "Payment received", -45000),
    ]
    assert st["credit_pence"] == 4500 and st["lines"][0]["reference"] == inv.number
