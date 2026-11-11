#!/usr/bin/env bash
# PayPal hackathon video: assemble the cut from a timeline (EDL) JSON with ffmpeg.
#
#   tools/video/paypal/assemble_paypal.sh TIMELINE.json OUT.mp4 [--vo DIR] [--presenter DIR] [--keep]
#
# TIMELINE.json lists every segment at its script time (docs/submission/paypal/VIDEO_SCRIPT.md v4): source file,
# in-point, speed, burned-in caption, blur boxes. Paths in it are relative to its "media_root" (default: the folder
# the timeline is in). The draft timeline is tools/video/paypal/timeline_paypal.json: copy it into the media folder
# (cards/, raw/ as captured by capture_paypal.ts, vo/, presenter/) and run from there.
#
#   --vo DIR         voice-over WAVs named <id>.wav (i0 pr hw h1 ag h2 h3 h4 h5 ai m1 fl o0). Each is placed at its
#                    segment's start + "vo_lead" (default 0.3 s). A missing WAV is silence (and is reported).
#   --presenter DIR  presenter_intro.mp4 / presenter_outro.mp4. Present: each replaces its black slate, scaled to
#                    1920x1080 and labelled "AI presenter" for the whole slot; if the clip has sound, that sound is
#                    used and i0.wav / o0.wav are skipped. Missing: a labelled black slate of the slot's length.
#   --keep           keep the per-segment intermediates (OUT dir/.segments).
#
# Writes OUT.mp4 (H.264 veryfast CRF 20, AAC 192k, 30 fps, 1920x1080), OUT.srt (the narration, from
# docs/submission/paypal/narration/lines.json, timed to the WAVs), OUT.edl.json (every segment resolved: source,
# in/out, caption, start/end in the cut) and OUT.contact.jpg (one frame per segment).
# Needs python3 and an ffmpeg with libass (subtitles filter), libx264 and xfade. Fonts: Inter if installed, else
# libass falls back to a system sans.
#
# Re-assembling with the owner's files (on any machine with the media folder):
#   tools/video/paypal/assemble_paypal.sh MEDIA/timeline_paypal.json out/accnomos_paypal_final.mp4 \
#       --vo MEDIA/vo_owner --presenter MEDIA/presenter
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../../.." && pwd)"
[[ $# -ge 2 ]] || { sed -n '2,25p' "$0"; exit 2; }
exec python3 - "$repo" "$@" <<'PY'
import json, os, subprocess, sys, shutil, wave, tempfile

repo, timeline_path, out = sys.argv[1], sys.argv[2], sys.argv[3]
args = sys.argv[4:]
opt = {"--vo": None, "--presenter": None}
keep = False
i = 0
while i < len(args):
    if args[i] in opt:
        opt[args[i]] = os.path.abspath(args[i + 1]); i += 2
    elif args[i] == "--keep":
        keep = True; i += 1
    else:
        sys.exit(f"unknown option {args[i]}")

T = json.load(open(timeline_path, encoding="utf-8"))
root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(timeline_path)), T.get("media_root", ".")))
W, H, FPS = T.get("width", 1920), T.get("height", 1080), T.get("fps", 30)
XF = float(T.get("xfade", 0.25))
LEAD = float(T.get("vo_lead", 0.3))
out = os.path.abspath(out)
base = os.path.splitext(out)[0]
work = os.path.join(os.path.dirname(out), ".segments")
os.makedirs(work, exist_ok=True)
lines = {l["id"]: l for l in json.load(open(os.path.join(repo, "docs/submission/paypal/narration/lines.json"), encoding="utf-8"))}

def P(p):
    return p if os.path.isabs(p) else os.path.join(root, p)

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(" ".join(cmd) + "\n" + r.stderr[-3000:])
        sys.exit(f"ffmpeg failed")

def probe_dur(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0

def has_audio(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", f], capture_output=True, text=True)
    return bool(r.stdout.strip())

def wav_len(f):
    with wave.open(f) as w:
        return w.getnframes() / w.getframerate()

# ---- captions (ASS): bottom-left dark band in the app's colours; a small tag top-right --------------------------
def ass_escape(t):
    return t.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")

def write_ass(path, dur, caption=None, tag=None, label=None, centre=None, timed=None):
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Inter,46,&H00FFFFFF,&H00FFFFFF,&H1A0E1C2C,&H00000000,-1,0,0,0,100,100,0,0,3,16,0,1,96,560,84,1
Style: Tag,Inter,34,&H00FFFFFF,&H00FFFFFF,&H1A002D5A,&H00000000,-1,0,0,0,100,100,0,0,3,12,0,9,60,60,48,1
Style: Label,Inter,40,&H00FFFFFF,&H00FFFFFF,&H1A002D5A,&H00000000,-1,0,0,0,100,100,0,0,3,14,0,7,60,60,48,1
Style: Centre,Inter,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,5,120,120,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    def ts(s):
        s = max(0.0, s); h = int(s // 3600); m = int(s % 3600 // 60); sec = s % 60
        return f"{h}:{m:02d}:{sec:05.2f}"
    ev = []
    end = ts(dur + 1)
    if caption:
        txt = "\\N".join(ass_escape(p.strip()) for p in caption.split(" · "))
        ev.append(f"Dialogue: 0,{ts(0)},{end},Cap,,0,0,0,,{txt}")
    for (a, b, c) in (timed or []):
        txt = "\\N".join(ass_escape(p.strip()) for p in c.split(" · "))
        ev.append(f"Dialogue: 0,{ts(a)},{ts(b)},Cap,,0,0,0,,{txt}")
    if tag:
        ev.append(f"Dialogue: 0,{ts(0)},{end},Tag,,0,0,0,,{ass_escape(tag)}")
    if label:
        ev.append(f"Dialogue: 0,{ts(0)},{end},Label,,0,0,0,,{ass_escape(label)}")
    if centre:
        ev.append(f"Dialogue: 0,{ts(0)},{end},Centre,,0,0,0,,{ass_escape(centre)}")
    open(path, "w", encoding="utf-8").write(head + "\n".join(ev) + "\n")
    return path

def subs_filter(ass):
    p = ass.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return f"subtitles='{p}'"

ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", "-r", str(FPS), "-an"]

def blur_chain(blurs, label_in="v0"):
    """Box blur over each {x,y,w,h,from,to} rectangle (output pixels, segment seconds)."""
    f = []
    cur = label_in
    for k, b in enumerate(blurs or []):
        x, y, w, h = int(b["x"]), int(b["y"]), int(b["w"]), int(b["h"])
        en = f":enable='between(t,{b.get('from', 0)},{b.get('to', 9999)})'"
        f.append(f"[{cur}]split[bb{k}a][bb{k}b];[bb{k}b]crop={w}:{h}:{x}:{y},boxblur=lr={max(1, min(16, min(w, h) // 2 - 1))}:lp=3:cr={max(1, min(8, min(w, h) // 4 - 1))}:cp=3[bb{k}c];[bb{k}a][bb{k}c]overlay={x}:{y}{en}[bo{k}]")
        cur = f"bo{k}"
    return f, cur

def render(seg, dur, dst, presenter_dir):
    """One segment, video only, exactly `dur` seconds at W x H, FPS, captions burned in."""
    kind = seg["type"]
    ass = os.path.join(work, os.path.basename(dst) + ".ass")
    tag, label, centre = seg.get("tag"), seg.get("label"), None
    cap = seg.get("caption")
    if kind == "presenter":
        clip = os.path.join(presenter_dir, seg["file"]) if presenter_dir else None
        if clip and os.path.exists(clip):
            kind = "video"
            seg = dict(seg, src=clip, **{"in": 0})
            label = seg.get("label", "AI presenter")
        else:
            kind = "slate"
            seg = dict(seg, text=seg.get("slate_text"))
    write_ass(ass, dur, cap, tag, label, None, seg.get("timed_captions"))
    if kind == "slate":
        write_ass(ass, dur, cap, tag, label, seg.get("text"), seg.get("timed_captions"))
        run(["ffmpeg", "-y", "-hide_banner", "-f", "lavfi", "-i", f"color=c={seg.get('color', 'black')}:s={W}x{H}:r={FPS}:d={dur}",
             "-vf", subs_filter(ass), "-t", f"{dur:.3f}", *ENC, dst])
        return
    if kind in ("still", "stills"):
        srcs = [P(s) for s in (seg["srcs"] if kind == "stills" else [seg["src"]])]
        each = dur / len(srcs)
        inputs, fl = [], []
        for k, s in enumerate(srcs):
            d = each if k < len(srcs) - 1 else dur - each * (len(srcs) - 1)
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{d:.3f}", "-i", s]
            fl.append(f"[{k}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[s{k}]")
        fl.append("".join(f"[s{k}]" for k in range(len(srcs))) + f"concat=n={len(srcs)}:v=1:a=0[v0]")
        cur = "v0"
        if seg.get("zoom"):
            z = float(seg["zoom"])  # e.g. 0.03 = a slow 3 % zoom over the segment
            n = int(dur * FPS)
            fl.append(f"[v0]scale={W*2}:{H*2},zoompan=z='1+{z}*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}[vz]")
            cur = "vz"
        fl.append(f"[{cur}]{subs_filter(ass)}[vout]")
        run(["ffmpeg", "-y", "-hide_banner", *inputs, "-filter_complex", ";".join(fl), "-map", "[vout]", "-t", f"{dur:.3f}", *ENC, dst])
        return
    if kind == "video":
        src = P(seg["src"])
        sp = float(seg.get("speed", 1.0))
        t_in = float(seg.get("in", 0))
        fl = [f"[0:v]setpts=(PTS-STARTPTS)/{sp},fps={FPS}"]
        if seg.get("crop"):
            x, y, w, h = seg["crop"]
            fl[0] += f",scale={W}:{H},crop={w}:{h}:{x}:{y}"
        fl[0] += f",scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0xf4f3ee,setsar=1,format=yuv420p,tpad=stop_mode=clone:stop_duration={dur + 2}[v0]"
        bl, cur = blur_chain(seg.get("blur"))
        fl += bl
        fl.append(f"[{cur}]{subs_filter(ass)}[vout]")
        run(["ffmpeg", "-y", "-hide_banner", "-ss", f"{t_in:.3f}", "-i", src, "-filter_complex", ";".join(fl), "-map", "[vout]", "-t", f"{dur:.3f}", *ENC, dst])
        return
    if kind == "group":
        parts = []
        t = 0.0
        for k, ch in enumerate(seg["children"]):
            d = float(ch["dur"])
            if k == len(seg["children"]) - 1:
                d = dur - t  # the last child takes what is left (incl. the cross-fade overlap)
            pdst = f"{dst}.{k:02d}.mp4"
            render(ch, d, pdst, presenter_dir)
            parts.append(pdst)
            t += d
        lst = dst + ".txt"
        open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
        run(["ffmpeg", "-y", "-hide_banner", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", dst])
        return
    sys.exit(f"unknown segment type {kind}")

# ---- 1. segments ------------------------------------------------------------------------------------------------
segs = T["segments"]
t = 0.0
edl = []
for k, s in enumerate(segs):
    s["start"] = round(t, 3)
    t += float(s["dur"])
total = t
paths = []
for k, s in enumerate(segs):
    d = float(s["dur"]) + (XF if k < len(segs) - 1 else 0.0)
    dst = os.path.join(work, f"{k:02d}_{s['id']}.mp4")
    print(f"[{s['start']:6.2f}] {s['id']:<4} {s['type']:<9} {float(s['dur']):5.2f}s", flush=True)
    render(s, d, dst, opt["--presenter"])
    paths.append(dst)

# ---- 2. audio: VO at each segment's start + lead; presenter sound when the clip has it ----------------------------
a_inputs, a_filters, n_a, srt = [], [], 0, []
missing = []
for s in segs:
    vid = s.get("vo")
    if not vid:
        continue
    start = s["start"] + float(s.get("vo_lead", LEAD))
    src = None
    if s["type"] == "presenter" and opt["--presenter"]:
        clip = os.path.join(opt["--presenter"], s["file"])
        if os.path.exists(clip) and has_audio(clip):
            src, start, length = clip, s["start"], min(probe_dur(clip), float(s["dur"]))
    if src is None and opt["--vo"] and os.path.exists(os.path.join(opt["--vo"], f"{vid}.wav")):
        src = os.path.join(opt["--vo"], f"{vid}.wav")
        length = wav_len(src)
        room = float(s["dur"]) - float(s.get("vo_lead", LEAD))
        if length > room + 0.05:
            print(f"  WARNING {vid}.wav is {length:.2f}s; the slot leaves {room:.2f}s", flush=True)
    if src is None:
        missing.append(vid)
        length = float(s["dur"]) - 0.6
    else:
        a_inputs += ["-i", src]
        a_filters.append(f"[{1 + n_a}:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{float(s['dur']):.3f},adelay={int(start * 1000)}|{int(start * 1000)}[a{n_a}]")
        n_a += 1
    if vid in lines:
        srt.append((start, min(start + length, s["start"] + float(s["dur"])), lines[vid]["text"]))
if missing:
    print("  no voice-over for: " + ", ".join(missing) + " (silent in this cut; narration is in the .srt)", flush=True)

# ---- 3. join: cross-fades at each segment's script time, then the mix -------------------------------------------
inputs = []
for p in paths:
    inputs += ["-i", p]
fl = []
cur = "0:v"
for k in range(1, len(paths)):
    nxt = f"x{k}"
    fl.append(f"[{cur}][{k}:v]xfade=transition=fade:duration={XF}:offset={segs[k]['start']:.3f}[{nxt}]")
    cur = nxt
vmap = f"[{cur}]" if len(paths) > 1 else "0:v"
nV = len(paths)
a_filters = [f.replace(f"[{1 + j}:a]", f"[{nV + j}:a]") for j, f in enumerate(a_filters)]
fl += a_filters
if n_a:
    fl.append("".join(f"[a{j}]" for j in range(n_a)) + f"amix=inputs={n_a}:normalize=0:dropout_transition=0,apad,atrim=0:{total:.3f},loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[aout]")
else:
    fl.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{total:.3f}[aout]")
cmd = ["ffmpeg", "-y", "-hide_banner", *inputs, *a_inputs, "-filter_complex", ";".join(fl), "-map", vmap, "-map", "[aout]",
       "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
       "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{total:.3f}", out]
print("joining…", flush=True)
run(cmd)

# ---- 4. sidecars: SRT, EDL, contact sheet ---------------------------------------------------------------------
def srt_ts(s):
    ms = int(round(s * 1000)); return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
with open(base + ".srt", "w", encoding="utf-8") as f:
    for n, (a, b, txt) in enumerate(srt, 1):
        f.write(f"{n}\n{srt_ts(a)} --> {srt_ts(b)}\n{txt}\n\n")

def res(s):
    r = {k: v for k, v in s.items() if k not in ("children",)}
    r["end"] = round(s["start"] + float(s["dur"]), 3)
    if s["type"] == "video":
        r["out"] = round(float(s.get("in", 0)) + float(s["dur"]) * float(s.get("speed", 1)), 3)
    if s["type"] == "group":
        t0 = s["start"]; kids = []
        for ch in s["children"]:
            c = dict(ch, start=round(t0, 3)); c["end"] = round(t0 + float(ch["dur"]), 3)
            if ch["type"] == "video":
                c["out"] = round(float(ch.get("in", 0)) + float(ch["dur"]) * float(ch.get("speed", 1)), 3)
            kids.append(c); t0 += float(ch["dur"])
        r["children"] = kids
    return r
json.dump({"output": out, "runtime_s": round(total, 3), "xfade_s": XF, "vo_dir": opt["--vo"], "presenter_dir": opt["--presenter"],
           "media_root": root, "segments": [res(s) for s in segs]}, open(base + ".edl.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)

frames = []
for s in segs:
    if s["type"] == "group":
        t0 = s["start"]
        for k, ch in enumerate(s["children"]):
            frames.append((f"{s['id']}.{k + 1}", t0 + float(ch["dur"]) * 0.6)); t0 += float(ch["dur"])
    else:
        frames.append((s["id"], s["start"] + float(s["dur"]) * 0.6))
sheet = os.path.join(work, "sheet"); os.makedirs(sheet, exist_ok=True)
for n, (name, at) in enumerate(frames):
    run(["ffmpeg", "-y", "-hide_banner", "-ss", f"{at:.2f}", "-i", out, "-frames:v", "1", "-vf", "scale=480:270", os.path.join(sheet, f"{n:02d}.png")])
try:
    from PIL import Image, ImageDraw, ImageFont
    cols = 4; rows = (len(frames) + cols - 1) // cols
    im = Image.new("RGB", (cols * 490 + 10, rows * 310 + 10), (28, 20, 14))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("Inter-Bold.otf", 20)
    except OSError:
        font = ImageFont.load_default()
    for n, (name, at) in enumerate(frames):
        x, y = 10 + n % cols * 490, 10 + n // cols * 310
        im.paste(Image.open(os.path.join(sheet, f"{n:02d}.png")), (x, y))
        d.text((x, y + 274), f"{name}  @ {int(at // 60)}:{at % 60:04.1f}", fill=(240, 220, 170), font=font)
    im.save(base + ".contact.jpg", quality=88)
except ImportError:
    run(["ffmpeg", "-y", "-hide_banner", "-framerate", "1", "-i", os.path.join(sheet, "%02d.png"), "-vf", "tile=4x5", "-frames:v", "1", base + ".contact.jpg"])
if not keep:
    shutil.rmtree(work, ignore_errors=True)
print(f"wrote {out} ({total:.2f}s), {base}.srt, {base}.edl.json, {base}.contact.jpg")
PY
