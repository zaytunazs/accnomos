"""Read a landlord's letting paperwork with the user's AI: a letting agent's statement, a bill for work on the
let property (an invoice), a landlord insurance schedule, or a mortgage statement.

Same AI setup and transport as reading receipts (app/ai/extract.py) and CIS documents (app/ai/cis_read.py):
Glimmer over Ollama in local mode, Muse Spark over the Meta Model API in key mode, one strict JSON schema, the
document's own text passed as data between markers. The model only reads figures as printed; app/property_readings.py
fits them into pence, matches the property by code and checks them, and the user approves before anything is kept or
posted (AI proposes, user approves, code calculates).
"""

from __future__ import annotations

import base64
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from app.ai.config import AiConfig
from app.ai.extract import TIMEOUT_S, ExtractionError, image_mime, parse_model_json, user_message
from app.property import BY_KEY

CATEGORIES = sorted(BY_KEY)

SYSTEM_PROMPT = (
    "You read UK landlord paperwork for a bookkeeper. Return only the JSON. "
    "kind: letting_statement for a letting agent's statement for one property and one period (rent received, "
    "the agent's fee, VAT on the fee, repairs deducted, the payout to the landlord); invoice for a bill for work "
    "on a let property (a repair, gas safety, replacement appliances, ground rent, a service charge); insurance "
    "for a landlord insurance schedule or premium notice; mortgage_statement for a mortgage statement naming "
    "payments made with an interest and capital split; other for anything else. "
    "Copy the document date as date (YYYY-MM-DD; UK documents print day first), the period it covers as "
    "period_start and period_end (null when not printed), the counterparty (the agent, insurer, lender or "
    "supplier), and the address of the let property as property_text, copied exactly as printed (never an id; "
    "null when no property address is printed). "
    "List every money line as printed in lines: description, then category, one of: " + ", ".join(CATEGORIES) + ". "
    "Rent received is rents; an agent or management fee (with its VAT) is professional; repairs and maintenance "
    "is repairs; gas safety and other certificates are other; ground rent and service charges are premises; "
    "landlord insurance is premises; mortgage interest is finance_res; replacing furniture, appliances or "
    "kitchenware like for like is domestic_items. "
    "amount in pounds to 2 dp exactly as printed, with the printed sign (fees and deductions are negative); "
    "vat: the VAT on the line when shown separately, else null. "
    "info: true for a headline or breakdown line that would double-count (the payout to the landlord on a "
    "statement; a printed Total when the parts are listed; an `of which` line such as the Insurance Premium "
    "Tax inside a premium, or the payments-made headline when the interest and capital split is listed); "
    "otherwise false. "
    "capital: true only for a line that repays capital (mortgage capital, loan principal), never an expense; "
    "otherwise false. "
    "replacement: true when the document shows the line replaces an item already in the let property; "
    "otherwise false. "
    "total: the headline total as printed (the payout to the landlord on a statement; Total, payments made or "
    "the premium on a bill); null when none is printed. Do not correct arithmetic. "
    "Never invent a figure, an address or a category. confidence: your 0-1 estimate that every field is right."
)
USER_PROMPT = "Read this document."
RETRY_PROMPT = "Your last reply was not valid JSON against the schema. Return only the JSON object, nothing else."

_STR = {"type": ["string", "null"]}
_NUM = {"type": ["number", "null"]}


def reading_json_schema() -> dict[str, Any]:
    line: dict[str, Any] = {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "category": {"type": "string", "enum": CATEGORIES},
            "amount": {"type": "number"},
            "vat": _NUM,
            "capital": {"type": "boolean"},
            "info": {"type": "boolean"},
            "replacement": {"type": "boolean"},
        },
        "required": ["description", "category", "amount", "vat", "capital", "info", "replacement"],
        "additionalProperties": False,
    }
    props: dict[str, Any] = {
        "kind": {
            "type": "string",
            "enum": ["letting_statement", "insurance", "mortgage_statement", "invoice", "other"],
        },
        "date": _STR,
        "period_start": _STR,
        "period_end": _STR,
        "counterparty": _STR,
        "property_text": _STR,
        "lines": {"type": "array", "items": line},
        "total": _NUM,
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


class PropertyLine(BaseModel):
    """One money line as printed (pounds). app/property_readings.py turns it into pence and checks it."""

    description: str = ""
    category: str = ""
    amount: float | None = None
    vat: float | None = None
    capital: bool = False
    info: bool = False
    replacement: bool = False


class PropertyReading(BaseModel):
    """What the model read, as printed (pounds). app/property_readings.py turns it into pence and checks it."""

    kind: Literal["letting_statement", "insurance", "mortgage_statement", "invoice", "other"]
    date: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    counterparty: str | None = None
    property_text: str | None = None
    lines: list[PropertyLine] = Field(default_factory=list)
    total: float | None = None
    confidence: float = Field(0, ge=0, le=1)


def to_pence(pounds: float | None) -> int | None:
    """Pounds as printed to integer pence (half up), or None. Floats from JSON go through their shortest repr."""
    if pounds is None:
        return None
    try:
        return int((Decimal(repr(pounds)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None


def to_date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


async def _post(messages: list[dict[str, Any]], cfg: AiConfig) -> str:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S)) as client:
            if cfg.mode == "local":
                r = await client.post(
                    f"{cfg.base_url}/api/chat",
                    json={
                        "model": cfg.model,
                        "messages": messages,
                        "format": reading_json_schema(),
                        "think": False,
                        "stream": False,
                        "options": {"temperature": 0},
                    },
                )
                r.raise_for_status()
                return r.json().get("message", {}).get("content", "")
            r = await client.post(
                f"{cfg.base_url}/chat/completions",
                json={
                    "model": cfg.model,
                    "messages": messages,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "property_document", "strict": True, "schema": reading_json_schema()},
                    },
                    "reasoning_effort": "low",
                },
                headers={"Authorization": f"Bearer {cfg.api_key}"},
            )
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"].get("content") or ""
            if isinstance(raw, list):
                raw = "".join(p.get("text", "") for p in raw if isinstance(p, dict))
            return raw
    except httpx.HTTPStatusError as exc:
        raise ExtractionError(f"{cfg.mode} backend HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise ExtractionError(f"{cfg.mode} backend unreachable: {exc!r}") from exc


def _validate(raw: str) -> PropertyReading:
    obj = parse_model_json(raw)
    try:
        return PropertyReading.model_validate(obj)
    except ValueError as exc:
        raise ExtractionError(f"Model JSON failed validation: {exc}", raw=raw) from exc


async def read_property_document(
    image_bytes: bytes | None, mime: str | None, cfg: AiConfig, *, text: str | None = None
) -> tuple[PropertyReading, dict[str, Any]]:
    """One strict-JSON call to the user's backend, asked once more when the first reply is not valid JSON.

    Raises ExtractionError when it cannot answer.
    """
    if image_bytes is None and not text:
        raise ExtractionError("Nothing to read: no image and no text")
    b64 = None
    if image_bytes is not None:
        mime = image_mime(mime)
        b64 = base64.b64encode(image_bytes).decode("ascii")
    ollama = cfg.mode == "local"
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, user_message(USER_PROMPT, b64, mime, text, ollama)]
    raw = await _post(messages, cfg)
    try:
        return _validate(raw), {"backend": cfg.mode, "model": cfg.model}
    except ExtractionError:
        messages = [*messages, {"role": "assistant", "content": raw}, {"role": "user", "content": RETRY_PROMPT}]
        return _validate(await _post(messages, cfg)), {"backend": cfg.mode, "model": cfg.model}
