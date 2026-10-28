"""The accountant portal: every Accnomos books folder shared with the signed-in accountant, one summary each.

Where the list comes from (no database):

1. Graph `sharedWithMe`, folders only, kept when the folder holds the Accnomos tree (a `_System` folder). That API
   is deprecated and "will stop returning data" after November 2026 (Microsoft Learn,
   https://learn.microsoft.com/graph/api/drive-sharedwithme, checked 28 Oct 2026), so:
2. client codes the accountant added by hand (from the invitation email: `drive id:item id`), kept in the
   accountant's own books, `_System/Accountant/clients.json`. A code is checked (shared with you, holds `_System`)
   before it is saved.

Each client is read through its own read-only `Books` (its own cache key, app/sharing.py), at most four at once.
A client that cannot be read shows with an error instead of failing the page.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from accnomos_connectors.base import SharedRoot, SharingProvider
from app import accountant, queries
from app.books import AUDIT, QUERIES_AUDIT, SYSTEM, Books, now
from app.deadlines import filing_deadline, period_containing, period_label, previous_period
from app.validation import StrictBody

CLIENTS = f"{SYSTEM}/Accountant/clients.json"
MARKER = "_System"  # a folder with this child is an Accnomos books folder
MAX_CLIENTS = 200
IN_FLIGHT = 4

_CODE = re.compile(r"([A-Za-z0-9!._~-]{1,256}):([A-Za-z0-9!._~-]{1,256})")


class ClientLink(BaseModel):
    drive_id: str
    item_id: str
    name: str = ""
    added_at: datetime


class AddClientIn(StrictBody):
    code: str = Field(max_length=1000)  # "drive:item", or a portal link with ?client=drive:item


class VatDeadline(BaseModel):
    period: str  # "Jul–Sep 2026"
    due: date
    days_left: int


class ClientSummary(BaseModel):
    drive_id: str
    item_id: str
    code: str
    name: str
    kind: accountant.ClientKind | None = None
    owner: str | None = None
    source: Literal["shared_with_me", "added", "both"]
    access: accountant.Role | None = None  # what the client's invitation to you says, when they recorded one
    review_waiting: int = 0  # proposals waiting for approval
    needs_a_look: int = 0
    open_queries: int = 0
    waiting_on_client: int = 0
    waiting_on_you: int = 0
    last_activity: datetime | None = None
    vat: VatDeadline | None = None
    vat_registered: bool | None = None
    error: str | None = None


class Portal(BaseModel):
    clients: list[ClientSummary]
    shared_with_me_ok: bool  # False when Graph sharedWithMe failed or returned nothing usable
    note: str | None = None


def parse_code(raw: str) -> SharedRoot:
    """'drive:item', or any link whose `client=` parameter holds one. ValueError otherwise."""
    raw = raw.strip()
    if m := re.search(r"[?&]client=([^&#\s]+)", raw):
        raw = m.group(1).replace("%3A", ":").replace("%3a", ":").replace("%21", "!")
    m = _CODE.fullmatch(raw)
    if not m:
        raise ValueError("That is not a client code. It looks like two ids joined by a colon, as in the invitation.")
    return SharedRoot(drive_id=m.group(1), item_id=m.group(2))


async def saved_links(own: Books) -> list[ClientLink]:
    raw = await own.read_json(CLIENTS, [])
    return [ClientLink.model_validate(x) for x in raw if isinstance(x, dict)] if isinstance(raw, list) else []


async def add_link(own: Books, sharing: SharingProvider, body: AddClientIn, user: str) -> ClientLink:
    root = parse_code(body.code)
    folder = await sharing.folder(root)  # FileNotFoundError: not shared with this account
    if MARKER not in await sharing.child_names(root):
        raise ValueError("That folder is shared with you but is not a set of Accnomos books.")
    link = ClientLink(drive_id=root.drive_id, item_id=root.item_id, name=folder.name, added_at=now())

    def change(raw: object) -> object:
        items = [x for x in (raw if isinstance(raw, list) else []) if isinstance(x, dict)]
        items = [x for x in items if (x.get("drive_id"), x.get("item_id")) != (root.drive_id, root.item_id)]
        if len(items) >= MAX_CLIENTS:
            raise ValueError(f"At most {MAX_CLIENTS} clients can be added by code.")
        return [*items, link.model_dump(mode="json")]

    await own._update_json(CLIENTS, [], change)
    await own.audit(f"user:{user}", "accountant_client_added", {"client": f"{root.drive_id}:{root.item_id}"})
    return link


async def remove_link(own: Books, root: SharedRoot, user: str) -> bool:
    gone: list[bool] = []

    def change(raw: object) -> object:
        items = [x for x in (raw if isinstance(raw, list) else []) if isinstance(x, dict)]
        kept = [x for x in items if (x.get("drive_id"), x.get("item_id")) != (root.drive_id, root.item_id)]
        gone[:] = [len(kept) != len(items)]
        return kept

    await own._update_json(CLIENTS, [], change)
    if gone and gone[0]:
        await own.audit(f"user:{user}", "accountant_client_removed", {"client": f"{root.drive_id}:{root.item_id}"})
    return bool(gone and gone[0])


def next_vat_deadline(profile: accountant.ClientProfile, today: date) -> VatDeadline:
    """The earliest return due on or after today: the last ended period's, else the current one's."""
    start, end = period_containing(today, profile.vat_start_month, profile.vat_months)
    prev = previous_period(start, profile.vat_months)
    for s, e in (prev, (start, end)):
        due = filing_deadline(e)
        if due >= today:
            return VatDeadline(period=period_label(s, e), due=due, days_left=(due - today).days)
    raise AssertionError("unreachable: the current period's deadline is after today")


async def _last_activity(books: Books, today: date) -> datetime | None:
    months = {f"{today.year:04d}-{today.month:02d}", f"{(today.replace(day=1) - timedelta(days=1)):%Y-%m}"}
    latest: datetime | None = None
    for folder in (AUDIT, QUERIES_AUDIT):
        for m in months:
            try:
                raw = (await books.storage.read(f"{folder}/{m}.jsonl")).decode("utf-8", "replace")
            except FileNotFoundError:
                continue
            for line in raw.splitlines()[-50:]:
                ts = re.search(r'"ts":\s*"([^"]+)"', line)
                try:
                    when = datetime.fromisoformat(ts.group(1)) if ts else None
                except ValueError:
                    continue
                if when and when.tzinfo and (latest is None or when > latest):
                    latest = when
    return latest


async def summarise(books: Books, me: str, today: date) -> dict:
    """The counts and dates for one client's books (read-only)."""
    info = await accountant.load(books)
    proposals, threads, last = await asyncio.gather(
        books.list_proposals(), queries.list_queries(books, status="open"), _last_activity(books, today)
    )
    mine = [i for i in info.invitations if i.active and i.email == me.lower()]
    profile = info.profile
    out: dict = {
        "review_waiting": sum(p.status == "proposed" for p in proposals),
        "needs_a_look": sum(p.status == "needs_a_look" for p in proposals),
        "open_queries": len(threads),
        "waiting_on_client": sum(q.waiting_on == "client" for q in threads),
        "waiting_on_you": sum(q.waiting_on == "accountant" for q in threads),
        "last_activity": last,
        "access": mine[0].role if mine else None,
    }
    if profile:
        out |= {"kind": profile.kind, "vat_registered": profile.vat_registered}
        if profile.name:
            out["name"] = profile.name
        if profile.vat_registered:
            out["vat"] = next_vat_deadline(profile, today)
    return out


async def list_clients(
    own: Books | None,
    sharing: SharingProvider,
    open_client: Callable[[SharedRoot], Awaitable[Books]],
    me: str,
    today: date,
) -> Portal:
    note = None
    try:
        shared = await sharing.shared_with_me()
        shared_ok = bool(shared)
    except Exception as exc:  # deprecated API: a failure must not hide the clients added by code
        shared, shared_ok = [], False
        note = f"Microsoft's 'shared with me' list did not answer ({type(exc).__name__}); clients added by code show."
    links = await saved_links(own) if own is not None else []
    found: dict[tuple[str, str], ClientSummary] = {}
    gate = asyncio.Semaphore(IN_FLIGHT)

    async def books_folder(drive: str, item: str) -> bool:
        async with gate:
            try:
                return MARKER in await sharing.child_names(SharedRoot(drive_id=drive, item_id=item))
            except Exception:
                return False

    checks = await asyncio.gather(*(books_folder(f.drive_id, f.item_id) for f in shared))
    for f, ok in zip(shared, checks, strict=True):
        if ok:
            found[(f.drive_id, f.item_id)] = ClientSummary(
                drive_id=f.drive_id, item_id=f.item_id, code=f"{f.drive_id}:{f.item_id}", name=f.name,
                owner=f.owner, source="shared_with_me",
            )  # fmt: skip
    for link in links:
        key = (link.drive_id, link.item_id)
        if key in found:
            found[key].source = "both"
        else:
            found[key] = ClientSummary(
                drive_id=link.drive_id, item_id=link.item_id, code=f"{link.drive_id}:{link.item_id}",
                name=link.name, source="added",
            )  # fmt: skip

    async def fill(c: ClientSummary) -> ClientSummary:
        async with gate:
            try:
                books = await open_client(SharedRoot(drive_id=c.drive_id, item_id=c.item_id))
                return c.model_copy(update=await summarise(books, me, today))
            except FileNotFoundError:
                return c.model_copy(update={"error": "No longer shared with you."})
            except Exception as exc:
                return c.model_copy(update={"error": f"Could not read these books ({type(exc).__name__})."})

    clients = list(await asyncio.gather(*(fill(c) for c in list(found.values())[:MAX_CLIENTS])))
    clients.sort(key=lambda c: (c.error is not None, c.vat.due if c.vat else date.max, c.name.casefold()))
    return Portal(clients=clients, shared_with_me_ok=shared_ok, note=note)
