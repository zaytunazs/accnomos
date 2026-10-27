"""Voice questions: ffmpeg conversion of a generated tone, the Muse Voice client on stubbed HTTP,
error mapping, the route.
"""

from __future__ import annotations

import io
import json
import math
import struct
import subprocess
import wave

import httpx
import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app.ai import ask as ask_ai
from app.ai import voice
from app.ai.config import AiConfig
from app.books import Books
from app.schemas import AskModelOutput

KEY = AiConfig(mode="key", base_url="https://api.meta.invalid/v1", model="muse-spark-1.3", api_key="test-key")
LOCAL = AiConfig(mode="local", base_url="http://ollama.invalid", model="muse-glimmer:30b")
needs_ffmpeg = pytest.mark.skipif(voice.ffmpeg_path() is None, reason="ffmpeg not installed")


def _tone_wav(seconds: float = 1.0, rate: int = 44_100, channels: int = 2) -> bytes:
    """A 440 Hz stereo 44.1 kHz WAV, made in code (no fixtures on disk)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) * channels
            for i in range(int(seconds * rate))
        )
        w.writeframes(frames)
    return buf.getvalue()


def _webm_tone() -> bytes:
    """The same tone as webm/opus, which is what Chrome's MediaRecorder sends."""
    run = subprocess.run(
        [
            voice.ffmpeg_path() or "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "wav",
            "-i",
            "pipe:0",
            "-c:a",
            "libopus",
            "-f",
            "webm",
            "pipe:1",
        ],
        input=_tone_wav(),
        capture_output=True,
        check=False,
    )
    if run.returncode != 0:
        pytest.skip("this ffmpeg has no libopus encoder")
    return run.stdout


# --------------------------------------------------------------------------- #
# ffmpeg
# --------------------------------------------------------------------------- #


def _info(wav_bytes: bytes) -> tuple[int, int, int, float]:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes() / w.getframerate()


@needs_ffmpeg
async def test_to_wav_converts_a_tone_to_mono_16k():
    channels, width, rate, seconds = _info(await voice.to_wav(_tone_wav(), "audio/wav", "tone.wav"))
    assert (channels, width, rate) == (1, 2, 16_000)
    assert 0.95 < seconds < 1.05


@needs_ffmpeg
async def test_to_wav_reads_webm_opus():
    channels, _, rate, seconds = _info(await voice.to_wav(_webm_tone(), "audio/webm;codecs=opus", "q.webm"))
    assert (channels, rate) == (1, 16_000) and 0.9 < seconds < 1.1


@needs_ffmpeg
async def test_to_wav_rejects_rubbish_and_tiny_clips():
    with pytest.raises(voice.VoiceError) as bad:
        await voice.to_wav(b"this is not audio at all" * 50, "audio/webm", "q.webm")
    assert bad.value.status == 422
    with pytest.raises(voice.VoiceError) as short:
        await voice.to_wav(_tone_wav(seconds=0.05), "audio/wav")
    assert short.value.status == 422 and "too short" in str(short.value)


@needs_ffmpeg
async def test_to_wav_keeps_no_audio_on_disk(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(voice.tempfile, "tempdir", str(tmp_path))
    await voice.to_wav(_tone_wav(), "audio/wav")
    with pytest.raises(voice.VoiceError) as bad:
        await voice.to_wav(b"not audio" * 50, "audio/webm")
    assert list(tmp_path.iterdir()) == []
    assert str(tmp_path) not in str(bad.value)  # the server's temp path isn't echoed to the user


async def test_to_wav_size_limits_need_no_ffmpeg():
    with pytest.raises(voice.VoiceError) as empty:
        await voice.to_wav(b"")
    with pytest.raises(voice.VoiceError) as big:
        await voice.to_wav(b"\0" * (voice.MAX_UPLOAD_BYTES + 1))
    assert (empty.value.status, big.value.status) == (400, 413)


async def test_missing_ffmpeg_is_a_503(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(voice.shutil, "which", lambda _name: None)
    with pytest.raises(voice.VoiceError) as exc:
        await voice.to_wav(_tone_wav())
    assert exc.value.status == 503 and "ffmpeg" in str(exc.value)


# --------------------------------------------------------------------------- #
# Muse Voice client (stubbed HTTP)
# --------------------------------------------------------------------------- #


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_transcribe_sends_multipart_with_the_users_key():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"text": "  How much VAT do I owe?  "})

    async with _client(handler) as c:
        text = await voice.transcribe(b"RIFF....WAVE", KEY, c)
    assert text == "How much VAT do I owe?"
    req = seen[0]
    assert str(req.url) == "https://api.meta.invalid/v1/asr/transcribe"
    assert req.headers["Authorization"] == "Bearer test-key"
    body = req.read()
    assert b'name="request"' in body and b'name="audio"' in body and b"RIFF....WAVE" in body
    assert json.dumps({"model": "muse-voice-transcribe-1.0"}).encode() in body


@pytest.mark.parametrize(
    "body,want",
    [({"transcript": "hello"}, "hello"), ({"results": [{"text": "who did"}, {"text": "I pay"}]}, "who did I pay")],
)
async def test_transcribe_reads_other_response_shapes(body: dict, want: str):
    async with _client(lambda _r: httpx.Response(200, json=body)) as c:
        assert await voice.transcribe(b"wav", KEY, c) == want


@pytest.mark.parametrize(
    "response,status",
    [
        (httpx.Response(401, json={"error": "bad key"}), 401),
        (httpx.Response(403), 401),
        (httpx.Response(413), 413),
        (httpx.Response(429), 429),
        (httpx.Response(500), 502),
        (httpx.Response(200, text="<html>oops</html>"), 502),
        (httpx.Response(200, json={"text": "   "}), 422),
    ],
)
async def test_transcribe_error_mapping(response: httpx.Response, status: int):
    async with _client(lambda _r: response) as c:
        with pytest.raises(voice.VoiceError) as exc:
            await voice.transcribe(b"wav", KEY, c)
    assert exc.value.status == status


async def test_transcribe_network_failure_is_502():
    def handler(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async with _client(handler) as c:
        with pytest.raises(voice.VoiceError) as exc:
            await voice.transcribe(b"wav", KEY, c)
    assert exc.value.status == 502


async def test_transcribe_refuses_local_mode():
    with pytest.raises(voice.VoiceError) as exc:
        await voice.transcribe(b"wav", LOCAL)
    assert (exc.value.status, str(exc.value)) == (400, "voice needs a Meta API key")


# --------------------------------------------------------------------------- #
# The route
# --------------------------------------------------------------------------- #


def _model_reply() -> str:
    return AskModelOutput(
        answer_md="Nothing posted yet, so there is no VAT to pay.",
        key_numbers=[],
        citations=[],
        suggested_actions=[],
        confidence="low",
    ).model_dump_json()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    from app.main import app
    from app.routes_books import get_books

    async def override():
        b = Books(FakeStorageProvider())
        await b.ensure_tree()
        yield b

    async def fake_model(messages: list[dict], cfg: AiConfig) -> str:
        return _model_reply()

    monkeypatch.setattr(ask_ai, "_call_model", fake_model)
    app.dependency_overrides[get_books] = override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


KEY_HEADERS = {"X-Graph-Token": "t", "X-AI-Mode": "key", "X-Meta-Api-Key": "test-key"}


def test_voice_route_local_mode_is_400(client: TestClient):
    r = client.post(
        "/books/ask/voice",
        headers={"X-Graph-Token": "t", "X-AI-Mode": "local"},
        files={"audio": ("q.wav", _tone_wav(), "audio/wav")},
    )
    assert r.status_code == 400 and r.json()["detail"] == "voice needs a Meta API key"


def test_voice_route_without_ffmpeg_is_503(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(voice.shutil, "which", lambda _name: None)
    r = client.post("/books/ask/voice", headers=KEY_HEADERS, files={"audio": ("q.wav", _tone_wav(), "audio/wav")})
    assert r.status_code == 503 and "ffmpeg" in r.json()["detail"]


@needs_ffmpeg
def test_voice_route_answers_with_transcript(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    heard: list[tuple[int, AiConfig]] = []

    async def fake_transcribe(wav: bytes, cfg: AiConfig, client=None) -> str:
        heard.append((len(wav), cfg))
        return "How much VAT do I owe?"

    monkeypatch.setattr(voice, "transcribe", fake_transcribe)
    r = client.post(
        "/books/ask/voice",
        headers=KEY_HEADERS,
        files={"audio": ("q.webm", _webm_tone(), "audio/webm")},
        data={"period": json.dumps({"start": "2026-07-01", "end": "2026-09-30"}), "history": "[]"},
    )
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["transcript"] == "How much VAT do I owe?"
    assert got["period"] == {"start": "2026-07-01", "end": "2026-09-30"} and got["answer_md"]
    assert heard[0][1].api_key == "test-key" and heard[0][0] > 30_000  # ~1 s of 16 kHz 16-bit mono


@needs_ffmpeg
def test_voice_route_maps_transcribe_errors(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def fail(*_a, **_k) -> str:
        raise voice.VoiceError(401, "Meta rejected the API key for Muse Voice")

    monkeypatch.setattr(voice, "transcribe", fail)
    r = client.post("/books/ask/voice", headers=KEY_HEADERS, files={"audio": ("q.wav", _tone_wav(), "audio/wav")})
    assert r.status_code == 401 and "rejected" in r.json()["detail"]


@needs_ffmpeg
def test_voice_route_overlong_transcript_is_422(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def ramble(*_a, **_k) -> str:
        return "and another thing " * 40

    monkeypatch.setattr(voice, "transcribe", ramble)
    r = client.post("/books/ask/voice", headers=KEY_HEADERS, files={"audio": ("q.wav", _tone_wav(), "audio/wav")})
    assert r.status_code == 422 and "too long" in r.json()["detail"]


def test_health_reports_voice(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    import app.main

    assert client.get("/health").json()["voice"] is (voice.ffmpeg_path() is not None)
    monkeypatch.setattr(app.main, "FFMPEG", None)
    assert client.get("/health").json()["voice"] is False


def test_voice_route_bad_period_is_422(client: TestClient):
    r = client.post(
        "/books/ask/voice",
        headers=KEY_HEADERS,
        files={"audio": ("q.wav", _tone_wav(), "audio/wav")},
        data={"period": '{"start": "2026-09-30", "end": "2026-07-01"}'},
    )
    assert r.status_code == 422
