"""What kind of document is this? One short model call before anything is read in full (app/scan_jobs.py).

The answer is a guess the user confirms or changes before the file is routed: receipts, bills and credit notes to
Review, sales invoices to Review as sales (they post to Sales), bank statements to the bank-lines import, anything else
to Needs a look. Nothing is posted on a guess.

The model sees the document's own text when it has one (a PDF's text layer, an email body), else the image, and
returns {kind, confidence, reason} under a strict schema. When it does not answer (or answers nonsense), `by_words`
guesses from the text with code and says so; a CSV is recognised by code alone (accnomos_ledger.bank).
"""

from __future__ import annotations

import base64
import re
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.ai import chain
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError, image_mime, parse_model_json, user_message

Kind = Literal["receipt", "purchase_invoice", "sales_invoice", "bank_statement", "credit_note", "payslip", "other"]
KINDS: tuple[Kind, ...] = (
    "receipt",
    "purchase_invoice",
    "sales_invoice",
    "bank_statement",
    "credit_note",
    "payslip",
    "other",
)
LABELS: dict[str, str] = {
    "receipt": "Receipt",
    "purchase_invoice": "Bill (purchase invoice)",
    "sales_invoice": "Sales invoice",
    "bank_statement": "Bank statement",
    "credit_note": "Credit note",
    "payslip": "Payslip",
    "other": "Something else",
}
TIMEOUT_S = 60.0
TEXT_CHARS = 4000  # the first page's words are plenty to tell a statement from a receipt

SYSTEM_PROMPT = (
    "You sort a small UK business's paperwork for a bookkeeper. Say what kind of document this is. "
    "receipt: a till or card slip for something bought. purchase_invoice: a bill a supplier sent us. "
    "sales_invoice: an invoice we sent a customer (the issuer is our business). bank_statement: a list of bank "
    "transactions with balances. credit_note: a supplier or we credit an earlier invoice. payslip: an employee's pay "
    "slip. other: anything else (letters, quotes, contracts, photos). confidence: your 0-1 estimate. "
    "reason: one short sentence, quoting no amounts. Return only the JSON."
)


class Guess(BaseModel):
    kind: Kind
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(default="", max_length=300)
    by: Literal["ai", "code"] = "ai"


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(KINDS)},
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": ["kind", "confidence", "reason"],
        "additionalProperties": False,
    }


def _prompt(business_name: str | None) -> str:
    ours = f" Our business is called {business_name!r}." if business_name else ""
    return "What kind of document is this?" + ours


async def classify(
    image_bytes: bytes | None,
    mime: str | None,
    cfg: AiConfig,
    *,
    text: str | None = None,
    business_name: str | None = None,
) -> Guess:
    """The model's guess. Text alone when there is text (fast), else the image. Raises `ExtractionError`."""
    text = (text or "").strip()[:TEXT_CHARS] or None
    b64 = None
    if text is None:
        if image_bytes is None:
            raise ExtractionError("Nothing to classify: no image and no text")
        mime = image_mime(mime)
        b64 = base64.b64encode(image_bytes).decode("ascii")
    words = _prompt(business_name)
    sch = schema()

    async def attempt(c: AiConfig) -> str:
        async with httpx.AsyncClient(timeout=c.http_timeout(TIMEOUT_S)) as client:
            if c.mode == "local":
                body: dict[str, Any] = {
                    "model": c.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        user_message(words, b64, None, text, ollama=True),
                    ],
                    "format": sch,
                    "think": False,
                    "stream": False,
                    "options": {"temperature": 0},
                    "keep_alive": "24h",
                }
                r = await client.post(f"{c.base_url}/api/chat", json=body, headers=c.auth_headers())
                r.raise_for_status()
                return r.json().get("message", {}).get("content", "")
            body = {
                "model": c.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    user_message(words, b64, mime, text, ollama=False),
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "kind", "strict": True, "schema": sch},
                },
                "reasoning_effort": "low",
            }
            r = await client.post(f"{c.base_url}/chat/completions", json=body, headers=c.auth_headers())
            r.raise_for_status()
            content = r.json()["choices"][0]["message"].get("content") or ""
            if isinstance(content, list):
                content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
            return content

    try:
        raw, _served = await chain.run(cfg, "classify", attempt, vision=b64 is not None)
    except httpx.HTTPStatusError as exc:
        raise ExtractionError(f"{cfg.mode} backend HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise ExtractionError(f"{cfg.mode} backend did not answer: {type(exc).__name__}") from exc
    except TimeoutError as exc:
        raise ExtractionError(f"{cfg.mode} backend timed out") from exc
    obj = parse_model_json(raw)
    try:
        conf = float(obj.get("confidence", 0))
        obj["confidence"] = min(1.0, max(0.0, conf / 100 if conf > 1 else conf))  # some models answer 85 for 0.85
        return Guess.model_validate({**obj, "by": "ai"})
    except (ValidationError, TypeError, ValueError) as exc:
        raise ExtractionError(f"Model's answer was not a document kind: {exc}", raw=raw) from exc


# --------------------------------------------------------------------------- #
# Code's guess, when the model does not answer
# --------------------------------------------------------------------------- #

_WORDS: tuple[tuple[Kind, tuple[str, ...]], ...] = (  # first match wins
    ("payslip", ("payslip", "pay slip", "net pay", "tax code", "ni number", "national insurance no")),
    (
        "bank_statement",
        ("opening balance", "closing balance", "sort code", "statement of account", "account statement"),
    ),
    ("credit_note", ("credit note", "credit memo")),
    ("purchase_invoice", ("invoice", "amount due", "payment terms", "due date")),
    ("receipt", ("receipt", "change due", "card payment", "contactless", "thank you for shopping", "total")),
)


def by_words(text: str | None, name: str = "", business_name: str | None = None) -> Guess:
    """A low-confidence guess from the document's words (and file name), for when no model answered."""
    hay = f"{name} {text or ''}".lower()
    hay = re.sub(r"\s+", " ", hay)
    for kind, words in _WORDS:
        hit = next((w for w in words if w in hay), None)
        if hit is None:
            continue
        if kind == "purchase_invoice" and business_name and business_name.lower() in hay[:400]:
            kind = "sales_invoice"  # our own name at the top: an invoice we issued
        return Guess(kind=kind, confidence=0.4, reason=f"Guessed from the words (“{hit}”)", by="code")
    return Guess(kind="other", confidence=0.2, reason="No words that say what it is", by="code")
