"""In-memory providers used by contract tests and by the runtime's own tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from accnomos_connectors.base import (
    AddressBookContact,
    CalendarEvent,
    CalendarProvider,
    ConflictError,
    ContactsProvider,
    FileRef,
    Identity,
    MailAttachment,
    MailDraft,
    MailMessage,
    MailProvider,
    MailSender,
    OutgoingMail,
    SharedFolder,
    SharedRoot,
    SharePermission,
    ShareRole,
    SharingProvider,
    StorageProvider,
)


class FakeMailProvider(MailProvider):
    """A mailbox in memory: `add()` messages with (attachment, bytes) pairs; `calls` records every read."""

    def __init__(self) -> None:
        self.messages: list[MailMessage] = []
        self.attachments: dict[str, list[tuple[MailAttachment, bytes]]] = {}
        self.bodies: dict[str, str] = {}  # message id -> plain-text body
        self.calls: list[str] = []
        self.drafts: list[dict[str, str]] = []  # {"id", "reply_to", "body"} per create_reply_draft
        self.folders: dict[str, str] = {}  # message id -> folder ("inbox" unless `add` says otherwise)

    def add(
        self, message: MailMessage, *files: tuple[MailAttachment, bytes], body: str = "", folder: str = "inbox"
    ) -> MailMessage:
        message.has_attachments = bool(files)
        self.messages.append(message)
        self.folders[message.id] = folder
        self.attachments[message.id] = list(files)
        self.bodies[message.id] = body
        return message

    def _in(self, m: MailMessage, folder: str | None, default: str | None) -> bool:
        want = default if folder in (None, "all") else folder
        return want is None or self.folders.get(m.id, "inbox").lower() == want.lower()

    async def list_without_attachments(
        self, since: datetime, max_results: int = 50, *, folder: str | None = None
    ) -> list[MailMessage]:
        self.calls.append("list_without_attachments" + (f":{folder}" if folder else ""))
        hits = [
            m for m in self.messages if not m.has_attachments and m.received_at >= since and self._in(m, folder, None)
        ]
        return sorted(hits, key=lambda m: m.received_at, reverse=True)[:max_results]

    async def message_text(self, message_id: str) -> str:
        self.calls.append(f"message_text:{message_id}")
        if message_id not in self.bodies:
            raise FileNotFoundError(message_id)
        return self.bodies[message_id]

    async def list_recent(self, since: datetime, max_results: int = 100) -> list[MailMessage]:
        self.calls.append("list_recent")
        hits = [m for m in self.messages if m.received_at >= since]
        return sorted(hits, key=lambda m: m.received_at, reverse=True)[:max_results]

    async def create_reply_draft(self, message_id: str, body_text: str) -> MailDraft:
        self.calls.append(f"create_reply_draft:{message_id}")
        if not any(m.id == message_id for m in self.messages):
            raise FileNotFoundError(message_id)
        draft_id = f"draft-{len(self.drafts) + 1}"
        self.drafts.append({"id": draft_id, "reply_to": message_id, "body": body_text})
        return MailDraft(id=draft_id, web_link=f"https://outlook.office.com/mail/drafts/id/{draft_id}")

    async def list_messages(
        self, since: datetime, max_results: int = 50, *, folder: str | None = None
    ) -> list[MailMessage]:
        self.calls.append("list_messages" + (f":{folder}" if folder else ""))
        hits = [m for m in self.messages if m.has_attachments and m.received_at >= since and self._in(m, folder, None)]
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


class FakeMailSender(MailSender):
    """Records every message instead of sending it; set `fail` to make the next send raise."""

    def __init__(self) -> None:
        self.sent: list[OutgoingMail] = []
        self.fail: Exception | None = None

    async def send(self, mail: OutgoingMail) -> None:
        if self.fail:
            raise self.fail
        self.sent.append(mail)


class FakeCalendarProvider(CalendarProvider):
    """A calendar in memory. Day planner side: seed `events`; `created` lists what `create_event` added (also appended
    to `events`). Deadline side: `calendars[name] -> id` and `all_day[calendar_id][key] = (date, title, body)`;
    upserting the same key replaces it."""

    def __init__(self, events: list[CalendarEvent] | None = None) -> None:
        self.events = list(events or [])
        self.created: list[CalendarEvent] = []
        self.calls: list[str] = []
        self.calendars: dict[str, str] = {}  # name -> id
        self.all_day: dict[str, dict[str, tuple[str, str, str]]] = {}

    async def list_events(self, day: date, tz: str = "Europe/London") -> list[CalendarEvent]:
        self.calls.append(f"list_events:{day.isoformat()}")
        zone = ZoneInfo(tz)
        start, end = datetime.combine(day, time(0), zone), datetime.combine(day + timedelta(days=1), time(0), zone)
        return sorted((e for e in self.events if e.start < end and e.end > start), key=lambda e: e.start)

    async def create_event(self, subject: str, start: datetime, end: datetime, location: str, body: str) -> str:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        self.calls.append(f"create_event:{subject}")
        event = CalendarEvent(
            id=f"fake-event-{len(self.created) + 1}",
            subject=subject,
            start=start,
            end=end,
            location=location,
            body_preview=body[:255],
        )
        self.created.append(event)
        self.events.append(event)
        return event.id

    async def ensure_calendar(self, name: str) -> str:
        if name not in self.calendars:
            self.calendars[name] = f"fake-cal:{len(self.calendars) + 1}"
            self.all_day[self.calendars[name]] = {}
        return self.calendars[name]

    async def upsert_all_day_event(self, calendar_id: str, key: str, date: str, title: str, body: str) -> str:
        if calendar_id not in self.all_day:
            raise FileNotFoundError(calendar_id)
        self.all_day[calendar_id][key] = (date, title, body)
        return f"{calendar_id}/{key}"


class FakeStorageProvider(StorageProvider):
    def __init__(self, web_base: str | None = None) -> None:
        self.files: dict[str, bytes] = {}
        self.folders: set[str] = {""}
        self._log: list[tuple[str, str]] = []
        self.web_base = web_base  # set: each FileRef gets web_url = f"{web_base}/{path}" (test mode's look-alike)

    def _ref(self, path: str, is_folder: bool = False) -> FileRef:
        data = self.files.get(path, b"")
        etag = hashlib.sha1(data).hexdigest()[:12] if not is_folder else None
        return FileRef(
            id=f"fake:{path}",
            path=path,
            name=path.rsplit("/", 1)[-1],
            size=len(data),
            etag=etag,
            modified=datetime.now(UTC),
            is_folder=is_folder,
            content_hash=None if is_folder else f"sha256:{hashlib.sha256(data).hexdigest()}",
            web_url=f"{self.web_base}/{path}" if self.web_base else None,
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
            if f and f.startswith(prefix) and "/" not in f[len(prefix) :]:
                out.append(self._ref(f, True))
        for p in sorted(self.files):
            if p.startswith(prefix) and "/" not in p[len(prefix) :]:
                out.append(self._ref(p))
        return out

    async def read(self, path: str) -> bytes:
        path = path.strip("/")
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    async def write(self, path: str, data: bytes, *, if_match: str | None = None, create_only: bool = False) -> FileRef:
        path = path.strip("/")
        if if_match is not None and path in self.files and self._ref(path).etag != if_match:
            raise ConflictError(path)
        if create_only and path in self.files:
            raise FileExistsError(path)
        if "/" in path:
            await self.ensure_folder(path.rsplit("/", 1)[0])
        self.files[path] = data
        self._log.append(("write", path))
        return self._ref(path)

    async def move(self, path: str, new_path: str) -> FileRef:
        path, new_path = path.strip("/"), new_path.strip("/")
        if path and path in self.folders:
            return await self._move_folder(path, new_path)
        if path not in self.files:
            raise FileNotFoundError(path)
        if new_path in self.files:
            raise FileExistsError(new_path)
        if "/" in new_path:
            await self.ensure_folder(new_path.rsplit("/", 1)[0])
        self.files[new_path] = self.files.pop(path)
        self._log.append(("move", f"{path} -> {new_path}"))
        return self._ref(new_path)

    async def _move_folder(self, path: str, new_path: str) -> FileRef:
        """Rename a folder with everything inside it, as one Graph PATCH would. The target must not exist."""
        if new_path in self.folders or new_path in self.files:
            raise FileExistsError(new_path)
        if new_path == path or new_path.startswith(f"{path}/"):
            raise ValueError(f"cannot move {path} into itself")

        def rebase(p: str) -> str:
            return new_path + p[len(path) :] if p == path or p.startswith(f"{path}/") else p

        self.folders = {rebase(f) for f in self.folders}
        self.files = {rebase(p): data for p, data in self.files.items()}
        await self.ensure_folder(new_path)  # its parents
        self._log.append(("move", f"{path} -> {new_path}"))
        return self._ref(new_path, True)

    async def changes(self, cursor: str | None) -> tuple[list[FileRef], str]:
        start = int(cursor or 0)
        changed = [self._ref(p.split(" -> ")[-1]) for _, p in self._log[start:] if p.split(" -> ")[-1] in self.files]
        return changed, str(len(self._log))


class FakeSharingWorld:
    """Several people's OneDrives in memory, with the permissions invitations made on them.

    Shapes follow Graph: an invitation makes a permission with an id and roles `read` or `write`; revoking deletes
    it; `sharedWithMe` lists the folders someone gave the caller a permission on."""

    def __init__(self) -> None:
        self.folders: dict[tuple[str, str], tuple[str, str, FakeStorageProvider]] = {}  # root -> owner, name, storage
        # root -> permission id -> (email, role, path inside the root; "" is the whole folder)
        self.permissions: dict[tuple[str, str], dict[str, tuple[str, ShareRole, str]]] = {}
        self.calls: list[tuple[str, str]] = []  # (who, what) for tests
        self.shared_with_me_works = True  # False: the deprecated API "stops returning data" (an empty list)
        self._n = 0

    def add_folder(
        self, owner: str, drive_id: str, item_id: str, name: str, storage: FakeStorageProvider
    ) -> SharedRoot:
        self.folders[(drive_id, item_id)] = (owner.lower(), name, storage)
        return SharedRoot(drive_id=drive_id, item_id=item_id)

    def role_of(self, root: SharedRoot, email: str, path: str = "") -> ShareRole | None:
        """`write` for the owner, else the best role a permission on `path` or a folder above it gives (permissions
        are inherited downwards, as in OneDrive), else None (no access)."""
        key = (root.drive_id, root.item_id)
        if key not in self.folders:
            return None
        if self.folders[key][0] == email.lower():
            return "write"
        path = path.strip("/")
        roles = [
            r
            for e, r, p in self.permissions.get(key, {}).values()
            if e == email.lower() and (not p or path == p or path.startswith(f"{p}/"))
        ]
        return "write" if "write" in roles else ("read" if roles else None)

    def storage_for(self, root: SharedRoot, email: str) -> tuple[FakeStorageProvider, ShareRole]:
        role = self.role_of(root, email)
        if role is None:
            raise FileNotFoundError(f"{root.drive_id}/{root.item_id}")  # Graph answers 404 for no access
        return self.folders[(root.drive_id, root.item_id)][2], role


class FakeSharingProvider(SharingProvider):
    """One signed-in person's view of a FakeSharingWorld."""

    def __init__(self, world: FakeSharingWorld, me: Identity, own: SharedRoot | None = None) -> None:
        self.world, self.me, self.own = world, me, own
        self.fail_invite: Exception | None = None  # set to make the next invite fail (e.g. a Graph 403)

    def _log(self, what: str) -> None:
        self.world.calls.append((self.me.email, what))

    async def books_root(self, account_kind: str) -> SharedRoot:
        self._log(f"books_root {account_kind}")
        if self.own is None:
            raise FileNotFoundError("Accnomos")
        return self.own

    def _owned(self, root: SharedRoot) -> tuple[str, str]:
        key = (root.drive_id, root.item_id)
        if key not in self.world.folders or self.world.folders[key][0] != self.me.email.lower():
            raise PermissionError("only the owner can share or unshare this folder")
        return key

    async def invite(
        self, root: SharedRoot, email: str, role: ShareRole, message: str, path: str = ""
    ) -> SharePermission:
        self._log(f"invite {email} {role} {path}".rstrip())
        if self.fail_invite is not None:
            exc, self.fail_invite = self.fail_invite, None
            raise exc
        key = self._owned(root)
        self.world._n += 1
        perm_id = f"perm-{self.world._n}"
        self.world.permissions.setdefault(key, {})[perm_id] = (email.lower(), role, path.strip("/"))
        return SharePermission(id=perm_id, roles=[role], email=email.lower())

    async def revoke(self, root: SharedRoot, permission_id: str, path: str = "") -> bool:
        self._log(f"revoke {permission_id}")
        key = self._owned(root)
        perm = self.world.permissions.get(key, {}).get(permission_id)
        if perm is None or perm[2] != path.strip("/"):
            return False
        del self.world.permissions[key][permission_id]
        return True

    async def shared_with_me(self) -> list[SharedFolder]:
        self._log("sharedWithMe")
        if not self.world.shared_with_me_works:
            return []
        out = []
        for (drive, item), (owner, name, _storage) in self.world.folders.items():
            root = SharedRoot(drive_id=drive, item_id=item)
            if owner != self.me.email.lower() and self.world.role_of(root, self.me.email):
                out.append(SharedFolder(drive_id=drive, item_id=item, name=name, owner=owner))
        return out

    async def folder(self, root: SharedRoot) -> SharedFolder:
        if self.world.role_of(root, self.me.email) is None:
            raise FileNotFoundError(root.item_id)
        owner, name, _ = self.world.folders[(root.drive_id, root.item_id)]
        return SharedFolder(drive_id=root.drive_id, item_id=root.item_id, name=name, owner=owner)

    async def child_names(self, root: SharedRoot) -> set[str]:
        storage, _ = self.world.storage_for(root, self.me.email)
        return {f.name for f in await storage.list("")}

    async def whoami(self) -> Identity:
        return self.me
