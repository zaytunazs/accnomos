#!/usr/bin/env bash
# Stitch the captured shots into the judges' video and each clip (ffmpeg + libass).
#
#   tools/video/assemble.sh                     # every sequence in docs/video/manifest.json, silent preview quality
#   tools/video/assemble.sh --final             # full quality, with voice-over from docs/video/vo/<shot-id>.wav
#   tools/video/assemble.sh --only judges       # one sequence (judges, clip-review, …)
#   tools/video/assemble.sh --no-test-tag       # drop the "Test-mode capture · AI stubbed" corner tag
#   tools/video/assemble.sh --covers            # only the how-to guide covers (docs/howto/img/<guide>-cover.png)
#
# Per shot: the raw WebM is fitted to the script's duration (held on its last frame if short, sped up and tagged
# "sped up" if long), the caption is burned in (Atkinson Hyperlegible, white on a dark box, inside title-safe
# margins), and the audio is docs/video/vo/<shot-id>.wav padded to the shot (or silence when there is none yet).
# Cards (title, provenance, eval, end, and placeholders for camera shots) are drawn from text over the Muse Image art in
# docs/video/cards/ (tools/video/muse_images.py), or over plain brand colour where a picture is missing. The judges'
# video always opens with the provenance card and ends on the end card with the art credit. Each sequence also gets
# <sequence>-thumbnail.png (1280 × 720). Output: docs/video/preview/<sequence>.mp4 (preview) or docs/video/out/<sequence>.mp4
# (--final). Both folders are git-ignored; regenerate with tools/video/regenerate.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
MANIFEST=docs/video/manifest.json
FONTS="$ROOT/tools/video/fonts"
FINAL=0
ONLY=""
TAG_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --final) FINAL=1 ;;
    --only) ONLY="$2"; shift ;;
    --no-test-tag) TAG_ARGS+=(--no-test-tag) ;;
    --covers) exec "${PYTHON:-python3}" tools/video/covers.py ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
command -v ffmpeg >/dev/null || { echo "ffmpeg is not on PATH" >&2; exit 1; }
[[ -f "$MANIFEST" ]] || { echo "no $MANIFEST: run tools/video/capture.ts first" >&2; exit 1; }

if [[ $FINAL == 1 ]]; then OUTDIR=docs/video/out; CRF=18; PRESET=slow; else OUTDIR=docs/video/preview; CRF=27; PRESET=veryfast; fi
mkdir -p "$OUTDIR"
PY="${PYTHON:-python3}"

sequences=$("$PY" -c "import json,sys; print('\n'.join(s['id'] for s in json.load(open('$MANIFEST'))['sequences']))")
for seq in $sequences; do
  [[ -n "$ONLY" && "$seq" != "$ONLY" ]] && continue
  read -r W H < <("$PY" -c "import json; s=[s for s in json.load(open('$MANIFEST'))['sequences'] if s['id']=='$seq'][0]; print(s['width'], s['height'])")
  WORK="docs/video/.work/$seq"
  rm -rf "$WORK"; mkdir -p "$WORK"
  plan=$("$PY" tools/video/segments.py --sequence "$seq" --work "$WORK" "${TAG_ARGS[@]}")
  : > "$WORK/list.txt"
  n=0
  # Card art (Muse Image, docs/video/cards/) is cropped to fill the frame and dimmed under the text; without it the card
  # is plain brand colour. The text is always drawn here, never baked into the art.
  fill="scale=${W}:${H}:force_original_aspect_ratio=increase,crop=${W}:${H},setsar=1"
  scrim="drawbox=x=0:y=0:w=iw:h=ih:color=0x0A4F47@0.5:t=fill"
  while IFS=$'\x1f' read -r kind id dur src speed ass vo art end_start end_art; do
    subs="subtitles=filename='$ass':fontsdir='$FONTS'"
    if [[ "$kind" == thumb ]]; then
      thumb="$OUTDIR/$seq-thumbnail.png"
      if [[ -n "$art" ]]; then tin=(-i "$art"); tf="scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1,$scrim"
      else tin=(-f lavfi -i "color=c=$src:s=1280x720"); tf="null"; fi
      ffmpeg -nostdin -y -hide_banner -loglevel error "${tin[@]}" -vf "$tf,$subs" -frames:v 1 "$thumb"
      continue
    fi
    n=$((n + 1))
    seg="$WORK/$(printf '%03d' "$n")-$id.mp4"
    if [[ -n "$vo" ]]; then
      audio=(-i "$vo")
    else
      audio=(-f lavfi -t "$dur" -i "anullsrc=channel_layout=stereo:sample_rate=48000")
    fi
    if [[ "$kind" == card ]]; then
      if [[ -n "$art" ]]; then
        vin=(-loop 1 -framerate 30 -t "$dur" -i "$art")
        base="${fill},${scrim},fps=30"
      else
        vin=(-f lavfi -t "$dur" -i "color=c=$src:s=${W}x${H}:r=30")
        base="null"
      fi
      fades="fade=t=in:st=0:d=0.3,fade=t=out:st=$(awk "BEGIN{print $dur-0.3}"):d=0.3"
    else
      vin=(-i "$src")
      # Fit to the shot: speed up when long, hold the last frame when short; then trim exactly.
      base="setpts=PTS/${speed},tpad=stop_mode=clone:stop_duration=${dur},trim=duration=${dur},setpts=PTS-STARTPTS,scale=${W}:${H}:flags=lanczos,fps=30"
      fades="null"
    fi
    if [[ -n "$end_art" ]]; then
      # The end card's art fades in over the last seconds; its text comes from the ASS file, above everything.
      endin=(-loop 1 -framerate 30 -t "$dur" -i "$end_art")
      graph="[0:v]${base}[b];[2:v]${fill},${scrim},format=yuva420p,fade=t=in:st=${end_start}:d=0.25:alpha=1[e];[b][e]overlay=enable='gte(t,${end_start})'[o];[o]${subs},${fades},format=yuv420p[v]"
    else
      endin=()
      graph="[0:v]${base},${subs},${fades},format=yuv420p[v]"
    fi
    ffmpeg -nostdin -y -hide_banner -loglevel error "${vin[@]}" "${audio[@]}" "${endin[@]}" \
      -filter_complex "${graph};[1:a]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration=${dur}[a]" \
      -map "[v]" -map "[a]" -t "$dur" -c:v libx264 -preset "$PRESET" -crf "$CRF" -pix_fmt yuv420p -r 30 \
      -c:a aac -b:a 160k -ar 48000 "$seg"
    if [[ -n "$vo" ]]; then
      vlen=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$vo")
      awk "BEGIN{exit !($vlen > $dur + 0.05)}" && echo "  warning: $id voice-over is ${vlen}s, the shot ${dur}s (cut)" >&2
    fi
    echo "file '$(basename "$seg")'" >> "$WORK/list.txt"
  done <<< "$plan"
  out="$OUTDIR/$seq.mp4"
  ffmpeg -nostdin -y -hide_banner -loglevel error -f concat -safe 0 -i "$WORK/list.txt" -c copy -movflags +faststart "$out"
  len=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$out")
  printf '%s  %ss  %s  (+ %s-thumbnail.png)\n' "$out" "${len%.*}" "$(du -h "$out" | cut -f1)" "$seq"
done
