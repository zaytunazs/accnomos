"""Answer a question about the user's books from a facts pack. Numbers from code, words from the model.

The model sees only the facts pack (app/facts.py) and the question, and returns strict JSON. Then
code checks it: every figure it quotes must be in the facts, every citation must be a listed source.
If it invents a figure, its words are dropped and the answer quotes the facts directly.

Backends mirror app/ai/extract.py: Ollama `/api/chat` with `format` = schema and `think: false`;
Meta Model API `/chat/completions` with `response_format` json_schema strict.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.ai.config import AiConfig
from app.ai.extract import ExtractionError, parse_model_json
from app.facts import vat_sources
from app.schemas import (
    ASK_ANSWER_MAX,
    AskAnswer,
    AskModelOutput,
    AskPeriod,
    AskTurn,
    KeyNumber,
    SuggestedAction,
    strict_json_schema,
)

TIMEOUT_S = 120.0
KEY_NUMBERS = (2, 5)
MAX_ACTIONS = 3
LABEL_MAX = 80

SYSTEM_PROMPT = (
    "You answer a UK small business owner's questions about their own books. Write in plain UK English, "
    "short and friendly, as plain markdown (short paragraphs or '-' lists; no tables, no headings). "
    f"Keep answer_md under {ASK_ANSWER_MAX} characters. "
    "You are given FACTS as JSON, calculated by code from the owner's ledger. Rules: "
    "1) Quote numbers only exactly as they appear in FACTS (you may add £ and thousands commas). "
    "Never add, subtract, average or estimate anything yourself: for changes use the `derived` values. "
    "2) If FACTS do not answer the question, say so plainly and suggest what would. "
    "3) key_numbers: 2 to 5 figures copied from FACTS; source = the path from FACTS.sources they come from. "
    "4) citations: only paths listed in FACTS.sources. "
    "5) suggested_actions (0-3): open_review (proposals waiting), open_vat (the VAT return), "
    "chase_supplier (arg = supplier name from FACTS), none. "
    "6) confidence: high when FACTS answer it directly, medium when partly, low otherwise. "
    "Box 5 is always positive; FACTS.derived.vat_position says whether the owner pays or is repaid."
)

_NUMBER = re.compile(r"[-−]?£?\d[\d,]*(?:\.\d+)?%?")


# --------------------------------------------------------------------------- #
# Numbers: what the facts contain, and what an answer quotes
# --------------------------------------------------------------------------- #

def _parse(token: str) -> Decimal | None:
    clean = token.replace("−", "-").replace("£", "").replace(",", "").rstrip("%")
    try:
        return Decimal(clean)
    except InvalidOperation:
        return None


def _is_plain_small(token: str) -> bool:
    """Bare small integers ("Box 5", "Q3", "7 Nov", "3 receipts") are words, not figures."""
    return re.fullmatch(r"\d{1,2}", token) is not None


def _walk(node: Any) -> Iterable[Any]:
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)
    else:
        yield node


class KnownNumbers:
    """Every number in the facts pack's values, compared by value (so 2140, 2140.00 and £2,140.00 match).

    `said` is the user's own question: a figure they typed ("fuel in March 2025") is not one the model made up.
    Also accepted: the absolute value (a delta of -620.00 quoted as "down £620") and whole-pound or
    whole-percent roundings ("£2,141" for 2140.56, "18%" for 18.3).
    """

    def __init__(self, facts: dict[str, Any], said: str = "") -> None:
        exact: set[Decimal] = {d for t in _NUMBER.findall(said) if (d := _parse(t)) is not None}
        for v in _walk(facts):
            if isinstance(v, bool) or v is None:
                continue
            if isinstance(v, (int, float)):
                exact.add(Decimal(str(v)))
            elif isinstance(v, str):
                exact.update(d for t in _NUMBER.findall(v) if (d := _parse(t)) is not None)
        self.exact = {abs(d) for d in exact}
        self.rounded = {d.quantize(Decimal("1"), rounding=ROUND_HALF_UP) for d in self.exact}
        self.rounded |= {d.to_integral_value(rounding=ROUND_DOWN) for d in self.exact}

    def knows(self, token: str) -> bool:
        d = _parse(token)
        if d is None:
            return True
        d = abs(d)
        return d in self.exact or (d == d.to_integral_value() and d in self.rounded)

    def unknown(self, text: str, *, all_tokens: bool) -> list[str]:
        found = _NUMBER.findall(text)
        if not all_tokens:
            found = [t for t in found if not _is_plain_small(t.lstrip("-−"))]
        return [t for t in found if not self.knows(t)]


# --------------------------------------------------------------------------- #
# Post-validation
# --------------------------------------------------------------------------- #

def _gbp(amount: str) -> str:
    return f"£{Decimal(amount):,.2f}" if "." in amount else f"£{int(amount):,}"


def _uk(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d:%b %Y}"


def _fact_key_numbers(facts: dict[str, Any]) -> list[KeyNumber]:
    src = vat_sources(facts)[0]
    this, prev = facts["this_period"], facts["previous_period"]
    return [
        KeyNumber(label=f"Net VAT (Box 5), {this['period_key']}", value=_gbp(this["vat"]["box5"]), source=src),
        KeyNumber(label=f"Net VAT (Box 5), {prev['period_key']}", value=_gbp(prev["vat"]["box5"]), source=src),
        KeyNumber(label="VAT on sales (Box 1)", value=_gbp(this["vat"]["box1"]), source=src),
        KeyNumber(label="VAT reclaimed (Box 4)", value=_gbp(this["vat"]["box4"]), source=src),
    ]


def _period(facts: dict[str, Any]) -> AskPeriod:
    return AskPeriod(start=facts["this_period"]["start"], end=facts["this_period"]["end"])


def fallback_answer(facts: dict[str, Any], model: str, reason: str) -> AskAnswer:
    """The facts, quoted directly by code. Used when the model fails or invents a figure."""
    this, prev, d = facts["this_period"], facts["previous_period"], facts["derived"]
    lines = [
        "I couldn't check a written explanation against your books, so here are the figures exactly as "
        "calculated from your ledger:",
        "",
        f"- Net VAT (Box 5), {_uk(this['start'])} to {_uk(this['end'])}: {_gbp(this['vat']['box5'])} "
        f"({d['vat_position']})",
        f"- Previous period ({_uk(prev['start'])} to {_uk(prev['end'])}): {_gbp(prev['vat']['box5'])}",
        f"- Sales {_gbp(this['totals']['sales']['net'])} net, purchases {_gbp(this['totals']['purchases']['net'])} net, "
        f"from {this['entries']} approved entries",
    ]
    pending = facts.get("pending_proposals")
    if pending and (pending["proposed"] or pending["needs_a_look"]):
        lines.append(f"- Waiting for you: {pending['proposed']} proposed, {pending['needs_a_look']} to look at")
    actions = [SuggestedAction(label="Open the VAT return", kind="open_vat", arg=None)]
    if pending and (pending["proposed"] or pending["needs_a_look"]):
        actions.append(SuggestedAction(label="Review waiting entries", kind="open_review", arg=None))
    return AskAnswer(
        answer_md="\n".join(lines), key_numbers=_fact_key_numbers(facts)[:3], citations=vat_sources(facts),
        suggested_actions=actions, confidence="low", model=model, period=_period(facts), fallback_reason=reason,
    )


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:") + "…"


def ground(out: AskModelOutput, facts: dict[str, Any], model: str, question: str = "") -> AskAnswer:
    """Check the model's answer against the facts (and the question's own figures); return it cleaned, or the
    fallback if it invented a figure."""
    known = KnownNumbers(facts, question)
    answer_md = _clip(out.answer_md, ASK_ANSWER_MAX)
    if not answer_md:
        return fallback_answer(facts, model, "The model returned an empty answer.")
    invented = known.unknown(answer_md, all_tokens=False)
    for kn in out.key_numbers:
        invented += known.unknown(kn.value, all_tokens=True)
    if invented:
        shown = ", ".join(dict.fromkeys(invented[:3]))
        return fallback_answer(facts, model, f"The model quoted figures that are not in your books ({shown}).")

    sources = set(facts["sources"])
    default_src = vat_sources(facts)[0]
    key_numbers = [
        KeyNumber(label=_clip(k.label, LABEL_MAX), value=k.value.strip(), source=k.source if k.source in sources else default_src)
        for k in out.key_numbers if k.value.strip()
    ][: KEY_NUMBERS[1]]
    labels = {k.label for k in key_numbers}
    for extra in _fact_key_numbers(facts):
        if len(key_numbers) >= KEY_NUMBERS[0]:
            break
        if extra.label not in labels:
            key_numbers.append(extra)

    citations = [c for c in dict.fromkeys(out.citations) if c in sources] or vat_sources(facts)

    names = {t["name"].lower() for t in facts.get("top_suppliers", [])}
    names |= {t["counterparty"].lower() for t in facts.get("largest_transactions", [])}
    actions: list[SuggestedAction] = []
    for a in out.suggested_actions:
        if a.kind == "chase_supplier" and (not a.arg or a.arg.strip().lower() not in names):
            continue  # never chase a supplier the books don't know
        if a.kind == "plan_day":
            continue  # only code offers a day plan (app/routes_ask.py)
        actions.append(SuggestedAction(label=_clip(a.label, LABEL_MAX), kind=a.kind, arg=_clip(a.arg, LABEL_MAX) if a.arg else None))

    return AskAnswer(
        answer_md=answer_md, key_numbers=key_numbers, citations=citations, suggested_actions=actions[:MAX_ACTIONS],
        confidence=out.confidence, model=model, period=_period(facts),
    )


# --------------------------------------------------------------------------- #
# Model call
# --------------------------------------------------------------------------- #

def _messages(question: str, facts: dict[str, Any], history: list[AskTurn]) -> list[dict[str, str]]:
    facts_json = json.dumps(facts, separators=(",", ":"), ensure_ascii=False)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        *({"role": t.role, "content": t.text[:1000]} for t in history),
        {"role": "user", "content": f"FACTS:\n{facts_json}\n\nQuestion: {question.strip()}"},
    ]


async def _call_model(
    messages: list[dict[str, str]], cfg: AiConfig, output: type[BaseModel] = AskModelOutput, name: str = "ask_answer",
) -> str:
    """Raw JSON text from the configured backend, constrained to `output`'s schema (app/ai/plan.py uses it too)."""
    return await call_json_model(messages, cfg, strict_json_schema(output), name)


async def call_json_model(messages: list[dict[str, str]], cfg: AiConfig, schema: dict[str, Any], name: str) -> str:
    """Raw JSON text from the user's backend, constrained to `schema` (also used by app/ai/remind.py)."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S)) as client:
        if cfg.mode == "local":
            body: dict[str, Any] = {
                "model": cfg.model, "messages": messages, "format": schema, "think": False, "stream": False,
                "options": {"temperature": 0}, "keep_alive": "24h",
            }
            r = await client.post(f"{cfg.base_url}/api/chat", json=body)
            r.raise_for_status()
            return r.json().get("message", {}).get("content", "")
        body = {
            "model": cfg.model, "messages": messages,
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
            "reasoning_effort": "low",
        }
        r = await client.post(f"{cfg.base_url}/chat/completions", json=body, headers={"Authorization": f"Bearer {cfg.api_key}"})
        r.raise_for_status()
        content = r.json()["choices"][0]["message"].get("content") or ""
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return content


async def answer(question: str, facts: dict[str, Any], history: list[AskTurn], cfg: AiConfig) -> AskAnswer:
    """Ask the model, then check its answer against the facts. Never raises for model trouble."""
    try:
        text = await _call_model(_messages(question, facts, history), cfg)
    except httpx.HTTPStatusError as exc:
        return fallback_answer(facts, cfg.model, f"Your AI ({cfg.mode}) returned HTTP {exc.response.status_code}.")
    except httpx.HTTPError:
        return fallback_answer(facts, cfg.model, f"Your AI ({cfg.mode}) could not be reached at {cfg.base_url}.")
    try:
        out = AskModelOutput.model_validate(parse_model_json(text))
    except (ExtractionError, ValidationError):
        return fallback_answer(facts, cfg.model, "The model's reply was not in the expected format.")
    return ground(out, facts, cfg.model, question)
