"""The server's AI provider chain (AI_PROVIDERS), so no AI call depends on one machine.

    AI_PROVIDERS=modal,meta,spark      # the recommended production order

Every provider serves a Meta model (a judging requirement, and the product's promise):

* modal -> Muse Glimmer 30B on Modal (tools/modal_glimmer.py: Ollama on an L40S behind a Modal web endpoint).
           MODAL_GLIMMER_URL (the endpoint, e.g. https://<workspace>--accnomos-glimmer-serve.us-east.modal.run),
           MODAL_MODEL (default muse-glimmer:30b), and, when the endpoint is deployed with proxy auth
           (MODAL_PROXY_AUTH=1 in tools/modal_glimmer.py), MODAL_PROXY_TOKEN_ID + MODAL_PROXY_TOKEN_SECRET.
* meta  -> Muse Spark on the Meta Model API with the server's key: META_API_KEY, MODEL_API_BASE, MODEL_API_MODEL.
* spark -> Muse Glimmer 30B on the owner's DGX Spark (Ollama): OLLAMA_BASE, OLLAMA_MODEL. The last resort.

A provider without its settings (no URL, no key) is left out of the chain and shown as "not configured".
Timeouts per provider, in seconds: <NAME>_CONNECT_S, <NAME>_FIRST_TOKEN_S (the longest wait for a reply to start,
which covers a Modal cold start), <NAME>_REQUEST_S (the longest one attempt may take in all); NAME is MODAL, META or
SPARK. Test mode keeps the chain's names and order but points every provider at the stub AI.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel

from app.ai.config import (
    DEFAULT_MODEL_API_BASE,
    DEFAULT_MODEL_API_MODEL,
    DEFAULT_OLLAMA_BASE,
    DEFAULT_OLLAMA_MODEL,
    TEST_AI_MODEL,
    AiConfig,
    is_test_mode,
    stub_ai_base,
)

ProviderName = Literal["modal", "meta", "spark"]
KNOWN: tuple[ProviderName, ...] = ("modal", "meta", "spark")
RECOMMENDED = "modal,meta,spark"

#: (connect, first token, whole request) seconds by default. Modal: a cold start loads ~18 GB from a volume (60-120 s).
DEFAULT_TIMEOUTS: dict[str, tuple[float, float, float]] = {
    "modal": (10.0, 150.0, 240.0),
    "meta": (10.0, 90.0, 120.0),
    "spark": (5.0, 180.0, 200.0),
}

LABELS: dict[str, str] = {
    "modal": "Modal",
    "meta": "Meta Model API",
    "spark": "DGX Spark",
    "local": "your machine",
    "key": "your Meta key",
    "test": "test stub",
}


class ProviderInfo(BaseModel):
    """What /health and /ai/health may show about a provider: never a key, token or URL."""

    name: str
    label: str
    model: str
    configured: bool
    vision: bool
    json_mode: bool
    voice: bool
    why_not: str | None = None  # what is missing when not configured


def chain_names(env: Mapping[str, str] | None = None) -> list[ProviderName]:
    """AI_PROVIDERS in order, known names only, each once. Empty when unset."""
    env = os.environ if env is None else env
    out: list[ProviderName] = []
    for raw in (env.get("AI_PROVIDERS") or "").split(","):
        name = raw.strip().lower()
        if name in KNOWN and name not in out:
            out.append(name)  # type: ignore[arg-type]
    return out


def unknown_names(env: Mapping[str, str] | None = None) -> list[str]:
    env = os.environ if env is None else env
    return [
        n.strip() for n in (env.get("AI_PROVIDERS") or "").split(",") if n.strip() and n.strip().lower() not in KNOWN
    ]


def _seconds(env: Mapping[str, str], name: str) -> tuple[float, float, float]:
    base = DEFAULT_TIMEOUTS[name]
    out = []
    for i, what in enumerate(("CONNECT_S", "FIRST_TOKEN_S", "REQUEST_S")):
        raw = env.get(f"{name.upper()}_{what}")
        try:
            out.append(float(raw) if raw else base[i])
        except ValueError:
            out.append(base[i])
    return out[0], out[1], out[2]


def provider_config(name: ProviderName, env: Mapping[str, str] | None = None) -> AiConfig | None:
    """One provider's config from the environment, or None when it is not configured."""
    env = os.environ if env is None else env
    connect, first, total = _seconds(env, name)
    common = {"provider": name, "connect_s": connect, "first_token_s": first, "request_s": total, "in_chain": True}
    if name == "modal":
        url = (env.get("MODAL_GLIMMER_URL") or "").strip()
        if not url:
            return None
        headers = {}
        tid, secret = (
            (env.get("MODAL_PROXY_TOKEN_ID") or "").strip(),
            (env.get("MODAL_PROXY_TOKEN_SECRET") or "").strip(),
        )
        if tid and secret:
            headers = {"Modal-Key": tid, "Modal-Secret": secret}
        return AiConfig(
            mode="local",
            base_url=url.rstrip("/"),
            model=env.get("MODAL_MODEL") or DEFAULT_OLLAMA_MODEL,
            extra_headers=headers,
            **common,
        )
    if name == "meta":
        key = (env.get("META_API_KEY") or "").strip()
        if not key:
            return None
        return AiConfig(
            mode="key",
            base_url=(env.get("MODEL_API_BASE") or DEFAULT_MODEL_API_BASE).rstrip("/"),
            model=env.get("MODEL_API_MODEL") or DEFAULT_MODEL_API_MODEL,
            api_key=key,
            voice=True,
            **common,
        )
    return AiConfig(
        mode="local",
        base_url=(env.get("OLLAMA_BASE") or DEFAULT_OLLAMA_BASE).rstrip("/"),
        model=env.get("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL,
        **common,
    )


def _test_config(name: ProviderName) -> AiConfig:
    """Test mode: the provider's name and place in the chain, but the stub AI behind it. ACCNOMOS_TEST_AI_DOWN lists
    providers whose stub answers 503, to show a failover end to end."""
    down = {n.strip() for n in (os.getenv("ACCNOMOS_TEST_AI_DOWN") or "").split(",") if n.strip()}
    base = stub_ai_base().rstrip("/") + ("/down" if name in down else "")
    connect, first, total = DEFAULT_TIMEOUTS[name]
    return AiConfig(
        mode="local",
        base_url=base,
        model=TEST_AI_MODEL,
        provider=name,
        connect_s=connect,
        first_token_s=first,
        request_s=total,
        voice=False,
        in_chain=True,
    )


def configured_chain(env: Mapping[str, str] | None = None) -> list[AiConfig]:
    names = chain_names(env)
    if is_test_mode():
        return [_test_config(n) for n in names]
    return [c for n in names if (c := provider_config(n, env)) is not None]


def chain_config(env: Mapping[str, str] | None = None) -> AiConfig:
    """The whole chain as one AiConfig: the first provider, with the rest as its fallbacks. With nothing configured
    the Spark default stands in (the runtime's default before the chain existed), so a request still gets an answer
    or a plain "could not be reached"."""
    chain = configured_chain(env)
    if not chain:
        spark = provider_config("spark", env)
        assert spark is not None
        chain = [spark]
    head, *rest = chain
    return head.model_copy(update={"fallbacks": rest})


def describe(env: Mapping[str, str] | None = None) -> list[ProviderInfo]:
    """Every provider named in AI_PROVIDERS, configured or not, in chain order (no secrets)."""
    env = os.environ if env is None else env
    out = []
    for name in chain_names(env):
        cfg = _test_config(name) if is_test_mode() else provider_config(name, env)
        why = None
        if cfg is None:
            why = "MODAL_GLIMMER_URL is not set" if name == "modal" else "META_API_KEY is not set"
        if cfg is not None:
            model = cfg.model
        elif name == "modal":
            model = env.get("MODAL_MODEL") or DEFAULT_OLLAMA_MODEL
        else:
            model = env.get("MODEL_API_MODEL") or DEFAULT_MODEL_API_MODEL
        out.append(
            ProviderInfo(
                name=name,
                label=LABELS[name],
                model=model,
                configured=cfg is not None,
                vision=True,
                json_mode=True,
                voice=cfg.voice if cfg else name == "meta",
                why_not=why,
            )
        )
    return out
