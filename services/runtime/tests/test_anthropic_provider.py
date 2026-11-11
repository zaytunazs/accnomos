"""The `anthropic` provider (app/ai/anthropic.py) and the chain `spark,anthropic` (owner's decision, 11 Nov 2026), the
Verifier's provider choice (VERIFIER_PROVIDER) and the backup's place under X-AI-Route. Fake transports only: no
request here reaches Anthropic or a Spark."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx
import pytest

from app.ai import anthropic, chain, providers
from app.ai import ask as ask_ai
from app.ai import verify as verify_mod
from app.ai.classify import classify
from app.ai.config import AiConfig, apply_route
from app.ai.crop import sam_config
from app.ai.extract import extract_document
from app.schemas import ExtractedDoc, ExtractedLine

SPARK = "http://spark.invalid:11434"
API = "https://api.anthropic.invalid/v1"
KEY = "sk-ant-SECRET-4444"
ENV = {
    "AI_PROVIDERS": "spark,anthropic",
    "OLLAMA_BASE": SPARK,
    "ANTHROPIC_API_KEY": KEY,
    "ANTHROPIC_BASE": API,
}
PNG = b"\x89PNG\r\n\x1a\nfake"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "ACCNOMOS_TEST_MODE",
        "AI_MODE",
        "VERIFIER",
        "VERIFIER_PROVIDER",
        "BASETEN_API_KEY",
        "BASETEN_ENABLED",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_VERIFY_MODEL",
        "ANTHROPIC_VERSION",
        "ANTHROPIC_MAX_TOKENS",
        "META_API_KEY",
        "MODAL_GLIMMER_URL",
        "SAM_CROP",
    ):
        monkeypatch.delenv(k, raising=False)
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    chain.BREAKER.reset()


def _doc() -> dict[str, Any]:
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
    ).model_dump(mode="json")


def _message(content: dict[str, Any] | str, usage: dict[str, int] | None = None) -> dict[str, Any]:
    text = content if isinstance(content, str) else json.dumps(content)
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": usage or {"input_tokens": 1200, "output_tokens": 180},
    }


def _fake(monkeypatch: pytest.MonkeyPatch, spark: Any, claude: Any) -> list[httpx.Request]:
    """Every httpx client answers: the Spark (Ollama-shaped) and Anthropic (Messages API), each an int status, an
    exception, or a callable(request)."""
    real = httpx._client.AsyncClient
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        request.read()
        out = spark if str(request.url).startswith(SPARK) else claude
        if isinstance(out, Exception):
            raise out
        if callable(out):
            return out(request)
        if isinstance(out, int) and out != 200:
            return httpx.Response(out, json={"type": "error", "error": {"type": "fake", "message": "fake"}})
        if str(request.url).startswith(SPARK):
            return httpx.Response(200, json={"message": {"content": json.dumps(_doc())}, "done": True})
        return httpx.Response(200, json=_message(_doc()))

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return seen


def chain_cfg() -> AiConfig:
    return AiConfig.from_headers({})


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_spark_then_anthropic_with_its_defaults() -> None:
    spark, claude = chain_cfg().chain()
    assert (spark.provider, spark.local) == ("spark", True)
    assert (claude.provider, claude.mode, claude.local, claude.voice) == ("anthropic", "key", False, False)
    assert (claude.base_url, claude.model) == (API, "claude-haiku-5-5")
    assert claude.auth_headers() == {"anthropic-version": "2026-10-21", "x-api-key": KEY}
    assert "Authorization" not in claude.auth_headers()
    assert KEY not in repr(chain_cfg())
    assert providers.RECOMMENDED == "spark,anthropic"


def test_no_key_leaves_anthropic_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert [c.provider for c in chain_cfg().chain()] == ["spark"]
    info = {p.name: p for p in providers.describe()}["anthropic"]
    assert (info.configured, info.why_not, info.model) == (False, "ANTHROPIC_API_KEY is not set", "claude-haiku-5-5")


def test_model_version_and_default_base_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_BASE")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("ANTHROPIC_VERSION", "2023-06-01")
    claude = chain_cfg().chain()[1]
    assert (claude.base_url, claude.model) == ("https://api.anthropic.com/v1", "claude-sonnet-5-5")
    assert claude.auth_headers()["anthropic-version"] == "2023-06-01"


def test_test_mode_points_anthropic_at_the_stub_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", "1")
    monkeypatch.setenv("ACCNOMOS_TEST_AI_BASE", "http://127.0.0.1:1/__test/ai")
    cfg = chain_cfg()
    assert [c.provider for c in cfg.chain()] == ["spark", "anthropic"]
    assert all(c.mode == "local" and c.api_key is None for c in cfg.chain())
    assert not any(anthropic.is_anthropic(c) for c in cfg.chain())


def test_routes_keep_the_backup_last_and_local_only_never_reaches_it() -> None:
    assert [c.provider for c in apply_route(chain_cfg(), "meta_first").chain()] == ["spark", "anthropic"]
    assert [c.provider for c in apply_route(chain_cfg(), "local_first").chain()] == ["spark", "anthropic"]
    assert [c.provider for c in apply_route(chain_cfg(), "local_only").chain()] == ["spark"]


def test_sam_never_runs_on_the_anthropic_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAM_CROP", "1")
    assert sam_config(chain_cfg()) is None


# --------------------------------------------------------------------------- #
# Translation
# --------------------------------------------------------------------------- #


def test_body_translation_images_pdf_schema_effort_and_no_temperature() -> None:
    cfg = chain_cfg().chain()[1]
    schema = {
        "type": "object",
        "properties": {"n": {"type": "number", "minimum": 0}, "s": {"type": "string", "maxLength": 5}},
        "required": ["n", "s"],
        "additionalProperties": False,
    }
    body = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": "Be exact."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Read this."},
                    {"type": "image_url", "image_url": {"url": "data:image/jpg;base64,QUJD"}},
                    {"type": "image_url", "image_url": {"url": "data:application/pdf;base64,UERG"}},
                ],
            },
            {"role": "user", "content": "And this."},
        ],
        "response_format": {"type": "json_schema", "json_schema": {"name": "x", "strict": True, "schema": schema}},
        "reasoning_effort": "low",
        "temperature": 0,
    }
    out = anthropic.to_messages_body(body, cfg)
    assert out["system"] == "Be exact." and out["model"] == "claude-haiku-5-5" and out["max_tokens"] == 4096
    [turn] = out["messages"]  # the two user turns merged
    assert turn["role"] == "user"
    assert turn["content"][1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"},
    }
    assert turn["content"][2]["type"] == "document"
    assert turn["content"][2]["source"]["media_type"] == "application/pdf"
    assert turn["content"][3] == {"type": "text", "text": "And this."}
    sent = out["output_config"]["format"]["schema"]
    assert out["output_config"]["effort"] == "low" and out["output_config"]["format"]["type"] == "json_schema"
    assert "minimum" not in json.dumps(sent) and "maxLength" not in json.dumps(sent)
    assert schema["properties"]["n"]["minimum"] == 0  # the caller's schema is untouched
    assert "temperature" not in out and "response_format" not in out and "reasoning_effort" not in out
    plain = anthropic.to_messages_body(body, cfg, structured=False)
    assert "format" not in plain["output_config"] and '"required":["n","s"]' in plain["system"]


def test_reply_translation_and_usage() -> None:
    got = anthropic.to_openai(
        {
            "content": [
                {"type": "thinking", "thinking": "hmm"},
                {"type": "text", "text": '{"a":'},
                {"type": "text", "text": "1}"},
            ],
            "stop_reason": "max_tokens",
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 5, "output_tokens": 7},
        }
    )
    assert got["choices"][0]["message"]["content"] == '{"a":1}'
    assert got["choices"][0]["finish_reason"] == "length"
    assert got["usage"] == {"prompt_tokens": 15, "completion_tokens": 7, "total_tokens": 22}


# --------------------------------------------------------------------------- #
# Calls on a fake transport
# --------------------------------------------------------------------------- #


async def test_post_chat_wire_format_and_usage_logged_without_content(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_message({"kind": "receipt"}))

    cfg = chain_cfg().chain()[1]
    body = {"model": cfg.model, "messages": [{"role": "user", "content": "SECRET-DOCUMENT-TEXT"}]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        r = await anthropic.post_chat(client, cfg, body)
    r.raise_for_status()
    assert r.json()["choices"][0]["message"]["content"] == '{"kind": "receipt"}'
    assert r.json()["usage"]["prompt_tokens"] == 1200
    [req] = seen
    assert str(req.url) == API + "/messages"
    assert req.headers["x-api-key"] == KEY and req.headers["anthropic-version"] == "2026-10-21"
    assert "authorization" not in req.headers
    assert "provider=anthropic model=claude-haiku-5-5 prompt_tokens=1200 completion_tokens=180" in caplog.text
    assert "SECRET-DOCUMENT-TEXT" not in caplog.text and KEY not in caplog.text


async def test_a_refused_schema_is_sent_once_more_with_the_schema_in_the_prompt() -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        if "format" in sent[-1].get("output_config", {}):
            return httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error"}})
        return httpx.Response(200, json=_message({"ok": True}))

    cfg = chain_cfg().chain()[1]
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    body = {
        "messages": [{"role": "user", "content": "x"}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "x", "schema": schema}},
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        r = await anthropic.post_chat(client, cfg, body)
    assert r.status_code == 200 and len(sent) == 2
    assert "JSON Schema" in sent[1]["system"]


async def test_extraction_falls_over_from_the_spark_to_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _fake(monkeypatch, spark=httpx.ConnectError("Spark offline"), claude=200)
    doc, meta = await extract_document(PNG, "image/png", chain_cfg())
    assert doc.supplier_name == "Screwfix Direct Ltd"
    served = meta["served"]
    assert (served.provider, served.model, served.fell_back_from) == ("anthropic", "claude-haiku-5-5", ["spark"])
    assert meta["usage"]["completion_tokens"] == 180
    claude_req = seen[-1]
    assert str(claude_req.url) == API + "/messages"
    sent = json.loads(claude_req.content)
    image = sent["messages"][0]["content"][1]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/png"
    assert base64.b64decode(image["source"]["data"]) == PNG
    assert "Return only the JSON" in sent["system"] and "format" in sent["output_config"]


async def test_the_spark_answering_sends_nothing_to_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _fake(monkeypatch, spark=200, claude=AssertionError("must not be called"))
    _doc_, meta = await extract_document(PNG, "image/png", chain_cfg())
    assert meta["served"].provider == "spark"
    assert all(str(r.url).startswith(SPARK) for r in seen)


async def test_our_own_bad_request_does_not_fall_over_but_overload_does(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake(monkeypatch, spark=httpx.ConnectError("down"), claude=529)
    with pytest.raises(Exception):  # noqa: B017 - both down: the extraction error names the last provider's status
        await extract_document(PNG, "image/png", chain_cfg())
    assert chain.BREAKER.state("anthropic")["last_error"] == "HTTP 529"


async def test_classify_on_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    def claude(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_message({"kind": "receipt", "confidence": 0.9, "reason": "till slip"}))

    _fake(monkeypatch, spark=503, claude=claude)
    guess = await classify(None, None, chain_cfg(), text="TESCO total 4.50")
    assert (guess.kind, guess.by) == ("receipt", "ai")


async def test_ask_json_and_stream_on_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    sse = "".join(
        f"event: {e['type']}\ndata: {json.dumps(e)}\n\n"
        for e in (
            {"type": "message_start", "message": {"usage": {"input_tokens": 50, "output_tokens": 1}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": '{"answer'}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": '": "hi"}'}},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 9}},
            {"type": "message_stop"},
        )
    )

    def claude(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content).get("stream"):
            return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=_message({"answer": "hi"}))

    _fake(monkeypatch, spark=httpx.ConnectError("down"), claude=claude)
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]
    text = await ask_ai.call_json_model(msgs, chain_cfg(), schema, "t")
    assert json.loads(text) == {"answer": "hi"}
    chunks = [c async for c in ask_ai.stream_json_model(msgs, chain_cfg(), schema, "t")]
    assert "".join(chunks) == '{"answer": "hi"}' and len(chunks) == 2


async def test_a_stream_error_event_before_any_text_fails_over() -> None:
    sse = 'event: error\ndata: {"type": "error", "error": {"type": "overloaded_error"}}\n\n'

    async def lines(r: httpx.Response):
        async for ln in r.aiter_lines():
            yield ln

    cfg = chain_cfg().chain()[1]
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, text=sse))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(chain.ProviderDown):
            _ = [t async for t in anthropic.stream_chat(client, cfg, {"messages": []}, lines)]


# --------------------------------------------------------------------------- #
# The Verifier's provider (VERIFIER_PROVIDER)
# --------------------------------------------------------------------------- #


def test_verifier_follows_the_chain_by_default() -> None:
    vc = verify_mod.verifier_chain(chain_cfg())
    assert vc is not None and [c.provider for c in vc.chain()] == ["spark", "anthropic"]


def test_verifier_provider_anthropic_reads_second_with_its_own_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERIFIER_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_VERIFY_MODEL", "claude-sonnet-5-5")
    vc = verify_mod.verifier_chain(chain_cfg())
    assert vc is not None and [(c.provider, c.model) for c in vc.chain()] == [
        ("anthropic", "claude-sonnet-5-5"),
        ("spark", "muse-glimmer:30b"),
    ]
    assert verify_mod.select_backend(chain_cfg()).kind == "anthropic"  # type: ignore[union-attr]


def test_verifier_provider_spark_and_unconfigured_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDERS", "anthropic,spark")
    monkeypatch.setenv("VERIFIER_PROVIDER", "spark")
    vc = verify_mod.verifier_chain(chain_cfg())
    assert vc is not None and [c.provider for c in vc.chain()] == ["spark", "anthropic"]
    monkeypatch.setenv("AI_PROVIDERS", "spark")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("VERIFIER_PROVIDER", "anthropic")
    vc = verify_mod.verifier_chain(chain_cfg())
    assert vc is not None and [c.provider for c in vc.chain()] == ["spark"]
    monkeypatch.setenv("VERIFIER_PROVIDER", "nonsense")
    assert verify_mod.verifier_provider({"VERIFIER_PROVIDER": "nonsense"}) == "chain"


def test_verifier_provider_anthropic_joins_a_chain_without_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDERS", "spark")
    monkeypatch.setenv("VERIFIER_PROVIDER", "anthropic")
    vc = verify_mod.verifier_chain(chain_cfg())
    assert vc is not None and [c.provider for c in vc.chain()] == ["anthropic", "spark"]


async def test_verifier_reads_on_anthropic_while_the_reader_was_the_spark(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERIFIER_PROVIDER", "anthropic")
    reading = {
        "seller": "Screwfix Direct Ltd",
        "vat_registration": "GB 232 4567 89",
        "issue_date": "2026-10-21",
        "amount_before_vat": 32.06,
        "vat_amount": 6.41,
        "amount_payable": 38.47,
    }
    seen = _fake(
        monkeypatch,
        spark=AssertionError("the verifier must not read on the Spark"),
        claude=lambda _r: httpx.Response(200, json=_message(reading)),
    )
    v = await verify_mod.verify(PNG, ExtractedDoc.model_validate(_doc()), chain_cfg(), mime="image/png")
    assert v is not None and v.error is None and v.agree_all
    assert v.model == "anthropic:claude-haiku-5-5"
    assert [str(r.url) for r in seen] == [API + "/messages"]
    sent = json.loads(seen[0].content)
    assert "temperature" not in sent and sent["output_config"]["effort"] == "low"
