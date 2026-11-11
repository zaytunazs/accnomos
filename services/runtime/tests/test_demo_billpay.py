"""Bill pay in the company demo (app/demo_recent.add_bill_pay): three fictional supplier bills to pay through PayPal,
one due today, one approved in advance, one planned, with the PayPal emails the owner typed (example.com addresses:
reserved, so nobody can claim a sandbox payout to them). Built on the real demo seed for one day; PayPal is the fake
in app/online_fakes.py, so nothing here talks to PayPal."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app import billpay as bp
from app import billpay_schedule as bs
from app import demo, demo_recent, online_fakes, online_payments, payment_providers
from app.books import Books, now
from app.invoicing import InvoiceStateError
from app.online_fakes import FAKES

DAY = date(2026, 11, 11)
SECRET = "s" * 40


@pytest.fixture(autouse=True)
def _no_paypal(monkeypatch: pytest.MonkeyPatch):
    """As the demo server without PayPal credentials; tests that need the fake PayPal set it up themselves."""
    for k in (
        "ACCNOMOS_TEST_MODE",
        "PAYMENTS_LIVE",
        "PAYPAL_BASE",
        "PAYPAL_DIRECT",
        "PAYPAL_CLIENT_ID",
        "PAYPAL_CLIENT_SECRET",
        "PAYPAL_PARTNER_MERCHANT_ID",
        "PAYPAL_PARTNER_ATTRIBUTION_ID",
        "PAYPAL_RETURN_URL",
        "BILLPAY_AUTOPILOT_OFF",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(bp, "london_today", lambda: DAY)
    monkeypatch.setattr(bs, "london_today", lambda: DAY)
    yield
    payment_providers.TRANSPORT = None


def _direct(monkeypatch: pytest.MonkeyPatch) -> None:
    """The public demo server: direct mode, the server's own PayPal sandbox app (here the fake)."""
    monkeypatch.setenv("PAYPAL_DIRECT", "1")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", online_fakes.PAYPAL_CLIENT[0])
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", online_fakes.PAYPAL_CLIENT[1])
    FAKES.reset()
    online_fakes.install("https://fake.example")  # answers for api-m.sandbox.paypal.com; nothing leaves the machine
    payment_providers._paypal_tokens.clear()


def _partner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Partner credentials against the fake (the fake PayPal models a partner's merchant; direct mode differs only in
    the headers, tests/test_online_payments_direct.py)."""
    monkeypatch.setenv("PAYPAL_CLIENT_ID", online_fakes.PAYPAL_CLIENT[0])
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", online_fakes.PAYPAL_CLIENT[1])
    monkeypatch.setenv("PAYPAL_PARTNER_MERCHANT_ID", online_fakes.PAYPAL_PARTNER)
    monkeypatch.setenv("PAYPAL_PARTNER_ATTRIBUTION_ID", "ACCNOMOS_FAKE_BN")
    monkeypatch.setenv("PAYPAL_RETURN_URL", "https://api.example/payments/online/paypal/callback")
    FAKES.reset()
    online_fakes.install("https://fake.example")
    FAKES.merchants[online_fakes.PAYPAL_MERCHANT] = {"merchant_id": online_fakes.PAYPAL_MERCHANT}


async def _connect(books: Books, merchant: str = online_payments.DIRECT_PAYPAL_MERCHANT) -> None:
    """What Settings › Online payments › Connect PayPal saves (the visitor's own tap)."""
    await books.write_json(
        online_payments.PROVIDERS,
        {
            "paypal": {
                "merchant_id": merchant,
                "sandbox": True,
                "connected_at": now().isoformat(),
                "connected_by": demo.USER,
            }
        },
    )


@pytest.fixture(scope="module")
def storage() -> FakeStorageProvider:
    return asyncio.run(demo.build_full(DAY)).storage


@pytest.fixture
def company(storage: FakeStorageProvider) -> Books:
    copy = FakeStorageProvider()
    copy.files = dict(storage.files)
    copy.folders = set(storage.folders)
    return Books(copy)


def _by_supplier(ov: bp.Overview) -> dict[str, bp.Bill]:
    return {b.supplier: b for b in [*ov.due, *ov.upcoming]}


async def test_a_fresh_demo_has_payees_and_three_paypal_bills(company: Books) -> None:
    ov = await bp.bills(company, today=DAY, read_documents=False)
    names = [b.supplier for b in demo_recent.BILLS]
    assert sorted(p.name for p in ov.payees) == sorted(names)
    assert all(p.paypal_email.endswith("@example.com") for p in ov.payees)  # reserved: nobody can own it
    bills = _by_supplier(ov)
    due, approved, planned = (bills[n] for n in names)
    assert [b.supplier for b in ov.due] == [due.supplier]
    assert (due.due_date, due.owed_pence, due.reference) == (DAY, 11_400, "PGS-4471")
    assert (approved.due_date, approved.owed_pence) == (DAY + timedelta(days=5), 15_360)
    assert approved.approval is not None and approved.approval.status == "scheduled"
    assert approved.approval.bill_version == approved.version  # exactly what the owner approved
    assert (planned.due_date, planned.owed_pence, planned.approval) == (DAY + timedelta(days=12), 12_600, None)
    assert {b.plan for b in bills.values() if b.supplier in names} == {"paypal"}
    assert all(b.person_approved for b in bills.values())
    # PayPal is not connected and this server has no PayPal app: the card says why it cannot pay yet.
    assert not ov.connected and not due.can_pay and due.blocks
    assert not ov.autopilot.enabled and ov.autopilot.rules == []
    assert ov.payouts == [] and ov.flags == []
    assert ov.clearing_pence == 330_000  # two recent sales paid through a PayPal link: covers every bill


async def test_upcoming_totals_and_no_shortfall(company: Books) -> None:
    u = await bs.upcoming(company, today=DAY)
    assert [(i.supplier, i.status, i.date) for i in u.items] == [
        ("Pennine Glazing Supplies Ltd", "due_today", DAY),
        ("Calder Valley Fixings Ltd", "scheduled", DAY + timedelta(days=5)),
        ("Nidderdale Saw Sharpening Ltd", "planned", DAY + timedelta(days=12)),
    ]
    assert (u.next_7_pence, u.next_30_pence) == (26_760, 39_360)
    assert (u.shortfall_7_pence, u.shortfall_30_pence, u.warning) == (0, 0, None)


async def test_run_in_a_fresh_demo_pays_nothing_even_with_paypal_connected(
    company: Books, monkeypatch: pytest.MonkeyPatch
) -> None:
    _direct(monkeypatch)
    assert bp._paypal()[0] is not None  # the server can send payouts: only the books' own state holds them back
    for books_connected in (False, True):
        if books_connected:
            await _connect(company)
        for day in (DAY, DAY + timedelta(days=1)):  # a demo session lives 2 hours; even past midnight
            out = await bp.run(company, today=day)
            assert (out.paid, out.scheduled_paid, out.scheduled_held, out.asked, out.problems) == ([], [], [], [], [])
    assert FAKES.payouts == {}
    assert not [r for r in FAKES.requests if "/payouts" in r.url.path]
    ov = await bp.bills(company, today=DAY, read_documents=False)
    assert ov.payouts == [] and _by_supplier(ov)["Calder Valley Fixings Ltd"].approval.status == "scheduled"  # type: ignore[union-attr]


async def test_pay_due_today_needs_paypal_connected_then_sends_one_sandbox_payout(
    company: Books, monkeypatch: pytest.MonkeyPatch
) -> None:
    _partner(monkeypatch)
    due = (await bp.bills(company, today=DAY, read_documents=False)).due[0]
    assert due.blocks == ["Connect PayPal in Settings › Online payments first"]
    with pytest.raises(InvoiceStateError, match="Connect PayPal"):
        await bp.pay(company, due.event_id, due.owed_pence, demo.USER, today=DAY)
    assert FAKES.payouts == {}
    await _connect(company, online_fakes.PAYPAL_MERCHANT)  # the visitor connects PayPal
    p = await bp.pay(company, due.event_id, due.owed_pence, demo.USER, today=DAY)
    assert (p.receiver, p.amount_pence, p.via) == ("accounts.pennine-glazing@example.com", 11_400, "owner")
    assert len(FAKES.payouts) == 1, (p.status, p.detail)
    (sent,) = FAKES.payouts.values()
    assert [i["payout_item"]["receiver"] for i in sent["_items"]] == ["accounts.pennine-glazing@example.com"]
    assert p.status in ("pending", "paid", "unclaimed")


def test_bill_dates_stay_in_the_current_vat_period() -> None:
    start = date(2026, 10, 1)
    for today in (date(2026, 10, 1), date(2026, 10, 4), DAY):
        for b in demo_recent.BILLS:
            day, terms = demo_recent.bill_dates(b, today, start)
            assert start <= day <= today and day + timedelta(days=terms) == today + timedelta(days=b.due_in)


# --------------------------------------------------------------------------- #
# Through the routes, with the demo header (as the web and the phone call them)
# --------------------------------------------------------------------------- #


@pytest.fixture
def demo_client(storage: FakeStorageProvider, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from app.routes_billpay import router as billpay_router

    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_SECRET", SECRET)
    monkeypatch.setattr(demo, "CREATE_LIMITER", None)
    demo.reset_for_tests()

    async def ready(day: date) -> demo.Snapshot:
        return demo.Snapshot(day, storage, "Bramblewood Joinery Ltd", 0.01)

    monkeypatch.setattr(demo, "BUILD", ready)
    monkeypatch.setattr(demo, "current_date", lambda: DAY)
    app = FastAPI()
    app.include_router(demo.router)
    app.include_router(billpay_router)
    yield TestClient(app)
    demo.reset_for_tests()


def _session(c: TestClient) -> dict[str, str]:
    r = c.post("/demo/session")
    assert r.status_code == 200, r.text
    return {demo.HEADER: r.json()["session"], "X-User": demo.USER}


def test_the_demo_routes_show_bill_pay_and_refuse_payouts_without_a_sandbox(demo_client: TestClient) -> None:
    h = _session(demo_client)
    u = demo_client.get("/billpay/upcoming", headers=h)
    assert u.status_code == 200, u.text
    assert (u.json()["next_7_pence"], u.json()["next_30_pence"], len(u.json()["items"])) == (26_760, 39_360, 3)
    o = demo_client.get("/billpay", headers=h).json()
    assert len(o["due"]) == 1 and len(o["payees"]) == 3 and o["due"][0]["blocks"]
    # No direct mode and no fakes: nothing may move from a demo, and it says so.
    r = demo_client.post("/billpay/run", headers=h)
    assert r.status_code == 403 and "demo sandbox" in r.json()["detail"]
    bill = o["due"][0]
    r = demo_client.post(
        f"/billpay/bills/{bill['event_id']}/pay", headers=h, json={"amount_pence": bill["owed_pence"], "confirm": True}
    )
    assert r.status_code == 403 and "switched off in the demo sandbox" in r.json()["detail"]


def test_the_demo_routes_in_direct_mode_run_and_pay_nothing_until_asked(
    demo_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _direct(monkeypatch)
    h = _session(demo_client)
    r = demo_client.post("/billpay/run", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["paid"] == [] and r.json()["scheduled_paid"] == []
    bill = demo_client.get("/billpay", headers=h).json()["due"][0]
    r = demo_client.post(
        f"/billpay/bills/{bill['event_id']}/pay", headers=h, json={"amount_pence": bill["owed_pence"], "confirm": True}
    )
    assert r.status_code == 409 and "Connect PayPal" in r.json()["detail"]  # the visitor has not connected PayPal
    assert FAKES.payouts == {}
