"""Accnomos HMRC relay (stateless).

HMRC's user-restricted OAuth needs the client secret at code exchange AND refresh (verified 26 Oct 2026),
so this is the one server component that holds a secret. It returns tokens to the client and stores
nothing. Fraud-prevention headers (spec v3.3) are assembled here from client-supplied facts + server facts.
Day 5 (30 Oct) fills in /hmrc/authorize, /hmrc/callback, /hmrc/refresh, /vat/* and the header builder.
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI

app = FastAPI(title="Accnomos HMRC relay", version="0.1.0")
STARTED = time.time()


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "service": "hmrc-relay",
        "version": app.version,
        "sandbox": os.getenv("HMRC_BASE", "https://test-api.service.hmrc.gov.uk").startswith("https://test-"),
        "configured": bool(os.getenv("HMRC_CLIENT_ID") and os.getenv("HMRC_CLIENT_SECRET")),
        "uptime_s": int(time.time() - STARTED),
    }
