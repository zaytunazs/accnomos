"""Interfaces. Paths are POSIX-style relative to the Accnomos root folder, e.g. '00 Inbox/IMG_2041.jpg'."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
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
    async def write(self, path: str, data: bytes, *, if_match: str | None = None) -> FileRef:
        """Create or replace. if_match = eTag for optimistic concurrency (412 -> ConflictError)."""

    @abstractmethod
    async def move(self, path: str, new_path: str) -> FileRef:
        """We move, never delete (PRD §4.3)."""

    @abstractmethod
    async def changes(self, cursor: str | None) -> tuple[list[FileRef], str]:
        """Delta since cursor; returns (changed items, new cursor)."""


class MailProvider(ABC):
    """Read-only access to the user's mailbox: nothing is ever moved, flagged, marked read or deleted."""

    @abstractmethod
    async def list_messages(self, since: datetime, max_results: int = 50) -> list[MailMessage]:
        """Messages with attachments received at or after `since`, newest first."""

    @abstractmethod
    async def list_attachments(self, message_id: str) -> list[MailAttachment]:
        """File attachments of one message (metadata only)."""

    @abstractmethod
    async def download_attachment(self, message_id: str, attachment_id: str) -> bytes: ...

    async def create_draft(self, to: str, subject: str, body_html: str) -> str:
        """Returns the draft id. Sending is a separate, user-tapped action. Not implemented yet."""
        raise NotImplementedError


class CalendarProvider(ABC):
    @abstractmethod
    async def ensure_calendar(self, name: str) -> str: ...

    @abstractmethod
    async def upsert_all_day_event(self, calendar_id: str, key: str, date: str, title: str, body: str) -> str: ...


class ConflictError(Exception):
    """Raised when an if_match precondition fails (someone else changed the file)."""


class TokenSource(Protocol):
    """How a provider gets the user's access token. The runtime passes it per request; nothing is stored."""

    async def access_token(self) -> str: ...
