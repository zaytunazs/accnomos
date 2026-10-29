"""/books/scan/jobs: read Inbox files in the background, with progress and a type the user confirms (app/scan_jobs.py).

    POST /books/scan/jobs                    {names?: [...], source?}: start a job (202), answers at once
    GET  /books/scan/jobs                    this user's jobs of the last day, with the counts the top bar shows
    GET  /books/scan/jobs/{id}               one job: every file's stage, guess, route and message
    POST /books/scan/jobs/{id}/confirm       {files: [{name, kind}]}: the user's types; needs X-User

Same headers as /books/scan (X-Graph-Token or X-Demo-Session, X-AI-*, X-Business-Name, X-Autopilot, the VAT
settings in the query). Every call is short: the reading happens after the answer.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import Field

from app import scan_jobs
from app.ai.config import AiConfig, ai_config_from_request
from app.books import Books
from app.books import today as current_date
from app.routes_books import business_name, get_books, optional_user, require_user
from app.scan_jobs import Confirmation, Opener, ScanJob, ScanJobList, Settings, Source
from app.validation import StrictBody
from app.vat_cycle import VatCycle, vat_cycle

router = APIRouter(prefix="/books/scan/jobs", tags=["books"])


def books_opener(request: Request) -> Opener:
    """Opens these books again for the background work, from this request's headers (tests override it)."""
    return lambda: asynccontextmanager(get_books)(request)


def settings(
    cfg: AiConfig = Depends(ai_config_from_request),
    business: str | None = Depends(business_name),
    x_autopilot: str | None = Header(default=None),
    cycle: VatCycle = Depends(vat_cycle),
    user: str | None = Depends(optional_user),
) -> Settings:
    return Settings(
        cfg=cfg,
        business_name=business,
        autopilot_on=(x_autopilot or "on").strip().lower() != "off",
        period=cycle.current(current_date()),
        user=user,
    )


class StartBody(StrictBody):
    names: list[str] | None = Field(default=None, max_length=scan_jobs.MAX_FILES)  # in 00 Inbox; None = every file
    source: Source = "upload"


class ConfirmBody(StrictBody):
    files: list[Confirmation] = Field(min_length=1, max_length=scan_jobs.MAX_FILES)


def _writable(books: Books) -> None:
    if books.read_only:  # an accountant with view access to a client's books
        raise HTTPException(status_code=403, detail="These books are shared with you to view only")


async def _job(job_id: str, books: Books) -> scan_jobs.Live:
    live = await scan_jobs.find(books, job_id)
    if live is None:
        raise HTTPException(status_code=404, detail="No such scan")
    return live


@router.post("", response_model=ScanJob, status_code=202)
async def start(
    body: StartBody | None = None,
    books: Books = Depends(get_books),
    opener: Opener = Depends(books_opener),
    s: Settings = Depends(settings),
) -> ScanJob:
    body = body or StartBody()
    _writable(books)
    if body.names is not None and any("/" in n or "\\" in n or n in ("", ".", "..") for n in body.names):
        raise HTTPException(status_code=400, detail="Give file names in 00 Inbox, not paths")
    return await scan_jobs.start(books, opener, s, body.names, body.source)


@router.get("", response_model=ScanJobList)
async def recent(books: Books = Depends(get_books)) -> ScanJobList:
    return await scan_jobs.recent(books)


@router.get("/{job_id}", response_model=ScanJob)
async def one(job_id: str, books: Books = Depends(get_books)) -> ScanJob:
    return (await _job(job_id, books)).job


@router.post("/{job_id}/confirm", response_model=ScanJob)
async def confirm(
    job_id: str,
    body: ConfirmBody,
    books: Books = Depends(get_books),
    opener: Opener = Depends(books_opener),
    s: Settings = Depends(settings),
    user: str = Depends(require_user),
) -> ScanJob:
    _writable(books)
    live = await _job(job_id, books)
    if len({f.name for f in body.files}) != len(body.files):
        raise HTTPException(status_code=400, detail="Each file once, please")
    s.user = user
    try:
        return await scan_jobs.confirm(live, books, opener, s, body.files)
    except scan_jobs.ConfirmError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
