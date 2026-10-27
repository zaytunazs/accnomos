"""/mail/*: Outlook intake (F10) and inbox triage. Same headers as /books/* (`X-Graph-Token`, `X-Account-Kind`,
optional `X-User`). Nothing is kept server-side.

* POST /mail/scan         copies receipts into 00 Inbox; the token must carry `Mail.Read`.
* POST /mail/triage       lists business threads with a summary, suggested reply and to-dos; `Mail.Read`.
                          AI headers are optional: without X-AI-Mode no model is called (summaries by code).
* POST /mail/draft-reply  saves a reply in the user's Outlook Drafts; needs `Mail.ReadWrite` and `X-User`.
                          It never sends: the user opens the draft in Outlook and sends it there.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from accnomos_connectors.base import MailProvider
from accnomos_connectors.msgraph import GraphMailProvider
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.ai.config import is_test_mode
from app.ai.config import AiConfig
from app.books import Books
from app.intake import IntakeResult, scan_mail
from app.routes_books import business_name, get_books, optional_user, require_user
from app.routes_plan import optional_ai
from app.triage import TriageResult, triage_mail
from app.validation import StrictBody

router = APIRouter(prefix="/mail", tags=["mail"])


async def get_mail(request: Request) -> AsyncIterator[MailProvider]:
    token = request.headers.get("X-Graph-Token", "").strip().removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="X-Graph-Token header required")
    if is_test_mode():
        from app import testmode

        yield (await testmode.state()).mail
        return
    mail = GraphMailProvider(token)
    try:
        yield mail
    finally:
        await mail.aclose()


class MailScanBody(StrictBody):
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


def chosen_ai(request: Request) -> AiConfig | None:
    """The AI the user picked in the app (X-AI-Mode sent), or None. Unlike /plan/day, never the server's
    fallback model: email previews go only to a backend the user chose."""
    if not request.headers.get("X-AI-Mode"):
        return None
    return optional_ai(request)


class TriageBody(StrictBody):
    since_days: int = Field(7, ge=1, le=30)
    max_threads: int = Field(20, ge=1, le=50)


@router.post("/triage", response_model=TriageResult)
async def mail_triage(
    body: TriageBody | None = None,
    books: Books = Depends(get_books),
    mail: MailProvider = Depends(get_mail),
    cfg: AiConfig | None = Depends(chosen_ai),
    user: str | None = Depends(optional_user),
    business: str | None = Depends(business_name),
) -> TriageResult:
    """Reads the Inbox (previews only) and writes nothing but one audit line of counts."""
    body = body or TriageBody()
    return await triage_mail(
        books, mail, cfg, since_days=body.since_days, max_threads=body.max_threads, user=user, business_name=business,
    )


class DraftReplyBody(StrictBody):
    message_id: str = Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9+/=_-]+$")
    body: str = Field(min_length=1, max_length=5000)


class DraftReplyResult(BaseModel):
    draft_id: str
    web_link: str | None


@router.post("/draft-reply", response_model=DraftReplyResult)
async def mail_draft_reply(
    body: DraftReplyBody,
    books: Books = Depends(get_books),
    mail: MailProvider = Depends(get_mail),
    user: str = Depends(require_user),
) -> DraftReplyResult:
    """Save the user's (possibly edited) reply as an Outlook draft. Never sends."""
    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=422, detail="The reply is empty")
    try:
        draft = await mail.create_reply_draft(body.message_id, text)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="That email is no longer in your mailbox") from exc
    await books.audit(f"user:{user}", "mail_draft_created", {
        "reply_to": body.message_id, "draft": draft.id, "chars": len(text),
    })
    return DraftReplyResult(draft_id=draft.id, web_link=draft.web_link)
