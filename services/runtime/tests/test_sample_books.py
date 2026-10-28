"""POST/GET /books/sample: Load sample books into an empty folder, in the background, resumable (app/sample_books.py).

The books are tools/seed_demo.py's, run on the in-memory fake OneDrive as of the seed tests' day (27 Oct 2026). Token
expiry is simulated by storage that refuses every call with Graph's 401 after a set number of calls, until the next
request hands over a fresh token (`set_token`)."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
from collections import Counter
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

from accnomos_connectors import FakeStorageProvider
from accnomos_connectors.base import FileRef, StorageProvider
from accnomos_connectors.msgraph import GraphError
from app import autopilot, invoicing, sample_books, security
from app.books import INBOX, Books
from app.main import app
from app.routes_books import get_books
from app.security import TokenBucket

TOOL = Path(__file__).resolve().parents[3] / "tools" / "seed_demo.py"
TODAY = date(2026, 10, 27)
HEADERS = {"X-Graph-Token": "token-one", "X-User": "judge@example.com"}
SETTLE_TIMEOUT_S = 900  # a hang, not slowness: the seed takes seconds here and minutes on a loaded machine


@pytest.fixture(scope="module")
def seed_demo() -> ModuleType:
    if (mod := sys.modules.get("seed_demo")) is not None:
        return mod
    spec = importlib.util.spec_from_file_location("seed_demo", TOOL)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["seed_demo"] = mod
    spec.loader.exec_module(mod)
    return mod


class Expiring(StorageProvider):
    """Fake OneDrive whose token "expires" after `budget` calls: every call then raises GraphError(401) until
    set_token gives it a fresh one (with `refill` calls; None: no limit)."""

    def __init__(self, inner: FakeStorageProvider, budget: int | None, refill: int | None = None) -> None:
        self.inner, self.left, self.refill = inner, budget, refill
        self.tokens: list[str] = []
        self.refused = 0

    def set_token(self, token: str) -> None:
        self.tokens.append(token)
        self.left = self.refill

    def _spend(self) -> None:
        if self.left is not None:
            if self.left <= 0:
                self.refused += 1
                raise GraphError(401, "InvalidAuthenticationToken")
            self.left -= 1

    async def ensure_root(self) -> FileRef:
        self._spend()
        return await self.inner.ensure_root()

    async def ensure_folder(self, path: str) -> FileRef:
        self._spend()
        return await self.inner.ensure_folder(path)

    async def list(self, path: str) -> list[FileRef]:
        self._spend()
        return await self.inner.list(path)

    async def read(self, path: str) -> bytes:
        self._spend()
        return await self.inner.read(path)

    async def write(self, path: str, data: bytes, *, if_match: str | None = None, create_only: bool = False) -> FileRef:
        self._spend()
        return await self.inner.write(path, data, if_match=if_match, create_only=create_only)

    async def move(self, path: str, new_path: str) -> FileRef:
        self._spend()
        return await self.inner.move(path, new_path)

    async def changes(self, cursor: str | None) -> tuple[list[FileRef], str]:
        self._spend()
        return await self.inner.changes(cursor)


class Breaking(Expiring):
    """Fails one write with a Graph error whose text holds things that must never reach the status."""

    def __init__(self, inner: FakeStorageProvider, at: int) -> None:
        super().__init__(inner, None)
        self.writes, self.at = 0, at

    async def write(self, path: str, data: bytes, *, if_match: str | None = None, create_only: bool = False) -> FileRef:
        self.writes += 1
        if self.writes == self.at:
            raise GraphError(500, "token eyJhbGciOi at /Users/judge/OneDrive/Apps/Accnomos/_System")
        return await super().write(path, data, if_match=if_match, create_only=create_only)


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch, seed_demo: ModuleType) -> None:
    monkeypatch.setattr(sample_books, "current_date", lambda: TODAY)
    monkeypatch.setattr(sample_books, "LIMITER", TokenBucket(1000))
    if security.LIMITER:  # the tests poll faster than the per-address budget allows
        monkeypatch.setattr(security.LIMITER, "take", lambda _key: 0.0)
    sample_books.RUNS.clear()


def _run_on(monkeypatch: pytest.MonkeyPatch, storage: StorageProvider) -> None:
    """The background run's storage (the requests keep seeing the plain fake)."""
    monkeypatch.setattr(sample_books, "_own_storage", lambda _books, _token, _kind: (storage, False))


def _client(storage: StorageProvider) -> httpx.AsyncClient:
    async def over() -> AsyncIterator[Books]:
        yield Books(storage)

    app.dependency_overrides[get_books] = over
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture(scope="module")
def _cli_books(seed_demo: ModuleType) -> FakeStorageProvider:
    fake = FakeStorageProvider()
    asyncio.run(seed_demo.seed(fake, seed_demo.build_plan("Bramblewood Joinery Ltd", TODAY), say=lambda _m: None))
    return fake


@pytest.fixture
def done_books(_cli_books: FakeStorageProvider) -> FakeStorageProvider:
    """The books the CLI writes, for comparison (a copy: one CLI run per module)."""
    fake = FakeStorageProvider()
    fake.files, fake.folders = dict(_cli_books.files), set(_cli_books.folders)
    return fake


async def _settle(client: httpx.AsyncClient, *, until: tuple[str, ...] = ("done", "failed")) -> dict[str, Any]:
    """The run's status once it has stopped in one of the `until` states. It waits on the run itself
    (`_Run.stopped`), not on a number of polls: a fixed polling budget raced the background run, so on a loaded
    machine the seed was still going when the budget ran out. The outer timeout only stops a hang."""
    for _ in range(3):  # a stop that is not wanted yet (say needs_token) is reported, not waited out
        r = await client.get("/books/sample", headers=HEADERS)
        assert r.status_code == 200, r.text
        status = r.json()
        if status["state"] in until:
            return status
        runs = list(sample_books.RUNS.values())
        assert len(runs) == 1, f"no run in this process, and the status is {status}"
        if runs[0].stopped.is_set():
            break
        await asyncio.wait_for(runs[0].stopped.wait(), SETTLE_TIMEOUT_S)
    raise AssertionError(f"stopped at {status}, waiting for {until}")


async def _facts(fake: FakeStorageProvider) -> dict[str, Any]:
    """What the judge sees, in a form two runs on different days of the clock can be compared by."""
    books = Books(fake)
    events = await books.list_events()
    lines = await books.stored_bank_lines()
    return {
        "events": len(events),
        "by": Counter(e.approved_by for e in events),
        "kinds": Counter(e.kind for e in events),
        "amounts": sorted(sum(ln.debit for ln in e.lines) for e in events),
        "proposals": Counter(p.status for p in await books.list_proposals()),
        "inbox": sorted(f.name for f in await books.list_files(INBOX)),
        "invoices": [(i.number, i.status, i.total_pence) for i in await invoicing.list_invoices(books)],
        "bank": Counter(ln.status for ln in lines),
        "rules": len(await autopilot.load_rules(books)),
        "files": sorted(p for p in fake.files if not p.startswith("_System/") and not p.startswith("07 Reports/")),
        "reports": len([p for p in fake.files if p.startswith("07 Reports/")]),
    }


def _audit(fake: FakeStorageProvider) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for path, data in sorted(fake.files.items())
        if path.startswith("_System/audit/") and path.count("/") == 2
        for line in data.decode().splitlines()
    ]


# --------------------------------------------------------------------------- #


async def test_loads_the_demo_books_into_an_empty_folder(done_books: FakeStorageProvider) -> None:
    fake = FakeStorageProvider()
    async with _client(fake) as client:
        before = (await client.get("/books/sample", headers=HEADERS)).json()
        assert before["state"] == "none" and before["empty"] is True
        started = await client.post("/books/sample", headers=HEADERS)
        assert started.status_code == 200, started.text
        body = started.json()
        assert body["state"] == "running" and body["done"] == 0 and body["total"] == len(body["steps"]) > 40
        assert body["business"] == "Bramblewood Joinery Ltd" and body["step"] == "Folders and business details"
        assert "today" not in body and "stagger" not in body
        status = await _settle(client)
    assert status["state"] == "done", status
    assert status["done"] == status["total"] and status["error"] is None and status["finished_at"]
    assert set(status) == {"state", "step", "done", "total", "steps", "error", "business", "empty"} | {
        "started_at",
        "updated_at",
        "finished_at",
    }
    stored = json.loads(fake.files[sample_books.STATUS])
    assert stored["state"] == "done" and stored["today"] == TODAY.isoformat() and stored["stagger"] == 1
    assert await _facts(fake) == await _facts(done_books)
    facts = await _facts(fake)
    assert facts["events"] == 59 and len(facts["inbox"]) == 25 and facts["reports"] == 1
    loaded = [a for a in _audit(fake) if a["action"] == "sample_books_loaded"]
    assert loaded == [
        {
            **loaded[0],
            "actor": "user:judge@example.com",
            "refs": {"business": "Bramblewood Joinery Ltd", "events": 59, "steps": status["total"]},
        }
    ]
    assert [a["action"] for a in _audit(fake)].count("sample_books_started") == 1
    assert not sample_books.RUNS  # a finished run leaves


class Held(Expiring):
    """Holds every write until `release` is set, so the run is certainly still going when the test presses again
    (sleeping in each write only made that likely, and made the run slow enough to outlast the test's polling)."""

    def __init__(self, inner: FakeStorageProvider) -> None:
        super().__init__(inner, None)
        self.release = asyncio.Event()

    async def write(self, path: str, data: bytes, *, if_match: str | None = None, create_only: bool = False) -> FileRef:
        await self.release.wait()
        return await super().write(path, data, if_match=if_match, create_only=create_only)


async def test_a_second_press_while_running_or_after_is_the_same_run(
    done_books: FakeStorageProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStorageProvider()
    held = Held(fake)
    _run_on(monkeypatch, held)
    async with _client(fake) as client:
        first = (await client.post("/books/sample", headers=HEADERS)).json()
        (run,) = sample_books.RUNS.values()
        again = await client.post("/books/sample/continue", headers={**HEADERS, "X-Graph-Token": "token-two"})
        assert again.status_code == 200 and again.json()["state"] == "running"
        assert list(sample_books.RUNS.values()) == [run]
        assert first["started_at"] == again.json()["started_at"]
        held.release.set()
        await _settle(client)
        files = dict(fake.files)
        after = await client.post("/books/sample", headers=HEADERS)
        assert after.status_code == 200 and after.json()["state"] == "done"
        await asyncio.sleep(0.05)
    assert fake.files == files  # nothing more written
    assert held.tokens == ["token-two"]  # the second press handed its token to the run
    assert [a["action"] for a in _audit(fake)].count("sample_books_loaded") == 1


@pytest.mark.parametrize("what", ["event", "proposal", "contact"])
async def test_refused_unless_the_folder_is_empty(done_books: FakeStorageProvider, what: str) -> None:
    fake = FakeStorageProvider()
    source = Books(done_books)
    if what == "event":
        await Books(fake).post_event((await source.list_events())[0])
    elif what == "proposal":
        await Books(fake).save_proposal((await source.list_proposals())[0])
    else:
        fake.files["_System/Contacts/contacts.json"] = done_books.files["_System/Contacts/contacts.json"]
    before = dict(fake.files)
    async with _client(fake) as client:
        status = (await client.get("/books/sample", headers=HEADERS)).json()
        assert status == {**status, "state": "none", "empty": False}
        r = await client.post("/books/sample", headers=HEADERS)
    assert r.status_code == 409
    assert r.json()["detail"].startswith("Your Accnomos folder already has books in it")
    assert fake.files == before and not sample_books.RUNS


async def test_a_folder_seeded_by_the_cli_is_refused(done_books: FakeStorageProvider) -> None:
    async with _client(done_books) as client:
        assert (await client.post("/books/sample", headers=HEADERS)).status_code == 409


@pytest.mark.parametrize("budget", [40, 2600])
async def test_token_expiry_mid_way_waits_for_a_fresh_one(
    done_books: FakeStorageProvider, budget: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run stops at the refused call (whatever step it is in), says needs_token, and the next POST's token
    lets it carry on from that step: the books come out the same as in one go."""
    fake = FakeStorageProvider()
    storage = Expiring(fake, budget)
    _run_on(monkeypatch, storage)
    async with _client(fake) as client:
        await client.post("/books/sample", headers=HEADERS)
        status = await _settle(client, until=("needs_token", "done", "failed"))
        assert status["state"] == "needs_token", status
        assert status["error"] == sample_books.NEEDS_TOKEN and 0 <= status["done"] < status["total"]
        status = (await client.post("/books/sample/continue", headers={**HEADERS, "X-Graph-Token": "token-two"})).json()
        assert status["state"] in ("running", "needs_token")
        status = await _settle(client)
    assert status["state"] == "done", status
    assert storage.tokens == ["token-two"] and storage.refused >= 1
    assert await _facts(fake) == await _facts(done_books)


@pytest.mark.parametrize("budget", [300, 1700])
async def test_resumes_from_the_recorded_step_after_a_restart(
    done_books: FakeStorageProvider, budget: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No fresh token in time (or the runtime restarted): the run is gone, the file still says running. Once that
    is stale, GET says needs_token and a POST starts a new run from the recorded step."""
    monkeypatch.setattr(sample_books, "TOKEN_WAIT_S", 0.01)
    fake = FakeStorageProvider()
    _run_on(monkeypatch, Expiring(fake, budget))
    async with _client(fake) as client:
        await client.post("/books/sample", headers=HEADERS)
        for _ in range(2000):
            (run,) = sample_books.RUNS.values()
            if run.task and run.task.done():
                break
            await asyncio.sleep(0.01)
        recorded = json.loads(fake.files[sample_books.STATUS])
        assert recorded["state"] == "running" and recorded["done"] < recorded["total"]
        sample_books.RUNS.clear()  # the runtime restarted
        stale = datetime.now(UTC) - timedelta(seconds=sample_books.STALE_S + 5)
        fake.files[sample_books.STATUS] = json.dumps({**recorded, "updated_at": stale.isoformat()}).encode()
    _run_on(monkeypatch, fake)  # the new run has the fresh token
    async with _client(fake) as client:
        status = (await client.get("/books/sample", headers=HEADERS)).json()
        assert status["state"] == "needs_token" and status["error"] == sample_books.STOPPED
        resumed = (await client.post("/books/sample", headers=HEADERS)).json()
        assert resumed["state"] == "running" and resumed["done"] == recorded["done"]
        assert resumed["started_at"] == recorded["started_at"]
        status = await _settle(client)
    assert status["state"] == "done", status
    assert await _facts(fake) == await _facts(done_books)
    assert [a["action"] for a in _audit(fake)].count("sample_books_started") == 1


class RefusedAt(Expiring):
    """The token "expires" at a chosen moment: on the first write or move whose path matches `pattern` (and whose
    data contains `content`), refused (`after` False) or done and then everything after it refused (`after` True)."""

    def __init__(
        self, inner: FakeStorageProvider, pattern: str, *, content: bytes | tuple[bytes, ...] = b"", after: bool = False
    ) -> None:
        super().__init__(inner, None)
        self.pattern, self.after, self.fired = re.compile(pattern), after, False
        self.content = content if isinstance(content, tuple) else (content,)

    def _hit(self, path: str, data: bytes = b"") -> bool:
        if self.fired or not self.pattern.search(path) or not all(c in data for c in self.content):
            return False
        self.fired = True
        return True

    async def write(self, path: str, data: bytes, *, if_match: str | None = None, create_only: bool = False) -> FileRef:
        if self._hit(path, data):
            self.left = 0
            if self.after:
                self.left = None
                ref = await super().write(path, data, if_match=if_match, create_only=create_only)
                self.left = 0
                return ref
        return await super().write(path, data, if_match=if_match, create_only=create_only)

    async def move(self, path: str, new_path: str) -> FileRef:
        if self._hit(new_path):
            self.left = 0
            if self.after:
                self.left = None
                ref = await super().move(path, new_path)
                self.left = 0
                return ref
        return await super().move(path, new_path)


# The narrow windows a resumed step has to repair: each refuses the token between two writes of one action.
WINDOWS = {
    "document filed, not yet recorded": dict(pattern=r"^01 Receipts/", after=True),
    "approval posted, proposal not saved": dict(pattern=r"^_System/Ledger/events/", after=True),
    "autopilot posted, proposal not saved": dict(
        pattern=r"^_System/Ledger/events/", content=b'"autopilot"', after=True
    ),
    "invoice saved as sent, PDF not written": dict(pattern=r"^03 Sales/invoices/sent/INV-0001\.pdf$"),
    "statement filed, lines not stored": dict(pattern=r"^04 Bank statements/"),
    "payment posted, no record": dict(pattern=r"^_System/Ledger/events/", content=b"Payment for", after=True),
    "payment recorded, line not matched": dict(pattern=r"^_System/Payments/payments\.json$", after=True),
    "rule coding proposed, not linked": dict(pattern=r"^_System/proposals/", content=b'"bank-line"', after=True),
    "rule coding posted, proposal not saved": dict(
        pattern=r"^_System/proposals/", content=(b'"bank-line"', b'"posted"')
    ),
    "emailed receipt copied, not recorded": dict(pattern=r"^00 Inbox/2026-", after=True),
}


@pytest.mark.parametrize("window", sorted(WINDOWS))
async def test_a_token_refused_inside_one_action_is_repaired_on_resume(
    done_books: FakeStorageProvider, window: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStorageProvider()
    storage = RefusedAt(fake, **WINDOWS[window])  # type: ignore[arg-type]
    _run_on(monkeypatch, storage)
    async with _client(fake) as client:
        await client.post("/books/sample", headers=HEADERS)
        assert (await _settle(client, until=("needs_token", "done", "failed")))["state"] == "needs_token"
        await client.post("/books/sample/continue", headers={**HEADERS, "X-Graph-Token": "token-two"})
        status = await _settle(client)
    assert storage.fired and status["state"] == "done", status
    assert await _facts(fake) == await _facts(done_books)


async def test_a_quiet_run_elsewhere_is_left_alone_until_stale() -> None:
    """Another runtime process is running it (recent progress, no run here): a POST only reports it."""
    fake = FakeStorageProvider()
    now = datetime.now(UTC).isoformat()
    fake.files[sample_books.STATUS] = json.dumps(
        {"state": "running", "done": 3, "total": 57, "updated_at": now, "started_at": now, "today": "2026-10-27"}
    ).encode()
    async with _client(fake) as client:
        r = (await client.post("/books/sample", headers=HEADERS)).json()
    assert r["state"] == "running" and r["done"] == 3 and not sample_books.RUNS


async def test_a_failure_is_a_plain_sentence_and_press_again_carries_on(
    done_books: FakeStorageProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStorageProvider()
    _run_on(monkeypatch, Breaking(fake, at=150))
    async with _client(fake) as client:
        await client.post("/books/sample", headers=HEADERS)
        status = await _settle(client)
        assert status["state"] == "failed"
        assert status["error"].startswith("OneDrive refused a request (HTTP 500) at “")
        assert "eyJ" not in json.dumps(status) and "/Users" not in json.dumps(status)
        assert "eyJ" not in fake.files[sample_books.STATUS].decode()
        status = (await client.post("/books/sample", headers=HEADERS)).json()
        assert status["state"] == "running" and status["error"] is None
        status = await _settle(client)
    assert status["state"] == "done"
    assert await _facts(fake) == await _facts(done_books)


async def test_resuming_refuses_books_someone_else_added_to(
    done_books: FakeStorageProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStorageProvider()
    _run_on(monkeypatch, Breaking(fake, at=400))
    async with _client(fake) as client:
        await client.post("/books/sample", headers=HEADERS)
        assert (await _settle(client))["state"] == "failed"
        ev = (await Books(done_books).list_events())[0]
        await Books(fake).post_event(ev.model_copy(update={"approved_by": "someone@example.com", "id": "f" * 32}))
        r = await client.post("/books/sample", headers=HEADERS)
    assert r.status_code == 409 and "did not come from the sample books" in r.json()["detail"]


async def test_rate_limited_per_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sample_books, "LIMITER", TokenBucket(2))
    one, two = FakeStorageProvider(), FakeStorageProvider()
    async with _client(one) as client:
        codes = [(await client.post("/books/sample", headers=HEADERS)).status_code for _ in range(3)]
        assert codes == [200, 200, 429]
        r = await client.post("/books/sample", headers=HEADERS)
        assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
        await _settle(client)
    async with _client(two) as client:  # someone else's folder has its own budget
        assert (await client.post("/books/sample", headers=HEADERS)).status_code == 200
        await _settle(client)


async def test_needs_a_token_and_a_user() -> None:
    app.dependency_overrides.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/books/sample")).status_code == 401
        assert (await client.post("/books/sample")).status_code == 401
    async with _client(FakeStorageProvider()) as client:
        r = await client.post("/books/sample", headers={"X-Graph-Token": "t"})
    assert r.status_code == 400


@pytest.fixture(autouse=True)
def _no_overrides() -> Any:
    yield
    app.dependency_overrides.clear()


def test_the_runtime_image_carries_the_seed() -> None:
    """app/sample_books.py finds tools/seed_demo.py, evals/gold and the renderer next to services/runtime."""
    docker = (TOOL.parents[1] / "deploy" / "Dockerfile.runtime").read_text()
    for src, dest in (
        ("tools/seed_demo.py", "/srv/tools/seed_demo.py"),
        ("evals/gold", "/srv/evals/gold"),
        ("evals/harness/render.py", "/srv/evals/harness/render.py"),
    ):
        assert f"COPY {src} {dest}" in docker
    assert "COPY services/runtime /srv/services/runtime" in docker


async def test_the_run_and_its_key_never_use_the_request_memo() -> None:
    """get_books wraps storage in the per-request memo (app/cache.py). The background run outlives the request, and
    every request for one folder must find the same run, so both look under the memo."""
    fake = FakeStorageProvider()
    first, second = Books(fake, cache_key="a"), Books(fake, cache_key="b")
    assert first.storage is not fake  # the memo is really there
    assert await sample_books.folder_key(first, "personal") == await sample_books.folder_key(second, "personal")
    storage, owns = sample_books._own_storage(first, "token", "personal")
    assert storage is fake and not owns
