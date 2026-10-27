"""Accnomos Agent Runtime (stateless).

Every request carries the user's storage access token and AI config in headers; the runtime does the
work against the user's own cloud folder and Meta models, returns, and keeps nothing.
"""

from __future__ import annotations

import logging
import os
import re
import time

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from app.ai.config import base_url_allowed
from app.security import SecurityMiddleware, install_log_scrubbing, scrub

install_log_scrubbing()
from app.ai.config import TEST_AI_MODEL, is_test_mode, stub_ai_base

app = FastAPI(title="Accnomos Agent Runtime", version="0.1.0")
STARTED = time.time()


def cors_origins(raw: str) -> list[str]:
    """Exact `scheme://host[:port]` origins from CORS_ORIGINS; anything else (a wildcard, a path) is refused."""
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    bad = [o for o in origins if not re.fullmatch(r"https?://[A-Za-z0-9.-]+(:\d{1,5})?", o)]
    if bad:
        raise RuntimeError(f"CORS_ORIGINS must list exact origins, not {bad}")
    return origins


# Browsers (PWA) call the runtime directly; it keeps nothing, so CORS is the only gate. The security middleware
# sits inside CORS so its 4xx/5xx answers still reach the page.
app.add_middleware(SecurityMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(os.getenv("CORS_ORIGINS", "http://localhost:3000")),
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-Graph-Token", "X-Account-Kind", "X-User", "X-AI-Mode", "X-AI-Base-Url",
                   "X-AI-Model", "X-Meta-Api-Key", "X-Business-Name", "X-Autopilot"],
    expose_headers=["X-Correlation-Id", "Retry-After"],
    max_age=600,
)


class AiConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = Field(max_length=10)  # "key" (user's Meta Model API key) | "local" (Ollama/Glimmer on the user's machine)
    base_url: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=200)


class AiTestResult(BaseModel):
    ok: bool
    mode: str
    model: str | None = None
    detail: str


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True, "service": "runtime", "version": app.version, "uptime_s": int(time.time() - STARTED),
        "voice": bool(FFMPEG), **({"test_mode": True} if is_test_mode() else {}),
    }


@app.post("/ai/test", response_model=AiTestResult)
async def ai_test(cfg: AiConfig, x_meta_api_key: str | None = Header(default=None)) -> AiTestResult:
    """F2: 'Test connection' button. Lists models with the user's key, or pings the user's local agent."""
    if cfg.base_url and not base_url_allowed(cfg.base_url):
        raise HTTPException(400, "base_url is not on this server's allow-list (AI_ALLOWED_BASE_URLS)")
    if is_test_mode():  # the stub AI stands in for whatever the user typed
        cfg = AiConfig(mode="local", base_url=stub_ai_base(), model=TEST_AI_MODEL)
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0), follow_redirects=False) as client:
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
    return JSONResponse(status_code=status, content={"detail": scrub(str(exc))})


from app.validation import UnsafeName  # noqa: E402


@app.exception_handler(UnsafeName)
async def unsafe_name(_request: Request, exc: UnsafeName) -> JSONResponse:
    """A file name that could climb out of its folder (e.g. a hand-edited proposal in the user's books) -> 400."""
    return JSONResponse(status_code=400, content={"detail": f"Bad file name: {exc}"})
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
from app.routes_vehicles import router as vehicles_router  # noqa: E402  /vehicles, /mileage
app.include_router(vehicles_router)
from app.routes_invoices import router as invoices_router  # noqa: E402  /invoices/*
app.include_router(invoices_router)
from app.routes_actions import router as actions_router  # noqa: E402  /actions/approve, /actions/reject
app.include_router(actions_router)
from app.routes_payroll import router as payroll_router  # noqa: E402  /payroll/runs
app.include_router(payroll_router)

from app.routes_plan import router as plan_router  # noqa: E402  /plan/day, /plan/day/apply
app.include_router(plan_router)
if is_test_mode():  # ACCNOMOS_TEST_MODE=1 only (e2e tests): fakes + stub AI under /__test (app/testmode.py)
    from app import testmode

    testmode.enable()
    app.include_router(testmode.router)

