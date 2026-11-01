"""Who a request really is: the Microsoft Graph `/me` of its `X-Graph-Token`, never a header the client wrote.

`X-Graph-Token` is only a credential once Graph has accepted it, so anything that must know the caller (the audit
actor, `/lookup/*`, `/extract`) goes through `verified_identity`. The answer is remembered by token hash for
`TTL_SECONDS` (no token is kept); a failure is never remembered. In test mode (`ACCNOMOS_TEST_MODE=1`) the fake
sharing world answers instead, as the signed-in test user or as `X-User`, and Graph is never called.
"""

from __future__ import annotations

import time
from collections import OrderedDict

from fastapi import HTTPException, Request

from accnomos_connectors.base import Identity
from accnomos_connectors.msgraph import GraphError
from app import sharing
from app.ai.config import is_test_mode
from app.cache import user_cache_key

TTL_SECONDS = 600
_MAX = 512
_CACHE: OrderedDict[str, tuple[float, Identity]] = OrderedDict()  # sha256 of the token -> (expires, /me)


def bearer(request: Request) -> str:
    """The `X-Graph-Token` value without a `Bearer ` prefix; "" when absent."""
    return request.headers.get("X-Graph-Token", "").strip().removeprefix("Bearer ").strip()


def reset() -> None:
    _CACHE.clear()


async def verified_identity(token: str, hint: str | None = None) -> Identity:
    """Graph `/me` for `token`. 401 when Graph refuses it (or there is none); other Graph failures are the usual 502.
    `hint` (the request's `X-User`) is read in test mode only, to choose which fake user the fakes answer as."""
    token = token.strip().removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="X-Graph-Token header required")
    if is_test_mode():  # per-tenant fakes and a different X-User per call: nothing to remember
        provider = await sharing.sharing_for(token, hint)
        return await provider.whoami()
    key = user_cache_key(token, "identity")
    hit = _CACHE.get(key)
    if hit is not None and hit[0] > time.monotonic():
        _CACHE.move_to_end(key)
        return hit[1]
    provider = await sharing.sharing_for(token)
    try:
        me = await provider.whoami()
    except GraphError as exc:
        if exc.status in (401, 403):
            raise HTTPException(status_code=401, detail="Microsoft did not accept this sign-in") from exc
        raise
    finally:
        await provider.aclose()  # type: ignore[attr-defined]
    _CACHE[key] = (time.monotonic() + TTL_SECONDS, me)
    _CACHE.move_to_end(key)
    while len(_CACHE) > _MAX:
        _CACHE.popitem(last=False)
    return me


async def signed_in_identity(request: Request) -> Identity:
    """Dependency: the verified identity of this request's `X-Graph-Token` (401 without one)."""
    return await verified_identity(bearer(request), request.headers.get("X-User"))
