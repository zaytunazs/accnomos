"""/files/* and /backups/*: storage overview, search index, moves, renames, Clean up, archive by year, backups.

Same headers as /books/*; every write needs X-User and is audited. Nothing here deletes a file: what would be
deleted goes to _Trash (app/files.py). The work is in app/files.py, app/archive.py and app/backups.py.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import archive, backups
from app import files as fm
from app.books import Books
from app.routes_books import get_books, require_user
from app.validation import StrictBody

router = APIRouter(prefix="/files", tags=["files"])
backups_router = APIRouter(prefix="/backups", tags=["files"])

Path = Field(min_length=1, max_length=1000)
FilePath = Annotated[str, Field(min_length=1, max_length=1000)]


def _refused(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=f"No such file: {exc}")
    if isinstance(exc, FileExistsError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, backups.BackupTooBig):
        return HTTPException(status_code=413, detail=str(exc))
    if isinstance(exc, backups.ConfirmationNeeded):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


_ERRORS = (FileNotFoundError, FileExistsError, ValueError)


# --------------------------------------------------------------------------- #
# Overview, index, moves
# --------------------------------------------------------------------------- #


@router.get("/overview", response_model=fm.Overview)
async def overview(books: Books = Depends(get_books)) -> fm.Overview:
    """Files and bytes per folder and per tax year, the 10 largest documents and duplicate groups. Reads only."""
    return await fm.overview(books)


@router.get("/index", response_model=fm.FileIndex)
async def file_index(books: Books = Depends(get_books)) -> fm.FileIndex:
    """Every document outside _System, Backups and _Trash, with its date, tax year, type and (when the books point
    at it) the ledger entry's amount, for the Files page's search and filters. Reads only."""
    return await fm.index(books)


class MoveBody(StrictBody):
    paths: list[FilePath] = Field(min_length=1, max_length=fm.MAX_BATCH)
    to: str = Path


class MovedList(BaseModel):
    moved: list[fm.Moved]


@router.post("/move", response_model=MovedList)
async def move(body: MoveBody, books: Books = Depends(get_books), user: str = Depends(require_user)) -> MovedList:
    """Move documents into another folder. A name already taken there gets " (2)"."""
    try:
        return MovedList(moved=await fm.move_files(books, body.paths, body.to, user))
    except _ERRORS as exc:
        raise _refused(exc) from exc


class RenameBody(StrictBody):
    path: str = Path
    name: str = Field(min_length=1, max_length=300)


@router.post("/rename", response_model=fm.Moved)
async def rename(body: RenameBody, books: Books = Depends(get_books), user: str = Depends(require_user)) -> fm.Moved:
    """Rename one document; the name is made safe for OneDrive (app/files.py safe_name) and keeps its extension."""
    try:
        return await fm.rename_file(books, body.path, body.name, user)
    except _ERRORS as exc:
        raise _refused(exc) from exc


class TrashBody(StrictBody):
    paths: list[FilePath] = Field(min_length=1, max_length=fm.MAX_BATCH)


@router.post("/trash", response_model=MovedList)
async def trash(body: TrashBody, books: Books = Depends(get_books), user: str = Depends(require_user)) -> MovedList:
    """Clean up: move documents to _Trash/{date}/. Nothing is deleted; documents the books link to are refused."""
    try:
        return MovedList(moved=await fm.trash_files(books, body.paths, user))
    except _ERRORS as exc:
        raise _refused(exc) from exc


# --------------------------------------------------------------------------- #
# Archive by year
# --------------------------------------------------------------------------- #


class ArchiveBody(StrictBody):
    up_to: str | None = Field(default=None, max_length=20)
    kind: fm.YearKind = "tax"
    end_month: int = Field(default=3, ge=1, le=12)
    end_day: int = Field(default=31, ge=1, le=31)
    zip: bool = False


@router.post("/archive/preview", response_model=archive.Preview)
async def archive_preview(body: ArchiveBody, books: Books = Depends(get_books)) -> archive.Preview:
    """The years there are to archive and, with `up_to`, every move archiving them would make. Writes nothing."""
    try:
        return await archive.preview(books, body.up_to, body.kind, body.end_month, body.end_day)
    except archive.ArchiveError as exc:
        raise _refused(exc) from exc


@router.post("/archive", response_model=archive.Run)
async def archive_run(
    body: ArchiveBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> archive.Run:
    """Move documents of every year up to `up_to` into Archive/{year}/ (optionally also Archive/{year}.zip)."""
    if not body.up_to:
        raise HTTPException(status_code=422, detail="choose the year to archive up to")
    try:
        return await archive.run(
            books,
            body.up_to,
            user,
            kind=body.kind,
            end_month=body.end_month,
            end_day=body.end_day,
            make_zip=body.zip,
        )
    except archive.ArchiveError as exc:
        raise _refused(exc) from exc


@router.get("/archive/runs", response_model=list[archive.Run])
async def archive_runs(books: Books = Depends(get_books)) -> list[archive.Run]:
    return await archive.list_runs(books)


@router.post("/archive/runs/{run_id}/undo", response_model=archive.Run)
async def archive_undo(
    run_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> archive.Run:
    """Move a run's files back where they were; its zips go to _Trash."""
    try:
        return await archive.undo(books, run_id, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such archive run") from exc
    except archive.ArchiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# Backups
# --------------------------------------------------------------------------- #


class BackupList(BaseModel):
    backups: list[backups.Backup]
    settings: backups.FileSettings


@backups_router.get("", response_model=BackupList)
async def list_backups(books: Books = Depends(get_books)) -> BackupList:
    return BackupList(backups=await backups.list_backups(books), settings=await backups.load_settings(books))


@backups_router.post("", response_model=backups.BackupResult)
async def back_up_now(books: Books = Depends(get_books), user: str = Depends(require_user)) -> backups.BackupResult:
    """Back up now: Backups/accnomos-backup-YYYY-MM-DD.zip with a manifest, and its .sha256 beside it."""
    try:
        return await backups.back_up(books, f"user:{user}")
    except backups.BackupError as exc:
        raise _refused(exc) from exc


class AutoResult(BaseModel):
    ran: bool
    result: backups.BackupResult | None = None


@backups_router.post("/auto", response_model=AutoResult)
async def monthly(books: Books = Depends(get_books), user: str = Depends(require_user)) -> AutoResult:
    """The monthly backup, called by the app when it opens: backs up only if switched on and none is dated this
    month. (X-User is required so only a signed-in app can trigger it; the audit line names the backup agent.)"""
    del user
    try:
        result = await backups.maybe_monthly(books)
    except backups.BackupError as exc:
        raise _refused(exc) from exc
    return AutoResult(ran=result is not None, result=result)


class SettingsBody(StrictBody):
    backup_keep: int = Field(ge=1, le=120)
    monthly_backup: bool


@backups_router.put("/settings", response_model=backups.FileSettings)
async def put_settings(
    body: SettingsBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> backups.FileSettings:
    settings = backups.FileSettings(backup_keep=body.backup_keep, monthly_backup=body.monthly_backup)
    saved = await backups.save_settings(books, settings, user)
    await backups.apply_retention(books, saved.backup_keep)
    return saved


class BackupPath(StrictBody):
    path: str = Path


@backups_router.post("/verify", response_model=backups.Verification)
async def verify(
    body: BackupPath, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> backups.Verification:
    """Check a backup against its .sha256 and every file against its manifest."""
    try:
        return await backups.verify(books, body.path, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such backup") from exc


@backups_router.post("/restore/preview", response_model=backups.RestorePreview)
async def restore_preview(body: BackupPath, books: Books = Depends(get_books)) -> backups.RestorePreview:
    """What restoring this backup would do, file by file. Writes nothing."""
    try:
        return await backups.restore_preview(books, body.path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such backup") from exc
    except backups.BackupError as exc:
        raise _refused(exc) from exc


class RestoreBody(StrictBody):
    path: str = Path
    confirm: str | None = Field(default=None, max_length=20)


@backups_router.post("/restore", response_model=backups.RestoreResult)
async def restore(
    body: RestoreBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> backups.RestoreResult:
    """Restore a backup into _System. Needs `confirm: "RESTORE"` unless the books are empty; never deletes."""
    try:
        return await backups.restore(books, body.path, user, body.confirm)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No such backup") from exc
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409, detail="A file changed while restoring; check the preview again and restore once more"
        ) from exc
    except backups.BackupError as exc:
        raise _refused(exc) from exc
