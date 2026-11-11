"""What the user has set up, read from their own books: live bank feeds, marketplace connections, Autopilot rules.

These limits are about things that exist, not a monthly count, so they are counted where they live (the user's
storage) when one more is added, and for the usage panel on GET /account. Users: Accnomos has no team members yet
(accountant access is free and extra), so it is always 1, the owner.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.books import Books

log = logging.getLogger("accnomos.billing")
TIMEOUT_S = 6.0


async def bank_feeds(books: Books) -> int:
    """Connections that are live or can be renewed; one waiting for the user to go back through the bank still
    counts (renewing it replaces it, see `bank_feed_room`)."""
    from app import bank_feeds as bf

    return len((await bf.load_feeds(books)).connections)


async def bank_feeds_needing_reauth(books: Books) -> int:
    from app import bank_feeds as bf

    return sum(1 for c in (await bf.load_feeds(books)).connections if c.needs_reauth)


async def marketplaces(books: Books) -> int:
    from app import ebay_sync

    return 1 if (await ebay_sync.load(books)).connection is not None else 0


async def autopilot_rules(books: Books) -> int:
    from app import autopilot

    return len(await autopilot.load_rules(books))


async def read_all(books: Books) -> dict[str, int | None]:
    async def safe(fn: Any) -> int | None:
        try:
            return await asyncio.wait_for(fn(books), TIMEOUT_S)
        except Exception:  # noqa: BLE001  the usage panel shows "?" rather than failing /account
            log.info("gauge %s not read", getattr(fn, "__name__", fn), exc_info=True)
            return None

    feeds, markets, rules = await asyncio.gather(safe(bank_feeds), safe(marketplaces), safe(autopilot_rules))
    return {"bank_feeds": feeds, "marketplaces": markets, "autopilot_rules": rules, "users": 1}


async def bank_feed_room(books: Books) -> None:
    """Before starting a bank connection: refuse when the plan's live bank feeds are all in use. A connection that
    needs the user to go back through their bank does not block (reconnecting replaces it)."""
    from app.billing import service

    if service.current() is None:
        return
    in_use = await bank_feeds(books) - await bank_feeds_needing_reauth(books)
    service.require_room("bank_feeds", in_use)


async def marketplace_room(books: Books) -> None:
    """Before connecting eBay: reconnecting the one already connected is always allowed."""
    from app.billing import service

    if service.current() is None:
        return
    if await marketplaces(books):
        return
    service.require_room("marketplaces", 0)
