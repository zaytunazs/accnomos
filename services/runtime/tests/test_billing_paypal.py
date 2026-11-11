"""PayPal Subscriptions for Accnomos's own plans (PAYMENTS_PROVIDER=paypal, app/billing/paypal_api.py): subscribe
-> approve link, the webhook (verified with PayPal; a bad signature is refused; idempotent), cancel, plan change and
the top-up, against the PayPal fake in app/billing/fakes.py. Nothing here reaches PayPal."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.billing import fakes, paypal_api
from app.billing import plans as P
from app.billing import registry as R
from app.billing import routes as billing_routes
from app.billing import service as S

USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
WEBHOOK = "/billing/paypal/webhook"
SIGNED = {
    "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-fake",
    "PAYPAL-TRANSMISSION-ID": "69cd13f0-d67a-11e5-baa3-778b53f4ae55",
    "PAYPAL-TRANSMISSION-SIG": "fake-signature-lmI95Jx3Y9nhR5SJWlHVIWpg4AgFk7n9bCHSRx",
    "PAYPAL-TRANSMISSION-TIME": "2026-11-11T16:00:00Z",
}
PLANS = {
    "STARTER_MONTH": "P-STARTER-M",
    "STARTER_YEAR": "P-STARTER-Y",
    "COMPREHENSIVE_MONTH": "P-COMP-M",
    "COMPREHENSIVE_YEAR": "P-COMP-Y",
    "ULTIMATE_MONTH": "P-ULT-M",
    "ULTIMATE_YEAR": "P-ULT-Y",
}


@pytest.fixture
def reg(monkeypatch: pytest.MonkeyPatch):
    r = R.MemoryRegistry(storage=True)
    R.install(r)
    S.forget()
    fakes.paypal_reset()
    fakes.paypal_install()
    monkeypatch.setenv("PAYMENTS_PROVIDER", "paypal")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "sandbox-client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "sandbox-secret")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-OURS-123")
    monkeypatch.setenv("ACCNOMOS_WEB_URL", "https://app.accnomos.example")
    for k in ("BILLING_RETURN_URL", "PAYPAL_BASE", "PAYMENTS_LIVE", "PAYPAL_VAT_PERCENT", "STRIPE_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in PLANS.items():
        monkeypatch.setenv(f"PAYPAL_PLAN_{k}", v)

    async def no_books(_request) -> dict:
        return {"bank_feeds": 0, "marketplaces": 0, "autopilot_rules": 0, "users": 1}

    monkeypatch.setattr(billing_routes, "read_gauges", no_books)
    yield r
    R.install(None)
    S.forget()
    paypal_api.TRANSPORT = None


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def _acc(reg: R.MemoryRegistry) -> dict:
    return next(iter(reg.accounts.values()))


def _calls(path: str, method: str = "POST") -> list:
    return [body for m, p, body in fakes.PAYPAL_CALLS if p == path and m == method]


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event(event_id: str, event_type: str, resource: dict) -> dict:
    return {
        "id": event_id,
        "event_version": "1.0",
        "create_time": "2026-11-11T16:00:00Z",
        "resource_type": "subscription",
        "event_type": event_type,
        "summary": "fake",
        "resource": resource,
    }


def _sub(acc: dict, sub_id: str = "I-SUB1", status: str = "ACTIVE", plan: str = "P-STARTER-Y", **kw) -> dict:
    return {
        "id": sub_id,
        "status": status,
        "plan_id": plan,
        "custom_id": acc["id"],
        "start_time": kw.pop("start_time", "2026-11-01T00:00:00Z"),
        "billing_info": {"next_billing_time": kw.pop("next", "2027-11-11T10:00:00Z")},
        **kw,
    }


def _post(client: TestClient, event: dict, headers: dict | None = None):
    return client.post(WEBHOOK, content=json.dumps(event).encode(), headers=SIGNED if headers is None else headers)


def _subscribed(reg: R.MemoryRegistry, client: TestClient, sub_id: str = "I-SUB1") -> dict:
    """An account with an active yearly Starter subscription, its period ending in a year."""
    client.get("/account", headers=H)
    acc = _acc(reg)
    fakes.PAYPAL_STATE["subscriptions"][sub_id] = _sub(acc, sub_id)
    assert (
        _post(client, _event(f"WH-act-{sub_id}", "BILLING.SUBSCRIPTION.ACTIVATED", _sub(acc, sub_id))).status_code
        == 200
    )
    return _acc(reg)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_payments_provider_paypal_is_reported_and_its_client_used(reg: R.MemoryRegistry, client: TestClient):
    acc = client.get("/account", headers=H).json()
    assert acc["payments_provider"] == "paypal"
    assert acc["has_payment_account"] is False
    assert isinstance(billing_routes.provider_or_503(), paypal_api.PayPalBilling)


def test_paypal_live_api_is_refused_unless_payments_live(reg: R.MemoryRegistry, client: TestClient, monkeypatch):
    monkeypatch.setenv("PAYPAL_BASE", paypal_api.LIVE)
    assert paypal_api.client() is None
    r = client.post("/billing/checkout", json={"plan_code": "starter", "interval": "month"}, headers=H)
    assert r.status_code == 503
    monkeypatch.setenv("PAYMENTS_LIVE", "1")
    assert paypal_api.client() is not None
    assert paypal_api.settings().autopay_url == "https://www.paypal.com/myaccount/autopay/"


def test_without_credentials_or_plan_ids_checkout_is_503(reg: R.MemoryRegistry, client: TestClient, monkeypatch):
    monkeypatch.delenv("PAYPAL_PLAN_STARTER_MONTH")
    r = client.post("/billing/checkout", json={"plan_code": "starter", "interval": "month"}, headers=H)
    assert r.status_code == 503 and "PayPal" in r.json()["detail"]
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET")
    r = client.post("/billing/checkout", json={"plan_code": "starter", "interval": "year"}, headers=H)
    assert r.status_code == 503
    assert _calls("/v1/billing/subscriptions") == []


def test_plan_body_is_ex_vat_with_uk_vat_added_and_no_paypal_trial():
    cfg = paypal_api.settings()
    body = paypal_api.PayPalBilling(cfg).plan_body(
        product="PROD-1", plan_code="starter", name="Starter", interval="year", pence=10000
    )
    assert body["product_id"] == "PROD-1" and body["status"] == "ACTIVE"
    assert body["taxes"] == {"percentage": "20", "inclusive": False}
    [cycle] = body["billing_cycles"]  # one REGULAR cycle, forever: the trial is ours, not PayPal's
    assert cycle == {
        "frequency": {"interval_unit": "YEAR", "interval_count": 1},
        "tenure_type": "REGULAR",
        "sequence": 1,
        "total_cycles": 0,
        "pricing_scheme": {"fixed_price": {"currency_code": "GBP", "value": "100.00"}},
    }
    assert body["payment_preferences"]["auto_bill_outstanding"] is True
    assert paypal_api.value(1000) == "10.00" and paypal_api.value(5) == "0.05"
    assert paypal_api.vat_pence(300, "20") == 60


async def test_setup_creates_the_product_and_plans_with_idempotency_keys(reg: R.MemoryRegistry):
    api = paypal_api.PayPalBilling(paypal_api.settings())
    product = await api.create_product()
    plan = await api.create_plan(product=product, plan_code="ultimate", name="Ultimate", interval="month", pence=5000)
    assert product.startswith("PROD-") and plan.startswith("P-")
    [prod] = _calls("/v1/catalogs/products")
    assert prod["type"] == "SERVICE" and prod["category"] == "SOFTWARE"
    [body] = _calls("/v1/billing/plans")
    assert body["billing_cycles"][0]["pricing_scheme"]["fixed_price"]["value"] == "50.00"


# --------------------------------------------------------------------------- #
# Subscribe
# --------------------------------------------------------------------------- #


def test_subscribe_returns_the_approve_link_and_defers_the_start_to_the_trial_end(
    reg: R.MemoryRegistry, client: TestClient
):
    r = client.post("/billing/checkout", json={"plan_code": "comprehensive", "interval": "year"}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["url"].startswith("https://www.sandbox.paypal.test/webapps/billing/subscriptions?ba_token=")
    acc = _acc(reg)
    [body] = _calls("/v1/billing/subscriptions")
    assert body["plan_id"] == "P-COMP-Y"
    assert body["custom_id"] == acc["id"]
    assert body["subscriber"] == {"email_address": USER}
    assert body["start_time"] == _iso(acc["trial_ends_at"])  # nothing charged before the 90-day trial ends
    ctx = body["application_context"]
    assert ctx["return_url"] == "https://app.accnomos.example/settings/billing?checkout=success"
    assert ctx["cancel_url"] == "https://app.accnomos.example/settings/billing?checkout=cancelled"
    assert ctx["shipping_preference"] == "NO_SHIPPING" and ctx["user_action"] == "SUBSCRIBE_NOW"
    assert ctx["brand_name"] == "Accnomos"
    assert acc["stripe_subscription_id"] is None  # nothing is linked until PayPal's webhook says it is active
    assert [e["name"] for e in reg.events][-1] == "checkout_started"


def test_subscribe_after_the_trial_starts_now(reg: R.MemoryRegistry, client: TestClient):
    client.get("/account", headers=H)
    _acc(reg).update(status="trial_ended", trial_ends_at=S.now() - timedelta(days=1))
    S.forget()
    r = client.post("/billing/checkout", json={"plan_code": "starter", "interval": "month"}, headers=H)
    assert r.status_code == 200, r.text
    [body] = _calls("/v1/billing/subscriptions")
    assert "start_time" not in body and body["plan_id"] == "P-STARTER-M"


def test_subscribe_refuses_a_second_subscription(reg: R.MemoryRegistry, client: TestClient):
    _subscribed(reg, client)
    r = client.post("/billing/checkout", json={"plan_code": "ultimate", "interval": "month"}, headers=H)
    assert r.status_code == 409 and "Change plan" in r.json()["detail"]


async def test_discount_codes_are_refused_with_paypal_but_free_months_work(reg: R.MemoryRegistry, client: TestClient):
    await reg.create_code({"code": "TENOFF", "kind": "percent", "value": 10})
    await reg.create_code({"code": "YEARFREE", "kind": "free_months", "value": 12})
    r = client.post(
        "/billing/checkout", json={"plan_code": "starter", "interval": "month", "promo_code": "tenoff"}, headers=H
    )
    assert r.status_code == 400 and "contact us" in r.json()["detail"]
    assert _calls("/v1/billing/subscriptions") == []
    redeemed = client.post("/billing/redeem", json={"code": "TENOFF"}, headers=H).json()
    assert "PayPal subscription" in redeemed["message"]
    free = client.post("/billing/redeem", json={"code": "YEARFREE"}, headers=H).json()
    assert free["ok"] and free["account"]["status"] == "comped"


# --------------------------------------------------------------------------- #
# The webhook: verified with PayPal, idempotent
# --------------------------------------------------------------------------- #


def test_webhook_is_verified_with_paypal_using_the_event_exactly_as_received(reg: R.MemoryRegistry, client: TestClient):
    client.get("/account", headers=H)
    acc = _acc(reg)
    raw = json.dumps(_event("WH-1", "BILLING.SUBSCRIPTION.ACTIVATED", _sub(acc)), indent=3).encode()  # odd spacing
    r = client.post(WEBHOOK, content=raw, headers=SIGNED)
    assert r.status_code == 200 and r.json() == {"ok": True, "handled": True}
    [(_, _, body)] = [c for c in fakes.PAYPAL_CALLS if c[1] == "/v1/notifications/verify-webhook-signature"]
    assert body["webhook_id"] == "WH-OURS-123"
    assert body["auth_algo"] == SIGNED["PAYPAL-AUTH-ALGO"] and body["cert_url"] == SIGNED["PAYPAL-CERT-URL"]
    assert body["transmission_id"] == SIGNED["PAYPAL-TRANSMISSION-ID"]
    assert body["transmission_sig"] == SIGNED["PAYPAL-TRANSMISSION-SIG"]
    assert body["transmission_time"] == SIGNED["PAYPAL-TRANSMISSION-TIME"]
    assert body["webhook_event"]["id"] == "WH-1"
    sent = next(req for req in _raw_requests() if req.url.path == "/v1/notifications/verify-webhook-signature").content
    assert raw in sent  # spliced in byte for byte, not re-serialised


_REQUESTS: list = []


def _raw_requests() -> list:
    return _REQUESTS


@pytest.fixture(autouse=True)
def _keep_requests(monkeypatch: pytest.MonkeyPatch):
    _REQUESTS.clear()
    real = fakes.paypal_handle

    def spy(request):
        _REQUESTS.append(request)
        return real(request)

    monkeypatch.setattr(fakes, "paypal_handle", spy)
    yield


def test_a_bad_signature_is_refused_and_changes_nothing(reg: R.MemoryRegistry, client: TestClient):
    client.get("/account", headers=H)
    acc = _acc(reg)
    fakes.PAYPAL_STATE["verify"] = "FAILURE"
    r = _post(client, _event("WH-bad", "BILLING.SUBSCRIPTION.ACTIVATED", _sub(acc)))
    assert r.status_code == 400 and "signature" in r.json()["detail"]
    assert _acc(reg)["status"] == "trialing" and _acc(reg)["stripe_subscription_id"] is None
    assert reg.stripe_events == {}  # not recorded: a genuine delivery later still counts


def test_missing_signature_headers_are_refused_without_asking_paypal(reg: R.MemoryRegistry, client: TestClient):
    client.get("/account", headers=H)
    acc = _acc(reg)
    headers = {k: v for k, v in SIGNED.items() if k != "PAYPAL-TRANSMISSION-SIG"}
    r = _post(client, _event("WH-2", "BILLING.SUBSCRIPTION.ACTIVATED", _sub(acc)), headers)
    assert r.status_code == 400 and "PAYPAL-TRANSMISSION-SIG" in r.json()["detail"]
    assert _calls("/v1/notifications/verify-webhook-signature") == []


def test_without_a_webhook_id_nothing_is_trusted(reg: R.MemoryRegistry, client: TestClient, monkeypatch):
    monkeypatch.delenv("PAYPAL_WEBHOOK_ID")
    client.get("/account", headers=H)
    r = _post(client, _event("WH-3", "BILLING.SUBSCRIPTION.ACTIVATED", _sub(_acc(reg))))
    assert r.status_code == 400 and "PAYPAL_WEBHOOK_ID" in r.json()["detail"]


def test_activated_mirrors_the_subscription_and_is_idempotent(reg: R.MemoryRegistry, client: TestClient):
    client.get("/account", headers=H)
    acc = _acc(reg)
    event = _event("WH-act", "BILLING.SUBSCRIPTION.ACTIVATED", _sub(acc))
    assert _post(client, event).json() == {"ok": True, "handled": True}
    acc = _acc(reg)
    assert acc["status"] == "active" and acc["plan_code"] == "starter" and acc["billing_interval"] == "year"
    assert acc["stripe_subscription_id"] == "I-SUB1"
    assert acc["current_period_end"] == datetime(2027, 11, 11, 10, tzinfo=UTC)
    view = client.get("/account", headers=H).json()
    assert view["has_payment_account"] is True and view["status"] == "active"
    # the same delivery again: acknowledged, nothing changes
    acc["plan_code"] = "ultimate"
    assert _post(client, event).json() == {"ok": True, "duplicate": True}
    assert _acc(reg)["plan_code"] == "ultimate"
    assert [e["name"] for e in reg.events].count("subscription_active") == 1


def test_activated_with_a_deferred_start_stays_in_trial_until_then(reg: R.MemoryRegistry, client: TestClient):
    client.get("/account", headers=H)
    acc = _acc(reg)
    start = S.now() + timedelta(days=60)
    _post(client, _event("WH-def", "BILLING.SUBSCRIPTION.ACTIVATED", _sub(acc, start_time=_iso(start))))
    acc = _acc(reg)
    assert acc["status"] == "trialing" and acc["stripe_subscription_id"] == "I-SUB1"
    assert abs((acc["trial_ends_at"] - start).total_seconds()) < 1
    # the first payment, at the start: active
    fakes.PAYPAL_STATE["subscriptions"]["I-SUB1"] = _sub(acc, next="2028-01-10T10:00:00Z")
    sale = {"id": "SALE-1", "state": "completed", "billing_agreement_id": "I-SUB1", "amount": {"total": "120.00"}}
    assert _post(client, _event("WH-sale", "PAYMENT.SALE.COMPLETED", sale)).json()["handled"] is True
    acc = _acc(reg)
    assert acc["status"] == "active" and acc["current_period_end"] == datetime(2028, 1, 10, 10, tzinfo=UTC)


def test_a_failed_event_is_forgotten_so_paypals_retry_gets_another_go(
    reg: R.MemoryRegistry, client: TestClient, monkeypatch
):
    client.get("/account", headers=H)
    acc = _acc(reg)
    real = reg.update_account
    calls = {"n": 0}

    async def flaky(account_id: str, patch: dict):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database blip")
        return await real(account_id, patch)

    monkeypatch.setattr(reg, "update_account", flaky)
    event = _event("WH-retry", "BILLING.SUBSCRIPTION.ACTIVATED", _sub(acc))
    assert _post(client, event).status_code == 500  # PayPal retries a non-2xx
    assert "WH-retry" not in reg.stripe_events
    assert _post(client, event).json()["handled"] is True
    assert _acc(reg)["status"] == "active"


@pytest.mark.parametrize("event_type", ["BILLING.SUBSCRIPTION.PAYMENT.FAILED", "BILLING.SUBSCRIPTION.SUSPENDED"])
def test_failed_payment_and_suspension_are_past_due(event_type: str, reg: R.MemoryRegistry, client: TestClient):
    acc = _subscribed(reg, client)
    assert _post(client, _event("WH-f", event_type, _sub(acc, status="SUSPENDED"))).json()["handled"] is True
    assert _acc(reg)["status"] == "past_due"


def test_an_older_subscription_does_not_speak_for_the_account(reg: R.MemoryRegistry, client: TestClient):
    acc = _subscribed(reg, client)
    _post(client, _event("WH-old", "BILLING.SUBSCRIPTION.CANCELLED", _sub(acc, "I-OLD", status="CANCELLED")))
    assert _acc(reg)["status"] == "active" and _acc(reg)["stripe_subscription_id"] == "I-SUB1"


# --------------------------------------------------------------------------- #
# Cancel, change plan, manage
# --------------------------------------------------------------------------- #


def test_cancel_keeps_the_paid_for_time_then_ends(reg: R.MemoryRegistry, client: TestClient):
    _subscribed(reg, client)
    r = client.post("/billing/cancel", headers=H)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True and "11 November 2027" in out["message"]
    assert out["account"]["status"] == "active" and out["account"]["cancel_at_period_end"] is True
    [body] = _calls("/v1/billing/subscriptions/I-SUB1/cancel")
    assert 1 <= len(body["reason"]) <= 128
    acc = _acc(reg)
    assert acc["stripe_subscription_id"] is None
    # PayPal's CANCELLED event for it afterwards changes nothing
    ev = _event("WH-c", "BILLING.SUBSCRIPTION.CANCELLED", _sub(acc, status="CANCELLED"))
    assert _post(client, ev).json()["handled"] is False
    assert _acc(reg)["status"] == "active"
    # once the period has passed, the account is cancelled (read-only) the next time it is seen
    _acc(reg)["current_period_end"] = S.now() - timedelta(minutes=1)
    S.forget()
    view = client.get("/account", headers=H).json()
    assert view["status"] == "cancelled" and view["read_only"] is True


def test_re_subscribing_before_the_period_ends_starts_paying_then(reg: R.MemoryRegistry, client: TestClient):
    _subscribed(reg, client)
    client.post("/billing/cancel", headers=H)
    r = client.post("/billing/checkout", json={"plan_code": "starter", "interval": "year"}, headers=H)
    assert r.status_code == 200, r.text
    body = _calls("/v1/billing/subscriptions")[-1]
    assert body["start_time"] == "2027-11-11T10:00:00Z"  # no double charge for time already paid for


def test_cancel_during_a_deferred_start_leaves_the_trial_running(reg: R.MemoryRegistry, client: TestClient):
    client.get("/account", headers=H)
    acc = _acc(reg)
    trial_end = acc["trial_ends_at"]
    fakes.PAYPAL_STATE["subscriptions"]["I-SUB1"] = _sub(acc)
    _post(client, _event("WH-d", "BILLING.SUBSCRIPTION.ACTIVATED", _sub(acc, start_time=_iso(trial_end))))
    out = client.post("/billing/cancel", headers=H).json()
    assert out["ok"] and out["account"]["status"] == "trialing" and out["account"]["read_only"] is False
    assert _acc(reg)["stripe_subscription_id"] is None


def test_cancelled_at_paypal_keeps_paid_time_and_expired_ends_now(reg: R.MemoryRegistry, client: TestClient):
    acc = _subscribed(reg, client)
    _post(client, _event("WH-x", "BILLING.SUBSCRIPTION.CANCELLED", _sub(acc, status="CANCELLED")))
    acc = _acc(reg)
    assert acc["status"] == "active" and acc["cancel_at_period_end"] and acc["stripe_subscription_id"] is None
    acc = _subscribed(reg, client, "I-SUB2")
    _post(client, _event("WH-y", "BILLING.SUBSCRIPTION.EXPIRED", _sub(acc, "I-SUB2", status="EXPIRED")))
    assert _acc(reg)["status"] == "cancelled"
    assert "subscription_cancelled" in [e["name"] for e in reg.events]


def test_cancel_without_a_subscription_says_so(reg: R.MemoryRegistry, client: TestClient):
    out = client.post("/billing/cancel", headers=H).json()
    assert out["ok"] is False and _calls("/v1/billing/subscriptions/I-SUB1/cancel") == []


def test_change_plan_asks_paypal_for_a_revision_and_the_update_moves_the_plan(
    reg: R.MemoryRegistry, client: TestClient
):
    acc = _subscribed(reg, client)
    r = client.post("/billing/change-plan", json={"plan_code": "ultimate", "interval": "month"}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["url"].startswith("https://www.sandbox.paypal.test/webapps/billing/subscriptions/update")
    [body] = _calls("/v1/billing/subscriptions/I-SUB1/revise")
    assert body["plan_id"] == "P-ULT-M"
    assert body["application_context"]["return_url"].endswith("/settings/billing?change=success")
    assert _acc(reg)["plan_code"] == "starter"  # nothing moves until PayPal says the buyer approved
    _post(client, _event("WH-u", "BILLING.SUBSCRIPTION.UPDATED", _sub(acc, plan="P-ULT-M")))
    acc = _acc(reg)
    assert acc["plan_code"] == "ultimate" and acc["billing_interval"] == "month" and acc["status"] == "active"


def test_change_plan_needs_a_subscription_and_a_different_plan(reg: R.MemoryRegistry, client: TestClient):
    r = client.post("/billing/change-plan", json={"plan_code": "ultimate", "interval": "month"}, headers=H)
    assert r.status_code == 409
    _subscribed(reg, client)
    r = client.post("/billing/change-plan", json={"plan_code": "starter", "interval": "year"}, headers=H)
    assert r.status_code == 400


def test_manage_billing_opens_paypals_automatic_payments_page(reg: R.MemoryRegistry, client: TestClient):
    client.get("/account", headers=H)
    assert client.post("/billing/portal", headers=H).status_code == 409
    _subscribed(reg, client)
    r = client.post("/billing/portal", headers=H)
    assert r.json() == {"url": "https://www.sandbox.paypal.com/myaccount/autopay/"}


# --------------------------------------------------------------------------- #
# Top-up: a PayPal order, captured when approved
# --------------------------------------------------------------------------- #


def test_top_up_order_carries_vat_and_is_captured_once(reg: R.MemoryRegistry, client: TestClient):
    r = client.post("/billing/topup", headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["url"].startswith("https://www.sandbox.paypal.test/checkoutnow?token=ORDER-FAKE")
    acc = _acc(reg)
    [order] = _calls("/v2/checkout/orders")
    assert order["intent"] == "CAPTURE"
    [unit] = order["purchase_units"]
    assert unit["custom_id"] == f"topup:{acc['id']}"
    assert unit["amount"] == {
        "currency_code": "GBP",
        "value": "3.60",
        "breakdown": {
            "item_total": {"currency_code": "GBP", "value": "3.00"},
            "tax_total": {"currency_code": "GBP", "value": "0.60"},
        },
    }
    assert unit["items"][0]["tax"] == {"currency_code": "GBP", "value": "0.60"}
    ctx = order["payment_source"]["paypal"]["experience_context"]
    assert ctx["return_url"].endswith("?topup=success") and ctx["user_action"] == "PAY_NOW"
    order_id = r.json()["url"].rsplit("=", 1)[-1]
    approved = {"id": order_id, "status": "APPROVED", "purchase_units": [{"custom_id": f"topup:{acc['id']}"}]}
    assert _post(client, _event("WH-o1", "CHECKOUT.ORDER.APPROVED", approved)).json()["handled"] is True
    assert client.get("/account", headers=H).json()["usage"]["topup_docs_remaining"] == P.TOPUP_DOCS
    # PayPal sends it again under another id: the order is already captured, nothing more is added
    assert _post(client, _event("WH-o2", "CHECKOUT.ORDER.APPROVED", approved)).json()["handled"] is False
    assert client.get("/account", headers=H).json()["usage"]["topup_docs_remaining"] == P.TOPUP_DOCS
    assert len(_calls(f"/v2/checkout/orders/{order_id}/capture")) == 2
