"""Speech-to-text provider chain: the speech-to-text model on our own server first; Muse Voice Transcribe on the
Meta Model API only when the owner switches it on.

Owner's decision (11 Nov 2026): recordings no longer go to Meta by default. The same idea as the text chain
(app/ai/providers.py, app/ai/chain.py): try each configured provider in order and fall over to the next on an error,
a timeout or a limit.

    STT_PROVIDER=local     # the default: our own server's speech-to-text (`whisper` below) and nothing else
    STT_PROVIDER=meta      # Muse Voice Transcribe first, our own server second (sends recordings to Meta)
    STT_PROVIDERS=whisper,muse   # an explicit order wins over STT_PROVIDER; unknown names are ignored

* whisper -> the speech-to-text service on our own server (spark-voice) behind the standard OpenAI-compatible
             `POST {url}/audio/transcriptions`, multipart `file`, `model`, `language=en`, `response_format=json`
             -> `{"text": ...}`. The URL: SPARK_WHISPER_URL (with its `/v1`), else STT_BASE + `/v1` (STT_BASE
             default http://host.docker.internal:8890, the Spark's spark-voice port as the runtime container sees it;
             STT_BASE=off switches it off). The model: SPARK_WHISPER_MODEL (or STT_MODEL), else the first id the
             service lists at `GET {url}/models` (asked once, then remembered), else DEFAULT_WHISPER_MODEL.
             SPARK_WHISPER_KEY: an optional bearer token.
* muse    -> Muse Voice Transcribe (`muse-voice-transcribe-1.0`) on the Meta Model API, `POST {base}/asr/transcribe`
             (app/ai/voice.py has the documented wire format), only when STT_PROVIDER=meta or STT_PROVIDERS names it,
             or when the user chose their own Meta key (X-AI-Mode: key): then their key, first, as before.
             The key: the user's own X-Meta-Api-Key when they chose key mode, else the server's META_API_KEY.

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
from dataclasses import dataclass, field, replace
from typing import Literal

import httpx
from pydantic import BaseModel

from app.ai import voice
from app.ai.config import DEFAULT_MODEL_API_BASE, AiConfig, is_test_mode
from app.schemas import Transcription

log = logging.getLogger("accnomos.stt")

SttName = Literal["muse", "whisper"]
KNOWN: tuple[SttName, ...] = ("muse", "whisper")
DEFAULT_ORDER = "whisper"  # STT_PROVIDER=local (the default)
META_ORDER = "muse,whisper"  # STT_PROVIDER=meta
DEFAULT_STT_BASE = "http://host.docker.internal:8890"
DEFAULT_WHISPER_MODEL = "Systran/faster-whisper-large-v3"
OFF = ("off", "none", "0", "false", "no")
_MODELS: dict[str, str] = {}  # url -> the model id its /models listed (asked once per process)
DEFAULT_TIMEOUTS: dict[str, float] = {"muse": 45.0, "whisper": 90.0}
# Shown to users (answers, action cards): no engine or vendor names for our own server's model.
LABELS: dict[str, str] = {"muse": "the hosted speech-to-text model", "whisper": "our own server"}


@dataclass(frozen=True)
class SttProvider:
    name: SttName
    base_url: str
    model: str
    timeout_s: float
    key: str | None = field(default=None, repr=False)  # never logged, serialised or shown
    key_source: Literal["user", "server", "none"] = "none"
    heard_text: str = field(default="", repr=False)  # the transcript, once heard (never logged)

    @property
    def label(self) -> str:
        return LABELS[self.name]


class Heard(BaseModel):
    text: str
    by: Transcription
    ms: int


def order(env: Mapping[str, str] | None = None) -> list[SttName]:
    env = os.environ if env is None else env
    explicit = (env.get("STT_PROVIDERS") or "").strip()
    default = META_ORDER if (env.get("STT_PROVIDER") or "").strip().lower() == "meta" else DEFAULT_ORDER
    out: list[SttName] = []
    for raw in (explicit or default).split(","):
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
    if cfg is not None and cfg.route == "local_only":  # the user chose to send nothing to the Meta Model API
        return None
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


def whisper_url(env: Mapping[str, str]) -> str | None:
    """Our own server's speech-to-text endpoint (ending in /v1), or None when switched off."""
    url = (env.get("SPARK_WHISPER_URL") or "").strip().rstrip("/")
    if url:
        return url
    base = (env.get("STT_BASE") or DEFAULT_STT_BASE).strip().rstrip("/")
    if not base or base.lower() in OFF:
        return None
    return base if base.endswith("/v1") else base + "/v1"


def _whisper(env: Mapping[str, str]) -> SttProvider | None:
    url = whisper_url(env)
    if not url:
        return None
    key = (env.get("SPARK_WHISPER_KEY") or "").strip() or None
    model = (env.get("SPARK_WHISPER_MODEL") or env.get("STT_MODEL") or "").strip()  # "": ask the service (/models)
    return SttProvider("whisper", url, model, _seconds(env, "whisper"), key, "server" if key else "none")


async def whisper_model(c: SttProvider, client: httpx.AsyncClient | None = None) -> str:
    """The model to ask for: the configured one, else the first id `GET {url}/models` lists (remembered per URL),
    else DEFAULT_WHISPER_MODEL. Never raises: a service that does not list its models still gets a request."""
    if c.model:
        return c.model
    if c.base_url in _MODELS:
        return _MODELS[c.base_url]
    headers = {"Authorization": f"Bearer {c.key}"} if c.key else {}
    own = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0))
    try:
        r = await http.get(f"{c.base_url}/models", headers=headers)
        data = r.json().get("data") if r.status_code == 200 else None
        ids = [str(m["id"]) for m in data or [] if isinstance(m, dict) and isinstance(m.get("id"), str)]
    except (httpx.HTTPError, ValueError, AttributeError):
        ids = []
    finally:
        if own:
            await http.aclose()
    if not ids:
        return DEFAULT_WHISPER_MODEL  # not remembered: the next request asks again
    _MODELS[c.base_url] = ids[0]
    return ids[0]


def chain(cfg: AiConfig | None = None, env: Mapping[str, str] | None = None) -> list[SttProvider]:
    """The configured speech-to-text providers for this request, in order. Empty in test mode."""
    env = os.environ if env is None else env
    if is_test_mode():
        return []
    names = order(env)
    own_key = cfg is not None and not cfg.in_chain and cfg.mode == "key" and bool(cfg.api_key)
    if own_key and "muse" not in names and not (env.get("STT_PROVIDERS") or "").strip():
        names = ["muse", *names]  # the user chose their own Meta key: their recordings go where they chose
    out: list[SttProvider] = []
    for name in names:
        p = _muse(cfg, env) if name == "muse" else _whisper(env)
        if p is not None:
            out.append(p)
    return out


def describe(env: Mapping[str, str] | None = None) -> list[dict[str, object]]:
    """For /health: names, labels, models and whether each is configured on the server. Never a key or a URL."""
    env = os.environ if env is None else env
    configured = {p.name for p in chain(None, env)}
    url = whisper_url(env) or ""
    local_model = env.get("SPARK_WHISPER_MODEL") or env.get("STT_MODEL") or _MODELS.get(url) or DEFAULT_WHISPER_MODEL
    out: list[dict[str, object]] = []
    for n in order(env):
        model = voice.VOICE_MODEL if n == "muse" else local_model
        out.append({"name": n, "label": LABELS[n], "model": model, "configured": n in configured})
    return out


async def whisper_transcribe(
    wav: bytes, c: SttProvider, client: httpx.AsyncClient | None = None, *, prompt: str | None = None
) -> str:
    """The local speech-to-text model behind a standard `/audio/transcriptions` endpoint. Errors never carry the key."""
    data = {"model": c.model or DEFAULT_WHISPER_MODEL, "language": "en", "response_format": "json", "temperature": "0"}
    if prompt:
        data["prompt"] = prompt[:800]  # the model reads up to ~224 tokens of prompt; names help with spelling
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
        raise voice.VoiceError(504, f"The local speech-to-text model took longer than {c.timeout_s:g} s") from exc
    except httpx.HTTPError as exc:
        raise voice.VoiceError(
            502, f"The local speech-to-text model could not be reached ({type(exc).__name__})"
        ) from exc
    finally:
        if own:
            await http.aclose()
    if r.status_code in (401, 403):
        raise voice.VoiceError(502, "The local speech-to-text model refused the server's credentials")
    if r.status_code == 413:
        raise voice.VoiceError(413, "The local speech-to-text model says the recording is too large")
    if r.status_code >= 400:
        raise voice.VoiceError(502, f"The local speech-to-text model returned HTTP {r.status_code}")
    try:
        body = r.json()
    except ValueError:
        raise voice.VoiceError(502, "The local speech-to-text model returned something that isn't JSON") from None
    text = (body.get("text") if isinstance(body, dict) else "") or ""
    if not isinstance(text, str) or not text.strip():
        raise voice.VoiceError(422, "Didn't catch any words in that recording")
    return text.strip()


async def _one(wav: bytes, p: SttProvider, keywords: list[str], client: httpx.AsyncClient | None) -> SttProvider:
    """Transcribe with `p`; returns `p` with the text in `heard_text` (its model resolved)."""
    if p.name == "muse":
        cfg = AiConfig(mode="key", base_url=p.base_url, model=p.model, api_key=p.key, provider="muse")
        text = await voice.transcribe(wav, cfg, client, keywords=keywords, timeout_s=p.timeout_s)
        return replace(p, heard_text=text)
    prompt = ("Names: " + ", ".join(keywords) + ".") if keywords else None
    p = replace(p, model=await whisper_model(p, client))
    return replace(p, heard_text=await whisper_transcribe(wav, p, client, prompt=prompt))


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
        raise voice.VoiceError(
            400,
            "Voice needs the speech-to-text model on our own server (STT_BASE)"
            " or the hosted speech-to-text model (an API key)",
        )
    words = list(keywords or [])
    failures: list[tuple[SttProvider, voice.VoiceError]] = []
    for p in providers:
        t0 = time.perf_counter()
        try:
            done = await _one(wav, p, words, client)
        except voice.VoiceError as exc:
            failures.append((p, exc))
            nxt = providers[len(failures)].label if len(failures) < len(providers) else "nothing"
            # The message is ours (status words only): no key, header or audio is in it.
            log.warning("speech-to-text: %s failed (%s: %s); trying %s", p.label, exc.status, exc, nxt)
            continue
        ms = int((time.perf_counter() - t0) * 1000)
        why = "; ".join(f"{f.label}: {e}" for f, e in failures) or None
        return Heard(
            text=done.heard_text,
            ms=ms,
            by=Transcription(provider=p.name, label=p.label, model=done.model, fallback_reason=why),
        )
    err = failures[0][1]
    if len(failures) == 1:
        raise err
    rest = "; ".join(f"{f.label}: {e}" for f, e in failures[1:])
    raise voice.VoiceError(err.status, f"{err} (the fallback failed too: {rest})")
