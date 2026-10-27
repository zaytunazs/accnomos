"""Verifier: a second, independent reading of the same image, compared field by field in code.

The Verifier never sees the Extractor's answer. It gets a different prompt (one plain question
per field) and a different, smaller schema with different key names, so it cannot simply echo
the first reading's shape. Code compares the two; the model never merges or chooses values.

Backend choice (`select_backend`), keeping the user's own choice of where their documents go:

* local mode -> Glimmer via Ollama with the verifier prompt. The image never leaves the machine,
  even when the server has a Baseten key.
* key mode   -> (1) Muse Spark Open on Baseten when the owner set `BASETEN_API_KEY` on the server
  (OpenAI-compatible; model from `VERIFIER_MODEL`, else `BASETEN_MODEL`, else the default slug);
  (2) otherwise the Meta Model API with the user's own key (`X-Meta-Api-Key`).

`VERIFIER=off` on the server disables the verifier entirely.
"""

from __future__ import annotations

import base64
import os
import re
import string
import time
import unicodedata
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.ai.config import AiConfig
from app.ai.extract import SUPPORTED_MIME, ExtractionError, parse_model_json
from app.checks import p
from app.schemas import ExtractedDoc, FieldAgreement, Verification, strict_json_schema

TIMEOUT_S = 180.0
BASETEN_BASE = "https://inference.baseten.co/v1"
DEFAULT_BASETEN_MODEL = "meta-models/muse-spark-open"  # slug not yet confirmed against Baseten's docs

BackendKind = Literal["baseten", "meta", "ollama"]


class VerifierBackend(BaseModel):
    kind: BackendKind
    base_url: str
    model: str
    api_key: str | None = None

    def label(self) -> str:
        return f"{self.kind}:{self.model}"


def select_backend(cfg: AiConfig, env: Mapping[str, str] | None = None) -> VerifierBackend | None:
    """Pick the verifier backend for this request; None when the owner switched it off."""
    env = os.environ if env is None else env
    if (env.get("VERIFIER") or "").strip().lower() in ("off", "0", "false", "no"):
        return None
    if cfg.mode == "local":
        return VerifierBackend(kind="ollama", base_url=cfg.base_url, model=cfg.model)
    baseten_key = (env.get("BASETEN_API_KEY") or "").strip()
    if baseten_key:
        model = env.get("VERIFIER_MODEL") or env.get("BASETEN_MODEL") or DEFAULT_BASETEN_MODEL
        return VerifierBackend(kind="baseten", base_url=BASETEN_BASE, model=model, api_key=baseten_key)
    return VerifierBackend(kind="meta", base_url=cfg.base_url, model=cfg.model, api_key=cfg.api_key)


# --------------------------------------------------------------------------- #
# Prompt and schema (deliberately unlike extract.py's)
# --------------------------------------------------------------------------- #


class VerifierReading(BaseModel):
    seller: str = Field(description="Business that issued the document")
    vat_registration: str | None = Field(
        description="Seller's VAT registration number exactly as printed; null if none"
    )
    issue_date: str = Field(description="YYYY-MM-DD")
    amount_before_vat: float
    vat_amount: float
    amount_payable: float


VERIFIER_SYSTEM_PROMPT = (
    "You are checking a UK receipt or invoice. Answer each question by looking only at what is printed. "
    "Do not calculate or correct anything; copy figures exactly. Reply with the JSON object only.\n"
    "seller: Which business issued this document (the name at the top, or next to the VAT number)?\n"
    "vat_registration: What VAT registration number is printed for that business? null if there is none.\n"
    "issue_date: On what date was it issued? Answer YYYY-MM-DD; UK documents print the day first.\n"
    "amount_before_vat: What total before VAT (net, subtotal ex VAT) is printed? If no VAT is shown, the total.\n"
    "vat_amount: What total VAT amount is printed? 0 if none is shown.\n"
    "amount_payable: What is the final total to pay or paid, including VAT?"
)
VERIFIER_USER_PROMPT = "Answer the questions for this document."

#: Proposal field -> (verifier key, how to compare). All six are decisive: any disagreement needs a look.
FIELD_MAP: dict[str, tuple[str, str]] = {
    "supplier_name": ("seller", "name"),
    "supplier_vat_number": ("vat_registration", "vat_number"),
    "date": ("issue_date", "date"),
    "net_total": ("amount_before_vat", "money"),
    "vat_total": ("vat_amount", "money"),
    "gross_total": ("amount_payable", "money"),
}


# --------------------------------------------------------------------------- #
# Comparison (pure)
# --------------------------------------------------------------------------- #

_LEGAL_SUFFIX = re.compile(r"(\s(ltd|limited|plc|llp|co|company|uk))+$")  # trailing only: "UK Fuels" keeps its "uk"
_PUNCT = str.maketrans({c: " " for c in string.punctuation + "“”–—£"} | {"'": None, "’": None, "‘": None})


def normalise_name(s: str | None) -> str:
    """Case-, accent-, punctuation- and whitespace-insensitive; '&' = 'and';
    legal suffixes (Ltd/Limited/PLC…) dropped.
    """
    if not s:
        return ""
    s = s.replace("&", " and ").translate(_PUNCT)  # before ASCII folding, which would drop curly quotes
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
    s = " ".join(s.split())
    return _LEGAL_SUFFIX.sub("", s).strip()


def vat_digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d %B %Y", "%d %b %Y")


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def money_agree(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(p(a) - p(b)) <= 1


def field_agree(kind: str, a: Any, b: Any) -> bool:
    if kind == "name":
        na, nb = normalise_name(a), normalise_name(b)
        return bool(na) and na == nb
    if kind == "vat_number":
        return vat_digits(a) == vat_digits(b)  # both blank also agree: neither reading saw one
    if kind == "date":
        da, db = parse_date(a), parse_date(b)
        return da is not None and da == db
    if kind == "money":
        return money_agree(a, b)
    raise ValueError(f"unknown comparison {kind!r}")


def compare(
    extracted: ExtractedDoc, reading: VerifierReading, model: str, elapsed_s: float | None = None
) -> Verification:
    fields: dict[str, FieldAgreement] = {}
    for name, (vkey, kind) in FIELD_MAP.items():
        a, b = getattr(extracted, name), getattr(reading, vkey)
        fields[name] = FieldAgreement(extractor=a, verifier=b, agree=field_agree(kind, a, b))
    return Verification(
        fields=fields, agree_all=all(f.agree for f in fields.values()), model=model, elapsed_s=elapsed_s
    )


# --------------------------------------------------------------------------- #
# Model calls
# --------------------------------------------------------------------------- #


async def _call_ollama(client: httpx.AsyncClient, b64: str, be: VerifierBackend, schema: dict[str, Any]) -> str:
    body = {
        "model": be.model,
        "messages": [
            {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": VERIFIER_USER_PROMPT, "images": [b64]},
        ],
        "format": schema,
        "think": False,
        "stream": False,
        "options": {"temperature": 0},
        "keep_alive": "24h",
    }
    r = await client.post(f"{be.base_url}/api/chat", json=body)
    r.raise_for_status()
    return r.json().get("message", {}).get("content", "")


async def _call_openai_compatible(
    client: httpx.AsyncClient, b64: str, mime: str, be: VerifierBackend, schema: dict[str, Any]
) -> str:
    """Meta Model API and Baseten both speak OpenAI chat completions."""
    body: dict[str, Any] = {
        "model": be.model,
        "messages": [
            {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VERIFIER_USER_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "verifier", "strict": True, "schema": schema},
        },
    }
    if be.kind == "meta":
        body["reasoning_effort"] = "low"
    else:
        body["temperature"] = 0
    r = await client.post(
        f"{be.base_url}/chat/completions", json=body, headers={"Authorization": f"Bearer {be.api_key}"}
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"].get("content") or ""
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content


async def read_independently(image_bytes: bytes, mime: str, be: VerifierBackend) -> VerifierReading:
    """Ask the verifier model the field questions. Raises `ExtractionError`."""
    mime = mime.lower().split(";")[0].strip().replace("image/jpg", "image/jpeg")
    if mime not in SUPPORTED_MIME:
        raise ExtractionError(f"Unsupported image type {mime!r}")
    b64 = base64.b64encode(image_bytes).decode("ascii")
    schema = strict_json_schema(VerifierReading)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S)) as client:
            if be.kind == "ollama":
                text = await _call_ollama(client, b64, be, schema)
            else:
                text = await _call_openai_compatible(client, b64, mime, be, schema)
    except httpx.HTTPStatusError as exc:
        raise ExtractionError(f"verifier {be.kind} HTTP {exc.response.status_code}: {exc.response.text[:300]}") from exc
    except httpx.HTTPError as exc:
        raise ExtractionError(f"verifier {be.kind} unreachable: {exc!r}") from exc
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:  # 200 with an unexpected body
        raise ExtractionError(f"verifier {be.kind} returned an unexpected response: {exc!r}") from exc
    try:
        return VerifierReading.model_validate(parse_model_json(text))
    except ValidationError as exc:
        raise ExtractionError(f"Verifier JSON failed validation: {exc}", raw=text) from exc


async def verify(
    image_bytes: bytes,
    extracted: ExtractedDoc,
    cfg: AiConfig,
    *,
    mime: str = "image/jpeg",
    env: Mapping[str, str] | None = None,
) -> Verification | None:
    """Independent second reading compared field by field. None when the verifier is switched off.

    Never raises for model/network trouble: returns a `Verification` with `error` set and
    `agree_all=False`, so the UI never claims agreement it did not see.
    """
    be = select_backend(cfg, env)
    if be is None:
        return None
    t0 = time.perf_counter()
    try:
        reading = await read_independently(image_bytes, mime, be)
    except ExtractionError as exc:
        return Verification(fields={}, agree_all=False, model=be.label(), error=str(exc)[:500])
    return compare(extracted, reading, be.label(), elapsed_s=round(time.perf_counter() - t0, 3))
