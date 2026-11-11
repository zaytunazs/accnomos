"""Sync PayPal (app/paypal_sync.py) against the Transaction Search fake in app/online_fakes.py: 31-day windows and
pages, the fee kept apart from the gross, invoice matching (through the payment link and by number), idempotency by
PayPal transaction id, and nothing posted until the user approves. Nothing here talks to PayPal."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeMailSender, FakeStorageProvider
from app import online_fakes, online_payments, payment_providers
from app import paypal_sync as ps
from app.books import Books, now
from app.invoicing import PROFILE, InvoiceProfile
from app.online_fakes import FAKES, paypal_fee, reporting_row
from app.online_payments import PayPalConnection

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
PROFILE_JSON = {
    "name": "Sam Builds Ltd",
    "address": "1 High Street\nLeeds LS1 1AA",
    "vrn": "GB 123 4567 89",
    "bank": {"account_name": "Sam Builds Ltd", "sort_code": "12 34 56", "account_number": "12345678"},
}
DRAFT = {
    "customer": {"name": "Harbour Cafe Ltd", "email": "accounts@harbourcafe.example"},
    "issue_date": "2026-10-20",
    "lines": [{"description": "Kitchen first fix", "quantity": "6", "unit": "hours", "unit_price_pence": 4500}],
}
TOTAL = 32400  # 6 × £45 + 20% VAT
NOW = datetime.now(UTC)


def _at(days_ago: float) -> datetime:
    return NOW - timedelta(days=days_ago)


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch):
    for k in ("ACCNOMOS_TEST_MODE", "PAYMENTS_LIVE", "PAYPAL_BASE", "PAYPAL_DIRECT", "DEMO_MODE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", online_fakes.PAYPAL_CLIENT[0])
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", online_fakes.PAYPAL_CLIENT[1])
    monkeypatch.setenv("PAYPAL_PARTNER_MERCHANT_ID", online_fakes.PAYPAL_PARTNER)
    monkeypatch.setenv("PAYPAL_PARTNER_ATTRIBUTION_ID", "ACCNOMOS_FAKE_BN")
    monkeypatch.setenv("PAYPAL_RETURN_URL", "https://api.example/payments/online/paypal/callback")
    FAKES.reset()
    FAKES.reporting = []
    FAKES.merchants[online_fakes.PAYPAL_MERCHANT] = {"merchant_id": online_fakes.PAYPAL_MERCHANT}
    online_fakes.install("https://fake.example")
    online_payments._spent.clear()
    yield
    payment_providers.TRANSPORT = None


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
async def books(fake: FakeStorageProvider) -> Books:
    b = Books(fake)
    await b.write_json(PROFILE, InvoiceProfile.model_validate(PROFILE_JSON).model_dump(mode="json"))
    conn = PayPalConnection(merchant_id=online_fakes.PAYPAL_MERCHANT, connected_at=now(), connected_by=USER)
    await online_payments._save_connection(b, "paypal", conn)
    return b


@pytest.fixture
def client(books: Books):
    from app.main import app
    from app.routes_books import get_books
    from app.routes_invoices import get_sender

    async def over_books() -> Books:
        return books

    async def over_sender() -> FakeMailSender:
        return FakeMailSender()

    app.dependency_overrides[get_books] = over_books
    app.dependency_overrides[get_sender] = over_sender
    yield TestClient(app)
    app.dependency_overrides.clear()


def _ok(r: httpx.Response) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


def _sync(client: TestClient, **body) -> dict:
    return _ok(client.post("/payments/paypal/sync", json={"ai": False, **body}, headers=H))


def _item(result: dict, tid: str) -> dict:
    return next(i for i in result["items"] if i["transaction_id"] == tid)


def _reporting_calls() -> list[httpx.Request]:
    return [r for r in FAKES.requests if r.url.path == "/v1/reporting/transactions"]


def _balance(events: list, account: str) -> int:
    return sum(ln.debit - ln.credit for e in events for ln in e.lines if ln.account == account)


def _sent_invoice(client: TestClient) -> str:
    number = _ok(client.post("/invoices", json=DRAFT, headers=H))["number"]
    _ok(client.post(f"/invoices/{number}/send", json={"confirm": True}, headers=H))
    return number


SALE = reporting_row(
    "SALE0000000000001",
    _at(5),
    code="T0006",
    gross=4800,
    fee=paypal_fee(4800),
    name="Amelia Clarke",
    items=[("Oak chopping board", 4800)],
)
SCREWFIX = reporting_row(
    "SCRW0000000000001",
    _at(4),
    code="T0006",
    gross=-3699,
    name="Screwfix Direct Ltd",
    items=[("Wood screws 4.0 x 40mm (200)", 1299), ("Wood glue 1L", 2400)],
)


# --------------------------------------------------------------------------- #
# Reading PayPal: 31-day windows, pages, the request
# --------------------------------------------------------------------------- #


def test_windows_are_at_most_31_days_and_join_up() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=95, hours=5)
    w = ps.windows(start, end)
    assert len(w) == 4 and w[0][0] == start and w[-1][1] == end
    assert all(b - a <= timedelta(days=31) for a, b in w)
    assert all(w[n][1] == w[n + 1][0] for n in range(len(w) - 1))


def test_parse_time_reads_paypal_dates() -> None:
    got = payment_providers.paypal_parse_time("2014-07-11T04:03:52+0000")
    assert got == datetime(2014, 7, 11, 4, 3, 52, tzinfo=UTC)
    assert payment_providers.paypal_time(got) == "2014-07-11T04:03:52+0000"
    assert payment_providers.paypal_parse_time("nonsense") is None


def test_first_sync_reads_90_days_in_windows_and_pages(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ps, "PAGE_SIZE", 2)
    FAKES.reporting = [
        reporting_row(f"PAGE{n:013d}", _at(1 + n / 10), code="T0006", gross=1000 + n, name=f"Buyer {n}")
        for n in range(5)
    ]
    out = _sync(client)
    calls = _reporting_calls()
    spans = []
    for req in calls:
        q = parse_qs(urlsplit(str(req.url)).query)
        start = payment_providers.paypal_parse_time(q["start_date"][0])
        end = payment_providers.paypal_parse_time(q["end_date"][0])
        assert start and end and end - start <= timedelta(days=31)
        assert q["fields"] == ["all"] and q["page_size"] == ["2"]
        assert req.headers["PayPal-Auth-Assertion"]  # partner mode names the merchant
        spans.append((start, end, q["page"][0]))
    assert len({(a, b) for a, b, _ in spans}) == 3  # 90 days: three windows
    last = spans[-1][1]
    assert [page for _a, b, page in spans if b == last] == ["1", "2", "3"]  # 5 rows, 2 a page, in the last window
    assert out["read"] == 5 and out["new"] == 5 and len(out["items"]) == 5
    assert out["end"] and datetime.fromisoformat(out["end"]) - datetime.fromisoformat(out["start"]) == timedelta(
        days=90
    )


def test_three_years_at_most(client: TestClient) -> None:
    r = client.post("/payments/paypal/sync", json={"days": 2000, "ai": False}, headers=H)
    assert r.status_code == 422
    out = _sync(client, days=ps.MAX_DAYS)
    assert len(_reporting_calls()) == len(
        ps.windows(datetime.fromisoformat(out["start"]), datetime.fromisoformat(out["end"]))
    )


def test_next_sync_starts_three_hours_before_the_last_one_ended(client: TestClient, books: Books) -> None:
    first = _sync(client)
    FAKES.requests.clear()
    second = _sync(client)
    assert datetime.fromisoformat(second["start"]) == datetime.fromisoformat(first["end"]) - ps.LATE
    assert len(_reporting_calls()) == 1


def test_not_connected_says_so(client: TestClient, fake: FakeStorageProvider) -> None:
    fake.files.pop(online_payments.PROVIDERS)
    r = client.post("/payments/paypal/sync", json={"ai": False}, headers=H)
    assert r.status_code == 503 and "Connect PayPal" in r.json()["detail"]
    assert _ok(client.get("/payments/paypal/sync", headers=H))["available"] is False


def test_paypal_refusing_saves_nothing(client: TestClient, fake: FakeStorageProvider) -> None:
    FAKES.merchants.clear()  # PayPal answers 403
    r = client.post("/payments/paypal/sync", json={"ai": False}, headers=H)
    assert r.status_code == 400 and "PayPal did not answer" in r.json()["detail"]
    assert ps.SYNC not in fake.files


# --------------------------------------------------------------------------- #
# Proposals: fee split, no posting, idempotency
# --------------------------------------------------------------------------- #


async def test_a_sale_keeps_gross_fee_and_net_apart_and_posts_only_on_approve(client: TestClient, books: Books) -> None:
    FAKES.reporting = [SALE]
    out = _sync(client)
    it = _item(out, "SALE0000000000001")
    fee = paypal_fee(4800)  # 169
    assert (it["kind"], it["status"]) == ("sale", "proposed")
    assert (it["gross_pence"], it["fee_pence"], it["net_pence"]) == (4800, fee, 4800 - fee)
    assert it["vat_code"] == "S"  # the books are VAT registered: 20% included
    assert [(j["account"], j["debit_pence"], j["credit_pence"], j["vat_code"]) for j in it["journal"]] == [
        ("1240 PayPal clearing", 4800, 0, None),
        ("4000 Sales", 0, 4000, "S"),
        ("2200 VAT control", 0, 800, "S"),
        ("7900 Bank charges", fee, 0, "E"),
        ("1240 PayPal clearing", 0, fee, None),
    ]
    assert await books.list_events() == []  # syncing posts nothing
    done = _ok(client.post("/payments/paypal/sync/SALE0000000000001/approve", json={"confirm": True}, headers=H))
    assert done["status"] == "approved" and len(done["event_ids"]) == 2
    events = await books.list_events()
    sale = next(e for e in events if e.kind == "sale")
    assert (sale.net, sale.vat, sale.id) == (4000, 800, ps.sync_event_id("SALE0000000000001"))
    assert _balance(events, "1240 PayPal clearing") == 4800 - fee
    assert _balance(events, "7900 Bank charges") == fee
    assert sum(ln.debit for e in events for ln in e.lines) == sum(ln.credit for e in events for ln in e.lines)


def test_approve_needs_a_yes(client: TestClient) -> None:
    FAKES.reporting = [SALE]
    _sync(client)
    r = client.post("/payments/paypal/sync/SALE0000000000001/approve", json={}, headers=H)
    assert r.status_code == 400 and "Nothing was posted" in r.json()["detail"]


async def test_syncing_again_never_proposes_twice_and_approving_twice_is_refused(
    client: TestClient, books: Books
) -> None:
    FAKES.reporting = [SALE, SCREWFIX]
    first = _sync(client)
    assert first["new"] == 2
    again = _sync(client, days=30)  # the same window again
    assert again["new"] == 0 and len(again["items"]) == 2
    _ok(client.post("/payments/paypal/sync/SALE0000000000001/approve", json={"confirm": True}, headers=H))
    r = client.post("/payments/paypal/sync/SALE0000000000001/approve", json={"confirm": True}, headers=H)
    assert r.status_code == 409
    third = _sync(client, days=30)
    assert _item(third, "SALE0000000000001")["status"] == "approved"
    assert len([e for e in await books.list_events() if e.kind == "sale"]) == 1


def test_pending_is_not_kept_until_paypal_completes_it(client: TestClient) -> None:
    pending = reporting_row("PEND0000000000001", _at(1), code="T0006", gross=2500, fee=103, status="P")
    FAKES.reporting = [pending]
    out = _sync(client)
    assert out["pending"] == 1 and out["items"] == []
    pending["transaction_info"]["transaction_status"] = "S"
    out = _sync(client, days=5)
    assert _item(out, "PEND0000000000001")["status"] == "proposed"


async def test_withdrawals_refunds_and_foreign_currency_are_shown_not_posted(client: TestClient, books: Books) -> None:
    FAKES.reporting = [
        reporting_row("WDRL0000000000001", _at(2), code="T0400", gross=-15000, subject="Withdrawal to bank"),
        reporting_row("RFND0000000000001", _at(2), code="T1107", gross=-1000, name="Amelia Clarke"),
        reporting_row("USD00000000000001", _at(2), code="T0006", gross=2000, currency="USD", name="Kim"),
    ]
    out = _sync(client)
    assert {i["transaction_id"]: (i["kind"], i["status"]) for i in out["items"]} == {
        "WDRL0000000000001": ("withdrawal", "info"),
        "RFND0000000000001": ("refund", "info"),
        "USD00000000000001": ("other", "info"),
    }
    assert "payout" in _item(out, "WDRL0000000000001")["notes"][0]
    r = client.post("/payments/paypal/sync/WDRL0000000000001/approve", json={"confirm": True}, headers=H)
    assert r.status_code == 409
    assert await books.list_events() == []


# --------------------------------------------------------------------------- #
# Invoices: through the link (the existing online payment) and by number
# --------------------------------------------------------------------------- #


async def test_a_payment_through_the_invoice_link_posts_like_online_payments_and_only_once(
    client: TestClient, books: Books
) -> None:
    number = _sent_invoice(client)
    link = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "paypal"}, headers=H))["invoice"][
        "payment_link"
    ]
    tid = FAKES.pay_paypal(link["provider_ref"])
    out = _sync(client)
    it = _item(out, tid)
    fee = paypal_fee(TOTAL)
    assert (it["kind"], it["invoice"], it["via_link"]) == ("invoice", number, True)
    expected = [j.model_dump() for j in online_payments.journal_for("paypal", TOTAL, fee)]
    assert it["journal"] == expected
    done = _ok(client.post(f"/payments/paypal/sync/{tid}/approve", json={"confirm": True}, headers=H))
    assert done["event_ids"] == [online_payments.fee_event_id("paypal", tid)]
    inv = _ok(client.get(f"/invoices/{number}", headers=H))
    assert inv["status"] == "paid" and tid in inv["online_payments"]
    assert _ok(client.get("/payments/online/check", headers=H))["found"] == []  # the Invoices page has nothing more
    events = await books.list_events()
    assert _balance(events, "1240 PayPal clearing") == TOTAL - fee
    assert _balance(events, "1100 Debtors") == 0


async def test_a_payment_already_approved_on_invoices_is_shown_as_already_there(
    client: TestClient, books: Books
) -> None:
    number = _sent_invoice(client)
    link = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "paypal"}, headers=H))["invoice"][
        "payment_link"
    ]
    tid = FAKES.pay_paypal(link["provider_ref"])
    _ok(client.post(f"/invoices/{number}/payment-link/approve", json={"payment_id": tid, "confirm": True}, headers=H))
    before = len(await books.list_events())
    it = _item(_sync(client), tid)
    assert it["status"] == "already"
    r = client.post(f"/payments/paypal/sync/{tid}/approve", json={"confirm": True}, headers=H)
    assert r.status_code == 409 and len(await books.list_events()) == before


async def test_approved_on_invoices_after_the_sync_is_never_posted_again(client: TestClient, books: Books) -> None:
    number = _sent_invoice(client)
    link = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "paypal"}, headers=H))["invoice"][
        "payment_link"
    ]
    tid = FAKES.pay_paypal(link["provider_ref"])
    assert _item(_sync(client), tid)["status"] == "proposed"
    _ok(client.post(f"/invoices/{number}/payment-link/approve", json={"payment_id": tid, "confirm": True}, headers=H))
    assert _item(_ok(client.get("/payments/paypal/sync", headers=H)), tid)["status"] == "already"
    before = len(await books.list_events())
    r = client.post(f"/payments/paypal/sync/{tid}/approve", json={"confirm": True}, headers=H)
    assert r.status_code == 409 and len(await books.list_events()) == before


async def test_an_invoice_number_in_paypal_matches_without_a_link(client: TestClient, books: Books) -> None:
    number = _sent_invoice(client)
    FAKES.reporting = [
        reporting_row(
            "INVN0000000000001",
            _at(1),
            code="T0007",
            gross=TOTAL,
            fee=paypal_fee(TOTAL),
            name="Harbour Cafe Ltd",
            invoice_id=number,
        )
    ]
    it = _item(_sync(client), "INVN0000000000001")
    assert (it["kind"], it["invoice"], it["via_link"]) == ("invoice", number, False)
    _ok(client.post("/payments/paypal/sync/INVN0000000000001/approve", json={"confirm": True}, headers=H))
    inv = _ok(client.get(f"/invoices/{number}", headers=H))
    assert inv["status"] == "paid" and "INVN0000000000001" in inv["online_payments"]
    events = await books.list_events()
    assert _balance(events, "1240 PayPal clearing") == TOTAL - paypal_fee(TOTAL)
    assert not [e for e in events if e.kind == "sale" and e.id == ps.sync_event_id("INVN0000000000001")]


# --------------------------------------------------------------------------- #
# Purchases: coding, VAT, receipts
# --------------------------------------------------------------------------- #


async def test_a_purchase_is_coded_flagged_for_its_receipt_and_posted_from_clearing(
    client: TestClient, books: Books
) -> None:
    FAKES.reporting = [SCREWFIX]
    it = _item(_sync(client), "SCRW0000000000001")
    assert (it["kind"], it["account"], it["vat_code"]) == ("expense", "5000 Materials", "N")
    assert it["coded_by"].startswith("code:")
    assert it["items"] == ["Wood screws 4.0 x 40mm (200)", "Wood glue 1L"]
    assert any(ps.NO_RECEIPT in n for n in it["notes"])
    r = client.post(
        "/payments/paypal/sync/SCRW0000000000001/approve",
        json={"confirm": True, "account": "Not an account"},
        headers=H,
    )
    assert r.status_code == 400
    done = _ok(
        client.post(
            "/payments/paypal/sync/SCRW0000000000001/approve", json={"confirm": True, "vat_code": "S"}, headers=H
        )
    )
    assert done["vat_code"] == "S"
    (ev,) = await books.list_events()
    assert ev.kind == "purchase" and (ev.net, ev.vat) == (3082, 617)
    assert [(ln.account, ln.debit, ln.credit) for ln in ev.lines] == [
        ("5000 Materials", 3082, 0),
        ("2200 VAT control", 617, 0),
        ("1240 PayPal clearing", 0, 3699),
    ]


async def test_the_users_bank_rule_codes_a_purchase(client: TestClient, books: Books) -> None:
    from app.bank_rules import BankRule, BankRuleAction, BankRuleMatch, save_bank_rules

    await save_bank_rules(
        books,
        [
            BankRule(
                name="Adobe",
                match=BankRuleMatch(op="contains", value="adobe"),
                direction="out",
                action=BankRuleAction(account="7510 Software & subscriptions", vat_code="S"),
            )
        ],
    )
    FAKES.reporting = [
        reporting_row("ADBE0000000000001", _at(3), code="T0002", gross=-1997, name="Adobe Systems Software Ireland")
    ]
    it = _item(_sync(client), "ADBE0000000000001")
    assert (it["account"], it["vat_code"], it["coded_by"]) == ("7510 Software & subscriptions", "S", "Adobe")
    assert "VAT can only be reclaimed with a VAT receipt." in it["notes"]


async def test_a_receipt_already_posted_is_named(client: TestClient, books: Books) -> None:
    from app.schemas import ExtractedDoc, Proposal

    doc = ExtractedDoc(
        doc_type="receipt",
        supplier_name="Screwfix",
        supplier_vat_number="GB 232 4277 87",
        customer_name=None,
        invoice_number=None,
        date=_at(4).date().isoformat(),
        currency="GBP",
        lines=[],
        net_total=30.82,
        vat_total=6.17,
        gross_total=36.99,
        payment_method="card",
        card_last4=None,
        category_guess="Materials",
        confidence=0.9,
    )
    await books.save_proposal(
        Proposal(
            id="a" * 32,
            doc_sha256="b" * 64,
            extracted=doc,
            checks=[],
            status="posted",
            reasons=[],
            suggested_filename="x",
            journal_draft=[],
            model="muse-glimmer:30b",
            elapsed_s=1.0,
        )
    )
    FAKES.reporting = [SCREWFIX]
    it = _item(_sync(client), "SCRW0000000000001")
    assert it["receipt"]["proposal_id"] == "a" * 32 and it["receipt"]["status"] == "posted"
    assert any("counted twice" in n for n in it["notes"]) and not any(ps.NO_RECEIPT in n for n in it["notes"])


def test_reject_keeps_it_out_of_the_books(client: TestClient) -> None:
    FAKES.reporting = [SCREWFIX]
    _sync(client)
    out = _ok(client.post("/payments/paypal/sync/SCRW0000000000001/reject", json={"reason": "personal"}, headers=H))
    assert (out["status"], out["reject_reason"]) == ("rejected", "personal")
    assert (
        client.post("/payments/paypal/sync/SCRW0000000000001/approve", json={"confirm": True}, headers=H).status_code
        == 409
    )


# --------------------------------------------------------------------------- #
# Fees, sample history, audit
# --------------------------------------------------------------------------- #


def test_fee_summary_adds_up_what_paypal_charged_and_what_is_in_the_books(client: TestClient) -> None:
    other = reporting_row("SALE0000000000002", _at(2), code="T0006", gross=12000, fee=paypal_fee(12000), name="Ben")
    FAKES.reporting = [SALE, other, SCREWFIX]
    _sync(client)
    _ok(client.post("/payments/paypal/sync/SALE0000000000001/approve", json={"confirm": True}, headers=H))
    start, end = (_at(30).date().isoformat(), date.today().isoformat())
    out = _ok(client.get("/payments/paypal/fees", params={"start": start, "end": end}, headers=H))
    assert out["fees_pence"] == paypal_fee(4800) + paypal_fee(12000)
    assert out["transactions"] == 2 and out["received_pence"] == 16800
    assert out["fees_in_books_pence"] == paypal_fee(4800)
    assert sum(out["by_month"].values()) == out["fees_pence"]
    bad = client.get("/payments/paypal/fees", params={"start": end, "end": start}, headers=H)
    assert bad.status_code == 400


def test_sample_history_in_a_demo_session_without_paypal(client: TestClient, fake: FakeStorageProvider) -> None:
    fake.files.pop(online_payments.PROVIDERS)
    number = _sent_invoice(client)
    demo = {**H, "X-Demo-Session": "x"}
    assert _ok(client.get("/payments/paypal/sync", headers=demo))["sample"] is True
    out = _ok(client.post("/payments/paypal/sync", json={"ai": False}, headers=demo))
    assert out["sample"] is True and out["pending"] == 1
    kinds = {i["name"]: i["kind"] for i in out["items"]}
    assert kinds["Screwfix Direct Ltd"] == "expense" and kinds["Harbour Cafe Ltd"] == "invoice"
    assert kinds["Adobe Systems Software Ireland Ltd"] == "expense" and "withdrawal" in kinds.values()
    adobe = next(i for i in out["items"] if i["name"].startswith("Adobe"))
    assert adobe["account"] == "7510 Software & subscriptions"
    assert next(i for i in out["items"] if i["kind"] == "invoice")["invoice"] == number
    assert _reporting_calls() == []  # nothing asked of PayPal


def test_audit_lines_read_as_sentences(client: TestClient, fake: FakeStorageProvider) -> None:
    import json

    from app.audit_view import SUMMARIES
    from app.books import AUDIT

    FAKES.reporting = [SALE]
    _sync(client)
    _ok(client.post("/payments/paypal/sync/SALE0000000000001/approve", json={"confirm": True}, headers=H))
    lines = [
        json.loads(x)
        for p, d in fake.files.items()
        if p.startswith(f"{AUDIT}/") and p.endswith(".jsonl")
        for x in d.decode().splitlines()
    ]
    kinds = {ln["action"] for ln in lines}
    assert {"paypal_synced", "paypal_transaction_approved"} <= kinds
    for ln in lines:
        assert ln["action"] in SUMMARIES
