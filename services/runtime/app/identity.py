"""Who a request really is: the Microsoft Graph `/me` of its `X-Graph-Token` (for `X-Account-Kind: google`, Google's
OpenID Connect userinfo, https://openidconnect.googleapis.com/v1/userinfo), never a header the client wrote.

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


def kind(request: Request) -> str | None:
    """`"google"` for a Google token (app/accounts.py), else None: Microsoft Graph, personal or work."""
    return "google" if (request.headers.get("X-Account-Kind") or "").strip().lower() == "google" else None


async def verified_identity(token: str, hint: str | None = None, kind: str | None = None) -> Identity:
    """Graph `/me` for `token` (Google's OpenID Connect userinfo when `kind` is "google"). 401 when the provider
    refuses it (or there is none); other failures are the usual 502. `hint` (the request's `X-User`) is read in test
    mode only, to choose which fake user the fakes answer as."""
    token = token.strip().removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="X-Graph-Token header required")
    google = kind == "google"
    if is_test_mode() and not google:  # per-tenant fakes and a different X-User per call: nothing to remember
        provider = await sharing.sharing_for(token, hint)
        return await provider.whoami()
    key = user_cache_key(token, "identity:google" if google else "identity")
    hit = _CACHE.get(key)
    if hit is not None and hit[0] > time.monotonic():
        _CACHE.move_to_end(key)
        return hit[1]
    if google:
        from accnomos_connectors.google_drive import GoogleIdentity

        provider = GoogleIdentity(token)
    else:
        provider = await sharing.sharing_for(token)
    try:
        me = await provider.whoami()
    except GraphError as exc:
        if exc.status in (401, 403):
            who = "Google" if google else "Microsoft"
            raise HTTPException(status_code=401, detail=f"{who} did not accept this sign-in") from exc
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
    return await verified_identity(bearer(request), request.headers.get("X-User"), kind(request))
