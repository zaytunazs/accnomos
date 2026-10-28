"""Mailboxes Outlook intake reads: the signed-in account's own, more Microsoft accounts, and shared mailboxes.

The list lives in the user's books at `_System/mail/mailboxes.json`. It holds addresses, settings and the last
check's time and count, **never a token**: the web app keeps each account in its own MSAL cache and sends that
mailbox's token with each `POST /mail/scan` (`X-Mailbox-Token`), so the runtime still keeps nothing.

    {"mailboxes": [{"id", "address", "kind", "folder", "allow_senders", "deny_senders", "added_at", "added_by",
                    "last_scan_at", "last_scan_saved", "last_scan_error"}]}

Kinds:
  primary    the signed-in account's own mailbox (`/me`, token in X-Graph-Token). Never stored unless its folder or
             filters were changed; always listed.
  microsoft  another Outlook.com / Microsoft 365 account the user signed in to separately (`/me` with its own
             `Mail.Read` token).
  shared     a shared or delegated mailbox the signed-in work account can open (`/users/{address}` with the
             signed-in account's `Mail.Read.Shared` token).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.books import SYSTEM, Books, now

MAILBOXES = f"{SYSTEM}/mail/mailboxes.json"
PRIMARY_ID = "primary"
MAX_MAILBOXES = 10
MAX_FILTERS = 50

Kind = Literal["primary", "microsoft", "shared"]

ADDRESS = re.compile(r"^[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
# A sender filter: a whole address, or a domain ('screwfix.com', '@screwfix.com'), which also covers its subdomains.
SENDER = re.compile(r"^([A-Za-z0-9._%+'-]{1,64})?@?[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
# "all", "inbox", "archive", or a top-level folder's display name (no path separators or control characters).
FOLDER = re.compile(r"^[^/\\\x00-\x1f]{1,100}$")


class MailboxError(ValueError):
    """A bad request about mailboxes (the route answers 400/404/409 with the message)."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class Mailbox(BaseModel):
    id: str
    address: str
    kind: Kind
    folder: str = "all"
    allow_senders: list[str] = Field(default_factory=list)
    deny_senders: list[str] = Field(default_factory=list)
    added_at: datetime | None = None
    added_by: str | None = None
    last_scan_at: datetime | None = None
    last_scan_saved: int | None = None
    last_scan_error: str | None = None


def normalise_address(address: str) -> str:
    address = address.strip().lower()
    if not ADDRESS.match(address):
        raise MailboxError(f"Not an email address: {address[:80]!r}")
    return address


def normalise_folder(folder: str) -> str:
    folder = folder.strip()
    if not FOLDER.match(folder):
        raise MailboxError("A folder name is 1–100 characters, without / or \\")
    return folder.lower() if folder.lower() in ("all", "inbox", "archive") else folder


def normalise_senders(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        v = raw.strip().lower()
        if not v:
            continue
        if not SENDER.match(v):
            raise MailboxError(f"Not an address or domain: {v[:80]!r}")
        v = v.removeprefix("@")
        if v not in out:
            out.append(v)
    if len(out) > MAX_FILTERS:
        raise MailboxError(f"At most {MAX_FILTERS} senders per list")
    return out


def _matches(address: str, rule: str) -> bool:
    if "@" in rule:
        return address == rule
    domain = address.rsplit("@", 1)[-1]
    return domain == rule or domain.endswith(f".{rule}")


def sender_allowed(address: str, allow: list[str], deny: list[str]) -> bool:
    """Deny wins; a non-empty allow list keeps only the senders on it."""
    address = address.strip().lower()
    if any(_matches(address, r) for r in deny):
        return False
    return not allow or any(_matches(address, r) for r in allow)


def primary_mailbox(user: str | None) -> Mailbox:
    return Mailbox(id=PRIMARY_ID, address=(user or "").strip().lower(), kind="primary")


async def _stored(books: Books) -> list[Mailbox]:
    raw: Any = await books.read_json(MAILBOXES, {"mailboxes": []})
    out: list[Mailbox] = []
    for item in raw.get("mailboxes", []) if isinstance(raw, dict) else []:
        try:
            out.append(Mailbox.model_validate(item))
        except ValidationError:
            continue  # a hand-edited entry that no longer parses is ignored, not fatal
    return out


async def list_mailboxes(books: Books, user: str | None) -> list[Mailbox]:
    """The signed-in mailbox first (stored settings if any), then the linked ones in the order they were added."""
    stored = await _stored(books)
    primary = next((m for m in stored if m.id == PRIMARY_ID), None)
    if primary is None:
        primary = primary_mailbox(user)
    elif user:
        primary.address = user.strip().lower()
    return [primary, *(m for m in stored if m.id != PRIMARY_ID)]


async def get_mailbox(books: Books, mailbox_id: str, user: str | None) -> Mailbox:
    for m in await list_mailboxes(books, user):
        if m.id == mailbox_id:
            return m
    raise MailboxError("No such mailbox", 404)


def _dump(boxes: list[Mailbox]) -> dict[str, Any]:
    return {"mailboxes": [m.model_dump(mode="json") for m in boxes]}


async def _change(books: Books, change: Any) -> None:
    """Read-modify-write under the books' ETag check (`_update_json`)."""

    def apply(old: Any) -> dict[str, Any]:
        boxes: list[Mailbox] = []
        for item in old.get("mailboxes", []) if isinstance(old, dict) else []:
            try:
                boxes.append(Mailbox.model_validate(item))
            except ValidationError:
                continue
        return _dump(change(boxes))

    await books._update_json(MAILBOXES, {"mailboxes": []}, apply)


async def add_mailbox(
    books: Books,
    *,
    address: str,
    kind: Kind,
    user: str,
    folder: str = "all",
    allow_senders: list[str] | None = None,
    deny_senders: list[str] | None = None,
) -> Mailbox:
    if kind == "primary":
        raise MailboxError("The signed-in mailbox is always there")
    address = normalise_address(address)
    if address == user.strip().lower():
        raise MailboxError("That is the mailbox you are signed in with; it is already read", 409)
    box = Mailbox(
        id=uuid.uuid4().hex[:12],
        address=address,
        kind=kind,
        folder=normalise_folder(folder),
        allow_senders=normalise_senders(allow_senders or []),
        deny_senders=normalise_senders(deny_senders or []),
        added_at=now(),
        added_by=user.strip().lower(),
    )

    def change(boxes: list[Mailbox]) -> list[Mailbox]:
        if any(b.address == address and b.id != PRIMARY_ID for b in boxes):
            raise MailboxError(f"{address} is already linked", 409)
        if len([b for b in boxes if b.id != PRIMARY_ID]) >= MAX_MAILBOXES:
            raise MailboxError(f"At most {MAX_MAILBOXES} extra mailboxes")
        return [*boxes, box]

    await _change(books, change)
    await books.audit(f"user:{user}", "mailbox_added", {"mailbox": box.id, "address": address, "kind": kind})
    return box


async def update_mailbox(
    books: Books,
    mailbox_id: str,
    *,
    user: str,
    folder: str | None = None,
    allow_senders: list[str] | None = None,
    deny_senders: list[str] | None = None,
) -> Mailbox:
    fields: dict[str, Any] = {}
    if folder is not None:
        fields["folder"] = normalise_folder(folder)
    if allow_senders is not None:
        fields["allow_senders"] = normalise_senders(allow_senders)
    if deny_senders is not None:
        fields["deny_senders"] = normalise_senders(deny_senders)
    result: list[Mailbox] = []

    def change(boxes: list[Mailbox]) -> list[Mailbox]:
        if mailbox_id == PRIMARY_ID and not any(b.id == PRIMARY_ID for b in boxes):
            boxes = [primary_mailbox(user), *boxes]
        for i, b in enumerate(boxes):
            if b.id == mailbox_id:
                boxes[i] = b.model_copy(update=fields)
                result.append(boxes[i])
                return boxes
        raise MailboxError("No such mailbox", 404)

    await _change(books, change)
    box = result[-1]  # change() may run twice when the file changed underneath
    await books.audit(
        f"user:{user}",
        "mailbox_updated",
        {"mailbox": box.id, "address": box.address, "fields": sorted(fields)},
    )
    return box


async def remove_mailbox(books: Books, mailbox_id: str, *, user: str) -> Mailbox:
    if mailbox_id == PRIMARY_ID:
        raise MailboxError("The signed-in mailbox cannot be removed; turn Outlook intake off instead")
    removed: list[Mailbox] = []

    def change(boxes: list[Mailbox]) -> list[Mailbox]:
        keep = [b for b in boxes if b.id != mailbox_id]
        if len(keep) == len(boxes):
            raise MailboxError("No such mailbox", 404)
        removed.extend(b for b in boxes if b.id == mailbox_id)
        return keep

    await _change(books, change)
    box = removed[-1]
    await books.audit(f"user:{user}", "mailbox_removed", {"mailbox": box.id, "address": box.address})
    return box


async def record_scan(books: Books, box: Mailbox, saved: int, error: str | None) -> None:
    """The last check's time and count (no token, no mail content). The primary mailbox is stored only once the
    file exists, so a user with one mailbox gets no new file."""
    at = now()

    def change(boxes: list[Mailbox]) -> list[Mailbox]:
        if box.id == PRIMARY_ID and not any(b.id == PRIMARY_ID for b in boxes):
            boxes = [box, *boxes]
        for i, b in enumerate(boxes):
            if b.id == box.id:
                boxes[i] = b.model_copy(update={"last_scan_at": at, "last_scan_saved": saved, "last_scan_error": error})
        return boxes

    if box.id == PRIMARY_ID and not await books.exists(MAILBOXES):
        return
    await _change(books, change)
