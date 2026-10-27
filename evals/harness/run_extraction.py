"""Extraction eval: render each gold doc, run the real pipeline, score against gold.

    cd evals && python -m harness.run_extraction --mode local --limit 10 --messy
    (or from repo root: PYTHONPATH=evals python -m harness.run_extraction ...)

--verify runs the Verifier (app/ai/verify.py) on every reading that passed the checks, as the
runtime does, and reports agreement per field and whether agreement tracks correctness against
gold. Without it the verifier is switched off (VERIFIER=off) so extraction numbers stay comparable.

Writes <out>/NNN_case.json (+ .png), summary.json and report.md; prints the summary.
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "services" / "runtime", REPO / "packages" / "ledger" / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from app.ai.config import AiConfig  # noqa: E402
from app.ai.verify import parse_date, select_backend  # noqa: E402
from app.checks import normalise_vat_number  # noqa: E402
from app.pipeline import process_image  # noqa: E402

from harness.render import render_receipt  # noqa: E402

GOLD_DIR = REPO / "evals" / "gold" / "receipts"
FIELDS = ("supplier_name", "vat_number", "date", "net_total", "vat_total", "gross_total", "line_count", "status")
NEEDS_LOOK_CASES = {"arith_error", "no_vat_number"}


def expected_status(gold: dict[str, Any]) -> str:
    if gold.get("gold_case") in NEEDS_LOOK_CASES or gold.get("currency", "GBP") != "GBP":
        return "needs_a_look"
    return "proposed"


def _pence_eq(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return abs(round(a * 100) - round(b * 100)) <= 1


def _name_eq(a: str | None, b: str | None) -> bool:
    a, b = (a or "").lower().strip(), (b or "").lower().strip()
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def score(gold: dict[str, Any], proposal: dict[str, Any]) -> dict[str, bool]:
    ex = proposal["extracted"]
    return {
        "supplier_name": _name_eq(gold["supplier"]["name"], ex["supplier_name"]),
        "vat_number": normalise_vat_number(gold["supplier"].get("vat_number"))
        == normalise_vat_number(ex["supplier_vat_number"]),
        "date": gold["date"] == ex["date"],
        "net_total": _pence_eq(gold["net_total"], ex["net_total"]),
        "vat_total": _pence_eq(gold["vat_total"], ex["vat_total"]),
        "gross_total": _pence_eq(gold["gross_total"], ex["gross_total"]),
        "line_count": len(gold["lines"]) == len(ex["lines"]),
        "status": proposal["status"] == expected_status(gold),
    }


# Verifier field -> how to grade one reading of it against gold.
_GOLD_GRADERS = {
    "supplier_name": lambda g, v: _name_eq(g["supplier"]["name"], v),
    "supplier_vat_number": lambda g, v: normalise_vat_number(g["supplier"].get("vat_number")) == normalise_vat_number(v),
    "date": lambda g, v: (parse_date(v) or "") == parse_date(g["date"]),
    "net_total": lambda g, v: _pence_eq(g["net_total"], v),
    "vat_total": lambda g, v: _pence_eq(g["vat_total"], v),
    "gross_total": lambda g, v: _pence_eq(g["gross_total"], v),
}


def score_verification(gold: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any] | None:
    """Per field: did they agree, and was each reading right against gold?"""
    v = proposal.get("verification")
    if not v:
        return None
    if v.get("error"):
        return {"error": v["error"], "fields": {}}
    fields = {
        name: {
            "agree": f["agree"],
            "extractor_right": _GOLD_GRADERS[name](gold, f["extractor"]),
            "verifier_right": _GOLD_GRADERS[name](gold, f["verifier"]),
        }
        for name, f in v["fields"].items()
    }
    return {"error": None, "agree_all": v["agree_all"], "fields": fields}


async def run_one(path: Path, idx: int, cfg: AiConfig, messy: bool, out: Path) -> dict[str, Any]:
    gold = json.loads(path.read_text(encoding="utf-8"))
    png = render_receipt(gold["printed_text"], messy=messy, seed=idx)
    (out / f"{path.stem}.png").write_bytes(png)
    rec: dict[str, Any] = {
        "file": path.name,
        "gold_case": gold.get("gold_case"),
        "label": gold.get("label"),
        "expected_status": expected_status(gold),
    }
    t0 = time.perf_counter()
    try:
        proposal = (await process_image(png, "image/png", cfg)).model_dump(mode="json")
        rec |= {
            "proposal": proposal,
            "scores": score(gold, proposal),
            "verification": score_verification(gold, proposal),
            "error": None,
        }
    except Exception as exc:  # record and carry on; one bad doc must not stop the run
        rec |= {
            "proposal": None,
            "scores": {f: False for f in FIELDS},
            "verification": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    rec["elapsed_s"] = round(time.perf_counter() - t0, 3)
    (out / f"{path.stem}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
    return rec


def summarise(records: list[dict[str, Any]], cfg: AiConfig, messy: bool) -> dict[str, Any]:
    n = len(records)
    acc = {f: round(sum(r["scores"][f] for r in records) / n, 3) if n else 0.0 for f in FIELDS}
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_case[r["gold_case"] or "?"].append(r)
    cases = {
        c: {
            "n": len(rs),
            "all_fields": round(sum(all(r["scores"].values()) for r in rs) / len(rs), 3),
            "status": round(sum(r["scores"]["status"] for r in rs) / len(rs), 3),
            "errors": sum(r["error"] is not None for r in rs),
        }
        for c, rs in sorted(by_case.items())
    }
    times = [r["elapsed_s"] for r in records if r["error"] is None]
    return {
        "config": cfg.public(),
        "messy": messy,
        "n": n,
        "errors": sum(r["error"] is not None for r in records),
        "field_accuracy": acc,
        "all_fields_correct": round(sum(all(r["scores"].values()) for r in records) / n, 3) if n else 0.0,
        "by_case": cases,
        "mean_elapsed_s": round(statistics.mean(times), 2) if times else None,
        "max_elapsed_s": round(max(times), 2) if times else None,
    }


def _status_without_verifier(proposal: dict[str, Any]) -> str:
    fails = [c for c in proposal["checks"] if not c["ok"] and c["severity"] == "fail" and c["code"] != "VERIFIER_AGREES"]
    return "needs_a_look" if fails else "proposed"


def summarise_verification(records: list[dict[str, Any]], verifier: str) -> dict[str, Any]:
    """Agreement per field, and whether agreement means the Extractor was right (graded against gold)."""
    ok = [r for r in records if r["error"] is None]
    ran = [r for r in ok if r["verification"] and not r["verification"]["error"]]
    pct = lambda k, n: round(k / n, 3) if n else None  # noqa: E731
    per_field: dict[str, dict[str, Any]] = {}
    for name in _GOLD_GRADERS:
        fs = [r["verification"]["fields"][name] for r in ran]
        per_field[name] = {
            "agree": pct(sum(f["agree"] for f in fs), len(fs)),
            "extractor_right": pct(sum(f["extractor_right"] for f in fs), len(fs)),
            "verifier_right": pct(sum(f["verifier_right"] for f in fs), len(fs)),
            "agreed_but_both_wrong": sum(f["agree"] and not f["extractor_right"] for f in fs),
            "disagreed_extractor_wrong": sum(not f["agree"] and not f["extractor_right"] for f in fs),
            "disagreed_extractor_right": sum(not f["agree"] and f["extractor_right"] for f in fs),
        }
    docs = Counter()
    for r in ran:
        v = r["verification"]
        ex_right = all(f["extractor_right"] for f in v["fields"].values())
        docs[("agree" if v["agree_all"] else "differ", "right" if ex_right else "wrong")] += 1
    status_before = sum(_status_without_verifier(r["proposal"]) == r["expected_status"] for r in ok)
    status_after = sum(r["proposal"]["status"] == r["expected_status"] for r in ok)
    return {
        "verifier": verifier,
        "docs": len(records),
        "passed_checks": sum(_status_without_verifier(r["proposal"]) == "proposed" for r in ok),
        "verified": len(ran),
        "verifier_errors": sum(bool(r["verification"] and r["verification"]["error"]) for r in ok),
        "agree_all": pct(sum(r["verification"]["agree_all"] for r in ran), len(ran)),
        "doc_outcomes": {
            "agreed_and_extractor_right": docs[("agree", "right")],
            "agreed_but_extractor_wrong": docs[("agree", "wrong")],
            "disagreed_and_extractor_wrong": docs[("differ", "wrong")],
            "disagreed_but_extractor_right": docs[("differ", "right")],
        },
        "per_field": per_field,
        "status_accuracy_without_verifier": pct(status_before, len(ok)),
        "status_accuracy_with_verifier": pct(status_after, len(ok)),
        "mean_verifier_s": round(statistics.mean(ts), 2)
        if (ts := [r["proposal"]["verification"]["elapsed_s"] for r in ran if r["proposal"]["verification"].get("elapsed_s")])
        else None,
    }


def verification_md(v: dict[str, Any]) -> str:
    fmt = lambda x: "—" if x is None else f"{x:.0%}"  # noqa: E731
    o = v["doc_outcomes"]
    out = [
        f"## Verifier: {v['verifier']}",
        "",
        f"Docs: {v['docs']} | passed checks (so verified): {v['passed_checks']} | verified OK: {v['verified']} | "
        f"verifier errors: {v['verifier_errors']} | all fields agree: {fmt(v['agree_all'])} | mean {v['mean_verifier_s']} s",
        "",
        "| Doc outcome (graded against gold) | Docs |",
        "|---|---:|",
        f"| Agreed, Extractor right (confirmed) | {o['agreed_and_extractor_right']} |",
        f"| Agreed, Extractor wrong (missed) | {o['agreed_but_extractor_wrong']} |",
        f"| Disagreed, Extractor wrong (caught) | {o['disagreed_and_extractor_wrong']} |",
        f"| Disagreed, Extractor right (false alarm) | {o['disagreed_but_extractor_right']} |",
        "",
        "| Field | Agree | Extractor right | Verifier right | Agreed, both wrong | Disagreed, Extractor wrong | Disagreed, Extractor right |",
        "|---|---:|---:|---:|---:|---:|---:|",
        *(
            f"| {k} | {fmt(f['agree'])} | {fmt(f['extractor_right'])} | {fmt(f['verifier_right'])} | "
            f"{f['agreed_but_both_wrong']} | {f['disagreed_extractor_wrong']} | {f['disagreed_extractor_right']} |"
            for k, f in v["per_field"].items()
        ),
        "",
        f"Proposed / needs-a-look decision: {fmt(v['status_accuracy_without_verifier'])} without the verifier, "
        f"{fmt(v['status_accuracy_with_verifier'])} with it.",
        "",
    ]
    return "\n".join(out)


def report_md(summary: dict[str, Any]) -> str:
    c = summary["config"]
    out = [
        f"# Extraction eval: {c['mode']} / {c['model']}",
        "",
        f"Docs: {summary['n']} | errors: {summary['errors']} | messy: {summary['messy']} | "
        f"all fields correct: {summary['all_fields_correct']:.0%} | mean {summary['mean_elapsed_s']} s "
        f"(max {summary['max_elapsed_s']} s)",
        "",
        "## Accuracy per field",
        "",
        "| Field | Accuracy |",
        "|---|---:|",
        *(f"| {f} | {a:.0%} |" for f, a in summary["field_accuracy"].items()),
        "",
        "## Per gold case",
        "",
        "| Case | n | All fields | Status | Errors |",
        "|---|---:|---:|---:|---:|",
        *(
            f"| {k} | {v['n']} | {v['all_fields']:.0%} | {v['status']:.0%} | {v['errors']} |"
            for k, v in summary["by_case"].items()
        ),
        "",
    ]
    if summary.get("verification"):
        out.append(verification_md(summary["verification"]))
    return "\n".join(out)


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    cfg = AiConfig.resolve(mode=args.mode, model=args.model)
    if not args.verify:
        os.environ["VERIFIER"] = "off"
    backend = select_backend(cfg)
    if args.verify and backend is None:
        raise SystemExit("--verify given but VERIFIER=off is set in the environment")
    out = Path(args.out) if args.out else REPO / "evals" / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    golds = sorted(GOLD_DIR.glob("*.json"))
    if args.case:
        golds = [g for g in golds if json.loads(g.read_text(encoding="utf-8")).get("gold_case") in args.case]
    golds = golds[: args.limit] if args.limit else golds

    sem = asyncio.Semaphore(max(1, args.concurrency))

    async def guarded(i: int, g: Path) -> dict[str, Any]:
        async with sem:
            rec = await run_one(g, i, cfg, args.messy, out)
            mark = "ERR" if rec["error"] else ("ok " if all(rec["scores"].values()) else "MISS")
            print(f"[{mark}] {g.name} {rec['elapsed_s']:.1f}s {rec['error'] or ''}", flush=True)
            return rec

    records = await asyncio.gather(*(guarded(i, g) for i, g in enumerate(golds)))
    summary = summarise(list(records), cfg, args.messy)
    if backend is not None:
        summary["verification"] = summarise_verification(list(records), backend.label())
    summary["out_dir"] = str(out)
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out / "report.md").write_text(report_md(summary), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=("local", "key"), default="local")
    ap.add_argument("--model", default=None, help="override OLLAMA_MODEL / MODEL_API_MODEL")
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--messy", action="store_true", help="phone-photo style renders")
    ap.add_argument("--case", action="append", help="only these gold_case values (repeatable)")
    ap.add_argument("--verify", action="store_true", help="run the Verifier after passing checks and report agreement")
    ap.add_argument("--concurrency", type=int, default=1, help="keep 1 for local (single GPU)")
    ap.add_argument("--out", default=None, help="default evals/runs/<timestamp>/")
    summary = asyncio.run(main_async(ap.parse_args()))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
