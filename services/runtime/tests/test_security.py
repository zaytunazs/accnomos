"""Request hardening (app/security.py, docs/SECURITY.md): secrets, limits, CORS, safe errors, outbound timeouts."""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.ai.config import AiConfig, base_url_allowed
from app.main import app, cors_origins
from app.security import JSON_LIMIT, MAX_TOKEN_BYTES, SecurityMiddleware, TokenBucket, scrub

ROOT = Path(__file__).resolve().parents[3]
JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.c2lnbmF0dXJl"


@pytest.fixture
def tc() -> TestClient:
    return TestClient(app)


def tiny_app(limiter: TokenBucket | None = None) -> FastAPI:
    a = FastAPI()
    a.add_middleware(SecurityMiddleware, limiter=limiter)

    @a.get("/ok")
    async def ok() -> dict:
        return {"ok": True}

    @a.get("/boom")
    async def boom(request: Request) -> dict:
        raise RuntimeError(f"Graph said no to {request.headers.get('x-graph-token')}")

    @a.post("/echo")
    async def echo(body: dict) -> dict:
        return {"n": len(body)}

    return a


# --- 1. secrets never reach logs or error bodies ---------------------------------------------------------------

@pytest.mark.parametrize("text", [
    f"X-Graph-Token: {JWT}",
    "headers={'x-meta-api-key': 'mk-live-123456'}",
    "x-hmrc-access-token=abc123def",
    "Authorization: Bearer abc.def.ghi",
    "call failed with bearer 0123456789abcdef",
    f"token {JWT} expired",
    '{"access_token": "AT-secret", "refresh_token": "RT-secret"}',
])
def test_scrub_removes_secrets(text):
    out = scrub(text)
    for secret in (JWT, "mk-live-123456", "abc123def", "abc.def.ghi", "0123456789abcdef", "AT-secret", "RT-secret"):
        assert secret not in out
    assert "[redacted]" in out


def test_scrub_leaves_ordinary_text():
    assert scrub("Supplier Screwfix, total 38.47") == "Supplier Screwfix, total 38.47"


def test_log_records_are_scrubbed(caplog):
    logger = logging.getLogger("accnomos.test")
    with caplog.at_level(logging.INFO):
        logger.warning("calling Graph with %s", {"X-Graph-Token": "tok-very-secret"})
        try:
            raise ValueError(f"Authorization: Bearer {JWT}")
        except ValueError:
            logger.exception("failed")
    text = caplog.text + "".join(r.exc_text or "" for r in caplog.records)
    assert "tok-very-secret" not in text and JWT not in text
    assert "[redacted]" in text


def test_unhandled_error_is_safe_json_with_correlation_id(caplog):
    c = TestClient(tiny_app(), raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR):
        r = c.get("/boom", headers={"X-Graph-Token": "tok-very-secret"})
    assert r.status_code == 500
    body = r.json()
    assert set(body) == {"detail", "correlation_id"} and body["correlation_id"] == r.headers["x-correlation-id"]
    assert "Traceback" not in r.text and "RuntimeError" not in r.text and "tok-very-secret" not in r.text
    assert body["correlation_id"] in caplog.text
    assert "tok-very-secret" not in caplog.text + "".join(rec.exc_text or "" for rec in caplog.records)


def test_every_response_has_a_correlation_id(tc):
    assert len(tc.get("/health").headers["x-correlation-id"]) == 16


@pytest.mark.parametrize("header", ["X-Graph-Token", "X-Meta-Api-Key", "X-HMRC-Access-Token", "Authorization"])
def test_oversized_token_rejected(tc, header):
    r = tc.get("/books/summary", headers={header: "a" * (MAX_TOKEN_BYTES + 1)})
    assert r.status_code == 431 and "a" * 100 not in r.text


def test_credentials_refused_over_plain_http_behind_a_proxy(tc):
    r = tc.get("/books/summary", headers={"X-Graph-Token": "t", "X-Forwarded-Proto": "http"})
    assert r.status_code == 400 and "HTTPS" in r.json()["detail"]


def test_credentials_allowed_over_https_or_without_a_proxy():
    c = TestClient(tiny_app())
    assert c.get("/ok", headers={"X-Graph-Token": "t", "X-Forwarded-Proto": "https"}).status_code == 200
    assert c.get("/ok", headers={"X-Graph-Token": "t"}).status_code == 200  # direct (dev, tests)
    assert c.get("/ok", headers={"X-Forwarded-Proto": "http"}).status_code == 200  # nothing secret sent


# --- 2. limits ----------------------------------------------------------------------------------------------------

def test_token_bucket_refills():
    now = [0.0]
    b = TokenBucket(60, clock=lambda: now[0])
    assert all(b.take("1.2.3.4") == 0 for _ in range(60))
    assert b.take("1.2.3.4") == pytest.approx(1.0)
    assert b.take("5.6.7.8") == 0  # per key
    now[0] += 1.0
    assert b.take("1.2.3.4") == 0


def test_rate_limit_answers_429_with_retry_after():
    c = TestClient(tiny_app(TokenBucket(3)))
    assert [c.get("/ok").status_code for _ in range(3)] == [200, 200, 200]
    r = c.get("/ok")
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and "correlation_id" in r.json()
    assert c.options("/ok").status_code != 429  # preflights are not counted


def test_health_is_not_rate_limited(tc, monkeypatch):
    from app import security

    monkeypatch.setattr(security.LIMITER, "capacity", 1.0)
    monkeypatch.setattr(security.LIMITER, "per_s", 0.0001)
    assert all(tc.get("/health").status_code == 200 for _ in range(5))


def test_json_body_cap_by_content_length():
    r = TestClient(tiny_app()).post("/echo", content=b"{" + b" " * JSON_LIMIT + b"}",
                                    headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_json_body_cap_when_streamed_without_length():
    def chunks():
        for _ in range(JSON_LIMIT // 1024 + 2):
            yield b" " * 1024

    r = TestClient(tiny_app()).post("/echo", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_upload_routes_take_more_than_the_json_cap(tc):
    files = {"file": ("s.csv", b"x" * (JSON_LIMIT * 2), "text/csv")}
    r = tc.post("/books/bank/import", files=files)  # no token: refused later, but not for size
    assert r.status_code == 401


def test_upload_cap_is_25_mb(tc):
    def chunks():
        for _ in range(26):
            yield b"x" * (1024 * 1024)

    r = tc.post("/extract", content=chunks(), headers={"Content-Type": "multipart/form-data; boundary=x"})
    assert r.status_code == 413


def test_every_outbound_http_client_has_a_timeout():
    """Graph, Meta, Ollama, SAM and HMRC calls all go through httpx clients created with an explicit timeout."""
    sources = [*(ROOT / "services/runtime/app").rglob("*.py"), *(ROOT / "packages/connectors/src").rglob("*.py"),
               *(ROOT / "services/hmrc-relay/relay").rglob("*.py")]
    found = 0
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and ast.unparse(node.func) in ("httpx.AsyncClient", "httpx.Client"):
                found += 1
                assert any(k.arg == "timeout" for k in node.keywords), f"{path}:{node.lineno} has no timeout"
            if isinstance(node, ast.Call) and ast.unparse(node.func) in (
                "httpx.get", "httpx.post", "httpx.put", "httpx.delete", "httpx.request", "requests.get", "requests.post"
            ):
                raise AssertionError(f"{path}:{node.lineno}: module-level HTTP call; use a client with a timeout")
    assert found >= 5


def test_relay_copy_of_the_middleware_has_not_drifted():
    """services/hmrc-relay/relay/security.py is a copy (separate image); the request handling must stay identical."""
    def handler(path: Path) -> str:
        text = path.read_text()
        return text[text.index("    async def __call__"):]

    assert handler(ROOT / "services/runtime/app/security.py") == handler(ROOT / "services/hmrc-relay/relay/security.py")


# --- 3. CORS ------------------------------------------------------------------------------------------------------

def test_cors_preflight_is_exact_and_cached(tc):
    r = tc.options("/books/summary", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET",
                                               "Access-Control-Request-Headers": "x-graph-token"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert r.headers["access-control-max-age"] == "600"
    evil = tc.options("/books/summary", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in evil.headers


@pytest.mark.parametrize("raw", ["*", "https://app.accnomos.com,*", "https://app.accnomos.com/path", "app.accnomos.com",
                                 "https://*.accnomos.com"])
def test_cors_origins_refuse_wildcards_and_non_origins(raw):
    with pytest.raises(RuntimeError):
        cors_origins(raw)


def test_cors_origins_exact():
    assert cors_origins(" https://app.accnomos.com/, http://localhost:3000 ") == ["https://app.accnomos.com",
                                                                                 "http://localhost:3000"]


# --- 4. client-chosen AI base URL (SSRF) ---------------------------------------------------------------------

@pytest.mark.parametrize("url", ["http://169.254.169.254/latest", "http://relay:8787", "http://127.0.0.1:8780",
                                 "https://api.meta.ai.evil.example/v1", "file:///etc/passwd"])
def test_unknown_ai_base_url_refused(url, tc):
    assert not base_url_allowed(url)
    with pytest.raises(ValueError, match="allow-list"):
        AiConfig.from_headers({"X-AI-Mode": "local", "X-AI-Base-Url": url})
    assert tc.post("/ai/test", json={"mode": "local", "base_url": url}).status_code == 400


def test_known_ai_base_urls_allowed(monkeypatch):
    monkeypatch.setenv("AI_ALLOWED_BASE_URLS", "http://192.168.1.176:11434, https://models.example/v1")
    for url in ("https://api.meta.ai/v1/", "http://localhost:11434", "http://192.168.1.176:11434",
                "HTTPS://models.example/v1"):
        assert base_url_allowed(url)
    assert AiConfig.from_headers({"X-AI-Mode": "local", "X-AI-Base-Url": "http://192.168.1.176:11434"}).base_url \
        == "http://192.168.1.176:11434"
