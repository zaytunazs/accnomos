"""Read one receipt/invoice image into an `ExtractedDoc`.

Two backends share one prompt and one strict JSON schema:

* local -> Ollama native `/api/chat`, `images` = raw base64, `format` = schema OBJECT
  (`format: "json"` with an image returns `{}`).
* key   -> Meta Model API `/chat/completions` (OpenAI-compatible), image as a data
  URL, `response_format` json_schema strict, `reasoning_effort: low`, no tool_choice.
"""

from __future__ import annotations

import base64
import json
import re
import time
from typing import Any

import httpx
from pydantic import ValidationError

from app.ai.config import AiConfig
from app.schemas import CATEGORIES, CODE_CATEGORIES, ExtractedDoc, extraction_json_schema

TIMEOUT_S = 180.0
SUPPORTED_MIME = {"image/jpeg", "image/png", "image/webp"}

SYSTEM_PROMPT = (
    "You read UK receipts and invoices for a bookkeeper. Return only the JSON. "
    "Amounts in pounds (or the printed currency) to 2 dp exactly as printed; do not correct "
    "arithmetic. vat_rate is a percentage number (20, 5 or 0), never a fraction. "
    "If VAT is not shown use 0 and vat_rate null; never invent a VAT number. "
    "If line prices include VAT, net = price minus its VAT. Date as YYYY-MM-DD (UK receipts "
    "print day first). doc_type: receipt (till/card slip), purchase_invoice (bill to us), "
    "sales_invoice (we bill a customer). card_last4 only if printed. "
    "category_guess from this list: " + "; ".join(CATEGORIES) + ". "
    "confidence: your 0-1 estimate that every field is right."
)
USER_PROMPT = "Extract this document."


class ExtractionError(RuntimeError):
    """The model call failed or returned something we cannot parse/validate."""

    def __init__(self, message: str, raw: str | None = None) -> None:
        super().__init__(message)
        self.raw = raw


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_model_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating fences and chatter."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ExtractionError("Model output contained no JSON object", raw=text) from None
        try:
            obj = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ExtractionError(f"Model JSON did not parse: {exc}", raw=text) from exc
    if not isinstance(obj, dict) or not obj:
        raise ExtractionError("Model returned an empty or non-object JSON value", raw=text)
    return obj


async def _call_ollama(
    client: httpx.AsyncClient, b64: str, cfg: AiConfig, schema: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    body = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT, "images": [b64]},
        ],
        "format": schema,
        "think": False,
        "stream": False,
        "options": {"temperature": 0},
        "keep_alive": "24h",
    }
    r = await client.post(f"{cfg.base_url}/api/chat", json=body)
    r.raise_for_status()
    data = r.json()
    usage = {
        "prompt_tokens": data.get("prompt_eval_count"),
        "completion_tokens": data.get("eval_count"),
        "total_duration_s": (data.get("total_duration") or 0) / 1e9,
    }
    return data.get("message", {}).get("content", ""), usage


async def _call_meta(
    client: httpx.AsyncClient, b64: str, mime: str, cfg: AiConfig, schema: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    body = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": USER_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "receipt", "strict": True, "schema": schema},
        },
        "reasoning_effort": "low",  # temperature deliberately omitted (not in verified API facts)
    }
    headers = {"Authorization": f"Bearer {cfg.api_key}"}
    r = await client.post(f"{cfg.base_url}/chat/completions", json=body, headers=headers)
    r.raise_for_status()
    data = r.json()
    content = data["choices"][0]["message"].get("content") or ""
    if isinstance(content, list):  # some OpenAI-compatible servers return parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content, data.get("usage") or {}


def normalise_rates(obj: dict) -> None:
    """Models sometimes return VAT rates as fractions (0.2) rather than percentages (20). Fix in place."""
    for line in obj.get("lines") or []:
        if not isinstance(line, dict):
            continue
        rate = line.get("vat_rate")
        if isinstance(rate, (int, float)) and 0 < rate < 1:
            line["vat_rate"] = round(rate * 100, 2)


async def extract_document(image_bytes: bytes, mime: str, cfg: AiConfig) -> tuple[ExtractedDoc, dict[str, Any]]:
    """Run the configured vision model; return the validated doc and call metadata.

    Metadata keys: backend, model, elapsed_s, usage, raw (model text).
    Raises `ExtractionError` on unsupported type, HTTP failure or bad output.
    """
    mime = mime.lower().split(";")[0].strip()
    if mime == "image/jpg":
        mime = "image/jpeg"
    if mime not in SUPPORTED_MIME:
        raise ExtractionError(f"Unsupported image type {mime!r}; send JPEG, PNG or WebP")

    b64 = base64.b64encode(image_bytes).decode("ascii")
    schema = extraction_json_schema()
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S)) as client:
            if cfg.mode == "local":
                text, usage = await _call_ollama(client, b64, cfg, schema)
            else:
                text, usage = await _call_meta(client, b64, mime, cfg, schema)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        raise ExtractionError(f"{cfg.mode} backend HTTP {exc.response.status_code}: {detail}") from exc
    except httpx.HTTPError as exc:
        raise ExtractionError(f"{cfg.mode} backend unreachable: {exc!r}") from exc
    elapsed = time.perf_counter() - t0

    obj = parse_model_json(text)
    normalise_rates(obj)
    if obj.get("category_guess") in CODE_CATEGORIES:  # only code writes these (e.g. the mileage allowance)
        obj["category_guess"] = "Sundry"
    try:
        doc = ExtractedDoc.model_validate(obj)
    except ValidationError as exc:
        raise ExtractionError(f"Model JSON failed validation: {exc}", raw=text) from exc

    meta = {
        "backend": cfg.mode,
        "model": cfg.model,
        "elapsed_s": round(elapsed, 3),
        "usage": usage,
        "raw": text,
    }
    return doc, meta
