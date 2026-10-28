"""The server's AI provider chain (app/ai/providers.py, app/ai/chain.py, app/routes_ai.py), on fake transports only:
no request here reaches Modal, Meta or a Spark."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app import routes_ai
from app.ai import ask as ask_ai
from app.ai import chain, providers
from app.ai import verify as verify_mod
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError, extract_document
from app.schemas import ExtractedDoc, ExtractedLine

MODAL = "https://ws--accnomos-glimmer-serve.us-east.modal.run"
META = "https://api.meta.ai/v1"
SPARK = "http://spark.invalid:11434"
SECRETS = ("server-meta-key", "tok-id", "tok-secret")

ENV = {
    "AI_PROVIDERS": "modal,meta,spark",
    "MODAL_GLIMMER_URL": MODAL,
    "MODAL_PROXY_TOKEN_ID": "tok-id",
    "MODAL_PROXY_TOKEN_SECRET": "tok-secret",
    "META_API_KEY": "server-meta-key",
    "MODEL_API_BASE": META,
    "OLLAMA_BASE": SPARK,
}

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("ACCNOMOS_TEST_MODE", "AI_MODE", "VERIFIER", "BASETEN_API_KEY", "ACCNOMOS_TEST_AI_DOWN"):
        monkeypatch.delenv(k, raising=False)
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    routes_ai.reset()


def _doc() -> ExtractedDoc:
    return ExtractedDoc(
        doc_type="receipt",
        supplier_name="Screwfix Direct Ltd",
        supplier_vat_number="GB 232 4567 89",
        customer_name=None,
        invoice_number=None,
        date="2026-10-21",
        currency="GBP",
        lines=[ExtractedLine(description="Drill bits", qty=1, unit_price=38.47, net=32.06, vat_rate=20, vat=6.41)],
        net_total=32.06,
        vat_total=6.41,
        gross_total=38.47,
        payment_method="card",
        card_last4="1234",
        category_guess="Tools & small equipment",
        confidence=0.95,
    )


def _ok(request: httpx.Request, content: dict[str, Any]) -> httpx.Response:
    """A successful reply in the wire format the request asked for (Ollama native or OpenAI-compatible)."""
    text = json.dumps(content)
    if request.url.path.endswith("/api/chat"):
        return httpx.Response(200, json={"message": {"content": text}, "done": True})
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def _host(request: httpx.Request) -> str:
    url = str(request.url)
    return "modal" if url.startswith(MODAL) else "meta" if url.startswith(META) else "spark"


def _fake(monkeypatch: pytest.MonkeyPatch, by_provider: dict[str, Any], seen: list[str]) -> list[httpx.Request]:
    """Every httpx client answers per provider: an int status, an exception to raise, or a callable(request)."""
    real = httpx._client.AsyncClient
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        who = _host(request)
        seen.append(who)
        requests.append(request)
        out = by_provider.get(who, 200)
        if isinstance(out, Exception):
            raise out
        if callable(out):
            return out(request)
        if out == 200:
            return _ok(request, _doc().model_dump(mode="json"))
        return httpx.Response(out, json={"error": "fake"})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return requests


def chain_cfg() -> AiConfig:
    return AiConfig.from_headers({})


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_no_headers_get_the_chain_in_order() -> None:
    cfg = chain_cfg()
    assert [c.provider for c in cfg.chain()] == ["modal", "meta", "spark"]
    assert all(c.in_chain for c in cfg.chain())
    modal, meta, spark = cfg.chain()
    assert (modal.mode, modal.base_url, modal.model) == ("local", MODAL, "muse-glimmer:30b")
    assert modal.first_token_s and modal.first_token_s >= 120 and modal.connect_s <= 15  # cold start vs connect
    assert (meta.mode, meta.model, meta.voice) == ("key", "muse-spark-1.3", True)
    assert spark.base_url == SPARK and spark.api_key is None
    assert "tok-secret" not in repr(cfg) and "tok-secret" not in json.dumps(cfg.model_dump())


def test_auto_mode_is_the_chain_and_unconfigured_providers_drop_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODAL_GLIMMER_URL")
    monkeypatch.delenv("META_API_KEY")
    cfg = AiConfig.from_headers({"X-AI-Mode": "auto"})
    assert [c.provider for c in cfg.chain()] == ["spark"]
    assert [(p.name, p.configured) for p in providers.describe()] == [
        ("modal", False),
        ("meta", False),
        ("spark", True),
    ]


def test_without_ai_providers_nothing_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_PROVIDERS")
    cfg = chain_cfg()
    assert (cfg.mode, cfg.base_url, cfg.in_chain, cfg.fallbacks) == ("local", SPARK, False, [])


def test_own_key_and_own_local_agent_are_unchanged() -> None:
    own = AiConfig.from_headers({"X-AI-Mode": "key", "X-Meta-Api-Key": "users-own-key"})
    assert (own.mode, own.api_key, own.in_chain, own.fallbacks) == ("key", "users-own-key", False, [])
    local = AiConfig.from_headers({"X-AI-Mode": "local", "X-AI-Base-Url": SPARK})
    assert (local.base_url, local.in_chain, local.fallbacks) == (SPARK, False, [])


# --------------------------------------------------------------------------- #
# Failover
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "trouble",
    [503, 500, 502, 429, 402, httpx.ConnectError("refused"), httpx.ReadTimeout("slow")],
)
async def test_fails_over_in_order(monkeypatch: pytest.MonkeyPatch, trouble: Any) -> None:
    seen: list[str] = []
    _fake(monkeypatch, {"modal": trouble}, seen)
    doc, meta = await extract_document(b"img", "image/png", chain_cfg())
    assert doc.supplier_name == "Screwfix Direct Ltd"
    assert seen == ["modal", "meta"]
    served = meta["served"]
    assert (served.provider, served.model, served.fell_back_from) == ("meta", "muse-spark-1.3", ["modal"])
    assert meta["backend"] == "meta" and served.latency_ms >= 0


async def test_falls_through_to_the_spark_last(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    _fake(monkeypatch, {"modal": 503, "meta": 429}, seen)
    _, meta = await extract_document(b"img", "image/png", chain_cfg())
    assert seen == ["modal", "meta", "spark"] and meta["served"].fell_back_from == ["modal", "meta"]


async def test_every_provider_down_is_one_plain_error(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    _fake(monkeypatch, {"modal": 503, "meta": 503, "spark": httpx.ConnectError("no route")}, seen)
    with pytest.raises(ExtractionError):
        await extract_document(b"img", "image/png", chain_cfg())
    assert seen == ["modal", "meta", "spark"]


@pytest.mark.parametrize("status", [400, 413, 422])
async def test_no_failover_on_our_own_bad_request(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    seen: list[str] = []
    _fake(monkeypatch, {"modal": status}, seen)
    with pytest.raises(ExtractionError, match=f"HTTP {status}"):
        await extract_document(b"img", "image/png", chain_cfg())
    assert seen == ["modal"]
    assert chain.BREAKER.failures.get("modal", 0) == 0  # our mistake is not the provider's failure


async def test_no_failover_on_a_reply_that_does_not_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    garbage = lambda r: httpx.Response(200, json={"message": {"content": "not json"}})  # noqa: E731
    _fake(monkeypatch, {"modal": garbage}, seen)
    with pytest.raises(ExtractionError):
        await extract_document(b"img", "image/png", chain_cfg())
    assert seen == ["modal"]


async def test_own_key_never_falls_over_to_the_servers_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    requests = _fake(monkeypatch, {"meta": 503}, seen)
    own = AiConfig.from_headers({"X-AI-Mode": "key", "X-Meta-Api-Key": "users-own-key"})
    with pytest.raises(ExtractionError, match="HTTP 503"):
        await extract_document(b"img", "image/png", own)
    assert seen == ["meta"] and requests[0].headers["authorization"] == "Bearer users-own-key"
    for _ in range(5):  # and no breaker: a user's own backend is always tried
        with pytest.raises(ExtractionError):
            await extract_document(b"img", "image/png", own)
    assert seen == ["meta"] * 6


async def test_modal_proxy_auth_and_meta_key_go_to_their_own_provider_only(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    requests = _fake(monkeypatch, {"modal": 503}, seen)
    await extract_document(b"img", "image/png", chain_cfg())
    modal, meta = requests
    assert modal.headers["modal-key"] == "tok-id" and modal.headers["modal-secret"] == "tok-secret"
    assert "authorization" not in modal.headers
    assert meta.headers["authorization"] == "Bearer server-meta-key" and "modal-key" not in meta.headers


# --------------------------------------------------------------------------- #
# Circuit breaker
# --------------------------------------------------------------------------- #


async def test_breaker_skips_a_dead_provider_then_retries_after_the_cool_down(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    _fake(monkeypatch, {"modal": httpx.ConnectError("down")}, seen)
    cfg = chain_cfg()
    for _ in range(chain.BREAKER_FAILURES):
        await extract_document(b"img", "image/png", cfg)
    assert seen.count("modal") == chain.BREAKER_FAILURES and chain.BREAKER.is_open("modal")
    seen.clear()
    _, meta = await extract_document(b"img", "image/png", cfg)
    assert seen == ["meta"] and meta["served"].fell_back_from == []  # skipped, not tried
    assert chain.BREAKER.state("modal")["circuit"] == "open"

    chain.BREAKER.open_until["modal"] = 0.0  # the cool-down is over
    seen.clear()
    _fake(monkeypatch, {}, seen)
    _, meta = await extract_document(b"img", "image/png", cfg)
    assert seen == ["modal"] and meta["served"].provider == "modal"
    assert chain.BREAKER.failures["modal"] == 0 and not chain.BREAKER.is_open("modal")


async def test_with_every_circuit_open_they_are_still_tried(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("modal", "meta", "spark"):
        for _ in range(chain.BREAKER_FAILURES):
            chain.BREAKER.failure(name, "HTTP 503")
    seen: list[str] = []
    _fake(monkeypatch, {"modal": 503}, seen)
    _, meta = await extract_document(b"img", "image/png", chain_cfg())
    assert seen == ["modal", "meta"] and meta["served"].provider == "meta"


# --------------------------------------------------------------------------- #
# Who served it: recorded on every result
# --------------------------------------------------------------------------- #


async def test_verifier_result_records_its_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    reading = {
        "seller": "Screwfix Direct Ltd",
        "vat_registration": "GB232456789",
        "issue_date": "2026-10-21",
        "amount_before_vat": 32.06,
        "vat_amount": 6.41,
        "amount_payable": 38.47,
    }
    seen: list[str] = []
    _fake(monkeypatch, {"modal": 503, "meta": lambda r: _ok(r, reading)}, seen)
    v = await verify_mod.verify(b"img", _doc(), chain_cfg(), mime="image/png", env={})
    assert v is not None and v.agree_all and v.error is None
    assert v.served_by is not None and (v.served_by.provider, v.served_by.fell_back_from) == ("meta", ["modal"])
    assert v.model == "meta:muse-spark-1.3"


async def test_verifier_with_every_provider_down_is_an_error_not_agreement(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake(monkeypatch, {"modal": 503, "meta": 503, "spark": 503}, [])
    v = await verify_mod.verify(b"img", _doc(), chain_cfg(), mime="image/png", env={})
    assert v is not None and v.error and not v.agree_all and v.served_by is None


async def test_json_calls_record_who_served_them(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake(monkeypatch, {"modal": 502, "meta": lambda r: _ok(r, {"x": 1})}, [])
    chain.clear_served()
    text = await ask_ai.call_json_model([], chain_cfg(), {}, "mail_triage")
    assert json.loads(text) == {"x": 1}
    served = chain.take_served()
    assert served is not None and served.provider == "meta" and served.fell_back_from == ["modal"]
    assert chain.take_served() is None
    calls = chain.recent()
    assert [(c.provider, c.ok, c.task) for c in calls[:2]] == [
        ("meta", True, "mail_triage"),
        ("modal", False, "mail_triage"),
    ]
    assert calls[1].error == "HTTP 502"


async def test_stream_fails_over_before_the_first_token_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def ollama_stream(request: httpx.Request) -> httpx.Response:
        lines = [
            {"message": {"content": '{"answer_md":"Hi"}'}, "done": False},
            {"message": {"content": ""}, "done": True},
        ]
        return httpx.Response(200, text="\n".join(json.dumps(x) for x in lines) + "\n")

    seen: list[str] = []
    _fake(monkeypatch, {"modal": 503, "meta": 503, "spark": ollama_stream}, seen)
    chain.clear_served()
    got = [t async for t in ask_ai.stream_json_model([], chain_cfg(), {}, "ask_answer")]
    assert got == ['{"answer_md":"Hi"}'] and seen == ["modal", "meta", "spark"]
    served = chain.take_served()
    assert served is not None and served.provider == "spark" and served.fell_back_from == ["modal", "meta"]


def test_no_answer_names_the_providers_never_their_addresses() -> None:
    assert chain.trouble(chain_cfg(), "x") == "None of the server's AI providers answered (modal, meta, spark)."
    own = AiConfig.from_headers({"X-AI-Mode": "local", "X-AI-Base-Url": SPARK})
    assert chain.trouble(own, f"could not be reached at {SPARK}") == f"Your AI (local) could not be reached at {SPARK}."


# --------------------------------------------------------------------------- #
# Routes: /ai/health, /ai/calls, /ai/warm, /health
# --------------------------------------------------------------------------- #


def _client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_ai_health_probes_meta_and_spark_and_leaves_modal_passive(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def tags(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "muse-glimmer:30b"}]})

    def models(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "muse-spark-1.3"}]})

    _fake(monkeypatch, {"meta": models, "spark": tags}, seen)
    r = _client().get("/ai/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chain"] == ["modal", "meta", "spark"] and not body["cached"]
    by = {p["name"]: p for p in body["providers"]}
    assert by["modal"]["status"] == "idle" and by["meta"]["status"] == "up" and by["spark"]["status"] == "up"
    assert "modal" not in seen  # a probe would start a paid GPU container
    for secret in (*SECRETS, MODAL, SPARK, "modal.run"):
        assert secret not in r.text
    again = _client().get("/ai/health").json()
    assert again["cached"] and sorted(seen) == ["meta", "spark"]  # cached: no second probe


def test_ai_health_reports_a_down_provider_and_an_open_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_HEALTH_PROBE_MODAL", "1")
    for _ in range(chain.BREAKER_FAILURES):
        chain.BREAKER.failure("meta", "HTTP 503")
    _fake(monkeypatch, {"modal": httpx.ConnectError("x"), "meta": 503, "spark": 404}, [])
    by = {p["name"]: p for p in _client().get("/ai/health").json()["providers"]}
    assert by["modal"]["status"] == "down" and by["modal"]["detail"] == "connection refused"
    assert by["meta"]["status"] == "down" and by["meta"]["circuit"] == "open" and by["meta"]["retry_in_s"] > 0
    assert by["spark"]["detail"] == "HTTP 404"


def test_ai_calls_lists_recent_calls_without_content(monkeypatch: pytest.MonkeyPatch) -> None:
    chain._record("extract", chain_cfg(), 0.0, True, ["modal"])
    calls = _client().get("/ai/calls").json()
    assert calls[0]["task"] == "extract" and calls[0]["fell_back_from"] == ["modal"]
    assert set(calls[0]) == {"at", "task", "provider", "model", "latency_ms", "ok", "fell_back_from", "error"}


def test_warm_pings_modal_once_a_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    pinged: list[str] = []

    async def fake_ping(c: AiConfig) -> None:
        pinged.append(c.provider)

    async def warmed() -> None:  # the ping runs in the background: wait for it, not for the clock
        await asyncio.gather(*routes_ai._warming)

    monkeypatch.setattr(routes_ai, "_ping", fake_ping)
    client = _client()
    # One event loop for every request: without it each request's loop ends with the response, and the background
    # ping might never run (it did not, on CI).
    with client:
        first = client.post("/ai/warm").json()
        second = client.post("/ai/warm").json()
        client.portal.call(warmed)  # type: ignore[union-attr]
    assert first["warming"] and second["warming"] and pinged == ["modal"]
    routes_ai.reset()
    chain.BREAKER.success("modal")
    assert not client.post("/ai/warm").json()["warming"]  # already warm
    monkeypatch.delenv("MODAL_GLIMMER_URL")
    routes_ai.reset()
    assert client.post("/ai/warm").json() == {
        "ok": True,
        "warming": False,
        "detail": "No Modal provider in this server's chain.",
    }


async def test_warm_ping_sends_proxy_auth_and_marks_modal_warm(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = _fake(monkeypatch, {"modal": lambda r: httpx.Response(200, json={"models": []})}, [])
    modal = chain_cfg().chain()[0]
    await routes_ai._ping(modal)
    assert requests[0].url.path == "/api/tags" and requests[0].headers["modal-key"] == "tok-id"
    assert chain.BREAKER.state("modal")["last_ok_s_ago"] == 0


def test_health_shows_the_chain_without_secrets() -> None:
    r = _client().get("/health")
    ai = r.json()["ai"]
    assert ai["chain"] == ["modal", "meta", "spark"] and ai["configured"] == ["modal", "meta", "spark"]
    assert ai["recommended"] == "modal,meta,spark"
    for secret in (*SECRETS, MODAL, SPARK):
        assert secret not in r.text


def test_test_mode_points_every_provider_at_the_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", "1")
    monkeypatch.setenv("ACCNOMOS_TEST_AI_BASE", "http://127.0.0.1:1/__test/ai")
    monkeypatch.setenv("ACCNOMOS_TEST_AI_DOWN", "modal")
    cfg = chain_cfg()
    assert [c.provider for c in cfg.chain()] == ["modal", "meta", "spark"]
    assert {c.base_url for c in cfg.chain()} == {"http://127.0.0.1:1/__test/ai/down", "http://127.0.0.1:1/__test/ai"}
    assert all(c.api_key is None and c.mode == "local" for c in cfg.chain())
