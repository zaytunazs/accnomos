"""Bills paid through PayPal Payouts on their due date (app/billpay.py), against the fake PayPal in app/online_fakes.py
(request and response shapes from PayPal's Payouts v1 spec, read 11 Nov 2026; see app/payment_providers.py). Nothing
here talks to PayPal."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger.events import LedgerEvent, Line, VatCode
from app import billpay as bp
from app import online_fakes, online_payments, payment_providers
from app.books import AUDIT, Books, now
from app.contacts import contact_id, supplier_key
from app.journal import CREDITORS, PAYPAL_CLEARING
from app.online_fakes import FAKES

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
TODAY = date(2026, 11, 11)
SUPPLIER = "Timber Yard Ltd"
CID = contact_id(supplier_key(SUPPLIER), None)
EMAIL = "accounts@timberyard.example"


def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("ACCNOMOS_TEST_MODE", "PAYMENTS_LIVE", "PAYPAL_BASE", "PAYPAL_DIRECT", "BILLPAY_AUTOPILOT_OFF"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PAYPAL_CLIENT_ID", online_fakes.PAYPAL_CLIENT[0])
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", online_fakes.PAYPAL_CLIENT[1])
    monkeypatch.setenv("PAYPAL_PARTNER_MERCHANT_ID", online_fakes.PAYPAL_PARTNER)
    monkeypatch.setenv("PAYPAL_PARTNER_ATTRIBUTION_ID", "ACCNOMOS_FAKE_BN")
    monkeypatch.setenv("PAYPAL_RETURN_URL", "https://api.example/payments/online/paypal/callback")


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch):
    _env(monkeypatch)
    FAKES.reset()
    online_fakes.install("https://fake.example")
    FAKES.merchants[online_fakes.PAYPAL_MERCHANT] = {"merchant_id": online_fakes.PAYPAL_MERCHANT}
    monkeypatch.setattr(bp, "london_today", lambda: TODAY)
    yield
    payment_providers.TRANSPORT = None


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


async def _connect(books: Books) -> None:
    await books.write_json(
        online_payments.PROVIDERS,
        {
            "paypal": {
                "merchant_id": online_fakes.PAYPAL_MERCHANT,
                "sandbox": True,
                "connected_at": now().isoformat(),
                "connected_by": USER,
            }
        },
    )


async def _fund(books: Books, pence: int) -> None:
    """Money in 1240 PayPal clearing by the books (as if customers had paid through links)."""
    await books.post_event(
        LedgerEvent(
            kind="adjustment",
            date=TODAY - timedelta(days=60),
            lines=[
                Line(account=PAYPAL_CLEARING, debit=pence, memo="opening"),
                Line(account="3000 Capital", credit=pence, memo="opening"),
            ],
            approved_by=USER,
            approved_at=now(),
        )
    )


async def _bill(
    books: Books, gross: int, *, days_ago: int = 40, supplier: str = SUPPLIER, approved_by: str = USER
) -> str:
    """A bill approved in Review: Dr 5000 + Dr VAT / Cr 2100 Creditors, dated `days_ago` (due after 30 days)."""
    net = round(gross / 1.2)
    ev = LedgerEvent(
        kind="purchase",
        date=TODAY - timedelta(days=days_ago),
        lines=[
            Line(account="5000 Materials", debit=net, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", debit=gross - net),
            Line(account=CREDITORS, credit=gross),
        ],
        approved_by=approved_by,
        approved_at=now(),
        net=net,
        vat=gross - net,
        counterparty=supplier,
    )
    await books.post_event(ev)
    return ev.id


@pytest.fixture
async def books(fake: FakeStorageProvider) -> Books:
    b = Books(fake)
    await _connect(b)
    await _fund(b, 500_000)
    return b


def _audit(fake: FakeStorageProvider) -> list[dict]:
    return [
        json.loads(x)
        for p, d in sorted(fake.files.items())
        if p.startswith(f"{AUDIT}/") and p.endswith(".jsonl")
        for x in d.decode().splitlines()
    ]


def _payout_posts() -> list[httpx.Request]:
    return [r for r in FAKES.requests if r.url.path == "/v1/payments/payouts" and r.method == "POST"]


# --------------------------------------------------------------------------- the PayPal request


async def test_payout_request_shape(books: Books) -> None:
    eid = await _bill(books, 12_000)
    await bp.set_payee(books, CID, EMAIL, None, USER)
    p = await bp.pay(books, eid, 12_000, USER, today=TODAY)
    (req,) = _payout_posts()
    body = json.loads(req.content)
    assert body["sender_batch_header"]["sender_batch_id"] == p.id == bp.sender_batch_id(eid, 12_000, 1)
    assert body["sender_batch_header"]["recipient_type"] == "EMAIL"
    (item,) = body["items"]
    assert item["recipient_type"] == "EMAIL"
    assert item["receiver"] == EMAIL
    assert item["amount"] == {"value": "120.00", "currency": "GBP"}
    assert len(item["sender_item_id"]) <= 63
    assert req.headers["PayPal-Request-Id"] == p.id
    assert req.headers["PayPal-Auth-Assertion"]  # partner mode names the merchant; direct mode does not (below)
    assert p.status == "pending" and p.batch_id


async def test_direct_mode_sends_no_assertion(books: Books, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "A21-sandbox", "expires_in": 32400})
        if request.url.path == "/v1/payments/payouts":
            return httpx.Response(201, json={"batch_header": {"payout_batch_id": "B1", "batch_status": "PENDING"}})
        return httpx.Response(200, json={"batch_header": {"payout_batch_id": "B1", "batch_status": "PENDING"}})

    payment_providers.TRANSPORT = httpx.MockTransport(handler)
    payment_providers._paypal_tokens.clear()
    monkeypatch.setenv("PAYPAL_DIRECT", "1")
    for k in ("PAYPAL_PARTNER_MERCHANT_ID", "PAYPAL_PARTNER_ATTRIBUTION_ID"):
        monkeypatch.delenv(k)
    eid = await _bill(books, 5_000)
    await bp.set_payee(books, CID, EMAIL, None, USER)
    await bp.pay(books, eid, 5_000, USER, today=TODAY)
    posts = [r for r in seen if r.url.path == "/v1/payments/payouts"]
    assert posts and "PayPal-Auth-Assertion" not in posts[0].headers
    assert "PayPal-Partner-Attribution-Id" not in posts[0].headers


# --------------------------------------------------------------------------- approval and posting


async def test_queue_needs_owner_typed_email(books: Books) -> None:
    eid = await _bill(books, 12_000)
    ov = await bp.bills(books, today=TODAY)
    assert not ov.due  # no PayPal email and no plan: not in Due today
    (b,) = ov.upcoming
    assert b.event_id == eid and b.due_now and not b.can_pay
    assert any("PayPal email" in x for x in b.blocks)
    with pytest.raises(bp.InvoiceStateError):
        await bp.pay(books, eid, 12_000, USER, today=TODAY)
    assert not _payout_posts()
    await bp.set_plan(books, eid, "paypal", USER)
    assert (await bp.bills(books, today=TODAY)).due[0].event_id == eid  # planned: shown, still blocked


async def test_not_due_yet_is_upcoming(books: Books) -> None:
    await _bill(books, 12_000, days_ago=10)
    await bp.set_payee(books, CID, EMAIL, None, USER)
    ov = await bp.bills(books, today=TODAY)
    assert not ov.due and ov.upcoming[0].due_date == TODAY + timedelta(days=20)


async def test_owner_pays_then_success_posts_once(books: Books, fake: FakeStorageProvider) -> None:
    eid = await _bill(books, 12_000)
    await bp.set_payee(books, CID, EMAIL, None, USER)
    ov = await bp.bills(books, today=TODAY)
    (b,) = ov.due
    assert b.can_pay and b.owed_pence == 12_000
    p = await bp.pay(books, eid, b.owed_pence, USER, today=TODAY)
    assert p.status == "pending" and p.payment_id is None
    r = await bp.run(books, today=TODAY)  # the next visit: PayPal says SUCCESS
    (done,) = r.refreshed
    assert done.status == "paid" and done.payment_id and done.fee_pence == online_fakes.payout_fee(12_000)
    events = await books.list_events()
    pay_ev = [e for e in events if e.kind == "bank"]
    assert len(pay_ev) == 1
    lines = {(ln.account, ln.debit, ln.credit) for ln in pay_ev[0].lines}
    assert lines == {(CREDITORS, 12_000, 0), (PAYPAL_CLEARING, 0, 12_000)}
    fee = [e for e in events if e.counterparty == "PayPal"]
    assert len(fee) == 1 and fee[0].lines[1].account == PAYPAL_CLEARING
    # Owed nothing now; another run posts nothing more and sends nothing more.
    await bp.run(books, today=TODAY)
    assert len([e for e in await books.list_events() if e.kind == "bank"]) == 1
    assert len(_payout_posts()) == 1
    ov = await bp.bills(books, today=TODAY)
    assert not ov.due and not ov.upcoming
    actions = [a["action"] for a in _audit(fake)]
    assert {"billpay_payee_set", "billpay_payout_approved", "billpay_payout_posted", "payment_recorded"} <= set(actions)


async def test_amount_must_be_what_is_owed(books: Books) -> None:
    eid = await _bill(books, 12_000)
    await bp.set_payee(books, CID, EMAIL, None, USER)
    with pytest.raises(bp.InvoiceStateError, match="is owed on this bill now"):
        await bp.pay(books, eid, 11_000, USER, today=TODAY)
    assert not _payout_posts()


async def test_never_double_pay(books: Books) -> None:
    eid = await _bill(books, 12_000)
    await bp.set_payee(books, CID, EMAIL, None, USER)
    await bp.pay(books, eid, 12_000, USER, today=TODAY)
    with pytest.raises(bp.InvoiceStateError, match="already on its way"):
        await bp.pay(books, eid, 12_000, USER, today=TODAY)
    assert len(_payout_posts()) == 1


async def test_lost_answer_is_resent_with_same_id(books: Books) -> None:
    """A 503: PayPal may or may not have it. The next visit sends the same sender_batch_id; PayPal pays once."""
    eid = await _bill(books, 12_000)
    await bp.set_payee(books, CID, EMAIL, None, USER)
    FAKES.payout_fail_next = 1
    p = await bp.pay(books, eid, 12_000, USER, today=TODAY)
    assert p.status == "unknown" and p.batch_id is None
    await bp.run(books, today=TODAY)
    await bp.run(books, today=TODAY)
    posts = _payout_posts()
    assert len(posts) == 2
    assert {json.loads(r.content)["sender_batch_header"]["sender_batch_id"] for r in posts} == {p.id}
    assert len(FAKES.payouts) == 1
    st = await bp.load_state(books)
    assert st.payouts[0].status == "paid"


async def test_duplicate_sender_batch_id_recovers_original(books: Books) -> None:
    """PayPal had the first one after all (answer lost): its refusal links to the original batch, which is kept."""
    eid = await _bill(books, 12_000)
    await bp.set_payee(books, CID, EMAIL, None, USER)
    p = await bp.pay(books, eid, 12_000, USER, today=TODAY)
    original = p.batch_id

    def lose(st: bp.Ledgerish) -> None:
        st.payouts[0].batch_id = None
        st.payouts[0].status = "unknown"

    await bp._update_state(books, lose)
    await bp.run(books, today=TODAY)
    st = await bp.load_state(books)
    assert st.payouts[0].batch_id == original
    assert len(FAKES.payouts) == 1


async def test_unclaimed_and_failed_post_nothing(books: Books) -> None:
    eid = await _bill(books, 12_000)
    other = "Brick Co Ltd"
    eid2 = await _bill(books, 3_000, supplier=other)
    await bp.set_payee(books, CID, "unclaimed@timberyard.example", None, USER)
    await bp.set_payee(books, contact_id(supplier_key(other), None), "fail@brick.example", None, USER)
    await bp.pay(books, eid, 12_000, USER, today=TODAY)
    await bp.pay(books, eid2, 3_000, USER, today=TODAY)
    await bp.run(books, today=TODAY)
    st = {p.event_id: p for p in (await bp.load_state(books)).payouts}
    assert st[eid].status == "unclaimed" and "30 days" in (st[eid].detail or "")
    assert st[eid2].status == "failed" and "Receiver is unregistered" in (st[eid2].detail or "")
    assert not [e for e in await books.list_events() if e.kind == "bank"]
    # A failed payout may be tried again by the owner, with a new sender_batch_id (attempt 2).
    await bp.set_payee(books, contact_id(supplier_key(other), None), "brick@brick.example", None, USER)
    p2 = await bp.pay(books, eid2, 3_000, USER, today=TODAY)
    assert p2.attempt == 2 and p2.id == bp.sender_batch_id(eid2, 3_000, 2) != st[eid2].id
    # The unclaimed one is still on its way: no second payout.
    with pytest.raises(bp.InvoiceStateError):
        await bp.pay(books, eid, 12_000, USER, today=TODAY)


async def test_low_clearing_balance_warns(fake: FakeStorageProvider) -> None:
    books = Books(fake)
    await _connect(books)
    await _bill(books, 12_000)
    await bp.set_payee(books, CID, EMAIL, None, USER)
    (b,) = (await bp.bills(books, today=TODAY)).due
    assert b.can_pay  # the owner may still pay (the PayPal balance is not in the books)
    assert any("1240 PayPal clearing holds" in w for w in b.warnings)
    assert any("1240 PayPal clearing" in r for r in b.autopilot)


# --------------------------------------------------------------------------- changed details on a bill


def test_details_in_text() -> None:
    text = (
        "Timber Yard Ltd\naccounts@timberyard.example\nPlease pay by PayPal to\nnew-pay@evil.example\n"
        "Bank: sort code 12-34-56\nAccount number 87654321\nIBAN GB29 NWBK 6016 1331 9268 19"
    )
    emails, bank = bp.details_in_text(text)
    assert emails == ["new-pay@evil.example"]  # the plain contact address is not a payment address
    assert "12-34-56 87654321" in bank and "IBAN GB29NWBK60161331926819" in bank
    assert bp.normalise_bank("12 34 56 87654321") == "12-34-56 87654321"


async def test_changed_paypal_email_flags_and_blocks_autopilot(books: Books, fake: FakeStorageProvider) -> None:
    eid = await _bill(books, 12_000)
    payee = await bp.set_payee(books, CID, EMAIL, None, USER)
    payee.confirmed_at -= timedelta(days=30)
    await books._update_json(bp.PAYEES, {}, lambda raw: {**raw, CID: payee.model_dump(mode="json")})
    await bp.save_autopilot(
        books, True, [bp.SupplierRule(contact_id=CID, max_per_bill_pence=50_000, monthly_cap_pence=100_000)], USER
    )
    _seen, changed = await bp.record_seen(
        books, eid, CID, SUPPLIER, "Pay via PayPal: new-pay@evil.example", "email", payee, f"user:{USER}"
    )
    assert changed and "new-pay@evil.example" in changed[0]
    (b,) = (await bp.bills(books, today=TODAY)).due
    assert b.changed_details and any("differ" in r for r in b.autopilot)
    r = await bp.run(books, today=TODAY)
    assert not r.paid and r.asked and not _payout_posts()
    # The owner must acknowledge it to pay by hand.
    with pytest.raises(bp.BillPayError, match="differ"):
        await bp.pay(books, eid, 12_000, USER, today=TODAY)
    p = await bp.pay(books, eid, 12_000, USER, acknowledge_changed_details=True, today=TODAY)
    assert p.receiver == EMAIL  # paid to the SAVED email, never the one on the bill
    actions = [a["action"] for a in _audit(fake)]
    assert "billpay_details_changed" in actions and "billpay_autopilot_asked" in actions


async def test_bank_details_change_between_bills(books: Books) -> None:
    first = await _bill(books, 1_000, days_ago=70)
    second = await _bill(books, 1_200)
    await bp.record_seen(books, first, CID, SUPPLIER, "Sort code: 11-22-33 Account 12345678", "document", None, "x")
    _s, changed = await bp.record_seen(
        books, second, CID, SUPPLIER, "Sort code: 99-88-77\nAccount no 87654321", "document", None, "x"
    )
    assert changed and "earlier bills" in changed[0]


async def test_bill_document_text_is_read(books: Books, fake: FakeStorageProvider) -> None:
    """The filed bill's own text is read once by code; a PayPal address on it is compared, never saved."""
    from app.bills import make_bill_proposal
    from app.invoicing import LineIn

    p = await make_bill_proposal(
        books,
        pid="ab" * 16,
        evidence="x",
        source="bill.txt",
        note="test",
        supplier_name=SUPPLIER,
        contact_id=None,
        supplier_vat_number=None,
        bill_date=TODAY - timedelta(days=40),
        lines=[LineIn(description="Oak", quantity=Decimal(1), unit="each", unit_price_pence=10_000)],
        account=None,
        model="code",
    )
    p.file_path = "Documents/bill.txt"
    await books.save_proposal(p)
    await fake.write(p.file_path, b"Invoice 77\nPay with PayPal: payments@other.example\n")
    eid = await _bill(books, 12_000)
    ev = next(e for e in await books.list_events() if e.id == eid)
    ev2 = ev.model_copy(update={"id": "cd" * 16, "proposal_id": p.id})
    await books.post_event(ev2)
    await bp.set_payee(books, CID, EMAIL, None, USER)
    ov = await bp.bills(books, today=TODAY)
    flagged = next(b for b in ov.due if b.event_id == ev2.id)
    assert flagged.changed_details and flagged.details_checked == "checked"
    assert (await bp.load_payees(books))[CID].paypal_email == EMAIL


# --------------------------------------------------------------------------- Autopilot


async def _autopilot(books: Books, *, max_bill: int = 50_000, cap: int = 100_000, days: int = 7) -> None:
    payee = await bp.set_payee(books, CID, EMAIL, None, USER)
    payee.confirmed_at = datetime.combine(TODAY - timedelta(days=30), datetime.min.time()).astimezone()
    await books._update_json(bp.PAYEES, {}, lambda raw: {**raw, CID: payee.model_dump(mode="json")})
    rule = bp.SupplierRule(contact_id=CID, max_per_bill_pence=max_bill, monthly_cap_pence=cap, min_days_unchanged=days)
    await bp.save_autopilot(books, True, [rule], USER)


async def test_autopilot_off_by_default(books: Books) -> None:
    await _bill(books, 12_000)
    await bp.set_payee(books, CID, EMAIL, None, USER)
    assert not (await bp.load_settings(books)).autopilot.enabled
    r = await bp.run(books, today=TODAY)
    assert not r.paid and not _payout_posts()


async def test_autopilot_pays_within_limits_and_notifies(books: Books, fake: FakeStorageProvider) -> None:
    eid = await _bill(books, 12_000)
    await _autopilot(books)
    r = await bp.run(books, today=TODAY)
    (p,) = r.paid
    assert p.event_id == eid and p.via == "autopilot"
    await bp.run(books, today=TODAY)  # success posts, and leaves a notice
    ov = await bp.bills(books, today=TODAY)
    assert any(n.kind == "paid" and "Autopilot paid" in n.text for n in ov.notices)
    autopilot_audit = [
        json.loads(x)
        for path, d in fake.files.items()
        if path.startswith(f"{AUDIT}/autopilot/")
        for x in d.decode().splitlines()
    ]
    assert {"billpay_payout_approved", "billpay_payout_posted"} <= {a["action"] for a in autopilot_audit}


async def test_autopilot_limits_fall_back_to_asking(books: Books) -> None:
    await _bill(books, 60_000)  # over the per-bill limit
    await _autopilot(books, max_bill=50_000)
    r = await bp.run(books, today=TODAY)
    assert not r.paid and "over the limit" in r.asked[0]["reasons"][0] + " ".join(r.asked[0]["reasons"])
    assert not _payout_posts()


async def test_autopilot_monthly_cap(books: Books) -> None:
    await _bill(books, 30_000, days_ago=45)
    await _bill(books, 30_000, days_ago=40)
    await _autopilot(books, cap=50_000)
    r = await bp.run(books, today=TODAY)
    assert len(r.paid) == 1 and len(r.asked) == 1
    assert any("monthly cap" in x for x in r.asked[0]["reasons"])


async def test_autopilot_waits_after_email_change(books: Books) -> None:
    await _bill(books, 12_000)
    await _autopilot(books)
    await bp.set_payee(books, CID, "new@timberyard.example", None, USER)  # changed today
    r = await bp.run(books, today=TODAY)
    assert not r.paid and any("waits 7" in x for x in r.asked[0]["reasons"])


async def test_autopilot_only_person_approved(books: Books) -> None:
    await _bill(books, 12_000, approved_by="autopilot")
    await _autopilot(books)
    r = await bp.run(books, today=TODAY)
    assert not r.paid and any("not by a person" in x for x in r.asked[0]["reasons"])


async def test_kill_switches(books: Books, monkeypatch: pytest.MonkeyPatch) -> None:
    await _bill(books, 12_000)
    await _autopilot(books)
    await bp.stop_autopilot(books, USER)
    assert not (await bp.run(books, today=TODAY)).paid
    await bp.save_autopilot(books, True, (await bp.load_settings(books)).autopilot.rules, USER)
    monkeypatch.setenv("BILLPAY_AUTOPILOT_OFF", "1")
    assert not (await bp.run(books, today=TODAY)).paid
    assert not _payout_posts()
    monkeypatch.delenv("BILLPAY_AUTOPILOT_OFF")
    assert (await bp.run(books, today=TODAY)).paid


async def test_not_paypal_plan_is_skipped(books: Books) -> None:
    eid = await _bill(books, 12_000)
    await _autopilot(books)
    await bp.set_plan(books, eid, "not_paypal", USER)
    r = await bp.run(books, today=TODAY)
    assert not r.paid and not _payout_posts()


# --------------------------------------------------------------------------- routes


@pytest.fixture
def client(books: Books):
    from app.main import app
    from app.routes_books import get_books, require_user

    async def over_books() -> Books:
        return books

    async def over_user() -> str:
        return USER

    app.dependency_overrides[get_books] = over_books
    app.dependency_overrides[require_user] = over_user
    yield TestClient(app)
    app.dependency_overrides.clear()


async def test_routes(client: TestClient, books: Books) -> None:
    eid = await _bill(books, 12_000)
    r = client.put(f"/billpay/payees/{CID}", json={"paypal_email": EMAIL, "confirm": False}, headers=H)
    assert r.status_code == 400
    r = client.put(f"/billpay/payees/{CID}", json={"paypal_email": EMAIL, "confirm": True}, headers=H)
    assert r.status_code == 200, r.text
    r = client.get("/billpay", headers=H)
    assert r.status_code == 200 and r.json()["due"][0]["event_id"] == eid
    r = client.post(f"/billpay/bills/{eid}/pay", json={"amount_pence": 12_000, "confirm": False}, headers=H)
    assert r.status_code == 400
    r = client.post(f"/billpay/bills/{eid}/pay", json={"amount_pence": 12_000, "confirm": True}, headers=H)
    assert r.status_code == 200, r.text
    r = client.post(f"/billpay/bills/{eid}/pay", json={"amount_pence": 12_000, "confirm": True}, headers=H)
    assert r.status_code == 409
    r = client.post("/billpay/run", headers=H)
    assert r.status_code == 200 and r.json()["refreshed"][0]["status"] == "paid"
    r = client.put(
        "/billpay/autopilot",
        json={"enabled": True, "rules": [{"contact_id": CID, "max_per_bill_pence": 2, "monthly_cap_pence": 1}]},
        headers=H,
    )
    assert r.status_code == 400  # per bill over the monthly cap
    r = client.post("/billpay/autopilot/stop", headers=H)
    assert r.status_code == 200 and r.json()["enabled"] is False
