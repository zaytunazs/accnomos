"""The user's choice of which AI answers first (X-AI-Route, app/ai/config.py `apply_route`, app/ai/chain.py `accept`),
on fake transports only: no request here reaches Meta or a Spark."""

from __future__ import annotations

import httpx
import pytest
from test_ai_providers import ENV, META, SPARK, _fake

from app import routes_ai
from app.ai import stt
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError, extract_document

GARBAGE = lambda r: httpx.Response(200, json={"message": {"content": "I think it was about forty pounds"}})  # noqa: E731


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("ACCNOMOS_TEST_MODE", "AI_MODE", "VERIFIER", "BASETEN_API_KEY", "ACCNOMOS_TEST_AI_DOWN"):
        monkeypatch.delenv(k, raising=False)
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("AI_PROVIDERS", "meta,spark")  # the live server's chain
    monkeypatch.delenv("MODAL_GLIMMER_URL")
    routes_ai.reset()


def routed(route: str | None, **headers: str) -> AiConfig:
    h = dict(headers)
    if route is not None:
        h["X-AI-Route"] = route
    return AiConfig.from_headers(h)


def names(cfg: AiConfig) -> list[str]:
    return [c.provider for c in cfg.chain()]


def test_no_route_and_an_unknown_route_change_nothing() -> None:
    assert names(routed(None)) == ["meta", "spark"]
    assert routed(None).route is None
    assert names(routed("cheapest")) == ["meta", "spark"]


def test_the_three_routes_order_the_servers_chain() -> None:
    assert names(routed("meta_first")) == ["meta", "spark"]
    assert names(routed("local_first")) == ["spark", "meta"]
    assert names(routed("local_only")) == ["spark"]
    assert all(c.route == "local_first" for c in routed("local_first").chain())


def test_meta_first_puts_the_servers_spark_last_even_when_listed_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDERS", "spark,meta")
    assert names(routed("meta_first")) == ["meta", "spark"]


def test_own_computer_first_then_the_servers_meta_api() -> None:
    cfg = routed("local_first", **{"X-AI-Mode": "local", "X-AI-Base-Url": SPARK})
    assert [(c.provider, c.local) for c in cfg.chain()] == [("local", True), ("meta", False)]
    only = routed("local_only", **{"X-AI-Mode": "local", "X-AI-Base-Url": SPARK})
    assert names(only) == ["local"]


def test_own_key_with_local_only_never_uses_the_key() -> None:
    cfg = routed("local_only", **{"X-AI-Mode": "key", "X-Meta-Api-Key": "users-own-key"})
    assert names(cfg) == ["spark"]
    assert all(c.api_key is None for c in cfg.chain())


def test_local_only_with_no_local_model_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDERS", "meta")
    with pytest.raises(ValueError, match="no local model"):
        routed("local_only")
    assert names(routed("local_first")) == ["meta"]  # nothing local to try first: the Meta API, as before


async def test_local_first_stays_local_when_the_answer_is_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    _fake(monkeypatch, {}, seen)
    doc, meta = await extract_document(b"img", "image/png", routed("local_first"))
    assert doc.supplier_name == "Screwfix Direct Ltd"
    assert seen == ["spark"] and meta["served"].provider == "spark"


async def test_local_first_asks_the_meta_api_when_the_local_answer_is_unclear(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    _fake(monkeypatch, {"spark": GARBAGE}, seen)
    doc, meta = await extract_document(b"img", "image/png", routed("local_first"))
    assert doc.supplier_name == "Screwfix Direct Ltd"
    assert seen == ["spark", "meta"]
    assert (meta["served"].provider, meta["served"].fell_back_from) == ("meta", ["spark"])


async def test_local_first_asks_the_meta_api_when_the_local_model_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    _fake(monkeypatch, {"spark": httpx.ConnectError("offline")}, seen)
    _, meta = await extract_document(b"img", "image/png", routed("local_first"))
    assert seen == ["spark", "meta"] and meta["served"].provider == "meta"


async def test_meta_first_still_does_not_retry_an_unclear_meta_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    garbage = lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})  # noqa: E731
    _fake(monkeypatch, {"meta": garbage}, seen)
    with pytest.raises(ExtractionError):
        await extract_document(b"img", "image/png", routed("meta_first"))
    assert seen == ["meta"]


async def test_local_only_never_reaches_the_meta_api(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    requests = _fake(monkeypatch, {"spark": GARBAGE}, seen)
    with pytest.raises(ExtractionError):
        await extract_document(b"img", "image/png", routed("local_only"))
    seen.clear()
    _fake(monkeypatch, {"spark": httpx.ConnectError("offline")}, seen)
    with pytest.raises(ExtractionError):
        await extract_document(b"img", "image/png", routed("local_only"))
    assert "meta" not in seen
    assert all(not str(r.url).startswith(META) for r in requests)


def test_local_only_turns_off_muse_voice_transcribe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPARK_WHISPER_URL", raising=False)
    assert stt.chain(routed(None)) == []  # the default (STT_PROVIDER=local) never sends the server's recordings to Meta
    monkeypatch.setenv("STT_PROVIDER", "meta")
    assert [p.name for p in stt.chain(routed(None))] == ["muse"]
    assert stt.chain(routed("local_only")) == []
    monkeypatch.setenv("SPARK_WHISPER_URL", "http://spark.invalid:8000/v1")
    assert [p.name for p in stt.chain(routed("local_only"))] == ["whisper"]  # a local speech model still may
