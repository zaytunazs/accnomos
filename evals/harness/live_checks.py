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
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from harness.crop_bench import GOLD_DIR, make_scene

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
            "headers": {k: v for k, v in headers.items() if k.lower() != "x-demo-session"},
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


def _proposal_keep(b: dict[str, Any]) -> dict[str, Any]:
    ex = b.get("extracted") or {}
    return {x: b.get(x) for x in ("status", "model", "crop", "served_by")} | {
        "extracted": {y: ex.get(y) for y in ("supplier_name", "date", "gross_total")}
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="https://api.accnomos.com")
    ap.add_argument("--wav", action="append", default=[])
    ap.add_argument("--out", default="runs/live_checks")
    ap.add_argument("--scan-wait", type=float, default=240.0)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    k = Checker(args.api)

    r = k.step(
        "demo session",
        "POST",
        "/demo/session?kind=company",
        keep=lambda b: {x: b.get(x) for x in ("kind", "business", "today")},
    )
    k.h = {"X-Demo-Session": r.json()["session"]}
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
    gold = sorted(GOLD_DIR.glob("*.json"))[20]
    png, _truth = make_scene(json.loads(gold.read_text(encoding="utf-8"))["printed_text"], "dark_desk_mug", seed=4242)
    name = f"live-check-{gold.stem}.png"
    k.step(
        "upload a receipt photo to the demo inbox",
        "PUT",
        f"/demo/graph/v1.0/me/drive/special/approot:/00 Inbox/{name}:/content",
        keep=lambda b: {"name": b.get("name")},
        content=png,
        headers={"Content-Type": "image/png"},
    )
    r = k.step("start scan job", "POST", "/books/scan/jobs", keep=lambda b: {"id": b.get("id")}, json={"names": [name]})
    job: dict[str, Any] = {}
    if r.status_code < 400:
        jid = r.json()["id"]
        before = k.calls()
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < args.scan_wait:
            job = k.c.get(f"{k.api}/books/scan/jobs/{jid}", headers=k.h).json()
            if job.get("status") != "working":
                break
            time.sleep(3)
        k.out.append(
            {
                "check": "scan job result",
                "request": f"GET /books/scan/jobs/{{id}} (polled until not working, max {args.scan_wait:.0f} s)",
                "status": 200,
                "s": round(time.perf_counter() - t0, 2),
                "result": {"status": job.get("status"), "files": job.get("files"), "counts": job.get("counts")},
                "ai_calls": _new_calls(before, k.calls()),
            }
        )
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
    (out / "checks.json").write_text(
        json.dumps({"api": k.api, "at": datetime.now(UTC).isoformat(timespec="seconds"), "checks": k.out}, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
