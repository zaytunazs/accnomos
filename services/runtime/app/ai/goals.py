"""The goal suggestions' words: code works out every figure and its own suggestions (app/goals.py); the user's AI,
when one is set up, words a short "what your goals are telling you" note from those facts, and code checks it.

Checks (as app/ai/home_summary.py): not empty, not too long, no links, every figure in the facts (KnownNumbers).
If any check fails, or the model cannot be reached, code's note stands in, with the reason.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from app.ai.ask import KnownNumbers, call_json_model
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError, parse_model_json
from app.ai.home_summary import LINK
from app.schemas import strict_json_schema

NOTE_MAX = 600

SYSTEM_PROMPT = (
    "You write a short note for a UK small business owner or household about the goals they set themselves "
    "(saving for something, spending less, keeping under a limit, reaching sales). FACTS is JSON worked out by "
    "code from their own books. Write two to four short sentences in plain, friendly UK English, no headings, no "
    "lists, no links. Say which goal most needs attention and why, then give one or two practical suggestions "
    "drawn only from FACTS (the biggest_movers and code_suggestions), for example a category or item that grew. "
    'Rules: 1) Every amount in FACTS is already written as money ("£521.80"): quote amounts exactly as written, '
    "with their £ sign, never as a bare or negative number; say how a goal stands against its plan with its "
    "against_plan words; never add, subtract, work out a percentage or estimate anything. 2) Do not promise "
    "outcomes or give investment, tax or "
    "debt advice. 3) If every goal is on track or reached, say so briefly and name the one closest to slipping, if "
    "any. Return JSON with `note_md`."
)


#: An amount with pence but no £ in front ("521.80"), or a signed one ("-£360.45", "£-360.45", "-360.45").
BARE_MONEY = re.compile(r"(?<![£\d.,])\d[\d,]*\.\d{2}\b|[-−]\s?£|£\s?[-−]|(?<![\w])[-−]\d[\d,]*\.\d{2}\b")


class NoteOutput(BaseModel):
    note_md: str


class GoalsNote(BaseModel):
    note_md: str
    model: str  # "code" when no AI is set up
    fallback_reason: str | None = None


def code_note(facts: dict[str, Any]) -> str:
    goals = facts.get("goals") or []
    if not goals:
        return ""
    worried = [g for g in goals if g["status"] in ("At risk", "Off track", "Over limit", "Missed")]
    if not worried:
        live = [g for g in goals if g["status"] == "On track"]
        if live:
            return f"Your goals are on track. {live[0]['name']}: {live[0]['so_far']} so far."
        return "Your goals are up to date with your books."
    g = worried[0]
    out = [f"{g['name']} is {g['status'].lower()}."]
    out += g.get("code_suggestions", [])[:2]
    return " ".join(out)


def check(text: str, facts: dict[str, Any]) -> str | None:
    text = text.strip()
    if not text:
        return "The model returned an empty note."
    if len(text) > NOTE_MAX:
        return "The model's note was too long."
    if LINK.search(text):
        return "The model's note contained a link."
    if BARE_MONEY.search(text):
        return "The model wrote an amount without its £ sign, or as a negative number."
    if invented := KnownNumbers(facts).unknown(text, all_tokens=False):
        return f"The model quoted figures that are not in your books ({', '.join(dict.fromkeys(invented[:3]))})."
    return None


async def note(facts: dict[str, Any], cfg: AiConfig | None) -> GoalsNote:
    """Never raises: code's note stands in, with the reason."""
    fallback = code_note(facts)
    if not facts.get("goals"):
        return GoalsNote(note_md="", model="code")
    if cfg is None:
        return GoalsNote(note_md=fallback, model="code", fallback_reason="No AI is set up, so code wrote this.")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "FACTS:\n" + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))},
    ]
    try:
        raw = await call_json_model(messages, cfg, strict_json_schema(NoteOutput), "goals_note")
        text = NoteOutput.model_validate(parse_model_json(raw)).note_md.strip()
        reason = check(text, facts)
    except (ExtractionError, ValidationError):
        text, reason = "", "The model's reply was not in the expected format."
    except Exception as exc:  # noqa: BLE001  any model trouble: the figures stand without the model's words
        text, reason = "", f"Your AI ({cfg.mode}) could not write the note ({type(exc).__name__})."
    if reason:
        return GoalsNote(note_md=fallback, model=cfg.model, fallback_reason=reason)
    return GoalsNote(note_md=text, model=cfg.model)
