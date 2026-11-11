"""Direct mode (`PAYPAL_DIRECT=1`, `STRIPE_DIRECT=1`): payment links on the server's own sandbox/test account, with no
partner onboarding or Connect OAuth. The provider is a small MockTransport that records every request, so these tests
check what is (and is not) sent: no `PayPal-Auth-Assertion`, no partner attribution, no `Stripe-Account`."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, parse_qsl, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeMailSender, FakeStorageProvider
from app import online_payments, payment_providers
from app.books import Books
from app.invoicing import PROFILE, InvoiceProfile
from app.online_payments import DIRECT_PAYPAL_MERCHANT, binding_hash, paypal_config, stripe_config

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
WEB = "http://localhost:3000"
SETTINGS = f"{WEB}/settings"
BINDING = "browser-only-secret-0123456789"
API = "https://api.example"
PROFILE_JSON = {
    "name": "Sam Builds Ltd",
    "address": "1 High Street\nLeeds LS1 1AA",
    "vrn": "GB 123 4567 89",
    "bank": {"account_name": "Sam Builds Ltd", "sort_code": "12 34 56", "account_number": "12345678"},
}
DRAFT = {
    "customer": {"name": "Harbour Cafe Ltd", "email": "accounts@harbourcafe.example"},
    "issue_date": "2026-10-20",
    "lines": [{"description": "October support", "quantity": "1", "unit": "month", "unit_price_pence": 20000}],
}

REQUESTS: list[httpx.Request] = []


def _provider(request: httpx.Request) -> httpx.Response:
    REQUESTS.append(request)
    path = request.url.path
    if path == "/v1/oauth2/token":
        return httpx.Response(200, json={"access_token": "A21-sandbox", "expires_in": 32400})
    if path == "/v2/invoicing/invoices" and request.method == "POST":
        return httpx.Response(201, json={"id": "INV2-DIRECT-0001"})
    if path == "/v2/invoicing/invoices/INV2-DIRECT-0001/send":
        return httpx.Response(200, json={})
    if path == "/v2/invoicing/invoices/INV2-DIRECT-0001":
        body = {
            "id": "INV2-DIRECT-0001",
            "status": "SENT",
            "detail": {
                "metadata": {"recipient_view_url": "https://www.sandbox.paypal.com/invoice/p/#INV2-DIRECT-0001"}
            },
        }
        return httpx.Response(200, json=body)
    if path == "/v1/account":
        return httpx.Response(200, json={"id": "acct_1DirectTest", "charges_enabled": True})
    if path == "/v1/prices":
        return httpx.Response(200, json={"id": "price_direct"})
    if path == "/v1/payment_links":
        return httpx.Response(200, json={"id": "plink_direct", "url": "https://buy.stripe.com/test_direct"})
    return httpx.Response(404, json={"name": "NOT_FOUND", "message": path})


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    for k in (
        "ACCNOMOS_TEST_MODE",
        "PAYMENTS_LIVE",
        "PAYMENTS_STATE_KEY",
        "PAYPAL_BASE",
        "STRIPE_CONNECT_CLIENT_ID",
        "STRIPE_REDIRECT_URI",
        "PAYPAL_PARTNER_MERCHANT_ID",
        "PAYPAL_PARTNER_ATTRIBUTION_ID",
        "PAYPAL_RETURN_URL",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CORS_ORIGINS", WEB)
    monkeypatch.setenv("RUNTIME_PUBLIC_URL", API)
    monkeypatch.setenv("PAYPAL_DIRECT", "1")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "sandbox-client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "sandbox-secret")
    monkeypatch.setenv("STRIPE_DIRECT", "1")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_direct")
    REQUESTS.clear()
    payment_providers._paypal_tokens.clear()
    online_payments._spent.clear()
    payment_providers.TRANSPORT = httpx.MockTransport(_provider)
    yield
    payment_providers.TRANSPORT = None


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
async def books(fake: FakeStorageProvider) -> Books:
    b = Books(fake)
    await b.write_json(PROFILE, InvoiceProfile.model_validate(PROFILE_JSON).model_dump(mode="json"))
    return b


@pytest.fixture
def client(books: Books):
    from app.main import app
    from app.routes_books import get_books
    from app.routes_invoices import get_sender

    sender = FakeMailSender()

    async def over_books() -> Books:
        return books

    async def over_sender() -> FakeMailSender:
        return sender

    app.dependency_overrides[get_books] = over_books
    app.dependency_overrides[get_sender] = over_sender
    yield TestClient(app)
    app.dependency_overrides.clear()


def _ok(r: httpx.Response) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


def _connect(client: TestClient, provider: str) -> dict:
    """Start → our own callback (no provider page in direct mode) → Settings fragment → connect."""
    url = _ok(
        client.post(
            f"/payments/online/{provider}/start",
            json={"redirect_to": SETTINGS, "binding_hash": binding_hash(BINDING)},
            headers=H,
        )
    )["url"]
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}" == API and parts.path == f"/payments/online/{provider}/callback"
    back = client.get(parts.path, params=dict(parse_qsl(parts.query)), follow_redirects=False)
    assert back.status_code == 303
    frag = dict(parse_qsl(urlsplit(back.headers["location"]).fragment))
    body = {"state": frag["state"], "binding": BINDING}
    body |= {"code": frag["code"]} if provider == "stripe" else {"merchant_id": frag["merchant_id"]}
    return _ok(client.post(f"/payments/online/{provider}/connect", json=body, headers=H))


def _sent_invoice(client: TestClient) -> str:
    number = _ok(client.post("/invoices", json=DRAFT, headers=H))["number"]
    _ok(client.post(f"/invoices/{number}/send", json={"confirm": True}, headers=H))
    return number


def test_direct_mode_needs_only_the_app_credentials() -> None:
    cfg, why = paypal_config()
    assert cfg is not None and why is None and cfg.direct and cfg.test_mode
    assert cfg.return_url == f"{API}/payments/online/paypal/callback"
    s, why = stripe_config()
    assert s is not None and why is None and s.direct and s.test_mode


def test_direct_mode_refuses_live_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYPAL_BASE", "https://api-m.paypal.com")
    monkeypatch.setenv("PAYMENTS_LIVE", "1")  # even with live allowed: direct mode pools everyone's payments
    cfg, why = paypal_config()
    assert cfg is None and why and "sandbox" in why
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_x")
    s, why = stripe_config()
    assert s is None and why and "test key" in why


def test_direct_mode_is_off_in_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", "1")
    assert not online_payments.direct_mode("paypal") and not online_payments.direct_mode("stripe")


def test_paypal_direct_connect_and_link_send_no_partner_headers(client: TestClient) -> None:
    _connect(client, "paypal")
    rows = {r["provider"]: r for r in _ok(client.get("/payments/online/providers", headers=H))}
    assert rows["paypal"]["connected"] and rows["paypal"]["account"] == DIRECT_PAYPAL_MERCHANT
    assert not any(r.url.path.startswith("/v2/customer") for r in REQUESTS)  # no partner referral, no status check

    number = _sent_invoice(client)
    out = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "paypal"}, headers=H))
    assert "sandbox.paypal.com/invoice" in json.dumps(out)
    create = next(r for r in REQUESTS if r.url.path == "/v2/invoicing/invoices" and r.method == "POST")
    assert "PayPal-Auth-Assertion" not in create.headers
    assert "PayPal-Partner-Attribution-Id" not in create.headers
    assert create.headers["Authorization"] == "Bearer A21-sandbox"
    sent = json.loads(create.content)
    assert sent["items"][0]["unit_amount"] == {"currency_code": "GBP", "value": "240.00"}  # £200 + 20% VAT


def test_paypal_direct_refuses_another_merchant_id(client: TestClient) -> None:
    url = _ok(
        client.post(
            "/payments/online/paypal/start",
            json={"redirect_to": SETTINGS, "binding_hash": binding_hash(BINDING)},
            headers=H,
        )
    )["url"]
    state = parse_qs(urlsplit(url).query)["state"][0]
    r = client.post(
        "/payments/online/paypal/connect",
        json={"merchant_id": "SOMEONEELSE1", "state": state, "binding": BINDING},
        headers=H,
    )
    assert r.status_code >= 400 and "own PayPal sandbox account" in r.text


def test_stripe_direct_links_the_keys_own_account_without_stripe_account(client: TestClient) -> None:
    _connect(client, "stripe")
    rows = {r["provider"]: r for r in _ok(client.get("/payments/online/providers", headers=H))}
    assert rows["stripe"]["connected"] and rows["stripe"]["account"] == "acct_1DirectTest"
    assert not any(r.url.path == "/oauth/token" for r in REQUESTS)

    number = _sent_invoice(client)
    _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "stripe"}, headers=H))
    stripe_calls = [r for r in REQUESTS if r.url.path.startswith("/v1/")]
    assert stripe_calls and all("Stripe-Account" not in r.headers for r in stripe_calls)


async def test_a_spoken_invoice_gets_the_paypal_link_before_it_is_emailed(client: TestClient, books: Books) -> None:
    """ "Send JM Trading an invoice for £200 for October support": the card says it will carry a PayPal link, and
    once approved the invoice is created, linked and emailed with the link in it."""
    from datetime import date

    from app import actions
    from app.contacts import CONTACTS, Contact

    _connect(client, "paypal")
    await books.write_json(
        CONTACTS,
        [
            Contact(
                id="jmtrading0000000",
                kind="customer",
                name="JM Trading Ltd",
                normalised_key="jm-trading",  # type: ignore[arg-type]
                email="accounts@jmtrading.example",
            ).model_dump(mode="json")
        ],
    )
    intent = actions.CreateInvoiceIntent(
        customer_ref="JM Trading", description="October support", amount_pence=20_000, send=True
    )
    draft = await actions.resolve_invoice(books, intent, date(2026, 11, 11))
    assert isinstance(draft, actions.Draft)
    assert draft.preview["pay_online"] == "paypal" and "Pay online" in draft.summary_md
    action = actions.new_action(draft, "graph-token-1")
    sender = FakeMailSender()
    ctx = actions.Context(books=books, user=USER, graph_token="graph-token-1", mail_sender=lambda: sender)
    done = await actions.approve(action, ctx)
    assert done.result["status"] == "sent", done.result
    assert done.result["payment_link"].startswith("https://www.sandbox.paypal.com/invoice/")
    assert len(sender.sent) == 1 and "sandbox.paypal.com/invoice" in json.dumps(sender.sent[0], default=str)


async def test_no_connected_account_means_no_link_on_the_card(books: Books) -> None:
    from app import actions

    assert await actions._pay_online_provider(books) is None


def test_demo_may_connect_in_direct_mode_only(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Direct mode only points the demo's books at the server's own sandbox account, so the demo may "connect"."""
    demo_h = H | {"X-Demo-Session": "demo-session"}
    body = {"redirect_to": SETTINGS, "binding_hash": binding_hash(BINDING)}
    assert client.post("/payments/online/paypal/start", json=body, headers=demo_h).status_code == 200
    monkeypatch.delenv("PAYPAL_DIRECT")
    monkeypatch.setenv("PAYPAL_PARTNER_MERCHANT_ID", "PARTNER1")
    monkeypatch.setenv("PAYPAL_PARTNER_ATTRIBUTION_ID", "BN")
    monkeypatch.setenv("PAYPAL_RETURN_URL", f"{API}/payments/online/paypal/callback")
    r = client.post("/payments/online/paypal/start", json=body, headers=demo_h)
    assert r.status_code == 403 and "demo" in r.text
