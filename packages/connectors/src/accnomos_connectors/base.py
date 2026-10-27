"""Interfaces. Paths are POSIX-style relative to the Accnomos root folder, e.g. '00 Inbox/IMG_2041.jpg'."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Protocol

from pydantic import BaseModel


class FileRef(BaseModel):
    id: str
    path: str
    name: str
    size: int = 0
    etag: str | None = None
    modified: datetime | None = None
    is_folder: bool = False
    web_url: str | None = None


class MailMessage(BaseModel):
    id: str
    received_at: datetime
    from_address: str = ""
    from_name: str = ""
    subject: str = ""
    has_attachments: bool = False
    web_link: str | None = None
    conversation_id: str = ""  # set by list_recent (inbox triage)
    body_preview: str = ""  # Graph's first ~255 characters of the body; set by list_recent, never the full body
    is_read: bool = True


class MailDraft(BaseModel):
    """A reply saved in the user's Drafts folder. Nothing is sent: the user opens `web_link` and sends it."""

    id: str
    web_link: str | None = None


class MailAttachment(BaseModel):
    """A file attached to a message. Item and reference attachments are never listed."""

    id: str
    name: str
    content_type: str = ""
    size: int = 0
    is_inline: bool = False


class StorageProvider(ABC):
    """Folder tree, files and change tracking in the user's own cloud storage."""

    @abstractmethod
    async def ensure_root(self) -> FileRef: ...

    @abstractmethod
    async def ensure_folder(self, path: str) -> FileRef: ...

    @abstractmethod
    async def list(self, path: str) -> list[FileRef]: ...

    @abstractmethod
    async def read(self, path: str) -> bytes: ...

    @abstractmethod
    async def write(self, path: str, data: bytes, *, if_match: str | None = None, create_only: bool = False) -> FileRef:
        """Create or replace. if_match = eTag for optimistic concurrency (412 -> ConflictError);
        create_only = fail with FileExistsError when the file is already there (two writers racing to create it)."""

    @abstractmethod
    async def move(self, path: str, new_path: str) -> FileRef:
        """A file, or a folder with everything in it (FileExistsError if new_path exists). We move, never delete
        (PRD §4.3)."""

    @abstractmethod
    async def changes(self, cursor: str | None) -> tuple[list[FileRef], str]:
        """Delta since cursor; returns (changed items, new cursor)."""


class MailProvider(ABC):
    """Access to the user's mailbox: nothing is ever moved, flagged, marked read, deleted or sent.

    The one write is `create_reply_draft`, which only saves a draft (needs `Mail.ReadWrite`)."""

    @abstractmethod
    async def list_messages(self, since: datetime, max_results: int = 50) -> list[MailMessage]:
        """Messages with attachments received at or after `since`, newest first."""

    @abstractmethod
    async def list_attachments(self, message_id: str) -> list[MailAttachment]:
        """File attachments of one message (metadata only)."""

    @abstractmethod
    async def download_attachment(self, message_id: str, attachment_id: str) -> bytes: ...

    async def list_recent(self, since: datetime, max_results: int = 100) -> list[MailMessage]:
        """Inbox messages (with or without attachments) received at or after `since`, newest first,
        with `conversation_id`, `body_preview` and `is_read` filled in."""
        raise NotImplementedError

    async def create_reply_draft(self, message_id: str, body_text: str) -> MailDraft:
        """Save a reply to `message_id` in Drafts, `body_text` above the quoted thread. Never sends."""
        raise NotImplementedError

    async def create_draft(self, to: str, subject: str, body_html: str) -> str:
        """Returns the draft id. Sending is a separate, user-tapped action. Not implemented yet."""
        raise NotImplementedError


class AddressBookContact(BaseModel):
    """One entry from the user's address book, as read (nothing is ever written back)."""

    id: str
    display_name: str = ""
    company_name: str = ""
    emails: list[str] = []
    business_phones: list[str] = []


class ContactsProvider(ABC):
    """Read-only access to the user's address book."""

    @abstractmethod
    async def list_contacts(self, max_results: int = 1000) -> list[AddressBookContact]: ...


class OutgoingAttachment(BaseModel):
    name: str
    content_type: str
    data: bytes


class OutgoingMail(BaseModel):
    to: str
    subject: str
    body_text: str
    attachments: list[OutgoingAttachment] = []


class MailSender(ABC):
    """Sends one email as the signed-in user (`Mail.Send`). Kept apart from MailProvider, which only reads.

    Callers send only after the user has seen the message and confirmed it; nothing is sent on a schedule.
    """

    @abstractmethod
    async def send(self, mail: OutgoingMail) -> None: ...


class CalendarEvent(BaseModel):
    """One event on the user's calendar, as read. Times are timezone-aware."""

    id: str
    subject: str = ""
    start: datetime
    end: datetime
    location: str = ""
    body_preview: str = ""
    is_all_day: bool = False
    show_as: str = "busy"  # free | tentative | busy | oof | workingElsewhere | unknown


class CalendarProvider(ABC):
    """The user's default calendar: read a day, and create events (only after the user approves them)."""

    @abstractmethod
    async def list_events(self, day: date, tz: str = "Europe/London") -> list[CalendarEvent]:
        """Every non-cancelled event overlapping `day` (midnight to midnight in `tz`), earliest first."""

    @abstractmethod
    async def create_event(self, subject: str, start: datetime, end: datetime, location: str, body: str) -> str:
        """Create one event; returns its id. `start`/`end` must be timezone-aware."""

    async def ensure_calendar(self, name: str) -> str:
        raise NotImplementedError

    async def upsert_all_day_event(self, calendar_id: str, key: str, date: str, title: str, body: str) -> str:
        raise NotImplementedError


class ConflictError(Exception):
    """Raised when an if_match precondition fails (someone else changed the file)."""


class TokenSource(Protocol):
    """How a provider gets the user's access token. The runtime passes it per request; nothing is stored."""

    async def access_token(self) -> str: ...
