"""app/cache.py: per-request memoisation and the per-user cache of immutable files.

The rules under test (docs/ARCHITECTURE.md): repeated reads inside one request
cost one round trip; posted ledger events are cached across requests for the
same user only; mutable files are never shared between requests; the cache has
size limits; the user key never holds a token.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger.events import LedgerEvent, Line
from app import cache
from app.books import Books


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


class CountingStorage(FakeStorageProvider):
    """Fake OneDrive that counts Graph-like calls."""

    def __init__(self) -> None:
        super().__init__()
        self.lists = 0
        self.reads = 0

    async def list(self, path: str):  # noqa: ANN201
        self.lists += 1
        return await super().list(path)

    async def read(self, path: str) -> bytes:
        self.reads += 1
        return await super().read(path)


def _event() -> LedgerEvent:
    return LedgerEvent(
        kind="purchase",
        date=date(2026, 9, 15),
        lines=[
            Line(account="5100 Tools", debit=120, credit=0),
            Line(account="1200 Bank", debit=0, credit=120),
        ],
        approved_by="user:test@example.com",
        approved_at=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
        counterparty="Screwfix",
    )


async def test_repeated_reads_in_one_request_cost_one_round_trip() -> None:
    raw = CountingStorage()
    await raw.write("_System/Contacts/contacts.json", b"[]")
    books = Books(raw, cache_key="user-a")
    assert await books.read_json("_System/Contacts/contacts.json", None) == []
    assert await books.read_json("_System/Contacts/contacts.json", None) == []
    await books.list_files("_System/Contacts")
    await books.list_files("_System/Contacts")
    assert raw.reads == 1
    assert raw.lists == 1


async def test_books_without_a_cache_key_reads_everything_through() -> None:
    raw = CountingStorage()
    books = Books(raw)
    await books.post_event(_event())
    reads = raw.reads
    await books.list_events()
    await books.list_events()
    assert raw.reads > reads + 1  # no memoisation: every read is a round trip


async def test_a_request_sees_its_own_writes() -> None:
    books = Books(CountingStorage(), cache_key="user-a")
    await books.write_json("_System/Contacts/contacts.json", [])
    assert await books.read_json("_System/Contacts/contacts.json", None) == []
    await books.write_json("_System/Contacts/contacts.json", [{"name": "Screwfix"}])
    assert await books.read_json("_System/Contacts/contacts.json", None) == [{"name": "Screwfix"}]


async def test_posted_events_are_cached_for_the_same_user_only() -> None:
    raw = CountingStorage()
    await Books(raw, cache_key="user-a").post_event(_event())
    same = Books(raw, cache_key="user-a")
    reads = raw.reads
    assert len(await same.list_events()) == 1
    assert raw.reads == reads  # the event file came from the process cache; only listings hit storage

    other = Books(raw, cache_key="user-b")
    assert len(await other.list_events()) == 1
    assert raw.reads == reads + 1  # another user re-reads the file


async def test_mutable_files_are_never_shared_between_requests() -> None:
    raw = CountingStorage()
    path = "_System/Contacts/contacts.json"
    await Books(raw, cache_key="user-a").write_json(path, [])
    await raw.write(path, b'[{"name": "Screwfix"}]')  # someone else wrote (another tab, the phone app)
    assert await Books(raw, cache_key="user-a").read_json(path, None) == [{"name": "Screwfix"}]


def test_only_event_files_count_as_immutable() -> None:
    assert cache.is_immutable("_System/Ledger/events/2026-09/20260915T120000Z-runtime-abc.json")
    assert not cache.is_immutable("_System/proposals/abc.json")
    assert not cache.is_immutable("_System/bank/abc.json")
    assert not cache.is_immutable("_System/Ledger/events/2026-09/not-an-event.txt")


def test_immutable_cache_has_size_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache, "MAX_FILES", 3)
    for i in range(4):
        cache.put_cached("u", f"_System/Ledger/events/2026-09/000{i}.json", b"x" * 10)
    assert cache.stats()["files"] == 3
    assert cache.get_cached("u", "_System/Ledger/events/2026-09/0000.json") is None
    assert cache.get_cached("u", "_System/Ledger/events/2026-09/0003.json") == b"x" * 10


def test_mutable_and_oversized_files_are_never_cached() -> None:
    cache.put_cached("u", "_System/proposals/abc.json", b"x" * 10)
    cache.put_cached("u", "_System/Ledger/events/2026-09/big.json", b"x" * (cache.MAX_BYTES + 1))
    assert cache.stats() == {"files": 0, "bytes": 0}


def test_user_key_is_a_hash_not_the_token() -> None:
    key = cache.user_cache_key("my-graph-token")
    assert key != "my-graph-token" and "token" not in key
    assert cache.user_cache_key("my-graph-token") == key  # stable
    assert cache.user_cache_key("my-graph-token", "worker-2") != key
    assert cache.user_cache_key("another-token") != key


async def test_conflict_retry_reads_past_the_memo() -> None:
    """Another device writes between this request's read and its write: the If-Match retry must
    re-read storage (not the memo), keep the other write, and succeed."""
    inner = FakeStorageProvider()
    books = Books(inner, cache_key="u1")
    await books.write_json("_System/notes.json", ["a"])
    assert await books.read_json("_System/notes.json", []) == ["a"]  # memoised now
    await inner.write("_System/notes.json", b'["a", "other device"]')  # behind the memo's back
    await books._update_json("_System/notes.json", [], lambda old: [*old, "mine"])
    assert await Books(inner).read_json("_System/notes.json", []) == ["a", "other device", "mine"]


async def test_create_only_loser_sees_the_winner() -> None:
    """Two requests claim the same new file: the loser's retry must see the winner's claim (app/actions.py)."""
    inner = FakeStorageProvider()
    books = Books(inner, cache_key="u1")
    assert await books.read_json("_System/claim.json", None) is None
    await books.list_files("_System")  # memoise a listing without the file
    await inner.write("_System/claim.json", b'{"by": "winner"}')
    await books._update_json("_System/claim.json", {}, lambda old: {**old, "seen": True})
    assert await Books(inner).read_json("_System/claim.json", {}) == {"by": "winner", "seen": True}


class PathLog(FakeStorageProvider):
    """Fake OneDrive that records the path of every read."""

    def __init__(self) -> None:
        super().__init__()
        self.read_paths: list[str] = []

    async def read(self, path: str) -> bytes:
        self.read_paths.append(path.strip("/"))
        return await super().read(path)


async def test_a_second_request_by_the_same_user_reads_no_event_file_twice() -> None:
    """Events written behind the runtime's back (the phone app, another server): the first request reads each
    once, a second request by the same user reads none of them again, however many event reads it makes."""
    raw = PathLog()
    for month in (8, 9):
        for n in range(3):
            ev = _event().model_copy(update={"date": date(2026, month, 10 + n)})
            await Books(raw).post_event(ev)  # no cache key: nothing reaches the process cache
    raw.read_paths.clear()

    first = Books(raw, cache_key=cache.user_cache_key("token-a"))
    assert len(await first.list_events()) == 6
    second = Books(raw, cache_key=cache.user_cache_key("token-a"))
    assert len(await second.list_events()) == 6
    assert len(await second.list_events(date(2026, 9, 1), date(2026, 9, 30))) == 3

    event_reads = [p for p in raw.read_paths if cache.is_immutable(p)]
    assert len(event_reads) == 6
    assert len(set(event_reads)) == len(event_reads)  # no event file was read twice across the two requests

    third = Books(raw, cache_key=cache.user_cache_key("token-b"))  # another user pays for their own reads
    assert len(await third.list_events()) == 6
    assert len([p for p in raw.read_paths if cache.is_immutable(p)]) == 12
