#!/usr/bin/env bash
# Render the PayPal video narration with the existing voice-over tool (tools/video/v3/tts.py), voice bf_emma
# (British English, female), 24 kHz mono WAV per scene. Run on the GPU server, in the TTS venv the v3 video used:
#
#   cd <repo on the GPU server> && git fetch origin && git checkout paypal-video
#   source <the TTS venv>/bin/activate
#   bash docs/submission/paypal/narration/render.sh            # all scenes
#   bash docs/submission/paypal/narration/render.sh w1,w2,w3   # some lines only (v6 ids: i0 pr w1…w13 d1 d2 d3 o0)
#
# v6: i0 and pr are the PRESENTER slots (a labelled AI presenter, never presented as the founder; the clips carry
# their own sound); every other line, o0 included, is voice only. On a machine with no GPU the same lines were
# rendered with the Kokoro ONNX build (kokoro-onnx, kokoro-v1.0.onnx, voice bf_emma, lang en-gb, speed 1.0).
#   SPEED=1.05 bash docs/submission/paypal/narration/render.sh # a touch faster if the cut runs long
#
# lines.json is the source the tool reads ("text" is captioned, "say" is spoken when present). The per-scene .txt
# files hold the same text for the edit and for reading aloud; keep them in step with lines.json when editing.
# The tool runs on CPU too (slower); no GPU is needed for ten short lines.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../../../.." && pwd)"
out="${OUT:-$repo/docs/video/paypal-vo}"
mkdir -p "$out"
ids="${1:-}"
args=("$here/lines.json" "$out" "${VOICE:-bf_emma}" --speed "${SPEED:-1.0}")
[[ -n "$ids" ]] && args+=(--ids "$ids")
python "$repo/tools/video/v3/tts.py" "${args[@]}"
# Lengths against the scene budget in docs/submission/paypal/VIDEO_SCRIPT.md (seconds of narration per scene):
python - "$out" <<'EOF'
import sys, wave, pathlib
budget = {"i0": 10.4, "pr": 6.0, "w1": 6.6, "w2": 7.6, "w3": 6.6, "w4": 12.0, "w5": 4.8, "w6": 8.2, "w7": 11.0, "w8": 6.6, "w9": 13.6, "w10": 5.6, "w11": 9.0, "w12": 5.0, "w13": 4.2, "d1": 17.5, "d2": 7.8, "d3": 8.8, "o0": 7.6}
total = 0.0
for wav in [pathlib.Path(sys.argv[1]) / f"{k}.wav" for k in budget if (pathlib.Path(sys.argv[1]) / f"{k}.wav").exists()]:
    with wave.open(str(wav)) as w:
        s = w.getnframes() / w.getframerate()
    total += s
    flag = "  OVER" if s > budget.get(wav.stem, 99) else ""
    print(f"{wav.stem}: {s:5.1f}s (budget {budget.get(wav.stem, '?')}s){flag}")
print(f"narration total {total:.1f}s; the v6 cut is 2:39; it must stay at or under 2:50 (170 s) with the dwell time between lines")
EOF
