"""/notes: the user's notes in `_System/notes/notes.json` (app/assistant_tasks.py). Notes also arrive from Ask and the
"Talk to Accnomos" assistant ("take a note: …"), as a card the user approves. Same headers as /books/*; POST and
DELETE also need `X-User` (for the audit line)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.assistant_tasks import Note, NoteError, NoteIn, add_note, delete_note, load_notes
from app.books import Books
from app.routes_books import get_books, require_user

router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("", response_model=list[Note])
async def notes_list(books: Books = Depends(get_books)) -> list[Note]:
    """Newest first."""
    return await load_notes(books)


@router.post("", response_model=Note, status_code=201)
async def notes_add(body: NoteIn, books: Books = Depends(get_books), user: str = Depends(require_user)) -> Note:
    try:
        return await add_note(books, body, user)
    except NoteError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{note_id}", response_model=Note)
async def notes_delete(note_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> Note:
    try:
        return await delete_note(books, note_id, user)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No such note") from exc
