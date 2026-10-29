"""Speech-to-text eval: Muse Voice Transcribe and Whisper on the Spark over the same recordings, side by side.

    cd evals && python -m harness.stt --dry-run          # list the samples and which providers are configured
    cd evals && python -m harness.stt --stub             # the whole pipeline against in-process fakes (no network)
    cd evals && python -m harness.stt                    # both providers, as configured in the environment
    cd evals && python -m harness.stt --generate         # first make any missing accounting clips with Kokoro TTS
    cd evals && python -m harness.stt --providers whisper --limit 5

The code under test is the product's own clients: ``app.ai.stt`` (``whisper_transcribe`` and, through it,
``app.ai.voice.transcribe`` for Muse with the documented request), each provider called on its own (no fallback), after
the same ffmpeg conversion to WAV mono 16 kHz the runtime does (``app.ai.voice.to_wav``; skipped when ffmpeg is
missing, the WAV is then sent as it is).

Providers come from the same environment the runtime reads: ``META_API_KEY`` (+ ``MODEL_API_BASE``) for Muse Voice
Transcribe, ``SPARK_WHISPER_URL`` (+ ``SPARK_WHISPER_MODEL``, ``SPARK_WHISPER_KEY``) for Whisper. One without its
settings is skipped and named in the summary. Keys are never written to the results or the log.

Samples
-------
* ``tools/teaser/vo/*.wav``: the teaser voice-over (Kokoro TTS, voice bm_george, 24 kHz); text in ``vo/lines.json``.
* ``evals/gold/voice/*.wav``: 20 short UK-English accounting requests (``UTTERANCES`` below, ``manifest.json``), made by
  ``--generate`` with Kokoro on the Spark. Synthetic speech is easier than a real phone in a van: treat the numbers as
  an upper bound.

Scoring, per clip and provider
------------------------------
* ``wer``: word error rate (substitutions + deletions + insertions over reference words) after ``normalise``:
  lower case, punctuation dropped, "£450" -> "450 pounds", spelled-out numbers -> digits ("two" -> "2",
  "four hundred and fifty" -> "450"), so "2 hours" and "two hours" are the same words.
* ``numbers_ok``: every number in the reference (amounts, hours, sizes, dates' day numbers) appears in the transcript,
  as a multiset; ``amounts_ok``: the same for the pound amounts only (clips with no amount are not counted).
* ``latency_s``: wall time of the one request (conversion not included).

Summary per provider: mean and median WER, corpus WER, number accuracy, amount accuracy, latency mean / p50 / p95,
failures. Writes ``evals/runs/stt/{results.jsonl, summary.json, report.md}``. One request at a time.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "services" / "runtime", REPO / "packages" / "ledger" / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import httpx  # noqa: E402

from app.ai import stt as stt_mod  # noqa: E402
from app.ai import voice as voice_mod  # noqa: E402

TEASER = REPO / "tools" / "teaser" / "vo"
VOICE_GOLD = REPO / "evals" / "gold" / "voice"
OUT = REPO / "evals" / "runs" / "stt"

#: 20 short UK-English requests a sole trader or a small firm would say to Accnomos. Fictional names and jobs.
UTTERANCES: list[str] = [
    "Andy did 2 hours overtime at double time on the Hendon job.",
    "Remember to order 2-inch bolts for the Hendon job.",
    "Quote Harbour Cafe £450 for a boiler service.",
    "Send a £1,250 invoice to JM Trading for the kitchen refit.",
    "How much VAT do I owe for the quarter ending 30 September?",
    "Log 38 miles from Croydon to the Mill Lane job.",
    "Chase invoice INV-0042 from Acme Kitchens.",
    "Pay Priya time and a half for last week's overtime.",
    "Add 6 rolls of packing tape to my shopping list.",
    "What did I spend on fuel in August?",
    "Who owes me more than £500?",
    "Turn quote Q-0017 into an invoice.",
    "Book 7 and a half hours for Tom on the Ealing loft conversion.",
    "Remind me to pay the £89.99 phone bill on the 3rd of November.",
    "How much did Boltmart charge me for screws this year?",
    "Send a £75 invoice to Mrs Okafor for fitting a new tap.",
    "Plan my Thursday around the jobs in Hendon and Barnet.",
    "Order 12 lengths of 22 millimetre copper pipe for the Bromley bathroom.",
    "What is my profit for the tax year so far?",
    "Record a £320 cash payment from Greenway Lettings for invoice 58.",
]
KOKORO_VOICES = ("bm_george", "bf_emma")  # British English voices in Kokoro-82M

# --------------------------------------------------------------------------- #
# Normalising and scoring
# --------------------------------------------------------------------------- #

_UNIT_WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen"
)
_UNITS = {w: i for i, w in enumerate(_UNIT_WORDS.split())}
_TENS = {
    w: 10 * (i + 2)
    for i, w in enumerate(["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"])
}
_SCALES = {"hundred": 100, "thousand": 1000}
_ORDINALS = {"first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5", "1st": "1", "2nd": "2"}
_ORDINALS |= {"3rd": "3", "4th": "4", "5th": "5"}


def _words_to_digits(tokens: list[str]) -> list[str]:
    """'four hundred and fifty' -> '450'; 'twenty two' -> '22'; 'a half' stays words. Digits pass through."""
    out: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t not in _UNITS and t not in _TENS:
            out.append(_ORDINALS.get(t, t))
            i += 1
            continue
        total, current = 0, 0
        while i < len(tokens):
            t = tokens[i]
            if t in _UNITS:
                current += _UNITS[t]
            elif t in _TENS:
                current += _TENS[t]
            elif t in _SCALES and (current or total):
                if t == "hundred":
                    current = max(current, 1) * 100
                else:
                    total, current = (total + current) * 1000, 0
            elif (
                t == "and"
                and i + 1 < len(tokens)
                and (tokens[i + 1] in _UNITS or tokens[i + 1] in _TENS)
                and (current >= 100 or total)
            ):
                pass  # "four hundred and fifty"
            else:
                break
            i += 1
        out.append(str(total + current))
    return out


def normalise(text: str) -> list[str]:
    t = text.lower().replace("£", " £").replace("-", " ")
    t = re.sub(r"£\s*([\d,]+(?:\.\d+)?)", lambda m: f"{m[1]} pounds", t)
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)  # 1,250 -> 1250
    t = re.sub(r"(\d)\.(\d)", r"\1<dot>\2", t)  # keep decimal points through the punctuation strip
    t = re.sub(r"[^\w\s<>]", " ", t).replace("<dot>", ".")
    t = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", t)
    toks = _words_to_digits(t.split())
    return [w for w in toks if w]


def wer_counts(ref: list[str], hyp: list[str]) -> tuple[int, int]:
    """(edit distance, reference length) at word level."""
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1], len(ref)


def _is_number(w: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?", w))


def numbers(words: list[str]) -> Counter[str]:
    return Counter(w for w in words if _is_number(w))


def amounts(words: list[str]) -> Counter[str]:
    return Counter(w for w, nxt in zip(words, [*words[1:], ""], strict=True) if _is_number(w) and nxt == "pounds")


def contains(have: Counter[str], want: Counter[str]) -> bool:
    return all(have[k] >= n for k, n in want.items())


def score(reference: str, transcript: str) -> dict[str, Any]:
    ref, hyp = normalise(reference), normalise(transcript)
    edits, n = wer_counts(ref, hyp)
    want_amounts = amounts(ref)
    return {
        "edits": edits,
        "ref_words": n,
        "wer": round(edits / n, 4) if n else 0.0,
        "numbers_ok": contains(numbers(hyp), numbers(ref)) if numbers(ref) else None,
        "amounts_ok": contains(amounts(hyp), want_amounts) if want_amounts else None,
    }


# --------------------------------------------------------------------------- #
# Samples
# --------------------------------------------------------------------------- #


@dataclass
class Sample:
    id: str
    path: Path
    text: str
    source: str  # teaser | gold


def load_samples() -> list[Sample]:
    out: list[Sample] = []
    lines = TEASER / "lines.json"
    if lines.exists():
        for row in json.loads(lines.read_text(encoding="utf-8")):
            p = TEASER / row["file"]
            if p.exists():
                out.append(Sample(f"teaser/{p.stem}", p, row["text"], "teaser"))
    manifest = VOICE_GOLD / "manifest.json"
    if manifest.exists():
        for row in json.loads(manifest.read_text(encoding="utf-8")):
            p = VOICE_GOLD / row["file"]
            if p.exists():
                out.append(Sample(f"gold/{p.stem}", p, row["text"], "gold"))
    return out


async def generate(kokoro: str, *, force: bool = False, client: httpx.AsyncClient | None = None) -> int:
    """Make evals/gold/voice/vNN.wav for each utterance with Kokoro's OpenAI-compatible `POST {kokoro}/audio/speech`
    (Kokoro-FastAPI: model "kokoro", a voice, response_format "wav"). Voices alternate between a British man and woman.
    Returns how many clips were written; an unreachable Kokoro writes none and says so."""
    VOICE_GOLD.mkdir(parents=True, exist_ok=True)
    rows, made = [], 0
    own = client is None
    http = client or httpx.AsyncClient(timeout=120)
    try:
        for i, text in enumerate(UTTERANCES, 1):
            name, v = f"v{i:02d}.wav", KOKORO_VOICES[i % 2]
            rows.append({"file": name, "voice": v, "text": text})
            target = VOICE_GOLD / name
            if target.exists() and not force:
                continue
            try:
                r = await http.post(
                    f"{kokoro.rstrip('/')}/audio/speech",
                    json={"model": "kokoro", "input": text, "voice": v, "response_format": "wav", "speed": 1.0},
                )
            except httpx.HTTPError as exc:
                print(f"Kokoro at {kokoro} could not be reached ({type(exc).__name__}); no clips made", file=sys.stderr)
                return made
            if r.status_code != 200 or not r.content.startswith(b"RIFF"):
                print(f"Kokoro returned HTTP {r.status_code} for {name}; skipped", file=sys.stderr)
                continue
            target.write_bytes(r.content)
            made += 1
    finally:
        if own:
            await http.aclose()
    (VOICE_GOLD / "manifest.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return made


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #


def providers_from_env(wanted: list[str], env: dict[str, str] | None = None) -> tuple[list[Any], list[str]]:
    """(configured providers among `wanted`, the names left out). Each runs alone: no fallback in an eval."""
    env = dict(os.environ if env is None else env)
    env["STT_PROVIDERS"] = ",".join(wanted)
    env.pop("ACCNOMOS_TEST_MODE", None)
    got = stt_mod.chain(None, env)
    names = {p.name for p in got}
    return got, [n for n in wanted if n not in names]


async def _wav(sample: Sample) -> bytes:
    raw = sample.path.read_bytes()
    if voice_mod.ffmpeg_path() is None:
        return raw
    return await voice_mod.to_wav(raw, "audio/wav", sample.path.name)


async def run(
    samples: list[Sample],
    providers: list[Any],
    *,
    client: httpx.AsyncClient | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for s in samples:
        wav = await _wav(s)
        for p in providers:
            t0 = clock()
            try:
                heard = await stt_mod.transcribe(wav, [p], client=client)
                text, error = heard.text, None
            except voice_mod.VoiceError as exc:
                text, error = "", f"{exc.status}: {exc}"
            row = {"id": s.id, "source": s.source, "provider": p.name, "model": p.model, "reference": s.text}
            row |= {"transcript": text, "error": error, "latency_s": round(clock() - t0, 3)}
            row |= score(s.text, text) if error is None else {"wer": None, "numbers_ok": None, "amounts_ok": None}
            rows.append(row)
            print(f"{s.id} {p.name}: {'ERR ' + error if error else 'wer=' + str(row['wer'])}", flush=True)
    return rows


def _pct(xs: list[bool]) -> float | None:
    return round(100 * sum(xs) / len(xs), 1) if xs else None


def summarise(rows: list[dict[str, Any]], skipped: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "skipped": skipped, "providers": {}}
    for name in dict.fromkeys(r["provider"] for r in rows):
        mine = [r for r in rows if r["provider"] == name]
        ok = [r for r in mine if r["error"] is None]
        lat = sorted(r["latency_s"] for r in ok)
        edits, words = sum(r["edits"] for r in ok), sum(r["ref_words"] for r in ok)
        out["providers"][name] = {
            "model": mine[0]["model"],
            "clips": len(mine),
            "failures": len(mine) - len(ok),
            "corpus_wer": round(edits / words, 4) if words else None,
            "mean_wer": round(statistics.fmean(r["wer"] for r in ok), 4) if ok else None,
            "median_wer": round(statistics.median(r["wer"] for r in ok), 4) if ok else None,
            "numbers_accuracy_pct": _pct([r["numbers_ok"] for r in ok if r["numbers_ok"] is not None]),
            "amounts_accuracy_pct": _pct([r["amounts_ok"] for r in ok if r["amounts_ok"] is not None]),
            "latency_mean_s": round(statistics.fmean(lat), 3) if lat else None,
            "latency_p50_s": lat[len(lat) // 2] if lat else None,
            "latency_p95_s": lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else None,
        }
    return out


def _show(x: float | None, unit: str = "") -> str:
    return "n/a" if x is None else f"{x}{unit}"


def report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        f"# Speech-to-text eval ({summary['at']})",
        "",
        "| Provider | Model | Clips | Failures | Corpus WER | Mean WER | Numbers right | Amounts right "
        "| Latency mean / p50 / p95 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, s in summary["providers"].items():
        lines.append(
            f"| {stt_mod.LABELS.get(name, name)} | `{s['model']}` | {s['clips']} | {s['failures']} "
            f"| {_show(s['corpus_wer'])} | {_show(s['mean_wer'])} | {_show(s['numbers_accuracy_pct'], ' %')} "
            f"| {_show(s['amounts_accuracy_pct'], ' %')} "
            f"| {_show(s['latency_mean_s'])} / {_show(s['latency_p50_s'])} / {_show(s['latency_p95_s'])} s |"
        )
    if summary["skipped"]:
        lines += ["", f"Not configured, so not run: {', '.join(summary['skipped'])}."]
    misses = [r for r in rows if r["error"] or r["numbers_ok"] is False]
    if misses:
        lines += ["", "## Number misses and failures", ""]
        for r in misses:
            got = r["error"] or repr(r["transcript"])
            lines.append(f"- `{r['id']}` {r['provider']}: {got} (said: {r['reference']!r})")
    lines += [
        "",
        "Synthetic Kokoro speech, one clean voice per clip: real phone audio will score worse. See harness/stt.py.",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Stub: the documented response shapes, served in-process
# --------------------------------------------------------------------------- #


async def stub_client(samples: list[Sample]) -> httpx.AsyncClient:
    """Muse 'hears' every clip perfectly; Whisper drops the pound sign and spells "2 hours" out (so its WER is above 0
    on those clips while the numbers still count as right). Each clip is recognised by its WAV bytes in the upload."""
    heard = [(await _wav(s), s.text) for s in samples]

    def handler(req: httpx.Request) -> httpx.Response:
        body = req.read()
        text = next((t for wav, t in heard if wav in body), "")
        if req.url.path.endswith("/asr/transcribe"):
            return httpx.Response(200, json={"sessionId": "stub", "transcript": text, "audioDurationMs": 1000})
        return httpx.Response(200, json={"text": text.replace("£", "").replace("2 hours", "two hours")})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


STUB_ENV = {
    "META_API_KEY": "stub-key",
    "MODEL_API_BASE": "http://muse.stub/v1",
    "SPARK_WHISPER_URL": "http://w.stub/v1",
}


# --------------------------------------------------------------------------- #


async def main_async(args: argparse.Namespace) -> int:
    if args.generate and not args.dry_run:
        made = await generate(args.kokoro)
        print(f"Kokoro: {made} new clip(s) in {VOICE_GOLD.relative_to(REPO)}")
    samples = load_samples()
    if args.only_source:
        samples = [s for s in samples if s.source == args.only_source]
    if args.limit:
        samples = samples[: args.limit]
    wanted = [n.strip() for n in args.providers.split(",") if n.strip()]
    providers, skipped = providers_from_env(wanted, STUB_ENV if args.stub else None)
    print(f"{len(samples)} sample(s); providers: {[p.name for p in providers] or 'none'}; not configured: {skipped}")
    if args.dry_run:
        for s in samples:
            print(f"  {s.id}: {s.text}")
        return 0
    if not samples or not providers:
        print("nothing to run: no samples, or no provider set (META_API_KEY, SPARK_WHISPER_URL)", file=sys.stderr)
        return 2
    client = await stub_client(samples) if args.stub else None
    try:
        rows = await run(samples, providers, client=client)
    finally:
        if client is not None:
            await client.aclose()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = summarise(rows, skipped)
    (out / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out / "report.md").write_text(report(summary, rows), encoding="utf-8")
    print(json.dumps(summary["providers"], indent=2))
    return 0 if all(s["failures"] < s["clips"] for s in summary["providers"].values()) else 1


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--providers", default="muse,whisper", help="comma separated: muse, whisper")
    ap.add_argument("--dry-run", action="store_true", help="list samples and providers; call nothing")
    ap.add_argument("--stub", action="store_true", help="fake both providers in-process (no network)")
    ap.add_argument("--generate", action="store_true", help="make missing gold/voice clips with Kokoro first")
    ap.add_argument("--kokoro", default=os.getenv("KOKORO_URL", "http://127.0.0.1:8880/v1"), help="Kokoro base URL")
    ap.add_argument("--only-source", choices=("teaser", "gold"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=str(OUT))
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(parse(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
