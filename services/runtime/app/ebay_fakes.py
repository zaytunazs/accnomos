"""A stand-in for eBay's OAuth, Finances and Fulfillment APIs, for the unit tests and test mode
(`ACCNOMOS_TEST_MODE=1`). Nothing is ever sent to eBay from here.

`install()` points app/ebay.TRANSPORT at `handle`, an httpx MockTransport handler that answers the calls app/ebay.py
makes with the shapes its docstring lists: the form-encoded token endpoint with Basic client credentials, the Bearer
`GET /sell/finances/v1/transaction` and `/payout` (filter, limit, offset; `total` and `next`), and
`GET /sell/fulfillment/v1/order?orderIds=`. A request the fake does not know is a 404, so a wrong path fails a test
instead of passing quietly. Every request is kept in `FAKES.requests`.

In test mode `router` adds the page a browser would see at eBay: a sign-in and "Agree" that has already agreed and
sends the browser to the RuName's accept URL (this runtime's /books/ebay/callback) with a code.

The fake seller (SAMPLE — FICTIONAL) has two sales, a refund of half the second, a promoted-listing fee, a postage
label with VAT, an adjustment (skipped), one paid-out payout and one still being sent.
"""

from __future__ import annotations

import base64
import re
import secrets
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app import ebay

CLIENT = ("accnomos-fake-ebay", "accnomos-fake-ebay-secret")
RUNAME = "Accnomos-FakeRuName"
ORDER_1 = "01-11111-11111"
ORDER_2 = "02-22222-22222"


def _today() -> date:
    from app.books import today  # pinned in test mode

    return today()


def _ts(days_ago: int) -> str:
    return f"{(_today() - timedelta(days=days_ago)).isoformat()}T10:00:00.000Z"


def _gbp(v: str) -> dict[str, str]:
    return {"value": v, "currency": "GBP"}


def transactions() -> list[dict[str, Any]]:
    """The fake seller's monetary transactions, newest first, as getTransactions returns them."""
    return [
        {
            "transactionId": "fake-tx-006",
            "transactionType": "ADJUSTMENT",
            "transactionDate": _ts(2),
            "amount": _gbp("1.00"),
            "bookingEntry": "CREDIT",
            "transactionStatus": "PAYOUT",
        },
        {
            "transactionId": "fake-tx-005",
            "transactionType": "SHIPPING_LABEL",
            "transactionDate": _ts(3),
            "amount": _gbp("3.60"),
            "bookingEntry": "DEBIT",
            "transactionMemo": "Shipping label purchase",
            "taxes": [{"taxType": "VAT", "amount": _gbp("0.60")}],
            "orderId": ORDER_1,
        },
        {
            "transactionId": "fake-tx-004",
            "transactionType": "NON_SALE_CHARGE",
            "transactionDate": _ts(4),
            "amount": _gbp("4.00"),
            "bookingEntry": "DEBIT",
            "feeType": "AD_FEE",
            "transactionMemo": "Promoted Listings fee",
            "references": [{"referenceId": "110000000001", "referenceType": "ITEM_ID"}],
        },
        {
            "transactionId": "fake-tx-003",
            "transactionType": "REFUND",
            "transactionDate": _ts(5),
            "orderId": ORDER_2,
            "amount": _gbp("26.42"),
            "bookingEntry": "DEBIT",
            "totalFeeAmount": _gbp("3.58"),
            "buyer": {"username": "fake_buyer_2"},
        },
        {
            "transactionId": "fake-tx-002",
            "transactionType": "SALE",
            "transactionDate": _ts(10),
            "orderId": ORDER_2,
            "amount": _gbp("52.85"),
            "bookingEntry": "CREDIT",
            "totalFeeAmount": _gbp("7.15"),
            "totalFeeBasisAmount": _gbp("60.00"),
            "transactionStatus": "PAYOUT",
            "payoutId": "fake-payout-1",
            "buyer": {"username": "fake_buyer_2"},
            "orderLineItems": [
                {
                    "lineItemId": "li-2",
                    "feeBasisAmount": _gbp("60.00"),
                    "marketplaceFees": [
                        {"feeType": "FINAL_VALUE_FEE", "amount": _gbp("5.65")},
                        {"feeType": "FINAL_VALUE_FEE_FIXED_PER_ORDER", "amount": _gbp("0.30")},
                        {"feeType": "AD_FEE", "amount": _gbp("1.20")},
                    ],
                }
            ],
        },
        {
            "transactionId": "fake-tx-001",
            "transactionType": "SALE",
            "transactionDate": _ts(12),
            "orderId": ORDER_1,
            "amount": _gbp("21.20"),
            "bookingEntry": "CREDIT",
            "totalFeeAmount": _gbp("2.80"),
            "totalFeeBasisAmount": _gbp("24.00"),
            "transactionStatus": "PAYOUT",
            "payoutId": "fake-payout-1",
            "buyer": {"username": "fake_buyer_1"},
        },
    ]


def payouts() -> list[dict[str, Any]]:
    return [
        {
            "payoutId": "fake-payout-2",
            "payoutStatus": "INITIATED",
            "payoutDate": _ts(1),
            "amount": _gbp("0.00"),
            "payoutInstrument": {
                "instrumentType": "BANK",
                "nickname": "Business account",
                "accountLastFourDigits": "5678",
            },
            "transactionCount": 1,
        },
        {
            "payoutId": "fake-payout-1",
            "payoutStatus": "SUCCEEDED",
            "payoutDate": _ts(1),
            "amount": _gbp("40.03"),
            "payoutInstrument": {
                "instrumentType": "BANK",
                "nickname": "Business account",
                "accountLastFourDigits": "5678",
            },
            "transactionCount": 6,
        },
    ]


ORDERS = {
    ORDER_1: {"orderId": ORDER_1, "lineItems": [{"lineItemId": "li-1", "title": "Blue mug (sample)", "quantity": 2}]},
    ORDER_2: {"orderId": ORDER_2, "lineItems": [{"lineItemId": "li-2", "title": "Desk lamp (sample)", "quantity": 1}]},
}


@dataclass
class Fakes:
    requests: list[httpx.Request] = field(default_factory=list)
    codes: set[str] = field(default_factory=set)
    access: set[str] = field(default_factory=set)
    refresh: set[str] = field(default_factory=set)
    fail_orders: bool = False  # Fulfillment is down: the sync still proposes, with a warning
    revoke_refresh: bool = False  # the seller withdrew access at eBay: the refresh token is refused
    extra: list[dict[str, Any]] = field(default_factory=list)  # more transactions (pagination tests)

    def new_code(self) -> str:
        code = f"v^1.1#fake-code-{secrets.token_hex(8)}"  # eBay's codes carry ^ and #: the exchange must decode once
        self.codes.add(code)
        return code

    def tokens(self, with_refresh: bool) -> dict[str, Any]:
        access = f"fake-access-{secrets.token_hex(8)}"
        self.access.add(access)
        out: dict[str, Any] = {"access_token": access, "expires_in": 7200, "token_type": "User Access Token"}
        if with_refresh:
            refresh = f"fake-refresh-{secrets.token_hex(8)}"
            self.refresh.add(refresh)
            out |= {"refresh_token": refresh, "refresh_token_expires_in": 47304000}
        return out


FAKES = Fakes()


def _json(status: int, body: Any) -> httpx.Response:
    return httpx.Response(status, json=body)


def _err(status: int, error: str) -> httpx.Response:
    return _json(status, {"error": error, "error_description": error.replace("_", " ")})


def _api_err(status: int, message: str) -> httpx.Response:
    return _json(status, {"errors": [{"errorId": 1, "message": message, "longMessage": message}]})


FILTER = re.compile(
    r"^(transactionDate|payoutDate):\[(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z)\.\.(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z)\]$"
)


def _page(request: httpx.Request, rows: list[dict[str, Any]], key: str, field_: str, date_key: str) -> httpx.Response:
    q = dict(request.url.params)
    m = FILTER.match(q.get("filter", ""))
    if not m or m.group(1) != field_:
        return _api_err(400, "invalid filter")
    start, end = m.group(2)[:10], m.group(3)[:10]
    try:
        limit, offset = int(q.get("limit", "20")), int(q.get("offset", "0"))
    except ValueError:
        return _api_err(400, "invalid limit or offset")
    if not 1 <= limit <= 1000 or offset < 0:
        return _api_err(400, "invalid limit or offset")
    hits = [r for r in rows if start <= str(r.get(date_key))[:10] <= end]
    if not hits:
        return httpx.Response(204)
    body: dict[str, Any] = {"href": str(request.url), "limit": limit, "offset": offset, "total": len(hits)}
    body[key] = hits[offset : offset + limit]
    if offset + limit < len(hits):
        body["next"] = str(request.url.copy_merge_params({"offset": str(offset + limit)}))
    return _json(200, body)


def handle(request: httpx.Request) -> httpx.Response:
    FAKES.requests.append(request)
    path, host = request.url.path, request.url.host
    if request.method == "POST" and host == "api.sandbox.ebay.com" and path == "/identity/v1/oauth2/token":
        basic = base64.b64encode(f"{CLIENT[0]}:{CLIENT[1]}".encode()).decode()
        if request.headers.get("Authorization") != f"Basic {basic}":
            return _err(401, "invalid_client")
        if request.headers.get("Content-Type", "").split(";")[0] != "application/x-www-form-urlencoded":
            return _err(400, "invalid_request")
        form = dict(parse_qsl(request.content.decode()))
        if form.get("grant_type") == "authorization_code":
            if form.get("redirect_uri") != RUNAME or form.get("code") not in FAKES.codes:
                return _err(400, "invalid_grant")
            FAKES.codes.discard(form["code"])
            return _json(200, FAKES.tokens(with_refresh=True))
        if form.get("grant_type") == "refresh_token":
            if FAKES.revoke_refresh or form.get("refresh_token") not in FAKES.refresh:
                return _err(400, "invalid_grant")
            if set(form.get("scope", "").split()) - set(ebay.SCOPES):
                return _err(400, "invalid_scope")
            return _json(200, FAKES.tokens(with_refresh=False))
        return _err(400, "unsupported_grant_type")
    if host in ("apiz.sandbox.ebay.com", "api.sandbox.ebay.com") and request.method == "GET":
        if request.headers.get("Authorization", "").removeprefix("Bearer ") not in FAKES.access:
            return _api_err(401, "Invalid access token")
        if request.headers.get("X-EBAY-C-MARKETPLACE-ID") != ebay.MARKETPLACE:
            return _api_err(400, "marketplace id missing")
        if host == "apiz.sandbox.ebay.com" and path == "/sell/finances/v1/transaction":
            return _page(request, transactions() + FAKES.extra, "transactions", "transactionDate", "transactionDate")
        if host == "apiz.sandbox.ebay.com" and path == "/sell/finances/v1/payout":
            return _page(request, payouts(), "payouts", "payoutDate", "payoutDate")
        if host == "api.sandbox.ebay.com" and path == "/sell/fulfillment/v1/order":
            if FAKES.fail_orders:
                return _api_err(500, "System error")
            ids = [i for i in request.url.params.get("orderIds", "").split(",") if i]
            if not ids or len(ids) > ebay.ORDER_BATCH:
                return _api_err(400, "orderIds: 1 to 50")
            return _json(200, {"orders": [ORDERS[i] for i in ids if i in ORDERS], "total": len(ids)})
    return _api_err(404, f"ebay_fakes: no fake for {request.method} {host}{path}")


def install() -> None:
    ebay.TRANSPORT = httpx.MockTransport(handle)


def reset() -> None:
    FAKES.__dict__.update(Fakes().__dict__)


# --------------------------------------------------------------------------- #
# The browser's side of eBay, in test mode (mounted under /__test by app/testmode.py)
# --------------------------------------------------------------------------- #

router = APIRouter(include_in_schema=False)


@router.get("/ebay/oauth2/authorize")
async def ebay_authorize(request: Request) -> RedirectResponse:
    """eBay's sign-in and "Agree", already agreed: to the RuName's accept URL with `code`, `state`, `expires_in`."""
    from app.ebay_sync import public_base

    q = request.query_params
    if (
        q.get("client_id") != CLIENT[0]
        or q.get("response_type") != "code"
        or q.get("redirect_uri") != RUNAME
        or set(q.get("scope", "").split()) != set(ebay.SCOPES)
    ):
        raise HTTPException(400, "bad consent request")
    back = {"state": q.get("state", ""), "code": FAKES.new_code(), "expires_in": "299"}
    return RedirectResponse(f"{public_base()}/books/ebay/callback?{urlencode(back)}", 303)
