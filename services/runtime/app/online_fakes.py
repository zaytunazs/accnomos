"""Stand-ins for Stripe and PayPal, for the unit tests and test mode (`ACCNOMOS_TEST_MODE=1`). Nothing is ever sent
to either provider from here.

`install()` points app/payment_providers.TRANSPORT at `handle`, an httpx MockTransport handler that answers the
calls app/payment_providers.py makes, with the shapes the providers document (see that module's docstring for the
pages, read 28 Oct 2026): form-encoded Stripe requests with Basic auth and `Stripe-Account`, JSON PayPal requests
with a Bearer token and `PayPal-Auth-Assertion`. A request the fake does not know is a 404, so a wrong path fails a
test instead of passing quietly. Every request is kept in `FAKES.requests` for the tests to inspect.

In test mode `router` adds the pages a browser would see at the providers: a consent screen that sends the browser
straight back (Stripe OAuth, PayPal sign-up) and a "pay" page per link, so the end-to-end tests can play the
customer. Fees are made up (1.5% + 20p for Stripe, the UK standard card price on stripe.com/gb/pricing on 28 Oct
2026; 2.9% + 30p for PayPal), rounded half up.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from urllib.parse import parse_qsl, urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import payment_providers

STRIPE_KEY = "sk_test_accnomos_fake"
PAYPAL_CLIENT = ("accnomos-fake-client", "accnomos-fake-secret")
PAYPAL_PARTNER = "FAKEPARTNER1"
PAYPAL_MERCHANT = "FAKEMERCHANT1"  # the seller every fake PayPal sign-up comes back as


def _fee(pence: int, pct: str, fixed: int) -> int:
    return int((Decimal(pence) * Decimal(pct) / 100 + fixed).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def stripe_fee(pence: int) -> int:
    return _fee(pence, "1.5", 20)


def paypal_fee(pence: int) -> int:
    return _fee(pence, "2.9", 30)


@dataclass
class Fakes:
    requests: list[httpx.Request] = field(default_factory=list)
    codes: dict[str, str] = field(default_factory=dict)  # Stripe OAuth code -> connected account
    accounts: set[str] = field(default_factory=set)  # connected Stripe accounts
    live_codes: set[str] = field(default_factory=set)  # codes that answer livemode: true
    prices: dict[str, dict[str, Any]] = field(default_factory=dict)
    links: dict[str, dict[str, Any]] = field(default_factory=dict)  # plink_ -> link, with "_account"
    sessions: list[dict[str, Any]] = field(default_factory=list)  # completed Checkout Sessions, with "_account"
    fee_pending: bool = False  # Stripe sessions paid while True have no balance transaction yet
    referrals: dict[str, dict[str, Any]] = field(default_factory=dict)  # PayPal sign-up id -> {tracking_id, return}
    merchants: dict[str, dict[str, Any]] = field(default_factory=dict)  # PayPal merchant id -> merchant-integrations
    invoices: dict[str, dict[str, Any]] = field(default_factory=dict)  # INV2-… -> PayPal invoice, with "_merchant"
    captures: dict[str, dict[str, Any]] = field(default_factory=dict)
    paypal_fee_known: bool = True
    base: str = "http://127.0.0.1:8780"  # where the fake browser pages are (test mode sets the runtime's own)

    def reset(self) -> None:
        base = self.base
        self.__init__()  # type: ignore[misc]
        self.base = base

    # --- what a customer or seller does at the provider (the tests and the /__test pages call these) ---------

    def stripe_code(self, account: str | None = None, *, live: bool = False) -> str:
        code = f"ac_test_{secrets.token_hex(6)}"
        self.codes[code] = account or f"acct_test{secrets.token_hex(5)}"
        if live:
            self.live_codes.add(code)
        return code

    def pay_stripe(self, link_id: str, *, amount: int | None = None) -> dict[str, Any]:
        """The customer pays the link: one completed Checkout Session, shaped as listed with the fee expanded."""
        link = self.links[link_id]
        if not link["active"]:
            raise ValueError("link inactive")
        price = self.prices[link["line_items"][0]["price"]]
        total = amount or price["unit_amount"]
        sid = f"cs_test_{secrets.token_hex(8)}"
        created = int(time.time())
        bt = (
            None
            if self.fee_pending
            else {
                "id": f"txn_{secrets.token_hex(6)}",
                "object": "balance_transaction",
                "amount": total,
                "currency": "gbp",
                "fee": stripe_fee(total),
                "net": total - stripe_fee(total),
                "type": "charge",
            }
        )
        session = {
            "id": sid,
            "object": "checkout.session",
            "amount_total": total,
            "currency": "gbp",
            "created": created,
            "livemode": False,
            "metadata": dict(link["metadata"]),
            "mode": "payment",
            "payment_link": link_id,
            "payment_status": "paid",
            "status": "complete",
            "payment_intent": {
                "id": f"pi_{secrets.token_hex(8)}",
                "object": "payment_intent",
                "amount": total,
                "status": "succeeded",
                "metadata": dict(link["payment_intent_data"]["metadata"]),
                "latest_charge": {"id": f"ch_{secrets.token_hex(8)}", "created": created, "balance_transaction": bt},
            },
            "_account": link["_account"],
        }
        self.sessions.append(session)
        link["_completed"] = link.get("_completed", 0) + 1
        if link["_completed"] >= link["restrictions"]["completed_sessions"]["limit"]:
            link["active"] = False  # Stripe switches the link off once the limit is met
        return session

    def pay_paypal(self, invoice_id: str, *, amount: int | None = None) -> str:
        inv = self.invoices[invoice_id]
        due = _pence(inv["due_amount"]["value"])
        paid = amount or due
        tid = f"{secrets.token_hex(8).upper()}"
        inv["payments"]["transactions"].append(
            {
                "payment_id": tid,
                "type": "PAYPAL",
                "method": "PAYPAL",
                "payment_date": time.strftime("%Y-%m-%d", time.gmtime()) + " UTC",
                "amount": {"currency_code": "GBP", "value": _value(paid)},
            }
        )
        total_paid = sum(_pence(t["amount"]["value"]) for t in inv["payments"]["transactions"])
        inv["payments"]["paid_amount"] = {"currency_code": "GBP", "value": _value(total_paid)}
        inv["due_amount"] = {
            "currency_code": "GBP",
            "value": _value(max(0, _pence(inv["amount"]["value"]) - total_paid)),
        }
        inv["status"] = "PAID" if total_paid >= _pence(inv["amount"]["value"]) else "PARTIALLY_PAID"
        self.captures[tid] = {
            "id": tid,
            "status": "COMPLETED",
            "amount": {"currency_code": "GBP", "value": _value(paid)},
            "seller_receivable_breakdown": {
                "gross_amount": {"currency_code": "GBP", "value": _value(paid)},
                "paypal_fee": {"currency_code": "GBP", "value": _value(paypal_fee(paid))},
                "net_amount": {"currency_code": "GBP", "value": _value(paid - paypal_fee(paid))},
            },
        }
        return tid


FAKES = Fakes()


def _pence(value: str) -> int:
    return int(Decimal(value) * 100)


def _value(pence: int) -> str:
    return f"{pence // 100}.{pence % 100:02d}"


def _json(status: int, body: Any) -> httpx.Response:
    return httpx.Response(status, json=body)


def _stripe_error(status: int, message: str) -> httpx.Response:
    return _json(status, {"error": {"type": "invalid_request_error", "message": message}})


def _public(obj: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def _basic(request: httpx.Request) -> tuple[str, str] | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return None
    user, _, pw = base64.b64decode(auth[6:]).decode().partition(":")
    return user, pw


def _nested(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """Stripe's bracket form encoding (`a[b][0][c]=v`) back into nested dicts; list indices become dict keys."""
    out: dict[str, Any] = {}
    for key, value in pairs:
        parts = key.replace("]", "").split("[")
        cur = out
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value
    return out


def _stripe(request: httpx.Request) -> httpx.Response:
    if _basic(request) != (STRIPE_KEY, ""):
        return _stripe_error(401, "Invalid API Key provided")
    path, method = request.url.path, request.method
    form = _nested(parse_qsl(request.content.decode())) if method == "POST" else {}
    account = request.headers.get("Stripe-Account")
    if request.url.host == "connect.stripe.com":
        if path == "/oauth/token" and method == "POST":
            code = form.get("code", "")
            if form.get("grant_type") != "authorization_code" or code not in FAKES.codes:
                return _json(
                    400, {"error": "invalid_grant", "error_description": f"Authorization code does not exist: {code}"}
                )
            acct = FAKES.codes.pop(code)  # one use (docs: consuming a code twice revokes the connection)
            FAKES.accounts.add(acct)
            live = code in FAKES.live_codes
            return _json(
                200,
                {
                    "access_token": "sk_test_deprecated_token",
                    "livemode": live,
                    "refresh_token": "rt_deprecated",
                    "scope": "read_write",
                    "stripe_publishable_key": "pk_test_deprecated",
                    "stripe_user_id": acct,
                    "token_type": "bearer",
                },
            )
        if path == "/oauth/deauthorize" and method == "POST":
            acct = form.get("stripe_user_id", "")
            if form.get("client_id") != "ca_accnomos_fake" or acct not in FAKES.accounts:
                return _json(401, {"error": "invalid_client", "error_description": "No such application"})
            FAKES.accounts.discard(acct)
            return _json(200, {"stripe_user_id": acct})
        return _stripe_error(404, f"Unrecognized request URL ({method}: {path})")
    if not account or account not in FAKES.accounts:
        return _stripe_error(403, "The provided key does not have access to account (or that account does not exist)")
    if path == "/v1/prices" and method == "POST":
        if form.get("currency") != "gbp" or not str(form.get("unit_amount", "")).isdigit():
            return _stripe_error(400, "Invalid price")
        pid = f"price_{secrets.token_hex(6)}"
        FAKES.prices[pid] = {
            "id": pid,
            "object": "price",
            "currency": "gbp",
            "unit_amount": int(form["unit_amount"]),
            "product": f"prod_{secrets.token_hex(5)}",
            "metadata": form.get("metadata", {}),
            "_name": form.get("product_data", {}).get("name"),
        }
        return _json(200, _public(FAKES.prices[pid]))
    if path == "/v1/payment_links" and method == "POST":
        items = form.get("line_items", {})
        first = items.get("0", {})
        if first.get("price") not in FAKES.prices:
            return _stripe_error(400, "No such price")
        lid = f"plink_{secrets.token_hex(6)}"
        FAKES.links[lid] = {
            "id": lid,
            "object": "payment_link",
            "active": True,
            "currency": "gbp",
            "livemode": False,
            "line_items": [{"price": first["price"], "quantity": int(first.get("quantity", "1"))}],
            "metadata": form.get("metadata", {}),
            "payment_intent_data": form.get("payment_intent_data", {"metadata": {}}),
            "restrictions": {"completed_sessions": {"limit": int(form["restrictions"]["completed_sessions"]["limit"])}},
            "after_completion": form.get("after_completion"),
            "url": f"{FAKES.base}/__test/stripe/pay/{lid}",
            "_account": account,
        }
        return _json(200, _public(FAKES.links[lid]))
    if path.startswith("/v1/payment_links/") and method == "POST":
        lid = path.rsplit("/", 1)[1]
        link = FAKES.links.get(lid)
        if link is None or link["_account"] != account:
            return _stripe_error(404, f"No such payment link: '{lid}'")
        if "active" in form:
            link["active"] = form["active"] == "true"
        return _json(200, _public(link))
    if path == "/v1/checkout/sessions" and method == "GET":
        q = dict(request.url.params.multi_items())
        expand = request.url.params.get_list("expand[]")
        out = [
            s
            for s in FAKES.sessions
            if s["_account"] == account
            and (not q.get("payment_link") or s["payment_link"] == q["payment_link"])
            and (not q.get("status") or s["status"] == q["status"])
        ]
        data = []
        for s in out:
            item = json.loads(json.dumps(_public(s)))
            if "data.payment_intent.latest_charge.balance_transaction" not in expand:
                item["payment_intent"] = item["payment_intent"]["id"]  # not expanded: just the id
            data.append(item)
        return _json(200, {"object": "list", "url": "/v1/checkout/sessions", "has_more": False, "data": data})
    return _stripe_error(404, f"Unrecognized request URL ({method}: {path})")


def _paypal_error(status: int, name: str, message: str) -> httpx.Response:
    return _json(status, {"name": name, "message": message, "debug_id": secrets.token_hex(6)})


def _assertion_merchant(request: httpx.Request) -> str | None:
    raw = request.headers.get("PayPal-Auth-Assertion")
    if not raw:
        return None
    head, payload, sig = raw.split(".")
    if json.loads(base64.b64decode(head)) != {"alg": "none"} or sig:
        return None
    claims = json.loads(base64.b64decode(payload))
    return claims.get("payer_id") if claims.get("iss") == PAYPAL_CLIENT[0] else None


def _paypal(request: httpx.Request) -> httpx.Response:
    path, method = request.url.path, request.method
    if path == "/v1/oauth2/token" and method == "POST":
        if (
            _basic(request) != PAYPAL_CLIENT
            or dict(parse_qsl(request.content.decode())).get("grant_type") != "client_credentials"
        ):
            return _json(401, {"error": "invalid_client", "error_description": "Client Authentication failed"})
        return _json(
            200,
            {
                "scope": "https://uri.paypal.com/services/invoicing",
                "access_token": "A21AAfake",
                "token_type": "Bearer",
                "app_id": "APP-FAKE",
                "expires_in": 32400,
                "nonce": "fake",
            },
        )
    if request.headers.get("Authorization") != "Bearer A21AAfake":
        return _paypal_error(
            401, "AUTHENTICATION_FAILURE", "Authentication failed due to invalid authentication credentials"
        )
    if not request.headers.get("PayPal-Partner-Attribution-Id"):
        return _paypal_error(400, "INVALID_REQUEST", "PayPal-Partner-Attribution-Id is required for partners")
    body = json.loads(request.content) if request.content else {}
    if path == "/v2/customer/partner-referrals" and method == "POST":
        features = body["operations"][0]["api_integration_preference"]["rest_api_integration"]["third_party_details"][
            "features"
        ]
        if "INVOICE_READ_WRITE" not in features:
            return _paypal_error(400, "INVALID_REQUEST", "missing feature")
        rid = secrets.token_hex(8)
        FAKES.referrals[rid] = {
            "tracking_id": body["tracking_id"],
            "return_url": body["partner_config_override"]["return_url"],
        }
        return _json(
            201,
            {
                "links": [
                    {
                        "href": f"https://api-m.sandbox.paypal.com/v2/customer/partner-referrals/{rid}",
                        "rel": "self",
                        "method": "GET",
                    },
                    {"href": f"{FAKES.base}/__test/paypal/signup/{rid}", "rel": "action_url", "method": "GET"},
                ]
            },
        )
    if path.startswith(f"/v1/customer/partners/{PAYPAL_PARTNER}/merchant-integrations/") and method == "GET":
        mid = path.rsplit("/", 1)[1]
        if mid not in FAKES.merchants:
            return _paypal_error(404, "RESOURCE_NOT_FOUND", "The specified resource does not exist.")
        return _json(200, FAKES.merchants[mid])
    merchant = _assertion_merchant(request)
    if path.startswith(("/v2/invoicing/", "/v2/payments/")) and (merchant is None or merchant not in FAKES.merchants):
        return _paypal_error(403, "NOT_AUTHORIZED", "Authorization failed due to insufficient permissions.")
    if path == "/v2/invoicing/invoices" and method == "POST":
        number = body["detail"]["invoice_number"]
        if any(i["detail"]["invoice_number"] == number and i["_merchant"] == merchant for i in FAKES.invoices.values()):
            return _paypal_error(422, "UNPROCESSABLE_ENTITY", "Invoice number already exists")
        item = body["items"][0]
        if item["unit_amount"]["currency_code"] != "GBP":
            return _paypal_error(422, "UNPROCESSABLE_ENTITY", "currency")
        iid = "INV2-" + "-".join(secrets.token_hex(2).upper() for _ in range(4))
        amount = {"currency_code": "GBP", "value": item["unit_amount"]["value"]}
        FAKES.invoices[iid] = {
            "id": iid,
            "status": "DRAFT",
            "detail": {**body["detail"], "metadata": {"create_time": "2026-10-27T09:00:00Z"}},
            "primary_recipients": body.get("primary_recipients", []),
            "items": body["items"],
            "configuration": body.get("configuration", {}),
            "amount": amount,
            "due_amount": dict(amount),
            "payments": {"transactions": []},
            "_merchant": merchant,
        }
        return _json(201, _public(FAKES.invoices[iid]))
    if path.startswith("/v2/invoicing/invoices/"):
        rest = path.removeprefix("/v2/invoicing/invoices/").split("/")
        inv = FAKES.invoices.get(rest[0])
        if inv is None or inv["_merchant"] != merchant:
            return _paypal_error(404, "RESOURCE_NOT_FOUND", "The specified resource does not exist.")
        if len(rest) == 1 and method == "GET":
            return _json(200, _public(inv))
        if rest[1:] == ["send"] and method == "POST":
            inv["status"] = "UNPAID"  # sent, but (send_to_recipient: false) emailed to nobody
            inv["detail"]["metadata"]["recipient_view_url"] = f"{FAKES.base}/__test/paypal/pay/{inv['id']}"
            return _json(
                200, {"href": inv["detail"]["metadata"]["recipient_view_url"], "rel": "payer-view", "method": "GET"}
            )
        if rest[1:] == ["cancel"] and method == "POST":
            inv["status"] = "CANCELLED"
            return httpx.Response(204)
    if path.startswith("/v2/payments/captures/") and method == "GET":
        cap = FAKES.captures.get(path.rsplit("/", 1)[1])
        if cap is None or not FAKES.paypal_fee_known:
            return _paypal_error(404, "RESOURCE_NOT_FOUND", "The specified resource does not exist.")
        return _json(200, cap)
    return _paypal_error(404, "NOT_FOUND", f"{method} {path}")


def handle(request: httpx.Request) -> httpx.Response:
    FAKES.requests.append(request)
    host = request.url.host
    if host in ("api.stripe.com", "connect.stripe.com"):
        return _stripe(request)
    if host == "api-m.sandbox.paypal.com":
        return _paypal(request)
    return httpx.Response(599, text=f"online_fakes: no fake for {host}")  # a call that would have left the machine


def install(base: str | None = None) -> None:
    payment_providers.TRANSPORT = httpx.MockTransport(handle)
    payment_providers._paypal_tokens.clear()
    if base:
        FAKES.base = base.rstrip("/")


# --------------------------------------------------------------------------- #
# The browser's side of the providers, in test mode (mounted under /__test by app/testmode.py)
# --------------------------------------------------------------------------- #

router = APIRouter(include_in_schema=False)

PAGE = """<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family:sans-serif;max-width:32rem;margin:3rem auto">
<p><strong>TEST MODE</strong>: a stand-in for {who}; no money moves.</p><h1>{title}</h1>{body}</body></html>"""


@router.get("/stripe/oauth/authorize")
async def stripe_authorize(request: Request) -> RedirectResponse:
    """Stripe's consent screen, already agreed: straight back to the redirect URI with a code (docs/connect/
    oauth-reference: `code`, `scope`, `state`)."""
    q = request.query_params
    if q.get("client_id") != "ca_accnomos_fake" or q.get("response_type") != "code" or q.get("scope") != "read_write":
        raise HTTPException(400, "bad authorize request")
    code = FAKES.stripe_code()
    return RedirectResponse(
        f"{q['redirect_uri']}?{urlencode({'code': code, 'scope': 'read_write', 'state': q.get('state', '')})}", 303
    )


@router.get("/paypal/signup/{rid}")
async def paypal_signup(rid: str) -> RedirectResponse:
    """PayPal sign-up, already finished: the seller comes back with `merchantIdInPayPal` and the flags."""
    ref = FAKES.referrals.get(rid)
    if ref is None:
        raise HTTPException(404, "no such sign-up")
    FAKES.merchants[PAYPAL_MERCHANT] = {
        "merchant_id": PAYPAL_MERCHANT,
        "tracking_id": ref["tracking_id"],
        "payments_receivable": True,
        "primary_email_confirmed": True,
        "oauth_integrations": [
            {
                "integration_type": "OAUTH_THIRD_PARTY",
                "integration_method": "PAYPAL",
                "oauth_third_party": [
                    {"partner_client_id": PAYPAL_CLIENT[0], "scopes": ["https://uri.paypal.com/services/invoicing"]}
                ],
            }
        ],
    }
    extra = urlencode(
        {
            "merchantId": ref["tracking_id"],
            "merchantIdInPayPal": PAYPAL_MERCHANT,
            "permissionsGranted": "true",
            "consentStatus": "true",
            "isEmailConfirmed": "true",
        }
    )
    sep = "&" if "?" in ref["return_url"] else "?"
    return RedirectResponse(f"{ref['return_url']}{sep}{extra}", 303)


@router.get("/stripe/pay/{lid}", response_class=HTMLResponse)
async def stripe_pay_page(lid: str) -> HTMLResponse:
    link = FAKES.links.get(lid)
    if link is None:
        raise HTTPException(404, "no such link")
    price = FAKES.prices[link["line_items"][0]["price"]]
    if not link["active"]:
        body = f"<p>{link.get('inactive_message') or 'This link is no longer active.'}</p>"
    else:
        body = f'<form method="post"><button type="submit">Pay £{_value(price["unit_amount"])}</button></form>'
    return HTMLResponse(PAGE.format(title=price["_name"] or "Pay", who="Stripe Checkout", body=body))


@router.post("/stripe/pay/{lid}", response_class=HTMLResponse)
async def stripe_pay(lid: str) -> HTMLResponse:
    if lid not in FAKES.links or not FAKES.links[lid]["active"]:
        raise HTTPException(404, "no such active link")
    FAKES.pay_stripe(lid)
    return HTMLResponse(PAGE.format(title="Payment received", who="Stripe Checkout", body="<p>Thank you.</p>"))


@router.get("/paypal/pay/{iid}", response_class=HTMLResponse)
async def paypal_pay_page(iid: str) -> HTMLResponse:
    inv = FAKES.invoices.get(iid)
    if inv is None:
        raise HTTPException(404, "no such invoice")
    if inv["status"] in ("PAID", "CANCELLED"):
        body = f"<p>This invoice is {inv['status'].lower()}.</p>"
    else:
        body = f'<form method="post"><button type="submit">Pay £{inv["due_amount"]["value"]}</button></form>'
    return HTMLResponse(PAGE.format(title=inv["detail"]["note"], who="PayPal", body=body))


@router.post("/paypal/pay/{iid}", response_class=HTMLResponse)
async def paypal_pay(iid: str) -> HTMLResponse:
    inv = FAKES.invoices.get(iid)
    if inv is None or inv["status"] in ("PAID", "CANCELLED"):
        raise HTTPException(404, "no such open invoice")
    FAKES.pay_paypal(iid)
    return HTMLResponse(PAGE.format(title="Payment received", who="PayPal", body="<p>Thank you.</p>"))
