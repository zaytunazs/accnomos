"""Read a CIS payment and deduction statement, or a subcontractor's reverse-charge invoice, with the user's AI.

Same AI setup and transport as reading receipts (app/ai/extract.py): Glimmer over Ollama in local mode, Muse Spark
over the Meta Model API in key mode, one strict JSON schema, the document's own text passed as data between
markers. The model only reads figures as printed; app/cis.py checks them in code and the user approves before
anything is kept or posted (AI proposes, user approves, code calculates).
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

SYSTEM_PROMPT = (
    "You read UK Construction Industry Scheme (CIS) paperwork for a bookkeeper. Return only the JSON. "
    "kind: cis_statement for a contractor's monthly payment and deduction statement (it names a tax month ending "
    "on the 5th, a gross amount paid, the cost of materials and the amount deducted); reverse_charge_invoice for a "
    "subcontractor's VAT invoice that charges no VAT because the domestic reverse charge applies (it says "
    "'reverse charge', 'section 55A' or 'customer to pay the VAT to HMRC'); other for anything else. "
    "Amounts in pounds to 2 dp exactly as printed; do not correct arithmetic; null when not printed. "
    "Dates as YYYY-MM-DD (UK documents print day first). UTRs are 10 digits; copy them without spaces. "
    "vat_rate is a percentage number (20 or 5). Never invent a figure, a UTR or a VAT number. "
    "confidence: your 0-1 estimate that every field is right."
)
USER_PROMPT = "Read this document."

_STR = {"type": ["string", "null"]}
_NUM = {"type": ["number", "null"]}


def reading_json_schema() -> dict[str, Any]:
    props: dict[str, Any] = {
        "kind": {"type": "string", "enum": ["cis_statement", "reverse_charge_invoice", "other"]},
        "contractor_name": _STR,
        "contractor_ref": _STR,
        "subcontractor_name": _STR,
        "subcontractor_utr": _STR,
        "verification_number": _STR,
        "tax_month_end": _STR,
        "gross_amount": _NUM,
        "materials": _NUM,
        "amount_liable": _NUM,
        "deduction": _NUM,
        "net_paid": _NUM,
        "supplier_name": _STR,
        "supplier_vat_number": _STR,
        "invoice_number": _STR,
        "invoice_date": _STR,
        "net": _NUM,
        "vat_rate": _NUM,
        "reverse_charge_vat": _NUM,
        "reverse_charge_wording": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


class CisReading(BaseModel):
    """What the model read, as printed (pounds). app/cis_readings.py turns it into pence and checks it."""

    kind: Literal["cis_statement", "reverse_charge_invoice", "other"]
    contractor_name: str | None = None
    contractor_ref: str | None = None
    subcontractor_name: str | None = None
    subcontractor_utr: str | None = None
    verification_number: str | None = None
    tax_month_end: str | None = None
    gross_amount: float | None = None
    materials: float | None = None
    amount_liable: float | None = None
    deduction: float | None = None
    net_paid: float | None = None
    supplier_name: str | None = None
    supplier_vat_number: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    net: float | None = None
    vat_rate: float | None = None
    reverse_charge_vat: float | None = None
    reverse_charge_wording: bool = False
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


async def read_cis_document(
    image_bytes: bytes | None, mime: str | None, cfg: AiConfig, *, text: str | None = None
) -> tuple[CisReading, dict[str, Any]]:
    """One strict-JSON call to the user's backend. Raises ExtractionError when it cannot answer."""
    if image_bytes is None and not text:
        raise ExtractionError("Nothing to read: no image and no text")
    b64 = None
    if image_bytes is not None:
        mime = image_mime(mime)
        b64 = base64.b64encode(image_bytes).decode("ascii")
    schema = reading_json_schema()
    ollama = cfg.mode == "local"
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, user_message(USER_PROMPT, b64, mime, text, ollama)]
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S)) as client:
            if ollama:
                r = await client.post(
                    f"{cfg.base_url}/api/chat",
                    json={
                        "model": cfg.model,
                        "messages": messages,
                        "format": schema,
                        "think": False,
                        "stream": False,
                        "options": {"temperature": 0},
                    },
                )
                r.raise_for_status()
                raw = r.json().get("message", {}).get("content", "")
            else:
                r = await client.post(
                    f"{cfg.base_url}/chat/completions",
                    json={
                        "model": cfg.model,
                        "messages": messages,
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {"name": "cis_document", "strict": True, "schema": schema},
                        },
                        "reasoning_effort": "low",
                    },
                    headers={"Authorization": f"Bearer {cfg.api_key}"},
                )
                r.raise_for_status()
                raw = r.json()["choices"][0]["message"].get("content") or ""
                if isinstance(raw, list):
                    raw = "".join(p.get("text", "") for p in raw if isinstance(p, dict))
    except httpx.HTTPStatusError as exc:
        raise ExtractionError(f"{cfg.mode} backend HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise ExtractionError(f"{cfg.mode} backend unreachable: {exc!r}") from exc
    obj = parse_model_json(raw)
    try:
        reading = CisReading.model_validate(obj)
    except ValueError as exc:
        raise ExtractionError(f"Model JSON failed validation: {exc}", raw=raw) from exc
    return reading, {"backend": cfg.mode, "model": cfg.model}
