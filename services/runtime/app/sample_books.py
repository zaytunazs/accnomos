"""Load sample books: the judges' demo books for the fictional Bramblewood Joinery Ltd, into an empty folder.

    POST /books/sample            start (or carry on); a second POST while it runs hands over a fresh token
    POST /books/sample/continue   the same; the web app calls it every few minutes and when the status says so
    GET  /books/sample            how far it has got

The books are exactly what `tools/seed_demo.py` writes (six months of every feature, each document labelled
"SAMPLE — FICTIONAL COMPANY"): the same plan and the same steps (`seed_demo.seed_steps`), run here one at a time
in the background, because they take a long time: about 11,300 storage calls on the fake OneDrive, each roughly
one Graph request (unmeasured against Graph).

* Only into a folder with no ledger entries, proposals or contacts (409 otherwise). Nothing is ever deleted.
* Progress is kept in the user's own folder, `_System/sample_seed.json` ({state, step, done, total, started_at,
  updated_at, error, ...}), so a reload or another tab can follow it; the runtime still keeps no user data.
* The Graph token a request carries lasts about an hour and the runtime cannot refresh it. The background run uses
  the token of the request that started it and takes the fresh token of every later POST (`set_token`). If Graph
  refuses the token anyway, the run waits (state `needs_token`) for the next POST; if none comes, or the runtime
  restarts, the next POST starts a new run from the recorded step. Each step is safe to run again after it stopped
  part-way (seed_demo.py, "The seed as a list of steps").
* At most SAMPLE_RATE_PER_MIN POSTs a minute per folder. Audit: `sample_books_started`, `sample_books_loaded`.
* An error is recorded as a plain sentence naming the step: never a token, a path or a Graph message.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import importlib.util
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from accnomos_connectors.base import StorageProvider
from accnomos_connectors.msgraph import GraphError, GraphStorageProvider
from app import contacts as contacts_mod
from app.books import EVENTS, PROPOSALS, SYSTEM, Books
from app.books import today as current_date
from app.deadlines import stagger_of
from app.routes_books import get_books, require_user
from app.security import TokenBucket
from app.vat_cycle import VatCycle, vat_cycle

log = logging.getLogger("accnomos.sample_books")

STATUS = f"{SYSTEM}/sample_seed.json"
STALE_S = float(os.getenv("SAMPLE_STALE_S", "180"))  # no progress written for this long: the run has stopped
TOKEN_WAIT_S = float(os.getenv("SAMPLE_TOKEN_WAIT_S", "600"))  # how long a run waits for a fresh token
RATE_PER_MIN = int(os.getenv("SAMPLE_RATE_PER_MIN", "10"))

router = APIRouter(prefix="/books", tags=["sample books"])

State = Literal["none", "running", "needs_token", "done", "failed"]

NOT_EMPTY = (
    "Your Accnomos folder already has books in it (entries, receipts waiting in Review or contacts). Sample books "
    "only go into an empty folder, so nothing was changed."
)
NOT_OURS = (
    "Your Accnomos folder has entries that did not come from the sample books, so loading them was stopped and "
    "nothing more was changed."
)
NEEDS_TOKEN = "Your Microsoft sign-in needs renewing to carry on. Keep this page open: it carries on by itself."
STOPPED = "Loading stopped part-way. Press Load sample books to carry on from where it got to."


class SampleStatus(BaseModel):
    state: State
    step: str | None = None  # the step being done, or the one it stopped at
    done: int = 0  # steps finished
    total: int = 0
    steps: list[str] = []  # every step's name, in order
    started_at: datetime | None = None
    updated_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None  # a plain sentence, when it stopped
    business: str | None = None  # the fictional company
    empty: bool | None = None  # state "none" only: whether sample books could go into this folder
    today: date | None = None  # the plan's day and VAT stagger, so a resumed run builds the same plan
    stagger: int | None = None


# --------------------------------------------------------------------------- #
# The seed itself: tools/seed_demo.py (the Docker image copies it, evals/gold and evals/harness/render.py)
# --------------------------------------------------------------------------- #


class SampleUnavailable(RuntimeError):
    pass


def seed_module() -> ModuleType:
    if (mod := sys.modules.get("seed_demo")) is not None:
        return mod
    env = os.getenv("ACCNOMOS_SEED_DEMO")
    candidates = [Path(env)] if env else [p / "tools" / "seed_demo.py" for p in Path(__file__).resolve().parents]
    path = next((p for p in candidates if p.is_file()), None)
    spec = importlib.util.spec_from_file_location("seed_demo", path) if path else None
    if spec is None or spec.loader is None:
        raise SampleUnavailable("tools/seed_demo.py not found")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["seed_demo"] = mod  # dataclasses look their module up by name
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # e.g. evals/gold missing from this install
        del sys.modules["seed_demo"]
        raise SampleUnavailable(str(exc)) from exc
    return mod


# --------------------------------------------------------------------------- #
# Runs in this process, one per folder
# --------------------------------------------------------------------------- #


@dataclass
class _Run:
    key: str
    storage: StorageProvider
    status: SampleStatus
    user: str
    owns_storage: bool
    resume_from: int  # this step may have run part-way before (-1: none)
    fresh_token: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None

    def hand_token(self, token: str) -> None:
        set_token = getattr(self.storage, "set_token", None)
        if callable(set_token) and token:
            set_token(token)
        self.fresh_token.set()


RUNS: dict[str, _Run] = {}  # a finished run leaves; one that stopped stays, so GET can say why
_LOCKS: dict[int, asyncio.Lock] = {}


def _lock() -> asyncio.Lock:
    """One lock per event loop (the tests run one loop each; the server has one)."""
    loop = asyncio.get_running_loop()
    return _LOCKS.setdefault(id(loop), asyncio.Lock())


LIMITER = TokenBucket(RATE_PER_MIN) if RATE_PER_MIN > 0 else None


def _token(request: Request) -> str:
    return request.headers.get("X-Graph-Token", "").strip().removeprefix("Bearer ").strip()


def _kind(request: Request) -> str:
    return (request.headers.get("X-Account-Kind") or "personal").strip().lower()


async def folder_key(books: Books, kind: str) -> str:
    """Who this is, without keeping anything about them: the folder's drive item id (the fakes share one id, so
    there the storage object tells them apart)."""
    root = await books.storage.ensure_root()
    extra = "" if isinstance(books.storage, GraphStorageProvider) else f":{id(books.storage)}"
    return hashlib.sha256(f"{kind}:{root.id}{extra}".encode()).hexdigest()[:32]


def _now() -> datetime:
    return datetime.now(UTC)


async def load_status(books: Books) -> SampleStatus | None:
    raw = await books.read_json(STATUS, None)
    if not isinstance(raw, dict):
        return None
    try:
        return SampleStatus.model_validate(raw)
    except ValueError:
        return None


async def _save(books: Books, status: SampleStatus) -> None:
    status.updated_at = _now()
    await books.write_json(STATUS, status.model_dump(mode="json", exclude={"empty"}))


def _stale(status: SampleStatus) -> bool:
    return status.updated_at is None or (_now() - status.updated_at).total_seconds() > STALE_S


async def is_empty(books: Books) -> bool:
    """No proposals, no contacts and no ledger entries: nothing sample books could mix with. Home asks on every
    visit, so it lists folders and reads no entry (cheapest first; real books stop at the first listing)."""
    if any(f.name.endswith(".json") for f in await books.list_files(PROPOSALS)):
        return False
    if await contacts_mod.stored_contacts(books):
        return False
    try:
        months = [f for f in await books.storage.list(EVENTS) if f.is_folder]
    except FileNotFoundError:
        return True
    for m in months:
        if any(f.name.endswith(".json") for f in await books.list_files(f"{EVENTS}/{m.name}")):
            return False
    return True


def _safe_error(step: str | None, exc: BaseException) -> str:
    where = f" at “{step}”" if step else ""
    if isinstance(exc, GraphError):
        return f"OneDrive refused a request (HTTP {exc.status}){where}. Press Load sample books to carry on from there."
    return f"Loading stopped{where}. Press Load sample books to carry on from there."


async def _token_refused(storage: StorageProvider) -> bool:
    """After an error some app code reported in its own way (intake counts a failed copy, say): was it the token?"""
    try:
        await storage.ensure_root()
    except GraphError as exc:
        return exc.status in (401, 403)
    except Exception:  # noqa: BLE001
        return False
    return False


async def _run(run: _Run, steps: list[Any]) -> None:
    """Run the steps from `status.done` on, saving the status after each. A refused token makes it wait for the next
    POST's fresh one (up to TOKEN_WAIT_S), then redo the step it was on, which may have run part-way."""
    seed = seed_module()
    books = seed.SeedBooks(run.storage)
    status = run.status
    i, step_done = status.done, False
    try:
        await run.storage.ensure_root()
        while True:
            try:
                if i < len(steps):
                    status.step = steps[i].name
                    if not step_done:
                        await steps[i].run(books, i == run.resume_from)
                        step_done = True
                    status.done = i + 1
                    await _save(books, status)
                    i, step_done = i + 1, False
                    await asyncio.sleep(0)  # the fakes never wait on I/O: let the server answer meanwhile
                    continue
                status.state, status.step, status.finished_at, status.error = "done", None, _now(), None
                await _save(books, status)
                await books.audit(
                    f"user:{run.user}",
                    "sample_books_loaded",
                    {"business": status.business, "events": len(await books.list_events()), "steps": status.total},
                )
                return
            except Exception as exc:
                refused = isinstance(exc, GraphError) and exc.status in (401, 403)
                if not refused and not isinstance(exc, GraphError):
                    refused = await _token_refused(run.storage)
                if not refused:
                    raise
                status.state, status.error = "needs_token", NEEDS_TOKEN
                run.fresh_token.clear()
                try:
                    await asyncio.wait_for(run.fresh_token.wait(), TOKEN_WAIT_S)
                except TimeoutError:
                    return  # the file still says "running"; the next POST carries on from its step
                status.state, status.error = "running", None
                run.resume_from = -1 if step_done else i
    except Exception as exc:  # noqa: BLE001  recorded as a sentence; the details go to the (scrubbed) log
        log.warning("sample books stopped at %r: %s", status.step, type(exc).__name__, exc_info=True)
        status.state, status.error = "failed", _safe_error(status.step, exc)
        with contextlib.suppress(Exception):  # the token may be the problem; GET then reports the stale run
            await _save(books, status)
    finally:
        if status.state == "done" and RUNS.get(run.key) is run:
            RUNS.pop(run.key, None)
        if run.owns_storage:
            await run.storage.aclose()  # type: ignore[attr-defined]


def _own_storage(books: Books, token: str, kind: str) -> tuple[StorageProvider, bool]:
    """The background run's storage: its own Graph client (the request's closes when the request ends)."""
    if isinstance(books.storage, GraphStorageProvider):
        return GraphStorageProvider(token, kind), True  # type: ignore[arg-type]
    return books.storage, False  # test mode's fakes: the same object the requests see


def _stagger(cycle: VatCycle) -> int:
    return stagger_of(cycle.start_month) if cycle.months == 3 else 1


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get("/sample", response_model=SampleStatus, response_model_exclude={"today", "stagger"})
async def sample_status(request: Request, books: Books = Depends(get_books)) -> SampleStatus:
    """How far loading sample books has got; state "none" (with `empty`) when they were never started here."""
    run = RUNS.get(await folder_key(books, _kind(request)))
    if run is not None:
        return run.status
    status = await load_status(books)
    if status is None:
        return SampleStatus(state="none", empty=await is_empty(books))
    if status.state == "running" and _stale(status):
        status.state, status.error = "needs_token", STOPPED
    return status


@router.post("/sample", response_model=SampleStatus, response_model_exclude={"today", "stagger"})
@router.post("/sample/continue", response_model=SampleStatus, response_model_exclude={"today", "stagger"})
async def load_sample(
    request: Request,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
    cycle: VatCycle = Depends(vat_cycle),
) -> SampleStatus:
    """Start loading sample books into this empty folder, or carry on: a run in progress gets this request's fresh
    token and its status is returned as it is (so pressing twice, or two tabs, start one run)."""
    kind = _kind(request)
    key = await folder_key(books, kind)
    if LIMITER and (wait := LIMITER.take(key)):
        raise HTTPException(
            429,
            "Too many requests to load sample books; wait a moment.",
            headers={"Retry-After": str(max(1, round(wait)))},
        )
    async with _lock():
        run = RUNS.get(key)
        if run is not None and run.task is not None and not run.task.done():
            run.hand_token(_token(request))
            return run.status
        stopped_here = run is not None  # a run in this process that stopped: carry on whatever the file says
        status = await load_status(books)
        if status is not None and status.state == "done":
            return status
        if status is not None and status.state == "running" and not _stale(status) and not stopped_here:
            return status  # another runtime process is running it
        try:
            seed = seed_module()
        except SampleUnavailable as exc:
            log.warning("sample books unavailable: %s", exc)
            raise HTTPException(503, "Sample books aren't available on this server.") from exc
        if status is None or status.state == "none":
            if not await is_empty(books):
                raise HTTPException(409, NOT_EMPTY)
            day, stagger = current_date(), _stagger(cycle)
            status = SampleStatus(state="running", started_at=_now(), today=day, stagger=stagger)
            resume_from = -1
            await books.audit(f"user:{user}", "sample_books_started", {"business": seed.GOLD_BUSINESS})
        else:  # stopped part-way (needs a token, failed, or a run that went quiet): carry on from its step
            if await seed.seed_state(books) == "foreign":
                raise HTTPException(409, NOT_OURS)
            day, stagger = status.today or current_date(), status.stagger or _stagger(cycle)
            resume_from = status.done
        plan = seed.build_plan(seed.GOLD_BUSINESS, day, stagger)
        steps = seed.seed_steps(plan)
        status.state, status.error, status.business = "running", None, seed.GOLD_BUSINESS
        status.total, status.steps = len(steps), [s.name for s in steps]
        status.step = steps[min(status.done, len(steps) - 1)].name
        await _save(books, status)
        storage, owns = _own_storage(books, _token(request), kind)
        run = _Run(key, storage, status, user, owns, resume_from)
        RUNS[key] = run
        run.task = asyncio.create_task(_run(run, steps))
        return status
