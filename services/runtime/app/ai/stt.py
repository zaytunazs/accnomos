"""Speech-to-text provider chain: Muse Voice Transcribe first, the owner's Whisper on the DGX Spark as the fallback.

The same idea as the text chain (app/ai/providers.py, app/ai/chain.py): try each configured provider in order and fall
over to the next on an error, a timeout or a limit, so a spoken question does not depend on one service.

    STT_PROVIDERS=muse,whisper     # the default order; unknown names are ignored

* muse    -> Muse Voice Transcribe (`muse-voice-transcribe-1.0`) on the Meta Model API, `POST {base}/asr/transcribe`
             (app/ai/voice.py has the documented wire format). The key: the user's own X-Meta-Api-Key when they chose
             key mode, else the server's META_API_KEY (the chain's `meta` provider, or the env on its own).
             Base URL: the user's key-mode base, else MODEL_API_BASE (default https://api.meta.ai/v1).
* whisper -> Whisper on the owner's DGX Spark behind an OpenAI-compatible server (for example faster-whisper-server /
             speaches): `POST {SPARK_WHISPER_URL}/audio/transcriptions`, multipart `file`, `model`, `language=en`,
             `response_format=json` -> `{"text": ...}` (the OpenAI audio API shape,
             https://platform.openai.com/docs/api-reference/audio/createTranscription, checked 29 Oct 2026).
             SPARK_WHISPER_URL (e.g. http://<spark>:8000/v1; empty = not configured), SPARK_WHISPER_MODEL (default
             Systran/faster-whisper-large-v3), SPARK_WHISPER_KEY (optional bearer token).

Timeouts (whole request, seconds): MUSE_STT_TIMEOUT_S (default 45), WHISPER_STT_TIMEOUT_S (default 90).
Test mode (ACCNOMOS_TEST_MODE=1) has no speech-to-text: no recording may reach a real service from a test run.

Keys come only from the request header or the environment, live only in `SttProvider.key` (repr=False), and are never
put in a log line, an error message, an answer or the audit trail. Audio is not stored here: the WAV bytes are passed
from the ffmpeg step (app/ai/voice.py, a temporary directory deleted at once) to each provider in memory.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

import httpx
from pydantic import BaseModel

from app.ai import voice
from app.ai.config import DEFAULT_MODEL_API_BASE, AiConfig, is_test_mode
from app.schemas import Transcription

log = logging.getLogger("accnomos.stt")

SttName = Literal["muse", "whisper"]
KNOWN: tuple[SttName, ...] = ("muse", "whisper")
DEFAULT_ORDER = "muse,whisper"
DEFAULT_WHISPER_MODEL = "Systran/faster-whisper-large-v3"
DEFAULT_TIMEOUTS: dict[str, float] = {"muse": 45.0, "whisper": 90.0}
LABELS: dict[str, str] = {"muse": "Muse Voice Transcribe", "whisper": "a local fallback model"}  # shown to users: no non-Meta names


@dataclass(frozen=True)
class SttProvider:
    name: SttName
    base_url: str
    model: str
    timeout_s: float
    key: str | None = field(default=None, repr=False)  # never logged, serialised or shown
    key_source: Literal["user", "server", "none"] = "none"

    @property
    def label(self) -> str:
        return LABELS[self.name]


class Heard(BaseModel):
    text: str
    by: Transcription
    ms: int


def order(env: Mapping[str, str] | None = None) -> list[SttName]:
    env = os.environ if env is None else env
    out: list[SttName] = []
    for raw in (env.get("STT_PROVIDERS") or DEFAULT_ORDER).split(","):
        name = raw.strip().lower()
        if name in KNOWN and name not in out:
            out.append(name)  # type: ignore[arg-type]
    return out


def _seconds(env: Mapping[str, str], name: str) -> float:
    try:
        return float(env.get(f"{name.upper()}_STT_TIMEOUT_S") or DEFAULT_TIMEOUTS[name])
    except ValueError:
        return DEFAULT_TIMEOUTS[name]


def _muse(cfg: AiConfig | None, env: Mapping[str, str]) -> SttProvider | None:
    timeout = _seconds(env, "muse")
    if cfg is not None and not cfg.in_chain and cfg.mode == "key" and cfg.api_key:  # the user's own key
        return SttProvider("muse", cfg.base_url, voice.VOICE_MODEL, timeout, cfg.api_key, "user")
    meta = cfg.with_capability("voice") if cfg is not None and cfg.in_chain else None
    if meta is not None and meta.api_key:  # the server chain's Meta Model API provider
        return SttProvider("muse", meta.base_url, voice.VOICE_MODEL, timeout, meta.api_key, "server")
    key = (env.get("META_API_KEY") or "").strip()
    if not key:
        return None
    base = (env.get("MODEL_API_BASE") or DEFAULT_MODEL_API_BASE).rstrip("/")
    return SttProvider("muse", base, voice.VOICE_MODEL, timeout, key, "server")


def _whisper(env: Mapping[str, str]) -> SttProvider | None:
    url = (env.get("SPARK_WHISPER_URL") or "").strip().rstrip("/")
    if not url:
        return None
    key = (env.get("SPARK_WHISPER_KEY") or "").strip() or None
    model = (env.get("SPARK_WHISPER_MODEL") or "").strip() or DEFAULT_WHISPER_MODEL
    return SttProvider("whisper", url, model, _seconds(env, "whisper"), key, "server" if key else "none")


def chain(cfg: AiConfig | None = None, env: Mapping[str, str] | None = None) -> list[SttProvider]:
    """The configured speech-to-text providers for this request, in order. Empty in test mode."""
    env = os.environ if env is None else env
    if is_test_mode():
        return []
    out: list[SttProvider] = []
    for name in order(env):
        p = _muse(cfg, env) if name == "muse" else _whisper(env)
        if p is not None:
            out.append(p)
    return out


def describe(env: Mapping[str, str] | None = None) -> list[dict[str, object]]:
    """For /health: names, labels, models and whether each is configured on the server. Never a key or a URL."""
    env = os.environ if env is None else env
    configured = {p.name for p in chain(None, env)}
    whisper_model = env.get("SPARK_WHISPER_MODEL") or DEFAULT_WHISPER_MODEL
    out: list[dict[str, object]] = []
    for n in order(env):
        model = voice.VOICE_MODEL if n == "muse" else whisper_model
        out.append({"name": n, "label": LABELS[n], "model": model, "configured": n in configured})
    return out


async def whisper_transcribe(
    wav: bytes, c: SttProvider, client: httpx.AsyncClient | None = None, *, prompt: str | None = None
) -> str:
    """Whisper behind an OpenAI-compatible `/audio/transcriptions` endpoint. Errors never carry the key."""
    data = {"model": c.model, "language": "en", "response_format": "json", "temperature": "0"}
    if prompt:
        data["prompt"] = prompt[:800]  # Whisper reads up to ~224 tokens of prompt; names help with spelling
    headers = {"Authorization": f"Bearer {c.key}"} if c.key else {}
    own = client is None
    http = client or httpx.AsyncClient(timeout=c.timeout_s)
    try:
        r = await http.post(
            f"{c.base_url}/audio/transcriptions",
            data=data,
            files={"file": ("question.wav", wav, "audio/wav")},
            headers=headers,
        )
    except httpx.TimeoutException as exc:
        raise voice.VoiceError(504, f"Whisper on the Spark took longer than {c.timeout_s:g} s") from exc
    except httpx.HTTPError as exc:
        raise voice.VoiceError(502, f"Whisper on the Spark could not be reached ({type(exc).__name__})") from exc
    finally:
        if own:
            await http.aclose()
    if r.status_code in (401, 403):
        raise voice.VoiceError(502, "Whisper on the Spark refused the server's credentials")
    if r.status_code == 413:
        raise voice.VoiceError(413, "Whisper on the Spark says the recording is too large")
    if r.status_code >= 400:
        raise voice.VoiceError(502, f"Whisper on the Spark returned HTTP {r.status_code}")
    try:
        body = r.json()
    except ValueError:
        raise voice.VoiceError(502, "Whisper on the Spark returned something that isn't JSON") from None
    text = (body.get("text") if isinstance(body, dict) else "") or ""
    if not isinstance(text, str) or not text.strip():
        raise voice.VoiceError(422, "Didn't catch any words in that recording")
    return text.strip()


async def _one(wav: bytes, p: SttProvider, keywords: list[str], client: httpx.AsyncClient | None) -> str:
    if p.name == "muse":
        cfg = AiConfig(mode="key", base_url=p.base_url, model=p.model, api_key=p.key, provider="muse")
        return await voice.transcribe(wav, cfg, client, keywords=keywords, timeout_s=p.timeout_s)
    prompt = ("Names: " + ", ".join(keywords) + ".") if keywords else None
    return await whisper_transcribe(wav, p, client, prompt=prompt)


async def transcribe(
    wav: bytes,
    providers: list[SttProvider],
    *,
    keywords: list[str] | None = None,
    client: httpx.AsyncClient | None = None,
) -> Heard:
    """Try each provider in order; the first transcript wins. Falls over on any failure (network, timeout, a refused
    key, a size or length limit, rate limiting, no words heard). When every provider fails, raises the first one's
    error (the preferred service's reason is the useful one), noting that the fallback failed too."""
    if not providers:
        raise voice.VoiceError(400, "Voice needs Muse Voice Transcribe (a Meta API key) or the Spark's Whisper server")
    words = list(keywords or [])
    failures: list[tuple[SttProvider, voice.VoiceError]] = []
    for p in providers:
        t0 = time.perf_counter()
        try:
            text = await _one(wav, p, words, client)
        except voice.VoiceError as exc:
            failures.append((p, exc))
            nxt = providers[len(failures)].label if len(failures) < len(providers) else "nothing"
            # The message is ours (status words only): no key, header or audio is in it.
            log.warning("speech-to-text: %s failed (%s: %s); trying %s", p.label, exc.status, exc, nxt)
            continue
        ms = int((time.perf_counter() - t0) * 1000)
        why = "; ".join(f"{f.label}: {e}" for f, e in failures) or None
        return Heard(
            text=text, ms=ms, by=Transcription(provider=p.name, label=p.label, model=p.model, fallback_reason=why)
        )
    err = failures[0][1]
    if len(failures) == 1:
        raise err
    rest = "; ".join(f"{f.label}: {e}" for f, e in failures[1:])
    raise voice.VoiceError(err.status, f"{err} (the fallback failed too: {rest})")
