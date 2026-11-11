"""The server's AI provider chain (AI_PROVIDERS), so no AI call depends on one machine.

    AI_PROVIDERS=spark,anthropic       # the production order since 11 Nov 2026: our own server first, Anthropic backup

Owner's decision (11 Nov 2026): customer documents no longer go to Meta's Model API (the live server's
`muse-spark-1.3-contributor` model may be trained on). The server's own models answer first; Anthropic's API is the
backup when they cannot.

* spark     -> Muse Glimmer 30B on our own server (local model runtime): OLLAMA_BASE, OLLAMA_MODEL.
* anthropic -> the Anthropic Messages API (app/ai/anthropic.py): ANTHROPIC_API_KEY, ANTHROPIC_MODEL (default
               claude-haiku-5-5), ANTHROPIC_VERIFY_MODEL, ANTHROPIC_BASE, ANTHROPIC_VERSION, ANTHROPIC_MAX_TOKENS.
               Under Anthropic's Commercial Terms it may not train on the content; no zero data retention by default.
* modal     -> Muse Glimmer 30B on a hosted GPU (tools/modal_glimmer.py: a cloud GPU behind a web endpoint).
               MODAL_GLIMMER_URL, MODAL_MODEL (default muse-glimmer:30b), and, with proxy auth,
               MODAL_PROXY_TOKEN_ID + MODAL_PROXY_TOKEN_SECRET. Supported, not deployed.
* meta      -> Muse Spark on the Meta Model API with the server's key: META_API_KEY, MODEL_API_BASE, MODEL_API_MODEL.
               Still supported, but no longer in the live server's chain.

A provider without its settings (no URL, no key) is left out of the chain and shown as "not configured".
Timeouts per provider, in seconds: <NAME>_CONNECT_S, <NAME>_FIRST_TOKEN_S (the longest wait for a reply to start,
which covers a hosted GPU cold start), <NAME>_REQUEST_S (the longest one attempt may take in all); NAME is MODAL,
META, SPARK or ANTHROPIC. Test mode keeps the chain's names and order but points every provider at the stub AI.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel

from app.ai import anthropic
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

ProviderName = Literal["modal", "meta", "spark", "anthropic"]
KNOWN: tuple[ProviderName, ...] = ("modal", "meta", "spark", "anthropic")
RECOMMENDED = "spark,anthropic"

#: (connect, first token, whole request) seconds by default.
#: Hosted GPU: a cold start loads ~18 GB from a volume (60-120 s).
DEFAULT_TIMEOUTS: dict[str, tuple[float, float, float]] = {
    "modal": (10.0, 150.0, 240.0),
    "meta": (10.0, 90.0, 120.0),
    "spark": (5.0, 180.0, 200.0),
    "anthropic": (10.0, 90.0, 120.0),
}

LABELS: dict[str, str] = {
    "modal": "hosted GPU",  # shown to users: no vendor, host or hardware names
    "meta": "hosted model API",
    "spark": "our own server",  # shown to users: no hardware or vendor names
    "anthropic": "backup provider (Anthropic)",
    "local": "your machine",
    "key": "your own API key",
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
    if name == "anthropic":
        key = (env.get("ANTHROPIC_API_KEY") or "").strip()
        if not key:
            return None
        return AiConfig(
            mode="key",
            base_url=(env.get("ANTHROPIC_BASE") or anthropic.DEFAULT_BASE).rstrip("/"),
            model=(env.get("ANTHROPIC_MODEL") or "").strip() or anthropic.DEFAULT_MODEL,
            api_key=key,
            extra_headers={"anthropic-version": anthropic.version(env)},
            voice=False,
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
        local=True,  # the server's own Glimmer: a local model for X-AI-Route
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
        local=name == "spark",
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
            why = {"modal": "the hosted GPU endpoint is not set", "anthropic": "ANTHROPIC_API_KEY is not set"}.get(
                name, "META_API_KEY is not set"
            )
        if cfg is not None:
            model = cfg.model
        elif name == "modal":
            model = env.get("MODAL_MODEL") or DEFAULT_OLLAMA_MODEL
        elif name == "anthropic":
            model = env.get("ANTHROPIC_MODEL") or anthropic.DEFAULT_MODEL
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
