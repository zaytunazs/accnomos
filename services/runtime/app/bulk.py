"""Bulk upload (01 Bulk upload): many files or .zip archives filed in one go.

Users drop any number of files or .zip archives into the bulk folder (and only
there; the Files page and the help say so). A batch job then:

    1. unpacks every .zip safely (no path traversal, caps on files and bytes),
       flattening nested folders and keeping the folder name in each document's
       source note;
    2. classifies the documents a few at a time (concurrency 2) with the same
       reader the Inbox scan uses (app/pipeline.py);
    3. shows one summary to confirm in a single go ("120 receipts, 30 invoices,
       6 bank statements, 4 unclear"), editable per row;
    4. on Confirm all, routes each document the way the scan does
       (filed to its normal folder, proposal saved, audited).

Processed files move out of the bulk folder into the normal filed folders;
failures stay in the bulk folder with a reason on their row.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import uuid
import zipfile
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.ai.config import AiConfig
from app.books import SYSTEM, Books, DocMeta, now
from app.books import today as london_today
from app.files import to_trash
from app.formats import MAX_BYTES, FormatError, guess_mime, prepare
from app.inbox import apply_rule, mailbox_sources
from app.paths import BANK, BULK
from app.pipeline import process_document, sha256_hex
from app.schemas import Proposal

log = logging.getLogger(__name__)

ACTOR = "agent:bulk"
BULK_JOBS = f"{SYSTEM}/Bulk/jobs"
CLASSIFY_CONCURRENCY = 2

DEFAULT_MAX_FILES = 200
DEFAULT_MAX_BYTES = 200 * 1024 * 1024


def bulk_limits() -> tuple[int, int]:
    """(max files, max bytes) unpacked per batch, from the environment when set."""
    try:
        max_files = int(os.getenv("ACCNOMOS_BULK_MAX_FILES", str(DEFAULT_MAX_FILES)))
    except ValueError:
        max_files = DEFAULT_MAX_FILES
    try:
        max_bytes = int(os.getenv("ACCNOMOS_BULK_MAX_BYTES", str(DEFAULT_MAX_BYTES)))
    except ValueError:
        max_bytes = DEFAULT_MAX_BYTES
    return max(max_files, 1), max(max_bytes, 1)


class BulkError(ValueError):
    """A zip (or the batch) cannot be unpacked as asked: traversal, caps, damage."""


_UNSAFE = re.compile(r'[\\/:*?"<>|#%\x00-\x1f]+')  # OneDrive-forbidden and URL-awkward characters


def safe_name(text: str, limit: int = 120) -> str:
    """A zip member's base name made safe for OneDrive; "" when nothing usable is left."""
    return _UNSAFE.sub("_", text).strip(" ._")[:limit].rstrip(" .")


class UnpackedMember(BaseModel):
    """One file from inside a zip, flattened: `name` is the safe base name, `note` keeps where it was."""

    name: str
    data: bytes
    note: str  # e.g. "from january.zip" or "from january.zip/February"


def plan_unpack(
    zip_data: bytes,
    zip_name: str,
    *,
    max_files: int,
    max_bytes: int,
    already_bytes: int = 0,
    already_files: int = 0,
) -> list[UnpackedMember]:
    """The members of `zip_data` to write, flattened, or raises BulkError.

    Pure (no storage): traversal is refused entry by entry, so one bad path never
    stops the honest files around it from being listed; caps count the whole batch
    (`already_*` is what earlier zips of this batch already unpacked).
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_data))
    except zipfile.BadZipFile as exc:
        raise BulkError(f"{zip_name} is not a readable zip archive") from exc
    out: list[UnpackedMember] = []
    total_files = already_files
    total_bytes = already_bytes
    bad: list[str] = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        raw = info.filename.replace("\\", "/").strip()
        parts = [p for p in raw.split("/") if p not in ("", ".")]
        if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw) or any(p == ".." for p in parts):
            bad.append(info.filename)
            continue
        base = safe_name(parts[-1])
        if not base:
            bad.append(info.filename)
            continue
        if info.file_size > MAX_BYTES:
            bad.append(info.filename)
            continue
        total_files += 1
        total_bytes += info.file_size
        if total_files > max_files:
            raise BulkError(f"{zip_name} would unpack more than {max_files} files in this batch")
        if total_bytes > max_bytes:
            raise BulkError(f"{zip_name} would unpack more than {max_bytes // (1024 * 1024)} MB in this batch")
        with archive.open(info) as fh:
            data = fh.read(info.file_size + 1)
        if len(data) > info.file_size:  # the header lied about the size: refuse rather than overflow the cap
            raise BulkError(f"{zip_name}/{info.filename} is larger than its header says")
        subdir = "/".join(parts[:-1])
        note = f"from {zip_name}/{subdir}" if subdir else f"from {zip_name}"
        out.append(UnpackedMember(name=base, data=data, note=note))
    if bad:
        log.warning("bulk unpack skipped %d unsafe or oversize entries in %s", len(bad), zip_name)
    return out


# --------------------------------------------------------------------------- #
# Batch jobs
# --------------------------------------------------------------------------- #


class BulkRow(BaseModel):
    name: str  # file name in the bulk folder (after unpacking)
    path: str  # full path in the bulk folder
    source_note: str | None = None  # which zip or subfolder it came from, when flattened
    doc_type: str = "unclear"  # receipt | sales_invoice | bank_statement | unclear
    supplier: str | None = None
    gross: float | None = None
    status: str = "ready"  # ready | failed | routed
    reason: str | None = None  # why this row failed or was left behind
    proposal_id: str | None = None


EDIT_TYPES = ("receipt", "purchase_invoice", "sales_invoice", "credit_note", "bank_statement", "unclear")
"""Document types the confirm screen accepts per row; 'unclear' keeps the classifier's reading."""


class BulkJob(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "classified"  # classified | confirmed
    created_at: datetime = Field(default_factory=now)
    rows: list[BulkRow] = []
    summary: str = ""
    errors: list[dict[str, str]] = []


CATEGORY_LABELS = (
    ("receipt", "receipts"),
    ("purchase_invoice", "receipts"),
    ("sales_invoice", "invoices"),
    ("bank_statement", "bank statements"),
)


def category_of(doc_type: str) -> str:
    """The summary bucket for a classified document type; anything else is unclear."""
    return next((label for kind, label in CATEGORY_LABELS if doc_type == kind), "unclear")


def summarise(rows: list[BulkRow]) -> str:
    """One line for the confirm screen: '120 receipts, 30 invoices, 6 bank statements, 4 unclear'."""
    counts: dict[str, int] = {}
    for r in rows:
        label = category_of(r.doc_type) if r.status != "failed" else "unclear"
        counts[label] = counts.get(label, 0) + 1
    order = (("receipts", "receipt"), ("invoices", "invoice"), ("bank statements", "bank statement"))
    parts = [f"{counts[p]} {s if counts[p] == 1 else p}" for p, s in order if counts.get(p)]
    if counts.get("unclear"):
        parts.append(f"{counts['unclear']} unclear")
    return ", ".join(parts) or "nothing to file"


Classifier = Callable[[str, bytes], Awaitable[Proposal]]
"""(file name, data) -> proposal. The default reads with app/pipeline.py; tests stub it."""


async def _default_classifier(books: Books, cfg: AiConfig, known: set[str]) -> Classifier:
    rules = await books.load_rules()

    async def classify(name: str, data: bytes) -> Proposal:
        prep = await asyncio.to_thread(prepare, data, name)
        digest = sha256_hex(data)
        proposal = await process_document(prep, cfg, frozenset(known), digest=digest)
        apply_rule(proposal, books.match_rule(proposal.extracted, rules))
        proposal.source_name = name
        return proposal

    return classify


async def _list_all(books: Books, folder: str) -> list[Any]:
    """Every file under `folder`, following subfolders; empty when the folder is missing."""
    out: list[Any] = []

    async def walk(path: str) -> None:
        try:
            entries = await books.storage.list(path)
        except FileNotFoundError:
            return
        for e in entries:
            if e.is_folder:
                await walk(e.path)
            else:
                out.append(e)

    await walk(folder)
    return sorted(out, key=lambda f: f.path)


async def start_job(
    books: Books,
    cfg: AiConfig,
    *,
    limit: int = 50,
    classifier: Classifier | None = None,
) -> BulkJob:
    """Unpack the zips in the bulk folder, classify what is there (two at a time) and save the batch job.

    Proposals are saved for Review now; Confirm all files them to their normal
    folders. Raises nothing: per-file trouble lands on the row (or `errors`).
    """
    await books.ensure_tree()
    max_files, max_bytes = bulk_limits()
    job = BulkJob()
    unpacked_files, unpacked_bytes = 0, 0
    for ref in await _list_all(books, BULK):
        if not ref.name.lower().endswith(".zip"):
            continue
        try:
            members = await asyncio.to_thread(
                plan_unpack,
                await books.storage.read(ref.path),
                ref.name,
                max_files=max_files,
                max_bytes=max_bytes,
                already_bytes=unpacked_bytes,
                already_files=unpacked_files,
            )
        except BulkError as exc:
            job.errors.append({"path": ref.path, "error": str(exc)[:300]})
            continue
        for m in members:
            dest = await books.free_path(BULK, m.name)
            await books.storage.write(dest, m.data)
            unpacked_files += 1
            unpacked_bytes += len(m.data)
            job.rows.append(
                BulkRow(
                    name=dest.rsplit("/", 1)[-1],
                    path=dest,
                    source_note=m.note,
                    doc_type="unclear",
                    status="ready",
                )
            )
        # The zip served its purpose; its files are now loose in the bulk folder. Nothing is
        # ever deleted: it goes to _Trash, which only the user empties in OneDrive.
        trashed = await to_trash(books, ref.path, london_today())
        await books.audit(
            ACTOR, "bulk_unpacked", {"zip": ref.path, "trashed_as": trashed, "files": len(members), "job": job.id}
        )
    # Everything now in the bulk folder (the zips are gone), oldest first, up to `limit`.
    # Files no reader accepts still get a row, so they stay visible with their reason.
    candidates = await _list_all(books, BULK)
    known = await books.known_hashes()
    sources = await mailbox_sources(books)
    classify = classifier or await _default_classifier(books, cfg, known)
    gate = asyncio.Semaphore(CLASSIFY_CONCURRENCY)
    notes = {r.path: r.source_note for r in job.rows}

    async def one(path: str) -> BulkRow:
        async with gate:
            name = path.rsplit("/", 1)[-1]
            if name.lower().endswith(".csv"):
                return BulkRow(name=name, path=path, source_note=notes.get(path), doc_type="bank_statement")
            if not guess_mime(name):
                return BulkRow(
                    name=name,
                    path=path,
                    source_note=notes.get(path),
                    status="failed",
                    reason="Not a document Accnomos reads (a photo, PDF or email text)",
                )
            try:
                data = await books.storage.read(path)
                if len(data) > MAX_BYTES:
                    return BulkRow(name=name, path=path, status="failed", reason="File is too large; not read")
                proposal = await classify(name, data)
            except FormatError as exc:
                return BulkRow(
                    name=name, path=path, source_note=notes.get(path), status="failed", reason=str(exc)[:300]
                )
            except Exception as exc:  # noqa: BLE001  one unreadable file must not stop the batch
                log.warning("bulk classify failed for %s: %s", path, exc)
                return BulkRow(
                    name=name, path=path, source_note=notes.get(path), status="failed", reason=str(exc)[:300]
                )
            proposal.created_at = now()
            proposal.source_mailbox = sources.get(proposal.doc_sha256)
            if proposal.source_note is None:
                proposal.source_note = notes.get(path)
            proposal.source_name = name
            await books.save_proposal(proposal)
            if proposal.doc_sha256 not in known:
                await books.save_doc(
                    DocMeta(
                        sha256=proposal.doc_sha256,
                        source_name=name,
                        mime=guess_mime(name) or "application/octet-stream",
                        size=len(data),
                        proposal_id=proposal.id,
                    )
                )
                known.add(proposal.doc_sha256)
            return BulkRow(
                name=name,
                path=path,
                source_note=notes.get(path),
                doc_type=proposal.extracted.doc_type,
                supplier=proposal.extracted.supplier_name,
                gross=proposal.extracted.gross_total,
                proposal_id=proposal.id,
            )

    classified = await asyncio.gather(*(one(f.path) for f in candidates[:limit]))
    by_path = {r.path: r for r in classified}
    merged = [by_path.get(r.path, r) for r in job.rows]
    merged += [r for r in classified if r.path not in {m.path for m in job.rows}]
    job.rows = merged
    job.summary = summarise(job.rows)
    await books.write_json(f"{BULK_JOBS}/{job.id}.json", job.model_dump(mode="json"))
    await books.record_scan(now())
    return job


async def load_job(books: Books, job_id: str) -> BulkJob:
    """A batch job by id. Raises FileNotFoundError for anything but a plain id."""
    if not re.fullmatch(r"[0-9a-f]{8,64}", job_id):
        raise FileNotFoundError(job_id)
    return BulkJob.model_validate_json(await books.storage.read(f"{BULK_JOBS}/{job_id}.json"))


async def confirm_job(
    books: Books,
    job_id: str,
    edits: dict[str, str] | None = None,
) -> BulkJob:
    """Confirm all: apply per-row type edits, then route every ready row the way the scan does.

    Each document is moved out of the bulk folder to its normal filed folder and
    its proposal updated; failures stay in the bulk folder with a reason.
    """
    job = await load_job(books, job_id)
    edits = edits or {}
    for row in job.rows:
        if row.status != "ready":
            continue
        if row.proposal_id is None:
            if row.doc_type == "bank_statement":  # a statement CSV: filed, never extracted
                try:
                    dest = await books.free_path(BANK, row.name)
                    await books.storage.ensure_folder(BANK)
                    await books.storage.move(row.path, dest)
                except Exception as exc:  # noqa: BLE001  a stuck file stays, with its reason
                    row.status, row.reason = "failed", str(exc)[:300]
                    continue
                await books.audit(ACTOR, "bulk_routed", {"path": dest, "job": job.id})
                row.status = "routed"
                continue
            row.status, row.reason = "failed", "Nothing to route for this file"
            continue
        try:
            proposal = await books.get_proposal(row.proposal_id)
        except FileNotFoundError:
            row.status, row.reason = "failed", "Its proposal is gone; classify the batch again"
            continue
        if row.path in edits:
            want = edits[row.path]
            if want not in EDIT_TYPES:
                raise ValueError(f"Unknown document type {want!r} for {row.name}")
            if want != "unclear":
                proposal.extracted.doc_type = want  # type: ignore[assignment]
        folder = BANK if proposal.extracted.doc_type == "bank_statement" else None
        try:
            await books.file_document(proposal, row.path, folder=folder)
        except Exception as exc:  # noqa: BLE001  a stuck file stays, with its reason
            row.status, row.reason = "failed", str(exc)[:300]
            continue
        proposal.source_name = row.name
        if proposal.source_note is None:
            proposal.source_note = row.source_note
        await books.save_proposal(proposal)
        refs = {
            "proposal": proposal.id,
            "doc": proposal.doc_sha256,
            "status": proposal.status,
            "path": proposal.file_path,
        }
        await books.audit(ACTOR, "proposed", refs)
        row.doc_type = proposal.extracted.doc_type
        row.status = "routed"
    job.status = "confirmed"
    job.summary = summarise(job.rows)
    await books.write_json(f"{BULK_JOBS}/{job.id}.json", job.model_dump(mode="json"))
    return job
