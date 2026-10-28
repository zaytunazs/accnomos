"""Demo sandbox (`DEMO_MODE=1`): the whole app on the sample books, with no Microsoft sign-in.

`POST /demo/session` hands the visitor an opaque session id (random, signed with `DEMO_SECRET`) and a fresh
in-memory copy of the sample books: exactly what tools/seed_demo.py writes for the fictional Bramblewood Joinery Ltd
(every document labelled "SAMPLE — FICTIONAL COMPANY"), planned for today, plus a few inbox documents already read
so Review has something waiting. Requests then carry `X-Demo-Session` instead of `X-Graph-Token`, and every
dependency that would build a Microsoft client (storage, mail, address book, calendar, sender) gets this session's
in-memory fakes instead:

* Storage is a `DemoStorage` (a `FakeStorageProvider` with limits). No request in a demo reaches OneDrive or Graph;
  the browser's own Graph calls go to `/demo/graph/v1.0` (app/fake_graph.py) over the same storage.
* Mail is never sent: the sender only records it, and the web app says "Sent (demo — not actually sent)".
* HMRC is never called: the runtime holds no HMRC token anyway, and the web app simulates the submission in a demo
  (a clearly labelled "Demo — submission simulated" receipt). The VAT-number check and Companies House look-ups are
  refused for demo sessions (403).
* AI calls use the server's normal AI configuration, exactly as for a signed-in user.

Nothing is stored about the visitor: no Microsoft password or refresh token exists anywhere in this flow, and a
session is gone after `DEMO_IDLE_TTL_S` (2 h) without a request, when it is the least recently used of
`DEMO_MAX_SESSIONS` (200), or when the runtime restarts.

Seeding runs the whole plan (~4 s on an idle machine, much longer on a busy one), so it runs once per day in a
background thread and each session gets a copy of that snapshot: the files' bytes are immutable and shared, only the
dicts are copied, so a new session costs milliseconds and a few kilobytes until it writes.

Limits (env): DEMO_MAX_SESSIONS, DEMO_IDLE_TTL_S, DEMO_MAX_SESSION_BYTES (new bytes one session may add),
DEMO_MAX_SESSION_FILES (new files), DEMO_MAX_FILE_BYTES (one file), DEMO_MAX_TOTAL_BYTES (all sessions' added bytes;
the least recently used go first), DEMO_SESSIONS_PER_IP_PER_MIN (session starts per IP), DEMO_GRAPH_PER_MIN
(Graph look-alike calls per session; those are exempt from the per-IP budget, which a page of Files would use up).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import math
import os
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from accnomos_connectors import (
    AddressBookContact,
    CalendarEvent,
    FakeCalendarProvider,
    FakeContactsProvider,
    FakeMailProvider,
    FakeMailSender,
    FakeStorageProvider,
    MailMessage,
)
from accnomos_connectors.base import FileRef
from app import fake_graph, security
from app.books import Books
from app.books import today as current_date
from app.paths import INBOX

log = logging.getLogger("accnomos.demo")

HEADER = "X-Demo-Session"
LABEL = "SAMPLE — FICTIONAL COMPANY"
USER = "demo@accnomos.example"  # the X-User the web app sends in a demo
PRE_READ = 4  # inbox documents already read into Review (plus the two that need a look)
SECRET_MIN = 32
MB = 1024 * 1024


def enabled() -> bool:
    """DEMO_MODE=1. Off by default."""
    return os.getenv("DEMO_MODE") == "1"


def _env_num(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else default


@dataclass(frozen=True)
class Limits:
    max_sessions: int = 200
    idle_ttl_s: float = 2 * 3600
    session_bytes: int = 20 * MB
    session_files: int = 300
    file_bytes: int = 10 * MB
    total_bytes: int = 512 * MB
    sessions_per_ip_per_min: int = 5
    graph_per_min: int = 600

    @classmethod
    def from_env(cls) -> Limits:
        d = cls()
        return cls(
            max_sessions=int(_env_num("DEMO_MAX_SESSIONS", d.max_sessions)),
            idle_ttl_s=_env_num("DEMO_IDLE_TTL_S", d.idle_ttl_s),
            session_bytes=int(_env_num("DEMO_MAX_SESSION_BYTES", d.session_bytes)),
            session_files=int(_env_num("DEMO_MAX_SESSION_FILES", d.session_files)),
            file_bytes=int(_env_num("DEMO_MAX_FILE_BYTES", d.file_bytes)),
            total_bytes=int(_env_num("DEMO_MAX_TOTAL_BYTES", d.total_bytes)),
            sessions_per_ip_per_min=int(_env_num("DEMO_SESSIONS_PER_IP_PER_MIN", d.sessions_per_ip_per_min)),
            graph_per_min=int(_env_num("DEMO_GRAPH_PER_MIN", d.graph_per_min)),
        )


class DemoLimit(Exception):
    """A demo session went over one of its limits (answered 413 by app.main)."""


class DemoStorage(FakeStorageProvider):
    """A session's own copy of the sample books. `files` maps paths to immutable bytes, so copying the snapshot's
    dicts is enough: the bytes are shared until this session writes its own."""

    def __init__(self, base: FakeStorageProvider | None, limits: Limits) -> None:
        super().__init__()
        if base is not None:
            self.files = dict(base.files)
            self.folders = set(base.folders)
            self._log = list(base._log)
        self.limits = limits
        self.added_bytes = 0  # net bytes written since the copy (overwriting with less gives some back)
        self.added_files = 0

    async def write(self, path: str, data: bytes, *, if_match: str | None = None, create_only: bool = False) -> FileRef:
        lim = self.limits
        if len(data) > lim.file_bytes:
            raise DemoLimit(f"Files in the demo sandbox are limited to {lim.file_bytes // MB} MB each.")
        old = self.files.get(path.strip("/"))
        files = self.added_files + (old is None)
        added = self.added_bytes + len(data) - (len(old) if old is not None else 0)
        if old is None and files > lim.session_files:
            raise DemoLimit(f"This demo sandbox holds at most {lim.session_files} new files. Reset the demo.")
        if added > lim.session_bytes and len(data) > len(old or b""):
            raise DemoLimit(f"This demo sandbox holds at most {lim.session_bytes // MB} MB of new files. Reset it.")
        ref = await super().write(path, data, if_match=if_match, create_only=create_only)
        self.added_files, self.added_bytes = files, added
        return ref


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #


@dataclass
class DemoSession:
    id: str  # the random part of the token; the signature is checked before any lookup
    storage: DemoStorage
    mail: FakeMailProvider
    sender: FakeMailSender  # records only: nothing is ever sent from a demo
    contacts: FakeContactsProvider
    calendar: FakeCalendarProvider
    business: str
    today: date
    created: float
    last_used: float

    @property
    def token_key(self) -> str:
        """Stands in for the Graph token where code keys something on it (action signing, the event cache)."""
        return f"demo-session:{self.id}"

    def books(self) -> Books:
        from app.cache import user_cache_key

        return Books(self.storage, cache_key=user_cache_key(self.token_key, "demo"))


class SessionStore:
    """At most `max_sessions`, least recently used out first; idle ones expire; all their added bytes are capped."""

    def __init__(self, limits: Limits, clock: Callable[[], float] = time.monotonic) -> None:
        self.limits = limits
        self.clock = clock
        self.sessions: OrderedDict[str, DemoSession] = OrderedDict()
        self.evicted = 0

    def __len__(self) -> int:
        return len(self.sessions)

    def add(self, s: DemoSession) -> None:
        self.prune()
        while len(self.sessions) >= max(1, self.limits.max_sessions):
            self.sessions.popitem(last=False)
            self.evicted += 1
        self.sessions[s.id] = s
        self._cap_bytes(keep=s.id)

    def get(self, sid: str) -> DemoSession | None:
        s = self.sessions.get(sid)
        if s is None:
            return None
        now = self.clock()
        if now - s.last_used > self.limits.idle_ttl_s:
            del self.sessions[sid]
            return None
        s.last_used = now
        self.sessions.move_to_end(sid)
        self._cap_bytes(keep=sid)
        return s

    def drop(self, sid: str) -> bool:
        return self.sessions.pop(sid, None) is not None

    def prune(self) -> None:
        now = self.clock()
        for sid in [sid for sid, s in self.sessions.items() if now - s.last_used > self.limits.idle_ttl_s]:
            del self.sessions[sid]

    def total_added(self) -> int:
        return sum(max(0, s.storage.added_bytes) for s in self.sessions.values())

    def _cap_bytes(self, keep: str) -> None:
        while self.total_added() > self.limits.total_bytes:
            victim = next((sid for sid in self.sessions if sid != keep), None)
            if victim is None:
                return
            del self.sessions[victim]
            self.evicted += 1


LIMITS = Limits.from_env()
STORE = SessionStore(LIMITS)
CREATE_LIMITER = security.TokenBucket(LIMITS.sessions_per_ip_per_min) if LIMITS.sessions_per_ip_per_min > 0 else None
GRAPH_LIMITER = security.TokenBucket(LIMITS.graph_per_min) if LIMITS.graph_per_min > 0 else None


def _secret() -> bytes:
    secret = os.getenv("DEMO_SECRET", "")
    if len(secret) < SECRET_MIN:
        raise RuntimeError(f"DEMO_MODE=1 needs DEMO_SECRET (at least {SECRET_MIN} characters)")
    return secret.encode()


def sign(raw: str) -> str:
    return f"{raw}.{hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()[:32]}"


def unsign(token: str) -> str | None:
    """The session id inside a token this server signed, else None."""
    raw, _, sig = token.strip().partition(".")
    if not raw or len(sig) != 32 or len(raw) > 64:
        return None
    want = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    return raw if hmac.compare_digest(want, sig) else None


def from_request(request: Request) -> DemoSession | None:
    """This request's demo session; None when it carries no `X-Demo-Session` (a normal signed-in request).
    A demo header never falls through to Graph: off, forged or expired, it is a 401."""
    token = request.headers.get(HEADER)
    if token is None:
        return None
    if not enabled():
        raise HTTPException(401, "The demo sandbox isn't switched on on this server.")
    raw = unsign(token)
    s = STORE.get(raw) if raw else None
    if s is None:
        raise HTTPException(401, "This demo session has ended (demos reset after 2 hours). Start a new demo.")
    return s


def require(request: Request) -> DemoSession:
    s = from_request(request)
    if s is None:
        raise HTTPException(401, f"{HEADER} header required")
    return s


def is_demo_request(request: Request) -> bool:
    return request.headers.get(HEADER) is not None


# --------------------------------------------------------------------------- #
# The seeded snapshot (built once per day, in a background thread)
# --------------------------------------------------------------------------- #


@dataclass
class Snapshot:
    day: date
    storage: FakeStorageProvider
    business: str
    seconds: float


async def build_full(day: date) -> Snapshot:
    """tools/seed_demo.py's whole plan for `day` on a fresh fake, then a few inbox documents read into Review (the
    seed's own gold reading, as for every other seeded document), so a visitor can review and approve at once."""
    from app import sample_books

    started = time.perf_counter()
    seed = sample_books.seed_module()
    plan = seed.build_plan(seed.GOLD_BUSINESS, day, 1)
    st = FakeStorageProvider()
    await seed.seed(st, plan, say=lambda _m: None)
    books = seed.SeedBooks(st)
    needs = [d for d in plan.inbox if d.expect == "needs_a_look"]
    picks = needs + [d for d in plan.inbox if d.expect != "needs_a_look"][:PRE_READ]
    for d in picks:
        path = f"{INBOX}/{d.file_name}"
        await seed._propose(books, d, plan, arrived=(path, st.files[path]))
    return Snapshot(day, st, plan.business, time.perf_counter() - started)


BUILD: Callable[[date], Coroutine[Any, Any, Snapshot]] = build_full  # tests swap in a small one
SEED_TIMEOUT_S = _env_num("DEMO_SEED_TIMEOUT_S", 600)


@dataclass
class _Build:
    day: date
    done: threading.Event = field(default_factory=threading.Event)
    result: Snapshot | None = None
    error: BaseException | None = None


_lock = threading.Lock()
_snap: Snapshot | None = None
_builds: dict[date, _Build] = {}


def _run_build(b: _Build) -> None:
    global _snap
    try:
        result = b.result = asyncio.run(BUILD(b.day))
        log.info("demo sandbox: sample books for %s seeded in %.1f s", b.day, result.seconds)
        with _lock:
            if _snap is None or _snap.day <= b.day:
                _snap = result
            for d in [d for d in _builds if d < b.day]:
                _builds.pop(d, None)
    except BaseException as exc:  # noqa: BLE001  reported to every waiter; the next request starts again
        log.warning("demo sandbox: seeding failed: %s", type(exc).__name__, exc_info=True)
        b.error = exc
    finally:
        b.done.set()


def start_build(day: date) -> _Build:
    with _lock:
        b = _builds.get(day)
        if b is None or (b.done.is_set() and b.error is not None):
            b = _builds[day] = _Build(day)
            threading.Thread(target=_run_build, args=(b,), name=f"demo-seed-{day}", daemon=True).start()
        return b


async def snapshot(day: date) -> Snapshot:
    """Today's seeded books, built on first need; waiters poll rather than hold a worker thread each."""
    s = _snap
    if s is not None and s.day == day:
        return s
    b = start_build(day)
    deadline = time.monotonic() + SEED_TIMEOUT_S
    while not b.done.is_set():
        if time.monotonic() > deadline:
            raise TimeoutError("demo seed took too long")
        await asyncio.sleep(0.2)
    if b.error is not None or b.result is None:
        raise RuntimeError("demo seed failed") from b.error
    return b.result


def reset_for_tests() -> None:
    global _snap
    with _lock:
        _snap = None
        _builds.clear()
    STORE.sessions.clear()
    for limiter in (CREATE_LIMITER, GRAPH_LIMITER):
        if limiter:
            limiter.reset()


# --------------------------------------------------------------------------- #
# A session's mailbox, address book and calendar (fictional, in memory)
# --------------------------------------------------------------------------- #


def _mailbox() -> FakeMailProvider:
    mail = FakeMailProvider()
    received = datetime.now(UTC)
    mail.add(
        MailMessage(
            id="demo-msg-1",
            received_at=received - timedelta(hours=3),
            from_address="accounts@sterling-architects.example",
            from_name="Sterling & Co. Architects",
            subject="Copy of invoice INV-0002, please",
        ),
        body=f"Hello, could you resend invoice INV-0002? Our copy has gone missing. Thanks. ({LABEL})",
    )
    mail.add(
        MailMessage(
            id="demo-msg-2",
            received_at=received - timedelta(hours=9),
            from_address="news@trade-weekly.example",
            from_name="Trade Weekly",
            subject="This week's offers",
        ),
        body=f"Timber prices, new tools and a webinar. ({LABEL})",
    )
    return mail


def _contacts() -> list[AddressBookContact]:
    return [
        AddressBookContact(
            id="demo-contact-1",
            display_name="JM Trading Ltd",
            company_name="JM Trading Ltd",
            emails=["accounts@jmtrading.example"],
        ),
        AddressBookContact(
            id="demo-contact-2",
            display_name="Priya Shah",
            company_name="Shah Interiors Ltd",
            emails=["priya@shahinteriors.example"],
        ),
    ]


def _calendar(day: date) -> FakeCalendarProvider:
    london = ZoneInfo("Europe/London")
    nxt = day + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return FakeCalendarProvider(
        [
            CalendarEvent(
                id="demo-evt-1",
                subject="Site visit, Harbour Lane kitchen",
                location="12 Harbour Lane, Bristol BS1 4RW",
                start=datetime(nxt.year, nxt.month, nxt.day, 9, 0, tzinfo=london),
                end=datetime(nxt.year, nxt.month, nxt.day, 10, 0, tzinfo=london),
                body_preview=LABEL,
            )
        ]
    )


async def new_session(day: date | None = None) -> tuple[str, DemoSession]:
    day = day or current_date()
    snap = await snapshot(day)
    now = STORE.clock()
    s = DemoSession(
        id=secrets.token_urlsafe(24),
        storage=DemoStorage(snap.storage, LIMITS),
        mail=_mailbox(),
        sender=FakeMailSender(),
        contacts=FakeContactsProvider(_contacts()),
        calendar=_calendar(day),
        business=snap.business,
        today=day,
        created=now,
        last_used=now,
    )
    STORE.add(s)
    return sign(s.id), s


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

router = APIRouter(prefix="/demo", tags=["demo sandbox"])


class SessionInfo(BaseModel):
    session: str | None = None  # the token: only in the answer to POST
    business: str
    label: str = LABEL
    user: str = USER
    today: date
    idle_ttl_s: int
    simulated: list[str] = ["mail", "hmrc"]  # what a demo never really does


def _info(s: DemoSession, token: str | None = None) -> SessionInfo:
    return SessionInfo(session=token, business=s.business, today=s.today, idle_ttl_s=int(LIMITS.idle_ttl_s))


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/session", response_model=SessionInfo, response_model_exclude_none=True)
async def start_session(request: Request) -> SessionInfo:
    """A fresh sandbox with the sample books. Sent with a current `X-Demo-Session`, that one is dropped first
    (Reset demo). Rate-limited per IP."""
    if CREATE_LIMITER and (wait := CREATE_LIMITER.take(_client_ip(request))):
        raise HTTPException(
            429,
            "Too many demo sessions started from here; wait a minute.",
            headers={"Retry-After": str(max(1, math.ceil(wait)))},
        )
    if (old := request.headers.get(HEADER)) and (raw := unsign(old)):
        STORE.drop(raw)
    try:
        token, s = await new_session()
    except Exception as exc:  # noqa: BLE001  the details are in the log (seeding is retried on the next request)
        log.warning("demo sandbox: no session: %s", type(exc).__name__)
        raise HTTPException(503, "The demo sandbox couldn't be prepared just now; try again in a minute.") from exc
    return _info(s, token)


@router.get("/session", response_model=SessionInfo, response_model_exclude_none=True)
async def session_info(request: Request) -> SessionInfo:
    return _info(require(request))


@router.delete("/session", status_code=204)
async def end_session(request: Request) -> Response:
    if (token := request.headers.get(HEADER)) and (raw := unsign(token)):
        STORE.drop(raw)
    return Response(status_code=204)


@router.api_route("/graph/v1.0/{rest:path}", methods=["GET", "POST", "PUT"], include_in_schema=False)
async def graph(rest: str, request: Request) -> Response:
    """The browser's Graph calls (apps/web/src/lib/graph.ts) in a demo: this session's storage, never Microsoft."""
    s = require(request)
    if GRAPH_LIMITER and (wait := GRAPH_LIMITER.take(s.id)):
        raise HTTPException(429, "Too many requests; slow down", headers={"Retry-After": str(max(1, math.ceil(wait)))})
    return await fake_graph.respond(s.storage, rest, request, web_base=None, put=s.storage.write)


def status() -> dict[str, Any]:
    """For /health: whether demos can start, and whether today's books are ready."""
    s = _snap
    return {"enabled": True, "ready": s is not None and s.day == current_date(), "sessions": len(STORE)}


def enable() -> None:
    """Called once by app.main when DEMO_MODE=1: refuses to start without DEMO_SECRET, exempts the Graph
    look-alike from the per-IP budget (it has its own per-session one) and starts seeding today's books."""
    _secret()
    security.UNLIMITED_PREFIXES = (*security.UNLIMITED_PREFIXES, "/demo/graph/")
    start_build(current_date())
    log.warning("DEMO_MODE=1: demo sandboxes with sample books are on (no Microsoft sign-in)")
