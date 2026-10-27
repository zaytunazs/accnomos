"""POST /mail/scan: Outlook intake (F10). Same headers as /books/* (`X-Graph-Token`, `X-Account-Kind`,
optional `X-User`); the token must carry `Mail.Read`. Nothing is kept server-side.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from accnomos_connectors.base import MailProvider
from accnomos_connectors.msgraph import GraphMailProvider
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.books import Books
from app.intake import IntakeResult, scan_mail
from app.routes_books import get_books, optional_user

router = APIRouter(prefix="/mail", tags=["mail"])


async def get_mail(request: Request) -> AsyncIterator[MailProvider]:
    token = request.headers.get("X-Graph-Token", "").strip().removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="X-Graph-Token header required")
    mail = GraphMailProvider(token)
    try:
        yield mail
    finally:
        await mail.aclose()


class MailScanBody(BaseModel):
    since_days: int = Field(14, ge=1, le=90)
    dry_run: bool = False
    max_messages: int = Field(50, ge=1, le=200)


@router.post("/scan", response_model=IntakeResult)
async def mail_scan(
    body: MailScanBody | None = None,
    books: Books = Depends(get_books),
    mail: MailProvider = Depends(get_mail),
    user: str | None = Depends(optional_user),
) -> IntakeResult:
    body = body or MailScanBody()
    return await scan_mail(
        books, mail, since_days=body.since_days, dry_run=body.dry_run,
        user=user, max_messages=body.max_messages,
    )
