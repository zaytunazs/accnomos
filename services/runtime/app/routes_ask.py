"""POST /books/ask and /books/ask/voice: grounded answers about the user's own books.

Code loads the ledger and builds the facts pack; the model only writes words around those facts;
code then checks every figure and citation (app/ai/ask.py). Nothing is kept after the response.
An instruction ("send a £100 invoice to JM Trading") gets a proposed action instead (app/actions.py),
which does nothing until the user approves it with POST /actions/approve.
A spoken question is transcribed by Muse Voice (app/ai/voice.py) and then takes exactly the same path.
"Plan my Thursday" (typed or spoken) is not a question about the books: code spots it and answers with a
`plan_day` action for that date, which the app opens as a day plan (POST /plan/day); no model is called.

`POST /books/ask?stream=1` answers as server-sent events: `start` (code's key numbers, citations and buttons, at
once), `token` events (the explanation as the model writes it; unchecked until the end), then `answer`, the
checked AskAnswer exactly as the plain call returns it, whose words replace the streamed ones. An instruction or a
day plan needs no model, so it comes as a single `answer` event.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, TypeAdapter, ValidationError

from app import actions, spending
from app.ai import ask as ask_ai
from app.ai import spending as spending_ai
from app.ai import voice
from app.ai.config import AiConfig, ai_config_from_request
from app.books import EVENTS, Books, today
from app.facts import build_facts, default_period
from app.planner import TZ, plan_intent, uk_day
from app.routes_actions import graph_token
from app.routes_books import business_name, get_books
from app.schemas import (
    AskAnswer,
    AskPeriod,
    AskRequest,
    AskTurn,
    AskVoiceAnswer,
    Clarification,
    KeyNumber,
    ProposedAction,
    SuggestedAction,
)
from app.vat_cycle import VatCycle, vat_cycle

router = APIRouter(prefix="/books", tags=["ask"])
_TURNS = TypeAdapter(list[AskTurn])


def _action_answer(
    found: ProposedAction | Clarification | actions.NotAvailable, cfg: AiConfig, period: AskPeriod
) -> AskAnswer:
    """An instruction gets a card (or one follow-up question) instead of a facts answer."""
    base: dict[str, Any] = {
        "key_numbers": [],
        "citations": [],
        "suggested_actions": [],
        "confidence": "high",
        "model": cfg.model or cfg.mode,
        "period": period,
    }
    if isinstance(found, ProposedAction):
        return AskAnswer(answer_md=found.summary_md, proposed_action=found, **base)
    if isinstance(found, Clarification):
        return AskAnswer(answer_md=found.question_md, clarification=found, **base)
    return AskAnswer(answer_md=found.message, **base)


def plan_answer(day: date, period: AskPeriod) -> AskAnswer:
    label = uk_day(day)
    return AskAnswer(
        answer_md=f"I can plan {label} from your calendar and open jobs: visits grouped by postcode, travel, lunch "
        "and any admin that is due. Nothing goes in your calendar until you approve it.",
        key_numbers=[],
        citations=[],
        confidence="high",
        model="code",
        period=period,
        suggested_actions=[SuggestedAction(label=f"Plan {label}", kind="plan_day", arg=day.isoformat())],
    )


async def spending_answer(books: Books, period: AskPeriod, cfg: AiConfig, business: str | None) -> AskAnswer:
    """ "Summarise my spending": the Spending page's summary for the Ask period (code's figures, checked words)."""
    facts = await spending.build(books, period, business)
    text, by, why = await spending_ai.summarise(facts, cfg)
    t = facts["this_period"]
    src = (t["sources"] if "sources" in t else facts["sources"]) or [f"{EVENTS}/"]
    return AskAnswer(
        answer_md=text,
        key_numbers=[
            KeyNumber(label=f"Spent before VAT, {t['label']}", value=f"£{Decimal(t['spent']):,.2f}", source=src[0]),
            KeyNumber(label=f"Purchases, {t['label']}", value=str(t["purchases"]), source=src[0]),
        ],
        citations=src,
        suggested_actions=[SuggestedAction(label="Open Spending", kind="open_spending", arg=None)],
        confidence="high" if by == "model" else "medium",
        model=cfg.model if by == "model" else "code",
        period=period,
        fallback_reason=why,
    )


async def _prepare(
    req: AskRequest,
    books: Books,
    cfg: AiConfig,
    business: str | None,
    token: str,
    cycle: VatCycle,
) -> AskAnswer | dict[str, Any]:
    """Day-plan intent (code, no model) → instruction (proposed action) → the facts pack for a question about the books.

    No period in the request: the current VAT period by the settings sent as `stagger`/`start_month`/`months`."""
    period = req.period or default_period(today(), cycle)
    if (day := plan_intent(req.question, today(TZ))) is not None:
        return plan_answer(day, period)
    if spending.asks_for_summary(req.question):
        return await spending_answer(books, period, cfg, business)
    found = await actions.propose(req.question, books, cfg, token, today(TZ))  # the same day as the plan and VAT period
    if found is not None:
        return _action_answer(found, cfg, period)
    return await build_facts(books, period, business)


async def _answer(
    req: AskRequest,
    books: Books,
    cfg: AiConfig,
    business: str | None,
    token: str,
    cycle: VatCycle,
) -> AskAnswer:
    ready = await _prepare(req, books, cfg, business, token, cycle)
    if isinstance(ready, AskAnswer):
        return ready
    return await ask_ai.answer(req.question, ready, req.history, cfg)


def _sse(event: str, data: Any) -> str:
    payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


async def _events(req: AskRequest, ready: AskAnswer | dict[str, Any], cfg: AiConfig) -> AsyncIterator[str]:
    if isinstance(ready, AskAnswer):
        yield _sse("answer", ready)
        return
    async for event, data in ask_ai.answer_stream(req.question, ready, req.history, cfg):
        yield _sse(event, {"text": data} if event == "token" else data)


@router.post("/ask", response_model=AskAnswer)
async def ask(
    body: AskRequest,
    stream: bool = Query(
        default=False, description="1: server-sent events (start, token…, answer) instead of one JSON answer"
    ),
    books: Books = Depends(get_books),
    cfg: AiConfig = Depends(ai_config_from_request),
    business: str | None = Depends(business_name),
    token: str = Depends(graph_token),
    cycle: VatCycle = Depends(vat_cycle),
) -> Any:
    """An answer about the books, or, for an instruction ("send a £100 invoice to …"), a proposed action to approve."""
    ready = await _prepare(
        body, books, cfg, business, token, cycle
    )  # before streaming, so its errors keep their status
    if stream:
        return StreamingResponse(
            _events(body, ready, cfg),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    if isinstance(ready, AskAnswer):
        return ready
    return await ask_ai.answer(body.question, ready, body.history, cfg)


@router.post("/ask/voice", response_model=AskVoiceAnswer)
async def ask_voice(
    audio: UploadFile = File(...),
    period: str | None = Form(default=None),
    history: str | None = Form(default=None),
    books: Books = Depends(get_books),
    cfg: AiConfig = Depends(ai_config_from_request),
    business: str | None = Depends(business_name),
    token: str = Depends(graph_token),
    cycle: VatCycle = Depends(vat_cycle),
) -> AskVoiceAnswer:
    """Spoken question (webm/ogg/m4a/wav) -> WAV via ffmpeg -> Muse Voice Transcribe -> the /books/ask answer.

    Optional form fields `period` and `history` are JSON shaped as in AskRequest. Key mode only.
    """
    voice_cfg = cfg.with_capability("voice") if cfg.in_chain else cfg  # the chain: its Meta Model API provider
    if voice_cfg is None or voice_cfg.mode != "key":
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
        transcript = await voice.transcribe(wav, voice_cfg)
    except voice.VoiceError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    try:
        req = AskRequest(question=transcript, period=when, history=turns)
    except ValidationError as exc:
        raise HTTPException(
            422, f"That question is too long ({len(transcript)} characters; keep it under 500)"
        ) from exc
    answer = await _answer(req, books, cfg, business, token, cycle)
    return AskVoiceAnswer(**answer.model_dump(), transcript=transcript)
