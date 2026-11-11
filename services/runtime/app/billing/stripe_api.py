"""Stripe Billing for Accnomos's own subscriptions (not the users' invoice payment links: app/payment_providers.py).

No SDK: each call is the documented form-encoded request, so the tests can check it field by field through
`TRANSPORT`. Checked against docs.stripe.com, 11 Nov 2026:

  * Checkout Sessions (https://docs.stripe.com/api/checkout/sessions/create): `mode=subscription` with
    `line_items[0][price]`, `subscription_data[trial_end]`, `subscription_data[trial_settings][end_behavior]
    [missing_payment_method]=pause`, `payment_method_collection=if_required` (no card for a trial,
    https://docs.stripe.com/payments/checkout/free-trials), `discounts[0][coupon]`, `automatic_tax[enabled]=true`
    with `customer_update[address]=auto` (Stripe Tax needs the customer's address), `tax_id_collection[enabled]`;
    `mode=payment` for the one-off top-up with `price_data` and `tax_behavior=exclusive`.
  * Customer Portal (https://docs.stripe.com/api/customer_portal/sessions/create): `customer`, `return_url`.
  * Coupons (https://docs.stripe.com/api/coupons/create): `percent_off` or `amount_off`+`currency`, `duration`
    once|repeating (`duration_in_months`).
  * Products and prices (https://docs.stripe.com/api/prices/create): `recurring[interval]`, `tax_behavior=exclusive`
    (prices are ex VAT; Stripe Tax adds UK VAT at checkout).
  * Webhook signatures (https://docs.stripe.com/webhooks#verify-manually): `Stripe-Signature: t=<unix>,v1=<hex>`,
    HMAC-SHA256 of `"{t}.{raw body}"` with the endpoint secret; reject outside a 5 minute tolerance.

Every amount is integer pence, GBP only.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

TIMEOUT = httpx.Timeout(20.0, connect=5.0)
TRANSPORT: httpx.AsyncBaseTransport | None = None  # tests: answer instead of api.stripe.com
API = "https://api.stripe.com"
TOLERANCE_S = 300


class StripeError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Stripe: {message}" + (f" (HTTP {status})" if status else ""))
        self.status, self.message = status, message


class BadSignature(ValueError):
    pass


@dataclass(frozen=True)
class StripeSettings:
    secret_key: str
    webhook_secret: str
    return_url: str

    @property
    def configured(self) -> bool:
        return bool(self.secret_key)


def settings() -> StripeSettings:
    web = (os.getenv("ACCNOMOS_WEB_URL") or "http://localhost:3000").rstrip("/")
    return StripeSettings(
        secret_key=os.getenv("STRIPE_SECRET_KEY", "").strip(),
        webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET", "").strip(),
        return_url=(os.getenv("BILLING_RETURN_URL") or f"{web}/settings/billing").strip(),
    )


def env_price(plan_code: str, interval: str) -> str | None:
    """STRIPE_PRICE_<PLAN>_<MONTH|YEAR> (e.g. STRIPE_PRICE_STARTER_MONTH=price_…) overrides the plans table."""
    return os.getenv(f"STRIPE_PRICE_{plan_code.upper()}_{interval.upper()}", "").strip() or None


def verify_signature(payload: bytes, header: str, secret: str, now: float | None = None) -> None:
    """Raise BadSignature unless one `v1` signature in `header` matches and the timestamp is fresh."""
    if not secret:
        raise BadSignature("STRIPE_WEBHOOK_SECRET is not set")
    ts: str | None = None
    sigs: list[str] = []
    for part in (header or "").split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            ts = value
        elif key == "v1":
            sigs.append(value)
    if not ts or not ts.isdigit() or not sigs:
        raise BadSignature("Stripe-Signature header is malformed")
    if abs((now if now is not None else time.time()) - int(ts)) > TOLERANCE_S:
        raise BadSignature("Stripe-Signature timestamp is outside the tolerance")
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in sigs):
        raise BadSignature("no matching signature")


def sign(payload: bytes, secret: str, ts: int | None = None) -> str:
    """A valid Stripe-Signature header (tests and the local webhook replay)."""
    ts = int(time.time()) if ts is None else ts
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _error_text(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or err.get("code") or "error")[:300]
    return "error"


class StripeBilling:
    def __init__(self, cfg: StripeSettings) -> None:
        self.cfg = cfg

    async def _call(
        self,
        method: str,
        path: str,
        data: list[tuple[str, str]] | None = None,
        params: list[tuple[str, str]] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not self.cfg.secret_key:
            raise StripeError(0, "STRIPE_SECRET_KEY is not set")
        headers: dict[str, str] = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, transport=TRANSPORT, follow_redirects=False) as c:
                resp = await c.request(
                    method,
                    f"{API}{path}",
                    content=urlencode(data).encode() if data is not None else None,
                    params=tuple(params) if params is not None else None,
                    headers=headers,
                    auth=(self.cfg.secret_key, ""),
                )
        except httpx.HTTPError as exc:
            raise StripeError(0, f"could not be reached ({type(exc).__name__})") from exc
        if resp.status_code >= 400:
            raise StripeError(resp.status_code, _error_text(resp))
        return resp.json()

    async def create_customer(self, account_id: str, email: str, name: str | None) -> str:
        data = [("email", email), ("metadata[account_id]", account_id)]
        if name:
            data.append(("name", name))
        out = await self._call("POST", "/v1/customers", data, idempotency_key=f"customer-{account_id}")
        return str(out["id"])

    async def checkout_subscription(
        self,
        *,
        customer: str,
        account_id: str,
        price: str,
        plan_code: str,
        interval: str,
        trial_end: int | None,
        coupon: str | None,
        promo_code: str | None,
    ) -> dict[str, Any]:
        meta = [("account_id", account_id), ("plan_code", plan_code), ("interval", interval)]
        if promo_code:
            meta.append(("promo_code", promo_code))
        data = [
            ("mode", "subscription"),
            ("customer", customer),
            ("client_reference_id", account_id),
            ("line_items[0][price]", price),
            ("line_items[0][quantity]", "1"),
            ("success_url", f"{self.cfg.return_url}?checkout=success"),
            ("cancel_url", f"{self.cfg.return_url}?checkout=cancelled"),
            ("automatic_tax[enabled]", "true"),
            ("customer_update[address]", "auto"),
            ("customer_update[name]", "auto"),
            ("tax_id_collection[enabled]", "true"),
            ("billing_address_collection", "required"),
            *((f"metadata[{k}]", v) for k, v in meta),
            *((f"subscription_data[metadata][{k}]", v) for k, v in meta),
        ]
        if trial_end is not None:
            data += [
                ("subscription_data[trial_end]", str(trial_end)),
                ("subscription_data[trial_settings][end_behavior][missing_payment_method]", "pause"),
                ("payment_method_collection", "if_required"),
            ]
        if coupon:
            data.append(("discounts[0][coupon]", coupon))
        return await self._call("POST", "/v1/checkout/sessions", data)

    async def checkout_topup(self, *, customer: str, account_id: str, price: str | None, pence: int, docs: int):
        line = (
            [("line_items[0][price]", price)]
            if price
            else [
                ("line_items[0][price_data][currency]", "gbp"),
                ("line_items[0][price_data][unit_amount]", str(pence)),
                ("line_items[0][price_data][tax_behavior]", "exclusive"),
                ("line_items[0][price_data][product_data][name]", f"{docs} extra AI-read documents"),
            ]
        )
        data = [
            ("mode", "payment"),
            ("customer", customer),
            ("client_reference_id", account_id),
            *line,
            ("line_items[0][quantity]", "1"),
            ("success_url", f"{self.cfg.return_url}?topup=success"),
            ("cancel_url", f"{self.cfg.return_url}?topup=cancelled"),
            ("automatic_tax[enabled]", "true"),
            ("customer_update[address]", "auto"),
            ("customer_update[name]", "auto"),
            ("tax_id_collection[enabled]", "true"),
            ("billing_address_collection", "required"),
            ("invoice_creation[enabled]", "true"),  # a VAT invoice for the top-up
            ("metadata[account_id]", account_id),
            ("metadata[kind]", "topup"),
            ("metadata[docs]", str(docs)),
        ]
        return await self._call("POST", "/v1/checkout/sessions", data)

    async def portal(self, customer: str) -> dict[str, Any]:
        return await self._call(
            "POST", "/v1/billing_portal/sessions", [("customer", customer), ("return_url", self.cfg.return_url)]
        )

    async def create_coupon(self, *, code: str, kind: str, value: int, duration_months: int | None) -> str:
        data = [("name", code), ("metadata[promo_code]", code)]
        if kind == "percent":
            data.append(("percent_off", str(value)))
        else:
            data += [("amount_off", str(value)), ("currency", "gbp")]
        if duration_months:
            data += [("duration", "repeating"), ("duration_in_months", str(duration_months))]
        else:
            data.append(("duration", "once"))
        out = await self._call("POST", "/v1/coupons", data, idempotency_key=f"coupon-{code}-{kind}-{value}")
        return str(out["id"])

    async def create_product(self, plan_code: str, name: str) -> str:
        out = await self._call(
            "POST",
            "/v1/products",
            [("name", f"Accnomos {name}"), ("metadata[plan_code]", plan_code)],
        )
        return str(out["id"])

    async def create_price(self, *, product: str, plan_code: str, interval: str, pence: int) -> str:
        out = await self._call(
            "POST",
            "/v1/prices",
            [
                ("product", product),
                ("currency", "gbp"),
                ("unit_amount", str(pence)),
                ("recurring[interval]", interval),
                ("tax_behavior", "exclusive"),
                ("metadata[plan_code]", plan_code),
                ("metadata[interval]", interval),
            ],
        )
        return str(out["id"])

    async def retrieve_price(self, price: str) -> dict[str, Any]:
        return await self._call("GET", f"/v1/prices/{price}")

    async def subscription(self, sub_id: str) -> dict[str, Any]:
        return await self._call("GET", f"/v1/subscriptions/{sub_id}")

    async def set_cancel_at_period_end(self, sub_id: str, cancel: bool) -> dict[str, Any]:
        return await self._call(
            "POST", f"/v1/subscriptions/{sub_id}", [("cancel_at_period_end", "true" if cancel else "false")]
        )

    async def apply_coupon(self, sub_id: str, coupon: str) -> dict[str, Any]:
        return await self._call("POST", f"/v1/subscriptions/{sub_id}", [("discounts[0][coupon]", coupon)])

    async def invoices(self, customer: str, limit: int = 5) -> list[dict[str, Any]]:
        out = await self._call("GET", "/v1/invoices", params=[("customer", customer), ("limit", str(limit))])
        return [i for i in out.get("data", []) if isinstance(i, dict)]


def client() -> StripeBilling | None:
    cfg = settings()
    return StripeBilling(cfg) if cfg.configured else None
