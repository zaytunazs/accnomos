"""The user's to-do list, kept in their own books folder as `_System/Todos/todos.json`.

Inbox triage suggests to-dos; one lands here only when the user taps *Add*. Deleting one is how it is done.
Adding the same text from the same email twice keeps one entry. Every change is an audit line.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator

from app.books import SYSTEM, Books, now
from app.validation import StrictBody

TODOS = f"{SYSTEM}/Todos/todos.json"
TODOS_MAX = 500


class TodoError(ValueError):
    """The list cannot take this change (it is full, or the file is not a to-do list)."""


class TodoSource(StrictBody):
    kind: Literal["mail"] = "mail"
    message_id: str | None = Field(None, max_length=512)
    subject: str = Field("", max_length=200)
    web_link: str | None = Field(None, max_length=2000)

    @field_validator("web_link")
    @classmethod
    def _https(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("https://"):
            raise ValueError("web_link must be an https:// link")
        return v


class TodoIn(StrictBody):
    text: str = Field(min_length=1, max_length=200)
    due: date | None = None
    source: TodoSource | None = None

    @field_validator("text")
    @classmethod
    def _one_line(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("text is empty")
        return v


class Todo(TodoIn):
    id: str
    created_at: datetime
    created_by: str


def _sort_key(t: Todo) -> tuple[bool, date, datetime]:
    return (t.due is None, t.due or date.max, t.created_at)


def _parse(raw: Any) -> list[Todo]:
    if not isinstance(raw, list):
        raise TodoError(f"{TODOS} is not a list")
    try:
        return [Todo.model_validate(t) for t in raw]
    except ValidationError as exc:
        raise TodoError(f"{TODOS} has an entry that is not a to-do: {exc.errors()[0]['msg']}") from exc


def _same(a: TodoIn, b: TodoIn) -> bool:
    return a.text.casefold() == b.text.casefold() and (a.source and a.source.message_id) == (
        b.source and b.source.message_id
    )


async def list_todos(books: Books) -> list[Todo]:
    return sorted(_parse(await books.read_json(TODOS, [])), key=_sort_key)


async def add_todo(books: Books, body: TodoIn, user: str) -> tuple[Todo, bool]:
    """(the to-do, whether it is new). An identical one already on the list is returned as it is."""
    new = Todo(**body.model_dump(), id=uuid.uuid4().hex[:12], created_at=now(), created_by=user)
    found: list[Todo] = []

    def change(raw: Any) -> Any:
        todos = _parse(raw)
        found[:] = [t for t in todos if _same(t, body)][:1]
        if found:
            return raw
        if len(todos) >= TODOS_MAX:
            raise TodoError(f"Your to-do list is full ({TODOS_MAX}); tick some off first.")
        return [*raw, new.model_dump(mode="json")]

    await books._update_json(TODOS, [], change)
    if found:
        return found[0], False
    await books.audit(
        f"user:{user}", "todo_added", {"todo": new.id, "source": body.source.kind if body.source else None}
    )
    return new, True


async def delete_todo(books: Books, todo_id: str, user: str) -> Todo:
    """Remove one to-do (done or not wanted). KeyError if it is not on the list."""
    gone: list[Todo] = []

    def change(raw: Any) -> Any:
        todos = _parse(raw)
        gone[:] = [t for t in todos if t.id == todo_id]
        if not gone:
            raise KeyError(todo_id)
        return [t.model_dump(mode="json") for t in todos if t.id != todo_id]

    await books._update_json(TODOS, [], change)
    await books.audit(f"user:{user}", "todo_deleted", {"todo": todo_id})
    return gone[0]
