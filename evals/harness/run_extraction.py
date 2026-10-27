"""Extraction eval: render each gold doc, run the real pipeline, score against gold.

    cd evals && python -m harness.run_extraction --mode local --limit 10 --messy
    (or from repo root: PYTHONPATH=evals python -m harness.run_extraction ...)

Writes <out>/NNN_case.json (+ .png), summary.json and report.md; prints the summary.
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "services" / "runtime", REPO / "packages" / "ledger" / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from app.ai.config import AiConfig  # noqa: E402
from app.checks import normalise_vat_number  # noqa: E402
from app.pipeline import process_image  # noqa: E402

from harness.render import render_receipt  # noqa: E402

GOLD_DIR = REPO / "evals" / "gold" / "receipts"
FIELDS = ("supplier_name", "vat_number", "date", "net_total", "vat_total", "gross_total", "line_count", "side", "status")
NEEDS_LOOK_CASES = {"arith_error", "no_vat_number"}


def gold_side(gold: dict[str, Any]) -> str:
    """'sale' when the books owner issued the document, else 'purchase'.

    001-060 have no `side` and four of their `doc_type: sales_invoice` labels are wrong (Bramblewood is the
    customer), so the supplier decides.
    """
    if gold.get("side"):
        return gold["side"]
    return "sale" if gold["supplier"]["name"].lower().startswith("bramblewood") else "purchase"


def expected_status(gold: dict[str, Any]) -> str:
    if gold.get("expected_status"):  # explicit on docs 061+; the rules below cover the original 60
        return gold["expected_status"]
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
        "side": gold_side(gold) == ("sale" if ex["doc_type"] == "sales_invoice" else "purchase"),
        "status": proposal["status"] == expected_status(gold),
    }


async def run_one(path: Path, idx: int, cfg: AiConfig, messy: bool, out: Path, business_name: str | None = None) -> dict[str, Any]:
    gold = json.loads(path.read_text(encoding="utf-8"))
    png = render_receipt(gold["printed_text"], messy=messy, seed=idx, damage=gold.get("damage"))
    (out / f"{path.stem}.png").write_bytes(png)
    rec: dict[str, Any] = {
        "file": path.name,
        "gold_case": gold.get("gold_case"),
        "label": gold.get("label"),
        "expected_status": expected_status(gold),
    }
    t0 = time.perf_counter()
    try:
        proposal = (await process_image(png, "image/png", cfg, business_name=business_name)).model_dump(mode="json")
        rec |= {"proposal": proposal, "scores": score(gold, proposal), "error": None}
    except Exception as exc:  # record and carry on; one bad doc must not stop the run
        rec |= {"proposal": None, "scores": {f: False for f in FIELDS}, "error": f"{type(exc).__name__}: {exc}"}
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
    return "\n".join(out)


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    cfg = AiConfig.resolve(mode=args.mode, model=args.model)
    out = Path(args.out) if args.out else REPO / "evals" / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    golds = sorted(GOLD_DIR.glob("*.json"))
    if args.case:
        golds = [g for g in golds if json.loads(g.read_text(encoding="utf-8")).get("gold_case") in args.case]
    golds = golds[: args.limit] if args.limit else golds

    sem = asyncio.Semaphore(max(1, args.concurrency))

    async def guarded(i: int, g: Path) -> dict[str, Any]:
        async with sem:
            rec = await run_one(g, i, cfg, args.messy, out, args.business_name)
            mark = "ERR" if rec["error"] else ("ok " if all(rec["scores"].values()) else "MISS")
            print(f"[{mark}] {g.name} {rec['elapsed_s']:.1f}s {rec['error'] or ''}", flush=True)
            return rec

    records = await asyncio.gather(*(guarded(i, g) for i, g in enumerate(golds)))
    summary = summarise(list(records), cfg, args.messy)
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
    ap.add_argument("--business-name", default=None, help="books owner, enables sale/purchase orientation (e.g. 'Bramblewood Joinery Ltd')")
    ap.add_argument("--concurrency", type=int, default=1, help="keep 1 for local (single GPU)")
    ap.add_argument("--out", default=None, help="default evals/runs/<timestamp>/")
    summary = asyncio.run(main_async(ap.parse_args()))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
