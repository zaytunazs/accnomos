"""Accnomos Agent Runtime (stateless).

Every request carries the user's storage access token and AI config in headers; the runtime does the
work against the user's own cloud folder and Meta models, returns, and keeps nothing.
"""

from __future__ import annotations

import os
import time

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Accnomos Agent Runtime", version="0.1.0")
STARTED = time.time()

# Browsers (PWA) call the runtime directly; it keeps nothing, so CORS is the only gate.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,https://accnomos.com,https://app.accnomos.com").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AiConfig(BaseModel):
    mode: str  # "key" (user's Meta Model API key) | "local" (Ollama/Glimmer on the user's machine)
    base_url: str | None = None
    model: str | None = None


class AiTestResult(BaseModel):
    ok: bool
    mode: str
    model: str | None = None
    detail: str


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "runtime", "version": app.version, "uptime_s": int(time.time() - STARTED)}


@app.post("/ai/test", response_model=AiTestResult)
async def ai_test(cfg: AiConfig, x_meta_api_key: str | None = Header(default=None)) -> AiTestResult:
    """F2: 'Test connection' button. Lists models with the user's key, or pings the user's local agent."""
    async with httpx.AsyncClient(timeout=20) as client:
        if cfg.mode == "key":
            if not x_meta_api_key:
                raise HTTPException(400, "X-Meta-Api-Key header required in key mode")
            base = cfg.base_url or os.getenv("MODEL_API_BASE", "https://api.meta.ai/v1")
            r = await client.get(f"{base}/models", headers={"Authorization": f"Bearer {x_meta_api_key}"})
            if r.status_code != 200:
                return AiTestResult(ok=False, mode="key", detail=f"Meta API returned {r.status_code}")
            ids = [m["id"] for m in r.json().get("data", [])]
            want = cfg.model or "muse-spark-1.3"
            return AiTestResult(ok=want in ids, mode="key", model=want, detail=f"{len(ids)} models available")
        if cfg.mode == "local":
            base = (cfg.base_url or os.getenv("OLLAMA_BASE", "http://127.0.0.1:11434")).rstrip("/")
            r = await client.get(f"{base}/api/tags")
            if r.status_code != 200:
                return AiTestResult(ok=False, mode="local", detail=f"local agent returned {r.status_code}")
            names = [m["name"] for m in r.json().get("models", [])]
            want = cfg.model or os.getenv("OLLAMA_MODEL", "muse-glimmer:30b")
            return AiTestResult(ok=want in names, mode="local", model=want, detail=f"models: {', '.join(names)}")
    raise HTTPException(400, "mode must be 'key' or 'local'")
