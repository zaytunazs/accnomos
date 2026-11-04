"""Live checks of the Meta paths against a running Accnomos API, in a demo session (no sign-in, sample books).

    cd evals && python -m harness.live_checks --api https://api.accnomos.com --wav q1.wav --wav q2.wav \\
        --out runs/live_checks_2026-11-04

Each check records the HTTP status, wall time and what the server says served it, and GET /ai/calls (the runtime's
last 50 AI calls: task, provider, model, latency, fallbacks) is read after each step so the report can show which
model answered. The WAVs are synthetic test input (text to speech), not a person speaking. Nothing here holds or
prints a key: the server uses its own. Writes checks.json in --out.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "services" / "runtime", REPO / "packages" / "ledger" / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from app.paths import INBOX  # noqa: E402
from harness.crop_bench import GOLD_DIR, make_scene  # noqa: E402

QUESTIONS = ("How much did we spend on fuel this year?", "What is our VAT bill for this quarter?")


def _new_calls(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {json.dumps(c, sort_keys=True) for c in before}
    return [c for c in after if json.dumps(c, sort_keys=True) not in seen]


class Checker:
    def __init__(self, api: str) -> None:
        self.api = api.rstrip("/")
        self.c = httpx.Client(timeout=httpx.Timeout(240.0, connect=20.0))
        self.h: dict[str, str] = {}
        self.out: list[dict[str, Any]] = []

    def calls(self) -> list[dict[str, Any]]:
        r = self.c.get(f"{self.api}/ai/calls")
        return r.json() if r.status_code == 200 else []

    def step(self, name: str, method: str, path: str, keep: Any = None, **kw: Any) -> httpx.Response:
        before = self.calls()
        headers = {**self.h, **kw.pop("headers", {})}
        t0 = time.perf_counter()
        r = self.c.request(method, f"{self.api}{path}", headers=headers, **kw)
        rec: dict[str, Any] = {
            "check": name,
            "request": f"{method} {path}",
            "headers": {k: v for k, v in headers.items() if k.lower() not in ("x-demo-session", "x-user")},
            "status": r.status_code,
            "s": round(time.perf_counter() - t0, 2),
        }
        try:
            body = r.json()
        except ValueError:
            body = r.text[:300]
        rec["result"] = keep(body) if keep and r.status_code < 400 else (body if r.status_code >= 400 else None)
        rec["ai_calls"] = _new_calls(before, self.calls())
        self.out.append(rec)
        print(json.dumps({k: rec[k] for k in ("check", "status", "s")}), flush=True)
        return r


def _ask_keep(b: dict[str, Any]) -> dict[str, Any]:
    keys = ("answer_md", "answer", "model", "served_by", "transcript", "transcribed_by", "fallback_reason", "checked")
    return {k: b[k] for k in keys if k in b} | {"keys": sorted(b)}


def _poll(k: Checker, jid: str, wait: float, label: str) -> dict[str, Any]:
    before = k.calls()
    t0 = time.perf_counter()
    job: dict[str, Any] = {}
    while time.perf_counter() - t0 < wait:
        job = k.c.get(f"{k.api}/books/scan/jobs/{jid}", headers=k.h).json()
        if job.get("status") != "working":
            break
        time.sleep(3)
    k.out.append(
        {
            "check": label,
            "request": f"GET /books/scan/jobs/{{id}} (polled until not working, max {wait:.0f} s)",
            "status": 200,
            "s": round(time.perf_counter() - t0, 2),
            "result": {"status": job.get("status"), "files": job.get("files"), "counts": job.get("counts")},
            "ai_calls": _new_calls(before, k.calls()),
        }
    )
    print(json.dumps({"check": label, "status": job.get("status")}), flush=True)
    return job


def _proposal_keep(b: dict[str, Any]) -> dict[str, Any]:
    ex = b.get("extracted") or {}
    return {x: b.get(x) for x in ("status", "model", "crop", "served_by")} | {
        "extracted": {y: ex.get(y) for y in ("supplier_name", "date", "gross_total")}
    }


NOTES = """
**The spoken questions are synthetic speech** (text to speech on our own server, mono WAV, about 3 s each), used only
as test input. Separately, the owner used spoken questions from the Android app on his own phone on 4 Nov 2026; that
use is not recorded here.

What this shows and does not show:

- Each step's "Served by" is what the runtime's own call log (`GET /ai/calls`) recorded for that step. With
  `X-AI-Route: local_first` and `local_only` a call served by `spark` is Muse Glimmer 30B on our own server.
- The answers were not scored against an answer key; every figure an answer quotes is checked by code against the
  books (the KnownNumbers check). Reading accuracy is measured separately on 200 synthetic documents:
  `evals/runs/spark13_200` and `evals/runs/spark13_messy_200`; the word-error figure for transcription is in
  `evals/runs/stt`. A few live calls are not a measurement.
- The scanned photo is a synthetic scene (a gold receipt on a cluttered desk, `harness.crop_bench.make_scene`); its
  reading is compared with that gold document below.
"""


def _call(x: dict[str, Any]) -> str:
    fb = f" (fell back from {', '.join(x['fell_back_from'])})" if x.get("fell_back_from") else ""
    return f"{x['task']}: {x['provider']} `{x['model']}`{fb}{'' if x['ok'] else ' FAILED'}"


def _served(c: dict[str, Any]) -> str:
    calls = c.get("ai_calls") or []
    if not calls:
        heard = (c.get("result") or {}).get("transcribed_by") if isinstance(c.get("result"), dict) else None
        return f"{heard['label']} (`{heard['model']}`)" if heard else "no AI call"
    out = [_call(x) for x in calls]
    res = c.get("result")
    heard = res.get("transcribed_by") if isinstance(res, dict) else None
    if isinstance(heard, dict):
        out.insert(0, f"transcribed by {heard['label']} (`{heard['model']}`)")
    return "; ".join(out)


def _what(c: dict[str, Any]) -> str:
    r = c.get("result")
    if not isinstance(r, dict):
        return str(r)[:160] if r else ""
    if "transcript" in r and "answer_md" not in r:
        return f"heard: “{r['transcript']}”"
    if "answer_md" in r:
        t = f"heard: “{r['transcript']}”; " if r.get("transcript") else ""
        return t + f"answer: “{r['answer_md']}”"
    if "summary" in r:
        return f"summary: “{(r['summary'] or {}).get('summary_md')}” (by {(r['summary'] or {}).get('model')})"
    if "note" in r:
        n = r.get("note") or {}
        return f"{r.get('goals')} goals; note: “{n.get('note_md')}” (by {n.get('model')})"
    if "files" in r:
        f = (r.get("files") or [{}])[0]
        g = f.get("guess") or {}
        return f"job {r.get('status')}; file stage {f.get('stage_label')}; type guessed {g.get('kind')} ({g.get('confidence')}, by {g.get('by')})"  # noqa: E501
    if "extracted" in r:
        e = r["extracted"]
        crop = r.get("crop") or {}
        return (
            f"status {r.get('status')}; read {e.get('supplier_name')}, {e.get('date')}, gross {e.get('gross_total')}; "
            f"crop: {crop.get('note')}"
        )
    if "providers" in r:
        return "; ".join(f"{p['name']} `{p['model']}` {p['status']}" for p in r["providers"])
    return ", ".join(f"{k}={v}" for k, v in r.items())[:200]


def write_report(data: dict[str, Any], out: Path, gold: dict[str, Any] | None = None) -> None:
    rows = [
        "| # | Check | Request | HTTP | Result | Served by (`/ai/calls`) | Time |",
        "|---|---|---|---:|---|---|---:|",
    ]
    for i, c in enumerate(data["checks"], 1):
        cell = _what(c).replace("|", "\\|").replace("\n", " ")
        rows.append(f"| {i} | {c['check']} | `{c['request']}` | {c['status']} | {cell} | {_served(c)} | {c['s']} s |")
    calls = [x for c in data["checks"] for x in c.get("ai_calls") or []]
    meta = sum(x["provider"] == "meta" for x in calls)
    fell = sum(bool(x.get("fell_back_from")) for x in calls)
    failed = sum(not x["ok"] for x in calls)
    stt = sum(
        1
        for c in data["checks"]
        if isinstance(c.get("result"), dict) and (c["result"].get("transcribed_by") or {}).get("provider") == "muse"
    )
    g = ""
    if gold:
        g = (
            f"\nGold for the scanned photo (`{gold['file']}`): supplier {gold['supplier']}, date {gold['date']}, gross "
            f"{gold['gross']}, expected status {gold['status']}.\n"
        )
    text = (
        f"# Live checks of the Meta paths\n\nRun at {data['at']} against `{data['api']}` in a company demo session "
        "(`POST /demo/session?kind=company`, the fictional Bramblewood Joinery Ltd sample books). Script: "
        "`evals/harness/live_checks.py`; raw results with every step's `/ai/calls` records: `checks.json`. The script "
        "holds no key: the server uses its own.\n\n"
        + "\n".join(rows)
        + f"\n\nAI calls logged: {len(calls)} ({meta} to the Meta Model API), {fell} fell back, {failed} failed; "
        f"{stt} transcriptions by Muse Voice Transcribe.\n" + g + NOTES
    )
    (out / "report.md").write_text(text, encoding="utf-8")


def _gold_facts(path: Path) -> dict[str, Any]:
    from harness.run_extraction import expected_status

    gd = json.loads(path.read_text(encoding="utf-8"))
    return {
        "file": path.name,
        "supplier": gd["supplier"]["name"],
        "date": gd["date"],
        "gross": gd["gross_total"],
        "status": expected_status(gd),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="https://api.accnomos.com")
    ap.add_argument("--wav", action="append", default=[])
    ap.add_argument("--out", default="runs/live_checks")
    ap.add_argument("--scan-wait", type=float, default=240.0)
    ap.add_argument("--report-only", action="store_true", help="rewrite report.md from checks.json, no requests")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    gold_path = sorted(GOLD_DIR.glob("*.json"))[20]
    if args.report_only:
        write_report(json.loads((out / "checks.json").read_text(encoding="utf-8")), out, _gold_facts(gold_path))
        return
    k = Checker(args.api)

    r = k.step(
        "demo session",
        "POST",
        "/demo/session?kind=company",
        keep=lambda b: {x: b.get(x) for x in ("kind", "business", "today")},
    )
    sess = r.json()
    k.h = {"X-Demo-Session": sess["session"], "X-User": sess.get("user") or "demo"}  # X-User: the sandbox's own user
    k.step("ai health", "GET", "/ai/health", keep=lambda b: b)

    for i, wav in enumerate(args.wav):
        data = Path(wav).read_bytes()
        q = QUESTIONS[i] if i < len(QUESTIONS) else Path(wav).stem
        k.step(
            f"transcribe ({q!r}, synthetic speech)",
            "POST",
            "/books/ask/transcribe",
            keep=lambda b: b,
            files={"audio": (Path(wav).name, data, "audio/wav")},
        )
        k.step(
            f"ask by voice ({q!r}, synthetic speech)",
            "POST",
            "/books/ask/voice",
            keep=_ask_keep,
            files={"audio": (Path(wav).name, data, "audio/wav")},
        )

    for route in ("meta_first", "local_first", "local_only"):
        k.step(
            f"ask, route {route}",
            "POST",
            "/books/ask",
            keep=_ask_keep,
            json={"question": "What were our total sales last month?"},
            headers={"X-AI-Route": route},
        )

    # A cluttered phone-photo style scene of a gold receipt, uploaded to the demo inbox, then scanned
    gold = gold_path
    png, _truth = make_scene(json.loads(gold.read_text(encoding="utf-8"))["printed_text"], "dark_desk_mug", seed=4242)
    name = f"live-check-{gold.stem}.png"
    k.step(
        "upload a receipt photo to the demo inbox",
        "PUT",
        f"/demo/graph/v1.0/me/drive/special/approot:/{INBOX}/{name}:/content",
        keep=lambda b: {"name": b.get("name")},
        content=png,
        headers={"Content-Type": "image/png"},
    )
    r = k.step("start scan job", "POST", "/books/scan/jobs", keep=lambda b: {"id": b.get("id")}, json={"names": [name]})
    job: dict[str, Any] = {}
    if r.status_code < 400:
        jid = r.json()["id"]
        job = _poll(k, jid, args.scan_wait, "scan job: classify")
        guess = next((f.get("guess") for f in job.get("files") or [] if f.get("stage") == "confirm"), None)
        if guess:  # the owner's tap on "Confirm the type", with the type the AI guessed
            k.step(
                "confirm the type (as guessed)",
                "POST",
                f"/books/scan/jobs/{jid}/confirm",
                keep=lambda b: {"status": b.get("status")},
                json={"files": [{"name": name, "kind": guess["kind"]}]},
            )
            job = _poll(k, jid, args.scan_wait, "scan job: read")
        pid = next((f.get("proposal_id") for f in job.get("files") or [] if f.get("proposal_id")), None)
        if pid:
            k.step(
                "the proposal the scan made",
                "GET",
                f"/books/proposals/{pid}",
                keep=_proposal_keep,
            )

    k.step(
        "home summary",
        "GET",
        "/books/home",
        keep=lambda b: {
            "summary": {x: (b.get("summary") or {}).get(x) for x in ("summary_md", "model", "fallback_reason")}
        },  # noqa: E501
    )
    k.step(
        "goals note",
        "GET",
        "/books/goals",
        keep=lambda b: {"goals": len(b.get("goals") or []), "note": b.get("note")},
    )
    data = {"api": k.api, "at": datetime.now(UTC).isoformat(timespec="seconds"), "checks": k.out}
    (out / "checks.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    write_report(data, out, _gold_facts(gold_path))


if __name__ == "__main__":
    main()
