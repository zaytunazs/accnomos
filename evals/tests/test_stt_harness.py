"""harness/stt.py offline: normalising and scoring, the Kokoro generator against a fake, and a stubbed run of both
providers over generated clips. No network, no keys."""

from __future__ import annotations

import io
import json
import math
import struct
import wave
from pathlib import Path

import httpx
import pytest

from harness import stt as H


def _wav(seconds: float = 0.6, hz: int = 440, rate: int = 24_000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(
            b"".join(
                struct.pack("<h", int(6000 * math.sin(2 * math.pi * hz * i / rate))) for i in range(int(seconds * rate))
            )
        )
    return buf.getvalue()


@pytest.mark.parametrize(
    "text,want",
    [
        ("Quote Harbour Cafe £450 for a boiler service.", "quote harbour cafe 450 pounds for a boiler service"),
        ("Andy did two hours overtime", "andy did 2 hours overtime"),
        ("four hundred and fifty pounds", "450 pounds"),
        ("Send a £1,250 invoice", "send a 1250 pounds invoice"),
        ("the £89.99 bill on the 3rd of November", "the 89.99 pounds bill on the 3 of november"),
        ("2-inch bolts, twenty two millimetre", "2 inch bolts 22 millimetre"),
        ("seven and a half hours", "7 and a half hours"),
    ],
)
def test_normalise(text: str, want: str):
    assert " ".join(H.normalise(text)) == want


def test_score_counts_words_numbers_and_amounts():
    ref = "Quote Harbour Cafe £450 for a boiler service."
    assert H.score(ref, "quote harbour cafe four hundred and fifty pounds for a boiler service") == {
        "edits": 0,
        "ref_words": 9,
        "wer": 0.0,
        "numbers_ok": True,
        "amounts_ok": True,
    }
    bad = H.score(ref, "Quote Harbour Cafe £415 for a boiler service")
    assert (bad["edits"], bad["numbers_ok"], bad["amounts_ok"]) == (1, False, False)
    plain = H.score("What is my profit?", "What is my profit")
    assert (plain["wer"], plain["numbers_ok"], plain["amounts_ok"]) == (0.0, None, None)
    assert H.score("a b c d", "a x c")["wer"] == 0.5  # one substitution, one deletion


def test_twenty_uk_utterances_with_the_owners_three():
    assert len(H.UTTERANCES) == 20 and len(set(H.UTTERANCES)) == 20
    for said in (
        "Andy did 2 hours overtime at double time on the Hendon job.",
        "Remember to order 2-inch bolts for the Hendon job.",
    ):
        assert said in H.UTTERANCES
    assert any(u.startswith("Quote ") for u in H.UTTERANCES)


@pytest.fixture
def gold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(H, "VOICE_GOLD", tmp_path / "voice")
    monkeypatch.setattr(H, "TEASER", tmp_path / "no-teaser")
    return tmp_path / "voice"


async def test_generate_with_a_fake_kokoro(gold: Path):
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, content=_wav(hz=200 + 10 * len(seen)), headers={"content-type": "audio/wav"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        assert await H.generate("http://kokoro.invalid/v1/", client=c) == 20
        assert await H.generate("http://kokoro.invalid/v1", client=c) == 0  # resumable: nothing new
    assert seen[0] == {
        "model": "kokoro",
        "input": H.UTTERANCES[0],
        "voice": "bf_emma",
        "response_format": "wav",
        "speed": 1.0,
    }
    assert {s["voice"] for s in seen} == {"bm_george", "bf_emma"}
    manifest = json.loads((gold / "manifest.json").read_text(encoding="utf-8"))
    assert [m["text"] for m in manifest] == H.UTTERANCES and (gold / "v20.wav").exists()


async def test_generate_without_kokoro_makes_nothing(gold: Path):
    def down(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as c:
        assert await H.generate("http://kokoro.invalid/v1", client=c) == 0
    assert not list(gold.glob("*.wav"))


def test_providers_from_env_never_uses_test_mode_and_skips_the_unset():
    got, skipped = H.providers_from_env(["muse", "whisper"], {"SPARK_WHISPER_URL": "http://w.invalid/v1"})
    assert [p.name for p in got] == ["whisper"] and skipped == ["muse"]
    got, _ = H.providers_from_env(["muse"], {"META_API_KEY": "k", "ACCNOMOS_TEST_MODE": "1"})
    assert [p.name for p in got] == ["muse"]


def test_stub_run_writes_report_without_keys(gold: Path, tmp_path: Path):
    gold.mkdir(parents=True)
    rows = []
    for i, text in enumerate(H.UTTERANCES[:3], 1):
        (gold / f"v{i:02d}.wav").write_bytes(_wav(hz=300 + 50 * i))
        rows.append({"file": f"v{i:02d}.wav", "voice": "bm_george", "text": text})
    (gold / "manifest.json").write_text(json.dumps(rows), encoding="utf-8")
    out = tmp_path / "out"
    assert H.main(["--stub", "--out", str(out)]) == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    muse, whisper = summary["providers"]["muse"], summary["providers"]["whisper"]
    assert (muse["clips"], muse["failures"], muse["corpus_wer"], muse["numbers_accuracy_pct"]) == (3, 0, 0.0, 100.0)
    assert muse["amounts_accuracy_pct"] == 100.0  # the £450 quote
    assert 0 < whisper["corpus_wer"] < 0.1  # "two hours" normalises to "2 hours"; the dropped "£" costs a word
    assert whisper["numbers_accuracy_pct"] == 100.0  # the figures are all there
    assert whisper["amounts_accuracy_pct"] == 0.0  # but "450" without "pounds" is not an amount
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "muse" in report.lower() and "whisper" in report.lower()
    every = report + (out / "results.jsonl").read_text(encoding="utf-8")
    assert "stub-key" not in every


def test_dry_run_and_nothing_configured(gold: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    for k in ("META_API_KEY", "SPARK_WHISPER_URL", "AI_PROVIDERS"):
        monkeypatch.delenv(k, raising=False)
    assert H.main(["--dry-run"]) == 0
    assert "not configured: ['muse', 'whisper']" in capsys.readouterr().out
    assert H.main([]) == 2
