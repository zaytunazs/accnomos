"""POST /ai/grid-filter: plain words to a grid filter for the Power grid add-on (app/ai/grid_filter.py).

Body: {"grid": "ledger", "text": "PayPal fees over £5 in October", "today": "2026-11-11", "accounts": [...]}.
Returns an AG Grid filter model and sort built by code from the allowlist, or the words as a plain search. Same
headers as /books/* (the caller's books are opened to check who is asking); nothing here reads or writes the books.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import Field

from app.ai import grid_filter as gf
from app.ai.config import AiConfig
from app.books import Books
from app.books import today as london_today
from app.routes_books import get_books
from app.routes_plan import optional_ai
from app.validation import StrictBody

router = APIRouter(prefix="/ai", tags=["ai"])


class GridFilterIn(StrictBody):
    grid: Literal["ledger"]
    text: str = Field(min_length=1, max_length=300)
    today: date | None = None
    accounts: list[Annotated[str, Field(max_length=80)]] = Field(default_factory=list, max_length=300)


@router.post("/grid-filter", response_model=gf.GridFilterResult)
async def grid_filter(
    body: GridFilterIn,
    cfg: AiConfig | None = Depends(optional_ai),
    _books: Books = Depends(get_books),  # signed-in callers only: the model is the caller's (or the server's) AI
) -> gf.GridFilterResult:
    return await gf.grid_filter(body.grid, body.text, body.today or london_today(), body.accounts, cfg)
