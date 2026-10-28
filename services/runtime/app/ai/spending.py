"""The spending summary's words (app/spending.py computes the figures). Words from the model, checked by code.

The model gets the facts as JSON and returns {answer_md, confidence} (AskExplanation, strict). Code then applies the
Ask pipeline's checks (app/ai/ask.py): every figure must be in the facts (KnownNumbers), and a figure that belongs
only to the previous period must sit in a sentence that names that period (wrong_period). If either check fails,
or the model cannot be reached, code's own summary (spending.code_summary) is shown, with the reason.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.ai import ask as ask_ai
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError, parse_model_json
from app.ask_router import THIS, Route
from app.schemas import AskExplanation, strict_json_schema
from app.spending import code_summary

SUMMARY_MAX = 700

SYSTEM_PROMPT = (
    "You write a short spending summary for a UK small business owner, from FACTS calculated by code from their "
    "own approved receipts and bills. Plain UK English, friendly, two to four short sentences of plain markdown, "
    "no headings, no tables, no lists. this_period is the period they picked; previous_period the one before it. "
    "Rules: 1) Quote numbers only exactly as they appear in FACTS (you may add £ and thousands commas); never add, "
    "subtract, average or estimate anything yourself; for changes use the `change` values and the change_vs_previous "
    "values. 2) When you quote a previous_period figure, name that period. 3) Mention the biggest category or "
    "supplier, any recurring costs and any unusual one-off if FACTS list them. 4) Do not give financial advice "
    f"beyond pointing at what the figures show. Keep answer_md under {SUMMARY_MAX} characters."
)

_ROUTE = Route(sections=frozenset({"totals"}), periods=frozenset({THIS}))


def check(text: str, facts: dict[str, Any]) -> str | None:
    """Why the model's summary cannot be shown (an invented or misplaced figure), or None when it checks out."""
    known = ask_ai.KnownNumbers(facts)
    invented = known.unknown(text, all_tokens=False)
    if invented:
        return f"The model quoted figures that are not in your books ({', '.join(dict.fromkeys(invented[:3]))})."
    misplaced = ask_ai.wrong_period(text, known, facts, _ROUTE)
    if misplaced:
        return (
            f"The model quoted {misplaced[0][0]}, a figure for {facts['previous_period']['label']}, "
            f"as if it were for {facts['this_period']['label']}."
        )
    return None


def messages(facts: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "FACTS:\n" + json.dumps(facts, separators=(",", ":"), ensure_ascii=False)},
    ]


async def summarise(facts: dict[str, Any], cfg: AiConfig) -> tuple[str, str, str | None]:
    """(summary_md, "model"|"code", why code wrote it). Never raises for model trouble."""
    if not facts["this_period"]["purchases"]:
        return code_summary(facts), "code", None  # nothing to summarise: no model call
    try:
        raw = await ask_ai.call_json_model(messages(facts), cfg, strict_json_schema(AskExplanation), "spending_summary")
        out = AskExplanation.model_validate(parse_model_json(raw))
    except (ExtractionError, ValidationError):
        return code_summary(facts), "code", "The model's reply was not in the expected format."
    except Exception as exc:  # noqa: BLE001  model trouble of any kind: code's summary instead
        return code_summary(facts), "code", ask_ai._trouble(exc, cfg)
    text = ask_ai._clip(out.answer_md, SUMMARY_MAX)
    if not text:
        return code_summary(facts), "code", "The model returned an empty summary."
    if (why := check(text, facts)) is not None:
        return code_summary(facts), "code", why
    return text, "model", None
