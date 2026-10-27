"""POST /books/ask and /books/ask/voice: grounded answers about the user's own books.

Code loads the ledger and builds the facts pack; the model only writes words around those facts;
code then checks every figure and citation (app/ai/ask.py). Nothing is kept after the response.
An instruction ("send a £100 invoice to JM Trading") gets a proposed action instead (app/actions.py),
which does nothing until the user approves it with POST /actions/approve.
A spoken question is transcribed by Muse Voice (app/ai/voice.py) and then takes exactly the same path.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError

from app import actions
from app.ai import ask as ask_ai
from app.ai import voice
from app.ai.config import AiConfig, ai_config_from_request
from app.books import Books
from app.facts import build_facts, default_period
from app.routes_actions import graph_token
from app.routes_books import get_books
from app.schemas import AskAnswer, AskPeriod, AskRequest, AskTurn, AskVoiceAnswer, Clarification, ProposedAction

router = APIRouter(prefix="/books", tags=["ask"])
_TURNS = TypeAdapter(list[AskTurn])


def _action_answer(found: ProposedAction | Clarification | actions.NotAvailable, cfg: AiConfig, period: AskPeriod) -> AskAnswer:
    """An instruction gets a card (or one follow-up question) instead of a facts answer."""
    base: dict[str, Any] = {
        "key_numbers": [], "citations": [], "suggested_actions": [], "confidence": "high", "model": cfg.model or cfg.mode,
        "period": period,
    }
    if isinstance(found, ProposedAction):
        return AskAnswer(answer_md=found.summary_md, proposed_action=found, **base)
    if isinstance(found, Clarification):
        return AskAnswer(answer_md=found.question_md, clarification=found, **base)
    return AskAnswer(answer_md=found.message, **base)


async def _answer(req: AskRequest, books: Books, cfg: AiConfig, business: str | None, token: str) -> AskAnswer:
    period = req.period or default_period(date.today())
    found = await actions.propose(req.question, books, cfg, token)
    if found is not None:
        return _action_answer(found, cfg, period)
    facts = await build_facts(books, period, business)
    return await ask_ai.answer(req.question, facts, req.history, cfg)


@router.post("/ask", response_model=AskAnswer)
async def ask(
    body: AskRequest,
    books: Books = Depends(get_books),
    cfg: AiConfig = Depends(ai_config_from_request),
    x_business_name: str | None = Header(default=None),
    token: str = Depends(graph_token),
) -> AskAnswer:
    """An answer about the books, or, for an instruction ("send a £100 invoice to …"), a proposed action to approve."""
    return await _answer(body, books, cfg, x_business_name, token)


@router.post("/ask/voice", response_model=AskVoiceAnswer)
async def ask_voice(
    audio: UploadFile = File(...),
    period: str | None = Form(default=None),
    history: str | None = Form(default=None),
    books: Books = Depends(get_books),
    cfg: AiConfig = Depends(ai_config_from_request),
    x_business_name: str | None = Header(default=None),
    token: str = Depends(graph_token),
) -> AskVoiceAnswer:
    """Spoken question (webm/ogg/m4a/wav) -> WAV via ffmpeg -> Muse Voice Transcribe -> the /books/ask answer.

    Optional form fields `period` and `history` are JSON shaped as in AskRequest. Key mode only.
    """
    if cfg.mode != "key":
        raise HTTPException(400, "voice needs a Meta API key")
    try:
        when = AskPeriod.model_validate_json(period) if period else None
        turns = _TURNS.validate_json(history) if history else []
    except ValidationError as exc:
        raise HTTPException(422, f"Bad period or history: {exc.errors()[0]['msg']}") from exc
    try:
        voice.require_ffmpeg()
        data = await audio.read(voice.MAX_UPLOAD_BYTES + 1)
        wav = await voice.to_wav(data, audio.content_type, audio.filename)
        transcript = await voice.transcribe(wav, cfg)
    except voice.VoiceError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    try:
        req = AskRequest(question=transcript, period=when, history=turns)
    except ValidationError as exc:
        raise HTTPException(422, f"That question is too long ({len(transcript)} characters; keep it under 500)") from exc
    answer = await _answer(req, books, cfg, x_business_name, token)
    return AskVoiceAnswer(**answer.model_dump(), transcript=transcript)
