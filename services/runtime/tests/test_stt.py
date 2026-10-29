"""Speech-to-text chain (app/ai/stt.py): which providers a request gets, Muse Voice Transcribe first and Whisper on the
Spark as the fallback, the provenance on proposals and in the actions audit log, and that no key reaches a log line,
an error or an answer. All HTTP is faked with httpx.MockTransport in the documented shapes; nothing calls Meta.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app import actions, jobs
from app import payrun as PR
from app.actions import IntentModelOutput
from app.ai import ask as ask_ai
from app.ai import providers as ai_providers
from app.ai import stt, voice
from app.ai.config import AiConfig
from app.books import Books
from app.jobs import Job, StaffMember, TimesheetEntry

USER_KEY = "user-key-SECRET-1111"
SERVER_KEY = "server-key-SECRET-2222"
WHISPER_KEY = "whisper-key-SECRET-3333"
SECRETS = (USER_KEY, SERVER_KEY, WHISPER_KEY)
META_BASE = "https://api.meta.invalid/v1"
WHISPER_BASE = "http://spark.invalid:8000/v1"

USER_CFG = AiConfig(mode="key", base_url=META_BASE, model="muse-spark-1.3", api_key=USER_KEY, provider="key")
LOCAL_CFG = AiConfig(mode="local", base_url="http://ollama.invalid", model="muse-glimmer:30b", provider="local")
ENV = {"META_API_KEY": SERVER_KEY, "MODEL_API_BASE": META_BASE, "SPARK_WHISPER_URL": WHISPER_BASE + "/"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "META_API_KEY",
        "MODEL_API_BASE",
        "SPARK_WHISPER_URL",
        "SPARK_WHISPER_KEY",
        "SPARK_WHISPER_MODEL",
        "STT_PROVIDERS",
        "AI_PROVIDERS",
        "ACCNOMOS_TEST_MODE",
        "MUSE_STT_TIMEOUT_S",
        "WHISPER_STT_TIMEOUT_S",
    ):
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------- #
# Which providers, in which order
# --------------------------------------------------------------------------- #


def test_users_own_key_is_used_for_muse_then_whisper():
    got = stt.chain(USER_CFG, ENV)
    assert [(p.name, p.key_source, p.base_url) for p in got] == [
        ("muse", "user", META_BASE),
        ("whisper", "none", WHISPER_BASE),
    ]
    assert got[0].key == USER_KEY and got[0].model == "muse-voice-transcribe-1.0"


def test_local_mode_uses_the_servers_meta_key_when_set():
    [muse, whisper] = stt.chain(LOCAL_CFG, ENV)
    assert (muse.name, muse.key_source, muse.key) == ("muse", "server", SERVER_KEY)
    assert whisper.name == "whisper"


def test_server_chain_uses_its_meta_provider():
    env = {"AI_PROVIDERS": "modal,meta,spark", "META_API_KEY": SERVER_KEY, "MODEL_API_BASE": META_BASE}
    cfg = ai_providers.chain_config(env)
    [muse] = stt.chain(cfg, env)
    assert (muse.key_source, muse.key, muse.base_url) == ("server", SERVER_KEY, META_BASE)


def test_no_meta_key_means_whisper_only_and_nothing_means_empty():
    assert [p.name for p in stt.chain(LOCAL_CFG, {"SPARK_WHISPER_URL": WHISPER_BASE})] == ["whisper"]
    assert stt.chain(LOCAL_CFG, {}) == []


def test_order_and_timeouts_from_env():
    env = {
        **ENV,
        "STT_PROVIDERS": "whisper, muse, bogus, whisper",
        "MUSE_STT_TIMEOUT_S": "7",
        "WHISPER_STT_TIMEOUT_S": "x",
    }
    got = stt.chain(LOCAL_CFG, env)
    assert [(p.name, p.timeout_s) for p in got] == [("whisper", 90.0), ("muse", 7.0)]
    assert [p.name for p in stt.chain(LOCAL_CFG, {**ENV, "STT_PROVIDERS": "muse"})] == ["muse"]


def test_test_mode_has_no_speech_to_text(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", "1")
    assert stt.chain(USER_CFG, ENV) == []


def test_keys_are_not_in_repr_or_describe():
    env = {**ENV, "SPARK_WHISPER_KEY": WHISPER_KEY}
    shown = repr(stt.chain(USER_CFG, env)) + json.dumps(stt.describe(env))
    assert not any(s in shown for s in SECRETS)
    assert WHISPER_BASE not in json.dumps(stt.describe(env))
    assert [d["name"] for d in stt.describe(env) if d["configured"]] == ["muse", "whisper"]


# --------------------------------------------------------------------------- #
# The chain on faked HTTP
# --------------------------------------------------------------------------- #


class Fake:
    """Answers Muse at {META_BASE}/asr/transcribe and Whisper at {WHISPER_BASE}/audio/transcriptions."""

    def __init__(self, muse: Any, whisper: Any = None) -> None:
        self.muse, self.whisper = muse, whisper
        self.seen: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.seen.append(req)
        req.read()
        what = self.muse if req.url.path.endswith("/asr/transcribe") else self.whisper
        if isinstance(what, Exception):
            raise what
        if what is None:
            raise AssertionError(f"unexpected call to {req.url}")
        return what

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))

    def paths(self) -> list[str]:
        return [r.url.path for r in self.seen]


def muse_ok(text: str) -> httpx.Response:
    return httpx.Response(200, json={"sessionId": "S1", "transcript": text, "audioDurationMs": 2100, "turns": []})


def whisper_ok(text: str) -> httpx.Response:
    return httpx.Response(200, json={"text": text})


async def test_muse_first_and_whisper_not_called():
    fake = Fake(muse_ok(" Andy did 2 hours overtime. "))
    async with fake.client() as c:
        heard = await stt.transcribe(b"RIFFwav", stt.chain(USER_CFG, ENV), keywords=["Hendon"], client=c)
    assert heard.text == "Andy did 2 hours overtime."
    assert heard.by.model_dump() == {
        "provider": "muse",
        "label": "Muse Voice Transcribe",
        "model": "muse-voice-transcribe-1.0",
        "fallback_reason": None,
    }
    assert fake.paths() == ["/v1/asr/transcribe"]
    assert fake.seen[0].headers["Authorization"] == f"Bearer {USER_KEY}"


@pytest.mark.parametrize(
    "failure,why",
    [
        (httpx.Response(500), "Muse Voice returned HTTP 500"),
        (httpx.Response(429), "rate-limiting"),
        (httpx.Response(413), "too large"),
        (httpx.Response(400), "longer than 10 minutes"),
        (httpx.Response(401), "rejected the API key"),
        (httpx.ReadTimeout("slow"), "took longer than 45 s"),
        (httpx.ConnectError("down"), "could not be reached (ConnectError)"),
        (muse_ok("   "), "Didn't catch any words"),
    ],
)
async def test_whisper_takes_over_when_muse_fails(failure: Any, why: str):
    fake = Fake(failure, whisper_ok("Remember to order 2-inch bolts for the Hendon job."))
    async with fake.client() as c:
        heard = await stt.transcribe(b"RIFFwav", stt.chain(USER_CFG, ENV), client=c)
    assert heard.text == "Remember to order 2-inch bolts for the Hendon job."
    assert (heard.by.provider, heard.by.label) == ("whisper", "a local fallback model")
    assert heard.by.fallback_reason and heard.by.fallback_reason.startswith("Muse Voice Transcribe: ")
    assert why in heard.by.fallback_reason
    assert fake.paths() == ["/v1/asr/transcribe", "/v1/audio/transcriptions"]


async def test_whisper_request_shape():
    env = {**ENV, "SPARK_WHISPER_KEY": WHISPER_KEY, "SPARK_WHISPER_MODEL": "large-v3", "STT_PROVIDERS": "whisper"}
    fake = Fake(None, whisper_ok("Quote Harbour Cafe £450"))
    async with fake.client() as c:
        await stt.transcribe(b"RIFFwav", stt.chain(LOCAL_CFG, env), keywords=["Hendon", "Andy Smith"], client=c)
    req = fake.seen[0]
    assert str(req.url) == WHISPER_BASE + "/audio/transcriptions"
    assert req.headers["Authorization"] == f"Bearer {WHISPER_KEY}"
    body = req.content
    for part in (b'name="model"\r\n\r\nlarge-v3', b'name="language"\r\n\r\nen', b'name="response_format"\r\n\r\njson'):
        assert part in body
    assert b"Names: Hendon, Andy Smith." in body and b'name="file"; filename="question.wav"' in body


async def test_whisper_without_a_key_sends_no_authorization():
    fake = Fake(None, whisper_ok("hello"))
    async with fake.client() as c:
        await stt.transcribe(b"wav", stt.chain(LOCAL_CFG, {"SPARK_WHISPER_URL": WHISPER_BASE}), client=c)
    assert "Authorization" not in fake.seen[0].headers


async def test_both_fail_reports_muses_reason_and_the_fallback():
    fake = Fake(httpx.Response(429), httpx.Response(503))
    async with fake.client() as c:
        with pytest.raises(voice.VoiceError) as exc:
            await stt.transcribe(b"wav", stt.chain(USER_CFG, ENV), client=c)
    assert exc.value.status == 429
    assert "rate-limiting" in str(exc.value) and "the fallback failed too: a local fallback model" in str(exc.value)


async def test_only_one_provider_raises_its_own_error():
    fake = Fake(httpx.Response(401))
    async with fake.client() as c:
        with pytest.raises(voice.VoiceError) as exc:
            await stt.transcribe(b"wav", stt.chain(USER_CFG, {}), client=c)
    assert (exc.value.status, str(exc.value)) == (401, "Meta rejected the API key for Muse Voice")


async def test_no_providers_is_a_400():
    with pytest.raises(voice.VoiceError) as exc:
        await stt.transcribe(b"wav", [])
    assert exc.value.status == 400


async def test_no_key_in_logs_errors_or_results(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)  # httpx and httpcore included
    env = {**ENV, "SPARK_WHISPER_KEY": WHISPER_KEY}
    for muse, whisper in (
        (httpx.Response(401, text=f"bad {USER_KEY}"), whisper_ok("ok")),
        (httpx.Response(500), httpx.Response(401)),
    ):
        fake = Fake(muse, whisper)
        async with fake.client() as c:
            try:
                heard = await stt.transcribe(b"wav", stt.chain(USER_CFG, env), client=c)
                shown = heard.model_dump_json()
            except voice.VoiceError as exc:
                shown = str(exc)
        assert not any(s in shown for s in SECRETS), shown
    assert "speech-to-text: Muse Voice Transcribe failed" in caplog.text
    assert not any(s in caplog.text for s in SECRETS)


# --------------------------------------------------------------------------- #
# The route, the proposal and the audit trail
# --------------------------------------------------------------------------- #

TODAY = date(2026, 10, 27)  # Tuesday; "last week" is Mon 19 - Sun 25 Oct
H = {"X-Graph-Token": "t", "X-User": "owner@example.co.uk"}
HENDON = "Loft conversion, 14 Hendon Way"
OVERTIME = "Andy did 2 hours overtime at double time on the Hendon job last week"


async def _overtime_books() -> Books:
    b = Books(FakeStorageProvider())
    await b.ensure_tree()
    await jobs.save_job(b, Job(id="00000000a001", name=HENDON))
    await jobs.save_staff(b, StaffMember(id="00000000b001", name="Andy Smith", role="Joiner", hourly_rate_pence=2000))
    await PR.save_employer(
        b,
        PR.EmployerSettings(paye_office="123", paye_reference="AB45678", accounts_office_ref="123PA00045678"),
        "owner",
    )
    await PR.save_employee(
        b,
        PR.Employee(
            payroll_id="E010",
            forenames="Andy",
            surname="Smith",
            nino="AB123456C",
            dob=date(1985, 3, 3),
            gender="M",
            start_date=date(2020, 1, 1),
            staff_id="00000000b001",
            pay_type="hourly",
            hourly_rate_pence=2000,
            frequency="weekly",
            pension_exempt=True,
        ),
        "owner",
    )
    await jobs.add_entry(
        b, TimesheetEntry(staff_id="00000000b001", job_id="00000000a001", date=date(2026, 10, 21), hours=2)
    )
    return b


@pytest.fixture
def route(monkeypatch: pytest.MonkeyPatch):
    """The app with fake books, a faked ffmpeg step, the model's intent faked and every outbound httpx call faked."""
    import anyio

    from app import routes_ask
    from app.main import app
    from app.routes_books import get_books

    books = anyio.run(_overtime_books)

    async def override():
        yield books

    async def wav(data: bytes, content_type: str | None, filename: str | None) -> bytes:
        return b"RIFF-stub"

    async def intent(messages: list[dict], cfg: AiConfig, schema: dict, name: str) -> str:
        fields = dict.fromkeys(IntentModelOutput.model_fields)
        fields |= {
            "kind": "pay_overtime",
            "staff_ref": "Andy",
            "job_ref": "Hendon",
            "multiplier_text": "double time",
            "date_text": "last week",
        }
        return json.dumps(fields)

    real = httpx.AsyncClient
    state: dict[str, Any] = {}

    def faked(*_a: Any, **_k: Any) -> httpx.AsyncClient:
        return real(transport=httpx.MockTransport(state["fake"]))

    monkeypatch.setattr(voice, "require_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(voice, "to_wav", wav)
    monkeypatch.setattr(ask_ai, "call_json_model", intent)
    monkeypatch.setattr(routes_ask, "today", lambda *_a: TODAY)
    monkeypatch.setattr(stt.httpx, "AsyncClient", faked)
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    app.dependency_overrides[get_books] = override
    try:
        yield TestClient(app), state, books
    finally:
        app.dependency_overrides.clear()


def _ask(client: TestClient, headers: dict[str, str]) -> httpx.Response:
    return client.post(
        "/books/ask/voice",
        headers=headers,
        files={"audio": ("q.webm", b"\x1aE\xdf\xa3 stub", "audio/webm")},
        data={"period": json.dumps({"start": "2026-10-01", "end": "2026-12-31"})},
    )


def _audit(books: Books) -> list[dict[str, Any]]:
    import anyio

    async def read() -> bytes | None:
        return await books.storage.read(f"{actions.ACTIONS_AUDIT}/{date.today():%Y-%m}.jsonl")

    raw = anyio.run(read) or b""
    return [json.loads(ln) for ln in raw.decode().splitlines() if ln.strip()]


def test_spoken_overtime_by_muse_is_signed_and_audited(route):
    client, state, books = route
    state["fake"] = Fake(muse_ok(OVERTIME))
    r = _ask(client, {**H, "X-AI-Mode": "key", "X-Meta-Api-Key": USER_KEY})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transcript"] == OVERTIME
    assert body["transcribed_by"]["label"] == "Muse Voice Transcribe"
    card = body["proposed_action"]
    assert card["kind"] == "pay_overtime" and card["transcribed_by"] == body["transcribed_by"]
    assert card["preview"]["hours"] == "2"  # code found Andy's 2 hours on the Hendon job last week
    assert state["fake"].seen[0].headers["Authorization"] == f"Bearer {USER_KEY}"

    tampered = {**card, "transcribed_by": {**card["transcribed_by"], "label": "Someone else"}}
    assert client.post("/actions/approve", json={"action": tampered}, headers=H).status_code == 403
    ok = client.post("/actions/approve", json={"action": card}, headers=H)
    assert ok.status_code == 200, ok.text
    rows = _audit(books)
    assert [r["event"] for r in rows] == ["approving", "executed"]
    assert rows[0]["transcribed_by"]["provider"] == "muse"
    assert not any(s in json.dumps(rows) for s in SECRETS)


def test_spoken_overtime_falls_back_to_whisper_and_says_so(route):
    client, state, books = route
    state["fake"] = Fake(httpx.Response(503), whisper_ok(OVERTIME))
    r = _ask(client, {**H, "X-AI-Mode": "local"})  # no user key: the server's META_API_KEY, then Whisper
    assert r.status_code == 200, r.text
    body = r.json()
    by = body["transcribed_by"]
    assert (by["provider"], by["label"]) == ("whisper", "a local fallback model")
    assert "Muse Voice returned HTTP 503" in by["fallback_reason"]
    assert state["fake"].seen[0].headers["Authorization"] == f"Bearer {SERVER_KEY}"
    card = body["proposed_action"]
    assert card["transcribed_by"]["provider"] == "whisper"
    rej = client.post("/actions/reject", json={"action": card, "reason": "wrong week"}, headers=H)
    assert rej.status_code == 200
    [row] = _audit(books)
    assert (row["event"], row["transcribed_by"]["provider"]) == ("rejected", "whisper")


def test_typed_proposals_have_no_provenance_and_sign_as_before():
    from datetime import UTC, datetime

    draft = actions.Draft(kind="close_month", summary_md="x", preview={}, confirm_text="ok")
    a = actions.new_action(draft, "tok", datetime(2026, 10, 27, tzinfo=UTC))
    assert a.transcribed_by is None
    assert b"transcribed_by" not in actions._payload(a)
    actions.verify(a, "tok", check_expiry=False)


def test_voice_route_with_no_provider_is_400(route, monkeypatch: pytest.MonkeyPatch):
    client, _state, _books = route
    monkeypatch.delenv("META_API_KEY")
    monkeypatch.delenv("SPARK_WHISPER_URL")
    r = _ask(client, {**H, "X-AI-Mode": "local"})
    assert r.status_code == 400 and "Spark's Whisper server" in r.json()["detail"]


def test_health_lists_speech_to_text_without_secrets(route):
    client, _state, _books = route
    got = client.get("/health").json()
    assert [(p["name"], p["configured"]) for p in got["stt"]] == [("muse", True), ("whisper", True)]
    assert not any(s in json.dumps(got) for s in SECRETS) and WHISPER_BASE not in json.dumps(got)
