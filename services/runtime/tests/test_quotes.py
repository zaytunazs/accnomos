"""Quotes: numbering QU-0001, pricing, send behind a confirmation, accepted / declined / expired, and Convert to
invoice keeping the lines, VAT and totals exactly (app/quotes.py, /quotes/*)."""

from __future__ import annotations

import base64
import json
import re
import zlib
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeMailSender, FakeStorageProvider
from app import invoicing as inv_
from app import quotes as q_
from app.books import AUDIT, Books
from app.books import today as london_today
from app.invoicing import PROFILE, InvoiceError, InvoiceProfile, InvoiceStateError
from app.quotes import QUOTES, QUOTES_SENT, SEQUENCE, QuoteDraft

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
PROFILE_JSON = {
    "name": "Sam Builds Ltd",
    "address": "1 High Street\nLeeds LS1 1AA",
    "vrn": "GB 123 4567 89",
}
CUSTOMER = {"name": "Acme Kitchens Ltd", "email": "accounts@acme.example", "address": "2 Low Road\nYork"}
TODAY = london_today()  # the runtime's own clock: a quote's expiry is checked against it when it is sent
# Lines picked to be awkward: 7.5 x 45.00 (337.50 + 67.50), 3 x 3.33 (9.99 + 2.00 from 1.998), a 5% line, a zero-rated
# line, an exempt line, and a discount.
LINES = [
    {"description": "Labour", "quantity": "7.5", "unit": "hours", "unit_price_pence": 4500, "vat_code": "S"},
    {"description": "Fixings", "quantity": "3", "unit_price_pence": 333, "vat_code": "S", "item_code": "FIX-1"},
    {"description": "Boiler cover", "quantity": "1", "unit_price_pence": 12345, "vat_code": "R"},
    {"description": "Books", "quantity": "2.5", "unit_price_pence": 799, "vat_code": "Z"},
    {"description": "Training", "quantity": "1", "unit_price_pence": 5000, "vat_code": "E"},
    {"description": "Loyalty discount", "quantity": "1", "unit_price_pence": -1000, "vat_code": "S"},
]


def _draft(**kw) -> QuoteDraft:
    return QuoteDraft.model_validate(
        {"customer": CUSTOMER, "issue_date": TODAY.isoformat(), "lines": LINES, "reference": "Kitchen", **kw}
    )


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


def _audit(fake: FakeStorageProvider) -> list[str]:
    return [
        json.loads(x)["action"]
        for p, d in sorted(fake.files.items())
        if p.startswith(f"{AUDIT}/") and p.endswith(".jsonl")
        for x in d.decode().splitlines()
    ]


async def _sent(books: Books, sender: FakeMailSender, **kw):
    q = await q_.create_quote(books, _draft(**kw), USER)
    profile = await inv_.load_profile(books)
    return await q_.send_quote(books, sender, q.number, USER, q_.render_quote(q, profile))


# --------------------------------------------------------------------------- #
# Numbering and pricing
# --------------------------------------------------------------------------- #


async def test_numbers_run_qu_0001_and_are_never_reused(books: Books, fake: FakeStorageProvider):
    a = await q_.create_quote(books, _draft(), USER)
    b = await q_.create_quote(books, _draft(), USER)
    assert (a.number, b.number) == ("QU-0001", "QU-0002")
    assert json.loads(fake.files[SEQUENCE]) == {"prefix": "QU-", "next": 3}
    # a sequence file edited backwards skips numbers that already have a quote
    fake.files[SEQUENCE] = b'{"prefix": "QU-", "next": 1}'
    assert (await q_.create_quote(books, _draft(), USER)).number == "QU-0003"
    assert [q.number for q in await q_.list_quotes(books)] == ["QU-0003", "QU-0002", "QU-0001"]


async def test_invoices_and_quotes_number_separately(books: Books):
    q = await q_.create_quote(books, _draft(), USER)
    inv = await inv_.create_invoice(books, q_.invoice_draft_from(q), USER)
    assert (q.number, inv.number) == ("QU-0001", "INV-0001")


async def test_priced_like_an_invoice_in_pence(books: Books):
    q = await q_.create_quote(books, _draft(), USER)
    inv_lines, summary, net, vat = inv_.price_lines([inv_.LineIn(**ln) for ln in LINES])
    assert [ln.net_pence for ln in q.lines] == [ln.net_pence for ln in inv_lines]
    assert (q.net_pence, q.vat_pence, q.total_pence) == (net, vat, net + vat)
    assert [r.model_dump() for r in q.vat_summary] == [r.model_dump() for r in summary]
    # 33750 + 999 + 12345 + 1998 (2.5 x 7.99 = 19.975 -> 1998) + 5000 - 1000
    assert q.net_pence == 33750 + 999 + 12345 + 1998 + 5000 - 1000
    assert q.expiry_date == TODAY + timedelta(days=30)
    assert q.status == "draft" and q.lines[1].item_code == "FIX-1"


async def test_a_bad_draft_does_not_use_up_a_number(books: Books, fake: FakeStorageProvider):
    with pytest.raises(InvoiceError, match="before the quote date"):
        await q_.create_quote(books, _draft(expiry_date="2026-10-01"), USER)
    assert SEQUENCE not in fake.files
    assert (await q_.create_quote(books, _draft(), USER)).number == "QU-0001"


async def test_only_a_draft_can_be_changed(books: Books, sender: FakeMailSender):
    q = await q_.create_quote(books, _draft(), USER)
    changed = await q_.update_draft(books, q.number, _draft(reference="Changed"), USER)
    assert changed.reference == "Changed" and changed.created_at == q.created_at
    await _sent(books, sender)  # QU-0002
    with pytest.raises(InvoiceStateError, match="only drafts"):
        await q_.update_draft(books, "QU-0002", _draft(), USER)


# --------------------------------------------------------------------------- #
# Sending, decisions, expiry
# --------------------------------------------------------------------------- #


async def test_sending_emails_the_pdf_and_stores_the_exact_copy(
    books: Books, sender: FakeMailSender, fake: FakeStorageProvider
):
    q = await _sent(books, sender)
    assert q.status == "sent" and q.sent_to == "accounts@acme.example" and q.sent_by == USER
    (mail,) = sender.sent
    assert mail.to == "accounts@acme.example" and "QU-0001" in mail.subject
    assert mail.attachments[0].name == "QU-0001.pdf"
    assert fake.files[f"{QUOTES_SENT}/QU-0001.pdf"] == mail.attachments[0].data
    assert "quote_sent" in _audit(fake)
    assert b"QUOTE" in _words(mail.attachments[0].data) and b"Valid until" in _words(mail.attachments[0].data)
    # nothing posts to the books: a quote is an offer
    assert await books.list_events() == []


async def test_a_sent_quote_is_not_sent_twice_and_a_bad_draft_is_not_sent(books: Books, sender: FakeMailSender):
    await _sent(books, sender)
    with pytest.raises(InvoiceStateError, match="already sent"):
        await q_.send_quote(books, sender, "QU-0001", USER, b"%PDF")
    assert len(sender.sent) == 1
    no_email = await q_.create_quote(books, _draft(customer={"name": "No Email Ltd"}), USER)
    with pytest.raises(InvoiceError, match="email address"):
        await q_.send_quote(books, sender, no_email.number, USER, b"%PDF")
    assert len(sender.sent) == 1


async def test_accept_decline_and_expiry(books: Books, sender: FakeMailSender):
    draft = await q_.create_quote(books, _draft(), USER)
    with pytest.raises(InvoiceStateError, match="draft"):
        await q_.decide(books, draft.number, USER, "accepted")
    sent = await _sent(books, sender)
    assert sent.effective_status(TODAY) == "sent"
    assert sent.effective_status(TODAY + timedelta(days=31)) == "expired"
    assert sent.effective_status(TODAY + timedelta(days=30)) == "sent"  # good through its expiry date
    accepted = await q_.decide(books, sent.number, USER, "accepted")
    assert accepted.status == "accepted" and accepted.decided_by == USER
    assert accepted.effective_status(TODAY + timedelta(days=90)) == "accepted"
    with pytest.raises(InvoiceStateError, match="already accepted"):
        await q_.decide(books, sent.number, USER, "declined")
    declined = await q_.decide(books, draft.number, USER, "declined")  # a draft can be dropped
    assert declined.status == "declined"


async def test_an_expired_quote_can_still_be_answered_and_converted(books: Books, sender: FakeMailSender):
    q = await q_.mark_sent(
        books,
        (await q_.create_quote(books, _draft(issue_date="2026-01-01", expiry_date="2026-01-31"), USER)).number,
        USER,
    )
    row = q_.row(q, TODAY)
    assert row.status == "expired" and row.days_to_expiry is None
    done, inv = await q_.convert_to_invoice(books, q.number, USER)
    assert inv.total_pence == q.total_pence and done.invoice_number == inv.number


# --------------------------------------------------------------------------- #
# Convert to invoice
# --------------------------------------------------------------------------- #


async def test_convert_keeps_lines_vat_and_totals_exactly(books: Books, sender: FakeMailSender, fake):
    q = await _sent(books, sender)
    await q_.decide(books, q.number, USER, "accepted")
    q, inv = await q_.convert_to_invoice(books, q.number, USER, issue_date=TODAY + timedelta(days=5))
    assert inv.number == "INV-0001" and inv.status == "draft" and inv.issue_date == TODAY + timedelta(days=5)
    assert q.invoice_number == "INV-0001" and q.converted_at is not None
    assert [
        (ln.description, ln.quantity, ln.unit, ln.unit_price_pence, ln.vat_code, ln.item_code) for ln in inv.lines
    ] == [(ln.description, ln.quantity, ln.unit, ln.unit_price_pence, ln.vat_code, ln.item_code) for ln in q.lines]
    assert [ln.net_pence for ln in inv.lines] == [ln.net_pence for ln in q.lines]
    assert [ln.vat_pence for ln in inv.lines] == [ln.vat_pence for ln in q.lines]
    assert [r.model_dump() for r in inv.vat_summary] == [r.model_dump() for r in q.vat_summary]
    assert (inv.net_pence, inv.vat_pence, inv.total_pence) == (q.net_pence, q.vat_pence, q.total_pence)
    assert inv.customer == q.customer and inv.reference == "Kitchen"
    assert await books.list_events() == []  # a draft invoice posts nothing; sending it is the usual confirmed step
    assert "quote_converted" in _audit(fake)


async def test_convert_once_only_and_not_from_a_draft_or_declined_quote(books: Books, sender: FakeMailSender):
    draft = await q_.create_quote(books, _draft(), USER)
    with pytest.raises(InvoiceStateError, match="draft"):
        await q_.convert_to_invoice(books, draft.number, USER)
    sent = await _sent(books, sender)  # QU-0002
    await q_.convert_to_invoice(books, sent.number, USER)  # a sent quote may be converted without a formal accept
    with pytest.raises(InvoiceStateError, match="already become invoice INV-0001"):
        await q_.convert_to_invoice(books, sent.number, USER)
    with pytest.raises(InvoiceStateError, match="has become invoice"):
        await q_.decide(books, sent.number, USER, "declined")
    no = await q_.decide(books, draft.number, USER, "declined")
    with pytest.raises(InvoiceStateError, match="is declined"):
        await q_.convert_to_invoice(books, no.number, USER)


async def test_a_converted_invoice_sends_and_posts_the_quotes_total(books: Books, sender: FakeMailSender):
    q = await _sent(books, sender)
    _, inv = await q_.convert_to_invoice(books, q.number, USER, issue_date=TODAY)
    from app.pdf import render_invoice

    pdf = render_invoice(inv, await inv_.load_profile(books))
    sent = await inv_.send_invoice(books, sender, inv.number, USER, pdf)
    (event,) = await books.list_events()
    assert sent.status == "sent" and sum(ln.debit for ln in event.lines) == q.total_pence


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


def test_routes_full_flow(client: TestClient, sender: FakeMailSender, fake: FakeStorageProvider):
    body = _draft().model_dump(mode="json")
    made = client.post("/quotes", json=body, headers=H)
    assert made.status_code == 200 and made.json()["number"] == "QU-0001"
    assert client.get("/quotes/QU-0001", headers=H).json()["total_pence"] == made.json()["total_pence"]
    assert client.get("/quotes/NOPE-9", headers=H).status_code == 404
    assert client.get("/quotes/..%2Fx", headers=H).status_code == 404

    pdf = client.post("/quotes/QU-0001/pdf", headers=H).json()
    assert pdf["path"] == f"{QUOTES}/QU-0001.pdf" and pdf["problems"] == []
    assert pdf["email"]["to"] == "accounts@acme.example" and "QU-0001" in pdf["email"]["subject"]
    assert base64.b64decode(pdf["data_url"].split(",", 1)[1]).startswith(b"%PDF")

    for bad in ({}, {"confirm": False}, {"confirm": "yes"}):
        assert client.post("/quotes/QU-0001/send", json=bad, headers=H).status_code in (400, 422)
    assert sender.sent == []
    sent = client.post("/quotes/QU-0001/send", json={"confirm": True}, headers=H)
    assert sent.status_code == 200 and sent.json()["status"] == "sent" and len(sender.sent) == 1
    assert client.post("/quotes/QU-0001/send", json={"confirm": True}, headers=H).status_code == 409
    assert client.put("/quotes/QU-0001", json=body, headers=H).status_code == 409

    assert client.post("/quotes/QU-0001/accept", headers=H).json()["status"] == "accepted"
    out = client.post("/quotes/QU-0001/convert", json={}, headers=H)
    assert out.status_code == 200
    got = out.json()
    assert got["invoice"]["number"] == "INV-0001" and got["invoice"]["total_pence"] == got["quote"]["total_pence"]
    assert got["quote"]["invoice_number"] == "INV-0001"
    assert client.post("/quotes/QU-0001/convert", json={}, headers=H).status_code == 409
    assert client.get("/invoices/INV-0001", headers=H).json()["status"] == "draft"
    assert [q["number"] for q in client.get("/quotes", headers=H).json()] == ["QU-0001"]


def test_routes_mark_sent_decline_and_expired_reads_as_expired(client: TestClient):
    old = _draft(issue_date="2026-01-01", expiry_date="2026-01-31").model_dump(mode="json")
    n = client.post("/quotes", json=old, headers=H).json()["number"]
    assert client.post(f"/quotes/{n}/mark-sent", headers=H).json()["status"] == "expired"  # past its date today
    assert client.post(f"/quotes/{n}/decline", headers=H).json()["status"] == "declined"
    assert client.post(f"/quotes/{n}/mark-sent", headers=H).status_code == 409


def test_quote_pdf_names_the_customer_and_total(books: Books):
    import asyncio

    q = asyncio.run(_make(books))
    data = q_.render_quote(q, InvoiceProfile.model_validate(PROFILE_JSON))
    words = _words(data)
    assert b"Acme Kitchens Ltd" in words and b"PREPARED FOR" in words and b"QU-0001" in words


async def _make(books: Books):
    return await q_.create_quote(books, _draft(), USER)
