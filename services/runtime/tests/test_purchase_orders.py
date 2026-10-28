"""Purchase orders: PO-0001 numbering, approve then send, Convert to bill (a pre-filled proposal for the user to
approve) keeping lines, VAT and totals exactly, and matching a received supplier bill (app/purchase_orders.py,
app/bills.py, /purchase-orders/*)."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeMailSender, FakeStorageProvider
from app import approve as approve_
from app import bills
from app import invoicing as inv_
from app import items as it_
from app import purchase_orders as po_
from app.books import AUDIT, Books
from app.books import today as london_today
from app.invoicing import PROFILE, InvoiceError, InvoiceProfile, InvoiceStateError, LineIn
from app.journal import CREDITORS, VAT_CONTROL
from app.purchase_orders import ORDERS, ORDERS_SENT, SEQUENCE, PurchaseOrderDraft

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
PROFILE_JSON = {"name": "Sam Builds Ltd", "address": "1 High Street\nLeeds LS1 1AA", "vrn": "GB 123 4567 89"}
SUPPLIER = {
    "name": "Travis Perkins Ltd",
    "email": "orders@tp.example",
    "address": "5 Yard Lane\nLeeds",
    "vrn": "GB 220 4301 82",
}
TODAY = london_today()
LINES = [
    {
        "description": "Plasterboard 12.5mm",
        "quantity": "40",
        "unit": "sheets",
        "unit_price_pence": 899,
        "vat_code": "S",
    },
    {"description": "Screws", "quantity": "3", "unit_price_pence": 333, "vat_code": "S", "item_code": "SCREW"},
    {"description": "Insulation roll", "quantity": "2.5", "unit_price_pence": 1234, "vat_code": "R"},
    {"description": "Delivery", "quantity": "1", "unit_price_pence": 1500, "vat_code": "Z"},
]


def _draft(**kw) -> PurchaseOrderDraft:
    return PurchaseOrderDraft.model_validate(
        {"supplier": SUPPLIER, "issue_date": TODAY.isoformat(), "lines": LINES, "reference": "Job 14", **kw}
    )


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


async def _approved(books: Books, **kw):
    po = await po_.create_order(books, _draft(**kw), USER)
    return await po_.approve_order(books, po.number, USER)


async def _received_bill(books: Books, *, gross_lines: list[dict] | None = None, name: str = "Travis Perkins Ltd"):
    """A bill that arrived by scan: a proposal in Review (written here without the model)."""
    lines = [LineIn.model_validate(ln) for ln in (gross_lines or LINES)]
    return await bills.make_bill_proposal(
        books,
        pid=bills.proposal_id("scan", name, str(len(lines)), str(sum(ln.unit_price_pence for ln in lines))),
        evidence=f"scan:{name}:{lines}",
        source="scan.jpg",
        note="test",
        supplier_name=name,
        contact_id=None,
        supplier_vat_number=SUPPLIER["vrn"],
        bill_date=TODAY,
        lines=lines,
        account=None,
        model="test",
    )


# --------------------------------------------------------------------------- #
# Numbering, pricing, lifecycle
# --------------------------------------------------------------------------- #


async def test_numbers_run_po_0001_and_are_priced_in_pence(books: Books, fake: FakeStorageProvider):
    a = await po_.create_order(books, _draft(), USER)
    b = await po_.create_order(books, _draft(), USER)
    assert (a.number, b.number) == ("PO-0001", "PO-0002")
    assert json.loads(fake.files[SEQUENCE]) == {"prefix": "PO-", "next": 3}
    _, _, net, vat = inv_.price_lines([LineIn.model_validate(ln) for ln in LINES])
    assert (a.net_pence, a.vat_pence, a.total_pence) == (net, vat, net + vat)
    # 40 x 8.99 = 359.60 (+71.92); 3 x 3.33 = 9.99 (+2.00); 2.5 x 12.34 = 30.85 (5%: 1.54, from 1.5425); 15.00 zero
    assert a.net_pence == 35960 + 999 + 3085 + 1500
    assert a.vat_pence == 7192 + 200 + 154
    assert [o.number for o in await po_.list_orders(books)] == [
        "PO-0002",
        "PO-0001",
    ]  # the sequence file is not an order
    assert a.status == "draft" and a.created_by == USER


async def test_the_lifecycle_is_draft_approved_sent_and_a_draft_alone_can_be_edited(
    books: Books, sender: FakeMailSender, fake: FakeStorageProvider
):
    po = await po_.create_order(books, _draft(), USER)
    pdf = po_.render_order(po, await inv_.load_profile(books))
    with pytest.raises(InvoiceStateError, match="approve it first"):
        await po_.send_order(books, sender, po.number, USER, pdf)
    changed = await po_.update_draft(books, po.number, _draft(reference="Job 15"), USER)
    assert changed.reference == "Job 15"
    approved = await po_.approve_order(books, po.number, USER)
    assert approved.status == "approved" and approved.approved_by == USER
    with pytest.raises(InvoiceStateError, match="only drafts"):
        await po_.update_draft(books, po.number, _draft(), USER)
    with pytest.raises(InvoiceStateError, match="only a draft"):
        await po_.approve_order(books, po.number, USER)
    sent = await po_.send_order(books, sender, po.number, USER, pdf)
    assert sent.status == "sent" and sent.sent_to == "orders@tp.example"
    (mail,) = sender.sent
    assert mail.to == "orders@tp.example" and "PO-0001" in mail.subject and mail.attachments[0].name == "PO-0001.pdf"
    assert fake.files[f"{ORDERS_SENT}/PO-0001.pdf"] == mail.attachments[0].data
    assert await books.list_events() == []  # an order is not a cost
    for action in ("purchase_order_created", "purchase_order_approved", "purchase_order_sent"):
        assert action in _audit(fake)
    with pytest.raises(InvoiceStateError, match="is sent"):
        await po_.send_order(books, sender, po.number, USER, pdf)
    assert len(sender.sent) == 1


async def test_send_needs_a_supplier_email(books: Books, sender: FakeMailSender):
    po = await _approved(books, supplier={**SUPPLIER, "email": None})
    with pytest.raises(InvoiceError, match="supplier's email"):
        await po_.send_order(books, sender, po.number, USER, b"%PDF")
    assert sender.sent == []
    sent = await po_.mark_sent(books, po.number, USER)  # given over the phone
    assert sent.status == "sent" and sent.sent_to is None


async def test_bad_dates_and_accounts_are_refused_before_a_number_is_used(books: Books, fake: FakeStorageProvider):
    with pytest.raises(InvoiceError, match="before the order date"):
        await po_.create_order(books, _draft(delivery_date=(TODAY - timedelta(days=1)).isoformat()), USER)
    with pytest.raises(InvoiceError, match="expense account"):
        await po_.create_order(books, _draft(account="1200 Bank"), USER)
    assert SEQUENCE not in fake.files


async def test_cancel_keeps_the_number(books: Books):
    po = await _approved(books)
    with pytest.raises(InvoiceError, match="Say why"):
        await po_.cancel_order(books, po.number, USER, " ")
    cancelled = await po_.cancel_order(books, po.number, USER, "Supplier out of stock")
    assert cancelled.status == "cancelled"
    assert (await po_.create_order(books, _draft(), USER)).number == "PO-0002"
    with pytest.raises(InvoiceStateError, match="cannot be cancelled"):
        await po_.cancel_order(books, po.number, USER, "again")


# --------------------------------------------------------------------------- #
# Convert to bill
# --------------------------------------------------------------------------- #


async def test_convert_to_bill_keeps_lines_vat_and_totals_exactly_and_posts_nothing(
    books: Books, fake: FakeStorageProvider
):
    await it_.create_item(
        books,
        it_.ItemIn(
            code="SCREW", name="Screws", purchase_price_pence=333, expense_account="5100 Tools & small equipment"
        ),
        USER,
    )
    po = await _approved(books)
    po, p = await po_.convert_to_bill(books, po.number, USER)
    assert po.status == "billed" and po.bill and po.bill.proposal_id == p.id and po.bill.kind == "converted"
    d = p.extracted
    assert p.status == "proposed" and d.doc_type == "purchase_invoice" and d.currency == "GBP"
    assert d.supplier_name == "Travis Perkins Ltd" and d.supplier_vat_number == "GB220430182"
    assert [(ln.description, ln.qty, ln.unit_price, ln.net, ln.vat_rate, ln.vat) for ln in d.lines] == [
        ("Plasterboard 12.5mm", 40.0, 8.99, 359.60, 20, 71.92),
        ("Screws", 3.0, 3.33, 9.99, 20, 2.00),
        ("Insulation roll", 2.5, 12.34, 30.85, 5, 1.54),
        ("Delivery", 1.0, 15.00, 15.00, 0, 0.0),
    ]
    assert round(d.net_total * 100) == po.net_pence and round(d.vat_total * 100) == po.vat_pence
    assert round(d.gross_total * 100) == po.total_pence
    assert p.source_name == "Purchase order PO-0001" and p.model == "code:purchase-order"
    assert all(c.ok for c in p.checks if c.severity == "fail"), [c for c in p.checks if not c.ok]
    assert p.account_override == "5100 Tools & small equipment"  # from the item on the one catalogue line
    assert await books.list_events() == []  # waiting in Review, not posted
    assert [x.id for x in await books.list_proposals("proposed")] == [p.id]
    assert "purchase_order_converted" in _audit(fake)

    # The user approves it in Review: the ledger gets exactly the order's figures, owed to the supplier.
    await approve_.approve(books, p.id, USER)
    (event,) = await books.list_events()
    assert event.kind == "purchase" and event.counterparty == "Travis Perkins Ltd"
    assert sum(ln.debit for ln in event.lines) == po.total_pence == sum(ln.credit for ln in event.lines)
    assert next(ln.credit for ln in event.lines if ln.account == CREDITORS) == po.total_pence
    assert sum(ln.debit for ln in event.lines if ln.account == VAT_CONTROL) == po.vat_pence
    assert {ln.account for ln in event.lines if ln.debit} == {"5100 Tools & small equipment", VAT_CONTROL}


async def test_convert_uses_the_orders_account_over_the_items_and_needs_an_approved_order(books: Books):
    draft = await po_.create_order(books, _draft(account="5000 Materials"), USER)
    with pytest.raises(InvoiceStateError, match="is draft"):
        await po_.convert_to_bill(books, draft.number, USER)
    await po_.approve_order(books, draft.number, USER)
    _, p = await po_.convert_to_bill(books, draft.number, USER, bill_date=TODAY - timedelta(days=2))
    assert p.account_override == "5000 Materials" and p.extracted.date == (TODAY - timedelta(days=2)).isoformat()
    assert p.journal_draft[0].account == "5000 Materials"


async def test_a_supplier_without_a_vat_number_makes_a_bill_that_needs_a_look(books: Books):
    po = await _approved(books, supplier={"name": "Cash Merchant", "email": "a@b.example"})
    _, p = await po_.convert_to_bill(books, po.number, USER)
    assert p.status == "needs_a_look" and any("VAT_NUMBER_REQUIRED" in r for r in p.reasons)


async def test_the_supplier_vat_number_comes_from_the_contact_book(books: Books):
    await books.write_json(
        inv_.CONTACTS,
        [
            {
                "id": "c1",
                "kind": "supplier",
                "name": "Travis Perkins Ltd",
                "vrn": "GB 220 4301 82",
                "email": "x@y.example",
            }
        ],
    )
    po = await _approved(books, supplier={"name": "Travis Perkins Ltd", "contact_id": "c1"})
    assert po.supplier.email == "x@y.example"
    _, p = await po_.convert_to_bill(books, po.number, USER)
    assert p.extracted.supplier_vat_number == "GB220430182"


async def test_convert_once_then_again_after_the_bill_is_rejected_and_unlinked(books: Books):
    po = await _approved(books)
    _, first = await po_.convert_to_bill(books, po.number, USER)
    with pytest.raises(InvoiceStateError, match="already has a bill"):
        await po_.convert_to_bill(books, po.number, USER)
    await approve_.reject(books, first.id, USER, "wrong")
    unlinked = await po_.unlink_bill(books, po.number, USER)
    assert unlinked.status == "approved" and unlinked.bill is None
    _, second = await po_.convert_to_bill(books, po.number, USER)
    assert second.id != first.id and second.status == "proposed"


async def test_a_posted_bill_cannot_be_unlinked_until_undone(books: Books):
    po = await _approved(books)
    _, p = await po_.convert_to_bill(books, po.number, USER)
    await approve_.approve(books, p.id, USER)
    with pytest.raises(InvoiceStateError, match="undo it in Review"):
        await po_.unlink_bill(books, po.number, USER)
    with pytest.raises(InvoiceStateError, match="cannot be cancelled|unlink"):
        await po_.cancel_order(books, po.number, USER, "x")


# --------------------------------------------------------------------------- #
# Match a received bill
# --------------------------------------------------------------------------- #


async def test_candidates_list_the_suppliers_bills_exact_totals_first(books: Books):
    po = await _approved(books)
    exact = await _received_bill(books)
    more = await _received_bill(
        books, gross_lines=[*LINES, {"description": "Fuel", "quantity": "1", "unit_price_pence": 500}]
    )
    await _received_bill(books, name="Someone Else Ltd")
    got = await po_.bill_candidates(books, po.number)
    assert [c.proposal_id for c in got] == [exact.id, more.id]
    assert got[0].exact and got[0].variance_pence == 0
    assert not got[1].exact and got[1].variance_pence == 600  # £5.00 + 20% VAT


async def test_match_links_the_bill_with_its_variance_and_changes_nothing_else(books: Books, fake: FakeStorageProvider):
    po = await _approved(books)
    more = await _received_bill(
        books, gross_lines=[*LINES, {"description": "Fuel", "quantity": "1", "unit_price_pence": 500}]
    )
    matched = await po_.match_bill(books, po.number, more.id, USER)
    assert matched.status == "billed" and matched.bill and matched.bill.kind == "matched"
    row = (await po_.rows(books))[0]
    assert row.bill_now and row.bill_now.status == "proposed" and row.bill_now.variance_pence == 600
    assert (await books.get_proposal(more.id)).status == "proposed"  # still the user's to approve
    assert await books.list_events() == [] and "purchase_order_matched" in _audit(fake)
    with pytest.raises(InvoiceStateError, match="already has a bill"):
        await po_.match_bill(books, po.number, more.id, USER)
    other = await _approved(books)
    with pytest.raises(InvoiceStateError, match="already matched to PO-0001"):
        await po_.match_bill(books, other.number, more.id, USER)
    assert (await po_.bill_candidates(books, other.number))[0].linked_to == "PO-0001"


async def test_a_bill_from_another_supplier_or_a_draft_order_cannot_be_matched(books: Books):
    draft = await po_.create_order(books, _draft(), USER)
    bill = await _received_bill(books)
    with pytest.raises(InvoiceStateError, match="only an approved or sent order"):
        await po_.match_bill(books, draft.number, bill.id, USER)
    await po_.approve_order(books, draft.number, USER)
    other = await _received_bill(books, name="Someone Else Ltd")
    with pytest.raises(InvoiceError, match="from Someone Else Ltd, not Travis Perkins Ltd"):
        await po_.match_bill(books, draft.number, other.id, USER)
    with pytest.raises(InvoiceError, match="No such bill"):
        await po_.match_bill(books, draft.number, "0" * 16, USER)


async def test_unlinking_a_matched_unposted_bill_reopens_the_order(books: Books):
    po = await _approved(books)
    await po_.mark_sent(books, po.number, USER)
    bill = await _received_bill(books)
    await po_.match_bill(books, po.number, bill.id, USER)
    assert (await po_.unlink_bill(books, po.number, USER)).status == "sent"


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


def test_routes_full_flow(client: TestClient, sender: FakeMailSender, fake: FakeStorageProvider):
    body = _draft().model_dump(mode="json")
    made = client.post("/purchase-orders", json=body, headers=H)
    assert made.status_code == 200 and made.json()["number"] == "PO-0001"
    assert client.get("/purchase-orders/PO-0001", headers=H).json()["total_pence"] == made.json()["total_pence"]
    assert client.get("/purchase-orders/PO-9999", headers=H).status_code == 404
    pdf = client.post("/purchase-orders/PO-0001/pdf", headers=H).json()
    assert pdf["path"] == f"{ORDERS}/PO-0001.pdf" and pdf["problems"] == [
        "Purchase order PO-0001 is draft; approve it first"
    ]
    assert client.post("/purchase-orders/PO-0001/send", json={"confirm": True}, headers=H).status_code == 409
    assert client.post("/purchase-orders/PO-0001/approve", headers=H).json()["status"] == "approved"
    for bad in ({}, {"confirm": False}):
        assert client.post("/purchase-orders/PO-0001/send", json=bad, headers=H).status_code == 400
    assert sender.sent == []
    sent = client.post("/purchase-orders/PO-0001/send", json={"confirm": True}, headers=H)
    assert sent.status_code == 200 and sent.json()["status"] == "sent" and len(sender.sent) == 1

    out = client.post("/purchase-orders/PO-0001/convert-to-bill", json={}, headers=H)
    assert out.status_code == 200
    got = out.json()
    assert got["order"]["status"] == "billed" and got["order"]["bill_now"]["status"] == "proposed"
    assert got["order"]["bill_now"]["gross_pence"] == got["order"]["total_pence"]
    assert got["proposal"]["status"] == "proposed" and got["proposal"]["model"] == "code:purchase-order"
    assert client.post("/purchase-orders/PO-0001/convert-to-bill", json={}, headers=H).status_code == 409
    assert client.get("/purchase-orders/PO-0001", headers=H).json()["bill_now"]["proposal_id"] == got["proposal"]["id"]
    assert client.delete("/purchase-orders/PO-0001/bill", headers=H).json()["status"] == "sent"
    assert client.get("/purchase-orders/PO-0001/bill-candidates", headers=H).json()[0]["exact"] is True
    pid = got["proposal"]["id"]
    matched = client.post("/purchase-orders/PO-0001/match-bill", json={"proposal_id": pid}, headers=H)
    assert matched.status_code == 200 and matched.json()["bill_now"]["kind"] == "matched"
    assert client.post("/purchase-orders/PO-0001/match-bill", json={"proposal_id": "zz"}, headers=H).status_code == 422
    assert [o["number"] for o in client.get("/purchase-orders", headers=H).json()] == ["PO-0001"]


def test_routes_suppliers_cancel_and_edit(client: TestClient, books: Books):
    import asyncio

    asyncio.run(
        books.write_json(
            inv_.CONTACTS,
            [
                {"id": "s1", "kind": "supplier", "name": "Zed Supplies", "email": "z@z.example"},
                {"id": "c1", "kind": "customer", "name": "A Customer"},
                {"id": "b1", "kind": "both", "name": "Alpha Both"},
            ],
        )
    )
    assert [s["name"] for s in client.get("/purchase-orders/suppliers", headers=H).json()] == [
        "Alpha Both",
        "Zed Supplies",
    ]
    n = client.post("/purchase-orders", json=_draft().model_dump(mode="json"), headers=H).json()["number"]
    assert (
        client.put(f"/purchase-orders/{n}", json=_draft(reference="X").model_dump(mode="json"), headers=H).json()[
            "reference"
        ]
        == "X"
    )
    assert client.post(f"/purchase-orders/{n}/cancel", json={"reason": "no"}, headers=H).json()["status"] == "cancelled"
    assert client.put(f"/purchase-orders/{n}", json=_draft().model_dump(mode="json"), headers=H).status_code == 409


def test_order_pdf_names_the_supplier_and_total(books: Books):
    import asyncio
    import re
    import zlib

    po = asyncio.run(po_.create_order(books, _draft(delivery_address="Unit 3\nLeeds"), USER))
    data = po_.render_order(po, InvoiceProfile.model_validate(PROFILE_JSON))
    words = b"".join(zlib.decompress(s) for s in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", data, flags=16))
    for needle in (b"PURCHASE ORDER", b"SUPPLIER", b"DELIVER TO", b"Travis Perkins Ltd", b"PO-0001"):
        assert needle in words
