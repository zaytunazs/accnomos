"""The month-end close summary: facts from code, words from the user's AI, checked by code (as Ask and reminders).

Code runs the checklist (app/month_end.py) and hands the model only what it found: each step's title, status and
plain-English reason, the counts, and the month's figures already formatted. The model writes two to four
sentences of plain UK English. Code then checks them with Ask's number check (`KnownNumbers`): every figure must be
one of the facts, there may be no links, and a month that cannot be closed may not be called ready. Anything else,
or no AI set up, or any model trouble: code writes the summary itself and `fallback_reason` says why.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from app.ai.ask import KnownNumbers, call_json_model
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError, parse_model_json
from app.schemas import strict_json_schema

SUMMARY_MAX = 900

SYSTEM_PROMPT = (
    "You summarise a UK small business owner's month-end close checklist in plain UK English: two to four short "
    "sentences, no headings, no lists, no links. You are given FACTS as JSON, worked out by code. Rules: "
    "1) Quote figures, counts and dates exactly as they appear in FACTS; never calculate anything. "
    "2) Say first how many things need the owner and how many of them stop the close (FACTS.needs_you, "
    "FACTS.blocking). 3) If FACTS.can_close is false, never say the month is ready to close. "
    "4) Mention the most important step reasons by name. Return JSON with `summary_md`."
)

LINK = re.compile(r"https?://|www\.", re.IGNORECASE)
READY = re.compile(r"\bready to (be )?close|\bcan (now )?be closed|\ball clear\b", re.IGNORECASE)


class SummaryModelOutput(BaseModel):
    summary_md: str


class CloseSummary(BaseModel):
    summary_md: str
    model: str
    fallback_reason: str | None = None


def fallback_summary(facts: dict[str, Any]) -> str:
    """Written by code from the facts alone."""
    label, needs, blocking = facts["month"], facts["needs_you"], facts["blocking"]
    if facts.get("closed") and not needs:
        head = f"{label} is closed and nothing has changed since."
    elif needs == 0:
        head = f"{label}: nothing needs you."
    else:
        things = "thing needs" if needs == 1 else "things need"
        if blocking == needs:
            head = f"{label}: {needs} {things} you before the month can be closed."
        elif blocking:
            head = f"{label}: {needs} {things} you, {blocking} of them before the month can be closed."
        else:
            head = f"{label}: {needs} {things} you; none of them blocks the close."
    open_steps = [s for s in facts["steps"] if s["status"] != "ok"]
    detail = " ".join(f"{s['title']}: {s['reason']}" for s in open_steps[:3])
    tail = (
        f" Approve “Mark {label} closed” to lock it."
        if facts["can_close"]
        else (" The close is not offered until the blocking items are cleared." if blocking else "")
    )
    return " ".join(x for x in (head, detail, tail.strip()) if x)


def ground(text: str, facts: dict[str, Any]) -> str | None:
    """None when the model's summary passes every check, otherwise the reason it does not."""
    text = text.strip()
    if not text:
        return "The model returned an empty summary."
    if len(text) > SUMMARY_MAX:
        return "The model's summary was too long."
    if LINK.search(text):
        return "The model's summary contained a link."
    if not facts["can_close"] and READY.search(text):
        return "The model said the month was ready to close; it is not."
    if invented := KnownNumbers(facts).unknown(text, all_tokens=False):
        return f"The model quoted figures that are not in the checklist ({', '.join(dict.fromkeys(invented[:3]))})."
    return None


async def summarise(facts: dict[str, Any], cfg: AiConfig | None) -> CloseSummary:
    """Never raises: the code-written summary stands in, with the reason."""
    if cfg is None:
        return CloseSummary(
            summary_md=fallback_summary(facts), model="code", fallback_reason="No AI is set up, so code wrote this."
        )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"FACTS:\n{json.dumps(facts, ensure_ascii=False)}"},
    ]
    try:
        raw = await call_json_model(messages, cfg, strict_json_schema(SummaryModelOutput), "close_summary")
        text = SummaryModelOutput.model_validate(parse_model_json(raw)).summary_md.strip()
        reason = ground(text, facts)
    except (ExtractionError, ValidationError):
        text, reason = "", "The model's reply was not in the expected format."
    except Exception as exc:  # noqa: BLE001  any model trouble: the checklist stands without the model's words
        text, reason = "", f"Your AI ({cfg.mode}) could not write the summary ({type(exc).__name__})."
    if reason:
        return CloseSummary(summary_md=fallback_summary(facts), model=cfg.model, fallback_reason=reason)
    return CloseSummary(summary_md=text, model=cfg.model)
