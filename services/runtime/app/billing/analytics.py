"""First-party product analytics and bug reports (docs/billing/PLANS_AND_CONTRACT.md, "Analytics").

    POST /events        {name, props, app, version}  (signed in; dropped silently when opted out; rate-limited)
    POST /bug-reports   {message, page, app, version, ua, screenshot_b64?} -> {id}

Events never carry amounts, supplier or person names, document text, emails or file names. That is enforced, not
hoped for: `props` keys come from `PROP_RULES` only and every value must match its rule (a number in range, a plan
code, a lowercase slug or an app path), so nothing with an `@`, a space, a `£` or a decimal point gets through.
Server-side event names (`signup`, `subscription_active`, …) cannot be sent by a client.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import Field

from app.billing import plans as P
from app.billing import registry as R
from app.billing import service as S
from app.billing.registry import Row
from app.billing.routes import maybe_account
from app.security import TokenBucket
from app.validation import StrictBody

router = APIRouter(tags=["analytics"])

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
PAGE_RE = re.compile(r"^/[a-z0-9/_-]{0,99}$")
VERSION_RE = re.compile(r"^[A-Za-z0-9._+-]{1,40}$")
MAX_PROPS = 10
SERVER_ONLY = frozenset(
    {
        "signup",
        "document_scanned",
        "proposal_approved",
        "bank_synced",
        "ask",
        "vat_export",
        "itsa_export",
        "ebay_sync",
        "checkout_started",
        "subscription_active",
        "subscription_cancelled",
        "trial_ended",
        "topup_bought",
        "code_redeemed",
        "api_error",
    }
)


def _int(lo: int, hi: int):
    return lambda v: isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _slug(v: Any) -> bool:
    return isinstance(v, str) and bool(SLUG_RE.fullmatch(v))


def _page(v: Any) -> bool:
    return isinstance(v, str) and bool(PAGE_RE.fullmatch(v))


PROP_RULES: dict[str, Any] = {
    "page": _page,  # an app path such as /review or /bank/feeds (lowercase; no ids with dots or @)
    "from_page": _page,
    "feature": _slug,
    "action": _slug,
    "step": _slug,
    "source": _slug,
    "result": _slug,
    "variant": _slug,
    "screen": _slug,
    "plan": lambda v: v in P.PLAN_CODES,
    "interval": lambda v: v in ("month", "year"),
    "count": _int(0, 100_000),
    "duration_ms": _int(0, 86_400_000),
    "step_index": _int(0, 100),
    "ok": lambda v: isinstance(v, bool),
    "own_ai": lambda v: isinstance(v, bool),
}


def validate_props(props: dict[str, Any]) -> dict[str, Any]:
    if len(props) > MAX_PROPS:
        raise HTTPException(422, f"At most {MAX_PROPS} properties")
    for key, value in props.items():
        rule = PROP_RULES.get(key)
        if rule is None:
            raise HTTPException(422, f"Property {key!r} is not allowed")
        if not rule(value):
            raise HTTPException(422, f"Property {key!r} has a value that is not allowed")
    return props


_EVENTS_RATE = int(os.getenv("EVENTS_PER_MIN", "60"))
EVENTS_LIMITER: TokenBucket | None = TokenBucket(_EVENTS_RATE) if _EVENTS_RATE > 0 else None
_BUGS_RATE = int(os.getenv("BUG_REPORTS_PER_MIN", "3"))
BUGS_LIMITER: TokenBucket | None = TokenBucket(_BUGS_RATE) if _BUGS_RATE > 0 else None


def _limited(limiter: TokenBucket | None, key: str) -> JSONResponse | None:
    if limiter is None:
        return None
    wait = limiter.take(key)
    if not wait:
        return None
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests; slow down"},
        headers={"Retry-After": str(max(1, int(wait) + 1))},
    )


class EventIn(StrictBody):
    name: str = Field(max_length=48)
    props: dict[str, Any] = Field(default_factory=dict)
    app: Literal["web", "android"] = "web"
    version: str | None = Field(default=None, max_length=40)


@router.post("/events", status_code=202, response_model=None)
async def post_event(body: EventIn, acc: Annotated[Row | None, Depends(maybe_account)]) -> Response:
    reg = R.registry()
    if reg is None or acc is None:
        return Response(status_code=202)  # nowhere to keep it: dropped
    if not NAME_RE.fullmatch(body.name) or body.name in SERVER_ONLY:
        raise HTTPException(422, "Event name not allowed")
    validate_props(body.props)
    if body.version is not None and not VERSION_RE.fullmatch(body.version):
        raise HTTPException(422, "Bad version")
    if (refusal := _limited(EVENTS_LIMITER, acc["id"])) is not None:
        return refusal
    if acc.get("analytics_opt_out"):
        return Response(status_code=202)  # opted out: dropped silently
    await S.emit(reg, acc, body.name, body.props, app=body.app)
    return Response(status_code=202)


MAX_SCREENSHOT = 2 * 1024 * 1024
_MAGIC = ((b"\x89PNG\r\n\x1a\n", "image/png", "png"), (b"\xff\xd8\xff", "image/jpeg", "jpg"))


def _image_type(data: bytes) -> tuple[str, str] | None:
    for magic, mime, ext in _MAGIC:
        if data.startswith(magic):
            return mime, ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


class BugReportIn(StrictBody):
    message: str = Field(min_length=1, max_length=5000)
    page: str | None = Field(default=None, max_length=300)
    app: Literal["web", "android"] = "web"
    version: str | None = Field(default=None, max_length=40)
    ua: str | None = Field(default=None, max_length=500)
    screenshot_b64: str | None = Field(default=None, max_length=2_900_000)  # 2 MB as base64, with room for a data: URL


@router.post("/bug-reports", status_code=201)
async def post_bug_report(body: BugReportIn, acc: Annotated[Row | None, Depends(maybe_account)]) -> Any:
    reg = R.registry()
    if reg is None or acc is None:
        raise HTTPException(503, "Problem reports are not set up on this server")
    if (refusal := _limited(BUGS_LIMITER, acc["id"])) is not None:
        return refusal
    screenshot = None
    if body.screenshot_b64:
        raw = body.screenshot_b64.strip()
        if raw.startswith("data:"):
            raw = raw.split(",", 1)[-1]
        try:
            data = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(422, "The screenshot is not valid base64") from exc
        if len(data) > MAX_SCREENSHOT:
            raise HTTPException(413, "The screenshot is over 2 MB")
        kind = _image_type(data)
        if kind is None:
            raise HTTPException(415, "The screenshot must be a PNG, JPEG or WebP image")
        if not reg.storage_configured:
            raise HTTPException(
                422,
                detail={
                    "code": "screenshots_unavailable",
                    "detail": "Screenshots can't be kept on this server. Send the report without one.",
                },
            )
        screenshot = (data, *kind)
    path = None
    if screenshot is not None:
        data, mime, ext = screenshot
        path = f"{acc['id']}/{uuid.uuid4().hex}.{ext}"
        try:
            await reg.upload_screenshot(path, data, mime)
        except R.StorageUnavailable as exc:
            raise HTTPException(
                422,
                detail={
                    "code": "screenshots_unavailable",
                    "detail": "The screenshot couldn't be stored. Send the report without one.",
                },
            ) from exc
    row = await reg.add_bug_report(
        {
            "account_id": acc["id"],
            "email": acc.get("email"),
            "message": body.message.strip(),
            "page": (body.page or "").strip()[:300] or None,
            "app": body.app,
            "version": body.version,
            "ua": (body.ua or "").strip()[:500] or None,
            "screenshot_path": path,
        }
    )
    return {"id": str(row["id"])}
