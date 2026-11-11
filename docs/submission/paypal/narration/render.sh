#!/usr/bin/env bash
# Render the PayPal video narration with the existing voice-over tool (tools/video/v3/tts.py), voice bf_emma
# (British English, female), 24 kHz mono WAV per scene. Run on the Spark, in the TTS venv the v3 video used:
#
#   cd ~/spark/accnomos && git fetch origin && git checkout paypal-video
#   source ~/spark/accnomos/tts/.venv/bin/activate
#   bash docs/submission/paypal/narration/render.sh            # all scenes
#   bash docs/submission/paypal/narration/render.sh p4,p6      # only these scenes
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
budget = {"p0": 10, "p1": 15, "p2": 15, "p3": 7, "p4": 25, "p5": 10, "p6": 23, "p7": 15, "p8": 9, "p9": 9}
total = 0.0
for wav in sorted(pathlib.Path(sys.argv[1]).glob("p[0-9].wav")):
    with wave.open(str(wav)) as w:
        s = w.getnframes() / w.getframerate()
    total += s
    flag = "  OVER" if s > budget.get(wav.stem, 99) else ""
    print(f"{wav.stem}: {s:5.1f}s (budget {budget.get(wav.stem, '?')}s){flag}")
print(f"narration total {total:.1f}s; the cut must stay at or under 2:50 (170 s) with the dwell time between lines")
EOF
