"""Payment links through the user's own Stripe / PayPal account (app/online_payments.py), against the fakes in
app/online_fakes.py, which answer with the request and response shapes the providers document (pages cited in
app/payment_providers.py, read 28 Oct 2026). Nothing here talks to Stripe or PayPal."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, parse_qsl, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeMailSender, FakeStorageProvider
from app import online_fakes, online_payments, payment_providers
from app.books import AUDIT, Books
from app.invoicing import PROFILE, InvoiceProfile
from app.online_fakes import FAKES, paypal_fee, stripe_fee
from app.online_payments import (
    OnlinePaymentError,
    StateError,
    binding_hash,
    check_redirect,
    make_state,
    paypalme_url,
    read_state,
)
from app.payment_providers import auth_assertion, paypal_value, pence_from_paypal, stripe_minor

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
WEB = "http://localhost:3000"
SETTINGS = f"{WEB}/settings"
BINDING = "browser-only-secret-0123456789"
PROFILE_JSON = {
    "name": "Sam Builds Ltd",
    "address": "1 High Street\nLeeds LS1 1AA",
    "vrn": "GB 123 4567 89",
    "bank": {"account_name": "Sam Builds Ltd", "sort_code": "12 34 56", "account_number": "12345678"},
}
# 6 h × £45 + 4 × £10, 20% VAT: £310.00 net, £62.00 VAT, £372.00
DRAFT = {
    "customer": {"name": "Harbour Cafe Ltd", "email": "accounts@harbourcafe.example"},
    "issue_date": "2026-10-20",
    "lines": [
        {"description": "Kitchen first fix", "quantity": "6", "unit": "hours", "unit_price_pence": 4500},
        {"description": "Fixings", "quantity": "4", "unit": "boxes", "unit_price_pence": 1000},
    ],
}
TOTAL = 37200


def _server_env(monkeypatch: pytest.MonkeyPatch, *, stripe: bool = True, paypal: bool = True) -> None:
    for k in (
        "ACCNOMOS_TEST_MODE",
        "PAYMENTS_LIVE",
        "PAYMENTS_STATE_KEY",
        "PAYPAL_BASE",
        "STRIPE_SECRET_KEY",
        "STRIPE_CONNECT_CLIENT_ID",
        "STRIPE_REDIRECT_URI",
        "PAYPAL_CLIENT_ID",
        "PAYPAL_CLIENT_SECRET",
        "PAYPAL_PARTNER_MERCHANT_ID",
        "PAYPAL_PARTNER_ATTRIBUTION_ID",
        "PAYPAL_RETURN_URL",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CORS_ORIGINS", WEB)
    if stripe:
        monkeypatch.setenv("STRIPE_SECRET_KEY", online_fakes.STRIPE_KEY)
        monkeypatch.setenv("STRIPE_CONNECT_CLIENT_ID", "ca_accnomos_fake")
        monkeypatch.setenv("STRIPE_REDIRECT_URI", "https://api.example/payments/online/stripe/callback")
    if paypal:
        monkeypatch.setenv("PAYPAL_CLIENT_ID", online_fakes.PAYPAL_CLIENT[0])
        monkeypatch.setenv("PAYPAL_CLIENT_SECRET", online_fakes.PAYPAL_CLIENT[1])
        monkeypatch.setenv("PAYPAL_PARTNER_MERCHANT_ID", online_fakes.PAYPAL_PARTNER)
        monkeypatch.setenv("PAYPAL_PARTNER_ATTRIBUTION_ID", "ACCNOMOS_FAKE_BN")
        monkeypatch.setenv("PAYPAL_RETURN_URL", "https://api.example/payments/online/paypal/callback")


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch):
    _server_env(monkeypatch)
    FAKES.reset()
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
    c = TestClient(app)
    c.sender = sender  # type: ignore[attr-defined]
    yield c
    app.dependency_overrides.clear()


def _ok(r: httpx.Response) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


def _sent_invoice(client: TestClient) -> str:
    number = _ok(client.post("/invoices", json=DRAFT, headers=H))["number"]
    _ok(client.post(f"/invoices/{number}/send", json={"confirm": True}, headers=H))
    return number


def _fragment(location: str) -> dict[str, str]:
    return dict(parse_qsl(urlsplit(location).fragment))


def _connect_stripe(client: TestClient, account: str = "acct_test1sam") -> None:
    url = _ok(
        client.post(
            "/payments/online/stripe/start",
            json={"redirect_to": SETTINGS, "binding_hash": binding_hash(BINDING)},
            headers=H,
        )
    )["url"]
    state = parse_qs(urlsplit(url).query)["state"][0]
    back = client.get(
        "/payments/online/stripe/callback",
        params={"code": FAKES.stripe_code(account), "scope": "read_write", "state": state},
        follow_redirects=False,
    )
    assert back.status_code == 303
    frag = _fragment(back.headers["location"])
    _ok(
        client.post(
            "/payments/online/stripe/connect",
            json={"code": frag["code"], "state": frag["state"], "binding": BINDING},
            headers=H,
        )
    )


def _connect_paypal(client: TestClient) -> None:
    url = _ok(
        client.post(
            "/payments/online/paypal/start",
            json={"redirect_to": SETTINGS, "binding_hash": binding_hash(BINDING)},
            headers=H,
        )
    )["url"]
    rid = url.rsplit("/", 1)[1]
    ref = FAKES.referrals[rid]
    # PayPal sends the seller back to our return URL with its own parameters added (the fake page does the same).
    FAKES.merchants[online_fakes.PAYPAL_MERCHANT] = {
        "merchant_id": online_fakes.PAYPAL_MERCHANT,
        "tracking_id": ref["tracking_id"],
        "payments_receivable": True,
        "primary_email_confirmed": True,
        "oauth_integrations": [{"integration_type": "OAUTH_THIRD_PARTY"}],
    }
    ret = urlsplit(ref["return_url"])
    params = dict(parse_qsl(ret.query)) | {
        "merchantIdInPayPal": online_fakes.PAYPAL_MERCHANT,
        "permissionsGranted": "true",
        "consentStatus": "true",
        "isEmailConfirmed": "true",
    }
    back = client.get("/payments/online/paypal/callback", params=params, follow_redirects=False)
    assert back.status_code == 303
    frag = _fragment(back.headers["location"])
    assert frag["merchant_id"] == online_fakes.PAYPAL_MERCHANT
    _ok(
        client.post(
            "/payments/online/paypal/connect",
            json={"merchant_id": frag["merchant_id"], "state": frag["state"], "binding": BINDING},
            headers=H,
        )
    )


def _form(req: httpx.Request) -> dict[str, str]:
    return dict(parse_qsl(req.content.decode()))


def _calls(path: str) -> list[httpx.Request]:
    return [r for r in FAKES.requests if r.url.path == path]


def _audit(fake: FakeStorageProvider) -> list[dict]:
    return [
        json.loads(x)
        for p, d in sorted(fake.files.items())
        if p.startswith(f"{AUDIT}/") and p.endswith(".jsonl")
        for x in d.decode().splitlines()
    ]


async def _events(books: Books) -> list:
    return await books.list_events()


# --------------------------------------------------------------------------- #
# Money: pence to each provider's units and back
# --------------------------------------------------------------------------- #


def test_amounts_cross_in_pence() -> None:
    assert stripe_minor(37200) == 37200  # Stripe GBP: smallest unit
    assert [paypal_value(p) for p in (1, 99, 100, 37200, 123456)] == ["0.01", "0.99", "1.00", "372.00", "1234.56"]
    assert pence_from_paypal({"currency_code": "GBP", "value": "372.00"}) == 37200
    assert pence_from_paypal({"currency_code": "GBP", "value": "11.09"}) == 1109
    assert pence_from_paypal({"currency_code": "USD", "value": "1.00"}) is None
    assert pence_from_paypal({"currency_code": "GBP", "value": "1.005"}) is None
    assert pence_from_paypal({"currency_code": "GBP", "value": "x"}) is None
    with pytest.raises(ValueError):
        stripe_minor(0)
    with pytest.raises(ValueError):
        paypal_value(-1)
    assert paypalme_url("SamBuilds", 27205) == "https://paypal.me/SamBuilds/272.05GBP"


def test_fake_fees_are_the_published_uk_card_price() -> None:
    assert stripe_fee(37200) == 578  # 1.5% of £372 = £5.58, + 20p
    assert paypal_fee(37200) == 1109  # 2.9% = £10.788 -> £10.79, + 30p


def test_auth_assertion_is_an_unsigned_jwt_naming_the_merchant() -> None:
    head, payload, sig = auth_assertion("client-1", "MERCHANT9").split(".")
    assert json.loads(base64.b64decode(head)) == {"alg": "none"}
    assert json.loads(base64.b64decode(payload)) == {"iss": "client-1", "payer_id": "MERCHANT9"}
    assert sig == ""


# --------------------------------------------------------------------------- #
# Server configuration: off by default, test mode only
# --------------------------------------------------------------------------- #


def test_nothing_set_means_off_with_a_sentence(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    _server_env(monkeypatch, stripe=False, paypal=False)
    rows = {p["provider"]: p for p in _ok(client.get("/payments/online/providers", headers=H))}
    assert rows["stripe"]["available"] is False
    assert rows["stripe"]["reason"] == "Stripe payment links are not set up on this server yet."
    assert rows["paypal"]["reason"] == "PayPal payment links are not set up on this server yet."
    assert rows["paypalme"]["available"] is True and rows["paypalme"]["can_match"] is False
    r = client.post(
        "/payments/online/stripe/start",
        json={"redirect_to": SETTINGS, "binding_hash": binding_hash(BINDING)},
        headers=H,
    )
    assert r.status_code == 503


def test_live_credentials_are_refused_unless_the_owner_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_" + "x" * 20)
    monkeypatch.setenv("PAYPAL_BASE", "https://api-m.paypal.com")
    cfg, why = online_payments.stripe_config()
    assert cfg is None and why and "test mode" in why
    pcfg, pwhy = online_payments.paypal_config()
    assert pcfg is None and pwhy and "sandbox" in pwhy
    monkeypatch.setenv("PAYMENTS_LIVE", "1")
    assert online_payments.stripe_config()[0] is not None
    assert online_payments.paypal_config()[0] is not None


def test_test_mode_uses_the_fakes_and_local_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", "1")
    monkeypatch.setenv("PORT", "8781")
    cfg, _ = online_payments.stripe_config()
    assert cfg is not None and cfg.test_mode
    assert cfg.authorize_url == "http://127.0.0.1:8781/__test/stripe/oauth/authorize"
    pcfg, _ = online_payments.paypal_config()
    assert pcfg is not None and pcfg.test_mode


# --------------------------------------------------------------------------- #
# Signed state
# --------------------------------------------------------------------------- #


def test_state_is_signed_bound_and_spent_once() -> None:
    state = make_state("stripe", SETTINGS, binding_hash(BINDING), USER)
    st = read_state(state, "stripe")
    assert st.redirect_to == SETTINGS and st.binding_hash == binding_hash(BINDING)
    payload, sig = state.split(".")
    with pytest.raises(StateError, match="signature"):
        read_state(f"{payload}.{sig[:-2]}AA", "stripe")
    with pytest.raises(StateError):
        read_state(state, "paypal")  # another provider's key and name
    read_state(state, "stripe", use="callback")
    with pytest.raises(StateError, match="already used"):
        read_state(state, "stripe", use="callback")
    read_state(state, "stripe", use="connect")  # each step once


def test_state_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    state = make_state("stripe", SETTINGS, binding_hash(BINDING), USER)
    real = time.time
    monkeypatch.setattr(online_payments.time, "time", lambda: real() + online_payments.STATE_TTL_S + 1)
    with pytest.raises(StateError, match="expired"):
        read_state(state, "stripe")


def test_only_back_to_settings_on_our_origin() -> None:
    assert check_redirect(f"{SETTINGS}#old") == SETTINGS
    for bad in ("https://evil.example/settings", f"{WEB}/invoices", "javascript:alert(1)"):
        with pytest.raises(OnlinePaymentError):
            check_redirect(bad)


# --------------------------------------------------------------------------- #
# Stripe: connect, link, find, approve
# --------------------------------------------------------------------------- #


def test_stripe_connect_keeps_only_the_account_id(client: TestClient, fake: FakeStorageProvider) -> None:
    url = _ok(
        client.post(
            "/payments/online/stripe/start",
            json={"redirect_to": f"{SETTINGS}?x=1", "binding_hash": binding_hash(BINDING)},
            headers=H,
        )
    )["url"]
    q = parse_qs(urlsplit(url).query)
    assert url.startswith("https://connect.stripe.com/oauth/authorize?")
    assert q["response_type"] == ["code"] and q["scope"] == ["read_write"] and q["client_id"] == ["ca_accnomos_fake"]
    assert q["redirect_uri"] == ["https://api.example/payments/online/stripe/callback"]
    back = client.get(
        "/payments/online/stripe/callback",
        params={"code": FAKES.stripe_code("acct_test1sam"), "state": q["state"][0]},
        follow_redirects=False,
    )
    assert back.headers["location"].startswith(f"{SETTINGS}?x=1#")
    frag = _fragment(back.headers["location"])
    assert frag["pay"] == "stripe"
    # a second visit to the callback (reload) is refused
    again = client.get("/payments/online/stripe/callback", params={"code": "x", "state": q["state"][0]})
    assert again.status_code == 400 and "expired" in again.text
    # another browser (no binding secret) cannot finish it
    r = client.post(
        "/payments/online/stripe/connect",
        json={"code": frag["code"], "state": frag["state"], "binding": "someone-elses-secret-000"},
        headers=H,
    )
    assert r.status_code == 400 and "another browser" in r.json()["detail"]
    online_payments._spent.pop(("connect", read_state(frag["state"], "stripe").nonce))
    # nor someone else signed in
    r = client.post(
        "/payments/online/stripe/connect",
        json={"code": frag["code"], "state": frag["state"], "binding": BINDING},
        headers={**H, "X-User": "mallory@example.com"},
    )
    assert r.status_code == 400 and "someone else" in r.json()["detail"]
    online_payments._spent.pop(("connect", read_state(frag["state"], "stripe").nonce))
    rows = _ok(
        client.post(
            "/payments/online/stripe/connect",
            json={"code": frag["code"], "state": frag["state"], "binding": BINDING},
            headers=H,
        )
    )
    stripe = next(p for p in rows if p["provider"] == "stripe")
    assert stripe["connected"] and stripe["account"] == "acct_test1sam" and stripe["test_mode"]
    token_call = _calls("/oauth/token")[0]
    assert _form(token_call) == {"grant_type": "authorization_code", "code": frag["code"]}
    stored = fake.files["_System/Payments/providers.json"].decode()
    assert json.loads(stored)["stripe"]["account_id"] == "acct_test1sam"
    for secret in ("sk_", "rt_", "access_token", "refresh_token", "pk_test"):
        assert secret not in stored  # the deprecated tokens Stripe still returns are dropped
    assert any(a["action"] == "payment_provider_connected" for a in _audit(fake))


def test_stripe_error_on_the_consent_screen_comes_back_as_a_fragment(client: TestClient) -> None:
    state = make_state("stripe", SETTINGS, binding_hash(BINDING), USER)
    back = client.get(
        "/payments/online/stripe/callback",
        params={"error": "access_denied", "error_description": "The user denied your request", "state": state},
        follow_redirects=False,
    )
    frag = _fragment(back.headers["location"])
    assert frag["error"] == "access_denied" and "code" not in frag


def test_a_live_stripe_account_is_refused_and_unlinked(client: TestClient) -> None:
    state = make_state("stripe", SETTINGS, binding_hash(BINDING), USER)
    code = FAKES.stripe_code("acct_live1", live=True)
    r = client.post(
        "/payments/online/stripe/connect", json={"code": code, "state": state, "binding": BINDING}, headers=H
    )
    assert r.status_code == 400 and "live mode" in r.json()["detail"]
    assert "acct_live1" not in FAKES.accounts  # deauthorised again


async def test_stripe_link_pay_find_approve(client: TestClient, books: Books, fake: FakeStorageProvider) -> None:
    _connect_stripe(client)
    number = _sent_invoice(client)
    out = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "stripe"}, headers=H))
    link = out["invoice"]["payment_link"]
    assert link["provider"] == "stripe" and link["amount_pence"] == TOTAL and link["test_mode"] is True
    assert link["url"].startswith("https://fake.example/__test/stripe/pay/plink_")
    price_req, link_req = _calls("/v1/prices")[0], _calls("/v1/payment_links")[0]
    assert price_req.headers["Stripe-Account"] == link_req.headers["Stripe-Account"] == "acct_test1sam"
    assert price_req.headers["Idempotency-Key"].endswith("-price")
    price = _form(price_req)
    assert price["currency"] == "gbp" and price["unit_amount"] == str(TOTAL)
    assert price["product_data[name]"] == f"Invoice {number}"
    form = _form(link_req)
    assert form["restrictions[completed_sessions][limit]"] == "1"
    assert form["metadata[accnomos_ref]"] == link["ref"] == form["payment_intent_data[metadata][accnomos_ref]"]
    assert "Harbour" not in link_req.content.decode()  # nothing about the customer goes to Stripe
    # the poll on open: nothing paid yet
    assert _ok(client.get("/payments/online/check", headers=H)) == {"checked": 1, "found": [], "problems": []}
    FAKES.pay_stripe(link["provider_ref"])
    found = _ok(client.get("/payments/online/check", headers=H))["found"]
    assert len(found) == 1
    f = found[0]
    assert (f["invoice"], f["gross_pence"], f["fee_pence"], f["net_pence"]) == (number, TOTAL, 578, TOTAL - 578)
    assert f["journal"] == [
        {"account": "1230 Stripe clearing", "debit_pence": TOTAL, "credit_pence": 0, "vat_code": None},
        {"account": "1100 Debtors", "debit_pence": 0, "credit_pence": TOTAL, "vat_code": None},
        {"account": "7900 Bank charges", "debit_pence": 578, "credit_pence": 0, "vat_code": "E"},
        {"account": "1230 Stripe clearing", "debit_pence": 0, "credit_pence": 578, "vat_code": None},
    ]
    lists = _calls("/v1/checkout/sessions")
    assert lists[-1].url.params["payment_link"] == link["provider_ref"]
    assert lists[-1].url.params.get_list("expand[]") == ["data.payment_intent.latest_charge.balance_transaction"]
    before = len(await _events(books))
    # checking posts nothing; approving needs the user's yes
    r = client.post(f"/invoices/{number}/payment-link/approve", json={"payment_id": f["payment_id"]}, headers=H)
    assert r.status_code == 400 and len(await _events(books)) == before
    # a fee from the app is not taken over the provider's
    r = client.post(
        f"/invoices/{number}/payment-link/approve",
        json={"payment_id": f["payment_id"], "confirm": True, "fee_pence": 1},
        headers=H,
    )
    assert r.status_code == 400 and "£5.78" in r.json()["detail"]
    done = _ok(
        client.post(
            f"/invoices/{number}/payment-link/approve", json={"payment_id": f["payment_id"], "confirm": True}, headers=H
        )
    )
    assert done["invoice"]["status"] == "paid" and done["invoice"]["money"]["balance_pence"] == 0
    events = await _events(books)
    assert len(events) == before + 2
    fee_ev = next(e for e in events if e.counterparty == "Stripe")
    assert fee_ev.kind == "purchase" and fee_ev.net == 578 and fee_ev.vat == 0
    assert [(ln.account, ln.debit, ln.credit, ln.vat_code) for ln in fee_ev.lines] == [
        ("7900 Bank charges", 578, 0, "E"),
        ("1230 Stripe clearing", 0, 578, None),
    ]
    payments = _ok(client.get("/payments", headers=H))
    assert [p["amount_pence"] for p in payments] == [TOTAL]
    assert payments[0]["reference"] == f"Stripe {f['payment_id']}"
    # proposed once: the next check finds nothing, and a second approve is refused
    assert _ok(client.get("/payments/online/check", headers=H))["found"] == []
    r = client.post(
        f"/invoices/{number}/payment-link/approve", json={"payment_id": f["payment_id"], "confirm": True}, headers=H
    )
    assert r.status_code == 409
    assert "online_payment_approved" in [a["action"] for a in _audit(fake)]


async def test_part_paid_invoice_links_for_the_balance_and_replaces_the_old_link(client: TestClient) -> None:
    _connect_stripe(client)
    number = _sent_invoice(client)
    first = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "stripe"}, headers=H))["invoice"]
    _ok(client.post(f"/invoices/{number}/payments", json={"amount_pence": 10000}, headers=H))
    out = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "stripe"}, headers=H))
    assert out["warning"] is None
    link = out["invoice"]["payment_link"]
    assert link["amount_pence"] == TOTAL - 10000
    assert _form(_calls("/v1/prices")[-1])["unit_amount"] == str(TOTAL - 10000)
    old = FAKES.links[first["payment_link"]["provider_ref"]]
    assert old["active"] is False  # switched off before the new one is kept
    deactivate = _calls(f"/v1/payment_links/{old['id']}")[0]
    assert _form(deactivate) == {"active": "false"}
    FAKES.pay_stripe(link["provider_ref"])
    f = _ok(client.get("/payments/online/check", headers=H))["found"][0]
    assert f["gross_pence"] == TOTAL - 10000 and f["balance_pence"] == TOTAL - 10000
    done = _ok(
        client.post(
            f"/invoices/{number}/payment-link/approve", json={"payment_id": f["payment_id"], "confirm": True}, headers=H
        )
    )
    assert done["invoice"]["status"] == "paid"


async def test_fee_not_known_yet_is_typed_in(client: TestClient, books: Books) -> None:
    _connect_stripe(client)
    number = _sent_invoice(client)
    link = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "stripe"}, headers=H))["invoice"][
        "payment_link"
    ]
    FAKES.fee_pending = True
    FAKES.pay_stripe(link["provider_ref"])
    f = _ok(client.get("/payments/online/check", headers=H))["found"][0]
    assert f["fee_pence"] is None and f["net_pence"] is None and len(f["journal"]) == 2
    r = client.post(
        f"/invoices/{number}/payment-link/approve", json={"payment_id": f["payment_id"], "confirm": True}, headers=H
    )
    assert r.status_code == 400 and "not said its fee" in r.json()["detail"]
    r = client.post(
        f"/invoices/{number}/payment-link/approve",
        json={"payment_id": f["payment_id"], "confirm": True, "fee_pence": TOTAL},
        headers=H,
    )
    assert r.status_code == 400
    _ok(
        client.post(
            f"/invoices/{number}/payment-link/approve",
            json={"payment_id": f["payment_id"], "confirm": True, "fee_pence": 600},
            headers=H,
        )
    )
    fee = next(e for e in await _events(books) if e.counterparty == "Stripe")
    assert fee.lines[0].debit == 600


async def test_a_payment_after_the_invoice_was_paid_otherwise_is_not_posted(client: TestClient) -> None:
    _connect_stripe(client)
    number = _sent_invoice(client)
    link = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "stripe"}, headers=H))["invoice"][
        "payment_link"
    ]
    FAKES.pay_stripe(link["provider_ref"])
    _ok(client.post(f"/invoices/{number}/mark-paid", json={}, headers=H))  # paid by bank transfer meanwhile
    # a paid invoice is no longer checked; the money stays in Stripe for the user to refund or record by hand
    assert _ok(client.get("/payments/online/check", headers=H))["checked"] == 0


def test_a_retry_after_a_failure_part_way_does_not_record_twice(client: TestClient, monkeypatch) -> None:
    _connect_stripe(client)
    number = _sent_invoice(client)
    link = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "stripe"}, headers=H))["invoice"][
        "payment_link"
    ]
    FAKES.pay_stripe(link["provider_ref"])
    pid = _ok(client.get("/payments/online/check", headers=H))["found"][0]["payment_id"]
    real = online_payments.save_invoice
    calls = {"n": 0}

    async def flaky(books, inv):
        calls["n"] += 1
        if inv.online_payments and calls.get("failed") is None:  # the save that remembers the id fails once
            calls["failed"] = 1
            raise RuntimeError("OneDrive hiccup")
        return await real(books, inv)

    monkeypatch.setattr(online_payments, "save_invoice", flaky)
    r = client.post(f"/invoices/{number}/payment-link/approve", json={"payment_id": pid, "confirm": True}, headers=H)
    assert r.status_code == 500  # the money was posted; remembering the id failed
    _ok(client.post(f"/invoices/{number}/payment-link/approve", json={"payment_id": pid, "confirm": True}, headers=H))
    assert [p["amount_pence"] for p in _ok(client.get("/payments", headers=H))] == [TOTAL]


def test_disconnect_needs_a_yes_and_tells_stripe(client: TestClient, fake: FakeStorageProvider) -> None:
    _connect_stripe(client)
    r = client.post("/payments/online/stripe/disconnect", json={}, headers=H)
    assert r.status_code == 400
    out = _ok(client.post("/payments/online/stripe/disconnect", json={"confirm": True}, headers=H))
    assert not next(p for p in out["providers"] if p["provider"] == "stripe")["connected"]
    deauth = _form(_calls("/oauth/deauthorize")[0])
    assert deauth == {"client_id": "ca_accnomos_fake", "stripe_user_id": "acct_test1sam"}
    assert "stripe" not in json.loads(fake.files["_System/Payments/providers.json"])
    number = _sent_invoice(client)
    r = client.post(f"/invoices/{number}/payment-link", json={"provider": "stripe"}, headers=H)
    assert r.status_code == 400 and "Connect Stripe" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# The link on the invoice: email, reminder, PDF; a draft edited afterwards
# --------------------------------------------------------------------------- #


def test_link_on_a_draft_goes_in_the_email_and_pdf(client: TestClient) -> None:
    _connect_stripe(client)
    number = _ok(client.post("/invoices", json=DRAFT, headers=H))["number"]
    link = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "stripe"}, headers=H))["invoice"][
        "payment_link"
    ]
    pdf = _ok(client.post(f"/invoices/{number}/pdf", headers=H))
    assert f"Pay £372.00 online (TEST MODE: no real money is taken): {link['url']}" in pdf["email"]["body"]
    data = base64.b64decode(pdf["data_url"].split(",", 1)[1])
    assert link["url"].encode() in data  # the clickable link annotation (/URI)
    _ok(client.post(f"/invoices/{number}/send", json={"confirm": True}, headers=H))
    sent = client.sender.sent[-1]  # type: ignore[attr-defined]
    assert link["url"] in sent.body_text


def test_a_draft_edited_after_its_link_is_not_sent_with_the_wrong_amount(client: TestClient) -> None:
    _connect_stripe(client)
    number = _ok(client.post("/invoices", json=DRAFT, headers=H))["number"]
    _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "stripe"}, headers=H))
    edited = {**DRAFT, "lines": DRAFT["lines"][:1]}
    row = _ok(client.put(f"/invoices/{number}", json=edited, headers=H))
    assert row["payment_link"]["amount_pence"] == TOTAL  # kept, and now stale
    problems = _ok(client.post(f"/invoices/{number}/pdf", headers=H))["problems"]
    assert any("payment link is for £372.00" in p for p in problems)
    r = client.post(f"/invoices/{number}/send", json={"confirm": True}, headers=H)
    assert r.status_code == 400 and "payment link" in r.json()["detail"]
    out = _ok(client.delete(f"/invoices/{number}/payment-link", headers=H))
    assert out["invoice"]["payment_link"] is None
    assert FAKES.links[row["payment_link"]["provider_ref"]]["active"] is False


async def test_reminder_draft_gets_the_link_from_code(client: TestClient, books: Books) -> None:
    from datetime import date

    from app.ai import remind
    from app.ai.config import AiConfig
    from app.invoicing import get_invoice

    _connect_stripe(client)
    number = _sent_invoice(client)
    link = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "stripe"}, headers=H))["invoice"][
        "payment_link"
    ]
    inv = await get_invoice(books, number)
    cfg = AiConfig(mode="local", base_url="http://127.0.0.1:9/none", model="x")  # unreachable: the code draft
    draft = await remind.draft_reminder(inv, InvoiceProfile.model_validate(PROFILE_JSON), cfg, date(2026, 12, 1))
    assert draft.body.endswith(f"Pay £372.00 online (TEST MODE: no real money is taken): {link['url']}")


# --------------------------------------------------------------------------- #
# PayPal: partner sign-up, invoice link, find, approve; PayPal.me
# --------------------------------------------------------------------------- #


def test_paypal_signup_asks_for_invoicing_and_checks_the_merchant(
    client: TestClient, fake: FakeStorageProvider
) -> None:
    _connect_paypal(client)
    referral = json.loads(_calls("/v2/customer/partner-referrals")[0].content)
    rest = referral["operations"][0]["api_integration_preference"]["rest_api_integration"]
    assert rest["integration_type"] == "THIRD_PARTY"
    assert rest["third_party_details"]["features"] == ["PAYMENT", "REFUND", "INVOICE_READ_WRITE"]
    assert referral["legal_consents"] == [{"type": "SHARE_DATA_CONSENT", "granted": True}]
    token = _calls("/v1/oauth2/token")[0]
    assert _form(token) == {"grant_type": "client_credentials"}
    status_call = _calls(f"/v1/customer/partners/FAKEPARTNER1/merchant-integrations/{online_fakes.PAYPAL_MERCHANT}")
    assert status_call and status_call[0].headers["PayPal-Partner-Attribution-Id"] == "ACCNOMOS_FAKE_BN"
    stored = json.loads(fake.files["_System/Payments/providers.json"])
    assert stored["paypal"]["merchant_id"] == online_fakes.PAYPAL_MERCHANT and stored["paypal"]["sandbox"] is True
    assert set(stored["paypal"]) == {"merchant_id", "sandbox", "connected_at", "connected_by"}


def test_paypal_merchant_from_another_signup_is_refused(client: TestClient) -> None:
    state = make_state("paypal", SETTINGS, binding_hash(BINDING), USER)
    FAKES.merchants["OTHERMERCHANT"] = {
        "merchant_id": "OTHERMERCHANT",
        "tracking_id": "someone-elses-signup",
        "payments_receivable": True,
        "primary_email_confirmed": True,
        "oauth_integrations": [{}],
    }
    r = client.post(
        "/payments/online/paypal/connect",
        json={"merchant_id": "OTHERMERCHANT", "state": state, "binding": BINDING},
        headers=H,
    )
    assert r.status_code == 400 and "not linked through this sign-up" in r.json()["detail"]


def test_paypal_signup_not_finished_comes_back_as_an_error(client: TestClient) -> None:
    state = make_state("paypal", SETTINGS, binding_hash(BINDING), USER)
    back = client.get(
        "/payments/online/paypal/callback",
        params={"state": state, "merchantIdInPayPal": "X1", "permissionsGranted": "false", "consentStatus": "true"},
        follow_redirects=False,
    )
    frag = _fragment(back.headers["location"])
    assert frag["error"] == "access_denied" and "merchant_id" not in frag


async def test_paypal_invoice_link_pay_find_approve(client: TestClient, books: Books) -> None:
    _connect_paypal(client)
    number = _sent_invoice(client)
    link = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "paypal"}, headers=H))["invoice"][
        "payment_link"
    ]
    assert link["provider"] == "paypal" and link["url"].startswith("https://fake.example/__test/paypal/pay/INV2-")
    create = _calls("/v2/invoicing/invoices")[0]
    body = json.loads(create.content)
    assert body["items"][0]["unit_amount"] == {"currency_code": "GBP", "value": "372.00"}
    assert body["detail"]["currency_code"] == "GBP" and body["detail"]["reference"] == link["ref"]
    assert body["configuration"]["partial_payment"]["allow_partial_payment"] is False
    claims = json.loads(base64.b64decode(create.headers["PayPal-Auth-Assertion"].split(".")[1]))
    assert claims == {"iss": online_fakes.PAYPAL_CLIENT[0], "payer_id": online_fakes.PAYPAL_MERCHANT}
    assert create.headers["PayPal-Request-Id"] == f"accnomos-{link['ref']}"
    send = _calls(f"/v2/invoicing/invoices/{link['provider_ref']}/send")[0]
    assert json.loads(send.content) == {"send_to_recipient": False, "send_to_invoicer": False}  # we give the link
    assert _ok(client.get("/payments/online/check", headers=H))["found"] == []
    tid = FAKES.pay_paypal(link["provider_ref"])
    f = _ok(client.get("/payments/online/check", headers=H))["found"][0]
    assert (f["payment_id"], f["gross_pence"], f["fee_pence"]) == (tid, TOTAL, 1109)
    done = _ok(
        client.post(f"/invoices/{number}/payment-link/approve", json={"payment_id": tid, "confirm": True}, headers=H)
    )
    assert done["invoice"]["status"] == "paid"
    fee = next(e for e in await _events(books) if e.counterparty == "PayPal")
    assert fee.lines[0].account == "7900 Bank charges" and fee.lines[0].debit == 1109
    # replacing the link cancels the old PayPal invoice (here it is paid: the invoice takes no new link)
    r = client.post(f"/invoices/{number}/payment-link", json={"provider": "paypal"}, headers=H)
    assert r.status_code == 409


def test_paypal_fee_unknown_when_the_capture_cannot_be_read(client: TestClient) -> None:
    _connect_paypal(client)
    number = _sent_invoice(client)
    link = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "paypal"}, headers=H))["invoice"][
        "payment_link"
    ]
    FAKES.paypal_fee_known = False
    FAKES.pay_paypal(link["provider_ref"])
    f = _ok(client.get("/payments/online/check", headers=H))["found"][0]
    assert f["fee_pence"] is None


def test_paypal_replacing_a_link_cancels_the_old_invoice(client: TestClient) -> None:
    _connect_paypal(client)
    number = _sent_invoice(client)
    first = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "paypal"}, headers=H))["invoice"]
    _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "paypal"}, headers=H))
    old = first["payment_link"]["provider_ref"]
    assert FAKES.invoices[old]["status"] == "CANCELLED"
    assert json.loads(_calls(f"/v2/invoicing/invoices/{old}/cancel")[0].content) == {
        "send_to_recipient": False,
        "send_to_invoicer": False,
    }


def test_paypalme_needs_no_api_and_is_never_matched(client: TestClient) -> None:
    rows = _ok(client.put("/payments/online/paypalme", json={"username": "paypal.me/SamBuilds"}, headers=H))
    assert next(p for p in rows if p["provider"] == "paypalme")["account"] == "SamBuilds"
    r = client.put("/payments/online/paypalme", json={"username": "sam builds!"}, headers=H)
    assert r.status_code == 400
    number = _sent_invoice(client)
    _ok(client.post(f"/invoices/{number}/payments", json={"amount_pence": 99}, headers=H))
    before = len(FAKES.requests)
    link = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "paypalme"}, headers=H))["invoice"][
        "payment_link"
    ]
    assert link["url"] == "https://paypal.me/SamBuilds/371.01GBP" and link["test_mode"] is False
    assert len(FAKES.requests) == before  # no provider call
    assert _ok(client.get("/payments/online/check", headers=H))["checked"] == 0


def test_no_link_for_a_void_or_paid_invoice(client: TestClient) -> None:
    _ok(client.put("/payments/online/paypalme", json={"username": "SamBuilds"}, headers=H))
    number = _sent_invoice(client)
    _ok(client.post(f"/invoices/{number}/mark-paid", json={}, headers=H))
    assert client.post(f"/invoices/{number}/payment-link", json={"provider": "paypalme"}, headers=H).status_code == 409
    assert client.post("/invoices/INV-9999/payment-link", json={"provider": "paypalme"}, headers=H).status_code == 404


def test_a_provider_that_cannot_be_reached_is_a_problem_not_a_failure(client: TestClient) -> None:
    _connect_stripe(client)
    number = _sent_invoice(client)
    _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "stripe"}, headers=H))

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    payment_providers.TRANSPORT = httpx.MockTransport(down)
    out = _ok(client.get("/payments/online/check", headers=H))
    assert out["found"] == [] and out["problems"][0]["invoice"] == number
    assert "could not be reached" in out["problems"][0]["message"]


def test_binding_hash_is_sha256() -> None:
    assert binding_hash("abc") == hashlib.sha256(b"abc").hexdigest()


# --------------------------------------------------------------------------- #
# Clearing accounts and payouts: a receipt is counted once, the bank only when the payout lands
# --------------------------------------------------------------------------- #


def _balance(events: list, account: str) -> int:
    return sum(ln.debit - ln.credit for e in events for ln in e.lines if ln.account == account)


def _statement(*rows: tuple[str, str, str]) -> bytes:
    return ("Date,Description,Amount\n" + "".join(f"{d},{w},{a}\n" for d, w, a in rows)).encode()


async def _paid_by_link(client: TestClient, provider: str) -> tuple[str, str, int]:
    """A sent invoice paid through a `provider` link and approved: (number, payment id, fee)."""
    (_connect_stripe if provider == "stripe" else _connect_paypal)(client)
    number = _sent_invoice(client)
    link = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": provider}, headers=H))["invoice"][
        "payment_link"
    ]
    pid = FAKES.pay_stripe(link["provider_ref"]) if provider == "stripe" else FAKES.pay_paypal(link["provider_ref"])
    f = _ok(client.get("/payments/online/check", headers=H))["found"][0]
    _ok(
        client.post(
            f"/invoices/{number}/payment-link/approve",
            json={"payment_id": f["payment_id"], "confirm": True},
            headers=H,
        )
    )
    return number, pid or f["payment_id"], f["fee_pence"]


@pytest.mark.parametrize(
    ("provider", "clearing", "words"),
    [("stripe", "1230 Stripe clearing", "STRIPE PAYMENTS UK LTD"), ("paypal", "1240 PayPal clearing", "PAYPAL")],
)
async def test_a_payout_moves_the_money_from_clearing_to_the_bank_once(
    client: TestClient, books: Books, provider: str, clearing: str, words: str
) -> None:
    _number, _pid, fee = await _paid_by_link(client, provider)
    events = await _events(books)
    net = TOTAL - fee
    # Approved: the provider holds the money, the bank has nothing yet, the invoice is paid.
    assert (_balance(events, clearing), _balance(events, "1200 Bank")) == (net, 0)
    assert _balance(events, "1100 Debtors") == 0

    pounds = f"{net / 100:.2f}"
    r = client.post(
        "/books/bank/import",
        headers=H,
        files={"file": ("payout.csv", _statement(("30/10/2026", f"{words} PAYOUT", pounds)), "text/csv")},
    )
    assert r.status_code == 200, r.text
    lines = _ok(client.get("/books/bank/unmatched", headers=H))
    line = next(u for u in lines if u["line"]["amount_pence"] == net)
    assert line["payout"] == provider  # the hint the Bank page shows
    # The payout is not offered as the invoice's payment: that money is already in the books.
    r = client.post(f"/books/bank/lines/{line['line']['id']}/payout", json={"provider": provider}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "matched"
    events = await _events(books)
    assert (_balance(events, clearing), _balance(events, "1200 Bank")) == (0, net)  # equal to the statement
    sales = sum(-ln.credit + ln.debit for e in events for ln in e.lines if ln.account == "4000 Sales")
    assert sales == -31_000  # the invoice's net, once: the payout added no income

    # Unmatching puts the money back in clearing; matching again moves it once more.
    _ok(client.post(f"/books/bank/lines/{line['line']['id']}/unmatch", headers=H))
    events = await _events(books)
    assert (_balance(events, clearing), _balance(events, "1200 Bank")) == (net, 0)
    _ok(client.post(f"/books/bank/lines/{line['line']['id']}/payout", json={"provider": provider}, headers=H))
    assert _balance(await _events(books), "1200 Bank") == net


async def test_a_payout_bigger_than_what_the_provider_holds_is_refused(client: TestClient, books: Books) -> None:
    client.post(
        "/books/bank/import",
        headers=H,
        files={"file": ("p.csv", _statement(("30/10/2026", "STRIPE PAYOUT", "50.00")), "text/csv")},
    )
    line = _ok(client.get("/books/bank/unmatched", headers=H))[0]
    r = client.post(f"/books/bank/lines/{line['line']['id']}/payout", json={"provider": "stripe"}, headers=H)
    assert r.status_code == 409
    assert "1230 Stripe clearing holds £0.00" in r.json()["detail"]
    assert await _events(books) == []
