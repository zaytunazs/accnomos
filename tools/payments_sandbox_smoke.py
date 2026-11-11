"""Smoke test of payment links against the REAL PayPal sandbox and Stripe test mode, in direct mode.

Uses the same code the runtime uses (app/payment_providers.py), not the fakes. Nothing live: PayPal's sandbox host
and a Stripe `sk_test_` key only.

    PAYPAL_CLIENT_ID=… PAYPAL_CLIENT_SECRET=… uv run python tools/payments_sandbox_smoke.py paypal
    STRIPE_SECRET_KEY=sk_test_… uv run python tools/payments_sandbox_smoke.py stripe

PayPal: gets a token, creates a £1.20 invoice on the REST app's own sandbox business account, sends it (no email),
prints the customer's pay link, then reads it back. Pay it with a sandbox *personal* account, run again with
`paypal-check INV2-…` to see the payment and fee as Accnomos reads them.
Stripe: reads the key's own account, makes a one-use £1.20 Payment Link, prints it (pay with card 4242 4242 4242 4242).
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "runtime"))

from app.payment_providers import (  # noqa: E402
    PAYPAL_SANDBOX,
    PayPalApi,
    PayPalConfig,
    StripeApi,
    StripeConfig,
    client,
    pence_from_paypal,
    recipient_view_url,
)

DIRECT = "SANDBOXDIRECT"


def _paypal() -> PayPalConfig:
    return PayPalConfig(
        client_id=os.environ["PAYPAL_CLIENT_ID"],
        client_secret=os.environ["PAYPAL_CLIENT_SECRET"],
        partner_merchant_id="",
        attribution_id="",
        return_url="",
        base=PAYPAL_SANDBOX,
        direct=True,
    )


async def paypal() -> None:
    async with client() as http:
        api = PayPalApi(_paypal(), http)
        await api.token()
        print("PayPal sandbox token: ok")
        ref = secrets.token_hex(8)
        inv = await api.create_invoice(
            DIRECT,
            number=f"SMOKE-{ref[:4].upper()}",
            amount_pence=120,
            ref=ref,
            customer_name="Sandbox Customer",
            customer_email=None,
            request_id=f"accnomos-smoke-{ref}",
        )
        print("Invoice:", inv.get("id"), inv.get("status"))
        print("Pay link:", recipient_view_url(inv))


async def paypal_check(invoice_id: str) -> None:
    async with client() as http:
        api = PayPalApi(_paypal(), http)
        inv = await api.invoice(DIRECT, invoice_id)
        print("Status:", inv.get("status"))
        for t in (inv.get("payments") or {}).get("transactions", []):
            print("Payment:", t.get("payment_id"), pence_from_paypal(t.get("amount")), "p", t.get("payment_date"))
            try:
                cap = await api.capture(DIRECT, str(t.get("payment_id")))
                fee = (cap.get("seller_receivable_breakdown") or {}).get("paypal_fee")
                print("  fee:", pence_from_paypal(fee), "p")
            except Exception as exc:  # noqa: BLE001  documented as unverified: the user types the fee then
                print("  fee not readable from the capture:", exc)


async def stripe() -> None:
    cfg = StripeConfig(secret_key=os.environ["STRIPE_SECRET_KEY"], client_id="", redirect_uri="", direct=True)
    if not cfg.test_mode:
        sys.exit("Use a Stripe test key (sk_test_…)")
    async with client() as http:
        api = StripeApi(cfg, http)
        own = await api.own_account()
        print("Stripe test account:", own.get("id"))
        ref = secrets.token_hex(8)
        link = await api.create_link(
            str(own["id"]), amount_pence=120, invoice_number="SMOKE", ref=ref, idempotency_key=f"accnomos-smoke-{ref}"
        )
        print("Payment link:", link.get("url"))
        print(json.dumps({"id": link.get("id")}))


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    if what == "paypal":
        asyncio.run(paypal())
    elif what == "paypal-check" and len(sys.argv) > 2:
        asyncio.run(paypal_check(sys.argv[2]))
    elif what == "stripe":
        asyncio.run(stripe())
    else:
        sys.exit(__doc__)
