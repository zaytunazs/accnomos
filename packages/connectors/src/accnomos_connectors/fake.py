"""In-memory providers used by contract tests and by the runtime's own tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from accnomos_connectors.base import (
    AddressBookContact,
    CalendarProvider,
    ConflictError,
    ContactsProvider,
    FileRef,
    MailAttachment,
    MailMessage,
    MailProvider,
    StorageProvider,
)


class FakeMailProvider(MailProvider):
    """A mailbox in memory: `add()` messages with (attachment, bytes) pairs; `calls` records every read."""

    def __init__(self) -> None:
        self.messages: list[MailMessage] = []
        self.attachments: dict[str, list[tuple[MailAttachment, bytes]]] = {}
        self.calls: list[str] = []

    def add(self, message: MailMessage, *files: tuple[MailAttachment, bytes]) -> MailMessage:
        message.has_attachments = bool(files)
        self.messages.append(message)
        self.attachments[message.id] = list(files)
        return message

    async def list_messages(self, since: datetime, max_results: int = 50) -> list[MailMessage]:
        self.calls.append("list_messages")
        hits = [m for m in self.messages if m.has_attachments and m.received_at >= since]
        return sorted(hits, key=lambda m: m.received_at, reverse=True)[:max_results]

    async def list_attachments(self, message_id: str) -> list[MailAttachment]:
        self.calls.append(f"list_attachments:{message_id}")
        if message_id not in self.attachments:
            raise FileNotFoundError(message_id)
        return [a for a, _ in self.attachments[message_id]]

    async def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        self.calls.append(f"download:{message_id}/{attachment_id}")
        for a, data in self.attachments.get(message_id, []):
            if a.id == attachment_id:
                return data
        raise FileNotFoundError(f"{message_id}/{attachment_id}")


class FakeContactsProvider(ContactsProvider):
    """An address book in memory; `calls` counts reads."""

    def __init__(self, contacts: list[AddressBookContact] | None = None) -> None:
        self.contacts = list(contacts or [])
        self.calls = 0

    async def list_contacts(self, max_results: int = 1000) -> list[AddressBookContact]:
        self.calls += 1
        return self.contacts[:max_results]


class FakeCalendarProvider(CalendarProvider):
    """Calendars in memory: `events[calendar_id][key]` = (date, title, body); upserting the same key replaces it."""

    def __init__(self) -> None:
        self.calendars: dict[str, str] = {}  # name -> id
        self.events: dict[str, dict[str, tuple[str, str, str]]] = {}

    async def ensure_calendar(self, name: str) -> str:
        if name not in self.calendars:
            self.calendars[name] = f"fake-cal:{len(self.calendars) + 1}"
            self.events[self.calendars[name]] = {}
        return self.calendars[name]

    async def upsert_all_day_event(self, calendar_id: str, key: str, date: str, title: str, body: str) -> str:
        if calendar_id not in self.events:
            raise FileNotFoundError(calendar_id)
        self.events[calendar_id][key] = (date, title, body)
        return f"{calendar_id}/{key}"


class FakeStorageProvider(StorageProvider):
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.folders: set[str] = {""}
        self._log: list[tuple[str, str]] = []

    def _ref(self, path: str, is_folder: bool = False) -> FileRef:
        data = self.files.get(path, b"")
        etag = hashlib.sha1(data).hexdigest()[:12] if not is_folder else None
        return FileRef(
            id=f"fake:{path}", path=path, name=path.rsplit("/", 1)[-1], size=len(data), etag=etag,
            modified=datetime.now(UTC), is_folder=is_folder,
        )

    async def ensure_root(self) -> FileRef:
        return self._ref("", True)

    async def ensure_folder(self, path: str) -> FileRef:
        parts = path.strip("/").split("/")
        for i in range(1, len(parts) + 1):
            self.folders.add("/".join(parts[:i]))
        return self._ref(path.strip("/"), True)

    async def list(self, path: str) -> list[FileRef]:
        prefix = path.strip("/")
        prefix = prefix + "/" if prefix else ""
        out: list[FileRef] = []
        for f in sorted(self.folders):
            if f and f.startswith(prefix) and "/" not in f[len(prefix):]:
                out.append(self._ref(f, True))
        for p in sorted(self.files):
            if p.startswith(prefix) and "/" not in p[len(prefix):]:
                out.append(self._ref(p))
        return out

    async def read(self, path: str) -> bytes:
        path = path.strip("/")
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    async def write(self, path: str, data: bytes, *, if_match: str | None = None) -> FileRef:
        path = path.strip("/")
        if if_match is not None and path in self.files and self._ref(path).etag != if_match:
            raise ConflictError(path)
        if "/" in path:
            await self.ensure_folder(path.rsplit("/", 1)[0])
        self.files[path] = data
        self._log.append(("write", path))
        return self._ref(path)

    async def move(self, path: str, new_path: str) -> FileRef:
        path, new_path = path.strip("/"), new_path.strip("/")
        if path not in self.files:
            raise FileNotFoundError(path)
        if new_path in self.files:
            raise FileExistsError(new_path)
        if "/" in new_path:
            await self.ensure_folder(new_path.rsplit("/", 1)[0])
        self.files[new_path] = self.files.pop(path)
        self._log.append(("move", f"{path} -> {new_path}"))
        return self._ref(new_path)

    async def changes(self, cursor: str | None) -> tuple[list[FileRef], str]:
        start = int(cursor or 0)
        changed = [self._ref(p.split(" -> ")[-1]) for _, p in self._log[start:] if p.split(" -> ")[-1] in self.files]
        return changed, str(len(self._log))
