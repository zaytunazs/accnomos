"""Failover across the server's AI providers (app/ai/providers.py), a circuit breaker per provider, and a record
of who served every AI call.

`run(cfg, task, attempt)` calls `attempt(provider_cfg)` for each provider in `cfg.chain()` until one answers:

* fail over on a timeout, a connection error, HTTP 5xx, 402/429 (billing, rate limit) and 401/403/404/408 (that
  provider's own auth, model or gateway trouble: the next provider has different credentials and models);
* never on another 4xx (400, 413, 422 ...): that is our own bad request, and the next provider would refuse it too;
* never on a reply that came back but does not parse: that is the model's answer, not an outage.

A provider that fails BREAKER_FAILURES times in a row is skipped for BREAKER_COOLDOWN_S, so a dead one adds no
latency to every call; after the cool-down one call tries it again. When every provider is skipped they are all
tried anyway, in order, rather than failing without a try.

A backend the user chose (their own local agent or Meta key) is a chain of one with no breaker: it behaves as before.

`limits(call_s=..., deadline=...)` caps every attempt made inside it, whoever serves it: no attempt runs longer than
`call_s`, nor past `deadline` (a `time.monotonic()` value, the document's time budget in app/scan_jobs.py). A cap that
is reached reads as a timeout, so the chain fails over (or the caller falls back) exactly as for a slow provider.

Every call is recorded (provider, model, task, latency, fell back from) in memory only, the last RECENT_MAX of them,
for the /models page; nothing about the request's content is kept.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel

from app.ai.config import AiConfig
from app.schemas import ServedBy

log = logging.getLogger("accnomos.ai")

FAILOVER_STATUS = frozenset({401, 402, 403, 404, 408, 429})
RECENT_MAX = 50


def _env_number(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


BREAKER_FAILURES = int(_env_number("AI_BREAKER_FAILURES", 3))
BREAKER_COOLDOWN_S = _env_number("AI_BREAKER_COOLDOWN_S", 120)


class OutOfTime(httpx.ReadTimeout):
    """The caller's deadline (`limits`) ran out: not the provider's fault, so no breaker failure and no failover."""


class ProviderDown(RuntimeError):
    """A provider that failed in a way the next one may not (see `fails_over`)."""


def fails_over(exc: BaseException) -> bool:
    """True for trouble with the provider (move to the next), False for trouble with our request or the reply."""
    from app.ai.ask import AiStalled  # late: ask imports this module

    if isinstance(exc, (TimeoutError, AiStalled, ProviderDown)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code >= 500 or code in FAILOVER_STATUS
    return isinstance(exc, httpx.TransportError)  # connect/read/write timeouts, refused, reset, DNS


def why(exc: BaseException) -> str:
    """A short, secret-free reason for the record."""
    from app.ai.ask import AiStalled

    if isinstance(exc, ProviderDown) and exc.__cause__ is not None:
        return why(exc.__cause__)
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, (TimeoutError, httpx.TimeoutException, AiStalled)):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connection refused"
    if isinstance(exc, httpx.TransportError):
        return "connection error"
    return type(exc).__name__


def trouble(cfg: AiConfig, what: str) -> str:
    """The plain reason shown when no model answered. For the server's chain it names the providers, never their
    addresses; for a backend the user chose it reads as before ("Your AI (local) could not be reached at ...")."""
    if cfg.in_chain:
        return f"None of the server's AI providers answered ({', '.join(c.provider for c in cfg.chain())})."
    return f"Your AI ({cfg.mode}) {what}."


# --------------------------------------------------------------------------- #
# Circuit breaker
# --------------------------------------------------------------------------- #


class Breaker:
    def __init__(self) -> None:
        self.failures: dict[str, int] = {}
        self.open_until: dict[str, float] = {}
        self.last_ok: dict[str, float] = {}
        self.last_error: dict[str, str] = {}

    def is_open(self, name: str, now: float | None = None) -> bool:
        return (now if now is not None else time.monotonic()) < self.open_until.get(name, 0.0)

    def success(self, name: str) -> None:
        self.failures[name] = 0
        self.open_until.pop(name, None)
        self.last_ok[name] = time.monotonic()
        self.last_error.pop(name, None)

    def failure(self, name: str, reason: str) -> None:
        self.failures[name] = self.failures.get(name, 0) + 1
        self.last_error[name] = reason
        if self.failures[name] >= BREAKER_FAILURES:
            self.open_until[name] = time.monotonic() + BREAKER_COOLDOWN_S

    def state(self, name: str) -> dict[str, Any]:
        now = time.monotonic()
        ok_at = self.last_ok.get(name)
        return {
            "circuit": "open" if self.is_open(name, now) else "closed",
            "failures_in_a_row": self.failures.get(name, 0),
            "retry_in_s": max(0, round(self.open_until[name] - now)) if self.is_open(name, now) else None,
            "last_ok_s_ago": round(now - ok_at) if ok_at is not None else None,
            "last_error": self.last_error.get(name),
        }

    def reset(self) -> None:
        self.__init__()


BREAKER = Breaker()


# --------------------------------------------------------------------------- #
# The record: the last RECENT_MAX calls, and who served the last call in this context
# --------------------------------------------------------------------------- #


class CallRecord(BaseModel):
    at: datetime
    task: str
    provider: str
    model: str
    latency_ms: int
    ok: bool
    fell_back_from: list[str] = []
    error: str | None = None


RECENT: deque[CallRecord] = deque(maxlen=RECENT_MAX)
_SERVED: ContextVar[ServedBy | None] = ContextVar("accnomos_served_by", default=None)


def recent() -> list[CallRecord]:
    """Newest first."""
    return list(reversed(RECENT))


def clear_served() -> None:
    _SERVED.set(None)


def take_served() -> ServedBy | None:
    """Who served the last AI call made in this task (and forget it), or None when no call answered."""
    served = _SERVED.get()
    _SERVED.set(None)
    return served


def _record(task: str, cfg: AiConfig, t0: float, ok: bool, fell: list[str], error: str | None = None) -> ServedBy:
    latency = int((time.perf_counter() - t0) * 1000)
    RECENT.append(
        CallRecord(
            at=datetime.now(UTC),
            task=task,
            provider=cfg.provider or cfg.mode,
            model=cfg.model,
            latency_ms=latency,
            ok=ok,
            fell_back_from=list(fell),
            error=error,
        )
    )
    return ServedBy(provider=cfg.provider or cfg.mode, model=cfg.model, latency_ms=latency, fell_back_from=list(fell))


def candidates(cfg: AiConfig, *, vision: bool = False) -> list[AiConfig]:
    """The providers to try, in order: those that can do the job, minus those whose circuit is open (unless that
    leaves none). A user's own backend is always just itself."""
    chain = cfg.chain()
    if vision:
        chain = [c for c in chain if c.vision] or chain
    if not any(c.in_chain for c in chain):
        return chain
    closed = [c for c in chain if not BREAKER.is_open(c.provider)]
    return closed or chain


_CALL_S: ContextVar[float | None] = ContextVar("accnomos_ai_call_s", default=None)
_DEADLINE: ContextVar[float | None] = ContextVar("accnomos_ai_deadline", default=None)


@contextmanager
def limits(*, call_s: float | None = None, deadline: float | None = None) -> Iterator[None]:
    """Cap every AI attempt made inside: at most `call_s` each, and none past `deadline` (time.monotonic())."""
    t1, t2 = _CALL_S.set(call_s), _DEADLINE.set(deadline)
    try:
        yield
    finally:
        _CALL_S.reset(t1)
        _DEADLINE.reset(t2)


def attempt_limit(c: AiConfig, now: float | None = None) -> float | None:
    """The longest the next attempt on `c` may take: the provider's request_s, the caller's per-call cap and what is
    left of the deadline, whichever is least (None: no limit beyond the HTTP client's own)."""
    caps = [x for x in (c.request_s, _CALL_S.get()) if x]
    if (deadline := _DEADLINE.get()) is not None:
        caps.append(deadline - (now if now is not None else time.monotonic()))
    return min(caps) if caps else None


async def _within[T](coro: Awaitable[T], c: AiConfig) -> T:
    """`coro`, cut off at `attempt_limit`. A timeout is raised as httpx's, which every caller handles."""
    limit = attempt_limit(c)
    if limit is None:
        return await coro
    who = c.provider or c.mode
    deadline = _DEADLINE.get()
    by_deadline = deadline is not None and limit >= deadline - time.monotonic() - 0.01
    if limit <= 0:
        if asyncio.iscoroutine(coro):
            coro.close()  # never started: no "was never awaited" warning
        raise OutOfTime(f"no time left in this document's budget to ask {who}")
    try:
        return await asyncio.wait_for(coro, limit)
    except TimeoutError:
        log.warning("AI call to %s cut off after %.0f s", who, limit)
        error = OutOfTime if by_deadline else httpx.ReadTimeout
        raise error(f"{who} took longer than {limit:.0f} s") from None


async def run[T](
    cfg: AiConfig, task: str, attempt: Callable[[AiConfig], Awaitable[T]], *, vision: bool = False
) -> tuple[T, ServedBy]:
    """`attempt` on each provider until one answers; returns its result and who served it. Raises the last
    provider's error when none answers, or at once on an error that is not the provider's (see module doc)."""
    fell: list[str] = []
    tried = candidates(cfg, vision=vision)
    for i, c in enumerate(tried):
        t0 = time.perf_counter()
        try:
            result = await _within(attempt(c), c)
        except OutOfTime:
            _record(task, c, t0, False, fell, "out of time")
            raise
        except Exception as exc:
            down = fails_over(exc)
            _record(task, c, t0, False, fell, why(exc))
            if c.in_chain and down:
                BREAKER.failure(c.provider, why(exc))
            if down and i + 1 < len(tried):
                fell.append(c.provider or c.mode)
                continue
            raise
        if c.in_chain:
            BREAKER.success(c.provider)
        served = _record(task, c, t0, True, fell)
        _SERVED.set(served)
        return result, served
    raise ProviderDown("no AI provider to try")  # unreachable: chain() is never empty


async def stream(cfg: AiConfig, task: str, open_stream: Callable[[AiConfig], AsyncIterator[str]]) -> AsyncIterator[str]:
    """`run` for a streamed reply: fails over only until the first chunk arrives. After that the reply belongs to
    that provider and its errors reach the caller (half an answer from one model is not continued by another)."""
    fell: list[str] = []
    tried = candidates(cfg)
    for i, c in enumerate(tried):
        t0 = time.perf_counter()
        it = open_stream(c).__aiter__()
        try:
            first = await it.__anext__()
        except StopAsyncIteration:
            first = None
        except Exception as exc:
            down = fails_over(exc)
            _record(task, c, t0, False, fell, why(exc))
            if c.in_chain and down:
                BREAKER.failure(c.provider, why(exc))
            if down and i + 1 < len(tried):
                fell.append(c.provider or c.mode)
                continue
            raise
        if c.in_chain:
            BREAKER.success(c.provider)
        if first is not None:
            yield first
            try:
                async for chunk in it:
                    yield chunk
            except Exception as exc:
                _record(task, c, t0, False, fell, why(exc))
                raise
        _SERVED.set(_record(task, c, t0, True, fell))
        return
