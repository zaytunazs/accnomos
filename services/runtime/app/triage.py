"""Inbox triage: the last few days of business mail, one line each, a suggested reply and the to-dos in it.

Code first. The Inbox is listed with Graph's ≤255-character `bodyPreview` only (never a full body);
newsletters, no-reply senders and threads only from the user's own domain are dropped; the rest is grouped
by conversation. Then one strict-JSON model call per thread (app/ai/triage.py) classifies it, summarises it,
suggests a reply and lists to-dos, and code checks every answer. Without an AI, or when the model fails,
the thread is still listed with a summary written by code.

Nothing in the mailbox is changed here, and nothing is kept: the only write is one audit line (counts only).
Replies become Outlook drafts only when the user taps *Draft in Outlook* (POST /mail/draft-reply).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from accnomos_connectors.base import MailMessage, MailProvider
from app.ai.config import AiConfig
from app.books import Books, now
from app.intake import BULK_SENDER, domain_of, is_from_self

ACTOR = "agent:triage"
PREVIEW_MAX = 255
MESSAGES_PER_THREAD = 5  # the newest few previews are enough to say what a thread wants
MESSAGES_PER_THREAD_CAP = 8  # messages kept per thread (message_count, unread); the model sees MESSAGES_PER_THREAD
MODEL_CONCURRENCY = 4
SUBJECT_MAX = 200

Category = Literal["customer", "supplier", "hmrc", "accountant", "other"]
SkipReason = Literal["no_reply", "newsletter", "own_domain"]

# Automated senders, by the part before the @. 'info@' and 'hello@' are real people at small firms, so they stay.
NO_REPLY = re.compile(
    r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer[-_.]?daemon|postmaster|bounces?|notifications?|alerts?)([-_.+].*)?$"
)
BULK_TEXT = re.compile(
    r"unsubscribe|view (this email )?in (your )?browser|manage (your )?(email )?preferences|% off\b|webinar",
    re.IGNORECASE,
)
# Government senders write from no-reply addresses but matter (HMRC, Companies House): never dropped for that.
GOV_DOMAIN = re.compile(r"(^|\.)gov\.uk$")


class TriageTodo(BaseModel):
    text: str
    due: date | None = None


class TriageThread(BaseModel):
    conversation_id: str
    message_id: str  # the newest message from someone else: what *Draft in Outlook* replies to
    subject: str
    from_name: str
    from_address: str
    received_at: datetime
    unread: bool
    message_count: int
    web_link: str | None
    category: Category
    summary: str
    needs_reply: bool
    suggested_reply: str | None
    todos: list[TriageTodo]
    fallback_reason: str | None = None  # the model's answer was not used (or there is no AI); words are from code


class TriageResult(BaseModel):
    since_days: int
    scanned: int
    skipped: dict[str, int]
    threads: list[TriageThread]
    model: str | None = None
    generated_at: datetime


class Thread(BaseModel):
    """Messages of one conversation that survived the filters, newest first."""

    conversation_id: str
    messages: list[MailMessage]

    @property
    def latest(self) -> MailMessage:
        return self.messages[0]

    def reply_target(self, user: str | None) -> MailMessage:
        return next((m for m in self.messages if not is_from_self(m, user)), self.latest)


# ---------------------------------------------------------------------- #
# Filtering and grouping (pure, tested directly)
# ---------------------------------------------------------------------- #


def is_gov(address: str) -> bool:
    return bool(GOV_DOMAIN.search(domain_of(address)))


def is_no_reply(address: str) -> bool:
    return bool(NO_REPLY.match(address.rsplit("@", 1)[0].lower())) if "@" in address else False


def skip_reason(m: MailMessage) -> SkipReason | None:
    """Why this message is not business correspondence worth triaging, or None to keep it."""
    if is_gov(m.from_address):
        return None
    local = m.from_address.rsplit("@", 1)[0].lower() if "@" in m.from_address else ""
    if BULK_SENDER.match(local) or BULK_TEXT.search(m.body_preview) or BULK_TEXT.search(m.subject):
        return "newsletter"
    if not m.from_address or is_no_reply(m.from_address):
        return "no_reply"
    return None


def group_threads(
    messages: Iterable[MailMessage],
    user: str | None,
    max_threads: int,
) -> tuple[list[Thread], dict[str, int]]:
    """Kept threads (newest activity first, at most `max_threads`) and how many messages each filter dropped."""
    skipped: dict[str, int] = {"no_reply": 0, "newsletter": 0, "own_domain": 0}
    by_conv: dict[str, list[MailMessage]] = {}
    for m in messages:
        reason = skip_reason(m)
        if reason:
            skipped[reason] += 1
            continue
        by_conv.setdefault(m.conversation_id or m.id, []).append(m)
    threads: list[Thread] = []
    for conv, msgs in by_conv.items():
        if all(is_from_self(m, user) for m in msgs):  # the user, or colleagues on their own domain
            skipped["own_domain"] += len(msgs)
            continue
        msgs.sort(key=lambda m: m.received_at, reverse=True)
        threads.append(Thread(conversation_id=conv, messages=msgs[:MESSAGES_PER_THREAD_CAP]))
    threads.sort(key=lambda t: t.latest.received_at, reverse=True)
    return threads[:max_threads], skipped


def can_reply(target: MailMessage) -> bool:
    """A no-reply sender (HMRC included) cannot be answered by email."""
    return bool(target.from_address) and not is_no_reply(target.from_address)


def code_category(target: MailMessage) -> Category:
    return (
        "hmrc"
        if domain_of(target.from_address).endswith("hmrc.gov.uk") or "hmrc" in target.from_name.lower()
        else "other"
    )


def one_line(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def code_summary(thread: Thread, user: str | None) -> str:
    target = thread.reply_target(user)
    who = target.from_name or target.from_address
    what = one_line(target.subject, 80) or one_line(target.body_preview, 80) or "(no subject)"
    return f"{who}: {what}"


def _thread(thread: Thread, user: str | None) -> TriageThread:
    """The thread with a code-written summary and no suggestions; the model's answer (if any) replaces them."""
    target = thread.reply_target(user)
    return TriageThread(
        conversation_id=thread.conversation_id,
        message_id=target.id,
        subject=one_line(target.subject, SUBJECT_MAX),
        from_name=target.from_name,
        from_address=target.from_address,
        received_at=thread.latest.received_at,
        unread=any(not m.is_read for m in thread.messages),
        message_count=len(thread.messages),
        web_link=thread.latest.web_link,
        category=code_category(target),
        summary=code_summary(thread, user),
        needs_reply=False,
        suggested_reply=None,
        todos=[],
    )


# ---------------------------------------------------------------------- #
# The triage
# ---------------------------------------------------------------------- #


async def triage_mail(
    books: Books | None,
    mail: MailProvider,
    cfg: AiConfig | None,
    *,
    since_days: int = 7,
    max_threads: int = 20,
    user: str | None = None,
    business_name: str | None = None,
    today: date | None = None,
) -> TriageResult:
    from app.ai import triage as triage_ai  # the model half; imported here so the pure helpers stay light

    started = now()
    today = today or started.date()
    messages = await mail.list_recent(started - timedelta(days=since_days), min(250, max(100, max_threads * 8)))
    threads, skipped = group_threads(messages, user, max_threads)

    gate = asyncio.Semaphore(MODEL_CONCURRENCY)

    async def one(t: Thread) -> TriageThread:
        base = _thread(t, user)
        if cfg is None:
            return base.model_copy(
                update={"fallback_reason": "No AI is set up, so the summary is just the sender and subject."}
            )
        async with gate:
            return await triage_ai.triage_thread(t, base, cfg, user=user, business_name=business_name, today=today)

    out = list(await asyncio.gather(*(one(t) for t in threads)))
    result = TriageResult(
        since_days=since_days,
        scanned=len(messages),
        skipped=skipped,
        threads=out,
        model=cfg.model if cfg else None,
        generated_at=started,
    )
    if books is not None:
        await books.audit(
            f"user:{user}" if user else ACTOR,
            "mail_triaged",
            {
                "since_days": since_days,
                "scanned": result.scanned,
                "threads": len(out),
                "skipped": skipped,
                "model_failures": sum(1 for t in out if t.fallback_reason),
                "model": result.model,
            },
        )
    return result
