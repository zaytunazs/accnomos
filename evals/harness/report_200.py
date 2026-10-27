"""Build the markdown report for an extraction run (+ optional judge.json).

    cd evals && python -m harness.report_200 runs/glimmer_messy_200 --out REPORT_glimmer_messy_200_2026-10-27.md \
        [--diagnoses diag.json] [--fixes fixes.md] [--candidates]

--candidates prints the ranked worst cases (with gold vs extracted) so diagnoses can be written; --diagnoses is
{"NNN_case.json": "one-line diagnosis"}; --fixes is markdown inserted under "Suggested fixes".
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from harness.run_extraction import FIELDS, GOLD_DIR, gold_side, score

NEW_FROM = 61


def load(run: Path, rescore: bool = False) -> list[dict[str, Any]]:
    recs = []
    for p in sorted(run.glob("*.json")):
        if p.name in ("summary.json", "judge.json"):
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        r["gold"] = json.loads((GOLD_DIR / r["file"]).read_text(encoding="utf-8"))
        if r["proposal"]:  # re-score with the current rules (the live run captured an older `gold_side`)
            r["scores"] = score(r["gold"], r["proposal"])
            if rescore:
                p.write_text(
                    json.dumps({k: v for k, v in r.items() if k not in ("gold", "no")}, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
        r["no"] = int(r["file"][:3])
        recs.append(r)
    return recs


def pct(xs: list[bool]) -> str:
    return f"{sum(xs) / len(xs):.0%}" if xs else "-"


def field_table(recs: list[dict[str, Any]]) -> list[str]:
    subsets = (
        ("all", recs),
        ("001-060", [r for r in recs if r["no"] < NEW_FROM]),
        ("061-200", [r for r in recs if r["no"] >= NEW_FROM]),
    )
    out = ["| Field | " + " | ".join(f"{n} (n={len(s)})" for n, s in subsets) + " |", "|---|" + "---:|" * len(subsets)]
    for f in FIELDS:
        out.append(f"| {f} | " + " | ".join(pct([r["scores"][f] for r in s]) for _, s in subsets) + " |")
    no_status = lambda r: all(v for k, v in r["scores"].items() if k != "status")  # noqa: E731
    out.append(
        "| **all fields except status** | " + " | ".join(pct([no_status(r) for r in s]) for _, s in subsets) + " |"
    )
    out.append(
        "| **all fields** | " + " | ".join(pct([all(r["scores"].values()) for r in s]) for _, s in subsets) + " |"
    )
    return out


def side_section(recs: list[dict[str, Any]]) -> list[str]:
    ok = [r for r in recs if r["proposal"]]
    out = [
        f"Side accuracy: **{pct([r['scores']['side'] for r in recs])}** ({sum(r['scores']['side'] for r in recs)}/{len(recs)}).",
        "",
    ]
    conf: Counter = Counter()
    for r in ok:
        got = "sale" if r["proposal"]["extracted"]["doc_type"] == "sales_invoice" else "purchase"
        conf[(gold_side(r["gold"]), got)] += 1
    out += ["| Gold side | read as sale | read as purchase |", "|---|---:|---:|"]
    for g in ("sale", "purchase"):
        out.append(f"| {g} | {conf[(g, 'sale')]} | {conf[(g, 'purchase')]} |")
    oriented = sum(any(c["code"] == "DOC_TYPE_ORIENTED" for c in r["proposal"]["checks"]) for r in ok)
    out += [
        "",
        f"`DOC_TYPE_ORIENTED` fired on {oriented} documents (run with `--business-name 'Bramblewood Joinery Ltd'`).",
    ]
    return out


def status_section(recs: list[dict[str, Any]]) -> list[str]:
    ok = [r for r in recs if r["proposal"]]
    conf = Counter((r["expected_status"], r["proposal"]["status"]) for r in ok)
    out = ["| Expected \\ got | proposed | needs_a_look |", "|---|---:|---:|"]
    for e in ("proposed", "needs_a_look"):
        out.append(f"| {e} | {conf[(e, 'proposed')]} | {conf[(e, 'needs_a_look')]} |")
    fails: Counter = Counter()
    warns: Counter = Counter()
    for r in ok:
        for c in r["proposal"]["checks"]:
            if not c["ok"]:
                (fails if c["severity"] == "fail" else warns)[c["code"]] += 1
    out += ["", "Checks that did not pass (documents):", "", "| Check | fail | warn |", "|---|---:|---:|"]
    for code in sorted(set(fails) | set(warns), key=lambda k: -(fails[k] + warns[k])):
        out.append(f"| {code} | {fails[code]} | {warns[code]} |")
    return out


def case_table(recs: list[dict[str, Any]]) -> list[str]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in recs:
        by[r["gold_case"] or "?"].append(r)
    out = ["| Case | n | All fields | Side | Status | Errors |", "|---|---:|---:|---:|---:|---:|"]
    for c, rs in sorted(by.items()):
        out.append(
            f"| {c} | {len(rs)} | {pct([all(r['scores'].values()) for r in rs])} | {pct([r['scores']['side'] for r in rs])} | "
            f"{pct([r['scores']['status'] for r in rs])} | {sum(r['error'] is not None for r in rs)} |"
        )
    return out


def err_size(r: dict[str, Any]) -> float:
    if not r["proposal"]:
        return 1e9
    ex, g = r["proposal"]["extracted"], r["gold"]
    return abs(ex["gross_total"] - g["gross_total"]) + abs(ex["vat_total"] - g["vat_total"])


def worst(recs: list[dict[str, Any]], n: int = 10) -> list[dict[str, Any]]:
    def key(r: dict[str, Any]) -> tuple:
        failed = [k for k, v in r["scores"].items() if not v]
        money = sum(k in failed for k in ("net_total", "vat_total", "gross_total"))
        return (-(len(failed) + money), -min(err_size(r), 1e6))

    return sorted((r for r in recs if not all(r["scores"].values())), key=key)[:n]


def describe(r: dict[str, Any]) -> str:
    g = r["gold"]
    if not r["proposal"]:
        return f"gold {g['supplier']['name']} {g['gross_total']} | ERROR {r['error']}"
    ex = r["proposal"]["extracted"]
    bad = [k for k, v in r["scores"].items() if not v]
    return (
        f"failed {bad}\n    gold: {g['supplier']['name']!r} vrn={g['supplier'].get('vat_number')} {g['date']} net={g['net_total']} "
        f"vat={g['vat_total']} gross={g['gross_total']} lines={len(g['lines'])} side={gold_side(g)} status={r['expected_status']}\n"
        f"    got : {ex['supplier_name']!r} vrn={ex['supplier_vat_number']} {ex['date']} net={ex['net_total']} vat={ex['vat_total']} "
        f"gross={ex['gross_total']} lines={len(ex['lines'])} type={ex['doc_type']} cur={ex['currency']} status={r['proposal']['status']}\n"
        f"    reasons: {r['proposal']['reasons']}"
    )


def judge_section(judge: dict[str, Any], recs: list[dict[str, Any]]) -> list[str]:
    s = judge["summary"]
    by_file = {d["file"]: d for d in judge["docs"] if "final_severity" in d}
    fields: Counter = Counter()
    for d in by_file.values():
        final = d["escalated"] or d["first"]
        for fe in final.get("field_errors", []):
            fields[str(fe.get("field", "?")).split("[")[0]] += 1
    out = [
        f"Judge: {s['model']}, escalating disagreements to {s['escalate']}. Judged {s['n']}, skipped {s['skipped']}, "
        f"first-pass disagreements with the code comparison {s['disagreements']}, escalated {s['escalated']}.",
        "",
        "| Final severity | Docs |",
        "|---|---:|",
    ]
    out += [f"| {k} | {v} |" for k, v in sorted(s["severity"].items(), key=lambda kv: -kv[1])]
    code_ok = {r["file"]: all(v for k, v in r["scores"].items() if k != "status") for r in recs}
    agree = sum((d["final_severity"] == "none") == code_ok[f] for f, d in by_file.items())
    lenient = sum((d["final_severity"] in ("none", "minor")) == code_ok[f] for f, d in by_file.items())
    unparsed = s["severity"].get("unparsed", 0)
    capped = sum((d["escalated"] or d["first"]).get("stop_reason") == "max_tokens" for d in by_file.values())
    out += [
        "",
        f"Final judge verdict agrees with the code comparison (fields only) on **{agree}/{len(by_file)}** documents "
        f"(judge `none` = code all right). Counting a `minor` verdict (cosmetic or category only) as right too: "
        f"{lenient}/{len(by_file)}.",
        "",
        f"`major` verdicts: {len(major := [f for f, d in by_file.items() if d['final_severity'] == 'major'])}, covering "
        f"{sum(not code_ok[f] for f in major)}/{sum(not v for f, v in code_ok.items() if f in by_file)} documents the code "
        f"scores wrong; the other {sum(code_ok[f] for f in major)} are documents the code scores right.",
        "",
        f"Unparsed verdicts: {unparsed}/{len(by_file)} ({100 * unparsed / max(1, len(by_file)):.1f} %); final replies cut off at the "
        f"reply cap: {capped}.",
        "",
        "Most frequent judge-flagged fields (final verdicts): "
        + (", ".join(f"{k} {v}" for k, v in fields.most_common(8)) or "none"),
    ]
    out += [
        "",
        "Caveat: the judge is noisy and not a ground truth. It flags line-item wording and category on most documents, "
        "which the code comparison does not score, so it disagrees with the code on nearly every first pass. "
        "Treat the code-scored field accuracy above as the headline; use the judge only to spot-check `major` verdicts.",
    ]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--diagnoses", type=Path)
    ap.add_argument("--fixes", type=Path)
    ap.add_argument("--candidates", action="store_true")
    ap.add_argument(
        "--rescore",
        action="store_true",
        help="write re-scored results back into the run's NNN_*.json (do before the judge)",
    )
    args = ap.parse_args()
    recs = load(args.run, args.rescore)
    if args.candidates:
        for r in worst(recs, 25):
            print(f"{r['file']} ({r['gold_case']})\n    {describe(r)}\n")
        return
    summary = json.loads((args.run / "summary.json").read_text(encoding="utf-8"))
    judge_path = args.run / "judge.json"
    diag = json.loads(args.diagnoses.read_text(encoding="utf-8")) if args.diagnoses else {}
    cfg = summary["config"]
    new = [r for r in recs if r["no"] >= NEW_FROM]
    out = [
        f"# Extraction eval: Glimmer on 200 messy documents ({cfg['model']}, {cfg['mode']})",
        "",
        f"Docs: **{len(recs)}** (60 original + 140 new from Qwen) | messy phone-photo renders | errors: {summary['errors']} | "
        f"mean {summary['mean_elapsed_s']} s per document (max {summary['max_elapsed_s']} s)",
        "",
        "Run: `python -m harness.run_extraction --mode local --messy --business-name 'Bramblewood Joinery Ltd'`; no extraction code was changed. "
        "Differences from the 60-document report: `side` is a new scored field, expected status is explicit per document on 061-200, "
        "and the books owner's name is passed to the pipeline so sale/purchase orientation runs.",
        "",
        "## Headline",
        "",
        f"- All fields correct (incl. side and status): **{pct([all(r['scores'].values()) for r in recs])}** "
        f"(original 60: {pct([all(r['scores'].values()) for r in recs if r['no'] < NEW_FROM])}, new 140: {pct([all(r['scores'].values()) for r in new])})",
        f"- Side accuracy: **{pct([r['scores']['side'] for r in recs])}**; status accuracy: **{pct([r['scores']['status'] for r in recs])}**",
        "",
        "## Accuracy per field",
        "",
        *field_table(recs),
        "",
        "## Side (sale vs purchase)",
        "",
        *side_section(recs),
        "",
        "## Check status",
        "",
        *status_section(recs),
        "",
        "## Per gold case",
        "",
        *case_table(recs),
        "",
    ]
    if judge_path.exists():
        out += ["## Claude judge", "", *judge_section(json.loads(judge_path.read_text(encoding="utf-8")), recs), ""]
    out += ["## Ten worst cases", "", "| Document | Case | Failed | Diagnosis |", "|---|---|---|---|"]
    for r in worst(recs):
        failed = ", ".join(k for k, v in r["scores"].items() if not v)
        out.append(f"| {r['file']} | {r['gold_case']} | {failed} | {diag.get(r['file'], 'TODO')} |")
    out += ["", "## Suggested fixes", "", args.fixes.read_text(encoding="utf-8") if args.fixes else "TODO", ""]
    args.out.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
