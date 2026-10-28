"""Stripe and PayPal over HTTP, for payment links on invoices (app/online_payments.py). No SDKs: each call is the
documented request, so the fakes in app/online_fakes.py can check it field by field.

Stripe (Connect, Standard accounts linked with OAuth; checked 28 Oct 2026):
  * https://docs.stripe.com/connect/oauth-reference: `connect.stripe.com/oauth/authorize?response_type=code&client_id=
    &scope=read_write&state=&redirect_uri=`, then `POST /oauth/token` (platform secret as Basic user,
    `grant_type=authorization_code&code=`) answers `stripe_user_id` and `livemode`; its `access_token` and
    `refresh_token` are deprecated, so they are never kept. `POST /oauth/deauthorize` (`client_id`, `stripe_user_id`).
  * https://docs.stripe.com/connect/authentication: every call for the account sends `Stripe-Account: acct_…` with
    the platform's secret key.
  * https://docs.stripe.com/api/prices/create (`unit_amount` in the smallest currency unit, `product_data[name]`),
    https://docs.stripe.com/api/payment-link/create (`line_items`, `metadata`, `payment_intent_data[metadata]`,
    `restrictions[completed_sessions][limit]`), `POST /v1/payment_links/{id}` with `active=false`,
    https://docs.stripe.com/api/checkout/sessions/list (`payment_link=`, `status=complete`), and
    https://docs.stripe.com/expand (`expand[]=data.payment_intent.latest_charge.balance_transaction`: four levels,
    the maximum) for the fee (https://docs.stripe.com/api/balance_transactions/object: `fee` in pence).

PayPal (partner onboarding and Invoicing v2; checked 28 Oct 2026):
  * https://developer.paypal.com/api/rest/authentication/: `POST /v1/oauth2/token` with the app's client id and
    secret as Basic auth, `grant_type=client_credentials`.
  * https://developer.paypal.com/docs/multiparty/seller-onboarding/before-payment/: `POST /v2/customer/
    partner-referrals` (THIRD_PARTY `features`), the seller returns with `merchantIdInPayPal`; `GET /v1/customer/
    partners/{partner}/merchant-integrations/{merchant}` says whether onboarding finished. Approved partners only.
  * https://developer.paypal.com/api/rest/requests/: `PayPal-Auth-Assertion` is an unsigned JWT
    (`{"alg":"none"}`, `{"iss": client_id, "payer_id": merchant_id}`, empty signature), each part Base64.
  * Invoicing v2 (schema 2.12, https://developer.paypal.com/api/invoicing/v2/schema.json): create, `/send` with
    `send_to_recipient: false` (we give the customer the link ourselves), read back `detail.metadata.
    recipient_view_url`, `payments.transactions[]` (`payment_id`, `amount`, `payment_date`), `/cancel`.
  * Orders v2 (schema 2.36): `GET /v2/payments/captures/{id}` gives `seller_receivable_breakdown.paypal_fee`.
    UNVERIFIED: that an invoice payment's `payment_id` is a capture id this call accepts. When it fails the fee is
    left for the user to type in.

Every amount crosses this module as integer pence; the conversions are `stripe_minor`, `paypal_value` and
`pence_from_paypal`, and only GBP is accepted.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

import httpx

TIMEOUT = httpx.Timeout(20.0, connect=5.0)
# Set by app/online_fakes.py in test mode and by the unit tests: every provider call goes to the fakes instead.
TRANSPORT: httpx.AsyncBaseTransport | None = None


class ProviderError(RuntimeError):
    """The provider refused or could not be reached. `status` is the HTTP status (0: no answer)."""

    def __init__(self, provider: str, status: int, message: str) -> None:
        super().__init__(f"{provider}: {message}" + (f" (HTTP {status})" if status else ""))
        self.provider, self.status, self.message = provider, status, message


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, transport=TRANSPORT, follow_redirects=False)


# --------------------------------------------------------------------------- #
# Money
# --------------------------------------------------------------------------- #


def stripe_minor(pence: int) -> int:
    """Stripe's `unit_amount` for GBP is the smallest unit, so pence as they are (docs/api/prices/create)."""
    if pence <= 0:
        raise ValueError("A payment link needs an amount above £0.00")
    return pence


def paypal_value(pence: int) -> str:
    """PayPal's `money.value` is a string with the currency's decimals: 12345 -> "123.45"."""
    if pence <= 0:
        raise ValueError("A payment link needs an amount above £0.00")
    pounds, pennies = divmod(pence, 100)
    return f"{pounds}.{pennies:02d}"


def pence_from_paypal(money: dict[str, Any] | None) -> int | None:
    """A PayPal `money` object in GBP as pence; None for anything else (another currency, a third decimal)."""
    if not isinstance(money, dict) or money.get("currency_code") != "GBP":
        return None
    try:
        value = Decimal(str(money.get("value")))
    except InvalidOperation:
        return None
    p = value * 100
    return int(p) if p == p.to_integral_value() else None


def _error_text(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):  # Stripe API: {"error": {"message": ...}}
            return str(err.get("message") or err.get("code") or "error")[:300]
        if isinstance(err, str):  # Stripe OAuth: {"error": ..., "error_description": ...}
            return str(body.get("error_description") or err)[:300]
        return str(body.get("message") or body.get("name") or "error")[:300]  # PayPal: {"name", "message", ...}
    return "error"


# --------------------------------------------------------------------------- #
# Stripe
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StripeConfig:
    secret_key: str
    client_id: str
    redirect_uri: str
    authorize_url: str = "https://connect.stripe.com/oauth/authorize"
    connect_base: str = "https://connect.stripe.com"
    api_base: str = "https://api.stripe.com"

    @property
    def test_mode(self) -> bool:
        return self.secret_key.startswith(("sk_test_", "rk_test_"))


class StripeApi:
    def __init__(self, cfg: StripeConfig, http: httpx.AsyncClient) -> None:
        self.cfg, self.http = cfg, http

    async def _call(
        self,
        method: str,
        url: str,
        *,
        data: list[tuple[str, str]] | None = None,
        params: list[tuple[str, str]] | None = None,
        account: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Stripe-Account": account} if account else {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            if data is not None:  # form-encoded, keys in the order given (Stripe's bracket notation)
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            resp = await self.http.request(
                method,
                url,
                content=urlencode(data).encode() if data is not None else None,
                params=tuple(params) if params is not None else None,
                headers=headers,
                auth=(self.cfg.secret_key, ""),
            )
        except httpx.HTTPError as exc:
            raise ProviderError("Stripe", 0, f"could not be reached ({type(exc).__name__})") from exc
        if resp.status_code >= 400:
            raise ProviderError("Stripe", resp.status_code, _error_text(resp))
        return resp.json()

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """POST /oauth/token. Returns `stripe_user_id`, `livemode`, `scope` (the deprecated tokens are dropped)."""
        out = await self._call(
            "POST",
            f"{self.cfg.connect_base}/oauth/token",
            data=[("grant_type", "authorization_code"), ("code", code)],
        )
        return {k: out.get(k) for k in ("stripe_user_id", "livemode", "scope")}

    async def deauthorize(self, account: str) -> None:
        await self._call(
            "POST",
            f"{self.cfg.connect_base}/oauth/deauthorize",
            data=[("client_id", self.cfg.client_id), ("stripe_user_id", account)],
        )

    async def create_link(
        self, account: str, *, amount_pence: int, invoice_number: str, ref: str, idempotency_key: str
    ) -> dict[str, Any]:
        """A Price for the amount, then a Payment Link that can be paid once. Returns the Payment Link."""
        price = await self._call(
            "POST",
            f"{self.cfg.api_base}/v1/prices",
            account=account,
            idempotency_key=f"{idempotency_key}-price",
            data=[
                ("currency", "gbp"),
                ("unit_amount", str(stripe_minor(amount_pence))),
                ("product_data[name]", f"Invoice {invoice_number}"),
                ("metadata[accnomos_ref]", ref),
            ],
        )
        return await self._call(
            "POST",
            f"{self.cfg.api_base}/v1/payment_links",
            account=account,
            idempotency_key=f"{idempotency_key}-link",
            data=[
                ("line_items[0][price]", str(price["id"])),
                ("line_items[0][quantity]", "1"),
                ("metadata[accnomos_ref]", ref),
                ("metadata[invoice]", invoice_number),
                ("payment_intent_data[metadata][accnomos_ref]", ref),
                ("payment_intent_data[metadata][invoice]", invoice_number),
                ("restrictions[completed_sessions][limit]", "1"),
                ("after_completion[type]", "hosted_confirmation"),
                (
                    "after_completion[hosted_confirmation][custom_message]",
                    f"Thank you. Your payment for invoice {invoice_number} has been received.",
                ),
                ("inactive_message", f"Invoice {invoice_number} no longer takes payment through this link."),
            ],
        )

    async def deactivate_link(self, account: str, link_id: str) -> None:
        await self._call(
            "POST", f"{self.cfg.api_base}/v1/payment_links/{link_id}", account=account, data=[("active", "false")]
        )

    async def completed_sessions(self, account: str, link_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        params = [
            ("payment_link", link_id),
            ("status", "complete"),
            ("limit", "100"),
            ("expand[]", "data.payment_intent.latest_charge.balance_transaction"),
        ]
        for _ in range(5):  # a link is paid once (restrictions); five pages is far more than it can ever have
            page = await self._call("GET", f"{self.cfg.api_base}/v1/checkout/sessions", params=params, account=account)
            data = [s for s in page.get("data", []) if isinstance(s, dict)]
            out += data
            if not page.get("has_more") or not data:
                break
            params = [p for p in params if p[0] != "starting_after"] + [("starting_after", str(data[-1]["id"]))]
        return out


# --------------------------------------------------------------------------- #
# PayPal
# --------------------------------------------------------------------------- #

PAYPAL_SANDBOX = "https://api-m.sandbox.paypal.com"


@dataclass(frozen=True)
class PayPalConfig:
    client_id: str
    client_secret: str
    partner_merchant_id: str
    attribution_id: str  # the partner's BN code (PayPal-Partner-Attribution-Id)
    return_url: str
    base: str = PAYPAL_SANDBOX

    @property
    def test_mode(self) -> bool:
        return self.base.rstrip("/") == PAYPAL_SANDBOX


_paypal_tokens: dict[tuple[str, str], tuple[float, str]] = {}  # (base, client id) -> (expiry, app token)


def auth_assertion(client_id: str, merchant_id: str) -> str:
    """PayPal-Auth-Assertion: unsigned JWT naming the merchant we act for (docs/api/rest/requests)."""

    def part(obj: dict[str, str]) -> str:
        return base64.b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode()

    return f"{part({'alg': 'none'})}.{part({'iss': client_id, 'payer_id': merchant_id})}."


class PayPalApi:
    def __init__(self, cfg: PayPalConfig, http: httpx.AsyncClient) -> None:
        self.cfg, self.http = cfg, http

    async def token(self) -> str:
        key = (self.cfg.base, self.cfg.client_id)
        hit = _paypal_tokens.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        try:
            resp = await self.http.post(
                f"{self.cfg.base}/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(self.cfg.client_id, self.cfg.client_secret),
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise ProviderError("PayPal", 0, f"could not be reached ({type(exc).__name__})") from exc
        if resp.status_code >= 400:
            raise ProviderError("PayPal", resp.status_code, _error_text(resp))
        body = resp.json()
        ttl = max(int(body.get("expires_in", 0)) - 60, 0)
        _paypal_tokens[key] = (time.monotonic() + ttl, str(body["access_token"]))
        return str(body["access_token"])

    async def _call(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        merchant: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {await self.token()}",
            "Content-Type": "application/json",
            "PayPal-Partner-Attribution-Id": self.cfg.attribution_id,
        }
        if merchant:
            headers["PayPal-Auth-Assertion"] = auth_assertion(self.cfg.client_id, merchant)
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        try:
            resp = await self.http.request(method, f"{self.cfg.base}{path}", json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderError("PayPal", 0, f"could not be reached ({type(exc).__name__})") from exc
        if resp.status_code >= 400:
            raise ProviderError("PayPal", resp.status_code, _error_text(resp))
        return resp.json() if resp.content else {}

    async def partner_referral(self, tracking_id: str, return_url: str) -> str:
        """The single-use sign-up link for the seller (`links[rel=action_url]`)."""
        out = await self._call(
            "POST",
            "/v2/customer/partner-referrals",
            body={
                "tracking_id": tracking_id,
                "operations": [
                    {
                        "operation": "API_INTEGRATION",
                        "api_integration_preference": {
                            "rest_api_integration": {
                                "integration_method": "PAYPAL",
                                "integration_type": "THIRD_PARTY",
                                "third_party_details": {"features": ["PAYMENT", "REFUND", "INVOICE_READ_WRITE"]},
                            }
                        },
                    }
                ],
                "products": ["EXPRESS_CHECKOUT"],
                "legal_consents": [{"type": "SHARE_DATA_CONSENT", "granted": True}],
                "partner_config_override": {"return_url": return_url},
            },
        )
        for link in out.get("links", []):
            if isinstance(link, dict) and link.get("rel") == "action_url" and link.get("href"):
                return str(link["href"])
        raise ProviderError("PayPal", 0, "the sign-up link was missing from PayPal's answer")

    async def merchant_status(self, merchant_id: str) -> dict[str, Any]:
        return await self._call(
            "GET", f"/v1/customer/partners/{self.cfg.partner_merchant_id}/merchant-integrations/{merchant_id}"
        )

    async def create_invoice(
        self,
        merchant: str,
        *,
        number: str,
        amount_pence: int,
        ref: str,
        customer_name: str,
        customer_email: str | None,
        request_id: str,
    ) -> dict[str, Any]:
        """Create a PayPal invoice for the amount on the merchant's account, send it without emailing anyone, and
        return it read back (its `detail.metadata.recipient_view_url` is the link the customer pays through)."""
        billing: dict[str, Any] = {"name": {"full_name": customer_name[:300]}}
        if customer_email:
            billing["email_address"] = customer_email
        created = await self._call(
            "POST",
            "/v2/invoicing/invoices",
            merchant=merchant,
            request_id=request_id,
            body={
                "detail": {
                    # PayPal wants invoice numbers unique per merchant; a new link for the same invoice gets a suffix.
                    "invoice_number": f"{number}-{ref[:6]}",
                    "reference": ref,
                    "currency_code": "GBP",
                    "note": f"Invoice {number}",
                    "payment_term": {"term_type": "DUE_ON_RECEIPT"},
                },
                "primary_recipients": [{"billing_info": billing}],
                "items": [
                    {
                        "name": f"Invoice {number}",
                        "quantity": "1",
                        "unit_amount": {"currency_code": "GBP", "value": paypal_value(amount_pence)},
                        "unit_of_measure": "AMOUNT",
                    }
                ],
                "configuration": {"allow_tip": False, "partial_payment": {"allow_partial_payment": False}},
            },
        )
        invoice_id = str(created.get("id") or "")
        if not invoice_id:
            raise ProviderError("PayPal", 0, "the invoice id was missing from PayPal's answer")
        await self._call(
            "POST",
            f"/v2/invoicing/invoices/{invoice_id}/send",
            merchant=merchant,
            request_id=f"{request_id}-send",
            body={"send_to_recipient": False, "send_to_invoicer": False},
        )
        return await self.invoice(merchant, invoice_id)

    async def invoice(self, merchant: str, invoice_id: str) -> dict[str, Any]:
        return await self._call("GET", f"/v2/invoicing/invoices/{invoice_id}", merchant=merchant)

    async def cancel_invoice(self, merchant: str, invoice_id: str) -> None:
        await self._call(
            "POST",
            f"/v2/invoicing/invoices/{invoice_id}/cancel",
            merchant=merchant,
            body={"send_to_recipient": False, "send_to_invoicer": False},
        )

    async def capture(self, merchant: str, capture_id: str) -> dict[str, Any]:
        return await self._call("GET", f"/v2/payments/captures/{capture_id}", merchant=merchant)


def recipient_view_url(invoice: dict[str, Any]) -> str | None:
    meta = (invoice.get("detail") or {}).get("metadata") or {}
    url = meta.get("recipient_view_url")
    # http only for the test-mode fakes on this machine (app/online_fakes.py)
    return str(url) if isinstance(url, str) and url.startswith(("https://", "http://127.0.0.1")) else None
