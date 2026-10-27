"""Per-request AI backend configuration.

The UI chooses the backend per request via headers; the server falls back to
environment variables so the harness and CLI can run without a browser.

Headers: X-AI-Mode (local|key), X-AI-Base-Url, X-AI-Model, X-Meta-Api-Key.
Env:     AI_MODE, OLLAMA_BASE, OLLAMA_MODEL, MODEL_API_BASE, MODEL_API_MODEL, META_API_KEY.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel

try:  # FastAPI must see the real class to inject the request
    from starlette.requests import Request
except ImportError:  # harness-only installs without FastAPI
    Request = Any  # type: ignore[misc,assignment]

AiMode = Literal["local", "key"]

DEFAULT_OLLAMA_BASE = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "muse-glimmer:30b"
DEFAULT_MODEL_API_BASE = "https://api.meta.ai/v1"
DEFAULT_MODEL_API_MODEL = "muse-spark-1.3"
TEST_AI_MODEL = "accnomos-test-stub"


def is_test_mode() -> bool:
    """ACCNOMOS_TEST_MODE=1: fake providers and the stub AI (app/testmode.py). Never set in the Docker image."""
    return os.getenv("ACCNOMOS_TEST_MODE") == "1"


def stub_ai_base() -> str:
    """The stub AI served by this runtime in test mode (Ollama-shaped, under /__test/ai)."""
    return os.getenv("ACCNOMOS_TEST_AI_BASE") or f"http://127.0.0.1:{os.getenv('PORT', '8780')}/__test/ai"


class AiConfig(BaseModel):
    mode: AiMode
    base_url: str
    model: str
    api_key: str | None = None

    @classmethod
    def resolve(
        cls,
        mode: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> AiConfig:
        """Build a config from explicit values, falling back to the environment. Test mode ignores both."""
        if is_test_mode():  # whatever the browser sent, no request may reach a real model
            return cls(mode="local", base_url=stub_ai_base().rstrip("/"), model=TEST_AI_MODEL)
        m = (mode or os.getenv("AI_MODE") or "local").strip().lower()
        if m not in ("local", "key"):
            raise ValueError(f"Unknown AI mode {m!r}; expected 'local' or 'key'")
        if m == "local":
            base = base_url or os.getenv("OLLAMA_BASE") or DEFAULT_OLLAMA_BASE
            mdl = model or os.getenv("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL
            key = None
        else:
            base = base_url or os.getenv("MODEL_API_BASE") or DEFAULT_MODEL_API_BASE
            mdl = model or os.getenv("MODEL_API_MODEL") or DEFAULT_MODEL_API_MODEL
            key = api_key or os.getenv("META_API_KEY")
            if not key:
                raise ValueError("Mode 'key' needs X-Meta-Api-Key (or META_API_KEY)")
        return cls(mode=m, base_url=base.rstrip("/"), model=mdl, api_key=key)  # type: ignore[arg-type]

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> AiConfig:
        """Read X-AI-* headers (case-insensitive mapping, e.g. Starlette Headers)."""
        get = lambda k: (headers.get(k) or headers.get(k.lower()) or None)  # noqa: E731
        return cls.resolve(
            mode=get("X-AI-Mode"),
            base_url=get("X-AI-Base-Url"),
            model=get("X-AI-Model"),
            api_key=get("X-Meta-Api-Key"),
        )

    def public(self) -> dict[str, str]:
        """Loggable view (never includes the key)."""
        return {"mode": self.mode, "base_url": self.base_url, "model": self.model}


def ai_config_from_request(request: Request) -> AiConfig:
    """FastAPI dependency: `cfg: AiConfig = Depends(ai_config_from_request)`.

    Raises HTTP 400 on a bad mode or missing key.
    """
    from fastapi import HTTPException

    try:
        return AiConfig.from_headers(request.headers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
