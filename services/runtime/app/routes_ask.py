"""POST /books/ask: grounded answers about the user's own books.

Code loads the ledger and builds the facts pack; the model only writes words around those facts;
code then checks every figure and citation (app/ai/ask.py). Nothing is kept after the response.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Header

from app.ai import ask as ask_ai
from app.ai.config import AiConfig, ai_config_from_request
from app.books import Books
from app.facts import build_facts, default_period
from app.routes_books import get_books
from app.schemas import AskAnswer, AskRequest

router = APIRouter(prefix="/books", tags=["ask"])


@router.post("/ask", response_model=AskAnswer)
async def ask(
    body: AskRequest,
    books: Books = Depends(get_books),
    cfg: AiConfig = Depends(ai_config_from_request),
    x_business_name: str | None = Header(default=None),
) -> AskAnswer:
    period = body.period or default_period(date.today())
    facts = await build_facts(books, period, x_business_name)
    return await ask_ai.answer(body.question, facts, body.history, cfg)
