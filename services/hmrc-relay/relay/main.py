"""Accnomos HMRC relay (stateless).

HMRC's user-restricted OAuth needs the client secret at code exchange AND refresh (verified 26 Oct 2026),
so this is the one server component that holds a secret. It returns tokens to the client and stores
nothing. Fraud-prevention headers (spec v3.3) are assembled here from client-supplied facts + server facts.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .hmrc_client import HmrcClient, HmrcError, HmrcUnavailable
from .oauth import OAuth, StateError
from .routes import Relay, router
from .settings import Settings, get_settings


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """Build the app. `transport` lets tests swap in an httpx.MockTransport so HMRC is never called."""
    settings = settings or get_settings()
    http = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(20.0, connect=5.0))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await http.aclose()

    app = FastAPI(title="Accnomos HMRC relay", version="0.1.0", lifespan=lifespan)
    app.state.relay = Relay(settings, HmrcClient(settings, http), OAuth(settings, http))
    app.state.started = time.time()
    app.include_router(router)

    @app.middleware("http")
    async def stamp_received(request: Request, call_next):
        request.state.received_at = datetime.now(UTC)  # for Gov-Client-Public-IP-Timestamp
        return await call_next(request)

    @app.exception_handler(HmrcError)
    async def hmrc_error(_: Request, e: HmrcError) -> JSONResponse:
        return JSONResponse(e.to_json(), status_code=e.status)

    @app.exception_handler(HmrcUnavailable)
    async def hmrc_unavailable(_: Request, e: HmrcUnavailable) -> JSONResponse:
        return JSONResponse({"code": "HMRC_UNAVAILABLE", "message": str(e)}, status_code=502)

    @app.exception_handler(StateError)
    async def bad_state(_: Request, e: StateError) -> JSONResponse:
        return JSONResponse({"code": "INVALID_STATE", "message": str(e)}, status_code=400)

    @app.get("/health")
    async def health() -> dict:
        return {
            "ok": True,
            "service": "hmrc-relay",
            "version": app.version,
            "sandbox": settings.sandbox,
            "configured": settings.configured,
            "uptime_s": int(time.time() - app.state.started),
        }

    return app


app = create_app()
