"""Request hardening for the public runtime (docs/SECURITY.md).

One pure-ASGI middleware, inside CORS so its error responses still carry CORS headers:
  * a correlation id per request (`X-Correlation-Id`), also used in error bodies and logs;
  * credential headers (X-Graph-Token, X-Mailbox-Token, X-Meta-Api-Key, X-HMRC-Access-Token, Authorization,
    X-Demo-Session) over 8 KB -> 431, and over plain HTTP -> 400 whenever a proxy says so in X-Forwarded-Proto;
  * a per-IP token bucket (RATE_LIMIT_PER_MIN, default 60) -> 429 with Retry-After;
  * body caps: 25 MB on the document upload routes, 11 MB on the demo's Graph look-alike, 2 MB on the invoice logo,
    256 KB everywhere else -> 413;
  * any unhandled exception -> 500 `{"detail", "correlation_id"}`, never a stack trace.

`install_log_scrubbing()` makes every log record (any logger, including exception text) pass through `scrub`.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from contextvars import ContextVar
from typing import Any

from starlette.exceptions import HTTPException

log = logging.getLogger("accnomos.runtime")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

SECRET_HEADERS = (
    "x-graph-token",
    "x-mailbox-token",
    "x-meta-api-key",
    "x-hmrc-access-token",
    "authorization",
    "x-demo-session",
)
MAX_TOKEN_BYTES = 8 * 1024
UPLOAD_PATHS = frozenset({"/extract", "/books/ask/voice", "/books/bank/import"})
UPLOAD_LIMIT = 25 * 1024 * 1024
JSON_LIMIT = 256 * 1024
# Small uploads: the file itself is checked by its route (a 1 MB logo), the cap leaves room for the multipart wrapping.
SMALL_UPLOADS = {"/invoices/profile/logo": 2 * 1024 * 1024}
# Upload routes by prefix: the demo sandbox's Graph look-alike (app/demo.py), where a demo's "Add a receipt" PUTs the
# file (signed in, the browser uploads to Microsoft instead). DemoStorage refuses a file over DEMO_MAX_FILE_BYTES.
PREFIX_UPLOADS = {"/demo/graph/": 11 * 1024 * 1024}
UNLIMITED_PATHS = frozenset({"/health"})  # no rate limit (container healthcheck, uptime probes)
UNLIMITED_PREFIXES: tuple[str, ...] = ()  # test mode adds "/__test/": stand-ins for Graph and the AI, not this server
MAX_BUCKETS = 10_000

# --- scrubbing ------------------------------------------------------------------------------------------------

REDACTED = "[redacted]"
_HEADER_VALUE = re.compile(
    r"(?i)(x-graph-token|x-mailbox-token|x-demo-session|x-meta-api-key|x-hmrc-access-token|authorization"
    r"|api[_-]?key|access_token|refresh_token)"
    r"""(["']?\s*[:=]\s*["']?)(?:bearer\s+)?[^\s"',;&}]+"""
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]*")


# The credential values of the request being served, so a token quoted bare in an exception message (no
# "Bearer", no header name) is still caught. Values under 8 characters are skipped: too likely to be ordinary text.
_request_secrets: ContextVar[tuple[str, ...]] = ContextVar("request_secrets", default=())
# The server's own keys, read from the environment on each call (tests change it), so an upstream error that echoes
# one (a model provider quoting the key it refused) is redacted too.
SERVER_SECRET_ENV = (
    "META_API_KEY",
    "MODEL_API_KEY",
    "BASETEN_API_KEY",
    "COMPANIES_HOUSE_API_KEY",
    "ACTIONS_SIGNING_KEY",
)


def _server_secrets() -> tuple[str, ...]:
    return tuple(v for name in SERVER_SECRET_ENV if len(v := os.getenv(name, "").strip()) >= 8)


def scrub(text: str) -> str:
    """Remove this request's credentials, the server's own keys, bearer tokens, JWTs and credential header/field
    values from free text."""
    for secret in (*_request_secrets.get(), *_server_secrets()):
        text = text.replace(secret, REDACTED)
    text = _HEADER_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    return _JWT.sub(REDACTED, text)


def _scrub_arg(arg: Any) -> Any:
    if arg is None or isinstance(arg, (int, float)):
        return arg
    if isinstance(arg, str):
        return scrub(arg)
    text = str(arg)
    return arg if scrub(text) == text and scrub(repr(arg)) == repr(arg) else scrub(text)


def scrub_record(record: logging.LogRecord) -> None:
    """Scrub `record` in place. A clean record is left alone, and a dirty one keeps its msg/args shape when
    scrubbing each part is enough: some formatters read record.args (uvicorn's access log unpacks it)."""
    try:
        message = record.getMessage()
    except Exception:  # noqa: BLE001  a bad format string must not lose the record
        record.msg, record.args = scrub(str(record.msg)), None
        return
    if scrub(message) == message:
        return
    msg, args = record.msg, record.args
    if isinstance(args, tuple):
        args = tuple(_scrub_arg(a) for a in args)
    elif isinstance(args, Mapping):
        args = {k: _scrub_arg(v) for k, v in args.items()}
    record.msg, record.args = (scrub(msg) if isinstance(msg, str) else msg), args
    try:
        if scrub(record.getMessage()) == record.getMessage():
            return
    except Exception:  # noqa: BLE001
        pass
    record.msg, record.args = scrub(message), None  # a secret split across msg and args: flatten


_installed = False


def install_log_scrubbing() -> None:
    """Scrub every LogRecord as it is created, whichever logger or handler ends up emitting it."""
    global _installed
    if _installed:
        return
    make = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = make(*args, **kwargs)
        scrub_record(record)
        if record.exc_info:
            # Re-scrub even when an inner install already formatted it: its secrets are a
            # different service's (empty here), and scrubbing is idempotent. Without this, two
            # installs in one process (the combined pytest run) leak through the inner one's text.
            record.exc_text = scrub(record.exc_text or logging.Formatter().formatException(record.exc_info))
        return record

    logging.setLogRecordFactory(factory)
    _installed = True


# --- rate limit -----------------------------------------------------------------------------------------------


class TokenBucket:
    """`rate` requests per minute per key, bursting to `rate`. In memory, per process."""

    def __init__(self, rate: int, clock: Callable[[], float] = time.monotonic):
        self.rate, self.capacity, self.per_s = rate, float(rate), rate / 60.0
        self.clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last refill)

    def reset(self) -> None:
        self._buckets.clear()

    def take(self, key: str) -> float:
        """0 if allowed, else seconds until a token is available."""
        now = self.clock()
        tokens, last = self._buckets.get(key, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - last) * self.per_s)
        if tokens >= 1:
            self._buckets[key] = (tokens - 1, now)
            if len(self._buckets) > MAX_BUCKETS:
                self._prune(now)
            return 0.0
        self._buckets[key] = (tokens, now)
        return (1 - tokens) / self.per_s

    def _prune(self, now: float) -> None:
        """Drop buckets that have refilled completely (they behave exactly like a fresh one)."""
        self._buckets = {
            k: (t, last) for k, (t, last) in self._buckets.items() if t + (now - last) * self.per_s < self.capacity
        }


# --- middleware -----------------------------------------------------------------------------------------------


class BodyTooLarge(HTTPException):
    """Raised from `receive`; a Starlette HTTPException so FastAPI's body parser lets it through as a 413."""

    def __init__(self, limit: int):
        super().__init__(
            413,
            f"Request body over {limit // 1024} KB"
            if limit < 1024 * 1024
            else f"Request body over {limit // (1024 * 1024)} MB",
        )


def body_limit(path: str) -> int:
    if path in UPLOAD_PATHS:
        return UPLOAD_LIMIT
    prefixed = next((cap for prefix, cap in PREFIX_UPLOADS.items() if path.startswith(prefix)), None)
    return prefixed or SMALL_UPLOADS.get(path, JSON_LIMIT)


_RATE = int(os.getenv("RATE_LIMIT_PER_MIN", "60"))
LIMITER: TokenBucket | None = TokenBucket(_RATE) if _RATE > 0 else None  # RATE_LIMIT_PER_MIN=0 turns it off


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, limiter: TokenBucket | None = LIMITER):
        self.app = app
        self.limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        cid = uuid.uuid4().hex[:16]
        scope.setdefault("state", {})["correlation_id"] = cid
        headers = {k.decode("latin-1").lower(): v for k, v in scope.get("headers", [])}
        path, method = scope.get("path", ""), scope.get("method", "")
        started = False

        async def send_with_id(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"x-correlation-id", cid.encode())]
            await send(message)

        async def reply(status: int, detail: str, extra: dict[str, str] | None = None) -> None:
            body = json.dumps({"detail": detail, "correlation_id": cid}).encode()
            hdrs = [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                *((k.encode(), v.encode()) for k, v in (extra or {}).items()),
            ]
            await send_with_id({"type": "http.response.start", "status": status, "headers": hdrs})
            await send_with_id({"type": "http.response.body", "body": body})

        # 1. credentials: size, and HTTPS whenever a proxy tells us the scheme
        present = [h for h in SECRET_HEADERS if headers.get(h)]
        if any(len(headers[h]) > MAX_TOKEN_BYTES for h in present):
            return await reply(431, f"Credential header over {MAX_TOKEN_BYTES // 1024} KB")
        proto = headers.get("x-forwarded-proto", b"").decode("latin-1").split(",")[0].strip().lower()
        if present and proto and proto != "https":
            return await reply(400, "Credentials must be sent over HTTPS")
        values = (headers[h].decode("latin-1").strip() for h in present)
        _request_secrets.set(tuple(s for v in values for s in {v, v.removeprefix("Bearer ").strip()} if len(s) >= 8))

        # 2. rate limit (preflights and health checks are free)
        if (
            self.limiter
            and method != "OPTIONS"
            and path not in UNLIMITED_PATHS
            and not (UNLIMITED_PREFIXES and path.startswith(UNLIMITED_PREFIXES))
        ):
            client = scope.get("client")
            wait = self.limiter.take(client[0] if client else "unknown")
            if wait:
                return await reply(429, "Too many requests; slow down", {"retry-after": str(max(1, math.ceil(wait)))})

        # 3. body size: refuse an honest Content-Length up front, count the bytes of everything else
        limit = body_limit(path)
        try:
            declared = int(headers.get("content-length", b"0"))
        except ValueError:
            return await reply(400, "Bad Content-Length")
        if declared > limit:
            return await reply(413, str(BodyTooLarge(limit).detail))
        seen = 0

        async def capped_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise BodyTooLarge(limit)
            return message

        # 4. anything unhandled: log it (scrubbed) under the correlation id, answer without internals
        try:
            await self.app(scope, capped_receive, send_with_id)
        except BodyTooLarge as exc:  # raised outside FastAPI's body parsing (e.g. a raw request.stream())
            if started:
                raise
            await reply(413, str(exc.detail))
        except Exception:
            log.exception("unhandled error [%s] %s %s", cid, method, path)
            if started:
                raise
            await reply(500, "Internal error; quote the correlation id if you report it")
