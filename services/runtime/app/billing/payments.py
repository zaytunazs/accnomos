"""Which payment provider takes money for Accnomos plans: `PAYMENTS_PROVIDER` (`none` by default, or `stripe`).

With `none` the plans, the free trial and promo codes (free months) all work, and nothing can be bought: checkout,
the billing portal and top-ups answer 503, and `GET /account` reports `payments_provider: "none"` so the apps show no
buy buttons and no provider's name. A provider is a module next to `stripe_api.py` (checkout for a plan and a top-up,
a self-service portal, a signed webhook); `stripe` is the one there is. Another one slots in by adding its name to
`PROVIDERS` and its module, and pointing the routes at it where `provider()` says so.

Not the same as the invoice payment links (app/online_payments.py), which pay the user's own Stripe or PayPal.
"""

from __future__ import annotations

import os
from typing import Literal

Provider = Literal["none", "stripe"]
PROVIDERS: tuple[Provider, ...] = ("none", "stripe")


def provider() -> Provider:
    """The configured provider; anything unknown counts as `none`, so a typo never opens payments by accident."""
    value = os.getenv("PAYMENTS_PROVIDER", "").strip().lower()
    return value if value in PROVIDERS else "none"  # type: ignore[return-value]


def taking_payments() -> bool:
    return provider() != "none"
