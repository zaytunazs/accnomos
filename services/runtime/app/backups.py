"""Backups of the books: dated zips of _System in Backups/, a checksum beside each, retention, verify, restore.

    Back up now     Backups/accnomos-backup-YYYY-MM-DD.zip (a second the same day gets " (2)") holding every file
                    under _System (ledger events, proposals, contacts, settings, audit, ...) at its own path, plus
                    manifest.json: each file's path, size and sha256, and files_sha256 over them all. Beside it,
                    the same name + ".sha256" holds the zip's own sha256 ("<hex>  <name>", as sha256sum writes).
    Retention       keep the newest N backups (Settings: backup_keep, default 12); older ones and their .sha256
                    go to _Trash/{date}/Backups/, never deleted.
    Verify          the zip against its .sha256, then every file against the manifest.
    Restore         preview first: each file in the backup is new (not in the books now), same, changed, or kept
                    (a ledger event or audit file that differs: those are append-only and never replaced). Restoring
                    writes the new files and, for changed ones, first moves the current file to
                    _Trash/{date}/restore-{time}/{path}. It needs the typed word RESTORE unless the books are empty
                    (no ledger events and no proposals). Never deletes a file the backup does not have.
    Monthly backup  optional (monthly_backup, off by default): POST /backups/auto backs up when no backup is dated
                    this month. There is no server per user, so the app calls it when it is opened (the web app,
                    once a month per device); a month nobody opens the app has no automatic backup.

Settings live in _System/Settings/files.json.
"""

from __future__ import annotations

import hashlib
import io
import json
import posixpath
import re
import zipfile
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from app import files as fm
from app.books import AUDIT, EVENTS, PROPOSALS, SYSTEM, Books, now
from app.books import today as current_date
from app.paths import BACKUPS
from app.validation import UnsafeName, check_name

PREFIX = "accnomos-backup-"
SETTINGS = f"{SYSTEM}/Settings/files.json"
CONFIRM_WORD = "RESTORE"
DEFAULT_KEEP = 12
MAX_BACKUP_FILES = 20_000
MAX_BACKUP_BYTES = 100 * 1024 * 1024
ACTOR = "agent:backup"
_NAME = re.compile(rf"^{re.escape(PREFIX)}(\d{{4}}-\d{{2}}-\d{{2}})(?: \((\d+)\))?\.zip$")


class BackupError(ValueError):
    """A backup, verify or restore the app refuses; the message says why."""


class BackupTooBig(BackupError):
    pass


class ConfirmationNeeded(BackupError):
    pass


class FileSettings(BaseModel):
    backup_keep: int = Field(default=DEFAULT_KEEP, ge=1, le=120)
    monthly_backup: bool = False


async def load_settings(books: Books) -> FileSettings:
    raw = await books.read_json(SETTINGS, {})
    try:
        return FileSettings.model_validate(raw if isinstance(raw, dict) else {})
    except ValueError:
        return FileSettings()


async def save_settings(books: Books, settings: FileSettings, user: str) -> FileSettings:
    await books.write_json(SETTINGS, settings.model_dump())
    await books.audit(f"user:{user}", "file_settings_saved", settings.model_dump())
    return settings


# --------------------------------------------------------------------------- #
# Writing a backup
# --------------------------------------------------------------------------- #


def backup_name(day: date) -> str:
    return f"{PREFIX}{day.isoformat()}.zip"


def _order(name: str) -> tuple[str, int] | None:
    """('2026-10-27', 2) for 'accnomos-backup-2026-10-27 (2).zip'; None for anything else."""
    m = _NAME.match(name)
    return (m.group(1), int(m.group(2) or 1)) if m else None


def files_digest(entries: list[dict[str, Any]]) -> str:
    """One sha256 over every file's "sha256  path" line, sorted by path."""
    lines = "".join(f"{e['sha256']}  {e['path']}\n" for e in sorted(entries, key=lambda e: e["path"]))
    return hashlib.sha256(lines.encode()).hexdigest()


class Backup(BaseModel):
    path: str
    name: str
    day: date
    size: int
    files: int | None = None  # set right after a backup; listing does not open the zips
    sha256: str | None = None
    web_url: str | None = None
    has_checksum: bool = False


class BackupResult(BaseModel):
    backup: Backup
    retired: list[str]  # older backups moved to _Trash by retention


async def back_up(books: Books, actor: str, day: date | None = None) -> BackupResult:
    """Write today's backup and apply retention. `actor` is "user:..." or ACTOR (the monthly backup)."""
    day = day or current_date()
    w = await fm.walk(books, SYSTEM)
    if w.truncated or len(w.files) > MAX_BACKUP_FILES or sum(f.size for f in w.files) > MAX_BACKUP_BYTES:
        raise BackupTooBig(
            f"Your {SYSTEM} folder is bigger than one backup holds ({MAX_BACKUP_FILES} files, "
            f"{MAX_BACKUP_BYTES // (1024 * 1024)} MB); OneDrive's own version history still has it"
        )
    entries: list[dict[str, Any]] = []
    created = now()
    stamp = (created.year, created.month, created.day, created.hour, created.minute, created.second)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(w.files, key=lambda f: f.path):
            data = await books.storage.read(f.path)
            z.writestr(zipfile.ZipInfo(f.path, date_time=stamp), data, zipfile.ZIP_DEFLATED)
            entries.append({"path": f.path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        man = {
            "format": "accnomos-backup/1",
            "created_at": created.isoformat(),
            "day": day.isoformat(),
            "folder": SYSTEM,
            "files": entries,
            "files_sha256": files_digest(entries),
        }
        z.writestr(zipfile.ZipInfo("manifest.json", date_time=stamp), json.dumps(man, indent=2), zipfile.ZIP_DEFLATED)
    data = buf.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    await books.storage.ensure_folder(BACKUPS)
    path = await books.free_path(BACKUPS, backup_name(day))
    ref = await books.storage.write(path, data, create_only=True)
    name = posixpath.basename(path)
    await books.storage.write(f"{path}.sha256", f"{digest}  {name}\n".encode())
    retired = await apply_retention(books, (await load_settings(books)).backup_keep)
    await books.audit(
        actor,
        "backup_created",
        {"file": path, "files": len(entries), "bytes": len(data), "sha256": digest, "retired": retired},
    )
    return BackupResult(
        backup=Backup(
            path=path,
            name=name,
            day=day,
            size=len(data),
            files=len(entries),
            sha256=digest,
            web_url=ref.web_url,
            has_checksum=True,
        ),
        retired=retired,
    )


async def list_backups(books: Books) -> list[Backup]:
    """Backups in Backups/, newest first (by the date in the name, then the " (n)")."""
    found = await books.list_files(BACKUPS)
    names = {f.name for f in found}
    out = []
    for f in found:
        if (o := _order(f.name)) is None:
            continue
        out.append(
            Backup(
                path=f.path,
                name=f.name,
                day=date.fromisoformat(o[0]),
                size=f.size,
                web_url=f.web_url,
                has_checksum=f"{f.name}.sha256" in names,
            )
        )
    return sorted(out, key=lambda b: _order(b.name) or ("", 0), reverse=True)


async def apply_retention(books: Books, keep: int) -> list[str]:
    """Move all but the newest `keep` backups (with their .sha256) to _Trash. Returns the paths moved."""
    old = (await list_backups(books))[keep:]
    day = current_date()
    moved = []
    for b in old:
        await fm.to_trash(books, b.path, day)
        if b.has_checksum:
            await fm.to_trash(books, f"{b.path}.sha256", day)
        moved.append(b.path)
    return moved


async def maybe_monthly(books: Books) -> BackupResult | None:
    """The monthly backup: only when it is switched on and no backup is dated this month."""
    if not (await load_settings(books)).monthly_backup:
        return None
    month = current_date().isoformat()[:7]
    if any(b.day.isoformat()[:7] == month for b in await list_backups(books)):
        return None
    return await back_up(books, ACTOR)


# --------------------------------------------------------------------------- #
# Verifying and restoring
# --------------------------------------------------------------------------- #


class Verification(BaseModel):
    path: str
    ok: bool
    checksum: Literal["ok", "mismatch", "missing"]
    files: int
    problems: list[str]  # plain sentences, at most 50


def _backup_path(path: str) -> str:
    path = path.strip("/")
    parent, _, name = path.rpartition("/")
    if parent != BACKUPS or _order(name) is None:
        raise FileNotFoundError(path)
    return path


def _safe_entry(path: str) -> bool:
    """A file a restore may write: under _System, every segment a plain name (no zip-slip)."""
    if not path.startswith(f"{SYSTEM}/"):
        return False
    try:
        for seg in path.split("/"):
            check_name(seg)
    except UnsafeName:
        return False
    return True


async def _open(books: Books, path: str) -> tuple[bytes, Verification, dict[str, Any] | None, dict[str, bytes]]:
    path = _backup_path(path)
    data = await books.storage.read(path)
    problems: list[str] = []
    try:
        side = (await books.storage.read(f"{path}.sha256")).decode("utf-8", "replace").split()
        checksum: Literal["ok", "mismatch", "missing"] = (
            "ok" if side and side[0].lower() == hashlib.sha256(data).hexdigest() else "mismatch"
        )
    except FileNotFoundError:
        checksum = "missing"
    if checksum == "mismatch":
        problems.append("The zip does not match its .sha256 checksum: it has changed since it was written")
    elif checksum == "missing":
        problems.append("The .sha256 checksum file is missing, so the zip as a whole cannot be checked")
    man: dict[str, Any] | None = None
    contents: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            man = json.loads(z.read("manifest.json"))
            for name in z.namelist():
                if name != "manifest.json" and not name.endswith("/"):
                    contents[name] = z.read(name)
    except (zipfile.BadZipFile, KeyError, ValueError):
        problems.append("The zip cannot be opened, or has no manifest.json")
        man = None
    if man is not None:
        listed = {e.get("path"): e for e in man.get("files", []) if isinstance(e, dict)}
        for p, e in listed.items():
            if not isinstance(p, str) or not _safe_entry(p):
                problems.append(f"The manifest lists a path outside {SYSTEM}: {p!r}")
            elif p not in contents:
                problems.append(f"{p} is in the manifest but not in the zip")
            elif hashlib.sha256(contents[p]).hexdigest() != e.get("sha256"):
                problems.append(f"{p} does not match its sha256 in the manifest")
        problems += [f"{p} is in the zip but not in the manifest" for p in contents if p not in listed]
        if man.get("files_sha256") != files_digest([e for e in listed.values() if isinstance(e.get("path"), str)]):
            problems.append("The manifest's files_sha256 does not match its file list")
    v = Verification(
        path=path,
        ok=checksum == "ok" and not problems,
        checksum=checksum,
        files=len(contents),
        problems=problems[:50],
    )
    return data, v, man, contents


async def verify(books: Books, path: str, user: str) -> Verification:
    _, v, _, _ = await _open(books, path)
    await books.audit(f"user:{user}", "backup_verified", {"file": v.path, "ok": v.ok, "problems": len(v.problems)})
    return v


RestoreStatus = Literal["new", "same", "changed", "kept"]


class RestoreItem(BaseModel):
    path: str
    status: RestoreStatus
    size: int


class RestorePreview(BaseModel):
    path: str
    verification: Verification
    books_empty: bool  # no ledger events and no proposals now
    needs_confirmation: bool  # type CONFIRM_WORD to restore
    confirm_word: str = CONFIRM_WORD
    counts: dict[str, int]
    items: list[RestoreItem]  # new, changed and kept first; at most 500
    note: str


def _append_only(path: str) -> bool:
    return path.startswith(f"{EVENTS}/") or path.startswith(f"{AUDIT}/")


async def _plan(books: Books, path: str) -> tuple[RestorePreview, dict[str, bytes], dict[str, RestoreStatus]]:
    _, v, man, contents = await _open(books, path)
    if not v.ok:
        raise BackupError("This backup does not pass its checks, so it cannot be restored: " + "; ".join(v.problems))
    assert man is not None
    current = {f.path: f for f in (await fm.walk(books, SYSTEM)).files}
    items: list[RestoreItem] = []
    for p in sorted(contents):
        data = contents[p]
        ref = current.get(p)
        if ref is None:
            status: RestoreStatus = "new"
        elif (await books.storage.read(p)) == data:
            status = "same"
        else:
            status = "kept" if _append_only(p) else "changed"
        items.append(RestoreItem(path=p, status=status, size=len(data)))
    empty = not any(p.startswith(f"{EVENTS}/") or p.startswith(f"{PROPOSALS}/") for p in current)
    counts = {s: sum(i.status == s for i in items) for s in ("new", "same", "changed", "kept")}
    order = {"changed": 0, "kept": 1, "new": 2, "same": 3}
    preview = RestorePreview(
        path=v.path,
        verification=v,
        books_empty=empty,
        needs_confirmation=not empty,
        counts=counts,
        items=sorted(items, key=lambda i: (order[i.status], i.path))[:500],
        note=(
            "Nothing in your books is deleted. New files are added; for a changed file, today's copy goes to "
            "_Trash first. Ledger events and audit files already in your books are never replaced."
        ),
    )
    return preview, contents, {i.path: i.status for i in items}


async def restore_preview(books: Books, path: str) -> RestorePreview:
    return (await _plan(books, path))[0]


class RestoreResult(BaseModel):
    path: str
    restored: int
    replaced: int
    kept: int
    trash: str | None  # the folder the replaced files went to


async def restore(books: Books, path: str, user: str, confirm: str | None) -> RestoreResult:
    plan, contents, status = await _plan(books, path)
    if plan.needs_confirmation and (confirm or "").strip() != CONFIRM_WORD:
        raise ConfirmationNeeded(
            f"Your books are not empty. Check the preview, then type {CONFIRM_WORD} to restore this backup"
        )
    stamp = now().strftime("%H%M%S")
    trash_root = f"restore-{stamp}"
    day = current_date()
    restored = replaced = 0
    for p, data in sorted(contents.items()):
        st = status[p]
        if st == "new":
            await books.storage.write(p, data, create_only=True)
            restored += 1
        elif st == "changed":
            await _trash_as(books, p, day, trash_root)
            await books.storage.write(p, data, create_only=True)
            replaced += 1
    kept = sum(1 for s in status.values() if s == "kept")
    await books.audit(
        f"user:{user}",
        "backup_restored",
        {"file": plan.path, "restored": restored, "replaced": replaced, "kept": kept},
    )
    await books.rebuild_safely(f"user:{user}")
    return RestoreResult(
        path=plan.path,
        restored=restored,
        replaced=replaced,
        kept=kept,
        trash=f"{fm.trash_folder(day)}/{trash_root}" if replaced else None,
    )


async def _trash_as(books: Books, path: str, day: date, sub: str) -> str:
    folder = posixpath.dirname(f"{fm.trash_folder(day)}/{sub}/{path}")
    await books.storage.ensure_folder(folder)
    dest = await books.free_path(folder, posixpath.basename(path))
    await books.storage.move(path, dest)
    return dest
