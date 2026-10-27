"""/todos: the user's to-do list in `_System/Todos/todos.json` (app/todos.py). Same headers as /books/*;
POST and DELETE also need `X-User` (for the audit line)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from app.books import Books
from app.routes_books import get_books, require_user
from app.todos import Todo, TodoError, TodoIn, add_todo, delete_todo, list_todos

router = APIRouter(prefix="/todos", tags=["todos"])


@router.get("", response_model=list[Todo])
async def todos_list(books: Books = Depends(get_books)) -> list[Todo]:
    try:
        return await list_todos(books)
    except TodoError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("", response_model=Todo)
async def todos_add(
    body: TodoIn, response: Response, books: Books = Depends(get_books), user: str = Depends(require_user),
) -> Todo:
    """201 for a new to-do; 200 with the existing one when the same to-do is already on the list."""
    try:
        todo, created = await add_todo(books, body, user)
    except TodoError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    response.status_code = 201 if created else 200
    return todo


@router.delete("/{todo_id}", response_model=Todo)
async def todos_delete(todo_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> Todo:
    try:
        return await delete_todo(books, todo_id, user)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No such to-do") from exc
    except TodoError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
