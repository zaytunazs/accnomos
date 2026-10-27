"""AI judgement on duplicate groups: prompt shape, both backends, failures, blocked groups. HTTP is faked."""

from __future__ import annotations

from typing import Any

import pytest

from app import contacts as cb
from app.ai import duplicates as dup
from app.ai.config import AiConfig


def _contact(cid: str, name: str, **kw) -> cb.Contact:
    from app.autopilot import supplier_key

    return cb.Contact(id=cid, kind="supplier", name=name, normalised_key=supplier_key(name), **kw)


class _Resp:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> Any:
        return self._payload


class _Client:
    """Fake httpx.AsyncClient: `reply` is the Ollama or Meta body the one POST returns."""

    reply: Any = {}
    seen: list[dict[str, Any]] = []

    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *a: Any) -> None:
        pass

    async def post(self, url: str, **kw: Any) -> _Resp:
        _Client.seen.append({"url": url, **kw})
        return _Resp(_Client.reply)


@pytest.fixture
def fake_http(monkeypatch: pytest.MonkeyPatch) -> type[_Client]:
    _Client.seen = []
    monkeypatch.setattr(dup.httpx, "AsyncClient", _Client)
    return _Client


def _cfg(mode: str = "local") -> AiConfig:
    return AiConfig(mode=mode, base_url="http://stub", model="stub", api_key="k" if mode == "key" else None)


def test_prompt_pins_first_name_line_for_the_stub() -> None:
    prompt = dup.judgement_prompt(
        [{"name": "Screwfix", "kind": "supplier", "vrn": None, "email": "t@s.example", "phone": None, "address": None}],
        ["same email t@s.example"],
    )
    assert '1. "Screwfix"' in prompt and "- same email t@s.example" in prompt


def test_schema_is_strict() -> None:
    schema = dup.judgement_json_schema()
    assert schema["required"] == ["same", "confidence", "keep_name", "reason"]
    assert schema["additionalProperties"] is False


async def test_local_backend_parses_ollama_reply(fake_http: type[_Client]) -> None:
    import json as _json

    fake_http.reply = {
        "message": {
            "content": _json.dumps(
                {"same": True, "confidence": 0.8, "keep_name": "Screwfix", "reason": "Same VAT and email."}
            )
        }
    }
    view = await dup.judge_duplicate([{"name": "Screwfix"}], ["same email x"], _cfg("local"))
    assert view == {"same": True, "confidence": 0.8, "keep_name": "Screwfix", "reason": "Same VAT and email."}
    assert fake_http.seen[0]["url"] == "http://stub/api/chat"


async def test_key_backend_parses_meta_reply(fake_http: type[_Client]) -> None:
    import json as _json

    body = _json.dumps({"same": False, "confidence": 0.7, "keep_name": "", "reason": "Two firms, one word."})
    fake_http.reply = {"choices": [{"message": {"content": body}}], "usage": {}}
    view = await dup.judge_duplicate([{"name": "A"}], ["share name word: builders"], _cfg("key"))
    assert view["same"] is False and view["confidence"] == 0.7
    assert fake_http.seen[0]["url"] == "http://stub/chat/completions"
    assert fake_http.seen[0]["headers"] == {"Authorization": "Bearer k"}


async def test_unusable_model_output_is_a_judgement_error(fake_http: type[_Client]) -> None:
    fake_http.reply = {"message": {"content": "not json at all {{{{"}}
    with pytest.raises(dup.JudgementError):
        await dup.judge_duplicate([{"name": "A"}], ["same email x"], _cfg())
    fake_http.reply = {"message": {"content": '{"same": true}'}}
    with pytest.raises(dup.JudgementError):
        await dup.judge_duplicate([{"name": "A"}], ["same email x"], _cfg())


async def test_http_failure_is_a_judgement_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    class Failing(_Client):
        async def post(self, url: str, **kw: Any) -> _Resp:
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(dup.httpx, "AsyncClient", Failing)
    with pytest.raises(dup.JudgementError):
        await dup.judge_duplicate([{"name": "A"}], ["same email x"], _cfg())


async def test_blocked_groups_never_reach_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    async def explode(*a: Any, **k: Any) -> dict[str, Any]:
        raise AssertionError("blocked groups must not call the model")

    monkeypatch.setattr(dup, "judge_duplicate", explode)
    a = _contact("a" * 16, "Alpha", vrn="GB111111111", email="same@example.co.uk")
    b = _contact("b" * 16, "Beta", vrn="GB222222222", email="same@example.co.uk")
    (g,) = cb.find_duplicate_groups([a, b])
    assert g.blocked
    (judged,) = await cb.judge_groups([g], [a, b], _cfg())
    assert judged.ai is not None and judged.ai.same is False and judged.ai.confidence == 1.0


async def test_model_failure_leaves_ai_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(*a: Any, **k: Any) -> dict[str, Any]:
        raise dup.JudgementError("down")

    monkeypatch.setattr(dup, "judge_duplicate", fail)
    a = _contact("a" * 16, "Screwfix", email="same@example.co.uk")
    b = _contact("b" * 16, "Screwfix Direct", email="same@example.co.uk")
    (g,) = cb.find_duplicate_groups([a, b])
    (judged,) = await cb.judge_groups([g], [a, b], _cfg())
    assert judged.ai is None and judged.evidence
