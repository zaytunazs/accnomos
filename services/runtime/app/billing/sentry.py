"""Error reports to Sentry (EU data region), only when SENTRY_DSN is set and `sentry-sdk` is installed.

`send_default_pii=False`; request bodies, cookies, headers and query strings are dropped; and `scrub_event` runs as
`before_send` (and on breadcrumbs), replacing anything that looks like money (£12.34, GBP 12, 12.34), an email
address, a GB VAT number, a bearer token or JWT with "[redacted]", on top of app/security.py's credential scrubbing.

    SENTRY_DSN                     https://…@o….ingest.de.sentry.io/… (EU region)
    SENTRY_ENVIRONMENT             production | staging (default: production)
    SENTRY_TRACES_SAMPLE_RATE      0 by default (errors only)
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from app.security import scrub

log = logging.getLogger("accnomos.runtime")
REDACTED = "[redacted]"

_PATTERNS = [
    re.compile(r"(?i)\b(?:bearer|token)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]*"),
    re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"),
    re.compile(r"(?i)\bGB\s?(?:\d{3}\s?\d{4}\s?\d{2}(?:\s?\d{3})?|GD\d{3}|HA\d{3})\b"),
    re.compile(r"(?i)(?:£|\bGBP\s?|\bEUR\s?|€|\$)\s?-?\d[\d,]*(?:\.\d+)?"),
    re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})*\.\d{2}(?![\d.])"),  # a bare 12.34 or 1,234.56
    re.compile(r"\b(?:sk|rk|pk|whsec)_(?:live|test)?_?[A-Za-z0-9]{8,}"),  # Stripe keys
]
_DROP_KEYS = frozenset({"cookies", "headers", "data", "query_string", "env"})


def scrub_text(text: str) -> str:
    text = scrub(text)
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def _walk(value: Any, depth: int = 0) -> Any:
    if depth > 12:
        return REDACTED
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {k: _walk(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_walk(v, depth + 1) for v in value]
    return value


def scrub_event(event: dict[str, Any], _hint: Any = None) -> dict[str, Any]:
    """`before_send`: strip the request down to method and path, drop the user, then scrub every string left."""
    request = event.get("request")
    if isinstance(request, dict):
        url = str(request.get("url") or "")
        event["request"] = {"method": request.get("method"), "url": url.split("?", 1)[0]}
        for key in _DROP_KEYS:
            event["request"].pop(key, None)
    event.pop("user", None)
    event.pop("server_name", None)
    for frame_holder in ("exception", "threads"):
        for item in (event.get(frame_holder) or {}).get("values") or []:
            for frame in (item.get("stacktrace") or {}).get("frames") or []:
                frame.pop("vars", None)  # local variables can hold anything
    return _walk(event)


def scrub_breadcrumb(crumb: dict[str, Any], _hint: Any = None) -> dict[str, Any] | None:
    if crumb.get("category") in ("httplib", "http"):
        data = crumb.get("data") or {}
        if "url" in data:
            data["url"] = str(data["url"]).split("?", 1)[0]
        data.pop("http.query", None)
    return _walk(crumb)


def init() -> bool:
    """Start Sentry when configured. Returns whether it is on."""
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk  # type: ignore[import-not-found]
    except ImportError:
        log.warning("SENTRY_DSN is set but sentry-sdk is not installed; error reports are off")
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        release=os.getenv("ACCNOMOS_VERSION") or None,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0") or 0),
        before_send=scrub_event,  # type: ignore[arg-type]
        before_breadcrumb=scrub_breadcrumb,  # type: ignore[arg-type]
    )
    return True
