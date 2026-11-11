"""Support tickets and their messages, kept in the account registry (supabase/migrations/0002_support.sql).

Same two back ends as app/billing/registry.py: Supabase over PostgREST with the service-role key, or an in-memory
store for the unit tests and test mode (`ACCNOMOS_TEST_MODE=1`), which hangs off the in-memory registry so a test that
installs a fresh registry also gets fresh tickets. `support_store()` is None when billing (the registry) is off.
"""

from __future__ import annotations

import copy
import itertools
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from app.billing import registry as R
from app.billing.registry import MemoryRegistry, RegistryError, Row, SupabaseRegistry, _parse_row

STATUSES = ("open", "pending", "solved")
CATEGORIES = ("how_to", "bug", "account", "billing", "paypal", "hmrc_vat", "bank", "storage", "mobile", "other")
FIRST_NUMBER = 1001


def _now() -> datetime:
    return datetime.now(UTC)


def _ticket_row(row: Row) -> Row:
    out = _parse_row(row)
    for k in ("updated_at", "solved_at"):
        out[k] = R.parse_dt(out.get(k))
    return out


class SupportStore(ABC):
    @abstractmethod
    async def create_ticket(self, row: Row, first_message: Row) -> tuple[Row, bool]:
        """Insert the ticket and its first message. When `row["action_id"]` is set and a ticket already came from that
        assistant card, return that one and False (a card makes one ticket however often it is approved)."""

    @abstractmethod
    async def get_ticket(self, ticket_id: str) -> Row | None: ...
    @abstractmethod
    async def list_tickets(
        self, account_id: str | None, status: str | None, q: str | None, page: int, per_page: int
    ) -> tuple[list[Row], int]: ...
    @abstractmethod
    async def update_ticket(self, ticket_id: str, patch: Row) -> Row | None: ...
    @abstractmethod
    async def add_message(self, row: Row) -> Row: ...
    @abstractmethod
    async def messages(self, ticket_id: str, include_internal: bool) -> list[Row]: ...


class MemorySupportStore(SupportStore):
    def __init__(self, reg: MemoryRegistry) -> None:
        self.reg = reg
        self.tickets: dict[str, Row] = {}
        self.msgs: list[Row] = []
        self._numbers = itertools.count(FIRST_NUMBER)

    async def create_ticket(self, row: Row, first_message: Row) -> tuple[Row, bool]:
        if row.get("action_id"):
            found = next((t for t in self.tickets.values() if t.get("action_id") == row["action_id"]), None)
            if found is not None:
                return copy.deepcopy(found), False
        at = _now()
        tid = str(uuid.uuid4())
        rec: Row = {
            "id": tid,
            "number": next(self._numbers),
            "status": "open",
            "source": "form",
            "page": None,
            "app": None,
            "version": None,
            "context": {},
            "action_id": None,
            "created_at": at,
            "updated_at": at,
            "last_reply_by": "user",
            "solved_at": None,
            **copy.deepcopy(row),
        }
        self.tickets[tid] = rec
        await self.add_message({**first_message, "ticket_id": tid})
        return copy.deepcopy(rec), True

    async def get_ticket(self, ticket_id: str) -> Row | None:
        t = self.tickets.get(ticket_id)
        return copy.deepcopy(t) if t else None

    async def list_tickets(
        self, account_id: str | None, status: str | None, q: str | None, page: int, per_page: int
    ) -> tuple[list[Row], int]:
        rows = sorted(self.tickets.values(), key=lambda t: t["updated_at"], reverse=True)
        if account_id:
            rows = [t for t in rows if t["account_id"] == account_id]
        if status:
            rows = [t for t in rows if t["status"] == status]
        if q:
            n = q.lower()
            rows = [t for t in rows if n in t["subject"].lower() or n in (t.get("email") or "").lower()]
        start = (page - 1) * per_page
        return copy.deepcopy(rows[start : start + per_page]), len(rows)

    async def update_ticket(self, ticket_id: str, patch: Row) -> Row | None:
        t = self.tickets.get(ticket_id)
        if t is None:
            return None
        t.update(copy.deepcopy(patch))
        return copy.deepcopy(t)

    async def add_message(self, row: Row) -> Row:
        rec = {"id": str(uuid.uuid4()), "at": _now(), "internal": False, "emailed": False, **copy.deepcopy(row)}
        self.msgs.append(rec)
        return copy.deepcopy(rec)

    async def messages(self, ticket_id: str, include_internal: bool) -> list[Row]:
        return copy.deepcopy(
            [m for m in self.msgs if m["ticket_id"] == ticket_id and (include_internal or not m["internal"])]
        )


class SupabaseSupportStore(SupportStore):
    """Reuses the registry's PostgREST helpers (same URL, key, schema and errors)."""

    def __init__(self, reg: SupabaseRegistry) -> None:
        self.reg = reg

    @staticmethod
    def _uuid(value: str) -> bool:
        try:
            uuid.UUID(value)
        except ValueError:
            return False
        return True

    async def create_ticket(self, row: Row, first_message: Row) -> tuple[Row, bool]:
        if row.get("action_id"):
            found = await self.reg._one("support_tickets", [("action_id", f"eq.{row['action_id']}")])  # noqa: SLF001
            if found is not None:
                return _ticket_row(found), False
        try:
            rec = (await self.reg._insert("support_tickets", row))[0]  # noqa: SLF001
        except RegistryError as exc:
            if exc.status == 409 and row.get("action_id"):  # two approvals at once: the other one made it
                found = await self.reg._one("support_tickets", [("action_id", f"eq.{row['action_id']}")])  # noqa: SLF001
                if found is not None:
                    return _ticket_row(found), False
            raise
        await self.add_message({**first_message, "ticket_id": rec["id"]})
        return _ticket_row(rec), True

    async def get_ticket(self, ticket_id: str) -> Row | None:
        if not self._uuid(ticket_id):
            return None
        found = await self.reg._one("support_tickets", [("id", f"eq.{ticket_id}")])  # noqa: SLF001
        return _ticket_row(found) if found else None

    async def list_tickets(
        self, account_id: str | None, status: str | None, q: str | None, page: int, per_page: int
    ) -> tuple[list[Row], int]:
        params: list[tuple[str, str]] = [("order", "updated_at.desc")]
        if account_id:
            params.append(("account_id", f"eq.{account_id}"))
        if status:
            params.append(("status", f"eq.{status}"))
        if q and (needle := R._SEARCH_SAFE.sub("", q).strip()):  # noqa: SLF001
            params.append(("or", f"(subject.ilike.*{needle}*,email.ilike.*{needle}*)"))
        rows, total = await self.reg._page("support_tickets", params, page, per_page)  # noqa: SLF001
        return [_ticket_row(r) for r in rows], total

    async def update_ticket(self, ticket_id: str, patch: Row) -> Row | None:
        if not self._uuid(ticket_id):
            return None
        found = await self.reg._patch("support_tickets", [("id", f"eq.{ticket_id}")], patch)  # noqa: SLF001
        return _ticket_row(found) if found else None

    async def add_message(self, row: Row) -> Row:
        return (await self.reg._insert("support_messages", row))[0]  # noqa: SLF001

    async def messages(self, ticket_id: str, include_internal: bool) -> list[Row]:
        params = [("ticket_id", f"eq.{ticket_id}"), ("order", "at.asc")]
        if not include_internal:
            params.append(("internal", "eq.false"))
        return await self.reg._rows("support_messages", params)  # noqa: SLF001


def support_store() -> SupportStore | None:
    reg = R.registry()
    if reg is None:
        return None
    if isinstance(reg, MemoryRegistry):
        store: Any = getattr(reg, "_support_store", None)
        if store is None:
            store = MemorySupportStore(reg)
            reg._support_store = store  # type: ignore[attr-defined]  # noqa: SLF001
        return store
    if isinstance(reg, SupabaseRegistry):
        return SupabaseSupportStore(reg)
    return None
