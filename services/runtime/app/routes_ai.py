"""The server's AI providers, for the "Meta models at work" page (/models in the web app).

GET  /ai/health  the chain (AI_PROVIDERS) and each provider's live health: cheap probes, cached HEALTH_TTL_S.
GET  /ai/calls   the last 50 AI calls (provider, model, task, latency, fell back?), kept in memory only.
POST /ai/warm    ping the Modal endpoint so its container is up before a judge's first upload; at most one ping per
                 WARM_EVERY_S, on top of the usual per-IP rate limit.

No output carries a key, token or provider URL. The Modal probe is passive by default (its state comes from the
last real call and the circuit breaker): an active probe would start a GPU container, which costs money, every time
someone opened the page. AI_HEALTH_PROBE_MODAL=1 makes it active (test mode always probes, against the stub).
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from app.ai import chain, providers
from app.ai.config import AiConfig, is_test_mode

router = APIRouter(prefix="/ai", tags=["ai"])

HEALTH_TTL_S = 60.0
PROBE_TIMEOUT = httpx.Timeout(4.0, connect=3.0)
WARM_EVERY_S = 60.0
#: tools/modal_glimmer.py SCALEDOWN_S: a container that served within this window is still up.
MODAL_WARM_FOR_S = 300

_cache: tuple[float, dict[str, Any]] | None = None
_last_warm: float | None = None  # monotonic time of the last ping; None: none yet (the clock may start near 0)
_warming: set[asyncio.Task[None]] = set()


class ProviderHealth(BaseModel):
    name: str
    label: str
    model: str
    configured: bool
    vision: bool
    json_mode: bool
    voice: bool
    status: str  # up | warm | idle | down | not configured
    detail: str
    probe_ms: int | None = None
    circuit: str = "closed"  # open: skipped until retry_in_s
    retry_in_s: int | None = None
    last_ok_s_ago: int | None = None
    last_error: str | None = None


class AiHealth(BaseModel):
    chain: list[str]
    configured: list[str]
    providers: list[ProviderHealth]
    checked_at: float
    cached: bool = False
    unknown: list[str] = []  # names in AI_PROVIDERS this runtime does not know


def _probe_modal_actively() -> bool:
    return is_test_mode() or os.getenv("AI_HEALTH_PROBE_MODAL") == "1"


async def _probe(c: AiConfig) -> tuple[str, str, int | None]:
    """(status, detail, ms) from one cheap request: the model list. Never raises."""
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT, follow_redirects=False) as client:
            if c.mode == "key":
                r = await client.get(f"{c.base_url}/models", headers=c.auth_headers())
                names = [m.get("id") for m in (r.json().get("data") or [])] if r.status_code == 200 else []
            else:
                r = await client.get(f"{c.base_url}/api/tags", headers=c.auth_headers())
                names = [m.get("name") for m in (r.json().get("models") or [])] if r.status_code == 200 else []
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        return "down", chain.why(exc), None
    ms = int((time.perf_counter() - t0) * 1000)
    if r.status_code != 200:
        return "down", f"HTTP {r.status_code}", ms
    if c.model not in names:
        return "down", f"answers, but {c.model} is not in its model list", ms
    return "up", f"{c.model} listed", ms


def _passive_modal(state: dict[str, Any]) -> tuple[str, str]:
    ago = state["last_ok_s_ago"]
    if state["circuit"] == "open":
        return "down", f"skipped after {state['failures_in_a_row']} failures ({state['last_error']})"
    if ago is not None and ago < MODAL_WARM_FOR_S:
        return "warm", f"served a call {ago} s ago"
    return "idle", "scaled to zero: the next call starts a container (60-120 s)"


async def _health() -> AiHealth:
    infos = providers.describe()
    configured = {c.provider: c for c in providers.configured_chain()}
    rows: list[ProviderHealth] = []

    async def one(info: providers.ProviderInfo) -> ProviderHealth:
        state = chain.BREAKER.state(info.name)
        base = {**info.model_dump(exclude={"why_not"}), **{k: state[k] for k in ("circuit", "retry_in_s")}}
        base |= {"last_ok_s_ago": state["last_ok_s_ago"], "last_error": state["last_error"]}
        c = configured.get(info.name)
        if c is None:
            return ProviderHealth(**base, status="not configured", detail=info.why_not or "not configured")
        if info.name == "modal" and not _probe_modal_actively():
            status, detail = _passive_modal(state)
            return ProviderHealth(**base, status=status, detail=detail)
        status, detail, ms = await _probe(c)
        if status == "up" and info.name == "modal":
            status = "warm"
        return ProviderHealth(**base, status=status, detail=detail, probe_ms=ms)

    rows = list(await asyncio.gather(*(one(i) for i in infos)))
    return AiHealth(
        chain=[i.name for i in infos],
        configured=list(configured),
        providers=rows,
        checked_at=time.time(),
        unknown=providers.unknown_names(),
    )


@router.get("/health", response_model=AiHealth)
async def ai_health() -> AiHealth:
    """The provider chain and each provider's health, cached for a minute (no secrets, no URLs)."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < HEALTH_TTL_S:
        return AiHealth.model_validate({**_cache[1], "cached": True})
    out = await _health()
    _cache = (now, out.model_dump())
    return out


@router.get("/calls", response_model=list[chain.CallRecord])
async def ai_calls() -> list[chain.CallRecord]:
    """The last 50 AI calls this runtime made, newest first. In memory only: a restart empties it."""
    return chain.recent()


class WarmResult(BaseModel):
    ok: bool
    warming: bool
    detail: str


async def _ping(c: AiConfig) -> None:
    timeout = httpx.Timeout(connect=c.connect_s, read=c.first_token_s or 150.0, write=10.0, pool=c.connect_s)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            r = await client.get(f"{c.base_url}/api/tags", headers=c.auth_headers())
            r.raise_for_status()
    except httpx.HTTPError as exc:  # recorded, not counted against the breaker: only real calls open it
        chain.BREAKER.last_error[c.provider] = f"warm-up: {chain.why(exc)}"
        return
    chain.BREAKER.success(c.provider)


@router.post("/warm", response_model=WarmResult)
async def ai_warm() -> WarmResult:
    """Start the Modal container now, so the first real call does not wait for a cold start. Returns at once."""
    global _last_warm
    modal = next((c for c in providers.configured_chain() if c.provider == "modal"), None)
    if modal is None:
        return WarmResult(ok=True, warming=False, detail="No Modal provider in this server's chain.")
    ago = chain.BREAKER.state("modal")["last_ok_s_ago"]
    if ago is not None and ago < MODAL_WARM_FOR_S - 60:
        return WarmResult(ok=True, warming=False, detail=f"Already warm (served {ago} s ago).")
    now = time.monotonic()
    if _last_warm is not None and now - _last_warm < WARM_EVERY_S:
        return WarmResult(ok=True, warming=True, detail="A warm-up is already on its way.")
    _last_warm = now
    task = asyncio.create_task(_ping(modal))
    _warming.add(task)
    task.add_done_callback(_warming.discard)
    return WarmResult(ok=True, warming=True, detail="Warming Muse Glimmer 30B on Modal (60-120 s from cold).")


def reset() -> None:
    """Tests: forget the cache, the warm-up clock and the breaker."""
    global _cache, _last_warm
    _cache, _last_warm = None, None
    chain.BREAKER.reset()
    chain.RECENT.clear()
