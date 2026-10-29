"""Voice-over for the captured shots: the lines to speak, and (on the owner's Spark) the WAVs.

    python3 tools/video/vo.py lines              # docs/video/vo/lines.json from docs/video/manifest.json (any machine)
    python tools/video/vo.py kokoro [--voice bm_george] [--force]
        # on the Spark: Kokoro TTS → docs/video/vo/<shot-id>.wav

`lines.json` has the same shape as tools/teaser/vo/lines.json (file, voice, text) plus the shot's length, so the
teaser's Kokoro set-up can read it as is. `kokoro` needs the `kokoro` package (Apache-2.0, British English voices,
24 kHz mono) and numpy; it has not been run in the cloud session that wrote it, only on the owner's Spark is it
expected to work. assemble.sh picks each <shot-id>.wav up by name and warns when one is longer than its shot.
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs/video/manifest.json"
VO = ROOT / "docs/video/vo"


def lines(voice: str) -> list[dict]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out = []
    for seq in manifest["sequences"]:
        for s in seq["shots"]:
            if s.get("vo"):
                out.append({"file": f"{s['id']}.wav", "voice": voice, "text": s["vo"], "seconds": s["duration"]})
    return out


def write_lines(voice: str) -> None:
    VO.mkdir(parents=True, exist_ok=True)
    items = lines(voice)
    (VO / "lines.json").write_text(json.dumps(items, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    words = sum(len(i["text"].split()) for i in items)
    print(f"wrote docs/video/vo/lines.json: {len(items)} lines, {words} words")


def kokoro(voice: str, force: bool) -> None:  # pragma: no cover - runs on the Spark only
    import numpy as np
    from kokoro import KPipeline

    pipe = KPipeline(lang_code="b")  # British English
    for item in lines(voice):
        out = VO / item["file"]
        if out.exists() and not force:
            continue
        audio = np.concatenate([np.asarray(a, dtype=np.float32) for _, _, a in pipe(item["text"], voice=voice)])
        pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(pcm.tobytes())
        secs = len(pcm) / 24000
        flag = "  LONGER THAN THE SHOT" if secs > item["seconds"] else ""
        print(f"{item['file']}: {secs:.1f} s of {item['seconds']} s{flag}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["lines", "kokoro"])
    ap.add_argument("--voice", default="bm_george")  # the teaser's voice (tools/teaser/build.py)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    write_lines(a.voice)
    if a.command == "kokoro":
        kokoro(a.voice, a.force)


if __name__ == "__main__":
    main()
