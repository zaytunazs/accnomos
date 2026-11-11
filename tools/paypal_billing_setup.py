"""Create Accnomos's PayPal product and the six plan prices in the PayPal SANDBOX, then print the env lines.

Uses the runtime's own code (services/runtime/app/billing/paypal_api.py), so the requests are the ones the tests
check against the fakes. Sandbox only: refused when PAYPAL_BASE points at PayPal's live API.

    PAYPAL_CLIENT_ID=… PAYPAL_CLIENT_SECRET=… uv run python tools/paypal_billing_setup.py

Prices come from the plans seed (Starter £10, Comprehensive £20, Ultimate £50 a month; yearly = 2 months free),
ex VAT, with PAYPAL_VAT_PERCENT (20) added on top by PayPal. Each request carries a PayPal-Request-Id, so running it
twice within PayPal's 72 hours returns the same ids instead of new ones. Put the printed PAYPAL_PRODUCT_ID and
PAYPAL_PLAN_* lines into the server's .env (they are ids, not secrets). Then add a webhook for
https://<api>/billing/paypal/webhook in the PayPal developer dashboard with the events BILLING.SUBSCRIPTION.ACTIVATED,
UPDATED, CANCELLED, EXPIRED, SUSPENDED, PAYMENT.FAILED, PAYMENT.SALE.COMPLETED and CHECKOUT.ORDER.APPROVED, and set
PAYPAL_WEBHOOK_ID to its id.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "runtime"))

from app.billing import paypal_api  # noqa: E402
from app.billing.plans import DEFAULT_PLANS  # noqa: E402


async def main() -> int:
    cfg = paypal_api.settings()
    if not cfg.configured:
        print("Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET (the sandbox REST app) first.", file=sys.stderr)
        return 2
    if not cfg.sandbox:
        print(f"Refused: PAYPAL_BASE is {cfg.base}, not the sandbox ({paypal_api.SANDBOX}).", file=sys.stderr)
        return 2
    api = paypal_api.PayPalBilling(cfg)
    product = await api.create_product()
    lines = [f"PAYPAL_PRODUCT_ID={product}"]
    for plan in DEFAULT_PLANS:
        for interval in ("month", "year"):
            pence = int(plan[f"price_{interval}_pence"])
            plan_id = await api.create_plan(
                product=product, plan_code=plan["code"], name=plan["name"], interval=interval, pence=pence
            )
            lines.append(f"PAYPAL_PLAN_{plan['code'].upper()}_{interval.upper()}={plan_id}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
