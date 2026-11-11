"""Plan limits and read-only accounts at the door (pure ASGI, inside the security middleware).

For a signed-in request (a verified `X-Graph-Token`) when billing is configured:

1. the caller's account is found or registered (app/billing/service.py `ensure_account`);
2. a `trial_ended` or `cancelled` account gets 402 `{code: "read_only"}` for any write except billing, account,
   settings, exports, disconnecting and taking access back (`WRITE_OK`);
3. an action whose monthly allowance is used up is refused before it starts: 402 `{code: "plan_limit"}`
   (documents for the scan and upload routes, Ask questions, invoices and quotes);
4. the request runs with the usage meter set, so the document reader charges each AI read (app/pipeline.py) and the
   bank-feed, eBay and Autopilot code can check what is set up;
5. after a 2xx, Ask questions and invoices are counted and the product events for the route are recorded; a 5xx is
   recorded as an `api_error` event for the route (no account id, no message).

Not metered: requests without a Graph token, demo sessions, an accountant working in a client's books
(`X-Books-Drive-Id`: the books, and so the plan, are the client's), and the billing/admin/analytics routes
themselves. If the registry cannot be reached the request goes ahead unmetered (logged): availability of people's
books matters more than a count.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from fastapi import HTTPException
from starlette.datastructures import Headers

from app.billing import registry as R
from app.billing import service as S

log = logging.getLogger("accnomos.billing")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

WRITES = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Never metered: health, public pages, billing/account/admin/analytics, the test stand-ins.
SKIP = re.compile(
    r"^/(health|plans|account|billing|admin|events|bug-reports|public|__test|demo|docs|openapi\.json)(/|$)"
)

# Writes a read-only account may still make: settings, exports, disconnecting things, taking access back.
WRITE_OK = re.compile(
    r"^/(profile|setup-wizard|exports|backups|ai/test)(/|$)"
    r"|^/invoices/profile(/|$)"
    r"|^/books/vat/schemes$"
    r"|^/books/self-employment/settings$"
    r"|^/books/(export|rebuild)$"
    r"|^/reports/export$"
    r"|/pdf$"
    r"|^/mail/mailboxes(/|$)"
    r"|^/books/bankfeeds/[^/]+/disconnect$"
    r"|^/books/ebay/disconnect$"
    r"|^/books/rules/[^/]+$"
    r"|^/accountant/invitations/[^/]+/revoke$"
    r"|^/accountant/team$"
)

# Refused up front when the month's allowance is used up.
PRECHECK: list[tuple[str, re.Pattern[str], str]] = [
    ("POST", re.compile(r"^/extract$"), "docs"),
    ("POST", re.compile(r"^/books/scan$"), "docs"),
    ("POST", re.compile(r"^/books/scan/jobs$"), "docs"),
    ("POST", re.compile(r"^/books/scan/jobs/[^/]+/confirm$"), "docs"),
    ("POST", re.compile(r"^/mail/scan$"), "docs"),
    ("POST", re.compile(r"^/books/ask(/voice)?$"), "ask"),
    ("POST", re.compile(r"^/invoices$"), "invoices"),
    ("POST", re.compile(r"^/quotes$"), "invoices"),
    ("POST", re.compile(r"^/quotes/[^/]+/convert$"), "invoices"),
]

# Counted after a 2xx.
COUNT_AFTER: list[tuple[str, re.Pattern[str], str]] = [(m, p, c) for m, p, c in PRECHECK if c in ("ask", "invoices")]

# Product events recorded after a 2xx (documents are counted where they are read: app/pipeline.py).
EVENTS: list[tuple[str, re.Pattern[str], str]] = [
    ("POST", re.compile(r"^/books/(proposals/[^/]+/approve|approve/[^/]+)$"), "proposal_approved"),
    ("POST", re.compile(r"^/books/bankfeeds/sync$"), "bank_synced"),
    ("POST", re.compile(r"^/books/ask(/voice)?$"), "ask"),
    ("POST", re.compile(r"^/books/ebay/sync$"), "ebay_sync"),
    ("GET", re.compile(r"^/books/self-employment/reports/"), "itsa_export"),
    ("GET", re.compile(r"^/exports/[^/]*(itsa|self-assessment|sa10)[^/]*(/file)?$"), "itsa_export"),
    ("GET", re.compile(r"^/exports/[^/]*vat[^/]*(/file)?$"), "vat_export"),
]

_ID_SEGMENT = re.compile(r"/(?=[^/]*\d)[^/]{6,}")


def match(table: list[tuple[str, re.Pattern[str], str]], method: str, path: str) -> list[str]:
    return [name for m, p, name in table if m == method and p.search(path)]


def route_template(scope: Scope) -> str:
    """The route's path template (`/invoices/{number}`), never the concrete path with someone's ids in it."""
    route = scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    return _ID_SEGMENT.sub("/{id}", scope.get("path", ""))[:200]


class BillingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        reg = R.registry()
        if reg is None:
            return await self.app(scope, receive, send)
        method, path = scope.get("method", ""), scope.get("path", "")
        meter = None if method == "OPTIONS" or SKIP.search(path) else await self._meter(reg, scope)
        if meter is not None:
            refusal = await self._refusal(meter, method, path)
            if refusal is not None:
                return await _reply(send, 402, refusal)
        status = 0

        async def send_wrapped(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                if meter is not None and meter.notices:
                    value = ",".join(sorted(set(meter.notices))).encode()
                    message["headers"] = [*message.get("headers", []), (b"x-plan-limit", value)]
            await send(message)

        try:
            with S.metering(meter):
                await self.app(scope, receive, send_wrapped)
        except Exception:
            await S.emit(reg, None, "api_error", {"route": route_template(scope), "method": method, "status": 500})
            raise
        if status >= 500:
            await S.emit(reg, None, "api_error", {"route": route_template(scope), "method": method, "status": status})
        if meter is not None and 200 <= status < 300:
            for counter in match(COUNT_AFTER, method, path):
                await meter.record(counter)
            for name in match(EVENTS, method, path):
                await S.emit(reg, meter.account, name, {})

    async def _meter(self, reg: R.Registry, scope: Scope) -> S.Meter | None:
        headers = Headers(scope=scope)
        token = headers.get("x-graph-token", "").strip().removeprefix("Bearer ").strip()
        if not token or headers.get("x-demo-session") or headers.get("x-books-drive-id"):
            return None
        kind = (headers.get("x-account-kind") or "personal").strip().lower()
        if kind not in ("personal", "work", "google"):
            return None  # the route answers 400
        from app import identity

        try:
            me = await identity.verified_identity(token, headers.get("x-user"), "google" if kind == "google" else None)
        except HTTPException:
            return None  # the route answers 401
        except Exception:  # noqa: BLE001  Graph down: the route will say so; nothing to meter
            log.warning("billing: identity not verified; request not metered", exc_info=True)
            return None
        try:
            acc = await S.ensure_account(reg, S.who_from(me, kind))
            plans = await S.plans_by_code(reg)
        except Exception:  # noqa: BLE001  registry down: fail open, never lock people out of their books
            log.warning("billing: registry unavailable; request not metered", exc_info=True)
            return None
        return S.Meter(reg=reg, account=acc, limits=S.limits_for(acc, plans), own_ai=S.own_ai(headers))

    async def _refusal(self, meter: S.Meter, method: str, path: str) -> dict[str, Any] | None:
        status = meter.account.get("status")
        if method in WRITES and status in S.READ_ONLY and not WRITE_OK.search(path):
            return S.ReadOnly(str(status)).body()
        for counter in match(PRECHECK, method, path):
            try:
                await meter.precheck(counter)
            except S.PlanLimit as exc:
                return exc.body()
            except Exception:  # noqa: BLE001  registry down: let it through
                log.warning("billing: precheck failed; request not limited", exc_info=True)
        return None


async def _reply(send: Send, status: int, body: dict[str, Any]) -> None:
    data = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(data)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": data})
