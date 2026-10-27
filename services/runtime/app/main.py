"""Accnomos Agent Runtime (stateless).

Every request carries the user's storage access token and AI config in headers; the runtime does the
work against the user's own cloud folder and Meta models, returns, and keeps nothing.
"""

from __future__ import annotations

import logging
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
    return {
        "ok": True, "service": "runtime", "version": app.version, "uptime_s": int(time.time() - STARTED),
        "voice": bool(FFMPEG),
    }


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

from app.routes_extract import router as extract_router  # noqa: E402  POST /extract
app.include_router(extract_router)

from accnomos_connectors.msgraph import GraphError  # noqa: E402
from fastapi import Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from app.routes_books import router as books_router  # noqa: E402  /books/*
app.include_router(books_router)


@app.exception_handler(GraphError)
async def graph_error(_request: Request, exc: GraphError) -> JSONResponse:
    """Expired/insufficient Graph token -> 401 so the app re-authenticates; anything else -> 502."""
    status = 401 if exc.status in (401, 403) else 502
    return JSONResponse(status_code=status, content={"detail": str(exc)})
from app.routes_vat import router as vat_router  # noqa: E402  GET /books/vat
app.include_router(vat_router)
from app.routes_bank import router as bank_router  # noqa: E402  /books/bank/*
app.include_router(bank_router)
from app.routes_ask import router as ask_router  # noqa: E402  POST /books/ask, /books/ask/voice
app.include_router(ask_router)
from app.routes_mail import router as mail_router  # noqa: E402  POST /mail/scan
app.include_router(mail_router)
from app.routes_jobs import router as jobs_router  # noqa: E402  /jobs, /staff, /timesheets
app.include_router(jobs_router)

from app.ai.voice import ffmpeg_path  # noqa: E402

FFMPEG = ffmpeg_path()  # checked once at startup; /books/ask/voice answers 503 without it
if not FFMPEG:
    logging.getLogger("accnomos.runtime").warning("ffmpeg not found: voice questions (/books/ask/voice) are disabled")
from app.routes_contacts import router as contacts_router  # noqa: E402  /contacts/*
app.include_router(contacts_router)

from app.routes_plan import router as plan_router  # noqa: E402  /plan/day, /plan/day/apply
app.include_router(plan_router)
