"""Per-request AI backend configuration.

The UI chooses the backend per request via headers; the server falls back to
environment variables so the harness and CLI can run without a browser.

Headers: X-AI-Mode (local|key|auto), X-AI-Base-Url, X-AI-Model, X-Meta-Api-Key,
         X-AI-Route (meta_first|local_first|local_only: which answers first, see `apply_route`).
Env:     AI_MODE, OLLAMA_BASE, OLLAMA_MODEL, MODEL_API_BASE, MODEL_API_MODEL, META_API_KEY,
         AI_ALLOWED_BASE_URLS (extra base URLs a client may pick with X-AI-Base-Url),
         AI_PROVIDERS (the server's ordered provider chain, e.g. `spark,anthropic`: app/ai/providers.py).

A request that names no backend (no X-AI-* headers, or X-AI-Mode: auto) gets the server's chain when AI_PROVIDERS
is set: each call tries the providers in order and falls over to the next on an outage (app/ai/chain.py). A request
that names a backend (the user's own local agent, or their own Meta key) gets exactly that one, as before.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal

import httpx
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from starlette.requests import Request
else:
    try:  # FastAPI must see the real class to inject the request
        from starlette.requests import Request
    except ImportError:  # harness-only installs without FastAPI
        Request = Any

AiMode = Literal["local", "key"]
AiRoute = Literal["meta_first", "local_first", "local_only"]
ROUTES: tuple[AiRoute, ...] = ("meta_first", "local_first", "local_only")

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


def _norm(url: str) -> str:
    return url.strip().rstrip("/").lower()


def base_url_allowed(url: str) -> bool:
    """A client-chosen AI base URL is used only if it is one the server already knows: the defaults, the
    OLLAMA_BASE / MODEL_API_BASE in use, or one listed in AI_ALLOWED_BASE_URLS (comma-separated)."""
    if is_test_mode():  # nothing the browser names is fetched: every config is swapped for the stub
        return True
    allowed = {
        DEFAULT_OLLAMA_BASE,
        DEFAULT_MODEL_API_BASE,
        os.getenv("OLLAMA_BASE", ""),
        os.getenv("MODEL_API_BASE", ""),
        *os.getenv("AI_ALLOWED_BASE_URLS", "").split(","),
    }
    return _norm(url) in {_norm(a) for a in allowed if a.strip()}


class AiConfig(BaseModel):
    mode: AiMode
    base_url: str
    model: str
    api_key: str | None = Field(default=None, repr=False)  # never in a repr or a log line
    # Who serves it: modal | meta | spark | anthropic (the server's chain), local | key (the user's own backend), test.
    provider: str = ""
    # Extra auth headers (Modal proxy auth: Modal-Key / Modal-Secret). Never logged or serialised.
    extra_headers: dict[str, str] = Field(default_factory=dict, repr=False, exclude=True)
    # Timeouts (s). None keeps each caller's own default, as before the chain existed.
    connect_s: float = 15.0
    first_token_s: float | None = None  # longest wait for a reply to start (a Modal cold start is 60-120 s)
    request_s: float | None = None  # longest one attempt may take in all
    vision: bool = True  # reads images
    voice: bool = False  # Muse Voice Transcribe (Meta Model API only)
    in_chain: bool = False  # one of the server's AI_PROVIDERS: failover and the circuit breaker apply
    local: bool = False  # a local model (the user's own computer, or the server's own Glimmer): not a hosted API
    route: AiRoute | None = None  # the user's X-AI-Route, when they chose one
    fallbacks: list[AiConfig] = Field(default_factory=list, repr=False)

    def chain(self) -> list[AiConfig]:
        """This provider, then its fallbacks, in order."""
        return [self.model_copy(update={"fallbacks": []}), *self.fallbacks]

    def auth_headers(self) -> dict[str, str]:
        """Headers every request to this backend carries (key: bearer token; Modal: its proxy-auth token)."""
        h = dict(self.extra_headers)
        if self.mode == "key" and self.api_key:
            if self.provider == "anthropic":  # the Messages API: x-api-key (anthropic-version is in extra_headers)
                h["x-api-key"] = self.api_key
            else:
                h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def http_timeout(self, default_s: float) -> httpx.Timeout:
        """A caller's httpx timeout: its own `default_s` for a backend the user chose (unchanged), or this provider's
        connect and first-byte limits in the chain (a non-streamed reply's first byte is the whole reply)."""
        if self.first_token_s is None:
            return httpx.Timeout(default_s)
        return httpx.Timeout(connect=self.connect_s, read=self.first_token_s, write=30.0, pool=self.connect_s)

    def with_capability(self, what: Literal["vision", "voice"]) -> AiConfig | None:
        """The first provider in the chain that can do `what`, or None."""
        return next((c for c in self.chain() if getattr(c, what)), None)

    @classmethod
    def resolve(
        cls,
        mode: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        route: str | None = None,
    ) -> AiConfig:
        """Build a config from explicit values, falling back to the environment, then order it by the user's
        route when they chose one (`apply_route`)."""
        cfg = cls._resolve(mode, base_url, model, api_key)
        return apply_route(cfg, route)

    @classmethod
    def _resolve(
        cls,
        mode: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> AiConfig:
        """Build a config from explicit values, falling back to the environment. Test mode ignores both.

        No explicit choice (or mode "auto") and AI_PROVIDERS set: the server's provider chain."""
        from app.ai import providers  # late: providers builds AiConfigs

        wants_chain = (mode is None or mode.strip().lower() == "auto") and not (base_url or model or api_key)
        if wants_chain and providers.chain_names():
            return providers.chain_config()
        if is_test_mode():  # whatever the browser sent, no request may reach a real model
            return cls(mode="local", base_url=stub_ai_base().rstrip("/"), model=TEST_AI_MODEL, provider="test")
        m = (mode or os.getenv("AI_MODE") or "local").strip().lower()
        if m == "auto":  # asked for the chain, but the server has none: its single default, as before
            m = (os.getenv("AI_MODE") or "local").strip().lower()
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
        return cls(
            mode=m,  # type: ignore[arg-type]
            base_url=base.rstrip("/"),
            model=mdl,
            api_key=key,
            provider=m,
            voice=m == "key",
            local=m == "local",
        )

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> AiConfig:
        """Read X-AI-* headers (case-insensitive mapping, e.g. Starlette Headers).

        X-AI-Base-Url must be on the server's allow-list: the runtime fetches that URL, so a free choice
        would let any caller point it at hosts only the server can reach.
        """
        get = lambda k: headers.get(k) or headers.get(k.lower()) or None  # noqa: E731
        base_url = get("X-AI-Base-Url")
        if base_url and not is_test_mode() and not base_url_allowed(base_url):  # test mode never uses it (resolve)
            raise ValueError("X-AI-Base-Url is not on this server's allow-list (AI_ALLOWED_BASE_URLS)")
        return cls.resolve(
            mode=get("X-AI-Mode"),
            base_url=base_url,
            model=get("X-AI-Model"),
            api_key=get("X-Meta-Api-Key"),
            route=get("X-AI-Route"),
        )

    def public(self) -> dict[str, str]:
        """Loggable view (never includes the key or auth headers)."""
        return {"mode": self.mode, "base_url": self.base_url, "model": self.model, "provider": self.provider}


def apply_route(cfg: AiConfig, route: str | None) -> AiConfig:
    """Order the providers by the user's choice of which answers first (X-AI-Route, Settings › AI):

    * meta_first  - the Meta Model API (the user's own key, else the server's) first, a local model if it is down;
    * local_first - a local model first; the Meta Model API when the local model is down or its reply does not come
                    back in a usable form (`chain.run(..., accept=...)`), so most calls spend no Meta credit;
    * local_only  - a local model and nothing else: nothing goes to the Meta Model API, voice included.

    "Local" is the user's own computer when they chose it (X-AI-Mode: local), else the server's own Glimmer
    (`spark`). The server's Anthropic backup (`anthropic`) is never local and always goes last, whatever the route, so
    documents reach it only when every other provider failed; local only never reaches it. No route (or an unknown
    one) leaves the config exactly as before. A route that leaves nothing to try raises ValueError (HTTP 400), so
    local only never quietly reaches a hosted API.
    """
    from app.ai import providers  # late: providers builds AiConfigs

    r = (route or "").strip().lower()
    if r not in ROUTES or cfg.provider == "test":
        return cfg
    mine = cfg.chain()
    if cfg.in_chain:  # the server's chain: its local ones and its hosted ones
        local = [c for c in mine if c.local]
        cloud = [c for c in mine if not c.local]
    else:  # a backend the user chose, plus the server's chain for the other half
        server = providers.chain_config().chain() if providers.chain_names() else []
        if cfg.local:
            local, cloud = mine, [c for c in server if not c.local]
        else:
            local, cloud = [c for c in server if c.local], mine
    backup = [c for c in cloud if c.provider == "anthropic"]  # the server's backup: last on every route, never first
    cloud = [c for c in cloud if c.provider != "anthropic"]
    order = {"meta_first": cloud + local + backup, "local_first": local + cloud + backup, "local_only": local}[r]
    if not order:
        if r == "local_only":
            raise ValueError("Local model only is chosen, but no local model is set up on this server")
        return cfg
    tagged = [c.model_copy(update={"route": r, "fallbacks": []}) for c in order]
    head, *rest = tagged
    return head.model_copy(update={"fallbacks": rest})


def ai_config_from_request(request: Request) -> AiConfig:
    """FastAPI dependency: `cfg: AiConfig = Depends(ai_config_from_request)`.

    Raises HTTP 400 on a bad mode or missing key.
    """
    from fastapi import HTTPException

    try:
        return AiConfig.from_headers(request.headers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
