"""Background scan jobs: a file goes uploaded → reading → confirm its type → checking → ready to review.

No request waits on a model any more. `POST /books/scan/jobs` answers at once with a job; the runtime reads the files
in the background and the app polls `GET /books/scan/jobs/{id}` every couple of seconds (web, phone and Outlook
intake alike). The work carries on when the user leaves the page or closes the app; the top bar shows the count.

Per file:

    uploaded   in 00 Inbox, waiting its turn
    reading    the AI says what kind of document it is (app/ai/classify.py): one short call, text first
    confirm    the guess and its confidence are shown; the user confirms or changes the type. Nothing is read
               further, filed or posted until they do
    checking   routed by the confirmed type:
                 receipt, bill, credit note -> read in full and checked, a card in Review
                 sales invoice              -> the same, as a sale (it posts to Sales when approved)
                 bank statement (CSV)       -> the bank-lines import (Bank); a PDF statement -> Needs a look
                 payslip, something else    -> Needs a look, saying why
    ready / needs_a_look / failed          done (failed: still in 00 Inbox, with the reason in plain words)

Approving stays a separate step in Review: a job never posts anything, except what one of the user's own Autopilot
rules posts, exactly as a scan always has (docs/AUTOPILOT.md).

Time limits: reading the type has CLASSIFY_TIMEOUT_S (default 45 s; past it code guesses from the words and says so);
reading a document in full has the scan's SCAN_DOC_TIMEOUT_S (180 s) with each AI call capped at AI_CALL_TIMEOUT_S
(90 s; app/inbox.py). At most JOB_CONCURRENCY documents of a job (2) and SCAN_CONCURRENCY of the whole server (4) are
read at once.

No database: the job lives in this process while it runs, and is written to the user's own books after every step,
as `_System/Scans/<id>.json`, so a page opened later (or a fresh token after a refresh) still finds it. A job file
whose work stopped with the process (a restart) reads as interrupted, and its files are still in 00 Inbox for the
next scan. Job files older than KEEP_DAYS (7) are removed when the next job starts.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from collections.abc import Callable, Coroutine
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from accnomos_connectors.base import FileRef
from accnomos_ledger.bank import BankCsvError, parse_bank_csv
from app import inbox
from app.ai import classify as classify_ai
from app.ai.classify import KINDS, LABELS, Guess, Kind
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError
from app.books import SYSTEM, Books, now
from app.checks import decide
from app.formats import MAX_BYTES, FormatError, guess_mime, prepare
from app.journal import draft_journal, with_expense_account
from app.paths import INBOX
from app.pipeline import sha256_hex
from app.schemas import Check, Proposal
from app.validation import StrictBody

log = logging.getLogger("accnomos.scan")

SCANS = f"{SYSTEM}/Scans"
Stage = Literal["uploaded", "reading", "confirm", "checking", "ready", "needs_a_look", "failed"]
Route = Literal["review", "sales", "bank", "needs_a_look", "inbox"]
Source = Literal["upload", "inbox", "email", "phone"]
FINAL: frozenset[str] = frozenset({"ready", "needs_a_look", "failed"})
PROGRESS: dict[str, float] = {"uploaded": 0.1, "reading": 0.3, "confirm": 0.5, "checking": 0.75}
STAGE_LABEL: dict[str, str] = {
    "uploaded": "Uploaded",
    "reading": "Reading",
    "confirm": "Confirm the type",
    "checking": "Checking",
    "ready": "Ready to review",
    "needs_a_look": "Needs a look",
    "failed": "Not read",
}
READ_IN_FULL: frozenset[str] = frozenset({"receipt", "purchase_invoice", "credit_note", "sales_invoice"})
SALE_SIDE: frozenset[str] = frozenset({"sales_invoice"})
MAX_FILES = 50
KEEP_DAYS = 7
ID_RE = re.compile(r"[0-9a-f]{32}")
PHOTO_GUESS = Guess(
    kind="receipt", confidence=0.3, reason="A photo with no text layer; most photos are receipts", by="code"
)


def _actor(user: str | None) -> str:
    """The audit line's actor: the signed-in user who confirmed, else the scan agent."""
    return f"user:{user}" if user else "agent:scan"


def _env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


CLASSIFY_TIMEOUT_S = _env("CLASSIFY_TIMEOUT_S", 45)
JOB_CONCURRENCY = max(1, int(_env("JOB_CONCURRENCY", 2)))
SCAN_CONCURRENCY = max(1, int(_env("SCAN_CONCURRENCY", 4)))
STALE_S = inbox.DOC_TIMEOUT_S + inbox.GRACE_S + 60  # a step this old that no task is running was interrupted


class ScanFile(BaseModel):
    name: str
    path: str
    stage: Stage = "uploaded"
    guess: Guess | None = None
    kind: Kind | None = None  # what the user confirmed
    route: Route | None = None
    proposal_id: str | None = None
    message: str | None = None  # one plain sentence for the row
    elapsed_s: float | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def progress(self) -> float:
        return 1.0 if self.stage in FINAL else PROGRESS[self.stage]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def stage_label(self) -> str:
        return STAGE_LABEL[self.stage]


class ScanJob(BaseModel):
    id: str
    source: Source = "upload"
    created_at: datetime
    updated_at: datetime
    files: list[ScanFile]
    interrupted: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> Literal["working", "waiting", "done"]:
        """working: something is being read; waiting: only the user's confirmation is missing; done."""
        stages = {f.stage for f in self.files}
        if stages - FINAL - {"confirm"}:
            return "working"
        return "waiting" if "confirm" in stages else "done"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def progress(self) -> float:
        return round(sum(f.progress for f in self.files) / len(self.files), 3) if self.files else 1.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def counts(self) -> dict[str, int]:
        out = {"working": 0, "to_confirm": 0, "ready": 0, "needs_a_look": 0, "failed": 0}
        for f in self.files:
            key = "to_confirm" if f.stage == "confirm" else "working" if f.stage not in FINAL else f.stage
            out[key] += 1
        return out


class ScanJobList(BaseModel):
    jobs: list[ScanJob]
    working: int  # files being read now, across these jobs
    to_confirm: int  # files waiting for the user to confirm their type


class Confirmation(StrictBody):
    name: str = Field(min_length=1, max_length=255)
    kind: Kind


# --------------------------------------------------------------------------- #
# The running jobs (this process only)
# --------------------------------------------------------------------------- #

Opener = Callable[[], AbstractAsyncContextManager[Books]]


@dataclass
class Settings:
    """What a phase needs from the request that started it (its own credentials come with its `Opener`)."""

    cfg: AiConfig
    business_name: str | None = None
    autopilot_on: bool = True
    period: tuple[date, date] | None = None
    user: str | None = None


@dataclass
class Live:
    job: ScanJob
    owner: str  # Books.cache_key of the request that started it (a hash; never a token)
    tasks: set[asyncio.Task[None]] = field(default_factory=set)
    save_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    touched: float = field(default_factory=time.monotonic)

    def file(self, name: str) -> ScanFile | None:
        return next((f for f in self.job.files if f.name == name), None)

    @property
    def running(self) -> bool:
        return any(not t.done() for t in self.tasks)


LIVE: dict[str, Live] = {}
_GATES: dict[int, asyncio.Semaphore] = {}
LIVE_MAX = 500  # finished jobs are forgotten first; their files in the books remain


def _server_gate() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    return _GATES.setdefault(id(loop), asyncio.Semaphore(SCAN_CONCURRENCY))


def _forget_old() -> None:
    if len(LIVE) <= LIVE_MAX:
        return
    idle = sorted((lv.touched, jid) for jid, lv in LIVE.items() if not lv.running)
    for _, jid in idle[: len(LIVE) - LIVE_MAX]:
        LIVE.pop(jid, None)


def claimed(owner: str) -> frozenset[str]:
    """Inbox paths a running job of this user is reading: the plain /books/scan leaves them alone."""
    return frozenset(
        f.path for lv in LIVE.values() if lv.owner == owner and lv.running for f in lv.job.files if f.stage not in FINAL
    )


def reset_for_tests() -> None:
    LIVE.clear()
    _GATES.clear()


# --------------------------------------------------------------------------- #
# Saving the job in the user's books
# --------------------------------------------------------------------------- #


def _job_path(job_id: str) -> str:
    return f"{SCANS}/{job_id}.json"


async def _save(live: Live, books: Books) -> None:
    live.job.updated_at = now()
    live.touched = time.monotonic()
    async with live.save_lock:
        try:
            await books.write_json(_job_path(live.job.id), live.job.model_dump(mode="json"))
        except Exception:  # noqa: BLE001  the progress file is a convenience; the reading goes on without it
            log.warning("scan job %s: progress not saved", live.job.id[:8], exc_info=True)


async def load_saved(books: Books, job_id: str) -> ScanJob | None:
    raw = await books.read_json(_job_path(job_id), None)
    if not isinstance(raw, dict):
        return None
    for derived in ("status", "progress", "counts"):
        raw.pop(derived, None)
    for f in raw.get("files") or []:
        if isinstance(f, dict):
            f.pop("progress", None)
            f.pop("stage_label", None)
    try:
        return ScanJob.model_validate(raw)
    except ValueError:
        return None


def mark_interrupted(job: ScanJob) -> ScanJob:
    """A saved job whose reading stopped with the process: its unfinished files are still in 00 Inbox."""
    if job.status != "working" or (now() - job.updated_at).total_seconds() < STALE_S:
        return job
    for f in job.files:
        if f.stage not in FINAL and f.stage != "confirm":
            f.stage, f.route = "failed", "inbox"
            f.message = "The reader stopped before this was finished. It is still in 00 Inbox: scan it again."
    job.interrupted = True
    return job


async def _prune(books: Books) -> None:
    cutoff = now() - timedelta(days=KEEP_DAYS)
    for f in await books.list_files(SCANS):
        if not f.name.endswith(".json") or f.modified is None or f.modified >= cutoff:
            continue
        try:
            await books.storage.move(f.path, await books.free_path(f"{SYSTEM}/Originals/Scans", f.name))
        except Exception:  # noqa: BLE001  housekeeping only
            log.info("scan jobs: could not tidy %s", f.name)


# --------------------------------------------------------------------------- #
# Starting, finding, confirming
# --------------------------------------------------------------------------- #


def readable(name: str) -> bool:
    """Files a job takes: everything the reader reads, plus bank statement CSVs."""
    return bool(guess_mime(name)) or name.lower().endswith(".csv")


async def start(
    books: Books,
    opener: Opener,
    settings: Settings,
    names: list[str] | None = None,
    source: Source = "upload",
) -> ScanJob:
    """A job over `names` in 00 Inbox (all readable files when None), started in the background."""
    owner = books.cache_key or ""
    busy = claimed(owner)
    files = [
        f
        for f in await books.list_files(INBOX)
        if readable(f.name) and (names is None or f.name in names) and f.path not in busy
    ]
    files.sort(key=lambda f: (names.index(f.name) if names else 0, f.name))
    job = ScanJob(
        id=uuid.uuid4().hex,
        source=source,
        created_at=now(),
        updated_at=now(),
        files=[ScanFile(name=f.name, path=f.path) for f in files[:MAX_FILES]],
    )
    for name in sorted(set(names or []) - {f.name for f in files}):
        message = "Already being read." if f"{INBOX}/{name}" in busy else "Not in 00 Inbox (moved or already read)."
        job.files.append(ScanFile(name=name, path=f"{INBOX}/{name}", stage="failed", route="inbox", message=message))
    too_big = {f.name for f in files if f.size > MAX_BYTES}
    for sf in job.files:
        if sf.name in too_big:
            sf.stage, sf.route = "failed", "inbox"
            sf.message = f"Over {MAX_BYTES // (1024 * 1024)} MB, so not read. It stays in 00 Inbox."
    live = Live(job=job, owner=owner)
    LIVE[job.id] = live
    _forget_old()
    await books.storage.ensure_folder(SCANS)
    await _save(live, books)
    await _prune(books)
    log.info("scan job %s: started (%s, %d files)", job.id[:8], source, len(job.files))
    _spawn(live, _classify_all(live, opener, settings))
    return job


def _spawn(live: Live, coro: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coro)
    live.tasks.add(task)
    task.add_done_callback(live.tasks.discard)


async def find(books: Books, job_id: str) -> Live | None:
    """This user's job: the running one when the caller owns it (by key, or because the job file is in their books),
    else the saved one (marked interrupted when its work stopped). None when it is not theirs."""
    if not ID_RE.fullmatch(job_id):
        return None
    live = LIVE.get(job_id)
    if live is not None and live.owner == (books.cache_key or ""):
        return live
    saved = await load_saved(books, job_id)
    if saved is None:
        return None
    if live is not None:  # same job, new token (a refresh): the books prove it is theirs
        live.owner = books.cache_key or ""
        return live
    live = Live(job=mark_interrupted(saved), owner=books.cache_key or "")
    LIVE[job_id] = live
    return live


async def recent(books: Books, limit: int = 10) -> ScanJobList:
    """This user's jobs from the last day, newest first: running ones from memory, others from their books."""
    since = now() - timedelta(days=1)
    names = sorted(
        (f for f in await books.list_files(SCANS) if f.name.endswith(".json")),
        key=lambda f: f.modified or since,
        reverse=True,
    )
    jobs: list[ScanJob] = []
    for f in names[:limit]:
        if f.modified and f.modified < since:
            continue
        live = await find(books, f.name.removesuffix(".json"))
        if live is not None:
            jobs.append(live.job)
    jobs.sort(key=lambda j: j.created_at, reverse=True)
    return ScanJobList(
        jobs=jobs,
        working=sum(j.counts["working"] for j in jobs),
        to_confirm=sum(j.counts["to_confirm"] for j in jobs),
    )


class ConfirmError(ValueError):
    pass


async def confirm(live: Live, books: Books, opener: Opener, settings: Settings, items: list[Confirmation]) -> ScanJob:
    """The user's types for files waiting to be confirmed; reading them in full starts in the background."""
    chosen: list[ScanFile] = []
    for item in items:
        f = live.file(item.name)
        if f is None:
            raise ConfirmError(f"{item.name} is not in this job")
        if f.stage != "confirm":
            raise ConfirmError(f"{item.name} is not waiting for its type ({STAGE_LABEL[f.stage].lower()})")
        chosen.append(f)
    for f, item in zip(chosen, items, strict=True):
        f.kind, f.stage, f.message = item.kind, "checking", None
    await _save(live, books)
    await books.audit(
        _actor(settings.user),
        "scan_type_confirmed",
        {
            "job": live.job.id,
            "files": [{"name": f.name, "kind": f.kind, "guess": f.guess.kind if f.guess else None} for f in chosen],
        },
    )
    _spawn(live, _process_all(live, opener, settings, [f.name for f in chosen]))
    return live.job


# --------------------------------------------------------------------------- #
# Phase 1: what kind of document is it?
# --------------------------------------------------------------------------- #


async def _classify_all(live: Live, opener: Opener, settings: Settings) -> None:
    todo = [f for f in live.job.files if f.stage == "uploaded"]
    gate = asyncio.Semaphore(JOB_CONCURRENCY)
    try:
        async with opener() as books:

            async def one(i: int, f: ScanFile) -> None:
                async with gate, _server_gate():
                    t0 = time.perf_counter()
                    f.stage = "reading"
                    await _save(live, books)
                    try:
                        await _classify(books, f, settings)
                    except Exception:  # noqa: BLE001  one file's trouble never stops the others
                        log.warning(
                            "scan job %s: file %d failed while reading its type", live.job.id[:8], i, exc_info=True
                        )
                        f.stage, f.route = "failed", "inbox"
                        f.message = "Something went wrong reading this. It stays in 00 Inbox: try again."
                    f.elapsed_s = round(time.perf_counter() - t0, 1)
                    log.info(
                        "scan job %s: file %d of %d -> %s (%s, %.1f s)",
                        live.job.id[:8],
                        i,
                        len(todo),
                        f.stage,
                        f.guess.kind if f.guess else "-",
                        f.elapsed_s,
                    )
                    await _save(live, books)

            await asyncio.gather(*(one(i + 1, f) for i, f in enumerate(todo)))
    except Exception:  # noqa: BLE001  the books could not be opened (a token that expired, storage down)
        log.warning("scan job %s: could not open the books", live.job.id[:8], exc_info=True)
        for f in todo:
            if f.stage not in FINAL and f.stage != "confirm":
                f.stage, f.route = "failed", "inbox"
                f.message = "Your books could not be opened. The file stays in 00 Inbox: sign in again and retry."


async def _classify(books: Books, f: ScanFile, settings: Settings) -> None:
    try:
        data = await books.storage.read(f.path)
    except FileNotFoundError:
        f.stage, f.route, f.message = "failed", "inbox", "No longer in 00 Inbox (moved or already read)."
        return
    if f.name.lower().endswith(".csv"):
        try:
            lines = parse_bank_csv(data, f.name)
        except BankCsvError as exc:
            f.guess = Guess(
                kind="other", confidence=0.3, reason=f"A CSV that is not a bank statement: {exc}", by="code"
            )
        else:
            f.guess = Guess(
                kind="bank_statement", confidence=0.95, reason=f"A bank CSV with {len(lines)} lines", by="code"
            )
        f.stage = "confirm"
        return
    try:
        prep = await asyncio.to_thread(prepare, data, f.name)
    except FormatError as exc:  # damaged, password-protected, too many pages: a card that says why
        await _needs_a_look(books, settings, f, data, f"Not read: {exc}. Please check it by hand")
        return
    text = prep.text
    try:
        f.guess = await inbox.bounded(
            classify_ai.classify(prep.image, prep.mime, settings.cfg, text=text, business_name=settings.business_name),
            CLASSIFY_TIMEOUT_S,
        )
    except ExtractionError as exc:
        timed_out = isinstance(exc, inbox.DocTimeout) or "timed out" in str(exc) or "did not answer" in str(exc)
        f.guess = classify_ai.by_words(text, f.name, settings.business_name) if text else PHOTO_GUESS
        why = "did not answer in time" if timed_out else "could not say"
        f.message = f"The AI {why}, so this guess is from code. Please check the type."
    f.stage = "confirm"


# --------------------------------------------------------------------------- #
# Phase 2: route each confirmed file
# --------------------------------------------------------------------------- #


async def _process_all(live: Live, opener: Opener, settings: Settings, names: list[str]) -> None:
    todo = [f for f in (live.file(n) for n in names) if f is not None]
    gate = asyncio.Semaphore(JOB_CONCURRENCY)
    try:
        async with opener() as books:
            ctx = await inbox.scan_context(books, settings.business_name, settings.autopilot_on, settings.period)
            inbox_files = {f.path: f for f in await books.list_files(INBOX)}

            async def one(i: int, f: ScanFile) -> None:
                async with gate, _server_gate():
                    t0 = time.perf_counter()
                    try:
                        await _route(books, ctx, settings, f, inbox_files.get(f.path))
                    except Exception:  # noqa: BLE001
                        log.warning("scan job %s: file %d failed while checking", live.job.id[:8], i, exc_info=True)
                        f.stage, f.route = "failed", "inbox"
                        f.message = "Something went wrong checking this. It stays in 00 Inbox: scan it again."
                    f.elapsed_s = round(time.perf_counter() - t0, 1)
                    log.info(
                        "scan job %s: file %d of %d (%s) -> %s via %s (%.1f s)",
                        live.job.id[:8],
                        i,
                        len(todo),
                        f.kind,
                        f.stage,
                        f.route,
                        f.elapsed_s,
                    )
                    await _save(live, books)

            await asyncio.gather(*(one(i + 1, f) for i, f in enumerate(todo)))
            await inbox.finish(books, ctx)
    except Exception:  # noqa: BLE001
        log.warning("scan job %s: could not open the books to check", live.job.id[:8], exc_info=True)
        for f in todo:
            if f.stage not in FINAL:
                f.stage, f.route = "failed", "inbox"
                f.message = "Your books could not be opened. The file stays in 00 Inbox: sign in again and retry."


async def _route(books: Books, ctx: inbox.ScanContext, settings: Settings, f: ScanFile, ref: FileRef | None) -> None:
    if ref is None:
        f.stage, f.route, f.message = "failed", "inbox", "No longer in 00 Inbox (moved or already read)."
        return
    kind = f.kind or "other"
    if kind in READ_IN_FULL and (mime := guess_mime(ref.name)):
        try:
            p, filed, mime = await inbox.read_one(books, ref, mime, settings.cfg, ctx)
        except ExtractionError as exc:
            await books.audit(inbox.ACTOR, "extract_failed", {"path": ref.path, "error": str(exc)[:200]})
            f.stage, f.route = "failed", "inbox"
            f.message = str(exc) if isinstance(exc, inbox.DocTimeout) else f"The AI could not read it: {str(exc)[:200]}"
            return
        apply_kind(p, kind)
        p = await inbox.commit(books, ctx, p, filed, mime)
        f.proposal_id = p.id
        f.route = "sales" if kind in SALE_SIDE else "review"
        f.stage = "needs_a_look" if p.status == "needs_a_look" else "ready"
        if p.status == "posted":
            f.message = "Posted by your Autopilot rule; Undo is on Review."
        return
    data = await books.storage.read(ref.path)
    if kind == "bank_statement" and ref.name.lower().endswith(".csv"):
        await _import_statement(books, settings, f, ref, data)
        return
    message = {
        "bank_statement": "You said this is a bank statement. Statements are imported from the CSV your bank lets "
        "you download (Bank › Import); this copy is kept here for your records.",
        "payslip": "You said this is a payslip. Payslips are not posted from Review: run pay in Payroll, or reject "
        "this card to keep the file only.",
        "other": "You said this is not a receipt, bill, invoice or statement, so nothing was read from it. Type the "
        "figures in if it should be in the books, or reject it.",
    }.get(kind, f"Not read as a {LABELS.get(kind, kind).lower()}: this file type is not one the reader takes.")
    await _needs_a_look(books, settings, f, data, message, ref=ref, ctx=ctx, code="DOC_KIND")


def apply_kind(p: Proposal, kind: str) -> None:
    """The user's type wins over the reader's. Within one side (receipt, bill, credit note) it is noted; across sides
    (a sale read as a purchase, or the other way) the card goes to Needs a look to check who issued it."""
    read = p.extracted.doc_type
    if read == kind:
        return
    across = (read in SALE_SIDE) != (kind in SALE_SIDE)
    p.extracted = p.extracted.model_copy(update={"doc_type": kind})
    p.journal_draft = draft_journal(p.extracted)
    if p.account_override:
        p.journal_draft = with_expense_account(p.journal_draft, p.account_override)
    said, thought = LABELS.get(kind, kind).lower(), LABELS.get(read, read).lower()
    p.checks.append(
        Check(
            code="DOC_KIND",
            ok=not across,
            severity="fail" if across else "warn",
            message=f"You said this is a {said}; the reader took it for a {thought}"
            + (". Check who issued it and the figures before approving" if across else ""),
        )
    )
    p.status, p.reasons = decide(p.checks)


async def _import_statement(books: Books, settings: Settings, f: ScanFile, ref: FileRef, data: bytes) -> None:
    try:
        result = await books.import_bank_csv(data, ref.name, settings.user or "user")
    except BankCsvError as exc:
        f.stage, f.route = "failed", "inbox"
        f.message = f"Not a bank statement CSV this app can read: {exc}. It stays in 00 Inbox."
        return
    await books.storage.ensure_folder(inbox.ORIGINALS)
    await books.storage.move(ref.path, await books.free_path(inbox.ORIGINALS, ref.name))  # the import filed its copy
    if not result.duplicate_file:
        await books.rebuild_safely(_actor(settings.user))
    f.stage, f.route = "ready", "bank"
    f.message = (
        "Already imported: no new bank lines."
        if result.duplicate_file
        else f"{result.new_lines} new bank line{'s' if result.new_lines != 1 else ''}: match them on Bank."
    )


async def _needs_a_look(
    books: Books,
    settings: Settings,
    f: ScanFile,
    data: bytes,
    message: str,
    *,
    ref: FileRef | None = None,
    ctx: inbox.ScanContext | None = None,
    code: str = "UNREADABLE",
) -> None:
    """A card with no figures in Needs a look, saying why, and the file filed with it."""
    ctx = ctx or await inbox.scan_context(books, settings.business_name, settings.autopilot_on, settings.period)
    ref = ref or FileRef(id="", path=f.path, name=f.name, size=len(data))
    p = inbox.placeholder(f.name, sha256_hex(data), message, code)
    p = await inbox.commit(books, ctx, p, ref, guess_mime(f.name) or "application/octet-stream")
    f.proposal_id, f.stage, f.route, f.message = p.id, "needs_a_look", "needs_a_look", message


__all__ = ["KINDS", "LABELS", "Confirmation", "ScanFile", "ScanJob", "ScanJobList", "Settings", "start"]
