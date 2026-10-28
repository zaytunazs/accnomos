"""Archive by year: move filed documents and reports of older years into Archive/{year}/, and back again.

    preview(up_to)  what would move: every document in 01 Receipts, 03 Sales (not invoices/ or credit-notes/),
                    04 Bank statements, 05 Payroll and 07 Reports whose year (app/files.py file_date + year_of)
                    ends on or before the end of `up_to`. The current year is refused.
    run(up_to)      moves each to Archive/{its year}/{same path}, records every move in _System/archive/map.json
                    (so proposals and bank lines still find their documents) and the run in
                    _System/archive/runs/{id}.json; with zip, also writes Archive/{year}.zip: a copy of that year's
                    folder plus manifest.json (path, size, sha256 of each file). The folder stays, so links work.
    undo(run_id)    moves each file back (a name now taken gets " (2)"), puts the run's zips in _Trash, marks the
                    run undone. Files the user has moved since are reported, not hunted for.

Ledger events and the rest of _System are never touched: they are the books.
"""

from __future__ import annotations

import hashlib
import io
import json
import posixpath
import secrets
import zipfile
from datetime import datetime

from pydantic import BaseModel

from app import files as fm
from app.books import Books, now
from app.books import today as current_date
from app.paths import ARCHIVE, ARCHIVE_SYSTEM

RUNS = f"{ARCHIVE_SYSTEM}/runs"
#: A year's zip is skipped (with a note) when its files add up to more than this.
MAX_ZIP_BYTES = 50 * 1024 * 1024


class ArchiveError(ValueError):
    """An archive or undo the app refuses; the message says why."""


class YearChoice(BaseModel):
    """One year the user can archive up to, with what is in it now."""

    label: str
    start: str
    end: str
    files: int
    bytes: int
    current: bool  # the year we are in: never archived


class PlannedMove(BaseModel):
    old: str
    new: str
    year: str
    size: int


class Preview(BaseModel):
    kind: fm.YearKind
    up_to: str | None
    years: list[YearChoice]  # every year with documents outside the archive, newest first
    moves: list[PlannedMove]
    bytes: int


class ZipNote(BaseModel):
    year: str
    path: str | None  # None when skipped
    files: int
    note: str | None = None


class Run(BaseModel):
    id: str
    created_at: datetime
    by: str
    kind: fm.YearKind
    up_to: str
    end_month: int
    end_day: int
    moves: list[PlannedMove]
    zips: list[ZipNote] = []
    undone_at: datetime | None = None
    undone_by: str | None = None
    undo_skipped: list[str] = []


async def _candidates(books: Books) -> list[fm.IndexedFile]:
    idx = await fm.index(books)
    return [
        f
        for f in idx.files
        if not f.archived and not f.protected and any(f.path.startswith(f"{root}/") for root in fm.ARCHIVABLE)
    ]


async def preview(
    books: Books, up_to: str | None, kind: fm.YearKind = "tax", end_month: int = 3, end_day: int = 31
) -> Preview:
    _check_year_end(end_month, end_day)
    current = fm.year_of(current_date(), kind, end_month, end_day)
    years: dict[str, YearChoice] = {}
    planned: list[PlannedMove] = []
    cands = await _candidates(books)
    for f in cands:
        y = fm.year_of(f.date, kind, end_month, end_day)
        c = years.setdefault(
            y.label,
            YearChoice(
                label=y.label,
                start=y.start.isoformat(),
                end=y.end.isoformat(),
                files=0,
                bytes=0,
                current=y.end >= current.start,
            ),
        )
        c.files += 1
        c.bytes += f.size
    if up_to is not None:
        chosen = years.get(up_to)
        if chosen is None:
            raise ArchiveError(f"There is nothing from {up_to} to archive")
        if chosen.current:
            raise ArchiveError(f"{up_to} is the year we are in; only earlier years can be archived")
        for f in cands:
            y = fm.year_of(f.date, kind, end_month, end_day)
            if y.end.isoformat() <= chosen.end:
                planned.append(PlannedMove(old=f.path, new=f"{ARCHIVE}/{y.label}/{f.path}", year=y.label, size=f.size))
    return Preview(
        kind=kind,
        up_to=up_to,
        years=sorted(years.values(), key=lambda c: c.end, reverse=True),
        moves=sorted(planned, key=lambda m: m.old),
        bytes=sum(m.size for m in planned),
    )


def _check_year_end(month: int, day: int) -> None:
    if not (1 <= month <= 12 and 1 <= day <= 31):
        raise ArchiveError("Choose a real year end, such as 31 March")


async def run(
    books: Books,
    up_to: str,
    user: str,
    *,
    kind: fm.YearKind = "tax",
    end_month: int = 3,
    end_day: int = 31,
    make_zip: bool = False,
) -> Run:
    plan = await preview(books, up_to, kind, end_month, end_day)
    if not plan.moves:
        raise ArchiveError(f"There is nothing up to {up_to} left to archive")
    r = Run(
        id=secrets.token_hex(8),
        created_at=now(),
        by=user,
        kind=kind,
        up_to=up_to,
        end_month=end_month,
        end_day=end_day,
        moves=[],
    )
    try:
        for m in plan.moves:
            folder = posixpath.dirname(m.new)
            await books.storage.ensure_folder(folder)
            dest = await books.free_path(folder, posixpath.basename(m.new))
            await books.storage.move(m.old, dest)
            r.moves.append(m.model_copy(update={"new": dest}))
    finally:  # a run that fails part way still records what it moved, so links follow and Undo can put it back
        if r.moves:
            await books.record_moves([(m.old, m.new) for m in r.moves])
            await books.write_json(f"{RUNS}/{r.id}.json", r.model_dump(mode="json"))
    done = r.moves
    if make_zip:
        for year in sorted({m.year for m in done}):
            r.zips.append(await zip_year(books, year))
        await books.write_json(f"{RUNS}/{r.id}.json", r.model_dump(mode="json"))
    await books.audit(
        f"user:{user}",
        "files_archived",
        {
            "run": r.id,
            "up_to": up_to,
            "kind": kind,
            "files": len(done),
            "years": sorted({m.year for m in done}),
            "zips": [z.path for z in r.zips if z.path],
        },
    )
    return r


def manifest(year: str, entries: list[tuple[str, bytes]], created: datetime) -> dict[str, object]:
    return {
        "format": "accnomos-archive/1",
        "year": year,
        "created_at": created.isoformat(),
        "note": f"A copy of {ARCHIVE}/{year}. The folder itself stays in OneDrive so the app's links keep working.",
        "files": [
            {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for path, data in entries
        ],
    }


async def zip_year(books: Books, year: str) -> ZipNote:
    """Archive/{year}.zip: every file under Archive/{year}/ plus manifest.json. A copy; nothing is removed."""
    root = f"{ARCHIVE}/{year}"
    w = await fm.walk(books, root)
    if sum(f.size for f in w.files) > MAX_ZIP_BYTES:
        return ZipNote(year=year, path=None, files=len(w.files), note="Too big to zip here; the folder is archived")
    entries = [(f.path.removeprefix(f"{root}/"), await books.storage.read(f.path)) for f in w.files]
    created = now()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, data in entries:
            z.writestr(path, data)
        z.writestr("manifest.json", json.dumps(manifest(year, entries, created), indent=2, ensure_ascii=False))
    dest = await books.free_path(ARCHIVE, f"{year}.zip")
    await books.storage.write(dest, buf.getvalue(), create_only=True)
    return ZipNote(year=year, path=dest, files=len(entries))


async def list_runs(books: Books) -> list[Run]:
    out = []
    for f in await books.list_files(RUNS):
        if f.name.endswith(".json"):
            try:
                out.append(Run.model_validate_json(await books.storage.read(f.path)))
            except ValueError:
                continue  # a hand-edited run file: shown nowhere, never fatal
    return sorted(out, key=lambda r: r.created_at, reverse=True)


async def get_run(books: Books, run_id: str) -> Run:
    if not run_id.isalnum() or len(run_id) != 16:
        raise FileNotFoundError(run_id)
    return Run.model_validate_json(await books.storage.read(f"{RUNS}/{run_id}.json"))


async def undo(books: Books, run_id: str, user: str) -> Run:
    r = await get_run(books, run_id)
    if r.undone_at:
        raise ArchiveError("This archive run has already been undone")
    back: list[tuple[str, str]] = []
    skipped: list[str] = []
    for m in reversed(r.moves):
        parent, name = posixpath.dirname(m.old), posixpath.basename(m.old)
        if not await books.exists(m.new):
            skipped.append(m.new)
            continue
        await books.storage.ensure_folder(parent)
        dest = await books.free_path(parent, name)
        await books.storage.move(m.new, dest)
        back.append((m.new, dest))
    await books.record_moves(back)
    day = current_date()
    for z in r.zips:
        if z.path and await books.exists(z.path):
            await fm.to_trash(books, z.path, day)
    r.undone_at, r.undone_by, r.undo_skipped = now(), user, skipped
    await books.write_json(f"{RUNS}/{r.id}.json", r.model_dump(mode="json"))
    await books.audit(
        f"user:{user}", "archive_undone", {"run": r.id, "files": len(back), "skipped": len(skipped), "up_to": r.up_to}
    )
    return r
