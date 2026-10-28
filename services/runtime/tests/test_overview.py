"""Sales and Purchases overviews and customer statements: every figure is worked out by code from the files
(app/overview.py, app/statements.py, /sales/overview, /purchases/overview, /statements/*)."""

from __future__ import annotations

import base64
import json
import re
import zlib
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeMailSender, FakeStorageProvider
from app import approve as approve_
from app import bills
from app import contacts as cb
from app import invoicing as inv_
from app import overview as ov_
from app import payments as pay_
from app import purchase_orders as po_
from app import quotes as q_
from app import repeating as rp_
from app import statements as st_
from app.books import AUDIT, Books
from app.invoicing import PROFILE, InvoiceDraft, InvoiceError, InvoiceProfile, LineIn
from app.paths import STATEMENTS
from app.pdf import render_invoice

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
PROFILE_JSON = {"name": "Sam Builds Ltd", "address": "1 High Street\nLeeds LS1 1AA", "vrn": "GB 123 4567 89"}
ACME = {"name": "Acme Kitchens Ltd", "email": "accounts@acme.example", "address": "2 Low Road\nYork"}
LABOUR = {"description": "Labour", "quantity": "7.5", "unit": "hours", "unit_price_pence": 4500}  # 405.00 gross
TODAY = date(2026, 10, 27)


def _words(data: bytes) -> bytes:
    assert data.startswith(b"%PDF")
    return b"".join(zlib.decompress(s) for s in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", data, flags=16))


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


async def _sent(books: Books, sender: FakeMailSender, issue: date, due: date, **cust) -> inv_.Invoice:
    draft = InvoiceDraft.model_validate(
        {
            "customer": {**ACME, **cust},
            "issue_date": issue.isoformat(),
            "due_date": due.isoformat(),
            "lines": [LABOUR],
        }
    )
    inv = await inv_.create_invoice(books, draft, USER)
    return await inv_.send_invoice(books, sender, inv.number, USER, render_invoice(inv, await inv_.load_profile(books)))


async def _pay(books: Books, inv: inv_.Invoice, pence: int, day: date) -> None:
    assert inv.event_id
    body = pay_.PaymentIn(
        side="sale",
        date=day,
        amount_pence=pence,
        allocations=[pay_.AllocationIn(event_id=inv.event_id, amount_pence=pence)],
    )
    await pay_.record_payment(books, body, USER)


async def _bill(books: Books, name: str, day: date, price: int, *, approve: bool = True):
    p = await bills.make_bill_proposal(
        books,
        pid=bills.proposal_id("t", name, day.isoformat(), str(price)),
        evidence=f"{name}{day}{price}",
        source="test",
        note="test bill",
        supplier_name=name,
        contact_id=None,
        supplier_vat_number=None,
        bill_date=day,
        lines=[LineIn.model_validate({"description": "Goods", "quantity": "1", "unit_price_pence": price})],
        account="5100 Tools & small equipment",
        model="test",
    )
    if approve:
        await approve_.approve(books, p.id, USER)
    return p


# --------------------------------------------------------------------------- #
# Sales overview
# --------------------------------------------------------------------------- #


async def test_sales_overview_counts_and_totals_come_from_the_books(books: Books, sender: FakeMailSender):
    overdue = await _sent(books, sender, date(2026, 9, 1), date(2026, 10, 1))  # 405.00, 26 days late
    soon = await _sent(books, sender, date(2026, 10, 20), date(2026, 10, 30), name="Beta Ltd", email="b@beta.example")
    later = await _sent(books, sender, date(2026, 10, 20), date(2026, 11, 19), name="Cee Ltd", email="c@cee.example")
    paid = await _sent(books, sender, date(2026, 10, 1), date(2026, 10, 31), name="Dee Ltd", email="d@dee.example")
    await _pay(books, overdue, 10000, date(2026, 10, 15))  # part paid: 305.00 left
    await _pay(books, paid, 40500, date(2026, 10, 12))  # all paid
    await inv_.create_invoice(
        books,
        InvoiceDraft.model_validate({"customer": ACME, "issue_date": "2026-10-27", "lines": [LABOUR]}),
        USER,
    )
    o = await ov_.load_sales(books, TODAY)

    assert (o.drafts.count, o.drafts.total_pence) == (1, 40500)
    assert (o.awaiting_payment.count, o.awaiting_payment.total_pence) == (3, 30500 + 40500 + 40500)
    assert (o.overdue.count, o.overdue.total_pence) == (1, 30500)  # what is left, not the invoice total
    assert (o.due_soon.count, o.due_soon.total_pence) == (1, 40500)  # due within 7 days
    assert o.money_in_pence == 10000 + 40500  # payments in the last 30 days
    assert o.invoiced_pence == 3 * 40500  # issued in the last 30 days: soon, later, paid (not the one from September)
    assert o.aged["0-30"] == 30500 and o.aged["current"] == 81000 and sum(o.aged.values()) == 111500
    assert [r.number for r in o.owed_most][0] == overdue.number  # overdue first
    assert o.owed_most[0].days_overdue == 26 and o.owed_most[0].owed_pence == 30500
    assert soon.number in [r.number for r in o.owed_most] and later.number in [r.number for r in o.owed_most]


async def test_sales_overview_ignores_old_payments_and_void_invoices(books: Books, sender: FakeMailSender):
    old = await _sent(books, sender, date(2026, 8, 1), date(2026, 8, 31))
    await _pay(books, old, 40500, date(2026, 8, 20))  # more than 30 days ago
    gone = await _sent(books, sender, date(2026, 10, 1), date(2026, 10, 31), name="Gone Ltd", email="g@gone.example")
    await inv_.void_invoice(books, gone.number, USER, "wrong customer")
    o = await ov_.load_sales(books, TODAY)
    assert o.money_in_pence == 0 and o.awaiting_payment.count == 0 and o.invoiced_pence == 0


async def test_sales_overview_quotes_and_repeating(books: Books):
    today = q_.london_today()
    mk = lambda **kw: q_.QuoteDraft.model_validate(  # noqa: E731
        {"customer": ACME, "issue_date": today.isoformat(), "lines": [LABOUR], **kw}
    )
    await q_.create_quote(books, mk(), USER)  # draft
    a = await q_.create_quote(books, mk(), USER)
    await q_.mark_sent(books, a.number, USER)  # waiting
    b = await q_.create_quote(books, mk(), USER)
    await q_.mark_sent(books, b.number, USER)
    await q_.decide(books, b.number, USER, "accepted")  # accepted, not yet an invoice
    c = await q_.create_quote(books, mk(), USER)
    await q_.mark_sent(books, c.number, USER)
    await q_.decide(books, c.number, USER, "accepted")
    await q_.convert_to_invoice(books, c.number, USER)  # accepted but already invoiced: not counted
    await rp_.create_template(
        books,
        rp_.RepeatingIn.model_validate(
            {
                "kind": "invoice",
                "frequency": "monthly",
                "start_date": "2026-11-15",
                "party": {"name": "Acme Kitchens Ltd", "email": "accounts@acme.example"},
                "lines": [LABOUR],
            }
        ),
        USER,
    )
    o = await ov_.load_sales(books, today)
    assert (o.quote_drafts.count, o.quotes_waiting.count, o.quotes_to_invoice.count) == (1, 1, 1)
    assert o.quotes_to_invoice.total_pence == 40500
    assert o.repeating.active == 1 and o.repeating.next_date == date(2026, 11, 15)
    assert o.repeating.due_now == (1 if today >= date(2026, 11, 15) else 0)


def test_sales_route_shape(client: TestClient):
    r = client.get("/sales/overview", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["drafts"] == {"count": 0, "total_pence": 0} and body["owed_most"] == []
    assert set(body["aged"]) == set(cb.BUCKETS)


# --------------------------------------------------------------------------- #
# Purchases overview
# --------------------------------------------------------------------------- #


async def test_purchases_overview_owed_overdue_and_review(books: Books):
    await _bill(books, "Screwfix Ltd", date(2026, 8, 20), 10000)  # 120.00 gross, due 19 Sep: overdue
    await _bill(books, "Wickes Ltd", date(2026, 10, 1), 20000)  # 240.00, due 31 Oct: due in 4 days
    await _bill(books, "Selco Ltd", date(2026, 10, 20), 5000)  # 60.00, due 19 Nov: not yet
    await _bill(books, "Pending Ltd", date(2026, 10, 25), 3000, approve=False)  # still in Review
    o = await ov_.load_purchases(books, TODAY)
    assert (o.awaiting_payment.count, o.awaiting_payment.total_pence) == (3, 12000 + 24000 + 6000)
    assert (o.overdue.count, o.overdue.total_pence) == (1, 12000)
    assert (o.due_soon.count, o.due_soon.total_pence) == (1, 24000)
    assert (o.in_review.count, o.in_review.total_pence) == (1, 3600)
    assert o.aged["31-60"] == 12000 and o.aged["current"] == 30000
    assert o.owed_most[0].name == "Screwfix Ltd" and o.owed_most[0].days_overdue == 38


async def test_purchases_overview_money_out_and_orders(books: Books):
    p = await _bill(books, "Screwfix Ltd", date(2026, 10, 1), 10000)
    (event,) = await books.list_events()
    body = pay_.PaymentIn(
        side="purchase",
        date=date(2026, 10, 20),
        amount_pence=5000,
        allocations=[pay_.AllocationIn(event_id=event.id, amount_pence=5000)],
    )
    await pay_.record_payment(books, body, USER)
    assert p.id
    supplier = {"name": "Travis Perkins Ltd", "email": "o@tp.example"}
    line = {"description": "Boards", "quantity": "10", "unit_price_pence": 1000}
    day = TODAY.isoformat()
    mk = lambda **kw: po_.PurchaseOrderDraft.model_validate(  # noqa: E731
        {"supplier": supplier, "issue_date": day, "lines": [line], **kw}
    )
    await po_.create_order(books, mk(), USER)  # draft
    late = await po_.create_order(books, mk(delivery_date=day), USER)
    await po_.approve_order(books, late.number, USER)
    future = await po_.create_order(books, mk(delivery_date=(TODAY + timedelta(days=5)).isoformat()), USER)
    await po_.approve_order(books, future.number, USER)
    o = await ov_.load_purchases(books, TODAY + timedelta(days=1))
    assert o.money_out_pence == 5000
    assert (o.awaiting_payment.count, o.awaiting_payment.total_pence) == (1, 7000)  # 120.00 less 50.00 paid
    assert (o.order_drafts.count, o.orders_open.count, o.orders_late.count) == (1, 2, 1)
    assert o.orders_open.total_pence == 2 * 12000


def test_purchases_route_shape(client: TestClient):
    body = client.get("/purchases/overview", headers=H).json()
    assert body["in_review"] == {"count": 0, "total_pence": 0} and body["orders_open"]["count"] == 0


# --------------------------------------------------------------------------- #
# Statements
# --------------------------------------------------------------------------- #


async def _acme_id(books: Books) -> str:
    contacts, _ledger, _ = await cb.contact_book(books)
    return next(c.id for c in contacts if c.name == ACME["name"])


async def test_statement_has_activity_balances_and_open_items(books: Books, sender: FakeMailSender):
    a = await _sent(books, sender, date(2026, 9, 1), date(2026, 10, 1))
    b = await _sent(books, sender, date(2026, 10, 10), date(2026, 11, 9))
    await _pay(books, a, 10000, date(2026, 10, 15))
    cid = await _acme_id(books)
    v = await st_.build_statement(books, cid, date(2026, 10, 1), TODAY, TODAY)
    assert v.opening_balance_pence == 40500  # invoice A, before the period
    assert [(ln.reference, ln.amount_pence + ln.paid_pence, ln.balance_pence) for ln in v.lines] == [
        (b.number, 40500, 81000),
        (None, -10000, 71000),  # the payment
    ]
    assert v.closing_balance_pence == 71000 == v.owed_pence
    assert [o.outstanding_pence for o in v.open_documents] == [30500, 40500]
    # An earlier end date: the outstanding list is left out, because it describes the books now.
    earlier = await st_.build_statement(books, cid, None, date(2026, 10, 12), TODAY)
    assert earlier.closing_balance_pence == 81000 and not earlier.open_documents and not earlier.shows_outstanding


async def test_statement_leaves_out_what_the_user_owes_a_contact(books: Books, sender: FakeMailSender):
    await _sent(books, sender, date(2026, 10, 1), date(2026, 10, 31))
    await _bill(books, ACME["name"], date(2026, 10, 2), 9999)  # the customer is also a supplier
    v = await st_.build_statement(books, await _acme_id(books), None, TODAY, TODAY)
    assert v.closing_balance_pence == 40500 and v.owed_pence == 40500 and len(v.lines) == 1


async def test_statement_pdf_names_the_customer_and_amounts(books: Books, sender: FakeMailSender):
    await _sent(books, sender, date(2026, 9, 1), date(2026, 10, 1))
    v = await st_.build_statement(books, await _acme_id(books), None, TODAY, TODAY)
    profile = await inv_.load_profile(books)
    text = _words(st_.render(v, profile))
    assert b"STATEMENT" in text and b"Acme Kitchens Ltd" in text and b"405.00" in text


async def test_statement_unknown_contact(books: Books):
    with pytest.raises(FileNotFoundError):
        await st_.build_statement(books, "nope", None, None, TODAY)
    cid = "x"
    with pytest.raises(InvoiceError):
        # start after end is refused before any lookup
        await st_.build_statement(books, cid, date(2026, 11, 1), date(2026, 10, 1), TODAY)


async def test_statement_routes_send_needs_confirm_and_is_audited(
    books: Books, sender: FakeMailSender, client: TestClient, fake: FakeStorageProvider
):
    await _sent(books, sender, date(2026, 9, 1), date(2026, 10, 1))
    sender.sent.clear()
    cid = await _acme_id(books)
    j = client.get(f"/statements/{cid}", headers=H).json()
    assert j["closing_balance_pence"] == 40500 and j["contact"]["name"] == ACME["name"]
    assert client.get("/statements/nope", headers=H).status_code == 404

    pdf = client.post(f"/statements/{cid}/pdf", headers=H).json()
    assert base64.b64decode(pdf["data_url"].split(",", 1)[1]).startswith(b"%PDF")
    assert pdf["email"]["to"] == ACME["email"] and pdf["problems"] == []

    assert client.post(f"/statements/{cid}/send", headers=H, json={}).status_code == 400
    assert client.post(f"/statements/{cid}/send", headers=H, json={"confirm": "yes"}).status_code in (400, 422)
    assert sender.sent == []  # nothing goes without a real confirmation

    r = client.post(f"/statements/{cid}/send", headers=H, json={"confirm": True})
    assert r.status_code == 200, r.text
    (mail,) = sender.sent
    assert mail.to == ACME["email"] and mail.attachments[0].data.startswith(b"%PDF") and "405.00" in mail.body_text
    assert any(p.startswith(STATEMENTS) for p in fake.files)
    audit = [
        json.loads(x)
        for p, d in sorted(fake.files.items())
        if p.startswith(f"{AUDIT}/") and p.endswith(".jsonl")
        for x in d.decode().splitlines()
    ]
    sent = [a for a in audit if a["action"] == "statement_sent"]
    assert len(sent) == 1 and sent[0]["refs"]["closing_pence"] == 40500 and sent[0]["refs"]["to"] == ACME["email"]


async def test_statement_send_refuses_a_bad_address(books: Books, sender: FakeMailSender, client: TestClient):
    await _sent(books, sender, date(2026, 9, 1), date(2026, 10, 1))
    sender.sent.clear()
    cid = await _acme_id(books)
    r = client.post(f"/statements/{cid}/send", headers=H, json={"confirm": True, "to": "not-an-email"})
    assert r.status_code == 400 and sender.sent == []
