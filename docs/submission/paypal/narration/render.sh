#!/usr/bin/env bash
# Render the PayPal video narration with the existing voice-over tool (tools/video/v3/tts.py), voice bf_emma
# (British English, female), 24 kHz mono WAV per scene. Run on the GPU server, in the TTS venv the v3 video used:
#
#   cd <repo on the GPU server> && git fetch origin && git checkout paypal-video
#   source <the TTS venv>/bin/activate
#   bash docs/submission/paypal/narration/render.sh            # all scenes
#   bash docs/submission/paypal/narration/render.sh h1,h4      # only these scenes
#
# i0 and o0 are the PRESENTER slots (founder, first person). Render them only if the owner chooses a labelled AI
# presenter; if he records them on camera himself, skip them: render.sh h1,h2,h3,h4,h5,h6,m1
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
budget = {"i0": 10, "h1": 28, "h2": 18, "h3": 10, "h4": 26, "h5": 16, "h6": 7, "m1": 45, "o0": 8}
total = 0.0
for wav in sorted(pathlib.Path(sys.argv[1]).glob("[ihmo][0-9].wav")):
    with wave.open(str(wav)) as w:
        s = w.getnframes() / w.getframerate()
    total += s
    flag = "  OVER" if s > budget.get(wav.stem, 99) else ""
    print(f"{wav.stem}: {s:5.1f}s (budget {budget.get(wav.stem, '?')}s){flag}")
print(f"narration total {total:.1f}s; the planned cut is 2:48; it must stay at or under 2:50 (170 s) with the dwell time between lines")
EOF
