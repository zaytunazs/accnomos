"""A stand-in for the Stripe Billing endpoints app/billing/stripe_api.py calls, for the unit tests and test mode
(`ACCNOMOS_TEST_MODE=1`), so no request ever reaches api.stripe.com from either. Every request is kept in `CALLS`
as (method, path, form fields) for the tests to check."""

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
        }
    elif path == "/v1/invoices" and method == "GET":
        out = {"data": [], "has_more": False}
    else:
        return httpx.Response(404, json={"error": {"message": f"fake: no {method} {path}"}})
    return httpx.Response(200, json=out)


def install() -> None:
    from app.billing import stripe_api

    stripe_api.TRANSPORT = httpx.MockTransport(handle)
