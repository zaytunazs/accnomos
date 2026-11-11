"""Which payment provider takes money for Accnomos plans: `PAYMENTS_PROVIDER` (`none` by default, `paypal` (the
owner's choice, 11 Nov 2026: PayPal Subscriptions, sandbox first) or `stripe` (kept in code, on hold)).

With `none` the plans, the free trial and promo codes (free months) all work, and nothing can be bought: checkout,
the billing portal and top-ups answer 503, and `GET /account` reports `payments_provider: "none"` so the apps show no
buy buttons and no provider's name. A provider is a module next to `stripe_api.py` (checkout for a plan and a top-up,
a self-service portal or its equivalent, a verified webhook): `stripe_api.py` and `paypal_api.py`. The routes pick the
client with `routes.provider_or_503()`. Another one slots in by adding its name to `PROVIDERS` and its module, and
pointing the routes at it where `provider()` says so.

Not the same as the invoice payment links (app/online_payments.py), which pay the user's own Stripe or PayPal.
"""

from __future__ import annotations

import os
from typing import Literal

Provider = Literal["none", "stripe", "paypal"]
PROVIDERS: tuple[Provider, ...] = ("none", "stripe", "paypal")


def provider() -> Provider:
    """The configured provider; anything unknown counts as `none`, so a typo never opens payments by accident."""
    value = os.getenv("PAYMENTS_PROVIDER", "").strip().lower()
    return value if value in PROVIDERS else "none"  # type: ignore[return-value]


def taking_payments() -> bool:
    return provider() != "none"
