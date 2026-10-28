"""Minimal examples of the bugs the property tests found (tests/test_properties_books.py), kept as plain tests.

1. Unmatching a bank line on the Bank page took back a credit that had already been refunded or applied: the
   refund stayed posted (Dr 1100 Debtors / Cr 1200 Bank) with no credit behind it, so the debtor control account
   no longer agreed with what customers owe.
2. The same through a credit note: one dated before a recorded payment leaves that payment's money as a credit;
   once the credit was refunded or applied, voiding the credit note took it back, stranding the refund.
3. ...and through removing a payment: an earlier one, once removed, lets a later payment take back the money over
   it had left as a credit, refunded or not.
   Undoing a supplier's credit note dated before a payment to that supplier strands it the same way.
4. Invoice files kept a stale status: a change to one invoice (a credit note) can change what a credit applied to
   another invoice pays, and only the first invoice's file was refreshed, so the other could read "sent" when paid
   (and be chased) or "paid" when owed.
5. A bank line of 1p matched to a document that a credit note dated before the line had since settled in full was
   "within a penny" of the £0.00 owed, so it paid nothing and left no credit: its penny went missing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from accnomos_connectors import FakeMailSender, FakeStorageProvider
from accnomos_ledger.bank import BankLine
from app import credit_notes as cn_
from app import credits as cr_
from app import invoicing as inv_
from app import payments as pay_
from app.approve import ApprovalError, approve, undo
from app.books import BankMatchError, Books
from app.contacts import Ledger, load_ledger
from app.credit_notes import CreditNote, credit_note_event
from app.invoicing import (
    PROFILE,
    InvoiceDraft,
    InvoiceProfile,
    InvoiceStateError,
    LineIn,
    build_invoice,
    price_lines,
    sale_event,
)
from app.journal import draft_journal
from app.schemas import ExtractedDoc, ExtractedLine, Proposal

USER = "sam@sambuilds.co.uk"
PROFILE_ = InvoiceProfile(name="Sam Builds Ltd", address="1 High Street\nLeeds", vrn="GB 123 4567 89")
DRAFT = InvoiceDraft.model_validate(
    {
        "customer": {"name": "Acme Kitchens Ltd", "email": "accounts@acme.example"},
        "issue_date": "2026-09-10",
        "lines": [{"description": "Labour", "quantity": "1", "unit_price_pence": 40000}],
    }
)


@pytest.fixture
async def books() -> Books:
    b = Books(FakeStorageProvider())
    await b.write_json(PROFILE, PROFILE_.model_dump(mode="json"))
    return b


async def test_a_bank_line_whose_credit_was_refunded_cannot_be_unmatched(books: Books):
    inv = await inv_.create_invoice(books, DRAFT, USER)
    inv = await inv_.send_invoice(books, FakeMailSender(), inv.number, USER, b"%PDF-1.4")  # £480.00
    await books.import_bank_csv(b"Date,Description,Amount\n20/09/2026,ACME KITCHENS,500.00\n", "s.csv", USER)
    (line,) = await books.stored_bank_lines()
    await books.confirm_match(line.id, [inv.event_id or ""], USER)  # £20.00 over: a credit on Acme
    (credit,) = (await load_ledger(books)).settlement().credits
    assert credit.amount_pence == 2000
    await cr_.refund_credit(books, cr_.RefundIn(credit=credit.id, date=date(2026, 9, 25)), USER)

    with pytest.raises(BankMatchError, match="refunded"):
        await books.unmatch(line.id, USER)  # was allowed: the £20.00 refund was left with no credit behind it
    s = (await load_ledger(books)).settlement()
    assert [u.applied_pence for u in s.uses] == [2000] and s.outstanding(inv.event_id or "") == 0


async def test_a_credit_note_whose_displaced_credit_was_refunded_cannot_be_voided(books: Books):
    inv = await inv_.create_invoice(books, DRAFT, USER)
    inv = await inv_.send_invoice(books, FakeMailSender(), inv.number, USER, b"%PDF-1.4")  # £480.00, 10 Sep
    await inv_.mark_paid(books, inv.number, USER, paid_on=date(2026, 10, 1))
    draft = cn_.CreditNoteDraft(issue_date=date(2026, 9, 20), reason="Cancelled")  # dated before the payment
    cn = await cn_.create_credit_note(books, inv.number, draft, USER)
    (credit,) = (await load_ledger(books)).settlement().credits  # the payment came after the credit note: money over
    assert (credit.source, credit.amount_pence) == ("payment", 48000)
    await cr_.refund_credit(books, cr_.RefundIn(credit=credit.id, date=date(2026, 10, 5)), USER)

    with pytest.raises(InvoiceStateError, match="refunded"):
        await cn_.void_credit_note(books, cn.number, USER, "Raised in error")  # was allowed: stranded the refund
    s = (await load_ledger(books)).settlement()
    assert [u.applied_pence for u in s.uses] == [48000]


async def test_removing_a_payment_cannot_strand_another_payments_refunded_credit(books: Books):
    inv = await inv_.create_invoice(books, DRAFT, USER)
    inv = await inv_.send_invoice(books, FakeMailSender(), inv.number, USER, b"%PDF-1.4")  # £480.00, 10 Sep
    first = await inv_.mark_paid(books, inv.number, USER, amount_pence=12000, paid_on=date(2026, 9, 15))
    assert first.balance_pence == 36000
    await inv_.mark_paid(books, inv.number, USER, paid_on=date(2026, 10, 1))  # the £360.00 left
    lines = [cn_.CreditLineIn(line=0, quantity=Decimal("0.25"))]  # £120.00, dated between the two payments
    await cn_.create_credit_note(
        books, inv.number, cn_.CreditNoteDraft(lines=lines, issue_date=date(2026, 9, 20), reason="Part"), USER
    )
    (credit,) = (await load_ledger(books)).settlement().credits  # the 1 Oct payment now has £120.00 over
    assert credit.amount_pence == 12000
    await cr_.refund_credit(books, cr_.RefundIn(credit=credit.id, date=date(2026, 10, 5)), USER)
    earliest = min((await load_ledger(books)).records, key=lambda r: r.date)

    with pytest.raises(InvoiceStateError, match="refunded"):
        await pay_.remove_payment(books, earliest.id, USER)  # was allowed: the 1 Oct payment took the £120.00 back


async def test_undoing_a_supplier_credit_note_cannot_strand_a_refunded_credit(books: Books):
    async def post(kind: str, number: str, day: str, original: str | None = None) -> str:
        doc = ExtractedDoc(
            doc_type=kind,  # type: ignore[arg-type]
            supplier_name="Howdens Joinery",
            supplier_vat_number="GB 232 4567 89",
            customer_name="Sam Builds Ltd",
            invoice_number=number,
            original_invoice_number=original,
            date=day,
            currency="GBP",
            lines=[ExtractedLine(description="Doors", qty=1, unit_price=100.0, net=100.0, vat_rate=20, vat=20.0)],
            net_total=100.0,
            vat_total=20.0,
            gross_total=120.0,
            payment_method=None,  # on account
            card_last4=None,
            category_guess="Materials",
            confidence=0.95,
        )
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
        )
        await books.save_proposal(p)
        return (await approve(books, p.id, USER)).event_id or ""

    bill = await post("purchase_invoice", "H-77", "2026-09-01")
    allocation = pay_.AllocationIn(event_id=bill, amount_pence=12000)
    await pay_.record_payment(
        books,
        pay_.PaymentIn(side="purchase", date=date(2026, 10, 1), amount_pence=12000, allocations=[allocation]),
        USER,
    )
    cn = await post("credit_note", "HC-12", "2026-09-20", original="H-77")  # before the payment: it is money over
    (credit,) = (await load_ledger(books)).settlement().credits
    assert (credit.source, credit.amount_pence) == ("payment", 12000)
    await cr_.refund_credit(books, cr_.RefundIn(credit=credit.id, date=date(2026, 10, 5)), USER)  # Howdens paid it back

    with pytest.raises(ApprovalError, match="refunded"):
        await undo(books, cn, USER)  # was allowed: the payment took the £120.00 back, stranding the refund


async def test_every_invoice_file_is_refreshed_when_credit_applied_to_it_changes(books: Books):
    async def sent(day: str) -> inv_.Invoice:
        d = DRAFT.model_copy(update={"issue_date": date.fromisoformat(day)})
        made = await inv_.create_invoice(books, d, USER)
        return await inv_.send_invoice(books, FakeMailSender(), made.number, USER, b"%PDF-1.4")

    def whole(day: int) -> cn_.CreditNoteDraft:
        return cn_.CreditNoteDraft(issue_date=date(2026, 9, day), reason="Cancelled")

    one = await sent("2026-09-10")
    await inv_.mark_paid(books, one.number, USER, paid_on=date(2026, 10, 1))
    cn1 = await cn_.create_credit_note(books, one.number, whole(20), USER)  # the payment is now money over
    two = await sent("2026-09-10")
    (credit,) = (await load_ledger(books)).settlement().credits
    body = cr_.ApplyIn(credit=credit.id, event_id=two.event_id or "", date=date(2026, 10, 5))
    await cr_.apply_credit(books, body, USER)  # pays invoice two
    cn2 = await cn_.create_credit_note(books, two.number, whole(20), USER)  # now the credit note settles two
    await cn_.void_credit_note(books, cn1.number, USER, "Wrong")  # the payment pays one again: no credit
    await cn_.void_credit_note(books, cn2.number, USER, "Wrong")  # two is owed again
    assert (await inv_.get_invoice(books, two.number)).status == "sent"
    await cn_.create_credit_note(books, one.number, whole(21), USER)  # the credit is back, and pays two again

    money = pay_.invoice_money(await inv_.get_invoice(books, two.number), await load_ledger(books))
    assert money is not None and money.balance_pence == 0
    assert (await inv_.get_invoice(books, two.number)).status == "paid"  # was left "sent": chased though paid


def test_a_penny_bank_line_for_a_document_already_settled_is_left_as_a_credit():
    draft = InvoiceDraft.model_validate(
        {"customer": {"name": "Acme Kitchens Ltd"}, "issue_date": "2026-09-01", "lines": DRAFT.lines}
    )
    inv = build_invoice("INV-0001", draft, PROFILE_, USER)
    sale = sale_event(inv, USER, [])
    lines, summary, net, vat = price_lines([LineIn(description="All", quantity=Decimal(1), unit_price_pence=40000)])
    cn = CreditNote(
        number="CN-0001",
        invoice=inv.number,
        invoice_event_id=sale.id,
        customer=inv.customer,
        issue_date=date(2026, 9, 2),
        lines=lines,
        vat_summary=summary,
        net_pence=net,
        vat_pence=vat,
        total_pence=net + vat,
        reason="Cancelled",
        created_by=USER,
        created_at=datetime(2026, 9, 2, tzinfo=UTC),
    )
    penny = BankLine(
        id="0123456789abcdef",
        date=date(2026, 9, 5),
        amount_pence=1,
        description="ACME KITCHENS",
        source_file="s.csv",
        status="matched",
        matched_event_ids=[sale.id],
    )
    s = Ledger(events=[sale, credit_note_event(cn, USER)], bank_lines=[penny]).settlement()
    (pay,) = s.payments
    assert pay.allocations == [] and pay.unallocated_pence == 1  # was 0: the penny paid nothing and left nothing
    assert [c.amount_pence for c in s.credits] == [1]  # the line's penny, a credit on Acme
