"""Tests for tools/video's Python side, with stubbed HTTP (no call to Meta): `python3 -m pytest -q tools/video`."""

from __future__ import annotations

import base64
import io
import json
import re
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import muse_images  # noqa: E402
import segments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
KEY = "sk-test-NEVER-PRINT-THIS"


def png(w: int, h: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (15, 110, 99)).save(buf, "PNG")
    return buf.getvalue()


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_prompts_file_parses_and_covers_every_card_the_tools_use():
    style, cards = muse_images.parse_prompts((ROOT / "docs/video/IMAGE_PROMPTS.md").read_text(encoding="utf-8"))
    ids = {c["id"] for c in cards}
    assert "no text" in style.lower() and "#0F6E63" in style
    assert {"judges-title", "section-impact", "section-meta-ai", "section-depth", "section-demo", "thumb-judges"} <= ids
    assert {f"clip-{n:02d}-title" for n in range(1, 9)} <= ids
    assert {f"thumb-clip-{n:02d}" for n in range(1, 9)} <= ids
    guides = {p.stem for p in (ROOT / "docs/howto").glob("*.md") if p.name != "README.md"}
    assert {f"howto-{g}" for g in guides} <= ids
    sizes = {c["id"]: c["size"] for c in cards}
    assert sizes["judges-title"] == "1920x1080" and sizes["clip-01-title"] == "1080x1920"
    assert sizes["thumb-judges"] == "1280x720"


def test_no_key_says_so_and_exits_cleanly(tmp_path):
    env = {"PATH": "/usr/bin:/bin"}
    r = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("muse_images.py")), "--only", "judges-title"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0
    assert "No META_API_KEY" in r.stdout


def test_generates_crops_to_exact_size_writes_sidecar_and_never_prints_the_key(monkeypatch, tmp_path, capsys):
    sent = {}

    def fake_urlopen(req, timeout):
        sent["url"] = req.full_url
        sent["auth"] = req.headers["Authorization"]
        sent["body"] = json.loads(req.data)
        return FakeResponse(json.dumps({"data": [{"b64_json": base64.b64encode(png(1024, 1024)).decode()}]}).encode())

    monkeypatch.setattr(muse_images.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(muse_images, "OUT", tmp_path)
    monkeypatch.setenv("META_API_KEY", KEY)
    monkeypatch.setattr(sys, "argv", ["muse_images.py", "--only", "judges-title"])
    muse_images.main()
    out = capsys.readouterr().out
    assert KEY not in out
    assert sent["url"] == "https://api.meta.ai/v1/images/generations"
    assert sent["auth"] == f"Bearer {KEY}"
    body = sent["body"]
    assert body["model"] == "muse-image-1.0" and body["size"] == "1920x1080" and body["output_format"] == "png"
    assert body["response_format"] == "b64_json" and body["n"] == 1
    assert Image.open(tmp_path / "judges-title.png").size == (1920, 1080)
    side = json.loads((tmp_path / "judges-title.json").read_text())
    assert side["model"] == "muse-image-1.0" and side["prompt"].startswith("Flat, clean vector") and side["date"]
    assert KEY not in json.dumps(side)
    # A second run skips the card that exists.
    sent.clear()
    muse_images.main()
    assert not sent


def test_retries_a_503_then_succeeds(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, io.BytesIO(b"{}"))
        return FakeResponse(json.dumps({"data": [{"b64_json": base64.b64encode(b"x").decode()}]}).encode())

    monkeypatch.setattr(muse_images.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(muse_images.time, "sleep", lambda s: None)
    assert muse_images.request_image(KEY, "p", "1280x720") == b"x"
    assert len(calls) == 2


def test_a_safety_block_is_reported_not_retried(monkeypatch):
    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(b'{"code":"content_policy_violation"}'))

    monkeypatch.setattr(muse_images.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="content_policy_violation"):
        muse_images.request_image(KEY, "p", "1280x720")


def test_cards_use_art_when_present_and_fall_back_to_brand_colour(monkeypatch, tmp_path):
    monkeypatch.setattr(segments, "CARDS", tmp_path)
    assert segments.art("judges-title") == ""
    (tmp_path / "judges-title.png").write_bytes(png(10, 10))
    assert segments.art("judges-title").endswith("judges-title.png")
    assert segments.section_art("Use of Meta AI tooling — which models") == "section-meta-ai"
    assert segments.section_art("Demo quality — one receipt end to end") == "section-demo"


def test_judge_facing_video_text_names_no_hardware_tool_or_voice_engine():
    banned = ["dgx", "ollama", "kokoro", "vllm", "whisper", "comfyui", "bm_george"]
    texts = [
        (ROOT / "docs/video/JUDGES_VIDEO.md").read_text(encoding="utf-8"),
        (ROOT / "docs/video/CLIPS.md").read_text(encoding="utf-8"),
        (ROOT / "docs/video/README.md").read_text(encoding="utf-8"),
        (ROOT / "docs/video/IMAGE_PROMPTS.md").read_text(encoding="utf-8"),
        (ROOT / "docs/video/vo/lines.json").read_text(encoding="utf-8"),
        segments.PROVENANCE_TITLE + segments.PROVENANCE_BODY + segments.CREDIT,
    ]
    manifest = ROOT / "docs/video/manifest.json"
    if manifest.exists():
        texts.append(manifest.read_text(encoding="utf-8"))
    for t in texts:
        low = t.lower()
        for word in banned:
            assert word not in low, word
        # "Muse Spark" is a model; "Spark" alone would be the hardware.
        assert not re.search(r"(?<!muse )\bspark\b(?! open| 1\.\d)", low.replace("muse spark open", "")), "Spark"
    assert segments.CREDIT == "Title art: Muse Image (Meta)."
