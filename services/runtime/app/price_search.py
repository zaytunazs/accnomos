"""Live price search: a provider interface, chosen by the PRICE_SEARCH_PROVIDER environment variable. Off by default.

    PRICE_SEARCH_PROVIDER=        (or `none`)  off: Cheaper options and the shopping list use the user's own books only,
                                              and the app says "Live price search is off".
    PRICE_SEARCH_PROVIDER=fake                the deterministic FakePriceSearch below. Test mode only
                                              (ACCNOMOS_TEST_MODE=1); refused, and so off, anywhere else.
    anything else                             not known to this version: off, with a warning in the log.

No real search API is wired in this version, and nothing here scrapes or calls a shopping site. A provider added
later implements PriceSearchProvider and is registered in PROVIDERS; docs/PRODUCTION.md says how it is switched on.

What a provider returns is a list of Offers: supplier, title, unit price, pack size, URL and when it was retrieved.
Code does the rest (app/prices.py): it reads the size and pack from the title the same way it reads a receipt line,
works out the price per metre / kg / litre / item, and keeps every live offer labelled with its source and time,
apart from the prices in the user's own books. A provider that fails or is slow costs the page nothing but its
offers: the history-only results are returned with a note.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, Field

from app.ai.config import is_test_mode

log = logging.getLogger(__name__)

ENV = "PRICE_SEARCH_PROVIDER"
TIMEOUT_S = 8.0  # one search; the page goes on without live offers after that
OFFERS_MAX = 5  # per search
SEARCHES_MAX = 8  # per Cheaper options page: the groups with the most spend first
OFF_NOTE = "Live price search is off: prices here come only from receipts and bills in your books."


class Offer(BaseModel):
    """One price a provider found. Money in pence; `unit_price_pence` is for one unit as sold (a pack of 6 is one)."""

    supplier: str = Field(max_length=200)
    title: str = Field(max_length=300)
    unit_price_pence: int = Field(gt=0)
    pack: int = Field(default=1, ge=1, le=10_000)
    url: str = Field(max_length=2000)
    retrieved_at: datetime
    source: str = Field(max_length=60)  # the provider's name, shown on every offer


class PriceSearchProvider(Protocol):
    """A live price search. `query` is the item in the user's words; `specs` the sizes code read from it
    (width_mm, length_m, weight_kg, volume_l, colour, pack; any may be None)."""

    name: str

    async def search(self, query: str, specs: dict[str, object]) -> list[Offer]: ...


class FakePriceSearch:
    """Deterministic offers for the tests and test mode. Never used with real books (provider_from_env refuses it
    outside test mode). Every offer says it is a test fake, on a .invalid URL."""

    name = "Test fake"

    async def search(self, query: str, specs: dict[str, object]) -> list[Offer]:
        q = query.lower()
        at = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
        if "tape" in q:
            return [
                Offer(
                    supplier="Example Packaging (test fake)",
                    title="Packing tape clear 48mm x 66m, pack of 36",
                    unit_price_pence=4140,
                    pack=36,
                    url="https://shop.example.invalid/tape-48-66-x36",
                    retrieved_at=at,
                    source=self.name,
                ),
                Offer(
                    supplier="Example Wholesale (test fake)",
                    title="Brown packing tape 50mm x 66m",
                    unit_price_pence=199,
                    pack=1,
                    url="https://wholesale.example.invalid/tape-50-66",
                    retrieved_at=at,
                    source=self.name,
                ),
            ]
        return []


PROVIDERS: dict[str, Callable[[], PriceSearchProvider]] = {"fake": FakePriceSearch}


def provider_from_env() -> PriceSearchProvider | None:
    """The configured provider, or None (off). Read on every call, so a test can change the variable."""
    name = os.getenv(ENV, "").strip().lower()
    if name in ("", "none", "off"):
        return None
    if name == "fake" and not is_test_mode():
        log.warning("%s=fake is for tests only; live price search stays off", ENV)
        return None
    cls = PROVIDERS.get(name)
    if cls is None:
        log.warning("%s=%r is not a provider this version knows; live price search stays off", ENV, name)
        return None
    return cls()


class SearchStatus(BaseModel):
    enabled: bool
    provider: str | None
    note: str


def status(provider: PriceSearchProvider | None = None, error: str | None = None) -> SearchStatus:
    if provider is None:
        return SearchStatus(enabled=False, provider=None, note=OFF_NOTE)
    note = f"Live prices from {provider.name}, shown apart from your own history with where and when each was found."
    return SearchStatus(enabled=True, provider=provider.name, note=f"{note} {error}" if error else note)


async def search(provider: PriceSearchProvider, query: str, specs: dict[str, object]) -> tuple[list[Offer], str | None]:
    """At most OFFERS_MAX offers, or ([], why) when the provider fails or takes longer than TIMEOUT_S."""
    try:
        found = await asyncio.wait_for(provider.search(query, specs), TIMEOUT_S)
    except TimeoutError:
        return [], f"{provider.name} did not answer within {TIMEOUT_S:.0f} s."
    except Exception as exc:  # noqa: BLE001  a provider's trouble must never break the page
        log.warning("price search failed: %s", type(exc).__name__)
        return [], f"{provider.name} could not be searched just now."
    return [o for o in found if isinstance(o, Offer)][:OFFERS_MAX], None
