"""Back up now: a full, dated backup of the books in a folder of its own, apart from the live books.

    Accnomos Backups/YYYY-MM-DD-HHMM/        (Europe/London time; a second in the same minute gets "-2")
        books-system.zip          every file under _System (ledger events, proposals, audit, settings, contacts,
                                  the documents' records), with manifest.json inside: app/backups.py writes it
        books-system.zip.sha256   the zip's own sha256 ("<hex>  <name>", as sha256sum writes)
        Books.xlsx                a copy of the spreadsheet, when the books have one
        documents-index.json      every document outside _System, Backups and _Trash: path, size, date, tax year
                                  and what in the books points at it (the Files page's index). The documents
                                  themselves stay where they are; OneDrive keeps their version history.
        manifest.json             each file above with its size and sha256, who made the backup and when
        RESTORE.txt               how to restore, in plain words

The folder sits at the top of the books folder. A personal Microsoft account gives Accnomos only its app folder
(Files.ReadWrite.AppFolder: "Apps/Accnomos"), so a backup cannot sit outside it there; it is still a separate
folder from the live books' folders, never moved by Archive or Clean up (app/files.py protects it). Work accounts
use the same layout under /Accnomos. Nothing is deleted: there is no retention for full backups; the user removes
old ones in OneDrive.

Restoring uses app/backups.py's verify, preview and restore on books-system.zip (it never deletes, and asks for the
typed word RESTORE unless the books are empty). Books.xlsx is rebuilt from _System afterwards.

`back_up_full` yields progress steps (the web shows them as they happen) and ends with the result. Audited as
`full_backup_created`.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app import backups
from app import files as fm
from app.books import Books, now
from app.paths import FULL_BACKUPS, SYSTEM

LONDON = ZoneInfo("Europe/London")
FORMAT = "accnomos-full-backup/1"
XLSX = "Books.xlsx"
INDEX = "documents-index.json"
MANIFEST = "manifest.json"
README = "RESTORE.txt"
MAX_LISTED = 50
_STAMP = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(?:-(\d+))?$")

Step = Literal["folder", "ledger", "spreadsheet", "index", "manifest", "done"]
STEPS: tuple[Step, ...] = ("folder", "ledger", "spreadsheet", "index", "manifest", "done")
STEP_LABEL: dict[Step, str] = {
    "folder": "Making the backup folder",
    "ledger": "Copying the ledger, audit trail and settings (_System)",
    "spreadsheet": "Copying Books.xlsx",
    "index": "Writing the documents index",
    "manifest": "Writing the checksums and restore instructions",
    "done": "Backup finished",
}


class FullBackupFile(BaseModel):
    name: str
    size: int
    sha256: str


class FullBackup(BaseModel):
    folder: str  # "Accnomos Backups/2026-10-29-1432"
    name: str  # "2026-10-29-1432"
    created_at: datetime | None = None
    created_by: str | None = None
    files: list[FullBackupFile] = []
    ledger_files: int | None = None  # files inside books-system.zip
    documents: int | None = None  # documents listed in the index
    system_zip: str | None = None  # the path verify/restore take
    web_url: str | None = None
    complete: bool = False  # manifest.json is there (written last)


class Progress(BaseModel):
    step: Step
    label: str
    done: int  # steps finished, of `total`
    total: int


def stamp(at: datetime) -> str:
    return at.astimezone(LONDON).strftime("%Y-%m-%d-%H%M")


def restore_text(folder: str, at: datetime, user: str) -> str:
    return f"""Accnomos full backup
Made {at.astimezone(LONDON):%d %B %Y at %H:%M} (UK time) by {user}.
Folder: {folder}

What is in it
- books-system.zip: everything in {SYSTEM} (ledger, proposals, audit trail, settings, contacts and the records
  of every document), with manifest.json inside listing each file's sha256.
- books-system.zip.sha256: the checksum of the zip itself.
- {XLSX}: the spreadsheet of your books as it was (when you had one).
- {INDEX}: the list of your documents (receipts, invoices, statements) and what in the books points at each.
  The documents themselves stay in their folders; OneDrive keeps their earlier versions.
- {MANIFEST}: the size and sha256 of each file in this folder.

How to restore
1. In Accnomos, open Settings > Files & backups (or the Files page) and find this backup under "Full backups".
2. Press "Check" to verify it against its checksums.
3. Press "Restore", read the preview (each file is new, the same, changed or kept), and type RESTORE.
   Nothing is deleted: a changed file's current copy goes to _Trash first, and ledger events and audit files
   already in your books are never replaced.
4. Books.xlsx is rebuilt from the restored books the next time you approve something, or from Reports.

Without the app: unzip books-system.zip; its {SYSTEM} folder is the same folder you have in OneDrive, and every
file in it is plain JSON or JSON lines you can read.
"""


async def _folder_for(books: Books, at: datetime) -> str:
    base = stamp(at)
    taken = {f.name for f in await books.storage.list(FULL_BACKUPS) if f.is_folder}
    name, n = base, 1
    while name in taken:
        n += 1
        name = f"{base}-{n}"
    return f"{FULL_BACKUPS}/{name}"


async def back_up_full(books: Books, user: str) -> AsyncIterator[Progress | FullBackup]:
    """Write a full backup, yielding a Progress before each step and the FullBackup at the end."""
    total = len(STEPS) - 1

    def at(step: Step) -> Progress:
        return Progress(step=step, label=STEP_LABEL[step], done=STEPS.index(step), total=total)

    created = now()
    yield at("folder")
    await books.storage.ensure_folder(FULL_BACKUPS)
    folder = await _folder_for(books, created)
    ref = await books.storage.ensure_folder(folder)
    written: list[FullBackupFile] = []

    async def put(name: str, data: bytes) -> None:
        await books.storage.write(f"{folder}/{name}", data, create_only=True)
        written.append(FullBackupFile(name=name, size=len(data), sha256=hashlib.sha256(data).hexdigest()))

    yield at("ledger")
    z = await backups.system_zip(books, created.astimezone(LONDON).date())
    await put(backups.SYSTEM_ZIP, z.data)
    await books.storage.write(
        f"{folder}/{backups.SYSTEM_ZIP}.sha256", f"{z.sha256}  {backups.SYSTEM_ZIP}\n".encode(), create_only=True
    )

    yield at("spreadsheet")
    with contextlib.suppress(FileNotFoundError):  # no spreadsheet yet: the ledger zip is the backup
        await put(XLSX, await books.storage.read(XLSX))

    yield at("index")
    index = await fm.index(books)
    await put(INDEX, index.model_dump_json(indent=2).encode())

    yield at("manifest")
    await put(README, restore_text(folder, created, user).encode())
    manifest = {
        "format": FORMAT,
        "created_at": created.isoformat(),
        "created_by": user,
        "folder": folder,
        "ledger_files": z.files,
        "documents": len(index.files),
        "files": [f.model_dump() for f in written],
    }
    await books.storage.write(f"{folder}/{MANIFEST}", json.dumps(manifest, indent=2).encode(), create_only=True)
    await books.audit(
        f"user:{user}",
        "full_backup_created",
        {
            "folder": folder,
            "files": [f.name for f in written],
            "ledger_files": z.files,
            "documents": len(index.files),
            "bytes": sum(f.size for f in written),
            "system_zip_sha256": z.sha256,
        },
    )
    yield at("done")
    yield FullBackup(
        folder=folder,
        name=folder.rsplit("/", 1)[1],
        created_at=created,
        created_by=user,
        files=written,
        ledger_files=z.files,
        documents=len(index.files),
        system_zip=f"{folder}/{backups.SYSTEM_ZIP}",
        web_url=ref.web_url,
        complete=True,
    )


async def run(books: Books, user: str) -> FullBackup:
    """The whole backup without progress (the plain JSON route)."""
    result: FullBackup | None = None
    async for item in back_up_full(books, user):
        if isinstance(item, FullBackup):
            result = item
    assert result is not None
    return result


async def list_full(books: Books) -> list[FullBackup]:
    """Full backups, newest first (at most 50), each read from its manifest.json; a folder without one is listed as
    incomplete (a backup that stopped part way)."""
    try:
        found = [f for f in await books.storage.list(FULL_BACKUPS) if f.is_folder and _STAMP.match(f.name)]
    except FileNotFoundError:
        return []
    found.sort(key=lambda f: (f.name[:15], int(_STAMP.match(f.name).group(6) or 1)), reverse=True)  # type: ignore[union-attr]
    out: list[FullBackup] = []
    for f in found[:MAX_LISTED]:
        folder = f"{FULL_BACKUPS}/{f.name}"
        try:
            man = json.loads(await books.storage.read(f"{folder}/{MANIFEST}"))
        except (FileNotFoundError, ValueError):
            out.append(FullBackup(folder=folder, name=f.name, web_url=f.web_url))
            continue
        out.append(
            FullBackup(
                folder=folder,
                name=f.name,
                created_at=man.get("created_at"),
                created_by=man.get("created_by"),
                files=[FullBackupFile.model_validate(x) for x in man.get("files", []) if isinstance(x, dict)],
                ledger_files=man.get("ledger_files"),
                documents=man.get("documents"),
                system_zip=f"{folder}/{backups.SYSTEM_ZIP}",
                web_url=f.web_url,
                complete=True,
            )
        )
    return out
