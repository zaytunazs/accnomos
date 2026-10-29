"""Document-type classifier eval: the mixed gold set through the app's own upload-flow classifier.

    cd evals && python -m harness.classify --dry-run              # build the cases, call no model
    cd evals && python -m harness.classify --stub                 # whole pipeline against an in-process fake model
    cd evals && python -m harness.classify                        # Spark model (OLLAMA_URL), or Meta (META_API_KEY)
    cd evals && python -m harness.classify --limit 40

The code under test is ``app.ai.classify.classify`` (the same prompt, strict JSON schema and validation the
upload flow in ``app/scan_jobs.py`` uses), through the provider chain: the Meta Model API when ``META_API_KEY``
is set, else the Spark local model (``OLLAMA_URL``, default ``http://localhost:11434``). When the model does
not answer, the harness falls back to ``app.ai.classify.by_words`` exactly as the upload flow does, and counts
how often that happened. Bank CSVs never reach the model: like the upload flow, they are recognised by code.

Cases: every ``evals/gold/receipts/*.json`` (purchase receipts and invoices, sales invoices, credit notes,
utilities and edge cases), every ``evals/gold/cis/<id>/`` (contractor statements and reverse-charge invoices),
every landlord document in ``evals/gold/landlord/landlord_*/`` (letting statements, insurance, mortgage
statements and bills), plus synthetic bank-statement CSVs in the sample-books seed layout (``tools/seed_demo.py``
``_statement``: the Starling header, a preamble row, ``SAMPLE`` label). Each case is labelled with one of the
classifier's own types (``app.ai.classify.KINDS``); the classifier sees only the document text, never the label.

Scoring, per document
---------------------
* ``correct``: the predicted kind equals the gold label (a refusal counts as wrong: a person gets nothing).
* per-type precision and recall over the classifier's type set.
* a confusion matrix (gold label -> predicted kind, refusals as ``refused``).
* latency p50 / p95 over the answered documents, and the share of rows where code's fallback guess was used.

Writes ``evals/runs/classify/{results.jsonl, summary.json, report.md}``. Resumable: ids already in
results.jsonl are skipped (``--fresh`` starts again). One request at a time, so the production runtime on
the same machine keeps priority.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import os
import random
import re
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "services" / "runtime", REPO / "packages" / "ledger" / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from app.ai import classify as classify_mod  # noqa: E402
from app.ai.config import (  # noqa: E402
    DEFAULT_MODEL_API_BASE,
    DEFAULT_MODEL_API_MODEL,
    DEFAULT_OLLAMA_BASE,
    DEFAULT_OLLAMA_MODEL,
    AiConfig,
)
from app.ai.extract import ExtractionError  # noqa: E402

RECEIPTS = REPO / "evals" / "gold" / "receipts"
CIS = REPO / "evals" / "gold" / "cis"
LANDLORD = REPO / "evals" / "gold" / "landlord"
OUT = REPO / "evals" / "runs" / "classify"
BUSINESS = "Bramblewood Joinery Ltd"  # the fictional company, as in the upload flow
N_BANK_CSV = 6  # synthetic statements in the sample-books seed layout

#: Gold CIS kinds -> the classifier's type set (a CIS statement is contractor paperwork, not a bank statement).
CIS_LABEL = {"cis_statement": "other", "reverse_charge_invoice": "purchase_invoice"}

#: Gold landlord kinds -> the classifier's type set (a mortgage statement lists transactions and balances).
LANDLORD_LABEL = {
    "letting_statement": "other",
    "insurance": "purchase_invoice",
    "mortgage_statement": "bank_statement",
    "invoice": "purchase_invoice",
}


@dataclass
class Case:
    """One gold document with its expected classifier type."""

    id: str
    source: str  # receipts | cis | landlord | bank_csv
    label: str  # one of app.ai.classify.KINDS
    text: str
    name: str = ""  # file name, as the upload flow passes it to the code fallback


def _receipt_label(doc: dict[str, Any]) -> str:
    if doc.get("gold_case") == "credit_note" or doc.get("is_credit_note") or doc.get("doc_type") == "credit_note":
        return "credit_note"
    if doc.get("side") == "sale" or doc.get("doc_type") == "sales_invoice":
        return "sales_invoice"
    if doc.get("doc_type") == "purchase_invoice":
        return "purchase_invoice"
    return "receipt"


def load_receipt_cases() -> list[Case]:
    out = []
    for path in sorted(RECEIPTS.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        text = doc.get("printed_text") or ""
        assert text, f"{path.name} has no printed_text"
        out.append(Case(id=f"receipts/{path.stem}", source="receipts", label=_receipt_label(doc), text=text))
    return out


def load_cis_cases() -> list[Case]:
    out = []
    for d in sorted(CIS.iterdir()):
        if not d.is_dir():
            continue
        doc, exp = d / "document.txt", d / "expected.json"
        if not (doc.exists() and exp.exists()):
            continue
        kind = str(json.loads(exp.read_text(encoding="utf-8"))["expected"].get("kind", ""))
        out.append(
            Case(
                id=f"cis/{d.name}",
                source="cis",
                label=CIS_LABEL.get(kind, "other"),
                text=doc.read_text(encoding="utf-8"),
            )
        )
    return out


def _bill_files(bills: Path) -> dict[str, Path]:
    """Bill text files by ISO date (parsed from the printed ``Date: DD/MM/YYYY``)."""
    out = {}
    for p in sorted(bills.glob("*.txt")):
        m = re.search(r"Date:\s*(\d{2})/(\d{2})/(\d{4})", p.read_text(encoding="utf-8"))
        if m:
            out[f"{m.group(3)}-{m.group(2)}-{m.group(1)}"] = p
    return out


def load_landlord_cases() -> list[Case]:
    out = []
    for landlord in sorted(LANDLORD.iterdir()):
        if not landlord.is_dir():
            continue
        exp = json.loads((landlord / "expectations.json").read_text(encoding="utf-8"))
        bills = _bill_files(landlord / "bills")
        for doc in exp["documents"]:
            kind = str(doc["kind"])
            if doc["kind"] == "letting_statement":
                path = landlord / "statements" / f"{doc['date'][:7]}_{doc['property']}.txt"
            else:
                path = bills[doc["date"]]
            out.append(
                Case(
                    id=f"landlord/{landlord.name}/{path.stem}",
                    source="landlord",
                    label=LANDLORD_LABEL[kind],
                    text=path.read_text(encoding="utf-8"),
                )
            )
    return out


def bank_csv_text(seed: int) -> str:
    """A synthetic Starling-layout statement in the sample-books seed shape (``tools/seed_demo.py``)."""
    rng = random.Random(seed)
    parties = ["Screwfix Direct", "Travis Perkins", "Acme Kitchens Ltd", "Starling Bank", "HMRC VAT", "Shell Fuel"]
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow([f"SAMPLE \u2014 FICTIONAL COMPANY: Bramblewood Joinery Ltd, statement {seed}"])
    w.writerow(["Date", "Counter Party", "Reference", "Type", "Amount (GBP)", "Balance (GBP)", "Spending Category"])
    balance = 12_500_00
    for i in range(rng.randint(8, 14)):
        pence = rng.choice([-1, -1, 1]) * rng.randint(500, 95_000)
        balance += pence
        w.writerow(
            [
                f"{rng.randint(1, 28):02d}/10/2026",
                rng.choice(parties),
                f"REF-{seed:02d}-{i:02d}",
                rng.choice(["CARD PAYMENT", "FASTER PAYMENT", "DIRECT DEBIT"]),
                f"{pence / 100:,.2f}",
                f"{balance / 100:,.2f}",
                "INCOME" if pence > 0 else "GENERAL",
            ]
        )
    return out.getvalue()


def load_cases() -> list[Case]:
    cases = load_receipt_cases() + load_cis_cases() + load_landlord_cases()
    cases += [
        Case(
            id=f"bank_csv/synth-{i:02d}",
            source="bank_csv",
            label="bank_statement",
            text=bank_csv_text(1000 + i),
            name=f"SAMPLE statement {i}.csv",
        )
        for i in range(1, N_BANK_CSV + 1)
    ]
    ids = [c.id for c in cases]
    assert len(set(ids)) == len(ids), "duplicate case ids"
    assert all(c.label in classify_mod.KINDS for c in cases), "every label is one of the classifier's types"
    return cases


# -------------------------------------------------------------------------------- run


async def run_case(case: Case, cfg: AiConfig) -> dict[str, Any]:
    t0 = time.perf_counter()
    row: dict[str, Any] = {"id": case.id, "source": case.source, "label": case.label}
    if case.source == "bank_csv":
        # The upload flow recognises a CSV by code alone; it never reaches the model.
        guess = classify_mod.Guess(
            kind="bank_statement", confidence=0.95, reason="A bank CSV recognised by code", by="code"
        )
        row.update(
            outcome="ok",
            predicted=guess.kind,
            confidence=guess.confidence,
            by="code",
            fallback=False,
            csv_by_code=True,
            correct=guess.kind == case.label,
            elapsed_s=round(time.perf_counter() - t0, 3),
        )
        return row
    try:
        guess = await classify_mod.classify(None, None, cfg, text=case.text, business_name=BUSINESS)
        fallback = False
    except ExtractionError:
        # The upload flow's fallback: code guesses from the words when the model does not answer.
        guess = classify_mod.by_words(case.text, case.name, BUSINESS)
        fallback = True
    except Exception as exc:  # noqa: BLE001 -- anything else is a refusal, never a crash
        row.update(
            outcome="refused",
            error=f"{type(exc).__name__}: {exc}"[:300],
            elapsed_s=round(time.perf_counter() - t0, 3),
            fallback=False,
            csv_by_code=False,
        )
        return row
    row.update(
        outcome="ok",
        predicted=guess.kind,
        confidence=guess.confidence,
        by=guess.by,
        fallback=fallback,
        csv_by_code=False,
        reason=guess.reason,
        correct=guess.kind == case.label,
        elapsed_s=round(time.perf_counter() - t0, 3),
    )
    return row


def pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def percentile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 3)


def summarise(rows: list[dict[str, Any]], cfg: AiConfig | None, stub: bool) -> dict[str, Any]:
    total = len(rows)
    ok = [r for r in rows if r["outcome"] == "ok"]
    refused = total - len(ok)
    fallback = sum(1 for r in ok if r.get("fallback"))
    csv_code = sum(1 for r in ok if r.get("csv_by_code"))
    kinds = list(classify_mod.KINDS)
    per_type = {}
    for kind in kinds:
        gold = [r for r in ok if r["label"] == kind]
        pred = [r for r in ok if r.get("predicted") == kind]
        right = sum(1 for r in ok if r["label"] == kind == r.get("predicted"))
        per_type[kind] = {
            "gold": len(gold),
            "predicted": len(pred),
            "correct": right,
            "precision_pct": pct(right, len(pred)),
            "recall_pct": pct(right, len(gold)),
        }
    confusion = {
        gold: {pred: sum(1 for r in ok if r["label"] == gold and r.get("predicted") == pred) for pred in kinds}
        for gold in kinds
        if any(r["label"] == gold for r in ok)
    }
    by_source = {}
    for source in sorted({r["source"] for r in rows}):
        sub = [r for r in rows if r["source"] == source]
        sub_ok = [r for r in sub if r["outcome"] == "ok"]
        by_source[source] = {
            "docs": len(sub),
            "answered": len(sub_ok),
            "correct": sum(1 for r in sub_ok if r.get("correct")),
            "accuracy_pct": pct(sum(1 for r in sub_ok if r.get("correct")), len(sub)),
        }
    lat = [r["elapsed_s"] for r in rows if r.get("elapsed_s") is not None]
    misses = [r for r in ok if not r.get("correct")]
    return {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": (cfg.model if cfg else None),
        "base_url": (cfg.base_url if cfg else None),
        "stub": stub,
        "docs": total,
        "answered": len(ok),
        "refusals": refused,
        "refusal_pct": pct(refused, total),
        "accuracy_pct": pct(sum(1 for r in ok if r.get("correct")), total),
        "fallback_used": fallback,
        "fallback_pct": pct(fallback, len(ok)),
        "csv_by_code": csv_code,
        "per_type": per_type,
        "confusion": confusion,
        "by_source": by_source,
        "latency_s": {
            "mean": round(statistics.fmean(lat), 3) if lat else None,
            "p50": percentile(lat, 0.5),
            "p95": percentile(lat, 0.95),
            "max": round(max(lat), 3) if lat else None,
            "total": round(sum(lat), 1),
        },
        "worst": [
            {"id": r["id"], "label": r["label"], "predicted": r.get("predicted"), "reason": r.get("reason")}
            for r in misses[:10]
        ],
    }


def report_md(s: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    L = s["latency_s"]
    stub_note = " (STUB: a fake model, numbers mean nothing)" if s["stub"] else ""
    kinds = [k for k in classify_mod.KINDS if k in s["confusion"]]
    header = "| Gold \\ predicted | " + " | ".join(classify_mod.KINDS) + " |"
    sep = "|" + "---|" * (len(classify_mod.KINDS) + 1)
    conf = [f"| {g} | " + " | ".join(str(s["confusion"][g][p]) for p in classify_mod.KINDS) + " |" for g in kinds]
    out = [
        "# Document-type classifier eval",
        "",
        f"Model `{s['model']}` at `{s['base_url']}`{stub_note}; {s['generated']}. "
        "Code under test: `app.ai.classify.classify` through the provider chain (Meta when `META_API_KEY` "
        "is set, else the Spark local model), with `app.ai.classify.by_words` on a model miss and code-only "
        "recognition for bank CSVs, exactly as the upload flow (`app/scan_jobs.py`) does.",
        "",
        f"- Documents: **{s['docs']}** ({s['answered']} answered, **{s['refusals']} refusals**, {s['refusal_pct']}%)",
        f"- Accuracy (predicted kind equals the gold label; a refusal counts as wrong): **{s['accuracy_pct']}%**",
        f"- Code's fallback guess used on **{s['fallback_used']}** answered documents ({s['fallback_pct']}%)",
        f"- Bank CSVs recognised by code alone: {s['csv_by_code']}",
        f"- Latency: mean {L['mean']} s, p50 {L['p50']} s, p95 {L['p95']} s, max {L['max']} s (total {L['total']} s)",
        "",
        "## Per-type precision and recall (answered documents)",
        "",
        "| Type | Gold | Predicted | Correct | Precision | Recall |",
        "|---|---:|---:|---:|---:|---:|",
        *(
            f"| {k} | {v['gold']} | {v['predicted']} | {v['correct']} | {v['precision_pct']}% | {v['recall_pct']}% |"
            for k, v in s["per_type"].items()
        ),
        "",
        "## Confusion matrix (rows: gold label, columns: predicted kind)",
        "",
        header,
        sep,
        *conf,
        "",
        "## Accuracy by source (refusals count as wrong)",
        "",
        "| Source | Docs | Answered | Correct | Accuracy |",
        "|---|---:|---:|---:|---:|",
        *(
            f"| {k} | {v['docs']} | {v['answered']} | {v['correct']} | {v['accuracy_pct']}% |"
            for k, v in s["by_source"].items()
        ),
        "",
        "## First 10 misses",
        "",
        "| Id | Gold label | Predicted | Reason |",
        "|---|---|---|---|",
        *(f"| {w['id']} | {w['label']} | {w['predicted']} | {(w['reason'] or '')[:80]} |" for w in s["worst"]),
        "",
        "Refusals (the model gave nothing usable and code raised):",
        "",
        *(f"- {r['id']} ({r['label']}): {r.get('error')}" for r in rows if r["outcome"] != "ok"),
        "",
        "How it is scored: the predicted kind against the gold label, one of the classifier's own types. "
        "Receipts and invoices take their label from the gold `doc_type`/`side` (credit notes first); "
        "CIS statements are `other` and reverse-charge invoices `purchase_invoice`; letting statements are "
        "`other`, insurance and landlord bills `purchase_invoice`, mortgage statements `bank_statement`; "
        "synthetic Starling-layout CSVs are `bank_statement`.",
    ]
    return "\n".join(out) + "\n"


# -------------------------------------------------------------------------------- stub model


def _stub_payload(case: Case, faults: bool = True) -> str:
    """A fake model reply for the document: the gold kind, with deterministic faults."""
    key = sum(ord(ch) for ch in case.text)
    if faults and key % 29 == 0:
        return "Certainly! This looks like a receipt of some kind"  # invalid JSON
    kind = case.label
    if faults and key % 31 == 0:  # a plain miss on the kind
        kind = next(k for k in classify_mod.KINDS if k != case.label)
    return json.dumps({"kind": kind, "confidence": 0.9, "reason": "stub guess"})


class _StubResponse:
    def __init__(self, text: str) -> None:
        self._text = text

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return {"message": {"content": self._text}, "choices": [{"message": {"content": self._text}}]}


_CASES_CACHE: list[Case] | None = None


def _cached_cases() -> list[Case]:
    global _CASES_CACHE  # noqa: PLW0603 -- the harness-wide case cache, as in the other harnesses
    if _CASES_CACHE is None:
        _CASES_CACHE = load_cases()
    return _CASES_CACHE


class _StubClient:
    """Stands in for httpx.AsyncClient: the request path is real, the model's bytes are canned."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _StubClient:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def post(self, url: str, **kwargs: Any) -> _StubResponse:
        payload = kwargs.get("json") or {}
        text = ""
        for m in payload.get("messages", []):
            content = m.get("content", "")
            if isinstance(content, list):  # Meta (OpenAI-compatible) shape: content parts
                text += "".join(p.get("text", "") for p in content if isinstance(p, dict))
            elif isinstance(content, str):
                text += content
        match = next((c for c in _cached_cases() if c.text.strip() in text), None)
        if match is None:
            return _StubResponse("no document recognised")
        return _StubResponse(_stub_payload(match))


# -------------------------------------------------------------------------------- main


def read_results(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:  # a line cut short by a kill: asked again
                continue
    return out


def _default_base() -> str:
    env = (os.getenv("OLLAMA_URL") or "").strip()
    if env:
        base = env[: -len("/api/tags")] if env.rstrip("/").endswith("/api/tags") else env
        return base.rstrip("/") or DEFAULT_OLLAMA_BASE
    return DEFAULT_OLLAMA_BASE


def default_config(base: str | None = None, model: str | None = None) -> AiConfig:
    """The provider chain default: the Meta Model API when ``META_API_KEY`` is set, else the Spark local model."""
    if (os.getenv("META_API_KEY") or "").strip():
        return AiConfig(
            mode="key",
            base_url=(os.getenv("MODEL_API_BASE") or DEFAULT_MODEL_API_BASE).rstrip("/"),
            model=model or os.getenv("MODEL_API_MODEL") or DEFAULT_MODEL_API_MODEL,
            api_key=os.getenv("META_API_KEY"),
            provider="key",
        )
    return AiConfig(
        mode="local",
        base_url=(base or _default_base()).rstrip("/"),
        model=model or os.getenv("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL,
        provider="local",
    )


async def main_async(args: argparse.Namespace) -> dict[str, Any] | None:
    cases = load_cases()
    if args.limit:
        step = max(1, len(cases) // args.limit)  # spread over sources and kinds, not just the receipts
        cases = cases[::step][: args.limit]
    by_source = Counter(c.source for c in cases)
    print(f"{len(cases)} documents {dict(by_source)}", flush=True)
    if args.dry_run:
        for c in cases[: args.show]:
            print(f"  {c.id} {c.label}")
        print(json.dumps({k: len([c for c in cases if c.label == k]) for k in classify_mod.KINDS}, indent=1))
        return None

    out = Path(args.out) if args.out else OUT
    out.mkdir(parents=True, exist_ok=True)
    results = out / "results.jsonl"
    if args.fresh and results.exists():
        results.unlink()
    done = {r["id"] for r in read_results(results)}
    cfg = default_config(args.base, args.model)
    import httpx as _httpx  # noqa: E402

    original = _httpx.AsyncClient
    if args.stub:
        _httpx.AsyncClient = _StubClient  # type: ignore[assignment]
    try:
        with results.open("a", encoding="utf-8") as fh:
            if results.stat().st_size and not results.read_bytes().endswith(b"\n"):
                fh.write("\n")  # a kill left half a line: do not glue the next row onto it
            for i, case in enumerate(cases, start=1):
                if case.id in done:
                    continue
                row = await run_case(case, cfg)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                mark = "ok " if row["outcome"] == "ok" and row.get("correct") else "MISS"
                print(f"[{i}/{len(cases)}] {mark} {row['elapsed_s']:.1f}s {case.id}", flush=True)
    finally:
        _httpx.AsyncClient = original  # type: ignore[assignment]
    wanted = {c.id for c in cases}
    rows = [r for r in read_results(results) if r["id"] in wanted]
    summary = summarise(rows, cfg, args.stub)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "report.md").write_text(report_md(summary, rows), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0, help="0 = every document; otherwise a spread sample of that size")
    ap.add_argument("--dry-run", action="store_true", help="build cases and expectations, call no model, write nothing")
    ap.add_argument("--stub", action="store_true", help="in-process fake model (tests the pipeline, not the model)")
    ap.add_argument("--fresh", action="store_true", help="ignore and replace an earlier results.jsonl")
    ap.add_argument("--show", type=int, default=15, help="--dry-run: how many cases to print")
    ap.add_argument("--base", default=None, help="local base URL (default OLLAMA_URL or localhost:11434)")
    ap.add_argument("--model", default=None, help="default OLLAMA_MODEL/MODEL_API_MODEL per provider")
    ap.add_argument("--out", default=None, help="default evals/runs/classify/")
    args = ap.parse_args(argv)
    if not args.stub and not args.dry_run and not (os.getenv("META_API_KEY") or "").strip():
        import urllib.request  # noqa: E402

        probe = (args.base or _default_base()).rstrip("/") + "/api/tags"
        try:
            urllib.request.urlopen(probe, timeout=5).read(1)
        except Exception as exc:  # noqa: BLE001 -- a down server reads as exit 2, like the stt harness
            print(f"no model server at {probe} ({exc}); set META_API_KEY or start Ollama", flush=True)
            return 2
    summary = asyncio.run(main_async(args))
    if summary:
        print(json.dumps({k: summary[k] for k in ("docs", "answered", "accuracy_pct", "refusals", "latency_s")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
