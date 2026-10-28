"""File management for big books: the storage overview, the file index the Files page searches, moves, renames and
_Trash. Archiving by year is app/archive.py, backups app/backups.py; routes in app/routes_files.py.

Rules (docs/ARCHITECTURE.md, "Files, archive and backups"):

* Nothing is ever deleted. What the app would delete goes to _Trash/{date}/{original path}; the user empties
  _Trash in OneDrive.
* Ledger events, proposals and everything else in _System are never moved here, nor are the files other modules
  read by a fixed path: invoice and credit note records and PDFs (03 Sales/invoices, 03 Sales/credit-notes),
  saved VAT returns (06 VAT returns, read for the submitted-period lock), Books.xlsx and README.txt.
* Every move the app makes is recorded in _System/archive/map.json (Books.record_moves), so a proposal's
  file_path and a bank line's source_file still lead to the document.
* Each folder is listed once per request (the request memo, app/cache.py); content hashes come from the listing
  (FileRef.content_hash) and only same-size files without one are read and hashed.
"""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import posixpath
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel

from accnomos_connectors.base import FileRef
from app.books import Books, follow
from app.books import today as current_date
from app.paths import (
    ARCHIVE,
    BACKUPS,
    BANK,
    CREDIT_NOTES,
    INBOX,
    INVOICES,
    NEEDS_A_LOOK,
    PAYROLL,
    RECEIPTS,
    REPORTS,
    SALES,
    SYSTEM,
    TRASH,
    VAT_RETURNS,
)
from app.validation import MAX_NAME, UnsafeName, check_name

ACTOR = "agent:files"
#: A walk stops after this many files (the overview then says it is partial).
MAX_WALK_FILES = 20_000
#: Same-size files without a listed hash are read and hashed only up to this size each, and this many in all.
MAX_HASH_READ_BYTES = 20 * 1024 * 1024
MAX_HASH_READS = 200
#: One bulk move or trash request.
MAX_BATCH = 200

YearKind = Literal["tax", "financial"]
FileKind = Literal["pdf", "image", "spreadsheet", "csv", "json", "text", "zip", "other"]

# Read by other modules at a fixed path, or the app's own records: never moved, renamed or trashed from here.
PROTECTED_PREFIXES = (f"{SYSTEM}/", f"{INVOICES}/", f"{CREDIT_NOTES}/", f"{VAT_RETURNS}/", f"{BACKUPS}/")
PROTECTED_FILES = ("Books.xlsx", "README.txt")
# The tree archiving moves from (minus the protected prefixes above).
ARCHIVABLE = (RECEIPTS, SALES, BANK, PAYROLL, REPORTS)
# Not counted as the user's documents in the overview's years, largest files or duplicates.
NOT_DOCUMENTS = (SYSTEM, BACKUPS, TRASH)

_EXT: dict[str, FileKind] = {
    "pdf": "pdf",
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "heic": "image",
    "webp": "image",
    "gif": "image",
    "xlsx": "spreadsheet",
    "xls": "spreadsheet",
    "ods": "spreadsheet",
    "csv": "csv",
    "json": "json",
    "jsonl": "json",
    "txt": "text",
    "md": "text",
    "eml": "text",
    "zip": "zip",
}


class FileError(ValueError):
    """A move, rename or trash the app refuses; the message says why in plain words."""


def kind_of(name: str) -> FileKind:
    return _EXT.get(name.rsplit(".", 1)[-1].lower() if "." in name else "", "other")


def top_of(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else ""


def is_protected(path: str) -> bool:
    return path in PROTECTED_FILES or any(path.startswith(p) for p in PROTECTED_PREFIXES) or path == SYSTEM


def _under(path: str, folders: Iterable[str]) -> bool:
    return any(path == f or path.startswith(f"{f}/") for f in folders)


# --------------------------------------------------------------------------- #
# Years: tax (6 April) or financial (any year end)
# --------------------------------------------------------------------------- #


class Year(BaseModel):
    label: str  # "2025-26" when the year spans two calendar years, else "2026"
    start: date
    end: date


def _clamp(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def year_of(d: date, kind: YearKind = "tax", end_month: int = 3, end_day: int = 31) -> Year:
    """The tax year (6 April to 5 April) or financial year (ending on end_day/end_month) holding `d`."""
    if kind == "tax":
        start = date(d.year, 4, 6) if d >= date(d.year, 4, 6) else date(d.year - 1, 4, 6)
        end = date(start.year + 1, 4, 5)
    else:
        end = _clamp(d.year, end_month, end_day)
        if d > end:
            end = _clamp(d.year + 1, end_month, end_day)
        prev = _clamp(end.year - 1, end_month, end_day)
        start = date.fromordinal(prev.toordinal() + 1)
    label = str(end.year) if start.year == end.year else f"{start.year}-{str(end.year)[2:]}"
    return Year(label=label, start=start, end=end)


_DAY = re.compile(r"(?<!\d)(\d{4})-(\d{2})(?:-(\d{2}))?(?!\d)")
_QUARTER = re.compile(r"(?<!\d)(\d{4})-Q([1-4])(?!\d)")


def _date_in(text: str) -> date | None:
    if m := _DAY.search(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3) or 1)
        try:
            return date(y, mo, d) if 1990 <= y <= 2200 else None
        except ValueError:
            return None
    if m := _QUARTER.search(text):
        y, q = int(m.group(1)), int(m.group(2))
        return _clamp(y, q * 3, 31) if 1990 <= y <= 2200 else None
    return None


def file_date(path: str, modified: datetime | None, linked: date | None = None) -> tuple[date, str]:
    """The date a document belongs to, and where it came from: the linked document's own date, else a date in its
    name ("2026-10-21 Screwfix £38.47.pdf", "2026-09-30_starling.csv"), else in a folder ("01 Receipts/2026-08"),
    else when it was last modified."""
    if linked:
        return linked, "document"
    parts = path.split("/")
    for i, part in enumerate(reversed(parts)):
        if i and part == ARCHIVE:
            break
        if d := _date_in(part):
            return d, "name" if i == 0 else "folder"
    if modified:
        return modified.astimezone(UTC).date(), "modified"
    return current_date(), "today"


# --------------------------------------------------------------------------- #
# Walking the tree
# --------------------------------------------------------------------------- #


class Walk(BaseModel):
    files: list[FileRef]
    folders: list[str]
    truncated: bool = False


async def walk(books: Books, folder: str = "", *, skip: Iterable[str] = ()) -> Walk:
    """Every file under `folder` (recursively), breadth first, each folder listed once. Missing folders give
    nothing. `skip`: folders not to descend into."""
    skipped = set(skip)
    out = Walk(files=[], folders=[])
    level = [folder]
    while level:
        listings = await asyncio.gather(*(_list(books, f) for f in level))
        level = []
        for items in listings:
            for item in sorted(items, key=lambda i: i.path):
                if item.is_folder:
                    if item.path not in skipped:
                        out.folders.append(item.path)
                        level.append(item.path)
                elif len(out.files) < MAX_WALK_FILES:
                    out.files.append(item)
                else:
                    out.truncated = True
    return out


async def _list(books: Books, folder: str) -> list[FileRef]:
    try:
        return await books.storage.list(folder)
    except FileNotFoundError:
        return []


# --------------------------------------------------------------------------- #
# Links: which documents the books point at
# --------------------------------------------------------------------------- #


class Link(BaseModel):
    proposal_id: str | None = None
    event_id: str | None = None  # set when the document's entry is posted and still stands
    amount_pence: int | None = None  # the ledger entry's net + VAT, from the event (code, not the model's reading)
    counterparty: str | None = None
    doc_date: date | None = None
    bank_lines: int = 0  # a bank statement: lines imported from it


async def links(books: Books) -> dict[str, Link]:
    """Path (where the document is now) -> what in the books points at it."""
    proposals, lines, events = await asyncio.gather(
        books.list_proposals(), books.stored_bank_lines(), books.live_events()
    )
    by_id = {e.id: e for e in events}
    out: dict[str, Link] = {}
    for p in proposals:
        if not p.file_path:
            continue
        ev = by_id.get(p.event_id or "")
        try:
            doc_date: date | None = date.fromisoformat(p.extracted.date)
        except ValueError:
            doc_date = None
        out[p.file_path] = Link(
            proposal_id=p.id,
            event_id=ev.id if ev else None,
            amount_pence=(ev.net + (ev.vat or 0)) if ev and ev.net is not None else None,
            counterparty=(ev.counterparty if ev else None) or p.extracted.supplier_name or None,
            doc_date=doc_date,
        )
    for ln in lines:
        link = out.setdefault(ln.source_file, Link())
        link.bank_lines += 1
    return out


# --------------------------------------------------------------------------- #
# The index the Files page searches, and the overview
# --------------------------------------------------------------------------- #


class IndexedFile(BaseModel):
    path: str
    name: str
    folder: str  # the top-level folder ("" for a file at the root)
    kind: FileKind
    size: int
    modified: datetime | None
    date: date  # file_date()
    date_from: str  # document | name | folder | modified | today
    tax_year: str
    archived: bool  # under Archive/
    protected: bool  # the app will not move, rename or trash it
    web_url: str | None
    linked: Link | None = None


def _indexed(ref: FileRef, link: Link | None) -> IndexedFile:
    d, src = file_date(ref.path, ref.modified, link.doc_date if link else None)
    return IndexedFile(
        path=ref.path,
        name=ref.name,
        folder=top_of(ref.path),
        kind=kind_of(ref.name),
        size=ref.size,
        modified=ref.modified,
        date=d,
        date_from=src,
        tax_year=year_of(d).label,
        archived=_under(ref.path, [ARCHIVE]),
        protected=is_protected(ref.path),
        web_url=ref.web_url,
        linked=link if link and (link.proposal_id or link.bank_lines) else None,
    )


class FileIndex(BaseModel):
    files: list[IndexedFile]  # every file outside _System, Backups and _Trash, newest date first
    folders: list[str]  # folders a file can be moved to
    truncated: bool


async def index(books: Books) -> FileIndex:
    w, linked = await asyncio.gather(walk(books, skip=NOT_DOCUMENTS), links(books))
    files = [_indexed(f, linked.get(f.path)) for f in w.files if top_of(f.path) not in NOT_DOCUMENTS]
    files.sort(key=lambda f: (f.date, f.path), reverse=True)
    targets = sorted(f for f in w.folders if move_target_ok(f))
    return FileIndex(files=files, folders=targets, truncated=w.truncated)


class FolderUse(BaseModel):
    folder: str
    files: int
    bytes: int


class YearUse(BaseModel):
    year: str  # tax year label
    files: int
    bytes: int
    archived_files: int


class DuplicateFile(BaseModel):
    path: str
    size: int
    modified: datetime | None
    web_url: str | None
    keep: bool  # the one Clean up suggests keeping
    linked: bool  # the books point at it: never suggested for _Trash
    protected: bool


class DuplicateGroup(BaseModel):
    hash: str
    size: int
    files: list[DuplicateFile]


class Overview(BaseModel):
    total_files: int
    total_bytes: int
    folders: list[FolderUse]  # top-level folders (and "" for files at the root), biggest first
    years: list[YearUse]  # tax years of the documents, newest first
    largest: list[IndexedFile]  # up to 10 documents
    duplicates: list[DuplicateGroup]
    duplicate_bytes: int  # what moving every suggested copy to _Trash would free
    truncated: bool


async def overview(books: Books) -> Overview:
    """Counts and sizes per folder and per year, the largest documents and duplicates by content hash."""
    w, linked = await asyncio.gather(walk(books), links(books))
    per_folder: dict[str, FolderUse] = {}
    for f in w.files:
        use = per_folder.setdefault(top_of(f.path), FolderUse(folder=top_of(f.path), files=0, bytes=0))
        use.files += 1
        use.bytes += f.size
    docs = [_indexed(f, linked.get(f.path)) for f in w.files if top_of(f.path) not in NOT_DOCUMENTS]
    per_year: dict[str, YearUse] = {}
    for d in docs:
        y = per_year.setdefault(d.tax_year, YearUse(year=d.tax_year, files=0, bytes=0, archived_files=0))
        y.files += 1
        y.bytes += d.size
        y.archived_files += d.archived
    groups = await duplicates(books, [f for f in w.files if top_of(f.path) not in NOT_DOCUMENTS], set(linked))
    return Overview(
        total_files=len(w.files),
        total_bytes=sum(f.size for f in w.files),
        folders=sorted(per_folder.values(), key=lambda u: (-u.bytes, u.folder)),
        years=sorted(per_year.values(), key=lambda y: y.year, reverse=True),
        largest=sorted(docs, key=lambda d: (-d.size, d.path))[:10],
        duplicates=groups,
        duplicate_bytes=sum(f.size for g in groups for f in g.files if not f.keep and not f.linked),
        truncated=w.truncated,
    )


async def duplicates(books: Books, files: list[FileRef], linked: set[str]) -> list[DuplicateGroup]:
    """Files with the same content (same listed hash, or the same sha256 when the listing gives none), two or more
    to a group. Empty files are not duplicates of each other."""
    by_hash: dict[str, list[FileRef]] = {}
    unhashed: dict[int, list[FileRef]] = {}
    for f in files:
        if f.size == 0:
            continue
        if f.content_hash:
            by_hash.setdefault(f.content_hash, []).append(f)
        else:
            unhashed.setdefault(f.size, []).append(f)
    reads = 0
    for same_size in unhashed.values():
        if len(same_size) < 2 or same_size[0].size > MAX_HASH_READ_BYTES:
            continue
        for f in same_size:
            if reads >= MAX_HASH_READS:
                break
            reads += 1
            digest = hashlib.sha256(await books.storage.read(f.path)).hexdigest()
            by_hash.setdefault(f"sha256:{digest}", []).append(f)
    out: list[DuplicateGroup] = []
    for h, group in by_hash.items():
        if len(group) < 2:
            continue
        keep = _keeper(group, linked)
        out.append(
            DuplicateGroup(
                hash=h,
                size=group[0].size,
                files=[
                    DuplicateFile(
                        path=f.path,
                        size=f.size,
                        modified=f.modified,
                        web_url=f.web_url,
                        keep=f.path == keep.path,
                        linked=f.path in linked,
                        protected=is_protected(f.path),
                    )
                    for f in sorted(group, key=lambda f: f.path)
                ],
            )
        )
    return sorted(out, key=lambda g: (-g.size * (len(g.files) - 1), g.hash))


def _keeper(group: list[FileRef], linked: set[str]) -> FileRef:
    """The copy to keep: one the books point at, else a protected one, else one already filed (not in the Inbox or
    an archive), else the shortest path, else the oldest."""

    def rank(f: FileRef) -> tuple[int, int, int, int, float, str]:
        loose = top_of(f.path) in (INBOX, NEEDS_A_LOOK) or _under(f.path, [ARCHIVE])
        age = f.modified.timestamp() if f.modified else 0.0
        return (f.path not in linked, not is_protected(f.path), loose, len(f.path), age, f.path)

    return min(group, key=rank)


# --------------------------------------------------------------------------- #
# Moves, renames, _Trash
# --------------------------------------------------------------------------- #

_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]+')


def safe_name(name: str, like: str = "") -> str:
    """A name OneDrive and Windows accept: no \\ / : * ? " < > | or control characters (each run becomes a space),
    spaces collapsed, no leading or trailing dots or spaces. Keeps `like`'s extension when the new name has none.
    Raises FileError when nothing usable is left."""
    s = _UNSAFE_CHARS.sub(" ", name)
    s = " ".join(s.split()).strip(" .")
    ext = like.rsplit(".", 1)[-1] if "." in like.strip(".") else ""
    if ext and "." not in s:
        s = f"{s}.{ext}" if s else ""
    if len(s) > MAX_NAME:
        stem, dot, e = s.rpartition(".")
        s = (stem[: MAX_NAME - len(e) - 1] + "." + e) if dot and len(e) < 10 else s[:MAX_NAME]
    try:
        return check_name(s)
    except UnsafeName as exc:
        raise FileError("Choose a name with some letters or numbers in it") from exc


def move_target_ok(folder: str) -> bool:
    """A folder the Files page may move documents into: not _System, Backups, _Trash or a protected folder."""
    folder = folder.strip("/")
    return bool(folder) and top_of(f"{folder}/x") != TRASH and not is_protected(f"{folder}/x")


async def _existing(books: Books, path: str) -> FileRef:
    parent, _, name = path.rpartition("/")
    ref = next((f for f in await books.list_files(parent) if f.name == name), None)
    if ref is None:
        raise FileNotFoundError(path)
    return ref


def _check_movable(path: str) -> None:
    for seg in path.split("/"):
        check_name(seg)
    if is_protected(path) or top_of(path) == TRASH:
        raise FileError(f"{path} is one of the files the app looks after itself; it stays where it is")


class Moved(BaseModel):
    old: str
    new: str


async def move_files(books: Books, paths: list[str], to: str, user: str) -> list[Moved]:
    """Move documents into folder `to` (made if missing), each keeping its name or getting " (2)". Audited and
    recorded in the redirect map."""
    to = to.strip("/")
    for seg in to.split("/"):
        check_name(seg)
    if not move_target_ok(to):
        raise FileError(f"Documents cannot be moved into {to}")
    paths = list(dict.fromkeys(p.strip("/") for p in paths))
    if not paths or len(paths) > MAX_BATCH:
        raise FileError(f"Choose between 1 and {MAX_BATCH} files")
    for p in paths:
        _check_movable(p)
        await _existing(books, p)
    await books.storage.ensure_folder(to)
    done: list[Moved] = []
    for p in paths:
        if posixpath.dirname(p) == to:
            continue
        dest = await books.free_path(to, posixpath.basename(p))
        await books.storage.move(p, dest)
        done.append(Moved(old=p, new=dest))
    await books.record_moves([(m.old, m.new) for m in done])
    await books.audit(f"user:{user}", "files_moved", {"to": to, "moved": [m.model_dump() for m in done]})
    return done


async def rename_file(books: Books, path: str, name: str, user: str) -> Moved:
    path = path.strip("/")
    _check_movable(path)
    await _existing(books, path)
    new_name = safe_name(name, like=posixpath.basename(path))
    parent = posixpath.dirname(path)
    dest = f"{parent}/{new_name}" if parent else new_name
    if dest == path:
        return Moved(old=path, new=dest)
    if any(f.name.casefold() == new_name.casefold() for f in await books.list_files(parent) if f.path != path):
        raise FileExistsError(f"{new_name} is already in {parent or 'the books folder'}")
    await books.storage.move(path, dest)
    await books.record_moves([(path, dest)])
    await books.audit(f"user:{user}", "file_renamed", {"file": dest, "old": path, "new": dest})
    return Moved(old=path, new=dest)


def trash_folder(day: date) -> str:
    return f"{TRASH}/{day.isoformat()}"


async def to_trash(books: Books, path: str, day: date) -> str:
    """Move one file to _Trash/{day}/{its path}; returns where it went. No checks: callers decide what may go."""
    folder = posixpath.dirname(f"{trash_folder(day)}/{path}")
    await books.storage.ensure_folder(folder)
    dest = await books.free_path(folder, posixpath.basename(path))
    await books.storage.move(path, dest)
    return dest


async def trash_files(books: Books, paths: list[str], user: str) -> list[Moved]:
    """Clean up: move documents (duplicates, usually) to _Trash. Refuses any the books point at: a proposal's
    document or an imported bank statement stays where it is."""
    paths = list(dict.fromkeys(p.strip("/") for p in paths))
    if not paths or len(paths) > MAX_BATCH:
        raise FileError(f"Choose between 1 and {MAX_BATCH} files")
    linked = await links(books)
    moved = await books.moved_paths()
    for p in paths:
        _check_movable(p)
        await _existing(books, p)
        if p in linked or follow(moved, p) in linked:
            raise FileError(f"{p} is linked from your books (a Review card or a bank statement); it stays")
    day = current_date()
    done = [Moved(old=p, new=await to_trash(books, p, day)) for p in paths]
    await books.audit(f"user:{user}", "files_trashed", {"moved": [m.model_dump() for m in done]})
    return done
