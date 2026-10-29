"""Earlier files: documents already in the books folders that Accnomos never read.

Someone who used the app before, or who dropped receipts into OneDrive by hand, can have documents waiting in
00 Inbox, 01 Receipts or 02 Needs a look that no proposal points at. On first connect, and whenever the user asks,
the app lists them and asks before reading any of them (AI proposes, the user approves, as for every document):

    find      every readable document (app/formats.py's types) in those three folders that nothing in the books
              points at (app/files.py `links`: no proposal's file, no bank statement's lines), minus the ones the
              user chose to leave alone. Reads only; downloads nothing.
    queue     the user ticked some and pressed "Read them": the ones outside the Inbox move into 00 Inbox (each
              keeps its name or gets " (2)"; the move is recorded so links follow), then the app runs the usual
              Inbox scan, which turns each into a Review card. Only files `find` lists can be queued.
    leave     the user chose "Leave them": remembered in _System/Settings/previous-files.json, so they are not
              offered again. Nothing moves.

Audited as `previous_files_queued` and `previous_files_left`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from pydantic import BaseModel

from app import files as fm
from app.books import SYSTEM, Books
from app.formats import guess_mime
from app.paths import INBOX, NEEDS_A_LOOK, RECEIPTS

STATE = f"{SYSTEM}/Settings/previous-files.json"
FOLDERS = (INBOX, RECEIPTS, NEEDS_A_LOOK)
MAX_LEFT = 5_000


class FileError(ValueError):
    """A queue or leave the app refuses; the message says why."""


class PreviousFile(BaseModel):
    path: str
    name: str
    folder: str  # INBOX, RECEIPTS or NEEDS_A_LOOK
    size: int
    modified: datetime | None
    web_url: str | None


class PreviousFiles(BaseModel):
    files: list[PreviousFile]  # oldest first
    count: int
    left_alone: int  # files the user chose to leave, not listed
    truncated: bool


class QueueResult(BaseModel):
    queued: int
    moved: list[fm.Moved]
    already_in_inbox: int


async def _left(books: Books) -> set[str]:
    raw = await books.read_json(STATE, {})
    left = raw.get("left", []) if isinstance(raw, dict) else []
    return {p for p in left if isinstance(p, str)}


async def find(books: Books) -> PreviousFiles:
    walks, linked, left = await asyncio.gather(
        asyncio.gather(*(fm.walk(books, f) for f in FOLDERS)), fm.links(books), _left(books)
    )
    out: list[PreviousFile] = []
    skipped = 0
    for folder, w in zip(FOLDERS, walks, strict=True):
        for f in w.files:
            if not guess_mime(f.name) or f.path in linked:
                continue
            if f.path in left:
                skipped += 1
                continue
            out.append(
                PreviousFile(
                    path=f.path, name=f.name, folder=folder, size=f.size, modified=f.modified, web_url=f.web_url
                )
            )
    out.sort(key=lambda f: (f.modified.timestamp() if f.modified else 0.0, f.path))
    return PreviousFiles(files=out, count=len(out), left_alone=skipped, truncated=any(w.truncated for w in walks))


async def _chosen(books: Books, paths: list[str]) -> list[PreviousFile]:
    wanted = list(dict.fromkeys(p.strip("/") for p in paths))
    if not wanted or len(wanted) > fm.MAX_BATCH:
        raise FileError(f"Choose between 1 and {fm.MAX_BATCH} files")
    listed = {f.path: f for f in (await find(books)).files}
    unknown = [p for p in wanted if p not in listed]
    if unknown:
        raise FileError(f"{unknown[0]} is not one of the earlier files waiting to be read")
    return [listed[p] for p in wanted]


async def queue(books: Books, paths: list[str], user: str) -> QueueResult:
    chosen = await _chosen(books, paths)
    outside = [f.path for f in chosen if f.folder != INBOX]
    moved = await fm.move_files(books, outside, INBOX, user) if outside else []
    await books.audit(
        f"user:{user}",
        "previous_files_queued",
        {"files": [f.path for f in chosen], "moved_to_inbox": [m.model_dump() for m in moved]},
    )
    return QueueResult(queued=len(chosen), moved=moved, already_in_inbox=len(chosen) - len(outside))


async def leave(books: Books, paths: list[str], user: str) -> int:
    chosen = await _chosen(books, paths)
    left = await _left(books)
    if len(left) + len(chosen) > MAX_LEFT:
        raise FileError("Too many files left alone to remember; move some of them out of the books folders")
    await books.write_json(STATE, {"left": sorted(left | {f.path for f in chosen})})
    await books.audit(f"user:{user}", "previous_files_left", {"files": [f.path for f in chosen]})
    return len(chosen)
