"""eBay's OAuth and Sell APIs over HTTP, for Connect eBay (app/ebay_sync.py). No SDK: each call is the documented
request, so the fakes in app/ebay_fakes.py can check it field by field.

Sources, read on 9 Nov 2026 (eBay's developer site moved its pages to /develop/...; the OpenAPI specs and the
Markdown guide below are eBay's own):

  * OAuth, the authorization code grant: https://developer.ebay.com/develop/guides/authorization.md
    - consent: `GET https://auth.sandbox.ebay.com/oauth2/authorize` | `https://auth.ebay.com/oauth2/authorize` with
      `client_id`, `redirect_uri` (**the RuName**, not a URL), `response_type=code`, `scope` (space-separated),
      `state` (returned unchanged), optional `prompt=login`. eBay sends the browser to the RuName's "Auth Accepted
      URL" with `code` (URL-encoded, single use, valid `expires_in` seconds, 299 in the example) and `state`.
    - token: `POST https://api.sandbox.ebay.com/identity/v1/oauth2/token` | `https://api.ebay.com/...`,
      `Content-Type: application/x-www-form-urlencoded`, `Authorization: Basic base64(client_id:client_secret)`;
      body `grant_type=authorization_code&code=&redirect_uri=<RuName>`, answer `access_token`, `expires_in` (7200),
      `refresh_token`, `refresh_token_expires_in` (47304000 s, about 18 months), `token_type`.
    - refresh: same endpoint, `grant_type=refresh_token&refresh_token=&scope=` (scope optional; "equal to or a
      subset of" the consent's). The answer carries a new access token; the guide does not show a new refresh
      token in it, so the stored one is kept unless one is returned.
    - **Not found in the guide: an endpoint to revoke a user's refresh token.** Disconnect forgets it here and asks
      the user to remove Accnomos in their eBay account settings (UNVERIFIED where eBay puts that setting).
  * Finances API v1.19.0, OpenAPI spec
    https://developer.ebay.com/api-docs/master/sell/finances/openapi/3/sell_finances_v1_oas3.json and
    https://developer.ebay.com/develop/api/sell/finances_api.md:
    - production base `https://apiz.ebay.com/sell/finances/v1` (the spec lists only production servers; the
      sandbox base `https://apiz.sandbox.ebay.com/sell/finances/v1` is **UNVERIFIED**, by eBay's usual naming).
    - scope `https://api.ebay.com/oauth/api_scope/sell.finances`; header `X-EBAY-C-MARKETPLACE-ID` (EBAY_US if
      absent; we send EBAY_GB).
    - `GET /transaction?filter=transactionDate:[2024-10-23T00:00:01.000Z..2024-11-09T00:00:01.000Z]&limit=&offset=`:
      range at most 36 months, within 5 years; `limit` max 1000 by the parameter, 200 by the response schema (we ask
      200), default 20; answer `{href, limit, next?, offset, prev?, total, transactions: [Transaction]}`, or 204
      when nothing matches. A Transaction: `transactionId` (unique with `transactionType`), `transactionType`
      (SALE, REFUND, CREDIT, DISPUTE, SHIPPING_LABEL, TRANSFER, NON_SALE_CHARGE, ADJUSTMENT, WITHDRAWAL,
      LOAN_REPAYMENT, PURCHASE; there is no FEE type, we accept one anyway), `transactionDate`, `amount {value,
      currency}`, `bookingEntry` (CREDIT | DEBIT to the seller), `orderId`, `payoutId`, `transactionStatus`,
      `totalFeeAmount` ("total amount of selling fees paid for order"), `totalFeeBasisAmount` ("total amount for the
      order before selling fees are deducted"), `eBayCollectedTaxAmount`, `orderLineItems[{lineItemId,
      feeBasisAmount, marketplaceFees[{feeType, amount}]}]`, `feeType`, `transactionMemo`, `references`, `taxes
      [{taxType: VAT, amount}]` ("only returned for tax charged against a purchased eBay shipping label"). A line
      item's feeBasisAmount "equals what the buyer has paid ... includes transactions.amount, totalFeeAmount,
      eBayCollectedTaxAmount, and shipping": so a SALE's `amount` is the seller's money **after** fees.
    - `GET /payout?filter=payoutDate:[..]&limit=&offset=`: limit max 200; answer `{next?, total, payouts:
      [{payoutId, payoutStatus (INITIATED|SUCCEEDED|REVERSED|RETRYABLE_FAILED|TERMINAL_FAILED), payoutDate,
      amount, payoutInstrument {instrumentType, nickname, accountLastFourDigits}, bankReference?, transactionCount}]}`.
  * Fulfillment API v1.20.7, https://developer.ebay.com/api-docs/master/sell/fulfillment/openapi/3/
    sell_fulfillment_v1_oas3.json: `GET https://api.ebay.com/sell/fulfillment/v1/order?orderIds=a,b` (at most 50;
    other parameters are then ignored), scope `sell.fulfillment.readonly`; answer `{orders: [{orderId, creationDate,
    lineItems: [{lineItemId, title, quantity, sku, total}], pricingSummary}]}`. Sandbox base
    `https://api.sandbox.ebay.com` (UNVERIFIED, eBay's usual naming).

Every amount leaves this module as integer pence (`pence`).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

import httpx

TIMEOUT = httpx.Timeout(20.0, connect=5.0)
#: Set by app/ebay_fakes.py in test mode and by the unit tests: every eBay call goes to the fakes instead.
TRANSPORT: httpx.AsyncBaseTransport | None = None

SCOPES = (
    "https://api.ebay.com/oauth/api_scope/sell.finances",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
)
MARKETPLACE = "EBAY_GB"
PAGE = 200  # transactions and payouts per page (the payouts maximum; the transactions schema's too)
MAX_PAGES = 50  # 10,000 rows a sync: well past a small seller's 90 days, and a stop if `total` misbehaves
ORDER_BATCH = 50  # getOrders' orderIds maximum


@dataclass(frozen=True)
class Hosts:
    auth: str  # the consent page
    api: str  # identity (token) and fulfillment
    apiz: str  # finances

    @property
    def sandbox(self) -> bool:
        return "sandbox" in self.api or "sandbox" in self.auth


SANDBOX = Hosts("https://auth.sandbox.ebay.com", "https://api.sandbox.ebay.com", "https://apiz.sandbox.ebay.com")
PRODUCTION = Hosts("https://auth.ebay.com", "https://api.ebay.com", "https://apiz.ebay.com")


class EbayError(RuntimeError):
    """eBay refused or could not be reached. `status` is the HTTP status (0: no answer)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"eBay: {message}" + (f" (HTTP {status})" if status else ""))
        self.status, self.message = status, message


@dataclass(frozen=True)
class EbayConfig:
    client_id: str
    client_secret: str
    runame: str  # eBay's name for the redirect; its "Auth Accepted URL" is this runtime's /books/ebay/callback
    hosts: Hosts = SANDBOX

    @property
    def sandbox(self) -> bool:
        return self.hosts.sandbox


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, transport=TRANSPORT, follow_redirects=False)


def pence(amount: Any) -> int | None:
    """eBay's `Amount.value` (a decimal string) as pence; None for a third decimal place or no number."""
    value = amount.get("value") if isinstance(amount, dict) else amount
    if isinstance(value, bool) or value is None:
        return None
    try:
        p = Decimal(str(value)) * 100
    except InvalidOperation:
        return None
    return int(p) if p == p.to_integral_value() else None


def currency(amount: Any) -> str:
    return str(amount.get("currency") or "").upper() if isinstance(amount, dict) else ""


def stamp(d: datetime) -> str:
    """eBay's filter timestamp: YYYY-MM-DDTHH:MM:SS.SSSZ in UTC."""
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def auth_url(cfg: EbayConfig, state: str) -> str:
    """Where the browser goes to sign in to eBay and agree; eBay comes back to the RuName's accept URL."""
    q = {
        "client_id": cfg.client_id,
        "redirect_uri": cfg.runame,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": state,
    }
    return f"{cfg.hosts.auth}/oauth2/authorize?{urlencode(q)}"


def _error_text(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200] or "error"
    if isinstance(body, dict):
        if isinstance(body.get("errors"), list) and body["errors"] and isinstance(body["errors"][0], dict):
            e = body["errors"][0]
            return str(e.get("longMessage") or e.get("message") or "error")[:300]
        return str(body.get("error_description") or body.get("error") or "error")[:300]
    return "error"


class EbayApi:
    def __init__(self, cfg: EbayConfig, http: httpx.AsyncClient) -> None:
        self.cfg, self.http = cfg, http

    async def _send(self, method: str, url: str, **kw: Any) -> dict[str, Any]:
        try:
            resp = await self.http.request(method, url, **kw)
        except httpx.HTTPError as exc:
            raise EbayError(0, f"could not reach eBay ({type(exc).__name__})") from exc
        if resp.status_code == 204:  # "nothing matches" on the Finances API
            return {}
        if resp.status_code >= 400:
            raise EbayError(resp.status_code, _error_text(resp))
        try:
            body = resp.json()
        except ValueError as exc:
            raise EbayError(resp.status_code, "answer was not JSON") from exc
        if not isinstance(body, dict):
            raise EbayError(resp.status_code, "answer was not a JSON object")
        return body

    def _basic(self) -> dict[str, str]:
        raw = f"{self.cfg.client_id}:{self.cfg.client_secret}".encode()
        return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}

    async def _token(self, form: dict[str, str]) -> dict[str, Any]:
        got = await self._send(
            "POST", f"{self.cfg.hosts.api}/identity/v1/oauth2/token", data=form, headers=self._basic()
        )
        if not got.get("access_token"):
            raise EbayError(0, "no access token in the answer")
        return got

    async def exchange_code(self, code: str) -> dict[str, Any]:
        # httpx form-encodes the body, so the code goes in decoded (the guide's tip on double encoding).
        return await self._token({"grant_type": "authorization_code", "code": code, "redirect_uri": self.cfg.runame})

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        return await self._token(
            {"grant_type": "refresh_token", "refresh_token": refresh_token, "scope": " ".join(SCOPES)}
        )

    def _bearer(self, access: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access}",
            "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE,
            "Accept": "application/json",
        }

    async def _pages(self, access: str, url: str, key: str, filt: str) -> list[dict[str, Any]]:
        """Every row of a Finances list, page by page (limit/offset), until `total` is reached or a page is short."""
        out: list[dict[str, Any]] = []
        offset = 0
        for _ in range(MAX_PAGES):
            params = {"filter": filt, "limit": str(PAGE), "offset": str(offset)}
            got = await self._send("GET", url, headers=self._bearer(access), params=params)
            got_rows = got.get(key)
            rows: list[Any] = got_rows if isinstance(got_rows, list) else []
            out += [r for r in rows if isinstance(r, dict)]
            offset += len(rows)
            total = got.get("total") if isinstance(got.get("total"), int) else None
            if not rows or (total is not None and offset >= total) or (total is None and not got.get("next")):
                return out
        raise EbayError(0, f"more than {MAX_PAGES * PAGE} rows; sync a shorter period")

    async def transactions(self, access: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        filt = f"transactionDate:[{stamp(start)}..{stamp(end)}]"
        return await self._pages(access, f"{self.cfg.hosts.apiz}/sell/finances/v1/transaction", "transactions", filt)

    async def payouts(self, access: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        filt = f"payoutDate:[{stamp(start)}..{stamp(end)}]"
        return await self._pages(access, f"{self.cfg.hosts.apiz}/sell/finances/v1/payout", "payouts", filt)

    async def orders(self, access: str, order_ids: list[str]) -> list[dict[str, Any]]:
        """The orders' line items (titles, quantities), at most ORDER_BATCH ids a call."""
        out: list[dict[str, Any]] = []
        for i in range(0, len(order_ids), ORDER_BATCH):
            batch = order_ids[i : i + ORDER_BATCH]
            got = await self._send(
                "GET",
                f"{self.cfg.hosts.api}/sell/fulfillment/v1/order",
                headers=self._bearer(access),
                params={"orderIds": ",".join(batch)},
            )
            out += [o for o in (got.get("orders") or []) if isinstance(o, dict)]
        return out
