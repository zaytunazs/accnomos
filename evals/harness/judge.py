"""Claude-as-judge for an extraction run (H19: grading only, never in the runtime path).

    cd evals && python -m harness.judge runs/20261027-120000 [--model claude-haiku-5-5]
        [--escalate claude-sonnet-5-5] [--limit N]

Reads ~/.anthropic_key and, if present, ~/.anthropic_workspace (sent as the
`anthropic-workspace-id` header, required for identity-linked keys). Talks to the
Messages API with httpx, so no SDK is needed. Writes <run>/judge.json.

Escalation: when the code comparison and the first judge disagree (code says all
fields right but judge finds errors, or vice versa), the doc is re-judged with the
escalation model and that verdict is final.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

API_URL = "https://api.anthropic.com/v1/messages"
#: Reply cap. The models think before answering and the thinking counts towards it: at 800, 27 of 200
#: replies ran out before the JSON started (stop_reason "max_tokens").
MAX_TOKENS = 4000
REPO = Path(__file__).resolve().parents[2]
GOLD_DIR = REPO / "evals" / "gold" / "receipts"

SYSTEM = (
    "You grade a UK receipt-extraction system for a bookkeeping app. You get the GOLD record "
    "(ground truth, including the receipt text as printed) and the EXTRACTED record. List every "
    "field where EXTRACTED is wrong in a way a bookkeeper would care about (supplier, VAT number, "
    "date, totals, VAT per line, line items, doc type, payment method, category if clearly wrong). "
    "Ignore case, spacing and harmless wording differences. Arithmetic errors that are printed on "
    "the receipt should be copied, not corrected. severity: none (no errors), minor (cosmetic or "
    "category only), major (anything that changes the books or VAT return). Reply with JSON only: "
    '{"field_errors":[{"field":str,"gold":str,"extracted":str}],"severity":"none|minor|major","note":str}'
)

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def _read_secret(name: str) -> str | None:
    p = Path.home() / name
    return p.read_text(encoding="utf-8").strip() or None if p.exists() else None


def _headers() -> dict[str, str]:
    key = _read_secret(".anthropic_key")
    if not key:
        raise SystemExit("~/.anthropic_key is missing or empty")
    h = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    if ws := _read_secret(".anthropic_workspace"):
        h["anthropic-workspace-id"] = ws
    return h


def _parse(text: str) -> dict[str, Any]:
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        s, e = cleaned.find("{"), cleaned.rfind("}")
        if s >= 0 and e > s:
            return json.loads(cleaned[s : e + 1])
        raise


def judge_one(client: httpx.Client, model: str, gold: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any]:
    gold_view = {k: v for k, v in gold.items() if k not in ("label", "notes")}
    body = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "messages": [
            {
                "role": "user",
                "content": "GOLD:\n"
                + json.dumps(gold_view, ensure_ascii=False)
                + "\n\nEXTRACTED:\n"
                + json.dumps(extracted, ensure_ascii=False),
            }
        ],
    }
    for attempt in range(4):
        r = client.post(API_URL, json=body)
        if r.status_code in (429, 500, 502, 503, 529) and attempt < 3:
            time.sleep(float(r.headers.get("retry-after", 2 ** (attempt + 1))))
            continue
        r.raise_for_status()
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        try:
            verdict = _parse(text)
        except json.JSONDecodeError:
            verdict = {"field_errors": [], "severity": "unparsed", "note": text[:500]}
        verdict["model"] = model
        verdict["stop_reason"] = data.get("stop_reason")
        verdict["usage"] = data.get("usage", {})
        return verdict
    raise RuntimeError("unreachable")


def _disagrees(code_ok: bool, verdict: dict[str, Any]) -> bool:
    judged_ok = verdict.get("severity") == "none"
    return code_ok != judged_ok or verdict.get("severity") == "unparsed"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--model", default="claude-haiku-5-5")
    ap.add_argument("--escalate", default=None, help="e.g. claude-sonnet-5-5")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    recs = sorted(p for p in args.run_dir.glob("*.json") if p.name not in ("summary.json", "judge.json"))
    recs = recs[: args.limit] if args.limit else recs
    docs: list[dict[str, Any]] = []
    with httpx.Client(headers=_headers(), timeout=120) as client:
        for path in recs:
            rec = json.loads(path.read_text(encoding="utf-8"))
            if rec.get("proposal") is None:
                docs.append({"file": rec["file"], "skipped": rec.get("error")})
                continue
            gold = json.loads((GOLD_DIR / rec["file"]).read_text(encoding="utf-8"))
            extracted = rec["proposal"]["extracted"]
            code_ok = all(v for k, v in rec["scores"].items() if k != "status")
            first = judge_one(client, args.model, gold, extracted)
            esc = None
            if args.escalate and _disagrees(code_ok, first):
                esc = judge_one(client, args.escalate, gold, extracted)
            final = esc or first
            docs.append(
                {
                    "file": rec["file"],
                    "gold_case": rec.get("gold_case"),
                    "code_ok": code_ok,
                    "first": first,
                    "escalated": esc,
                    "final_severity": final.get("severity"),
                }
            )
            print(
                f"{rec['file']}: code_ok={code_ok} {first.get('severity')}"
                + (f" -> {esc.get('severity')}" if esc else ""),
                flush=True,
            )

    judged = [d for d in docs if "final_severity" in d]
    summary = {
        "model": args.model,
        "escalate": args.escalate,
        "n": len(judged),
        "skipped": len(docs) - len(judged),
        "severity": dict(Counter(d["final_severity"] for d in judged)),
        "disagreements": sum(_disagrees(d["code_ok"], d["first"]) for d in judged),
        "escalated": sum(d["escalated"] is not None for d in judged),
    }
    (args.run_dir / "judge.json").write_text(
        json.dumps({"summary": summary, "docs": docs}, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
