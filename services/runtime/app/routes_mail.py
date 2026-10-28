"""/mail/*: Outlook intake (F10) and inbox triage. Same headers as /books/* (`X-Graph-Token`, `X-Account-Kind`,
optional `X-User`). Nothing is kept server-side.

* POST /mail/scan         copies receipts from one mailbox into 00 Inbox. The signed-in one (no `mailbox`): the
                          X-Graph-Token must carry `Mail.Read`. A linked one (`mailbox`: its id): its own token in
                          `X-Mailbox-Token` (a Microsoft account's `Mail.Read`, or for a shared mailbox the signed-in
                          work account's `Mail.Read.Shared`); X-Graph-Token still writes the books. One mailbox per
                          request, so each token travels alone and is never stored or logged (app/security.py
                          scrubs it like X-Graph-Token).
* GET/POST /mail/mailboxes, PATCH/DELETE /mail/mailboxes/{id}
                          the linked mailboxes in _System/mail/mailboxes.json (app/mailboxes.py); never tokens.
* POST /mail/triage       lists business threads with a summary, suggested reply and to-dos; `Mail.Read`.
                          AI headers are optional: without X-AI-Mode no model is called (summaries by code).
* POST /mail/draft-reply  saves a reply in the user's Outlook Drafts; needs `Mail.ReadWrite` and `X-User`.
                          It never sends: the user opens the draft in Outlook and sends it there.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

from accnomos_connectors.base import MailProvider
from accnomos_connectors.msgraph import GraphError, GraphMailProvider
from app import mailboxes as mb
from app.ai.config import AiConfig, is_test_mode
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


MailFactory = Callable[[str, mb.Mailbox], MailProvider]  # (that mailbox's token, the linked mailbox)


async def get_mail_factory() -> AsyncIterator[MailFactory]:
    """Opens a provider for a linked mailbox; every one opened is closed when the request ends."""
    if is_test_mode():
        from app import testmode

        state = await testmode.state()
        yield lambda _token, box: state.linked_mail(box.address)
        return
    opened: list[GraphMailProvider] = []

    def make(token: str, box: mb.Mailbox) -> MailProvider:
        # A shared mailbox is /users/{address} with the signed-in account's token; another account's is its /me.
        provider = GraphMailProvider(token, mailbox=box.address if box.kind == "shared" else None)
        opened.append(provider)
        return provider

    try:
        yield make
    finally:
        for provider in opened:
            await provider.aclose()


def mailbox_token(x_mailbox_token: str | None = Header(default=None)) -> str | None:
    return (x_mailbox_token or "").strip().removeprefix("Bearer ").strip() or None


class MailScanBody(StrictBody):
    since_days: int = Field(default=14, ge=1, le=90)
    dry_run: bool = False
    max_messages: int = Field(default=50, ge=1, le=200)
    mailbox: str | None = Field(
        default=None, max_length=32, pattern=r"^[a-z0-9]{1,32}$"
    )  # a linked mailbox's id; None = yours


def _http(exc: mb.MailboxError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.post("/scan", response_model=IntakeResult)
async def mail_scan(
    body: MailScanBody | None = None,
    books: Books = Depends(get_books),
    primary: MailProvider = Depends(get_mail),
    user: str | None = Depends(optional_user),
    token: str | None = Depends(mailbox_token),
    factory: MailFactory = Depends(get_mail_factory),
) -> IntakeResult:
    body = body or MailScanBody()
    try:
        box = await mb.get_mailbox(books, body.mailbox or mb.PRIMARY_ID, user)
    except mb.MailboxError as exc:
        raise _http(exc) from exc
    if box.id == mb.PRIMARY_ID:
        mail = primary
    elif not token:
        raise HTTPException(status_code=401, detail=f"X-Mailbox-Token header required to read {box.address}")
    else:
        mail = factory(token, box)
    try:
        return await scan_mail(
            books,
            mail,
            since_days=body.since_days,
            dry_run=body.dry_run,
            user=user,
            max_messages=body.max_messages,
            mailbox=box,
        )
    except (GraphError, FileNotFoundError) as exc:
        status = exc.status if isinstance(exc, GraphError) else 404
        reason = (
            f"mailbox or folder {box.folder!r} not found"
            if status == 404
            else "no access (sign in again, or ask for access)"
            if status in (401, 403)
            else f"Microsoft Graph answered {status}"
        )
        if not body.dry_run:
            await mb.record_scan(books, box, 0, reason)
        code = 403 if status in (401, 403) else 404 if status == 404 else 502
        raise HTTPException(
            status_code=code, detail=f"Could not read {box.address or 'your mailbox'}: {reason}"
        ) from exc


class MailboxList(BaseModel):
    mailboxes: list[mb.Mailbox]


Sender = Annotated[str, Field(max_length=254)]


class AddMailboxBody(StrictBody):
    address: str = Field(min_length=3, max_length=254)
    kind: Literal["microsoft", "shared"]
    folder: str = Field(default="all", max_length=100)
    allow_senders: list[Sender] = Field(default_factory=list, max_length=mb.MAX_FILTERS)
    deny_senders: list[Sender] = Field(default_factory=list, max_length=mb.MAX_FILTERS)


class UpdateMailboxBody(StrictBody):
    folder: str | None = Field(default=None, max_length=100)
    allow_senders: list[Sender] | None = Field(default=None, max_length=mb.MAX_FILTERS)
    deny_senders: list[Sender] | None = Field(default=None, max_length=mb.MAX_FILTERS)


MAILBOX_ID = r"^[a-z0-9]{1,32}$"


@router.get("/mailboxes", response_model=MailboxList)
async def list_mailboxes(books: Books = Depends(get_books), user: str | None = Depends(optional_user)) -> MailboxList:
    return MailboxList(mailboxes=await mb.list_mailboxes(books, user))


@router.post("/mailboxes", response_model=mb.Mailbox, status_code=201)
async def add_mailbox(
    body: AddMailboxBody,
    request: Request,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> mb.Mailbox:
    """Link a mailbox. Only its address and settings are kept; the web app holds its sign-in."""
    if body.kind == "shared" and (request.headers.get("X-Account-Kind") or "").strip().lower() != "work":
        raise HTTPException(
            status_code=400,
            detail="Shared mailboxes need a work or school account (Mail.Read.Shared is not offered to personal ones)",
        )
    try:
        return await mb.add_mailbox(
            books,
            address=body.address,
            kind=body.kind,
            user=user,
            folder=body.folder,
            allow_senders=body.allow_senders,
            deny_senders=body.deny_senders,
        )
    except mb.MailboxError as exc:
        raise _http(exc) from exc


@router.patch("/mailboxes/{mailbox_id}", response_model=mb.Mailbox)
async def update_mailbox(
    body: UpdateMailboxBody,
    mailbox_id: str = PathParam(pattern=MAILBOX_ID),
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> mb.Mailbox:
    try:
        return await mb.update_mailbox(
            books,
            mailbox_id,
            user=user,
            folder=body.folder,
            allow_senders=body.allow_senders,
            deny_senders=body.deny_senders,
        )
    except mb.MailboxError as exc:
        raise _http(exc) from exc


@router.delete("/mailboxes/{mailbox_id}", response_model=mb.Mailbox)
async def remove_mailbox(
    mailbox_id: str = PathParam(pattern=MAILBOX_ID),
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> mb.Mailbox:
    """Forget a linked mailbox. What it already copied stays in the books; its sign-in is cleared by the app."""
    try:
        return await mb.remove_mailbox(books, mailbox_id, user=user)
    except mb.MailboxError as exc:
        raise _http(exc) from exc


def chosen_ai(request: Request) -> AiConfig | None:
    """The AI the user picked in the app (X-AI-Mode sent), or None. Unlike /plan/day, never the server's
    fallback model: email previews go only to a backend the user chose."""
    if not request.headers.get("X-AI-Mode"):
        return None
    return optional_ai(request)


class TriageBody(StrictBody):
    since_days: int = Field(default=7, ge=1, le=30)
    max_threads: int = Field(default=20, ge=1, le=50)


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
        books,
        mail,
        cfg,
        since_days=body.since_days,
        max_threads=body.max_threads,
        user=user,
        business_name=business,
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
    await books.audit(
        f"user:{user}",
        "mail_draft_created",
        {
            "reply_to": body.message_id,
            "draft": draft.id,
            "chars": len(text),
        },
    )
    return DraftReplyResult(draft_id=draft.id, web_link=draft.web_link)
