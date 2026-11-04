# ruff: noqa  (one-off video edit script; kept as it was run)
"""Kokoro (open-source, Apache-2.0) voice-over for the v2 demo video. Runs on the Spark in ~/spark/accnomos/tts/.venv.

    python tts.py LINES.json OUTDIR VOICE [--ids s1,s3] [--speed 1.0] [--suffix _x]
Writes OUTDIR/<id><suffix>.wav (24 kHz mono) and prints each length. Pronunciation fixes are applied to the spoken
text only (the captions keep the script's words).
"""
import argparse
import json
import wave

import numpy as np
from kokoro import KPipeline

SAY = {"£450": "four hundred and fifty pounds", "CSV": "C S V", "HMRC's": "H M R C's", "HMRC": "H M R C",
       "OneDrive": "One Drive", "Muse": "Muse"}

ap = argparse.ArgumentParser()
ap.add_argument("lines"); ap.add_argument("out"); ap.add_argument("voice")
ap.add_argument("--ids", default=""); ap.add_argument("--speed", type=float, default=1.0); ap.add_argument("--suffix", default="")
a = ap.parse_args()
items = json.load(open(a.lines, encoding="utf-8"))
ids = set(filter(None, a.ids.split(",")))
pipe = KPipeline(lang_code="b")
for it in items:
    if ids and it["id"] not in ids: continue
    text = it.get("say", it["text"])
    for k, v in SAY.items(): text = text.replace(k, v)
    audio = np.concatenate([np.asarray(x, dtype=np.float32) for _, _, x in pipe(text, voice=a.voice, speed=a.speed)])
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    fn = f"{a.out}/{it['id']}{a.suffix}.wav"
    with wave.open(fn, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm.tobytes())
    print(f"{fn} {len(pcm)/24000:.2f}s", flush=True)
