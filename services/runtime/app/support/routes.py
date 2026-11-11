"""Support: the help articles, the support assistant, and tickets (supabase/migrations/0002_support.sql).

Public
    GET  /support/articles                      the help centre's articles (id, title, summary, category, url)
    GET  /support/articles/{id}                 one article with its steps
Signed in (X-Graph-Token, X-User; or a demo session for the assistant only)
    POST /support/assist                        {question, page?, app?, version?} -> answer from the articles, cited;
                                                a `create_support_ticket` card when it can't solve it (not in a demo)
    POST /support/assist/voice                  the same, spoken (speech-to-text chain, as /books/ask/voice)
    GET  /support/paypal                        PayPal help panel: connection, last sync, open disputes, last problem
    POST /support/tickets                       the New ticket form
    POST /support/tickets/from-card             {action, ...consent}: the assistant's card, after Create ticket
    GET  /support/tickets                       my tickets
    GET  /support/tickets/{id}                  one of mine, with its thread (internal notes never)
    POST /support/tickets/{id}/messages         {body}: my reply (a solved ticket opens again)
Admins (ADMIN_EMAILS, as app/billing/admin.py; every write in admin_audit)
    GET   /admin/support/tickets?status=&q=&page=
    GET   /admin/support/tickets/{id}           with the full thread, notes included, and the account
    POST  /admin/support/tickets/{id}/messages  {body, internal?, email_user?}
    PATCH /admin/support/tickets/{id}           {status}

What a ticket holds (`context`) is only what the user ticked: recent errors the app saw (method, path, status, a short
message, amounts masked), PayPal's connection status, last sync and last problem, and, only with "include financial
details", the assistant conversation as the app showed it. Nothing is read from the books for a ticket otherwise.

Email: there is no system mail sender on this server. An admin's reply is emailed to the user only from the admin's
own mailbox (the same Graph/Gmail sender invoices use, with the admin's sign-in), when the admin leaves "email the
user" ticked; otherwise, or if that fails, the reply is in the app only and the response says so.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from app import actions, demo
from app.ai.config import AiConfig, ai_config_from_request, is_test_mode
from app.billing import registry as R
from app.billing.admin import Admin
from app.billing.registry import Row
from app.billing.routes import Account
from app.routes_actions import graph_token
from app.schemas import ProposedAction
from app.support import help as H
from app.support.store import CATEGORIES, STATUSES, SupportStore, support_store
from app.validation import StrictBody

log = logging.getLogger("accnomos.support")
router = APIRouter(prefix="/support", tags=["support"])
admin_router = APIRouter(prefix="/admin/support", tags=["admin"])
PER_PAGE = 25
Category = Literal["how_to", "bug", "account", "billing", "paypal", "hmrc_vat", "bank", "storage", "mobile", "other"]
AppName = Literal["web", "android", "ios"]

PAYPAL_LINKS = [
    {"label": "PayPal Resolution Centre", "url": "https://www.paypal.com/disputes/"},
    {"label": "PayPal Business help", "url": "https://www.paypal.com/uk/cshelp/business"},
    {"label": "PayPal system status", "url": "https://www.paypal-status.com/"},
    {"label": "PayPal developer technical support", "url": "https://www.paypal-support.com/"},
]


def store_or_503() -> SupportStore:
    s = support_store()
    if s is None:
        raise HTTPException(503, "Support tickets are not set up on this server")
    return s


# --------------------------------------------------------------------------- #
# Articles
# --------------------------------------------------------------------------- #


class ArticleOut(BaseModel):
    id: str
    title: str
    summary: str
    category: str
    url: str
    path: str


class StepOut(BaseModel):
    title: str
    body: str
    image: str | None = None
    alt: str | None = None


class ArticleFull(ArticleOut):
    platforms: list[str]
    steps: list[StepOut]
    troubleshooting: list[dict[str, str]]
    related: list[str]


def _out(a: H.Article) -> ArticleOut:
    return ArticleOut(id=a.id, title=a.title, summary=a.summary, category=a.category, url=a.url, path=a.path)


@router.get("/articles", response_model=list[ArticleOut])
async def list_articles() -> list[ArticleOut]:
    return [_out(a) for a in H.articles()]


@router.get("/articles/{article_id}", response_model=ArticleFull)
async def get_article(article_id: str) -> ArticleFull:
    a = H.get(article_id)
    if a is None:
        raise HTTPException(404, "No such article")
    return ArticleFull(
        **_out(a).model_dump(),
        platforms=list(a.platforms),
        steps=[StepOut(title=s.title, body=s.body, image=s.image, alt=s.alt) for s in a.steps],
        troubleshooting=[{"problem": p, "fix": f} for p, f in a.troubleshooting],
        related=list(a.related),
    )


# --------------------------------------------------------------------------- #
# The support assistant
# --------------------------------------------------------------------------- #


class AssistIn(StrictBody):
    question: str = Field(min_length=1, max_length=500)
    page: str | None = Field(default=None, max_length=300)
    app: AppName = "web"
    version: str | None = Field(default=None, max_length=40)
    ticket: bool = False  # the user pressed "Create a ticket instead": always offer the card


class Citation(BaseModel):
    id: str
    title: str
    path: str
    url: str


class AssistOut(BaseModel):
    answer_md: str
    citations: list[Citation]
    ticket_card: ProposedAction | None = None
    ticket_note: str | None = None  # why there is no card when one was wanted (a demo, support off)
    transcript: str | None = None


_AMOUNT = re.compile(r"(£|\$|€)\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*\.\d{2}\b")


def mask_amounts(text: str) -> str:
    """No figures leave in a ticket unless the user ticked "include financial details": "£1,234.50" -> "£•••"."""
    return _AMOUNT.sub(lambda m: (m.group(1) or "") + "•••", text)


def _subject(question: str) -> str:
    q = " ".join(question.split())
    return (q[:117] + "…") if len(q) > 120 else q


def ticket_draft(question: str, found: H.HelpAnswer, page: str | None, app: str, version: str | None,
                 source: str) -> actions.Draft:  # fmt: skip
    category = H.category_for(question, found.article)
    tried = [found.article.title] if found.article else []
    preview: dict[str, Any] = {
        "subject": _subject(mask_amounts(question)),
        "category": category,
        "description": mask_amounts(question.strip()),
        "steps": [f"Asked the support assistant: {mask_amounts(question.strip())}"]
        + [f"Read the help article: {t}" for t in tried],
        "article_id": found.article.id if found.article else None,
        "page": page,
        "app": app,
        "version": version,
        "source": source,
        "warnings": [],
    }
    label = dict(TICKET_CATEGORIES).get(category, category)
    summary = (
        "I can raise a support ticket for you. Check it, choose what to attach, then press **Create ticket**.\n\n"
        f"**{preview['subject']}** · {label}"
    )
    return actions.Draft("create_support_ticket", summary, preview, "Create this support ticket")


TICKET_CATEGORIES: list[tuple[str, str]] = [
    ("how_to", "How do I…"),
    ("bug", "Something is broken"),
    ("account", "Account and sign-in"),
    ("billing", "Plan and billing"),
    ("paypal", "PayPal"),
    ("hmrc_vat", "VAT and HMRC"),
    ("bank", "Bank"),
    ("storage", "OneDrive or Google Drive"),
    ("mobile", "Android app"),
    ("other", "Something else"),
]


async def assist_answer(
    question: str, request: Request, page: str | None, app: str, version: str | None, source: str, force: bool = False
) -> AssistOut:
    found = H.answer(question)
    cites = [found.article, *found.others[:2]] if found.article else found.others[:2]
    out = AssistOut(
        answer_md=found.answer_md,
        citations=[Citation(id=a.id, title=a.title, path=a.path, url=a.url) for a in cites if a is not None],
    )
    if not (found.offer_ticket or force):
        return out
    if demo.is_demo_request(request):
        out.ticket_note = "Support tickets need a sign-in: the demo can't raise one."
        return out
    if support_store() is None:
        out.ticket_note = "Support tickets are not set up on this server."
        return out
    out.ticket_card = actions.new_action(
        ticket_draft(question, found, page, app, version, source), graph_token(request)
    )
    return out


@router.post("/assist", response_model=AssistOut)
async def assist(body: AssistIn, request: Request, _token: str = Depends(graph_token)) -> AssistOut:
    """Answers from the help articles only (code quotes the article; no model writes steps). Signed in or a demo."""
    return await assist_answer(body.question, request, body.page, body.app, body.version, "assistant", body.ticket)


@router.post("/assist/voice", response_model=AssistOut)
async def assist_voice(
    request: Request,
    audio: UploadFile = File(...),
    page: str | None = Form(default=None, max_length=300),
    version: str | None = Form(default=None, max_length=40),
    cfg: AiConfig = Depends(ai_config_from_request),
    _token: str = Depends(graph_token),
) -> AssistOut:
    """A spoken support question: the same speech-to-text chain as /books/ask/voice, then /support/assist."""
    from app.ai import stt, voice
    from app.routes_ask import _no_voice

    providers = stt.chain(cfg)
    if not providers:
        raise HTTPException(400, _no_voice(cfg))
    try:
        voice.require_ffmpeg()
        data = await audio.read(voice.MAX_UPLOAD_BYTES + 1)
        heard = await stt.transcribe(await voice.to_wav(data, audio.content_type, audio.filename), providers)
    except voice.VoiceError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    text = heard.text.strip()[:500]
    if not text:
        raise HTTPException(422, "Nothing was heard. Try again, or type the question.")
    out = await assist_answer(text, request, page, "web", version, "voice")
    out.transcript = text
    return out


# --------------------------------------------------------------------------- #
# PayPal help (context for tickets and the Support page's panel)
# --------------------------------------------------------------------------- #


class PayPalHelp(BaseModel):
    available: bool  # books could be read (signed in with storage, or a demo)
    connected: bool = False
    test_mode: bool | None = None
    account: str | None = None  # masked merchant id
    connected_at: datetime | None = None
    last_synced_at: datetime | None = None
    open_disputes: list[dict[str, Any]] = []
    problem: str | None = None  # the last problem our PayPal calls hit, in a sentence
    links: list[dict[str, str]] = PAYPAL_LINKS
    no_case_api: str = (
        "PayPal has no API for an app to open a PayPal support case for you: PayPal-only problems go to PayPal's "
        "Resolution Centre or Business help. Problems in Accnomos come to us as a ticket."
    )


def _mask(value: str | None) -> str | None:
    if not value:
        return None
    return value if len(value) <= 4 else "•" * 4 + value[-4:]


async def paypal_help_for(request: Request, with_disputes: bool = True) -> PayPalHelp:
    """Best effort, read only: never fails the caller. Each part that can't be read is left empty."""
    from app import online_payments as op
    from app import paypal_disputes as pd
    from app import paypal_sync as ps
    from app.routes_books import get_books

    gen: Any = get_books(request)  # an async generator dependency, driven by hand here
    try:
        books = await gen.__anext__()
    except Exception as exc:  # noqa: BLE001 - no books (not signed in, storage not connected): say so
        log.info("support: no books for the PayPal panel (%s)", type(exc).__name__)
        return PayPalHelp(available=False)
    out = PayPalHelp(available=True)
    try:
        status = next((s for s in await op.status(books) if s.provider == "paypal"), None)
        if status is not None:
            out.connected, out.test_mode = status.connected, status.test_mode
            out.account, out.connected_at = _mask(status.account), status.connected_at
            if not status.available:
                out.problem = status.reason
        out.last_synced_at = (await ps.load_state(books)).last_synced_at
        if with_disputes and (out.connected or demo.is_demo_request(request)):
            got = await asyncio.wait_for(pd.list_disputes(books, sample=demo.is_demo_request(request)), 20)
            out.problem = got.problem or out.problem
            out.open_disputes = [
                {
                    "dispute_id": d.dispute_id,
                    "reason": d.reason_text,
                    "status": d.status,
                    "respond_by": d.respond_by.isoformat() if d.respond_by else None,
                    "invoice": d.invoice,
                    "sample": d.sample,
                    "can_send_evidence": d.can_send_evidence,
                }
                for d in got.disputes
                if d.status not in ("RESOLVED",)
            ][:10]
    except TimeoutError:
        out.problem = "PayPal took too long to answer about disputes."
    except Exception as exc:  # noqa: BLE001 - the panel shows what it could read, and why not the rest
        out.problem = out.problem or f"Could not read the PayPal details ({type(exc).__name__})."
    finally:
        await gen.aclose()
    return out


@router.get("/paypal", response_model=PayPalHelp)
async def paypal_help(request: Request, _token: str = Depends(graph_token)) -> PayPalHelp:
    return await paypal_help_for(request)


# --------------------------------------------------------------------------- #
# Tickets: the user
# --------------------------------------------------------------------------- #


class ClientError(StrictBody):
    at: str | None = Field(default=None, max_length=40)
    method: str | None = Field(default=None, max_length=10)
    path: str | None = Field(default=None, max_length=200)
    status: int | None = Field(default=None, ge=0, le=999)
    message: str | None = Field(default=None, max_length=300)


class Turn(StrictBody):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=2000)


class Consent(StrictBody):
    attach_errors: bool = False
    recent_errors: list[ClientError] = Field(default_factory=list, max_length=10)
    include_paypal: bool = False
    include_financial: bool = False
    conversation: list[Turn] = Field(default_factory=list, max_length=8)  # only kept with include_financial


class TicketIn(Consent):
    subject: str = Field(min_length=3, max_length=200)
    category: Category = "other"
    body: str = Field(min_length=3, max_length=10_000)
    page: str | None = Field(default=None, max_length=300)
    app: AppName = "web"
    version: str | None = Field(default=None, max_length=40)


class FromCardIn(Consent):
    action: ProposedAction
    details: str | None = Field(default=None, max_length=5000)  # more words the user added on the card


class Message(BaseModel):
    id: str
    at: datetime
    author: Literal["user", "admin"]
    body: str
    internal: bool = False
    emailed: bool = False
    author_email: str | None = None


class Ticket(BaseModel):
    id: str
    number: int
    subject: str
    category: str
    status: str
    source: str
    page: str | None = None
    app: str | None = None
    version: str | None = None
    created_at: datetime
    updated_at: datetime
    last_reply_by: str | None = None
    solved_at: datetime | None = None
    context: dict[str, Any] = {}
    email: str | None = None
    account_id: str | None = None


class TicketThread(Ticket):
    messages: list[Message]


class TicketPage(BaseModel):
    items: list[Ticket]
    page: int
    per_page: int
    total: int


class Created(BaseModel):
    ticket: Ticket
    created: bool  # False: this card had already made the ticket


def _ticket(row: Row, admin: bool = False) -> Ticket:
    t = Ticket.model_validate({**row, "id": str(row["id"]), "account_id": str(row.get("account_id") or "") or None})
    if not admin:
        t.account_id = None
    return t


def _message(row: Row, admin: bool) -> Message:
    m = Message.model_validate({**row, "id": str(row["id"])})
    if not admin:
        m.author_email = None  # the user sees "Accnomos support", not which admin
    return m


async def build_context(
    request: Request, c: Consent, page: str | None, app: str, version: str | None
) -> dict[str, Any]:
    ctx: dict[str, Any] = {"page": page, "app": app, "version": version, "consent": {
        "errors": c.attach_errors, "paypal": c.include_paypal, "financial": c.include_financial}}  # fmt: skip
    if c.attach_errors:
        ctx["recent_errors"] = [
            {**e.model_dump(), "message": mask_amounts(e.message or "") or None} for e in c.recent_errors[:10]
        ]
    if c.include_paypal:
        ctx["paypal"] = (await paypal_help_for(request)).model_dump(mode="json", exclude={"links", "no_case_api"})
        if not c.include_financial:
            for d in ctx["paypal"].get("open_disputes", []):
                d.pop("invoice", None)
    if c.include_financial and c.conversation:
        ctx["conversation"] = [t.model_dump() for t in c.conversation[-8:]]
    return ctx


async def _create(
    s: SupportStore, acc: Row, *, subject: str, category: str, body: str, source: str, ctx: dict[str, Any],
    page: str | None, app: str, version: str | None, action_id: str | None = None,
) -> tuple[Row, bool]:  # fmt: skip
    row: Row = {
        "account_id": acc["id"],
        "email": acc.get("email"),
        "subject": subject.strip()[:200],
        "category": category if category in CATEGORIES else "other",
        "source": source,
        "page": (page or "")[:300] or None,
        "app": app,
        "version": version,
        "context": ctx,
        "last_reply_by": "user",
    }
    if action_id:
        row["action_id"] = action_id
    first = {"author": "user", "author_email": acc.get("email"), "body": body.strip()[:10_000]}
    return await s.create_ticket(row, first)


@router.post("/tickets", response_model=Created, status_code=201)
async def create_ticket(body: TicketIn, request: Request, acc: Account) -> Created:
    s = store_or_503()
    ctx = await build_context(request, body, body.page, body.app, body.version)
    text = body.body if body.include_financial else mask_amounts(body.body)
    row, made = await _create(
        s, acc, subject=mask_amounts(body.subject) if not body.include_financial else body.subject,
        category=body.category, body=text, source="form", ctx=ctx, page=body.page, app=body.app, version=body.version,
    )  # fmt: skip
    return Created(ticket=_ticket(row), created=made)


async def create_from_card(
    action: ProposedAction, request: Request, acc: Row, consent: Consent, details: str | None = None
) -> tuple[Row, bool]:
    """The card is checked exactly like /actions/approve checks one (signature over what the user saw, expiry); the
    card's id is the ticket's `action_id`, so approving it twice makes one ticket."""
    if action.kind != "create_support_ticket":
        raise actions.ActionError("That is not a support ticket card.", 400)
    actions.verify(action, graph_token(request))
    p = action.preview
    ctx = await build_context(request, consent, p.get("page"), str(p.get("app") or "web"), p.get("version"))
    lines = [str(p.get("description") or "")]
    if details and details.strip():
        lines += ["", details.strip() if consent.include_financial else mask_amounts(details.strip())]
    steps = [str(x) for x in p.get("steps") or []]
    if steps:
        lines += ["", "What happened so far:", *[f"- {x}" for x in steps]]
    return await _create(
        store_or_503(), acc, subject=str(p.get("subject") or "Support request"), category=str(p.get("category")),
        body="\n".join(lines), source=str(p.get("source") or "assistant") if p.get("source") in ("assistant", "voice")
        else "assistant", ctx=ctx, page=p.get("page"), app=str(p.get("app") or "web"), version=p.get("version"),
        action_id=action.id,
    )  # fmt: skip


@router.post("/tickets/from-card", response_model=Created, status_code=201)
async def ticket_from_card(body: FromCardIn, request: Request, acc: Account) -> Created:
    try:
        row, made = await create_from_card(body.action, request, acc, body, body.details)
    except actions.ActionError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return Created(ticket=_ticket(row), created=made)


@router.get("/tickets", response_model=TicketPage)
async def my_tickets(
    acc: Account,
    status: Literal["open", "pending", "solved"] | None = None,
    page: int = Query(default=1, ge=1, le=10_000),
) -> TicketPage:
    rows, total = await store_or_503().list_tickets(acc["id"], status, None, page, PER_PAGE)
    return TicketPage(items=[_ticket(r) for r in rows], page=page, per_page=PER_PAGE, total=total)


async def _mine(s: SupportStore, ticket_id: str, acc: Row) -> Row:
    row = await s.get_ticket(ticket_id)
    if row is None or str(row.get("account_id")) != str(acc["id"]):
        raise HTTPException(404, "No such ticket")  # someone else's ticket is "not found", never "forbidden"
    return row


@router.get("/tickets/{ticket_id}", response_model=TicketThread)
async def my_ticket(ticket_id: str, acc: Account) -> TicketThread:
    s = store_or_503()
    row = await _mine(s, ticket_id, acc)
    msgs = await s.messages(str(row["id"]), include_internal=False)
    return TicketThread(**_ticket(row).model_dump(), messages=[_message(m, False) for m in msgs])


class ReplyIn(StrictBody):
    body: str = Field(min_length=1, max_length=10_000)


@router.post("/tickets/{ticket_id}/messages", response_model=TicketThread, status_code=201)
async def reply(ticket_id: str, body: ReplyIn, acc: Account) -> TicketThread:
    s = store_or_503()
    row = await _mine(s, ticket_id, acc)
    await s.add_message({"ticket_id": str(row["id"]), "author": "user", "author_email": acc.get("email"),
                         "body": body.body.strip()})  # fmt: skip
    patch: Row = {"updated_at": datetime.now(UTC), "last_reply_by": "user", "status": "open", "solved_at": None}
    row = await s.update_ticket(str(row["id"]), patch) or row
    msgs = await s.messages(str(row["id"]), include_internal=False)
    return TicketThread(**_ticket(row).model_dump(), messages=[_message(m, False) for m in msgs])


# --------------------------------------------------------------------------- #
# Tickets: admins
# --------------------------------------------------------------------------- #


class AdminTicketPage(TicketPage):
    counts: dict[str, int]


@admin_router.get("/tickets", response_model=AdminTicketPage)
async def admin_tickets(
    _: Admin,
    status: Literal["open", "pending", "solved"] | None = None,
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1, le=10_000),
) -> AdminTicketPage:
    s = store_or_503()
    rows, total = await s.list_tickets(None, status, q, page, PER_PAGE)
    counts = {st: (await s.list_tickets(None, st, None, 1, 1))[1] for st in STATUSES}
    return AdminTicketPage(
        items=[_ticket(r, admin=True) for r in rows], page=page, per_page=PER_PAGE, total=total, counts=counts
    )


async def _any(s: SupportStore, ticket_id: str) -> Row:
    row = await s.get_ticket(ticket_id)
    if row is None:
        raise HTTPException(404, "No such ticket")
    return row


@admin_router.get("/tickets/{ticket_id}", response_model=TicketThread)
async def admin_ticket(ticket_id: str, _: Admin) -> TicketThread:
    s = store_or_503()
    row = await _any(s, ticket_id)
    msgs = await s.messages(str(row["id"]), include_internal=True)
    return TicketThread(**_ticket(row, admin=True).model_dump(), messages=[_message(m, True) for m in msgs])


class AdminReplyIn(StrictBody):
    body: str = Field(min_length=1, max_length=10_000)
    internal: bool = False  # a note for admins only: never shown to the user, never emailed
    email_user: bool = True  # also email the reply, from the admin's own mailbox


class AdminReplyOut(TicketThread):
    emailed: bool
    email_note: str | None = None  # why it was not emailed, in a sentence


def _reply_mail(ticket: Row, text: str) -> tuple[str, str]:
    subject = f"Re: [Accnomos support #{ticket['number']}] {ticket['subject']}"[:250]
    body = (
        f"{text.strip()}\n\n"
        "Reply in the app: https://accnomos.com/support (replies to this email may not reach the support queue).\n"
        f"Ticket {ticket['number']}"
    )
    return subject, body


async def email_reply(request: Request, to: str, ticket: Row, text: str) -> str | None:
    """Send from the admin's own mailbox; None when sent, else why not."""
    from accnomos_connectors.base import OutgoingMail

    subject, body = _reply_mail(ticket, text)
    try:
        if is_test_mode():
            from app import testmode

            sender: Any = testmode.current().sender
        else:
            from app import accounts

            sender = accounts.mail_sender(graph_token(request), request)
        try:
            await sender.send(OutgoingMail(to=to, subject=subject, body_text=body))
        finally:
            if hasattr(sender, "aclose"):
                await sender.aclose()
    except Exception as exc:  # noqa: BLE001 - the reply stands in the app either way; say why it was not emailed
        log.info("support: reply not emailed (%s)", type(exc).__name__)
        return f"The reply is in the app, but the email could not be sent from your mailbox ({type(exc).__name__})."
    return None


@admin_router.post("/tickets/{ticket_id}/messages", response_model=AdminReplyOut, status_code=201)
async def admin_reply(ticket_id: str, body: AdminReplyIn, request: Request, admin: Admin) -> AdminReplyOut:
    s = store_or_503()
    row = await _any(s, ticket_id)
    note: str | None = None
    emailed = False
    if not body.internal and body.email_user:
        if row.get("email"):
            note = await email_reply(request, str(row["email"]), row, body.body)
            emailed = note is None
        else:
            note = "The account has no email address: the reply is in the app only."
    elif not body.internal:
        note = "Not emailed (you unticked it): the user sees the reply on their Support page."
    message: Row = {"ticket_id": str(row["id"]), "author": "admin", "author_email": admin}
    await s.add_message({**message, "body": body.body.strip(), "internal": body.internal, "emailed": emailed})
    patch: Row = {"updated_at": datetime.now(UTC)}
    if not body.internal:
        patch.update(last_reply_by="admin")
        if row.get("status") == "open":
            patch["status"] = "pending"  # waiting for the user
    row = await s.update_ticket(str(row["id"]), patch) or row
    reg = R.registry()
    if reg is not None:
        await reg.add_audit(admin, row.get("account_id"), "support_note" if body.internal else "support_reply",
                            {"ticket": str(row["id"]), "number": row.get("number"), "emailed": emailed})  # fmt: skip
    msgs = await s.messages(str(row["id"]), include_internal=True)
    return AdminReplyOut(
        **_ticket(row, admin=True).model_dump(),
        messages=[_message(m, True) for m in msgs],
        emailed=emailed,
        email_note=note,
    )


class StatusIn(StrictBody):
    status: Literal["open", "pending", "solved"]


@admin_router.patch("/tickets/{ticket_id}", response_model=Ticket)
async def admin_status(ticket_id: str, body: StatusIn, admin: Admin) -> Ticket:
    s = store_or_503()
    row = await _any(s, ticket_id)
    now = datetime.now(UTC)
    patch: Row = {"status": body.status, "updated_at": now, "solved_at": now if body.status == "solved" else None}
    updated = await s.update_ticket(str(row["id"]), patch) or row
    reg = R.registry()
    if reg is not None:
        await reg.add_audit(admin, row.get("account_id"), "support_status",
                            {"ticket": str(row["id"]), "before": row.get("status"), "after": body.status})  # fmt: skip
    return _ticket(updated, admin=True)
