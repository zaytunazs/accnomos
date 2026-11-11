"""Verifier: a second, independent reading of the same image (and text, for a PDF or an email), compared field by
field in code.

The Verifier never sees the Extractor's answer. It gets a different prompt (one plain question
per field) and a different, smaller schema with different key names, so it cannot simply echo
the first reading's shape. Code compares the two; the model never merges or chooses values.

Backend choice (`select_backend`), keeping the user's own choice of where their documents go:

* local mode -> Glimmer via the local model server with the verifier prompt. The image never leaves the machine,
  even when the server has a hosted-verifier key.
* key mode   -> the Meta Model API with the user's own key (`X-Meta-Api-Key`); Muse Spark Open (hosted open
  weights) first only when the owner switched it on (`BASETEN_ENABLED=1` and `BASETEN_API_KEY`; model from
  `VERIFIER_MODEL`, else `BASETEN_MODEL`, else the default slug).
* the server's chain (AI_PROVIDERS, app/ai/providers.py) -> the chain's providers in order (Meta Model API, our
  own server), with the same failover and circuit breaker as every other call (app/ai/chain.py). The hosted Spark Open
  goes first only with `BASETEN_ENABLED=1` and a key; it is off by default (owner's decision, 2 Nov 2026).

`VERIFIER_PROVIDER` (the server's chain only) picks who reads second:

* chain (default) - the chain's own order (with AI_PROVIDERS=spark,anthropic: Glimmer on our own server, Anthropic
  when it is down). The reader and the Verifier are then usually the same model, which is less independent, but every
  document stays on our own server whenever it is up: the promise the privacy page makes.
* anthropic       - Anthropic first (ANTHROPIC_VERIFY_MODEL, else ANTHROPIC_MODEL), the rest of the chain after it.
  A different model from the Glimmer reader, so a truly independent second reading, but EVERY document then goes to
  Anthropic and costs one Messages API call: switch it on only together with privacy text that says so.
* spark           - our own server first, the rest of the chain after it (useful when the reader is Anthropic).

A provider that is not configured is skipped (falling back to the chain's order). A backend the user chose is
unaffected: their own local agent or key stays their verifier.

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

from app.ai import anthropic, chain
from app.ai.config import AiConfig, is_test_mode
from app.ai.extract import ExtractionError, image_mime, parse_model_json, user_message
from app.checks import p
from app.schemas import ExtractedDoc, FieldAgreement, Verification, strict_json_schema

TIMEOUT_S = 180.0
BASETEN_BASE = "https://inference.baseten.co/v1"
DEFAULT_BASETEN_MODEL = "meta-models/muse-spark-open"  # as Baseten's /v1/models lists it (checked 27 Oct 2026)

BackendKind = Literal["baseten", "meta", "ollama", "anthropic"]
VerifierProvider = Literal["chain", "anthropic", "spark"]


class VerifierBackend(BaseModel):
    kind: BackendKind
    base_url: str
    model: str
    api_key: str | None = None
    src: AiConfig | None = Field(default=None, exclude=True, repr=False)  # timeouts and auth headers, in the chain

    def label(self) -> str:
        return f"{self.kind}:{self.model}"


def baseten_key(env: Mapping[str, str]) -> str | None:
    """The Baseten key, only when the owner also switched Baseten on (`BASETEN_ENABLED=1`; off by default)."""
    if (env.get("BASETEN_ENABLED") or "").strip().lower() not in ("1", "true", "yes", "on"):
        return None
    return (env.get("BASETEN_API_KEY") or "").strip() or None


def _baseten(env: Mapping[str, str], in_chain: bool) -> AiConfig | None:
    key = baseten_key(env)
    if not key:
        return None
    model = env.get("VERIFIER_MODEL") or env.get("BASETEN_MODEL") or DEFAULT_BASETEN_MODEL
    return AiConfig(
        mode="key",
        base_url=BASETEN_BASE,
        model=model,
        api_key=key,
        provider="baseten",
        in_chain=in_chain,
        connect_s=10.0 if in_chain else 15.0,
        first_token_s=90.0 if in_chain else None,
        request_s=120.0 if in_chain else None,
    )


def backend_for(c: AiConfig) -> VerifierBackend:
    """The verifier backend that one provider config stands for."""
    kind: BackendKind
    if c.mode == "local":
        kind = "ollama"
    elif c.provider == "baseten":
        kind = "baseten"
    elif anthropic.is_anthropic(c):
        kind = "anthropic"
    else:
        kind = "meta"
    return VerifierBackend(kind=kind, base_url=c.base_url, model=c.model, api_key=c.api_key, src=c)


def verifier_provider(env: Mapping[str, str]) -> VerifierProvider:
    raw = (env.get("VERIFIER_PROVIDER") or "chain").strip().lower()
    return raw if raw in ("chain", "anthropic", "spark") else "chain"  # type: ignore[return-value]


def _first(providers: list[AiConfig], name: str, env: Mapping[str, str]) -> list[AiConfig]:
    """`providers` with `name` moved to the front (built from the environment when the chain lacks it), or unchanged
    when that provider is not configured. The Anthropic Verifier uses ANTHROPIC_VERIFY_MODEL when it is set."""
    from app.ai import providers as prov  # late: providers imports config, which this module's callers import

    pick = next((c for c in providers if c.provider == name), None)
    if pick is None and not is_test_mode():
        pick = prov.provider_config(name, env)  # type: ignore[arg-type]
    if pick is None:
        return providers
    if name == "anthropic" and anthropic.is_anthropic(pick) and (vm := anthropic.verify_model(env)):
        pick = pick.model_copy(update={"model": vm})
    rest = [c.model_copy(update={"fallbacks": []}) for c in providers if c.provider != name]
    return [pick.model_copy(update={"fallbacks": []}), *rest]


def verifier_chain(cfg: AiConfig, env: Mapping[str, str] | None = None) -> AiConfig | None:
    """The verifier's providers as one config (first, then fallbacks); None when the owner switched it off."""
    env = os.environ if env is None else env
    if (env.get("VERIFIER") or "").strip().lower() in ("off", "0", "false", "no"):
        return None
    if cfg.in_chain:
        providers = cfg.chain()
        if (who := verifier_provider(env)) != "chain":
            providers = _first(providers, who, env)
        if (baseten := _baseten(env, in_chain=True)) is not None:
            providers = [baseten, *providers]
        head, *rest = providers
        return head.model_copy(update={"fallbacks": rest})
    if cfg.mode == "local":
        return cfg
    return _baseten(env, in_chain=False) or cfg


def select_backend(cfg: AiConfig, env: Mapping[str, str] | None = None) -> VerifierBackend | None:
    """Pick the (first) verifier backend for this request; None when the owner switched it off."""
    env = os.environ if env is None else env
    if (env.get("VERIFIER") or "").strip().lower() in ("off", "0", "false", "no"):
        return None
    if cfg.in_chain:
        vc = verifier_chain(cfg, env)
        return backend_for(vc) if vc is not None else None
    if cfg.mode == "local":
        return VerifierBackend(kind="ollama", base_url=cfg.base_url, model=cfg.model)
    if key := baseten_key(env):
        model = env.get("VERIFIER_MODEL") or env.get("BASETEN_MODEL") or DEFAULT_BASETEN_MODEL
        return VerifierBackend(kind="baseten", base_url=BASETEN_BASE, model=model, api_key=key)
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


async def _call_ollama(
    client: httpx.AsyncClient, b64: str | None, be: VerifierBackend, schema: dict[str, Any], text: str | None = None
) -> str:
    body = {
        "model": be.model,
        "messages": [
            {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
            user_message(VERIFIER_USER_PROMPT, b64, None, text, ollama=True),
        ],
        "format": schema,
        "think": False,
        "stream": False,
        "options": {"temperature": 0},
        "keep_alive": "24h",
    }
    r = await client.post(f"{be.base_url}/api/chat", json=body, headers=be.src.auth_headers() if be.src else {})
    r.raise_for_status()
    return r.json().get("message", {}).get("content", "")


async def _call_openai_compatible(
    client: httpx.AsyncClient,
    b64: str | None,
    mime: str | None,
    be: VerifierBackend,
    schema: dict[str, Any],
    text: str | None = None,
) -> str:
    """Meta Model API and Baseten both speak OpenAI chat completions."""
    body: dict[str, Any] = {
        "model": be.model,
        "messages": [
            {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
            user_message(VERIFIER_USER_PROMPT, b64, mime, text, ollama=False),
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "verifier", "strict": True, "schema": schema},
        },
    }
    if be.kind in ("meta", "anthropic"):
        body["reasoning_effort"] = "low"
    else:
        body["temperature"] = 0
    headers = {**(be.src.extra_headers if be.src else {}), "Authorization": f"Bearer {be.api_key}"}
    r = await (
        anthropic.post_chat(client, be.src, body)
        if be.kind == "anthropic" and be.src is not None
        else client.post(f"{be.base_url}/chat/completions", json=body, headers=headers)
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"].get("content") or ""
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content


async def read_independently(
    image_bytes: bytes | None, mime: str | None, be: VerifierBackend, *, text: str | None = None
) -> VerifierReading:
    """Ask the verifier model the field questions about the image, its text, or both. Raises `ExtractionError`."""
    if image_bytes is None and not text:
        raise ExtractionError("Nothing to read: no image and no text")
    b64 = None
    if image_bytes is not None:
        mime = image_mime(mime)
        b64 = base64.b64encode(image_bytes).decode("ascii")
    schema = strict_json_schema(VerifierReading)
    timeout = be.src.http_timeout(TIMEOUT_S) if be.src else httpx.Timeout(TIMEOUT_S)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if be.kind == "ollama":
                answer = await _call_ollama(client, b64, be, schema, text)
            else:
                answer = await _call_openai_compatible(client, b64, mime, be, schema, text)
    except httpx.HTTPStatusError as exc:
        raise ExtractionError(f"verifier {be.kind} HTTP {exc.response.status_code}: {exc.response.text[:300]}") from exc
    except httpx.HTTPError as exc:
        raise ExtractionError(f"verifier {be.kind} unreachable: {exc!r}") from exc
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:  # 200 with an unexpected body
        raise ExtractionError(f"verifier {be.kind} returned an unexpected response: {exc!r}") from exc
    try:
        return VerifierReading.model_validate(parse_model_json(answer))
    except ValidationError as exc:
        raise ExtractionError(f"Verifier JSON failed validation: {exc}", raw=answer) from exc


async def verify(
    image_bytes: bytes | None,
    extracted: ExtractedDoc,
    cfg: AiConfig,
    *,
    mime: str | None = "image/jpeg",
    env: Mapping[str, str] | None = None,
    text: str | None = None,
) -> Verification | None:
    """Independent second reading compared field by field. None when the verifier is switched off.

    Never raises for model/network trouble: returns a `Verification` with `error` set and
    `agree_all=False`, so the UI never claims agreement it did not see.
    """
    vcfg = verifier_chain(cfg, env)
    if vcfg is None:
        return None

    async def attempt(c: AiConfig) -> VerifierReading:
        be = backend_for(c)
        try:
            if text is None:
                return await read_independently(image_bytes, mime, be)
            return await read_independently(image_bytes, mime, be, text=text)
        except ExtractionError as exc:
            if exc.__cause__ is not None and chain.fails_over(exc.__cause__):
                raise chain.ProviderDown(str(exc)) from exc.__cause__  # the next provider may answer
            raise

    t0 = time.perf_counter()
    try:
        reading, served = await chain.run(vcfg, "verify", attempt, vision=image_bytes is not None)
    except (ExtractionError, chain.ProviderDown, TimeoutError) as exc:
        label = backend_for(vcfg).label()
        return Verification(fields={}, agree_all=False, model=label, error=(str(exc) or "timed out")[:500])
    label = f"{backend_for(_served_cfg(vcfg, served.provider)).kind}:{served.model}"
    v = compare(extracted, reading, label, elapsed_s=round(time.perf_counter() - t0, 3))
    return v.model_copy(update={"served_by": served})


def _served_cfg(vcfg: AiConfig, provider: str) -> AiConfig:
    return next((c for c in vcfg.chain() if (c.provider or c.mode) == provider), vcfg)
