"""Stripe Billing (app/billing): Checkout, the portal, top-ups, the webhook (signature, idempotency, status mapping)
and promo codes of each kind, against the fake in app/billing/fakes.py."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.billing import fakes, stripe_api
from app.billing import plans as P
from app.billing import registry as R
from app.billing import routes as billing_routes
from app.billing import service as S

USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
SECRET = "whsec_test_secret_123"


@pytest.fixture
def reg(monkeypatch: pytest.MonkeyPatch):
    r = R.MemoryRegistry(storage=True)
    R.install(r)
    S.forget()
    fakes.reset()
    fakes.install()
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_billing_123")
    monkeypatch.setenv("PAYMENTS_PROVIDER", "stripe")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("ACCNOMOS_WEB_URL", "https://app.accnomos.example")
    for k in ("BILLING_RETURN_URL", "STRIPE_PRICE_TOPUP", "STRIPE_PRICE_STARTER_MONTH"):
        monkeypatch.delenv(k, raising=False)

    async def no_books(_request) -> dict:
        return {"bank_feeds": 0, "marketplaces": 0, "autopilot_rules": 0, "users": 1}

    monkeypatch.setattr(billing_routes, "read_gauges", no_books)
    r.plans["starter"].update(stripe_price_month="price_starter_m", stripe_price_year="price_starter_y")
    r.plans["ultimate"].update(stripe_price_month="price_ult_m", stripe_price_year="price_ult_y")
    yield r
    R.install(None)
    S.forget()
    stripe_api.TRANSPORT = None


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def _acc(reg: R.MemoryRegistry) -> dict:
    return next(iter(reg.accounts.values()))


def _last(path: str) -> dict[str, str]:
    return next(form for method, p, form in reversed(fakes.CALLS) if p == path and method == "POST")


async def _code(reg: R.MemoryRegistry, code: str, kind: str, value: int, **kw) -> dict:
    return await reg.create_code({"code": code, "kind": kind, "value": value, **kw})


# --------------------------------------------------------------------------- #
# Checkout, portal, top-up
# --------------------------------------------------------------------------- #


def test_checkout_carries_the_rest_of_the_trial_without_a_card(reg: R.MemoryRegistry, client: TestClient):
    r = client.post("/billing/checkout", json={"plan_code": "starter", "interval": "month"}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["url"].startswith("https://checkout.stripe.test/")
    acc = _acc(reg)
    assert acc["stripe_customer_id"].startswith("cus_fake")
    assert _last("/v1/customers")["metadata[account_id]"] == acc["id"]
    form = _last("/v1/checkout/sessions")
    assert form["mode"] == "subscription" and form["line_items[0][price]"] == "price_starter_m"
    assert form["customer"] == acc["stripe_customer_id"] and form["client_reference_id"] == acc["id"]
    assert form["payment_method_collection"] == "if_required"
    assert form["subscription_data[trial_settings][end_behavior][missing_payment_method]"] == "pause"
    assert int(form["subscription_data[trial_end]"]) == int(acc["trial_ends_at"].timestamp())
    assert form["automatic_tax[enabled]"] == "true" and form["tax_id_collection[enabled]"] == "true"
    assert form["subscription_data[metadata][plan_code]"] == "starter"
    assert "allow_promotion_codes" not in form and "discounts[0][coupon]" not in form
    assert form["success_url"] == "https://app.accnomos.example/settings/billing?checkout=success"
    assert [e["name"] for e in reg.events][-1] == "checkout_started"


def test_checkout_after_the_trial_has_no_trial(reg: R.MemoryRegistry, client: TestClient):
    client.get("/account", headers=H)
    _acc(reg)["trial_ends_at"] = datetime.now(UTC) + timedelta(hours=10)  # under Stripe's 48 hours
    S.forget()
    assert (
        client.post("/billing/checkout", json={"plan_code": "ultimate", "interval": "year"}, headers=H).status_code
        == 200
    )
    form = _last("/v1/checkout/sessions")
    assert "subscription_data[trial_end]" not in form and "payment_method_collection" not in form
    assert form["line_items[0][price]"] == "price_ult_y"


def test_checkout_needs_prices_and_refuses_a_second_subscription(
    reg: R.MemoryRegistry, client: TestClient, monkeypatch
):
    r = client.post("/billing/checkout", json={"plan_code": "comprehensive", "interval": "month"}, headers=H)
    assert r.status_code == 503 and "Prices" in r.json()["detail"]
    monkeypatch.setenv("STRIPE_PRICE_COMPREHENSIVE_MONTH", "price_env")
    assert (
        client.post(
            "/billing/checkout", json={"plan_code": "comprehensive", "interval": "month"}, headers=H
        ).status_code
        == 200
    )
    assert _last("/v1/checkout/sessions")["line_items[0][price]"] == "price_env"
    _acc(reg).update(stripe_subscription_id="sub_1", status="active")
    S.forget()
    assert (
        client.post("/billing/checkout", json={"plan_code": "starter", "interval": "month"}, headers=H).status_code
        == 409
    )


def test_checkout_without_stripe_is_503(reg: R.MemoryRegistry, client: TestClient, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY")
    assert (
        client.post("/billing/checkout", json={"plan_code": "starter", "interval": "month"}, headers=H).status_code
        == 503
    )


@pytest.mark.parametrize("value", [None, "", "none", "paypal-typo", "NONE"])
def test_payments_are_off_unless_a_provider_is_chosen(
    value: str | None, reg: R.MemoryRegistry, client: TestClient, monkeypatch
):
    """PAYMENTS_PROVIDER unset (the default) or unknown: plans, the trial and codes work, nothing can be bought, and
    the Stripe key alone opens nothing."""
    if value is None:
        monkeypatch.delenv("PAYMENTS_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("PAYMENTS_PROVIDER", value)
    fakes.reset()
    assert stripe_api.client() is None
    acc = client.get("/account", headers=H).json()
    assert acc["payments_provider"] == "none" and acc["status"] == "trialing"
    for path, body in (
        ("/billing/checkout", {"plan_code": "starter", "interval": "month"}),
        ("/billing/portal", None),
        ("/billing/topup", None),
    ):
        r = client.post(path, json=body, headers=H)
        assert r.status_code == 503 and "free trial and promo codes work" in r.json()["detail"], path
    assert fakes.CALLS == []  # nothing reached Stripe


def test_portal_and_top_up(reg: R.MemoryRegistry, client: TestClient):
    assert client.post("/billing/portal", headers=H).status_code == 409  # no customer yet
    r = client.post("/billing/topup", headers=H)
    assert r.status_code == 200 and r.json()["url"]
    form = _last("/v1/checkout/sessions")
    assert form["mode"] == "payment" and form["metadata[kind]"] == "topup" and form["metadata[docs]"] == "100"
    assert form["line_items[0][price_data][unit_amount]"] == "300"
    assert form["line_items[0][price_data][tax_behavior]"] == "exclusive"
    assert form["automatic_tax[enabled]"] == "true"
    r = client.post("/billing/portal", headers=H)
    assert r.status_code == 200 and r.json()["url"].startswith("https://billing.stripe.test/")
    assert _last("/v1/billing_portal/sessions")["return_url"] == "https://app.accnomos.example/settings/billing"


# --------------------------------------------------------------------------- #
# Webhook
# --------------------------------------------------------------------------- #


def _post(client: TestClient, event: dict, secret: str = SECRET, ts: int | None = None):
    payload = json.dumps(event).encode()
    return client.post(
        "/billing/stripe/webhook",
        content=payload,
        headers={"Stripe-Signature": stripe_api.sign(payload, secret, ts), "Content-Type": "application/json"},
    )


def _sub_event(event_id: str, acc: dict, status: str, kind: str = "customer.subscription.updated", **extra) -> dict:
    sub = {
        "id": "sub_123",
        "object": "subscription",
        "customer": acc.get("stripe_customer_id") or "cus_x",
        "status": status,
        "cancel_at_period_end": False,
        "trial_end": None,
        "metadata": {"account_id": acc["id"]},
        "items": {
            "data": [
                {
                    "price": {"id": "price_starter_y", "recurring": {"interval": "year"}},
                    "current_period_end": 1_800_000_000,
                }
            ]
        },
        **extra,
    }
    return {"id": event_id, "type": kind, "data": {"object": sub}}


def test_webhook_signature_is_checked(reg: R.MemoryRegistry, client: TestClient):
    client.get("/account", headers=H)
    event = _sub_event("evt_1", _acc(reg), "active")
    assert _post(client, event, secret="whsec_wrong").status_code == 400
    assert _post(client, event, ts=int(time.time()) - 3600).status_code == 400  # replayed an hour later
    r = client.post("/billing/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "t=1"})
    assert r.status_code == 400
    assert _acc(reg)["status"] == "trialing"


def test_signature_verification_unit():
    body = b'{"id":"evt"}'
    header = stripe_api.sign(body, "whsec_a", ts=1_000_000)
    stripe_api.verify_signature(body, header, "whsec_a", now=1_000_100)
    for bad in (
        lambda: stripe_api.verify_signature(body + b" ", header, "whsec_a", now=1_000_100),
        lambda: stripe_api.verify_signature(body, header, "whsec_a", now=1_000_400),
        lambda: stripe_api.verify_signature(body, header, "", now=1_000_100),
        lambda: stripe_api.verify_signature(body, "v1=abc", "whsec_a", now=1_000_100),
    ):
        with pytest.raises(stripe_api.BadSignature):
            bad()
    # several v1 signatures (secret rolling): one match is enough
    stripe_api.verify_signature(body, header + ",v1=deadbeef", "whsec_a", now=1_000_000)


def test_webhook_mirrors_the_subscription_and_is_idempotent(reg: R.MemoryRegistry, client: TestClient):
    client.get("/account", headers=H)
    acc = _acc(reg)
    r = _post(client, _sub_event("evt_1", acc, "active"))
    assert r.status_code == 200 and r.json() == {"ok": True, "handled": True}
    acc = _acc(reg)
    assert acc["status"] == "active" and acc["plan_code"] == "starter" and acc["billing_interval"] == "year"
    assert acc["stripe_subscription_id"] == "sub_123"
    assert acc["current_period_end"] == datetime.fromtimestamp(1_800_000_000, UTC)
    assert [e["name"] for e in reg.events].count("subscription_active") == 1
    # the same event again: acknowledged, nothing changes
    acc["plan_code"] = "ultimate"
    assert _post(client, _sub_event("evt_1", acc, "active")).json() == {"ok": True, "duplicate": True}
    assert _acc(reg)["plan_code"] == "ultimate"
    assert [e["name"] for e in reg.events].count("subscription_active") == 1


@pytest.mark.parametrize(
    ("stripe_status", "ours"),
    [
        ("trialing", "trialing"),
        ("active", "active"),
        ("past_due", "past_due"),
        ("unpaid", "past_due"),
        ("canceled", "cancelled"),
        ("paused", "trial_ended"),  # the trial ended without a card
        ("incomplete", "trialing"),  # first payment pending: the account keeps its own status
    ],
)
def test_webhook_status_mapping(stripe_status: str, ours: str, reg: R.MemoryRegistry, client: TestClient):
    client.get("/account", headers=H)
    _post(client, _sub_event(f"evt_{stripe_status}", _acc(reg), stripe_status))
    assert _acc(reg)["status"] == ours


def test_webhook_deleted_cancels_and_frees_the_subscription(reg: R.MemoryRegistry, client: TestClient):
    client.get("/account", headers=H)
    _post(client, _sub_event("evt_a", _acc(reg), "active"))
    _post(client, _sub_event("evt_b", _acc(reg), "canceled", kind="customer.subscription.deleted"))
    acc = _acc(reg)
    assert acc["status"] == "cancelled" and acc["stripe_subscription_id"] is None
    assert "subscription_cancelled" in [e["name"] for e in reg.events]
    # read-only now
    assert client.post("/invoices", json={}, headers=H).json()["code"] == "read_only"


def test_webhook_ignores_an_older_subscription(reg: R.MemoryRegistry, client: TestClient):
    client.get("/account", headers=H)
    _acc(reg)["stripe_subscription_id"] = "sub_new"
    _post(client, _sub_event("evt_old", _acc(reg), "canceled", kind="customer.subscription.deleted"))
    assert _acc(reg)["status"] == "trialing"


def test_webhook_failure_is_forgotten_for_the_retry(reg: R.MemoryRegistry, client: TestClient, monkeypatch):
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
    assert _post(client, _sub_event("evt_retry", acc, "active")).status_code == 500  # Stripe retries a 5xx
    assert "evt_retry" not in reg.stripe_events
    assert _post(client, _sub_event("evt_retry", acc, "active")).json()["handled"] is True
    assert _acc(reg)["status"] == "active"


def test_webhook_top_up_and_checkout_completion(reg: R.MemoryRegistry, client: TestClient):
    client.get("/account", headers=H)
    acc = _acc(reg)
    topup = {
        "id": "evt_t",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "mode": "payment",
                "payment_status": "paid",
                "client_reference_id": acc["id"],
                "metadata": {"account_id": acc["id"], "kind": "topup", "docs": "100"},
            }
        },
    }
    assert _post(client, topup).json()["handled"] is True
    assert _post(client, topup).json()["duplicate"] is True  # paid once, added once
    usage = reg.usage[(acc["id"], P.month_start())]
    assert usage["topup_docs_remaining"] == 100
    assert usage["topup_expires_at"] > datetime.now(UTC) + timedelta(days=360)
    done = {
        "id": "evt_c",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "mode": "subscription",
                "customer": "cus_9",
                "subscription": "sub_9",
                "metadata": {"account_id": acc["id"], "plan_code": "starter"},
            }
        },
    }
    _post(client, done)
    acc = _acc(reg)
    assert acc["stripe_customer_id"] == "cus_9" and acc["stripe_subscription_id"] == "sub_9"


# --------------------------------------------------------------------------- #
# Promo codes
# --------------------------------------------------------------------------- #


async def test_percent_and_fixed_codes_apply_a_coupon_at_checkout(reg: R.MemoryRegistry, client: TestClient):
    await _code(reg, "LAUNCH20", "percent", 20)
    r = client.post(
        "/billing/checkout", json={"plan_code": "starter", "interval": "month", "promo_code": "launch20"}, headers=H
    )
    assert r.status_code == 200, r.text
    coupon = _last("/v1/coupons")
    assert coupon["percent_off"] == "20" and coupon["duration"] == "once"
    form = _last("/v1/checkout/sessions")
    assert form["discounts[0][coupon]"].startswith("coupon_fake") and form["metadata[promo_code]"] == "LAUNCH20"
    assert "allow_promotion_codes" not in form
    assert reg.codes["LAUNCH20"]["stripe_coupon_id"] == form["discounts[0][coupon]"]
    # counted when the checkout completes
    acc = _acc(reg)
    _post(
        client,
        {
            "id": "evt_p",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "mode": "subscription",
                    "subscription": "sub_p",
                    "metadata": {"account_id": acc["id"], "promo_code": "LAUNCH20"},
                }
            },
        },
    )
    assert reg.codes["LAUNCH20"]["redeemed_count"] == 1
    await _code(reg, "FIVER", "fixed", 500, duration_months=3)
    _acc(reg)["stripe_subscription_id"] = None
    S.forget()
    client.post(
        "/billing/checkout", json={"plan_code": "starter", "interval": "month", "promo_code": "FIVER"}, headers=H
    )
    coupon = _last("/v1/coupons")
    assert coupon["amount_off"] == "500" and coupon["currency"] == "gbp"
    assert coupon["duration"] == "repeating" and coupon["duration_in_months"] == "3"


async def test_code_expiry_max_and_plan_restriction(reg: R.MemoryRegistry, client: TestClient):
    await _code(reg, "OLD", "percent", 10, expires_at=datetime.now(UTC) - timedelta(days=1))
    await _code(reg, "GONE", "percent", 10, max_redemptions=1, redeemed_count=1)
    await _code(reg, "ULTONLY", "percent", 10, plan_codes=["ultimate"])
    await _code(reg, "OFF", "percent", 10, active=False)
    cases = {
        "OLD": "expired",
        "GONE": "used up",
        "ULTONLY": "Ultimate plan only",
        "OFF": "isn't valid",
        "NOPE": "isn't valid",
    }
    for code, words in cases.items():
        r = client.post(
            "/billing/checkout", json={"plan_code": "starter", "interval": "month", "promo_code": code}, headers=H
        )
        assert r.status_code == 400 and words in r.json()["detail"], (code, r.text)
    r = client.post(
        "/billing/checkout", json={"plan_code": "ultimate", "interval": "month", "promo_code": "ULTONLY"}, headers=H
    )
    assert r.status_code == 200


async def test_free_months_code_comps_without_stripe(reg: R.MemoryRegistry, client: TestClient):
    await _code(reg, "YEARFREE", "free_months", 12, max_redemptions=2)
    client.get("/account", headers=H)
    trial_end = _acc(reg)["trial_ends_at"]
    n_calls = len(fakes.CALLS)
    r = client.post("/billing/redeem", json={"code": "yearfree"}, headers=H)
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True, body
    assert body["account"]["status"] == "comped"
    acc = _acc(reg)
    assert acc["status"] == "comped" and acc["comp_until"].date() == R.add_months(trial_end, 12).date()
    assert len(fakes.CALLS) == n_calls  # no Stripe call
    assert reg.codes["YEARFREE"]["redeemed_count"] == 1
    again = client.post("/billing/redeem", json={"code": "YEARFREE"}, headers=H).json()
    assert again["ok"] is False and "already" in again["message"]
    # the comp's limits are the plan's (comprehensive here), not read-only
    assert client.get("/account", headers=H).json()["read_only"] is False
    # free months at checkout are refused (they are not a coupon)
    r = client.post(
        "/billing/checkout", json={"plan_code": "starter", "interval": "month", "promo_code": "YEARFREE"}, headers=H
    )
    assert r.status_code == 400 and "redeem" in r.json()["detail"]
    # a checkout during the comp starts billing when the comp ends
    client.post("/billing/checkout", json={"plan_code": "starter", "interval": "month"}, headers=H)
    assert int(_last("/v1/checkout/sessions")["subscription_data[trial_end]"]) == int(acc["comp_until"].timestamp())


async def test_free_months_code_restricted_to_a_plan_sets_that_plan(reg: R.MemoryRegistry, client: TestClient):
    await _code(reg, "ULTYEAR", "free_months", 12, plan_codes=["ultimate"])
    body = client.post("/billing/redeem", json={"code": "ULTYEAR"}, headers=H).json()
    assert body["ok"] and body["account"]["plan_code"] == "ultimate"
    assert body["account"]["limits"]["docs"] == 1500


async def test_redeeming_a_discount_code_points_to_checkout(reg: R.MemoryRegistry, client: TestClient):
    await _code(reg, "LAUNCH20", "percent", 20)
    body = client.post("/billing/redeem", json={"code": "LAUNCH20"}, headers=H).json()
    assert body["ok"] and "checkout" in body["message"] and reg.codes["LAUNCH20"]["redeemed_count"] == 0
    bad = client.post("/billing/redeem", json={"code": "NOPE"}, headers=H).json()
    assert bad["ok"] is False
    assert client.post("/billing/redeem", json={"code": "bad code!"}, headers=H).status_code == 400


async def test_free_months_refused_for_a_paying_account(reg: R.MemoryRegistry, client: TestClient):
    await _code(reg, "YEARFREE", "free_months", 12)
    client.get("/account", headers=H)
    _acc(reg).update(status="active", stripe_subscription_id="sub_1")
    S.forget()
    body = client.post("/billing/redeem", json={"code": "YEARFREE"}, headers=H).json()
    assert body["ok"] is False and reg.codes["YEARFREE"]["redeemed_count"] == 0
