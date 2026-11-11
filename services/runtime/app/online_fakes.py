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
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from email.parser import BytesParser
from email.policy import default
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
    # Transaction Search rows (`transaction_details[]`). None: the sample history (sample_transactions), dated back
    # from the end of the first search, so test mode has something to sync. Payments made through fake PayPal
    # invoices (pay_paypal) are listed as well, as PayPal would.
    reporting: list[dict[str, Any]] | None = None
    paypal_tax_on_total: bool = False  # PayPal rounds tax once on the whole invoice (see _invoice_total)
    disputes: dict[str, dict[str, Any]] = field(default_factory=dict)  # PP-D-… -> PayPal dispute, with "_merchant"
    evidence: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # dispute id -> what was provided
    # Payouts v1 (bills paid through PayPal, app/billpay.py): sender_batch_id -> batch, with "_merchant"
    payouts: dict[str, dict[str, Any]] = field(default_factory=dict)
    payout_fail_next: int = 0  # answer the next N payout POSTs with a 503 (PayPal may or may not have it)
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

    def open_dispute(
        self, invoice_id: str, *, reason: str = "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", dispute_id: str | None = None
    ) -> str:
        """The payer disputes the last payment on the PayPal invoice: a dispute waiting for the seller's answer."""
        inv = self.invoices[invoice_id]
        tx = inv["payments"]["transactions"][-1]
        d = dispute_shape(
            dispute_id or f"PP-D-{secrets.randbelow(10**8):08d}",
            paypal_invoice_number=inv["detail"]["invoice_number"],
            transaction_id=tx["payment_id"],
            amount_pence=_pence(tx["amount"]["value"]),
            reason=reason,
            created="2026-11-05T10:00:00.000Z",
            due="2026-11-15T10:00:00.000Z",
        )
        self.disputes[d["dispute_id"]] = {**d, "_merchant": inv["_merchant"]}
        return d["dispute_id"]

    def resolve_dispute(self, dispute_id: str, *, buyer_wins: bool) -> None:
        d = self.disputes[dispute_id]
        d.update(
            status="RESOLVED",
            dispute_state="RESOLVED",
            dispute_outcome={
                "outcome_code": "RESOLVED_BUYER_FAVOUR" if buyer_wins else "RESOLVED_SELLER_FAVOUR",
                **({"amount_refunded": dict(d["dispute_amount"])} if buyer_wins else {}),
            },
            update_time="2026-11-20T10:00:00.000Z",
            links=[],
        )


def dispute_shape(
    dispute_id: str,
    *,
    paypal_invoice_number: str,
    transaction_id: str,
    amount_pence: int,
    reason: str,
    created: str,
    due: str,
) -> dict[str, Any]:
    """A dispute as `GET /v1/customer/disputes/{id}` shows it (Disputes v1 schema 1.12), waiting for the seller."""
    money = {"currency_code": "GBP", "value": _value(amount_pence)}
    base = f"https://api-m.sandbox.paypal.com/v1/customer/disputes/{dispute_id}"
    return {
        "dispute_id": dispute_id,
        "create_time": created,
        "update_time": created,
        "disputed_transactions": [
            {
                "seller_transaction_id": transaction_id,
                "create_time": created,
                "transaction_status": "COMPLETED",
                "gross_amount": dict(money),
                "invoice_number": paypal_invoice_number,
                "buyer": {"name": "Payer (sample)"},
            }
        ],
        "reason": reason,
        "status": "WAITING_FOR_SELLER_RESPONSE",
        "dispute_state": "REQUIRED_ACTION",
        "dispute_amount": dict(money),
        "dispute_life_cycle_stage": "CHARGEBACK",
        "dispute_channel": "INTERNAL",
        "seller_response_due_date": due,
        "messages": [{"posted_by": "BUYER", "time_posted": created, "content": "I have not received what I paid for."}],
        "links": [
            {"href": base, "rel": "self", "method": "GET"},
            {"href": f"{base}/provide-evidence", "rel": "provide_evidence", "method": "POST"},
            {"href": f"{base}/accept-claim", "rel": "accept_claim", "method": "POST"},
        ],
    }


def dispute_summary(d: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "dispute_id",
        "create_time",
        "update_time",
        "reason",
        "status",
        "dispute_state",
        "dispute_amount",
        "dispute_life_cycle_stage",
        "seller_response_due_date",
    )
    return {k: d[k] for k in keys if k in d} | {
        "links": [{"href": f"https://api-m.sandbox.paypal.com/v1/customer/disputes/{d['dispute_id']}", "rel": "self"}]
    }


FAKES = Fakes()


def payout_fee(pence: int) -> int:
    """Made up for the fakes (2%, at most £1): PayPal's real payout fee depends on the account and country."""
    return min(_fee(pence, "2", 0), 100)


def payout_outcome(receiver: str) -> str:
    """What the fake PayPal does with a payout, by the receiver's address: `unclaimed@…` has no PayPal account,
    `fail…@…` fails, `pending…@…` stays pending, anything else succeeds."""
    local = receiver.split("@", 1)[0].lower()
    if "unclaimed" in local:
        return "UNCLAIMED"
    if local.startswith("fail"):
        return "FAILED"
    if local.startswith("pending"):
        return "PENDING"
    return "SUCCESS"


def _payout_view(batch: dict[str, Any]) -> dict[str, Any]:
    """GET /v1/payments/payouts/{id}: the header and each item with its status (PENDING on the first read, then
    the outcome), as the Payouts v1 spec shapes them (fields in app/payment_providers.py)."""
    batch["_reads"] = batch.get("_reads", 0) + 1
    items = []
    for it in batch["_items"]:
        status = "PENDING" if batch["_reads"] < 2 and it["_outcome"] != "PENDING" else it["_outcome"]
        if it["_outcome"] == "PENDING":
            status = "PENDING"
        pence = _pence(it["payout_item"]["amount"]["value"])
        row = {
            "payout_item_id": it["payout_item_id"],
            "transaction_id": it["transaction_id"] if status in ("SUCCESS", "UNCLAIMED") else None,
            "transaction_status": status,
            "payout_item_fee": {"currency": "GBP", "value": _value(payout_fee(pence))},
            "payout_batch_id": batch["batch_header"]["payout_batch_id"],
            "payout_item": it["payout_item"],
            "links": [],
        }
        if status == "FAILED":
            row["errors"] = {"name": "RECEIVER_UNREGISTERED", "message": "Receiver is unregistered", "debug_id": "x"}
        items.append(row)
    done = all(i["transaction_status"] != "PENDING" for i in items)
    header = {**batch["batch_header"], "batch_status": "SUCCESS" if done else "PROCESSING"}
    return {"batch_header": header, "items": items, "links": []}


def _pence(value: str) -> int:
    return int(Decimal(value) * 100)


def _value(pence: int) -> str:
    return f"{pence // 100}.{pence % 100:02d}"


def _signed(pence: int) -> str:
    return f"-{_value(-pence)}" if pence < 0 else _value(pence)


def reporting_row(
    tid: str,
    when: datetime,
    *,
    code: str,
    gross: int,
    fee: int = 0,
    name: str | None = None,
    email: str | None = None,
    items: list[tuple[str, int]] | None = None,
    invoice_id: str | None = None,
    custom: str | None = None,
    subject: str | None = None,
    status: str = "S",
    currency: str = "GBP",
) -> dict[str, Any]:
    """One `transaction_details[]` entry shaped like the Transaction Search sample response (fields=all): amounts as
    signed strings, the fee negative, dates as `2014-07-11T04:03:52+0000`, the other party in `payer_info`."""
    ts = when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+0000")
    info: dict[str, Any] = {
        "paypal_account_id": "FAKEACCOUNT1",
        "transaction_id": tid,
        "transaction_event_code": code,
        "transaction_initiation_date": ts,
        "transaction_updated_date": ts,
        "transaction_amount": {"currency_code": currency, "value": _signed(gross)},
        "transaction_status": status,
        "protection_eligibility": "01",
    }
    if fee:
        info["fee_amount"] = {"currency_code": currency, "value": _signed(-abs(fee))}
    if invoice_id:
        info["invoice_id"] = invoice_id
    if custom:
        info["custom_field"] = custom
    if subject:
        info["transaction_subject"] = subject
    payer: dict[str, Any] = {"account_id": "FAKEPAYER" + tid[:4], "address_status": "Y", "payer_status": "Y"}
    if email:
        payer["email_address"] = email
    if name:
        payer["payer_name"] = {"alternate_full_name": name}
    row: dict[str, Any] = {"transaction_info": info, "payer_info": payer, "shipping_info": {}, "store_info": {}}
    if items:
        row["cart_info"] = {
            "item_details": [
                {
                    "item_name": n,
                    "item_quantity": "1",
                    "item_unit_price": {"currency_code": currency, "value": _value(p)},
                    "item_amount": {"currency_code": currency, "value": _value(p)},
                }
                for n, p in items
            ]
        }
    else:
        row["cart_info"] = {}
    return row


def sample_transactions(end: date, invoice: tuple[str, int, str] | None = None) -> list[dict[str, Any]]:
    """A small, believable month of a joinery firm's PayPal account, dated back from `end`: two sales, a payment
    naming one of the user's invoices (when given: number, amount and customer), two purchases (Screwfix, Adobe), a
    withdrawal to the bank and a payment still pending. Ids are fixed per day, so syncing twice finds the same rows.
    Fees are the made-up 2.9% + 30p above."""

    def at(days: int, hour: int = 10) -> datetime:
        d = end - timedelta(days=days)
        return datetime(d.year, d.month, d.day, hour, 15, tzinfo=UTC)

    def tid(n: int) -> str:
        return f"{end:%y%m%d}SMPL{n:04d}X"[:17]

    rows = [
        reporting_row(
            tid(1),
            at(12),
            code="T0006",
            gross=4800,
            fee=paypal_fee(4800),
            name="Amelia Clarke",
            email="amelia.clarke@example.com",
            items=[("Oak chopping board", 4800)],
            subject="Oak chopping board",
        ),
        reporting_row(
            tid(2),
            at(15),
            code="T0002",
            gross=-1997,
            name="Adobe Systems Software Ireland Ltd",
            email="billing@adobe.example",
            items=[("Creative Cloud Photography plan (monthly)", 1997)],
        ),
        reporting_row(
            tid(3),
            at(9),
            code="T0006",
            gross=-3699,
            name="Screwfix Direct Ltd",
            email="orders@screwfix.example",
            items=[("Wood screws 4.0 x 40mm (200)", 1299), ("Wood glue 1L", 2400)],
        ),
        reporting_row(
            tid(4),
            at(3),
            code="T0001",
            gross=12000,
            fee=paypal_fee(12000),
            name="Ben Hughes",
            email="ben.hughes@example.com",
            items=[("Floating shelf set, walnut", 12000)],
        ),
        reporting_row(tid(5), at(2), code="T0400", gross=-15000, subject="Withdrawal to bank account"),
        reporting_row(tid(6), at(0, 8), code="T0006", gross=2500, fee=paypal_fee(2500), name="Chloe Patel", status="P"),
    ]
    if invoice:
        number, pence, customer = invoice
        rows.append(
            reporting_row(
                tid(7),
                at(6),
                code="T0007",
                gross=pence,
                fee=paypal_fee(pence),
                name=customer,
                invoice_id=number,
                subject=f"Payment for invoice {number}",
            )
        )
    return rows


def _invoice_rows() -> list[dict[str, Any]]:
    """Payments made through fake PayPal invoices, as Transaction Search lists them (T0007, the invoice number)."""
    out = []
    for inv in FAKES.invoices.values():
        for t in inv["payments"]["transactions"]:
            day = date.fromisoformat(str(t["payment_date"])[:10])
            gross = _pence(t["amount"]["value"])
            out.append(
                reporting_row(
                    t["payment_id"],
                    datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC),
                    code="T0007",
                    gross=gross,
                    fee=paypal_fee(gross),
                    name=((inv.get("primary_recipients") or [{}])[0].get("billing_info") or {})
                    .get("name", {})
                    .get("full_name"),
                    invoice_id=inv["detail"]["invoice_number"],
                    subject=inv["detail"].get("note"),
                )
            )
    return out


def _reporting(request: httpx.Request) -> httpx.Response:
    q = request.url.params
    start = payment_providers.paypal_parse_time(q.get("start_date"))
    end = payment_providers.paypal_parse_time(q.get("end_date"))
    if start is None or end is None or end <= start:
        return _paypal_error(400, "INVALID_REQUEST", "start_date and end_date are required")
    if end - start > timedelta(days=31):
        return _paypal_error(400, "INVALID_REQUEST", "Date range is greater than 31 days")
    try:
        size, page = int(q.get("page_size", "100")), int(q.get("page", "1"))
    except ValueError:
        return _paypal_error(400, "INVALID_REQUEST", "page")
    if not 1 <= size <= 500 or page < 1:
        return _paypal_error(400, "INVALID_REQUEST", "page_size is 1 to 500")
    if FAKES.reporting is None:
        FAKES.reporting = sample_transactions(end.date())
    rows = []
    for row in [*FAKES.reporting, *_invoice_rows()]:
        when = payment_providers.paypal_parse_time(row["transaction_info"]["transaction_initiation_date"])
        if when is not None and start <= when <= end:
            rows.append(row)
    rows.sort(key=lambda r: r["transaction_info"]["transaction_initiation_date"])
    pages = max(1, -(-len(rows) // size))
    return _json(
        200,
        {
            "transaction_details": rows[(page - 1) * size : page * size],
            "account_number": "FAKEACCOUNT1",
            "start_date": q.get("start_date"),
            "end_date": q.get("end_date"),
            "last_refreshed_datetime": payment_providers.paypal_time(datetime.now(UTC)),
            "page": page,
            "total_items": len(rows),
            "total_pages": pages,
            "links": [],
        },
    )


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


QTY_RE = re.compile(r"\d+(\.\d{1,5})?")


def _invoice_problem(body: dict[str, Any]) -> str | None:
    """The Invoicing v2 (schema 2.12) rules the fake checks: field lengths, item shape, invoicer shape."""
    detail = body.get("detail") or {}
    for key, most in (("note", 4000), ("terms_and_conditions", 4000), ("memo", 500), ("reference", 120)):
        if len(str(detail.get(key) or "")) > most:
            return f"detail.{key} is longer than {most}"
    items = body.get("items") or []
    if not items or len(items) > 100:
        return "items: 1 to 100"
    for it in items:
        if not it.get("name") or len(it["name"]) > 200 or not QTY_RE.fullmatch(str(it.get("quantity"))):
            return "item name or quantity"
        if (it.get("unit_amount") or {}).get("currency_code") != "GBP":
            return "currency"
        tax = it.get("tax")
        if tax is not None and (not tax.get("name") or not 0 <= Decimal(str(tax.get("percent"))) <= 100):
            return "item tax needs name and percent 0-100"
        if it.get("unit_of_measure", "QUANTITY") not in ("QUANTITY", "HOURS", "AMOUNT"):
            return "unit_of_measure"
    inv = body.get("invoicer")
    if inv is not None:
        if not inv.get("business_name") or len(inv["business_name"]) > 300:
            return "invoicer.business_name"
        if "email_address" in inv:
            return "invoicer.email_address must be listed in the user's PayPal profile"
        if "address" in inv and not inv["address"].get("country_code"):
            return "invoicer.address.country_code is required"
        for ph in inv.get("phones") or []:
            if not (
                re.fullmatch(r"\d{1,3}", ph.get("country_code", ""))
                and re.fullmatch(r"\d{1,14}", ph.get("national_number", ""))
            ):
                return "invoicer.phones: E.164 digits"
            if ph.get("phone_type") not in ("FAX", "HOME", "MOBILE", "OTHER", "PAGER"):
                return "invoicer.phones.phone_type"
        if len(inv.get("additional_notes") or "") > 400:
            return "invoicer.additional_notes"
    return None


def _invoice_total(items: list[dict[str, Any]]) -> int:
    """PayPal's total as the fake works it out: per item, quantity × unit price, plus its tax, each rounded half up
    to the penny (how PayPal really rounds is not documented). `FAKES.paypal_tax_on_total` rounds the tax once on
    the whole instead, to test the fall-back to one line."""
    nets: list[tuple[Decimal, Decimal]] = []
    for it in items:
        net = Decimal(str(it["quantity"])) * Decimal(it["unit_amount"]["value"]) * 100
        pct = Decimal(str((it.get("tax") or {}).get("percent", "0")))
        nets.append((net, pct))
    whole = Decimal("1")
    if FAKES.paypal_tax_on_total:
        net_sum = sum((n.quantize(whole, ROUND_HALF_UP) for n, _ in nets), Decimal(0))
        tax = sum((n * p / 100 for n, p in nets), Decimal(0)).quantize(whole, ROUND_HALF_UP)
        return int(net_sum + tax)
    total = Decimal(0)
    for net, pct in nets:
        n = net.quantize(whole, ROUND_HALF_UP)
        total += n + (n * pct / 100).quantize(whole, ROUND_HALF_UP)
    return int(total)


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
    multipart = request.headers.get("Content-Type", "").startswith("multipart/")
    body = json.loads(request.content) if request.content and not multipart else {}
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
    if path.startswith(
        ("/v2/invoicing/", "/v2/payments/", "/v1/reporting/", "/v1/customer/disputes", "/v1/payments/")
    ) and (merchant is None or merchant not in FAKES.merchants):
        return _paypal_error(403, "NOT_AUTHORIZED", "Authorization failed due to insufficient permissions.")
    if path == "/v1/reporting/transactions" and method == "GET":
        return _reporting(request)
    if path == "/v2/invoicing/invoices" and method == "POST":
        number = body["detail"]["invoice_number"]
        if any(i["detail"]["invoice_number"] == number and i["_merchant"] == merchant for i in FAKES.invoices.values()):
            return _paypal_error(422, "UNPROCESSABLE_ENTITY", "Invoice number already exists")
        problem = _invoice_problem(body)
        if problem:
            return _paypal_error(400, "INVALID_REQUEST", problem)
        iid = "INV2-" + "-".join(secrets.token_hex(2).upper() for _ in range(4))
        amount = {"currency_code": "GBP", "value": _value(_invoice_total(body["items"]))}
        FAKES.invoices[iid] = {
            "id": iid,
            "status": "DRAFT",
            "detail": {**body["detail"], "metadata": {"create_time": "2026-10-27T09:00:00Z"}},
            "invoicer": body.get("invoicer", {}),
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
        if rest[1:] == ["remind"] and method == "POST":  # PayPal emails the payer; 204, no body
            if inv["status"] not in ("UNPAID", "SENT", "PARTIALLY_PAID"):
                return _paypal_error(422, "UNPROCESSABLE_ENTITY", "Invoice is not in a remindable state.")
            inv["reminders"] = int(inv.get("reminders", 0)) + 1
            return httpx.Response(204)
    if path.startswith("/v1/customer/disputes"):
        return _disputes(request, merchant, path, method)
    if path == "/v1/payments/payouts" and method == "POST":
        if FAKES.payout_fail_next > 0:
            FAKES.payout_fail_next -= 1
            return _paypal_error(503, "SERVICE_UNAVAILABLE", "Service Unavailable")
        sbh = body.get("sender_batch_header") or {}
        sid = sbh.get("sender_batch_id")
        items = body.get("items") or []
        if not sid or not items or any(i.get("recipient_type") != "EMAIL" for i in items):
            return _paypal_error(400, "VALIDATION_ERROR", "Invalid request - see details")
        if any(i["amount"].get("currency") != "GBP" for i in items):
            return _paypal_error(422, "UNPROCESSABLE_ENTITY", "currency")
        if sid in FAKES.payouts:  # the spec: a sender_batch_id used in the last 30 days is refused, with a link
            old = FAKES.payouts[sid]["batch_header"]["payout_batch_id"]
            return _json(
                400,
                {
                    "name": "USER_BUSINESS_ERROR",
                    "message": f"Batch with given sender_batch_id already exists: {sid}",
                    "debug_id": secrets.token_hex(6),
                    "links": [
                        {
                            "href": f"https://api-m.sandbox.paypal.com/v1/payments/payouts/{old}",
                            "rel": "self",
                            "method": "GET",
                        }
                    ],
                },
            )
        bid = secrets.token_hex(6).upper()
        header = {
            "payout_batch_id": bid,
            "batch_status": "PENDING",
            "sender_batch_header": {"sender_batch_id": sid, "email_subject": sbh.get("email_subject")},
        }
        FAKES.payouts[sid] = {
            "batch_header": header,
            "_merchant": merchant,
            "_items": [
                {
                    "payout_item_id": secrets.token_hex(7).upper(),
                    "transaction_id": secrets.token_hex(8).upper(),
                    "payout_item": {
                        k: i.get(k) for k in ("recipient_type", "amount", "note", "receiver", "sender_item_id")
                    },
                    "_outcome": payout_outcome(str(i.get("receiver", ""))),
                }
                for i in items
            ],
        }
        link = {"href": f"https://api-m.sandbox.paypal.com/v1/payments/payouts/{bid}", "rel": "self", "method": "GET"}
        return _json(201, {"batch_header": header, "links": [link]})
    if path.startswith("/v1/payments/payouts/") and method == "GET":
        bid = path.rsplit("/", 1)[1]
        batch = next((b for b in FAKES.payouts.values() if b["batch_header"]["payout_batch_id"] == bid), None)
        if batch is None or batch["_merchant"] != merchant:
            return _paypal_error(404, "RESOURCE_NOT_FOUND", "The specified resource does not exist.")
        return _json(200, _payout_view(batch))
    if path.startswith("/v2/payments/captures/") and method == "GET":
        cap = FAKES.captures.get(path.rsplit("/", 1)[1])
        if cap is None or not FAKES.paypal_fee_known:
            return _paypal_error(404, "RESOURCE_NOT_FOUND", "The specified resource does not exist.")
        return _json(200, cap)
    return _paypal_error(404, "NOT_FOUND", f"{method} {path}")


MAX_EVIDENCE_BYTES = 10 * 1024 * 1024  # UNVERIFIED: the per-document limit as remembered from PayPal's guide


def _multipart(request: httpx.Request) -> list[tuple[dict[str, str], bytes]]:
    """The parts of a multipart/form-data body: (Content-Disposition params + content type, bytes)."""
    raw = b"Content-Type: " + request.headers["Content-Type"].encode() + b"\r\n\r\n" + request.content
    msg = BytesParser(policy=default).parsebytes(raw)
    out = []
    for part in msg.iter_parts():
        params = dict(part.get_params(header="content-disposition") or [])
        params["_type"] = part.get_content_type()
        out.append((params, part.get_payload(decode=True) or b""))
    return out


def _disputes(request: httpx.Request, merchant: str | None, path: str, method: str) -> httpx.Response:
    mine = {k: d for k, d in FAKES.disputes.items() if d["_merchant"] == merchant}
    if path == "/v1/customer/disputes" and method == "GET":
        size = int(request.url.params.get("page_size", "10"))
        if not 1 <= size <= 50:
            return _paypal_error(400, "INVALID_REQUEST", "page_size")
        items = [dispute_summary(_public(d)) for d in mine.values()][:size]
        return _json(200, {"items": items, "links": []})
    rest = path.removeprefix("/v1/customer/disputes/").split("/")
    d = mine.get(rest[0])
    if d is None:
        return _paypal_error(404, "RESOURCE_NOT_FOUND", "The specified resource does not exist.")
    if len(rest) == 1 and method == "GET":
        return _json(200, _public(d))
    action = rest[1] if len(rest) == 2 and method == "POST" else ""
    if action == "provide-evidence":
        if d["status"] != "WAITING_FOR_SELLER_RESPONSE":
            return _paypal_error(422, "UNPROCESSABLE_ENTITY", "Evidence can only be provided while waiting for seller")
        if not request.headers.get("Content-Type", "").startswith("multipart/form-data"):
            return _paypal_error(415, "UNSUPPORTED_MEDIA_TYPE", "multipart/form-data")
        parts = _multipart(request)
        inputs = [b for p, b in parts if p.get("name") == "input" and p["_type"] == "application/json"]
        files = [(p, b) for p, b in parts if p.get("name") == "evidence-file"]
        if len(inputs) != 1:
            return _paypal_error(400, "MISSING_OR_INVALID_REQUEST_BODY", "input")
        evidences = json.loads(inputs[0]).get("evidences")
        if not isinstance(evidences, list) or not evidences:
            return _paypal_error(400, "MISSING_OR_INVALID_REQUEST_BODY", "evidences")
        for ev in evidences:
            if ev.get("evidence_type") not in EVIDENCE_TYPES or len(ev.get("notes") or "") > 2000:
                return _paypal_error(400, "INVALID_REQUEST", "evidence_type or notes")
        for p, b in files:
            if p["_type"] != "application/pdf" or not b.startswith(b"%PDF") or len(b) > MAX_EVIDENCE_BYTES:
                return _paypal_error(400, "INVALID_REQUEST", "evidence file")
        FAKES.evidence[d["dispute_id"]] = [
            {"evidences": evidences, "files": [(p.get("filename"), len(b)) for p, b in files]}
        ]
        d.update(status="UNDER_REVIEW", dispute_state="UNDER_PAYPAL_REVIEW", links=d["links"][:1])
        return _json(200, {"links": [{"href": d["links"][0]["href"], "rel": "self", "method": "GET"}]})
    if action == "send-message":
        if d.get("dispute_life_cycle_stage") != "INQUIRY":
            return _paypal_error(422, "UNPROCESSABLE_ENTITY", "Messages can only be sent in the INQUIRY stage")
        msg = str(json.loads(request.content).get("message") or "")
        d["messages"].append({"posted_by": "SELLER", "time_posted": "2026-11-11T10:00:00.000Z", "content": msg})
        return _json(200, {"links": []})
    if action == "accept-claim":
        FAKES.resolve_dispute(d["dispute_id"], buyer_wins=True)
        d["dispute_outcome"]["outcome_code"] = "RESOLVED_BUYER_FAVOUR"
        return _json(200, {"links": []})
    return _paypal_error(404, "NOT_FOUND", f"{method} {path}")


EVIDENCE_TYPES = frozenset(
    {
        "PROOF_OF_FULFILLMENT",
        "PROOF_OF_REFUND",
        "PROOF_OF_RECEIPT_COPY",
        "COPY_OF_CONTRACT",
        "OTHER",
        "ITEM_DESCRIPTION",
    }
)  # a few of the schema's evidence_type enum; the code only sends these


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


@router.post("/paypal/dispute/{iid}")
async def paypal_open_dispute(iid: str, reason: str = "MERCHANDISE_OR_SERVICE_NOT_RECEIVED") -> dict[str, str]:
    """The payer opens a dispute on the last payment of a fake PayPal invoice (for the end-to-end tests)."""
    inv = FAKES.invoices.get(iid)
    if inv is None or not inv["payments"]["transactions"]:
        raise HTTPException(404, "no such paid invoice")
    return {"dispute_id": FAKES.open_dispute(iid, reason=reason)}


@router.post("/paypal/dispute/{did}/resolve")
async def paypal_resolve_dispute(did: str, buyer_wins: bool = True) -> dict[str, str]:
    if did not in FAKES.disputes:
        raise HTTPException(404, "no such dispute")
    FAKES.resolve_dispute(did, buyer_wins=buyer_wins)
    return {"status": "RESOLVED"}


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
    return HTMLResponse(PAGE.format(title=f"Invoice {inv['detail']['invoice_number']}", who="PayPal", body=body))


@router.post("/paypal/pay/{iid}", response_class=HTMLResponse)
async def paypal_pay(iid: str) -> HTMLResponse:
    inv = FAKES.invoices.get(iid)
    if inv is None or inv["status"] in ("PAID", "CANCELLED"):
        raise HTTPException(404, "no such open invoice")
    FAKES.pay_paypal(iid)
    return HTMLResponse(PAGE.format(title="Payment received", who="PayPal", body="<p>Thank you.</p>"))
