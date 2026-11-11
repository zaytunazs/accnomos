"""PayPal Subscriptions for Accnomos's own plans (not the users' invoice payment links: app/payment_providers.py).

`PAYMENTS_PROVIDER=paypal` (app/billing/payments.py). Sandbox by default (`PAYPAL_BASE`, the same REST app as the
invoice links: `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET`); PayPal's live API is refused unless `PAYMENTS_LIVE=1`.

No SDK: each call is the documented JSON request, so the tests can check it field by field through `TRANSPORT`
(app/billing/fakes.py). Checked on 11 Nov 2026 against PayPal's published OpenAPI files and pages:

  * Auth (https://developer.paypal.com/api/rest/authentication/): `POST /v1/oauth2/token`, Basic client id/secret,
    `grant_type=client_credentials`; the token is cached until a minute before `expires_in`.
  * Catalog Products v1 (https://developer.paypal.com/api/catalog-products/v1/schema.json,
    `POST /v1/catalogs/products`): `name`* and `type`* (PHYSICAL | DIGITAL | SERVICE), `description`, `category`
    (SOFTWARE), `home_url`.
  * Billing plans (https://developer.paypal.com/api/subscriptions/v1/schema.json, `POST /v1/billing/plans`):
    `product_id`*, `name`*, `status` (CREATED | ACTIVE), `billing_cycles`* [{`frequency` {`interval_unit` MONTH |
    YEAR, `interval_count`}, `tenure_type` REGULAR | TRIAL, `sequence` 1-99, `total_cycles` (0 = forever for
    REGULAR), `pricing_scheme.fixed_price` {`currency_code`, `value`}}], `payment_preferences`*
    {`auto_bill_outstanding`, `payment_failure_threshold`}, `taxes` {`percentage`*, `inclusive`}.
  * Subscriptions (same schema, `POST /v1/billing/subscriptions`): `plan_id`*, `start_time` (RFC 3339; "Regular
    recurring payments begin on the selected start date", https://developer.paypal.com/subscriptions/delayed-start),
    `custom_id` (1-127 printable ASCII), `subscriber.email_address`, `application_context` {`brand_name`, `locale`,
    `shipping_preference` NO_SHIPPING, `user_action` SUBSCRIBE_NOW, `return_url`*, `cancel_url`*} (marked DEPRECATED
    in the schema but still the only place for the return/cancel URLs on this endpoint). The answer has `id`,
    `status` (APPROVAL_PENDING ...) and `links[]` with `rel=approve`, where the browser goes.
    `GET /v1/billing/subscriptions/{id}`: `status` (APPROVAL_PENDING | APPROVED | ACTIVE | SUSPENDED | CANCELLED |
    EXPIRED), `plan_id`, `start_time`, `custom_id`, `billing_info.next_billing_time`.
    `POST /v1/billing/subscriptions/{id}/cancel` {`reason`* 1-128}: 204, immediate.
    `POST /v1/billing/subscriptions/{id}/revise` {`plan_id`, `application_context` {`return_url`*, `cancel_url`*}}:
    "switch the plan ... This type of update requires the buyer's consent", so the answer's `links[rel=approve]`.
  * Orders v2 for the one-off top-up (https://developer.paypal.com/api/orders/v2/schema.json): `POST
    /v2/checkout/orders` {`intent` CAPTURE, `purchase_units[]` {`custom_id`, `description`, `amount` {`currency_code`,
    `value`, `breakdown` {`item_total`, `tax_total`}}, `items[]` {`name`, `quantity`, `unit_amount`, `tax`,
    `category` DIGITAL_GOODS}}, `payment_source.paypal.experience_context` {`brand_name`, `shipping_preference`,
    `user_action` PAY_NOW, `return_url`, `cancel_url`}}; the browser goes to `links[rel=payer-action]` (or `approve`).
    `POST /v2/checkout/orders/{id}/capture` (with `PayPal-Request-Id`, so a retry is one capture).
  * Webhooks (https://developer.paypal.com/api/webhooks/v1/schema.json, `POST /v1/notifications/
    verify-webhook-signature`): `auth_algo`, `cert_url`, `transmission_id`, `transmission_sig`, `transmission_time`
    (from the `PAYPAL-AUTH-ALGO`, `PAYPAL-CERT-URL`, `PAYPAL-TRANSMISSION-ID`, `PAYPAL-TRANSMISSION-SIG`,
    `PAYPAL-TRANSMISSION-TIME` headers), `webhook_id` (ours, `PAYPAL_WEBHOOK_ID`), `webhook_event` (the event);
    answers `verification_status` SUCCESS | FAILURE. The event goes back byte for byte as received (spliced into the
    body, not parsed and re-serialised), so nothing PayPal signed is changed on the way back.
    Event names (https://developer.paypal.com/api/rest/webhooks/event-names/): BILLING.SUBSCRIPTION.ACTIVATED |
    UPDATED | CANCELLED | EXPIRED | SUSPENDED | PAYMENT.FAILED, PAYMENT.SALE.COMPLETED, CHECKOUT.ORDER.APPROVED.

Decisions (docs/billing/PLANS_AND_CONTRACT.md):
  * **The trial is ours** (the registry's 90 days, no card), as with Stripe. The PayPal plans have one REGULAR cycle
    and no TRIAL cycle; subscribing during the trial (or a comp) sets `start_time` to its end, so nothing is charged
    before it. A TRIAL cycle on the plan would give a second three months to someone who subscribes after the trial.
  * **VAT:** prices are ex VAT; each plan carries `taxes` {`percentage`: `PAYPAL_VAT_PERCENT` (20), `inclusive`:
    false}, so PayPal adds 20% UK VAT on top (Starter £10 + £2). One flat rate: PayPal has no Stripe Tax equivalent,
    so no reverse charge for non-UK business customers. The top-up order carries the 60p VAT as item tax.
  * **Plan ids** come from env, `PAYPAL_PLAN_<STARTER|COMPREHENSIVE|ULTIMATE>_<MONTH|YEAR>` (made once by
    `tools/paypal_billing_setup.py` in the sandbox), so no Supabase column is added.
  * **Ids are kept in the existing columns:** the PayPal subscription id (`I-…`) in `accounts.stripe_subscription_id`
    (unique, and the code that asks "has a subscription?" works for both). The payer id is not kept: one PayPal
    account may pay for several Accnomos accounts, and `stripe_customer_id` is unique. Renaming the columns is a later
    migration; webhook ids are de-duplicated in the same `stripe_events` table (PayPal's `WH-…` ids cannot clash).

UNVERIFIED (fakes only, nothing has reached PayPal from this module): every answer's exact shape beyond the schema,
that the sandbox accepts a `start_time` 90 days out, that `/revise` to a plan with a different interval is allowed,
and the PAYMENT.SALE.COMPLETED resource's `billing_agreement_id` (the subscription id; PayPal's sample payloads show
it, the schema files do not cover webhook resources). See docs/HONESTY.md.

Every amount is integer pence, GBP only.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx

from app.billing import plans as P

TIMEOUT = httpx.Timeout(20.0, connect=5.0)
TRANSPORT: httpx.AsyncBaseTransport | None = None  # tests: answer instead of api-m.paypal.com
SANDBOX = "https://api-m.sandbox.paypal.com"
LIVE = "https://api-m.paypal.com"
BRAND = "Accnomos"
INTERVAL_UNIT = {"month": "MONTH", "year": "YEAR"}
VERIFY_HEADERS = {
    "auth_algo": "PAYPAL-AUTH-ALGO",
    "cert_url": "PAYPAL-CERT-URL",
    "transmission_id": "PAYPAL-TRANSMISSION-ID",
    "transmission_sig": "PAYPAL-TRANSMISSION-SIG",
    "transmission_time": "PAYPAL-TRANSMISSION-TIME",
}


class PayPalError(RuntimeError):
    def __init__(self, status: int, message: str, issue: str | None = None) -> None:
        super().__init__(f"PayPal: {message}" + (f" (HTTP {status})" if status else ""))
        self.status, self.message, self.issue = status, message, issue


class BadSignature(ValueError):
    pass


@dataclass(frozen=True)
class PayPalSettings:
    client_id: str
    client_secret: str
    base: str
    webhook_id: str
    return_url: str
    vat_percent: str

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def sandbox(self) -> bool:
        return self.base == SANDBOX

    @property
    def autopay_url(self) -> str:
        """Where a PayPal user manages (and cancels) their subscriptions: PayPal's own "Automatic payments" page."""
        return f"https://www.{'sandbox.' if self.sandbox else ''}paypal.com/myaccount/autopay/"


def settings() -> PayPalSettings:
    web = (os.getenv("ACCNOMOS_WEB_URL") or "http://localhost:3000").rstrip("/")
    return PayPalSettings(
        client_id=os.getenv("PAYPAL_CLIENT_ID", "").strip(),
        client_secret=os.getenv("PAYPAL_CLIENT_SECRET", "").strip(),
        base=(os.getenv("PAYPAL_BASE", "").strip().rstrip("/") or SANDBOX),
        webhook_id=os.getenv("PAYPAL_WEBHOOK_ID", "").strip(),
        return_url=(os.getenv("BILLING_RETURN_URL") or f"{web}/settings/billing").strip(),
        vat_percent=os.getenv("PAYPAL_VAT_PERCENT", "").strip() or "20",
    )


def env_plan(plan_code: str, interval: str) -> str | None:
    """PAYPAL_PLAN_<PLAN>_<MONTH|YEAR> (e.g. PAYPAL_PLAN_STARTER_MONTH=P-…)."""
    return os.getenv(f"PAYPAL_PLAN_{plan_code.upper()}_{interval.upper()}", "").strip() or None


def plan_for_id(plan_id: str | None) -> tuple[str, str] | None:
    """(plan_code, interval) for a PayPal plan id from env, or None."""
    if not plan_id:
        return None
    for code in P.PLAN_CODES:
        for interval in ("month", "year"):
            if env_plan(code, interval) == plan_id:
                return code, interval
    return None


def value(pence: int) -> str:
    """PayPal's GBP amount string: 1000 -> "10.00"."""
    if pence < 0:
        raise ValueError("negative amount")
    return f"{pence // 100}.{pence % 100:02d}"


def vat_pence(pence: int, percent: str) -> int:
    """VAT on an ex-VAT amount, rounded half up to the penny."""

    return int((Decimal(pence) * Decimal(percent) / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def rfc3339(ts: int | datetime) -> str:
    when = ts if isinstance(ts, datetime) else datetime.fromtimestamp(ts, UTC)
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def link(body: dict[str, Any], *rels: str) -> str | None:
    for rel in rels:
        for item in body.get("links") or []:
            if isinstance(item, dict) and item.get("rel") == rel and item.get("href"):
                return str(item["href"])
    return None


def _error(resp: httpx.Response) -> PayPalError:
    try:
        body = resp.json()
    except ValueError:
        return PayPalError(resp.status_code, resp.text[:200] or "error")
    if not isinstance(body, dict):
        return PayPalError(resp.status_code, "error")
    details = body.get("details") or []
    issue = details[0].get("issue") if details and isinstance(details[0], dict) else None
    msg = str(body.get("message") or body.get("error_description") or body.get("name") or "error")[:300]
    return PayPalError(resp.status_code, f"{msg}" + (f" ({issue})" if issue else ""), issue)


_tokens: dict[tuple[str, str], tuple[float, str]] = {}


class PayPalBilling:
    def __init__(self, cfg: PayPalSettings) -> None:
        self.cfg = cfg

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=TIMEOUT, transport=TRANSPORT, follow_redirects=False)

    async def token(self) -> str:
        key = (self.cfg.base, self.cfg.client_id)
        hit = _tokens.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        try:
            async with self._client() as c:
                resp = await c.post(
                    f"{self.cfg.base}/v1/oauth2/token",
                    data={"grant_type": "client_credentials"},
                    auth=(self.cfg.client_id, self.cfg.client_secret),
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise PayPalError(0, f"could not be reached ({type(exc).__name__})") from exc
        if resp.status_code >= 400:
            raise _error(resp)
        body = resp.json()
        _tokens[key] = (time.monotonic() + max(int(body.get("expires_in", 0)) - 60, 0), str(body["access_token"]))
        return str(body["access_token"])

    async def _call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
        raw: bytes | None = None,
    ) -> dict[str, Any]:
        if not self.cfg.configured:
            raise PayPalError(0, "PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET are not set")
        headers = {
            "Authorization": f"Bearer {await self.token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Prefer": "return=representation",
        }
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        content = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        try:
            async with self._client() as c:
                resp = await c.request(method, f"{self.cfg.base}{path}", content=content, headers=headers)
        except httpx.HTTPError as exc:
            raise PayPalError(0, f"could not be reached ({type(exc).__name__})") from exc
        if resp.status_code >= 400:
            raise _error(resp)
        return resp.json() if resp.content else {}

    # ---- catalog and plans (tools/paypal_billing_setup.py) ------------------------------------------------------

    async def create_product(self) -> str:
        out = await self._call(
            "POST",
            "/v1/catalogs/products",
            {
                "name": "Accnomos",
                "description": "Accnomos bookkeeping and MTD VAT: monthly or yearly plan",
                "type": "SERVICE",
                "category": "SOFTWARE",
                "home_url": "https://accnomos.com",
            },
            request_id="accnomos-product-v1",
        )
        return str(out["id"])

    def plan_body(self, *, product: str, plan_code: str, name: str, interval: str, pence: int) -> dict[str, Any]:
        """One REGULAR cycle forever, no TRIAL cycle (the trial is ours: see the module docstring), ex VAT with
        PAYPAL_VAT_PERCENT added on top."""
        return {
            "product_id": product,
            "name": f"Accnomos {name} ({'monthly' if interval == 'month' else 'yearly'})",
            "description": f"Accnomos {name} plan, billed {'monthly' if interval == 'month' else 'yearly'}, ex VAT",
            "status": "ACTIVE",
            "billing_cycles": [
                {
                    "frequency": {"interval_unit": INTERVAL_UNIT[interval], "interval_count": 1},
                    "tenure_type": "REGULAR",
                    "sequence": 1,
                    "total_cycles": 0,
                    "pricing_scheme": {"fixed_price": {"currency_code": "GBP", "value": value(pence)}},
                }
            ],
            "payment_preferences": {
                "auto_bill_outstanding": True,
                "setup_fee_failure_action": "CONTINUE",
                "payment_failure_threshold": 3,
            },
            "taxes": {"percentage": self.cfg.vat_percent, "inclusive": False},
        }

    async def create_plan(self, *, product: str, plan_code: str, name: str, interval: str, pence: int) -> str:
        body = self.plan_body(product=product, plan_code=plan_code, name=name, interval=interval, pence=pence)
        out = await self._call(
            "POST", "/v1/billing/plans", body, request_id=f"accnomos-plan-{plan_code}-{interval}-{pence}"
        )
        return str(out["id"])

    # ---- subscriptions -------------------------------------------------------------------------------------------

    def _context(self, ok: str, cancel: str, action: str = "SUBSCRIBE_NOW") -> dict[str, Any]:
        return {
            "brand_name": BRAND,
            "locale": "en-GB",
            "shipping_preference": "NO_SHIPPING",
            "user_action": action,
            "return_url": f"{self.cfg.return_url}?{ok}",
            "cancel_url": f"{self.cfg.return_url}?{cancel}",
        }

    async def create_subscription(
        self, *, plan_id: str, account_id: str, email: str | None, start: int | None
    ) -> dict[str, Any]:
        """A subscription waiting for the buyer's approval. `start` (unix time) defers the first payment to the end
        of our trial or comp. Returns PayPal's answer; the browser goes to `link(out, "approve")`."""
        body: dict[str, Any] = {
            "plan_id": plan_id,
            "custom_id": account_id,
            "application_context": self._context("checkout=success", "checkout=cancelled"),
        }
        if start is not None:
            body["start_time"] = rfc3339(start)
        if email:
            body["subscriber"] = {"email_address": email}
        return await self._call("POST", "/v1/billing/subscriptions", body)

    async def subscription(self, sub_id: str) -> dict[str, Any]:
        return await self._call("GET", f"/v1/billing/subscriptions/{sub_id}")

    async def cancel(self, sub_id: str, reason: str = "Cancelled by the customer in Accnomos") -> None:
        await self._call("POST", f"/v1/billing/subscriptions/{sub_id}/cancel", {"reason": reason[:128]})

    async def revise(self, sub_id: str, plan_id: str) -> dict[str, Any]:
        """Switch the subscription to another plan; PayPal asks the buyer to approve (`link(out, "approve")`)."""
        return await self._call(
            "POST",
            f"/v1/billing/subscriptions/{sub_id}/revise",
            {"plan_id": plan_id, "application_context": self._context("change=success", "change=cancelled")},
        )

    # ---- the one-off top-up (Orders v2) --------------------------------------------------------------------------

    async def create_topup_order(self, *, account_id: str, pence: int, docs: int) -> dict[str, Any]:
        tax = vat_pence(pence, self.cfg.vat_percent)
        gbp = lambda p: {"currency_code": "GBP", "value": value(p)}  # noqa: E731
        body = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "custom_id": f"topup:{account_id}",
                    "description": f"Accnomos: {docs} extra AI-read documents",
                    "amount": {**gbp(pence + tax), "breakdown": {"item_total": gbp(pence), "tax_total": gbp(tax)}},
                    "items": [
                        {
                            "name": f"{docs} extra AI-read documents",
                            "quantity": "1",
                            "unit_amount": gbp(pence),
                            "tax": gbp(tax),
                            "category": "DIGITAL_GOODS",
                        }
                    ],
                }
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "brand_name": BRAND,
                        "shipping_preference": "NO_SHIPPING",
                        "user_action": "PAY_NOW",
                        "return_url": f"{self.cfg.return_url}?topup=success",
                        "cancel_url": f"{self.cfg.return_url}?topup=cancelled",
                    }
                }
            },
        }
        return await self._call("POST", "/v2/checkout/orders", body)

    async def capture_order(self, order_id: str) -> dict[str, Any]:
        return await self._call(
            "POST", f"/v2/checkout/orders/{order_id}/capture", {}, request_id=f"accnomos-capture-{order_id}"
        )

    # ---- webhooks ------------------------------------------------------------------------------------------------

    async def verify_webhook(self, headers: Any, payload: bytes) -> None:
        """Raise BadSignature unless PayPal says this delivery is genuine for our webhook (PAYPAL_WEBHOOK_ID)."""
        if not self.cfg.webhook_id:
            raise BadSignature("PAYPAL_WEBHOOK_ID is not set")
        fields: dict[str, str] = {}
        for key, header in VERIFY_HEADERS.items():
            got = (headers.get(header) or headers.get(header.lower()) or "").strip()
            if not got:
                raise BadSignature(f"{header} header is missing")
            fields[key] = got
        try:
            json.loads(payload)
        except ValueError as exc:
            raise BadSignature("the body is not JSON") from exc
        head = json.dumps({**fields, "webhook_id": self.cfg.webhook_id})
        raw = head[:-1].encode() + b', "webhook_event": ' + payload + b"}"  # the event exactly as received
        try:
            out = await self._call("POST", "/v1/notifications/verify-webhook-signature", raw=raw)
        except PayPalError as exc:
            raise BadSignature(f"PayPal could not verify it: {exc.message}") from exc
        if out.get("verification_status") != "SUCCESS":
            raise BadSignature("PayPal says the signature does not match")


def live_refused(cfg: PayPalSettings) -> bool:
    return not cfg.sandbox and os.getenv("PAYMENTS_LIVE", "").strip() != "1"


def client() -> PayPalBilling | None:
    """The PayPal client when PayPal is the plan provider (app/billing/payments.py) and has credentials; None
    otherwise, or when it points at PayPal's live API without PAYMENTS_LIVE=1."""
    from app.billing import payments

    cfg = settings()
    if payments.provider() != "paypal" or not cfg.configured or live_refused(cfg):
        return None
    return PayPalBilling(cfg)
