"""Stand-ins for the Stripe Billing endpoints app/billing/stripe_api.py calls and the PayPal endpoints
app/billing/paypal_api.py calls, for the unit tests and test mode (`ACCNOMOS_TEST_MODE=1`), so no request ever
reaches api.stripe.com or PayPal from either. Every request is kept in `CALLS` (Stripe: method, path, form fields) or
`PAYPAL_CALLS` (method, path, JSON body) for the tests to check. The PayPal answers follow the shapes in PayPal's
published schemas (see app/billing/paypal_api.py); they are not recordings of real sandbox answers."""

from __future__ import annotations

import itertools
from typing import Any
from urllib.parse import parse_qsl

import httpx

CALLS: list[tuple[str, str, dict[str, str]]] = []
_ids = itertools.count(1)


def reset() -> None:
    CALLS.clear()


def _form(request: httpx.Request) -> dict[str, str]:
    body = request.content.decode() if request.content else ""
    return dict(parse_qsl(body, keep_blank_values=True))


def handle(request: httpx.Request) -> httpx.Response:
    path, method = request.url.path, request.method
    form = _form(request)
    CALLS.append((method, path, form))
    n = next(_ids)
    out: dict[str, Any]
    if path == "/v1/customers" and method == "POST":
        out = {"id": f"cus_fake{n}", "email": form.get("email")}
    elif path == "/v1/checkout/sessions" and method == "POST":
        out = {"id": f"cs_fake{n}", "url": f"https://checkout.stripe.test/c/cs_fake{n}", "mode": form.get("mode")}
    elif path == "/v1/billing_portal/sessions" and method == "POST":
        out = {"id": f"bps_fake{n}", "url": f"https://billing.stripe.test/p/bps_fake{n}"}
    elif path == "/v1/coupons" and method == "POST":
        out = {"id": f"coupon_fake{n}"}
    elif path == "/v1/products" and method == "POST":
        out = {"id": f"prod_fake{n}"}
    elif path == "/v1/prices" and method == "POST":
        out = {"id": f"price_fake{n}", "product": form.get("product")}
    elif path.startswith("/v1/prices/") and method == "GET":
        out = {"id": path.rsplit("/", 1)[-1], "product": "prod_fake0"}
    elif path.startswith("/v1/subscriptions/"):
        out = {
            "id": path.rsplit("/", 1)[-1],
            "status": "active",
            "cancel_at_period_end": form.get("cancel_at_period_end") == "true",
            "current_period_end": 1_800_000_000,
            "trial_end": None,
        }
    elif path == "/v1/invoices" and method == "GET":
        invoice = {
            "id": "in_fake1",
            "number": "ACC-0001",
            "status": "paid",
            "total": 2400,
            "currency": "gbp",
            "created": 1_790_000_000,
            "hosted_invoice_url": "https://invoice.stripe.test/i/in_fake1",
        }
        out = {"data": [invoice], "has_more": False}
    else:
        return httpx.Response(404, json={"error": {"message": f"fake: no {method} {path}"}})
    return httpx.Response(200, json=out)


def install() -> None:
    from app.billing import stripe_api

    stripe_api.TRANSPORT = httpx.MockTransport(handle)


# --------------------------------------------------------------------------- #
# PayPal (app/billing/paypal_api.py): the same idea, JSON bodies
# --------------------------------------------------------------------------- #

PAYPAL_CALLS: list[tuple[str, str, Any]] = []  # (method, path, JSON body or form) for the tests to check
PAYPAL_STATE: dict[str, Any] = {
    "verify": "SUCCESS",  # what verify-webhook-signature answers
    "subscriptions": {},  # id -> the subscription as GET answers it
    "captured": set(),  # order ids already captured
}
_pp_ids = itertools.count(1)


def paypal_reset() -> None:
    PAYPAL_CALLS.clear()
    PAYPAL_STATE.update(verify="SUCCESS", subscriptions={}, captured=set())


def _json(request: httpx.Request) -> Any:
    import json

    if not request.content:
        return None
    try:
        return json.loads(request.content)
    except ValueError:
        return _form(request)


def paypal_handle(request: httpx.Request) -> httpx.Response:
    path, method = request.url.path, request.method
    body = _json(request)
    PAYPAL_CALLS.append((method, path, body))
    n = next(_pp_ids)
    if path == "/v1/oauth2/token" and method == "POST":
        return httpx.Response(200, json={"access_token": "A21AA-fake", "token_type": "Bearer", "expires_in": 32400})
    if not request.headers.get("Authorization", "").startswith("Bearer "):
        return httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE", "message": "no token"})
    if path == "/v1/catalogs/products" and method == "POST":
        return httpx.Response(201, json={"id": f"PROD-FAKE{n}", "name": body.get("name")})
    if path == "/v1/billing/plans" and method == "POST":
        return httpx.Response(201, json={"id": f"P-FAKE{n}", "status": body.get("status"), "name": body.get("name")})
    if path == "/v1/billing/subscriptions" and method == "POST":
        sid = f"I-FAKE{n}"
        sub = {
            "id": sid,
            "status": "APPROVAL_PENDING",
            "plan_id": body.get("plan_id"),
            "custom_id": body.get("custom_id"),
            "start_time": body.get("start_time") or "2026-11-11T00:00:00Z",
        }
        PAYPAL_STATE["subscriptions"][sid] = sub
        approve = f"https://www.sandbox.paypal.test/webapps/billing/subscriptions?ba_token=BA-{n}"
        return httpx.Response(
            201,
            json={
                **sub,
                "links": [
                    {"href": approve, "rel": "approve", "method": "GET"},
                    {"href": f"https://api-m.sandbox.paypal.test/v1/billing/subscriptions/{sid}", "rel": "self"},
                ],
            },
        )
    if path.startswith("/v1/billing/subscriptions/"):
        parts = path.split("/")
        sid = parts[4]
        sub = PAYPAL_STATE["subscriptions"].get(sid)
        if sub is None:
            return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND", "message": "no such subscription"})
        if len(parts) == 5 and method == "GET":
            return httpx.Response(200, json=sub)
        if parts[5:] == ["cancel"] and method == "POST":
            if sub["status"] in ("CANCELLED", "EXPIRED"):
                return httpx.Response(
                    422,
                    json={
                        "name": "UNPROCESSABLE_ENTITY",
                        "message": "x",
                        "details": [{"issue": "SUBSCRIPTION_STATUS_INVALID"}],
                    },
                )
            sub["status"] = "CANCELLED"
            return httpx.Response(204)
        if parts[5:] == ["revise"] and method == "POST":
            approve = f"https://www.sandbox.paypal.test/webapps/billing/subscriptions/update?ba_token=BA-R{n}"
            return httpx.Response(
                200,
                json={"plan_id": body.get("plan_id"), "links": [{"href": approve, "rel": "approve", "method": "GET"}]},
            )
    if path == "/v2/checkout/orders" and method == "POST":
        oid = f"ORDER-FAKE{n}"
        return httpx.Response(
            200,
            json={
                "id": oid,
                "status": "PAYER_ACTION_REQUIRED",
                "links": [{"href": f"https://www.sandbox.paypal.test/checkoutnow?token={oid}", "rel": "payer-action"}],
            },
        )
    if path.startswith("/v2/checkout/orders/") and path.endswith("/capture") and method == "POST":
        oid = path.split("/")[4]
        if oid in PAYPAL_STATE["captured"]:
            return httpx.Response(
                422,
                json={"name": "UNPROCESSABLE_ENTITY", "message": "x", "details": [{"issue": "ORDER_ALREADY_CAPTURED"}]},
            )
        PAYPAL_STATE["captured"].add(oid)
        return httpx.Response(201, json={"id": oid, "status": "COMPLETED"})
    if path == "/v1/notifications/verify-webhook-signature" and method == "POST":
        return httpx.Response(200, json={"verification_status": PAYPAL_STATE["verify"]})
    return httpx.Response(404, json={"name": "NOT_FOUND", "message": f"fake: no {method} {path}"})


def paypal_install() -> None:
    from app.billing import paypal_api

    paypal_api._tokens.clear()
    paypal_api.TRANSPORT = httpx.MockTransport(paypal_handle)
