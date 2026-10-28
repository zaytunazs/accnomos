"""The model's view on one group of possible duplicate contacts.

Same AI setup as reading documents (app/ai/extract.py): Glimmer over Ollama in
local mode, Muse Spark over the Meta Model API in key mode, one strict JSON
schema. The answer is advisory only: code finds the candidates, the user
approves, and code merges. Groups with a different VAT number on each side
never reach the model: code rules those out itself.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.ai import chain
from app.ai.config import AiConfig
from app.ai.extract import TIMEOUT_S, ExtractionError, parse_model_json

SYSTEM_PROMPT = (
    "You judge whether contact-book entries are the same UK business. Return only the JSON. "
    "The entries arrive with what code already found (shared email, phone, VAT number, close names). "
    "Same means one business trading under two entries (a branch, an old name, a spelling); different "
    "means two businesses that happen to share a word or a domain. "
    "keep_name is the full trading name the merged contact should keep (one of the names given). "
    "reason is one short sentence for the card, naming the deciding evidence. "
    "confidence is your 0-1 estimate that same is right."
)


def judgement_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "same": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "keep_name": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["same", "confidence", "keep_name", "reason"],
        "additionalProperties": False,
    }


class JudgementError(RuntimeError):
    """The model call failed or returned something unusable; the card shows the code evidence alone."""


def judgement_prompt(names: list[dict[str, Any]], evidence: list[str]) -> str:
    lines = ["CONTACTS:"]
    for i, c in enumerate(names, 1):
        bits = [f"kind {c.get('kind')}", f"VAT {c.get('vrn') or 'none'}"]
        for k in ("email", "phone", "address"):
            if c.get(k):
                bits.append(f"{k} {c[k]}")
        lines.append(f'{i}. "{c.get("name")}" ({", ".join(bits)})')
    lines.append("CODE EVIDENCE:")
    lines.extend(f"- {e}" for e in evidence)
    lines.append("Are these the same business?")
    return "\n".join(lines)


async def judge_duplicate(contacts: list[dict[str, Any]], evidence: list[str], cfg: AiConfig) -> dict[str, Any]:
    """Ask the user's model about one candidate group; return the validated `{same, confidence,
    keep_name, reason}` view. Raises `JudgementError` when the model cannot answer."""
    from app.contacts import DuplicateAI  # late: app.contacts owns the model; this module only fills it

    prompt = judgement_prompt(contacts, evidence)
    schema = judgement_json_schema()

    async def attempt(c: AiConfig) -> str:
        async with httpx.AsyncClient(timeout=c.http_timeout(TIMEOUT_S)) as client:
            if c.mode == "local":
                r = await client.post(
                    f"{c.base_url}/api/chat",
                    json={
                        "model": c.model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        "format": schema,
                        "think": False,
                        "stream": False,
                        "options": {"temperature": 0},
                        "keep_alive": "24h",
                    },
                    headers=c.auth_headers(),
                )
                r.raise_for_status()
                return r.json().get("message", {}).get("content", "")
            else:
                r = await client.post(
                    f"{c.base_url}/chat/completions",
                    json={
                        "model": c.model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {"name": "duplicate", "strict": True, "schema": schema},
                        },
                        "reasoning_effort": "low",
                    },
                    headers=c.auth_headers(),
                )
                r.raise_for_status()
                data = r.json()
                text = data["choices"][0]["message"].get("content") or ""
                if isinstance(text, list):
                    text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
                return text

    try:
        text, _ = await chain.run(cfg, "duplicate", attempt)
    except httpx.HTTPError as exc:
        raise JudgementError(f"{cfg.mode} backend unreachable: {exc!r}") from exc
    try:
        view = DuplicateAI.model_validate(parse_model_json(text))
    except (ValueError, ExtractionError) as exc:
        raise JudgementError(f"Model judgement did not parse: {exc}") from exc
    return view.model_dump()
