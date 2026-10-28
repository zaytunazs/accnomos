"""Move folders that still carry an old name (app/paths.py RENAMED) to their current name, once.

Runs on the first request a sign-in makes (routes_books.get_books), before anything reads or writes the books:
    old name present, new name absent  -> move the old folder (one Graph PATCH of its name; everything inside goes
                                          with it) and write one audit line, action "folders_renamed"
    both present                       -> leave both and report a conflict (GET /books/layout, the Files page, and
                                          a count in /health); the user moves the files themselves
    neither, or only the new one       -> nothing
Never copies, never deletes, so running it again changes nothing.
"""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict

from pydantic import BaseModel, computed_field

from app.books import Books
from app.paths import RENAMED

log = logging.getLogger(__name__)
ACTOR = "agent:folder-layout"


class Renamed(BaseModel):
    old: str
    new: str


class Conflict(BaseModel):
    old: str  # as the folder is spelt in the user's storage
    new: str
    old_is_empty: bool


class LayoutStatus(BaseModel):
    moved: list[Renamed] = []
    conflicts: list[Conflict] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def warning(self) -> str | None:
        if not self.conflicts:
            return None
        pairs = "; ".join(f"{c.old} and {c.new}" for c in self.conflicts)
        return (
            f"Your books folder has both an old and a new folder: {pairs}. Accnomos uses the new one. "
            "Move anything you still need out of the old one; you can delete it once it is empty."
        )


async def migrate(books: Books) -> LayoutStatus:
    status = LayoutStatus()
    try:
        top = {f.name.casefold(): f for f in await books.storage.list("") if f.is_folder}
    except FileNotFoundError:
        return status  # no books folder yet: nothing to rename
    for old, new in RENAMED.items():
        found = top.get(old.casefold())
        if found is None:
            continue
        if new.casefold() in top:
            try:
                empty = not await books.storage.list(found.name)
            except FileNotFoundError:
                empty = True
            status.conflicts.append(Conflict(old=found.name, new=new, old_is_empty=empty))
            continue
        try:
            await books.storage.move(found.name, new)
        except Exception:
            # The first requests of a sign-in run this at the same time (Home loads several at once): another may
            # have renamed it a moment ago. That is not a failure of this request; anything else still is.
            now = {f.name.casefold() for f in await books.storage.list("") if f.is_folder}
            if old.casefold() in now or new.casefold() not in now:
                raise
            continue
        top[new.casefold()] = found
        status.moved.append(Renamed(old=found.name, new=new))
    if status.moved:
        await books.audit(ACTOR, "folders_renamed", {"moved": [m.model_dump() for m in status.moved]})
        log.info("renamed %d old books folders", len(status.moved))
    return status


# --------------------------------------------------------------------------- #
# Once per sign-in token (a token lasts about an hour), and what /health shows
# --------------------------------------------------------------------------- #

_SEEN: OrderedDict[str, LayoutStatus] = OrderedDict()
_SEEN_MAX = 2000
COUNTS = {"checks": 0, "folders_renamed": 0, "checks_with_conflicts": 0}  # a user is checked again on each new token


def _key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def on_first_contact(books: Books, token: str, *, cache: bool = True) -> LayoutStatus | None:
    """migrate() unless this token has already been checked. A failure is logged, never raised: the request goes
    on (and will hit the same storage error itself if there is one), and the next request tries again."""
    key = _key(token)
    if cache and key in _SEEN:
        _SEEN.move_to_end(key)
        return _SEEN[key]
    try:
        status = await migrate(books)
    except Exception:  # noqa: BLE001
        log.warning("folder rename check failed", exc_info=True)
        return None
    COUNTS["checks"] += 1
    COUNTS["folders_renamed"] += len(status.moved)
    COUNTS["checks_with_conflicts"] += bool(status.conflicts)
    if cache:
        _SEEN[key] = status
        while len(_SEEN) > _SEEN_MAX:
            _SEEN.popitem(last=False)
    return status


def health() -> dict[str, int | str]:
    """No user data: counts since the runtime started, plus a warning when some books need a person."""
    out: dict[str, int | str] = dict(COUNTS)
    if COUNTS["checks_with_conflicts"]:
        out["warning"] = "Some books folders have an old and a new folder side by side; the Files page explains."
    return out
