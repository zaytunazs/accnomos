"""Voice questions: browser/phone audio -> WAV mono 16 kHz (ffmpeg) -> speech-to-text -> text.

Which speech-to-text service hears it is app/ai/stt.py (Muse Voice Transcribe first, the owner's Whisper on the
DGX Spark as the fallback). This module holds the conversion and the Muse Voice Transcribe client. Audio lives in a
temporary directory for the length of the conversion and is deleted straight after; nothing is kept.

Muse Voice Transcribe one-shot endpoint, as documented by Meta (checked 29 Oct 2026; dev.meta.ai itself is not
reachable from our build sandbox, so the shapes are taken from Meta's own cookbook, meta-models/meta-model-cookbook
commit 0a99b98 of 7 Oct 2026, 06_muse_voice/01_voice_api_fundamentals/utils.py and README.md, which links
https://dev.meta.ai/docs/speech-to-text and https://dev.meta.ai/docs/api-reference/voice):

* `POST https://api.meta.ai/v1/asr/transcribe`, header `Authorization: Bearer <Model API key>`.
* multipart: a `request` part (JSON, application/json) `{"mode": "PUSH_TO_TALK", "model": "muse-voice-transcribe-1.0",
  "audioEncoding": "WAV", "keywords": [...]?, "languageBias": [...]?}` and an `audio` part (the WAV file).
* audio: mono 16-bit WAV at 24 kHz (engine-native) or 16 kHz; at most 10 minutes or 32 MB, whichever comes first.
* 200: `{"sessionId", "transcript", "audioDurationMs", "turns": [...]}`; 400 too long or malformed, 401 key not
  accepted, 413 body over 32 MB, 429 rate limited, 500 "exceeded its processing budget".

The live WebSocket (`wss://api.meta.ai/v1/asr/realtime`, credential inside the handshake JSON, paced at real time) is
not used: a question is recorded whole on the phone or in the browser, so one POST is quicker than replaying it.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import httpx

from app.ai.config import AiConfig

VOICE_MODEL = "muse-voice-transcribe-1.0"
SAMPLE_RATE = 16_000
MAX_UPLOAD_BYTES = 32 * 1024 * 1024
MAX_SECONDS = 600
CONVERT_TIMEOUT_S = 60.0
TRANSCRIBE_TIMEOUT_S = 120.0
WAV_HEADER_BYTES = 44
BYTES_PER_SECOND = SAMPLE_RATE * 2  # mono, 16-bit

AUDIO_SUFFIXES = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
}


class VoiceError(RuntimeError):
    """A voice failure with the HTTP status the route should return."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def require_ffmpeg() -> str:
    path = ffmpeg_path()
    if not path:
        raise VoiceError(503, "Voice is unavailable: ffmpeg is not installed on the reader service (see docs/DEV.md)")
    return path


def _suffix(content_type: str | None, filename: str | None) -> str:
    base = (content_type or "").split(";")[0].strip().lower()
    if base in AUDIO_SUFFIXES:
        return AUDIO_SUFFIXES[base]
    ext = Path(filename or "").suffix.lower()
    return ext if ext in set(AUDIO_SUFFIXES.values()) else ".bin"


async def to_wav(data: bytes, content_type: str | None = None, filename: str | None = None) -> bytes:
    """Convert any audio ffmpeg understands to WAV mono 16-bit 16 kHz, at most MAX_SECONDS long.

    Goes through a temporary file, not a pipe: m4a from phones puts its index at the end and needs seeking.
    """
    if not data:
        raise VoiceError(400, "The recording is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise VoiceError(413, "The recording is larger than 32 MB")
    ffmpeg = require_ffmpeg()
    with tempfile.TemporaryDirectory(prefix="accnomos-voice-") as tmp:
        src = Path(tmp) / f"in{_suffix(content_type, filename)}"
        dst = Path(tmp) / "out.wav"
        src.write_bytes(data)
        proc = await asyncio.create_subprocess_exec(
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(src),
            "-t",
            str(MAX_SECONDS + 1),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-sample_fmt",
            "s16",
            "-f",
            "wav",
            str(dst),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), CONVERT_TIMEOUT_S)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise VoiceError(422, "The recording took too long to convert") from None
        if proc.returncode != 0 or not dst.exists():
            detail = err.decode("utf-8", "replace").replace(str(src), "input").strip().splitlines()[-1:] or [
                "unknown error"
            ]
            raise VoiceError(422, f"Couldn't read that recording as audio ({detail[0][:200]})")
        wav = dst.read_bytes()
    seconds = (len(wav) - WAV_HEADER_BYTES) / BYTES_PER_SECOND
    if seconds > MAX_SECONDS:
        raise VoiceError(413, "The recording is longer than 10 minutes")
    if seconds < 0.2:
        raise VoiceError(422, "The recording is too short to transcribe")
    return wav


MODE = "PUSH_TO_TALK"  # the caller ends the turn by uploading a whole clip (the documented default)
LANGUAGE_BIAS = ["english"]  # UK English speakers; a nudge, not a constraint (the cookbook's example value)
MAX_KEYWORDS = 50


def _transcript(body: Any) -> str:
    """Pull the text out of the response: documented `transcript`; tolerant of `text`, or a list of turns/segments."""
    if isinstance(body, dict):
        for key in ("transcript", "text"):
            if isinstance(body.get(key), str):
                return body[key]
        for key in ("turns", "results", "segments"):
            items = body.get(key)
            if isinstance(items, list):
                return " ".join(_transcript(i) for i in items).strip()
    return ""


def muse_request(keywords: list[str] | None = None) -> dict[str, Any]:
    """The `request` JSON part. `keywords` (job, staff and customer names) bias recognition; sent only when set,
    because the server silently ignores what it does not know and an empty list would hide a typo."""
    req: dict[str, Any] = {"mode": MODE, "model": VOICE_MODEL, "audioEncoding": "WAV", "languageBias": LANGUAGE_BIAS}
    words = [k.strip() for k in (keywords or []) if k and k.strip()][:MAX_KEYWORDS]
    if words:
        req["keywords"] = words
    return req


async def transcribe(
    wav: bytes,
    cfg: AiConfig,
    client: httpx.AsyncClient | None = None,
    *,
    keywords: list[str] | None = None,
    timeout_s: float = TRANSCRIBE_TIMEOUT_S,
) -> str:
    """Send WAV audio to Muse Voice Transcribe with a Meta key; return the transcript text.

    Error messages name the status, never the key or the request headers."""
    if cfg.mode != "key" or not cfg.api_key:
        raise VoiceError(400, "voice needs a Meta API key")
    files = {
        "request": (None, json.dumps(muse_request(keywords)), "application/json"),
        "audio": ("question.wav", wav, "audio/wav"),
    }
    own = client is None
    http = client or httpx.AsyncClient(timeout=timeout_s)
    try:
        r = await http.post(
            f"{cfg.base_url}/asr/transcribe", files=files, headers={"Authorization": f"Bearer {cfg.api_key}"}
        )
    except httpx.TimeoutException as exc:
        raise VoiceError(504, f"Muse Voice took longer than {timeout_s:g} s") from exc
    except httpx.HTTPError as exc:
        raise VoiceError(502, f"Muse Voice could not be reached ({type(exc).__name__})") from exc
    finally:
        if own:
            await http.aclose()
    if r.status_code in (401, 403):
        raise VoiceError(401, "Meta rejected the API key for Muse Voice")
    if r.status_code == 413:
        raise VoiceError(413, "Muse Voice says the recording is too large")
    if r.status_code == 400:
        raise VoiceError(422, "Muse Voice refused the recording (longer than 10 minutes, or malformed)")
    if r.status_code == 429:
        raise VoiceError(429, "Muse Voice is rate-limiting this key; try again in a moment")
    if r.status_code >= 400:
        raise VoiceError(502, f"Muse Voice returned HTTP {r.status_code}")
    try:
        text = _transcript(r.json()).strip()
    except ValueError:
        raise VoiceError(502, "Muse Voice returned something that isn't JSON") from None
    if not text:
        raise VoiceError(422, "Didn't catch any words in that recording")
    return text
