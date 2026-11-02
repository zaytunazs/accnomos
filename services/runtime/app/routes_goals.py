"""Goals, tracked by code against the user's own books (app/goals.py); suggestions worded by the user's AI and checked.

GET    /books/goals            every goal with its progress, code's suggestions, and the note ("what your goals are
                               telling you"); `note_ai=false` keeps the model out (code writes the note)
POST   /books/goals            add a goal; 201
PATCH  /books/goals/{id}       change one (also how "I put aside £50 more" is recorded: a new saved_pence)
DELETE /books/goals/{id}       remove one; 204
Same headers as /books/*; changes also need X-User. Goals only read the books: nothing here posts or approves.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import dashboard as dash
from app import goals as gm
from app.ai import goals as goals_ai
from app.ai.config import AiConfig
from app.books import Books
from app.books import today as london_today
from app.routes_books import get_books, require_user
from app.routes_plan import optional_ai

router = APIRouter(prefix="/books", tags=["goals"])


class GoalsView(BaseModel):
    today: date
    household: bool
    goals: list[gm.GoalProgress]
    note: goals_ai.GoalsNote
    facts: dict  # every figure the note may quote


async def _household(books: Books) -> bool:
    prof = await dash._profile_or_default(books)  # noqa: SLF001 - the same lenient profile read Home uses
    return prof.kind == "personal"


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/goals", response_model=GoalsView)
async def get_goals(
    today: date | None = Query(None, description="the user's date (Europe/London); defaults to today"),
    note_ai: bool = Query(True, description="false: code writes the note even when an AI is set up"),
    cfg: AiConfig | None = Depends(optional_ai),
    books: Books = Depends(get_books),
) -> GoalsView:
    day = today or london_today()
    household = await _household(books)
    goals = await gm.load_goals(books)
    data = await gm.load_data(books, goals, household, day)
    progress = [gm.progress(g, data, day) for g in goals]
    facts = gm.facts(progress, day)
    note = await goals_ai.note(facts, cfg if note_ai else None)
    return GoalsView(today=day, household=household, goals=progress, note=note, facts=facts)


@router.post("/goals", response_model=gm.Goal, status_code=201)
async def post_goal(body: gm.GoalIn, books: Books = Depends(get_books), user: str = Depends(require_user)) -> gm.Goal:
    scope = "personal" if await _household(books) else "business"
    try:
        return await gm.add_goal(books, body, user, scope)
    except gm.GoalError as exc:
        raise _refused(exc) from exc


@router.patch("/goals/{goal_id}", response_model=gm.Goal)
async def patch_goal(
    goal_id: str, body: gm.GoalPatch, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> gm.Goal:
    try:
        return await gm.patch_goal(books, goal_id, body, user)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No such goal") from exc
    except gm.GoalError as exc:
        raise _refused(exc) from exc


@router.delete("/goals/{goal_id}", status_code=204)
async def delete_goal(goal_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> None:
    try:
        await gm.delete_goal(books, goal_id, user)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No such goal") from exc
