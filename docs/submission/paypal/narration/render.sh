#!/usr/bin/env bash
# Render the PayPal video narration with the existing voice-over tool (tools/video/v3/tts.py), voice bf_emma
# (British English, female), 24 kHz mono WAV per scene. Run on the GPU server, in the TTS venv the v3 video used:
#
#   cd <repo on the GPU server> && git fetch origin && git checkout paypal-video
#   source <the TTS venv>/bin/activate
#   bash docs/submission/paypal/narration/render.sh            # all scenes
#   bash docs/submission/paypal/narration/render.sh ai,m1,fl                        # the lines new or changed in v4 (12 Nov)
#
# i0 and o0 are the PRESENTER slots, spoken by a labelled AI presenter (never presented as the founder). If the
# presenter tool makes its own audio, skip them: render.sh pr,hw,h1,ag,h2,h3,h4,h5,ai,m1,fl
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
budget = {"i0": 10.4, "pr": 4.8, "hw": 5.6, "h1": 18, "ag": 9.5, "h2": 14.5, "h3": 8, "h4": 20, "h5": 8, "ai": 5, "ea": 8, "eb": 8, "ec": 7, "ed": 8, "ee": 5, "ef": 6, "eg": 5, "eh": 5, "o0": 7.4}
total = 0.0
for wav in [pathlib.Path(sys.argv[1]) / f"{k}.wav" for k in budget if (pathlib.Path(sys.argv[1]) / f"{k}.wav").exists()]:
    with wave.open(str(wav)) as w:
        s = w.getnframes() / w.getframerate()
    total += s
    flag = "  OVER" if s > budget.get(wav.stem, 99) else ""
    print(f"{wav.stem}: {s:5.1f}s (budget {budget.get(wav.stem, '?')}s){flag}")
print(f"narration total {total:.1f}s; the planned v5 cut is 2:46; it must stay at or under 2:50 (170 s) with the dwell time between lines")
EOF
