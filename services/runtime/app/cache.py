"""Fewer OneDrive round trips: per-request memoisation plus a small per-user cache of immutable files.

Every read of the books is a Graph call, so routes that read the same file
twice in one request pay twice. Two layers cut that:

1. Per-request memoisation. Each ``Books`` built with a ``cache_key`` wraps its
   storage in ``RequestMemoStorage`` (see ``Books.__init__``): repeated ``list``/``read``
   of the same path within one request hits the memo, and writes/moves drop
   only the paths they change. A miss is memoised too (a file or folder that is
   not there costs one round trip per request, not one per look); any write,
   move or new folder forgets every remembered miss. A ``Books`` lives for one
   request, so nothing mutable is ever shared between requests here.
2. Per-user immutable cache. Posted ledger events
   (``_System/Ledger/events/...``) are append-only: a file, once written, never
   changes. Their bytes are kept in a small in-process LRU keyed by
   (user, path), so the next request by the same user skips re-reading them.
   Mutable files are never put there, and users never share entries: the key
   holds a hash of the caller's token (plus the test tenant in test mode), not
   the token itself.

Caching rules (also in ``docs/ARCHITECTURE.md``):

* per request: memoise every repeated read, misses included; list each folder once;
* across requests: only immutable event files, only for the same user;
* never cache across users; never cache mutable files beyond one request.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

from accnomos_connectors.base import FileRef, StorageProvider

#: Posted ledger events live under here and never change once written.
IMMUTABLE_PREFIX = "_System/Ledger/events/"

#: Bounds for the in-process immutable cache: about a thousand small event files.
MAX_FILES = 1000
MAX_BYTES = 8 * 1024 * 1024

#: Round trips one request may have in flight at once (the parallel reads in Books), so a big book
#: does not fire hundreds of Graph calls together and get throttled.
MAX_IN_FLIGHT = 8

_cache: OrderedDict[tuple[str, str], bytes] = OrderedDict()
_cache_bytes = 0


def user_cache_key(token: str, tenant: str = "") -> str:
    """The immutable-cache user key: a hash, so no token is kept in memory."""
    return hashlib.sha256(f"{tenant}\x00{token}".encode()).hexdigest()


def _norm(path: str) -> str:
    return path.strip("/")


def is_immutable(path: str) -> bool:
    """Only posted ledger event files count as immutable (callers: never add mutable paths here)."""
    return _norm(path).startswith(IMMUTABLE_PREFIX) and _norm(path).endswith(".json")


def get_cached(user_key: str, path: str) -> bytes | None:
    """Immutable bytes for this user, or None. Refreshes the entry's LRU position."""
    global _cache
    key = (user_key, _norm(path))
    try:
        data = _cache.pop(key)
    except KeyError:
        return None
    _cache[key] = data
    return data


def put_cached(user_key: str, path: str, data: bytes) -> None:
    """Keep immutable bytes for this user, evicting the oldest entries past the size limits."""
    global _cache_bytes
    if not is_immutable(path) or len(data) > MAX_BYTES:
        return
    key = (user_key, _norm(path))
    if key in _cache:
        _cache_bytes -= len(_cache.pop(key))
    _cache[key] = data
    _cache_bytes += len(data)
    while len(_cache) > MAX_FILES or _cache_bytes > MAX_BYTES:
        _, old = _cache.popitem(last=False)
        _cache_bytes -= len(old)


def drop_cached(user_key: str, path: str) -> None:
    """Forget one entry (used when its file is rewritten, which events never are — belt and braces)."""
    global _cache_bytes
    key = (user_key, _norm(path))
    if key in _cache:
        _cache_bytes -= len(_cache.pop(key))


def clear(user_key: str | None = None) -> None:
    """Forget cached immutable files: all of them, or one user's (tests and the bench harness)."""
    global _cache_bytes
    if user_key is None:
        _cache.clear()
        _cache_bytes = 0
        return
    for key in [k for k in _cache if k[0] == user_key]:
        _cache_bytes -= len(_cache.pop(key))


def stats() -> dict[str, int]:
    return {"files": len(_cache), "bytes": _cache_bytes}


class RequestMemoStorage(StorageProvider):
    """A per-request view over another provider: memoises ``list``/``read``.

    One instance serves one request (``Books`` makes its own). Repeated reads
    of the same path and repeated listings of the same folder cost one round
    trip; a write/move forgets exactly the paths it changes, so a request
    always reads its own writes. Immutable event files additionally consult the
    per-user process cache when ``user_key`` is set.
    """

    def __init__(self, inner: StorageProvider, user_key: str | None = None) -> None:
        self.inner = inner
        self.user_key = user_key
        self.lists: dict[str, list[FileRef]] = {}
        self.reads: dict[str, bytes] = {}
        # Paths a read or list found missing in this request. Any write, move or ensure_folder clears both sets:
        # it may have created the file or a folder above it, and being conservative costs one round trip at most.
        self.missing_reads: set[str] = set()
        self.missing_lists: set[str] = set()
        self._gate = asyncio.Semaphore(MAX_IN_FLIGHT)
        # Round trips in flight, by (kind, path): concurrent looks at the same path share one. `_epoch` counts the
        # changes made through this view; a result that lands after one is handed back but not memoised.
        self._flights: dict[tuple[str, str], asyncio.Future[Any]] = {}
        self._epoch = 0

    @staticmethod
    def _parent(path: str) -> str:
        parent, _, _ = _norm(path).rpartition("/")
        return parent

    # -- reads ----------------------------------------------------------- #

    async def ensure_root(self) -> FileRef:
        return await self.inner.ensure_root()

    async def ensure_folder(self, path: str) -> FileRef:
        self._forget_misses()
        return await self.inner.ensure_folder(path)

    async def _shared[T](self, kind: str, key: str, fetch: Callable[[], Awaitable[T]]) -> T:
        """`fetch()` once for every concurrent look at (kind, key). A caller that is cancelled does not cancel the
        round trip the others are waiting for."""
        flight = self._flights.get((kind, key))
        if flight is None:

            async def run() -> T:
                try:
                    async with self._gate:
                        return await fetch()
                finally:
                    if self._flights.get((kind, key)) is flight:
                        del self._flights[(kind, key)]

            flight = asyncio.ensure_future(run())
            self._flights[(kind, key)] = flight
            flight.add_done_callback(lambda f: f.cancelled() or f.exception())  # never "exception not retrieved"
        return await asyncio.shield(flight)

    async def list(self, path: str) -> list[FileRef]:
        key = _norm(path)
        if key in self.missing_lists:
            raise FileNotFoundError(path)
        if key in self.lists:
            return list(self.lists[key])
        epoch = self._epoch

        async def fetch() -> list[FileRef]:
            try:
                got = await self.inner.list(path)
            except FileNotFoundError:
                if self._epoch == epoch:
                    self.missing_lists.add(key)
                raise
            if self._epoch == epoch:
                self.lists[key] = got
            return got

        return list(await self._shared("list", key, fetch))

    async def read(self, path: str) -> bytes:
        key = _norm(path)
        hit = self.reads.get(key)
        if hit is None and self.user_key is not None and is_immutable(key):
            hit = get_cached(self.user_key, key)
            if hit is not None:
                self.reads[key] = hit
        if hit is not None:
            return hit
        if key in self.missing_reads:
            raise FileNotFoundError(path)
        epoch = self._epoch

        async def fetch() -> bytes:
            try:
                got = await self.inner.read(path)
            except FileNotFoundError:
                if self._epoch == epoch:
                    self.missing_reads.add(key)
                raise
            if self._epoch == epoch:
                self.reads[key] = got
            if self.user_key is not None and is_immutable(key):
                put_cached(self.user_key, key, got)  # immutable: safe to keep whatever changed meanwhile
            return got

        return await self._shared("read", key, fetch)

    # -- writes: forget what they change --------------------------------- #

    def _changed(self) -> None:
        """Something changed through this view: results still in flight are not memoised, new looks go out afresh."""
        self._epoch += 1
        self._flights.clear()

    def _forget_misses(self) -> None:
        self._changed()
        self.missing_reads.clear()
        self.missing_lists.clear()

    def _forget_read(self, path: str) -> None:
        self._changed()
        key = _norm(path)
        self.reads.pop(key, None)
        self.missing_reads.discard(key)
        if self.user_key is not None:
            drop_cached(self.user_key, key)

    def _forget_list(self, folder: str) -> None:
        """Forget the folder's listing and every ancestor's: a write can create the folder itself (the first event
        of a month creates `events/<month>`), which changes the parent's listing too."""
        self._changed()
        key = _norm(folder)
        while True:
            self.lists.pop(key, None)
            if not key:
                return
            key = self._parent(key)

    def forget(self, path: str) -> None:
        """Drop the memo for one file and its folder listing, so the next stat and read reach storage.
        Books._update calls this before a read-modify-write: the bytes it changes and the etag it sends
        must be what storage holds now, or another device's write could be lost."""
        self._changed()
        self.reads.pop(_norm(path), None)
        self.missing_reads.discard(_norm(path))
        self._forget_list(self._parent(path))
        self.missing_lists.discard(self._parent(path))

    async def write(self, path: str, data: bytes, *, if_match: str | None = None, create_only: bool = False) -> FileRef:
        self._forget_misses()  # first, whatever happens: a refused create-only write means the file is there now
        try:
            ref = await self.inner.write(path, data, if_match=if_match, create_only=create_only)
        except BaseException:
            # A refused conditional write (If-Match or create-only) means someone else changed the file:
            # Books._update retries by listing and reading again, which must reach storage, not this memo.
            self._forget_read(path)
            self._forget_list(self._parent(path))
            raise
        self._forget_list(self._parent(path))
        # A blind in-request memo must not hide this write; the immutable
        # cache only ever holds event files, which are written once and never
        # rewritten, so record what was just written.
        self.reads[_norm(path)] = data
        if self.user_key is not None and is_immutable(path):
            put_cached(self.user_key, path, data)
        return ref

    async def move(self, path: str, new_path: str) -> FileRef:
        self._forget_misses()
        ref = await self.inner.move(path, new_path)
        self._forget_read(path)
        self._forget_read(new_path)
        self._forget_list(self._parent(path))
        self._forget_list(self._parent(new_path))
        return ref

    async def changes(self, cursor: str | None) -> tuple[list[FileRef], str]:
        return await self.inner.changes(cursor)
