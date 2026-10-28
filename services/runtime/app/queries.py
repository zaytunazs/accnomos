"""Client queries: an accountant asks about a transaction or a document; the client answers in the same thread.

One JSON file per thread, `_System/queries/<id>.json`, in the client's books (both sides write there: a view-only
accountant has write access to this folder alone, see app/accountant.py). One file per thread keeps two people
writing at once apart; a reply is a read-modify-write with If-Match (`Books._update_json`).

Who is who comes from the request: in a client's books opened through sharing (`books.accountant` is set, from
Graph /me) the writer is the accountant; otherwise it is the client. An open query whose last message is the
accountant's is *waiting on the client* and shows on their to-do list (web Home, Android to-dos).
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, computed_field, field_validator

from app.books import QUERIES, Books, now
from app.validation import StrictBody

QUERY_ID = re.compile(r"[0-9a-f]{12}")
MAX_MESSAGES = 200
MAX_QUERIES = 2000

QueryRole = Literal["accountant", "client"]
SubjectKind = Literal["transaction", "document", "proposal", "bank_line", "invoice", "general"]


class QueryError(ValueError):
    """The thread cannot take this change."""


class QuerySubject(StrictBody):
    """What the query is about: a ledger event id, a document path, a proposal id, a bank line, an invoice number."""

    kind: SubjectKind = "general"
    ref: str = Field(default="", max_length=300)
    label: str = Field(default="", max_length=200)  # how the page showed it: "Novex Office Supplies, £51.90"

    @field_validator("ref", "label")
    @classmethod
    def _one_line(cls, v: str) -> str:
        return " ".join(v.split())


class QueryMessage(BaseModel):
    ts: datetime
    author: str
    role: QueryRole
    text: str


class Query(BaseModel):
    id: str
    subject: QuerySubject
    status: Literal["open", "resolved"] = "open"
    created_at: datetime
    created_by: str
    messages: list[QueryMessage]
    resolved_at: datetime | None = None
    resolved_by: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def waiting_on(self) -> QueryRole | None:
        """Who should answer next: the other side from the last message; nobody once resolved."""
        if self.status != "open" or not self.messages:
            return None
        return "client" if self.messages[-1].role == "accountant" else "accountant"


class QueryIn(StrictBody):
    subject: QuerySubject = Field(default_factory=QuerySubject)
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def _text(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text is empty")
        return v.strip()


class ReplyIn(StrictBody):
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def _text(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text is empty")
        return v.strip()


def who(books: Books, user: str) -> tuple[str, QueryRole]:
    """(author, role) for this request: the verified accountant in shared books, else the signed-in client."""
    return (books.accountant, "accountant") if books.accountant else (user, "client")


def _path(query_id: str) -> str:
    if not QUERY_ID.fullmatch(query_id):
        raise KeyError(query_id)  # never a path built from anything else
    return f"{QUERIES}/{query_id}.json"


async def list_queries(books: Books, status: str | None = None, waiting_on: str | None = None) -> list[Query]:
    """Newest activity first. A file that is not a query is skipped, never fatal."""
    files = [
        f for f in await books.list_files(QUERIES) if f.name.endswith(".json") and QUERY_ID.fullmatch(f.name[:-5])
    ][:MAX_QUERIES]
    out: list[Query] = []
    for raw in await asyncio.gather(*(books.read_json(f.path, None) for f in files)):
        try:
            q = Query.model_validate(raw)
        except ValidationError:
            continue
        if (status is None or q.status == status) and (waiting_on is None or q.waiting_on == waiting_on):
            out.append(q)
    return sorted(out, key=lambda q: q.messages[-1].ts if q.messages else q.created_at, reverse=True)


async def get_query(books: Books, query_id: str) -> Query:
    try:
        return Query.model_validate_json(await books.storage.read(_path(query_id)))
    except FileNotFoundError as exc:
        raise KeyError(query_id) from exc


async def open_query(books: Books, body: QueryIn, user: str) -> Query:
    author, role = who(books, user)
    ts = now()
    q = Query(
        id=uuid.uuid4().hex[:12],
        subject=body.subject,
        created_at=ts,
        created_by=author,
        messages=[QueryMessage(ts=ts, author=author, role=role, text=body.text)],
    )
    await books.storage.write(_path(q.id), q.model_dump_json(indent=2).encode(), create_only=True)
    await books.audit(f"user:{user}", "query_opened", {"query": q.id, "about": body.subject.kind, "role": role})
    return q


async def _change(books: Books, query_id: str, fn) -> Query:  # noqa: ANN001 - a small local callback
    path = _path(query_id)
    out: list[Query] = []

    def apply(raw: object) -> object:
        if not raw:
            raise KeyError(query_id)
        q = Query.model_validate(raw)
        fn(q)
        out.append(q)
        return q.model_dump(mode="json", exclude={"waiting_on"})

    await books._update_json(path, None, apply)
    return out[-1]


async def reply(books: Books, query_id: str, body: ReplyIn, user: str) -> Query:
    author, role = who(books, user)

    def add(q: Query) -> None:
        if len(q.messages) >= MAX_MESSAGES:
            raise QueryError("This thread is full; resolve it and start a new one.")
        q.messages.append(QueryMessage(ts=now(), author=author, role=role, text=body.text))
        q.status, q.resolved_at, q.resolved_by = "open", None, None  # a reply reopens a resolved thread

    q = await _change(books, query_id, add)
    await books.audit(f"user:{user}", "query_replied", {"query": query_id, "role": role})
    return q


async def resolve(books: Books, query_id: str, user: str) -> Query:
    author, role = who(books, user)

    def done(q: Query) -> None:
        q.status, q.resolved_at, q.resolved_by = "resolved", now(), author

    q = await _change(books, query_id, done)
    await books.audit(f"user:{user}", "query_resolved", {"query": query_id, "role": role})
    return q
