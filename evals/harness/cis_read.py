"""CIS reader eval: every gold CIS document through the real `read_cis_document` plus the code checks.

    cd evals && python -m harness.cis_read --dry-run                  # build the cases, call no model
    cd evals && python -m harness.cis_read --stub                     # whole pipeline against an in-process fake model
    cd evals && python -m harness.cis_read                            # Glimmer on the Spark (Ollama :11434)
    cd evals && python -m harness.cis_read --base http://127.0.0.1:11434 --model muse-glimmer:30b --limit 20

The code under test is ``app.ai.cis_read.read_cis_document`` (the same prompt, strict JSON schema and
validation production uses) followed by ``app.cis_readings.from_reading`` (pounds to pence, dates parsed,
``app.cis.statement_checks`` / ``bill_checks`` in code). ``--stub`` fakes the Ollama HTTP reply in-process:
the real request path, prompt and response parsing run; only the bytes from the model are canned.

Cases: every ``evals/gold/cis/<id>/`` folder (S*: contractor payment and deduction statements, R*:
subcontractor reverse-charge invoices), each with ``document.txt`` (what the reader sees) and
``expected.json`` (the gold reading and the check codes that must fail on the distractors).

Scoring, per document
---------------------
* one row per field: ``kind``; statements add contractor / subcontractor names, subcontractor UTR,
  tax month end, gross, materials, amount liable, deduction, net paid and the reverse-charge wording flag;
  invoices add supplier name, supplier VAT number, invoice number, invoice date, net, VAT rate, the printed
  reverse-charge VAT and the reverse-charge wording flag. Names match fuzzily (ratio >= 0.8, as in
  ``harness.run_extraction``); amounts match within a penny; UTRs compare digits-only; VAT numbers are
  normalised by ``app.checks.normalise_vat_number``.
* ``checks``: whether the set of failing code-side check codes is exactly ``expect_check_fail``
  (``RATE`` on statements whose printed deduction is not 0/20/30% of the amount liable;
  ``RC_WORDING`` on invoices with no reverse-charge wording). On statements the CIS settings take the payment
  status from the gold ``rate`` (0 -> gross, 20 -> net, 30 -> unverified); on invoices the gold ``rate`` is
  the VAT rate and the settings stay at the default (invoice checks do not use them).

Writes ``evals/runs/cis_read/{results.jsonl, summary.json, report.md}``. Resumable: ids already in
results.jsonl are skipped (``--fresh`` starts again). One request at a time, so the production runtime on
the same machine keeps priority.
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
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "services" / "runtime", REPO / "packages" / "ledger" / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from app import cis as cis_mod  # noqa: E402
from app.ai import cis_read as cis_read_mod  # noqa: E402
from app.ai.config import DEFAULT_OLLAMA_BASE, DEFAULT_OLLAMA_MODEL, AiConfig  # noqa: E402
from app.ai.extract import ExtractionError  # noqa: E402
from app.checks import normalise_vat_number  # noqa: E402
from app.cis_readings import from_reading  # noqa: E402

GOLD = REPO / "evals" / "gold" / "cis"
OUT = REPO / "evals" / "runs" / "cis_read"

RATE_STATUS = {0: "gross", 20: "net", 30: "unverified"}

# field -> comparator. `kind` selects statement fields, invoice fields, or both.
NAME, UTR, VRN, DATE, MONEY, BOOL, KIND, RATE = (
    "name",
    "utr",
    "vrn",
    "date",
    "money",
    "bool",
    "kind",
    "rate",
)
STATEMENT_FIELDS: list[tuple[str, str]] = [
    ("kind", KIND),
    ("contractor_name", NAME),
    ("subcontractor_name", NAME),
    ("subcontractor_utr", UTR),
    ("tax_month_end", DATE),
    ("gross_amount", MONEY),
    ("materials", MONEY),
    ("amount_liable", MONEY),
    ("deduction", MONEY),
    ("net_paid", MONEY),
    ("reverse_charge_wording", BOOL),
]
INVOICE_FIELDS: list[tuple[str, str]] = [
    ("kind", KIND),
    ("supplier_name", NAME),
    ("supplier_vat_number", VRN),
    ("invoice_number", KIND),
    ("invoice_date", DATE),
    ("net", MONEY),
    ("vat_rate", RATE),
    ("reverse_charge_vat", MONEY),
    ("reverse_charge_wording", BOOL),
]
FIELD_ORDER = [f for f, _ in STATEMENT_FIELDS] + [f for f, _ in INVOICE_FIELDS if f not in dict(STATEMENT_FIELDS)]


@dataclass
class Case:
    """One gold document with its expectation."""

    id: str
    text: str
    expected: dict[str, Any]
    expect_fail: list[str]
    rate: int
    fields: list[tuple[str, str]]

    @property
    def kind(self) -> str:
        return str(self.expected.get("kind", ""))


def load_cases() -> list[Case]:
    out: list[Case] = []
    for d in sorted(GOLD.iterdir()):
        if not d.is_dir():
            continue
        doc, exp = d / "document.txt", d / "expected.json"
        if not (doc.exists() and exp.exists()):
            continue
        gold = json.loads(exp.read_text(encoding="utf-8"))
        expected = gold["expected"]
        kind = expected.get("kind")
        fields = STATEMENT_FIELDS if kind == "cis_statement" else INVOICE_FIELDS if kind == "reverse_charge_invoice" else [("kind", KIND)]
        out.append(
            Case(
                id=gold.get("id", d.name),
                text=doc.read_text(encoding="utf-8"),
                expected=expected,
                expect_fail=list(gold.get("expect_check_fail", [])),
                rate=int(gold.get("rate", 20)),
                fields=fields,
            )
        )
    return out


# -------------------------------------------------------------------------------- scoring


def _name_eq(a: str | None, b: str | None) -> bool:
    return difflib.SequenceMatcher(None, (a or "").lower().strip(), (b or "").lower().strip()).ratio() >= 0.8


def _digits(v: Any) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def _money_eq(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is b
    try:
        return abs(round(float(a) * 100) - round(float(b) * 100)) <= 1
    except (TypeError, ValueError):
        return False


def field_eq(how: str, got: Any, want: Any) -> bool:
    if how == KIND:
        if isinstance(got, str):
            got = got.strip()
        if isinstance(want, str):
            want = want.strip()
        return got == want
    if how == NAME:
        return _name_eq(None if got is None else str(got), None if want is None else str(want))
    if how == UTR:
        return bool(_digits(want)) and _digits(got) == _digits(want)
    if how == VRN:
        return normalise_vat_number(str(got or "") or None) == normalise_vat_number(str(want or "") or None)
    if how == DATE:
        return (None if got is None else str(got)) == (None if want is None else str(want))
    if how == MONEY:
        return _money_eq(got, want)
    if how == BOOL:
        return bool(got) is bool(want)
    if how == RATE:
        try:
            return got is not None and want is not None and float(got) == float(want)
        except (TypeError, ValueError):
            return False
    raise AssertionError(f"unknown comparator {how}")


def score_fields(reading: Any, case: Case) -> dict[str, bool]:
    got = reading.model_dump() if hasattr(reading, "model_dump") else dict(reading)
    return {name: field_eq(how, got.get(name), case.expected.get(name)) for name, how in case.fields}


# -------------------------------------------------------------------------------- stub model


def _stub_payload(text: str, faults: bool = True) -> str:
    """A fake Ollama reply for the document: the gold reading, with deterministic faults."""
    case = next(c for c in load_cases() if c.text == text)
    key = sum(ord(ch) for ch in text)
    if faults and key % 29 == 0:
        return "Certainly! The statement shows gross five thousand"  # invalid JSON
    obj = dict(case.expected)
    obj.setdefault("contractor_ref", None)
    obj.setdefault("verification_number", None)
    obj.setdefault("amount_liable", None)
    obj.setdefault("contractor_name", None)
    obj.setdefault("subcontractor_name", None)
    obj.setdefault("subcontractor_utr", None)
    obj.setdefault("tax_month_end", None)
    obj.setdefault("gross_amount", None)
    obj.setdefault("materials", None)
    obj.setdefault("deduction", None)
    obj.setdefault("net_paid", None)
    obj.setdefault("supplier_name", None)
    obj.setdefault("supplier_vat_number", None)
    obj.setdefault("invoice_number", None)
    obj.setdefault("invoice_date", None)
    obj.setdefault("net", None)
    obj.setdefault("vat_rate", None)
    obj.setdefault("reverse_charge_vat", None)
    obj.setdefault("reverse_charge_wording", False)
    obj["confidence"] = 0.95
    if faults and key % 31 == 0:
        obj["kind"] = "other"  # a plain miss on kind
    if faults and key % 37 == 0 and isinstance(obj.get("gross_amount"), (int, float)):
        obj["gross_amount"] = round(obj["gross_amount"] + 1.0, 2)  # a penny-plus miss
    return json.dumps(obj)


class _StubResponse:
    def __init__(self, text: str) -> None:
        self._text = text

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return {"message": {"content": self._text}}


_CASES_CACHE: list[Case] | None = None


def _cached_cases() -> list[Case]:
    global _CASES_CACHE
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
            if isinstance(content, str) and "SAMPLE" in content:
                text = content
        # the document sits between markers; recover the case whose full text the prompt contains
        # (full text: all statements start alike, so a prefix would collide)
        match = next((c for c in _cached_cases() if c.text.strip() in text), None)
        if match is None:
            return _StubResponse("no document recognised")
        return _StubResponse(_stub_payload(match.text))


# -------------------------------------------------------------------------------- run


async def run_case(case: Case, cfg: AiConfig) -> dict[str, Any]:
    t0 = time.perf_counter()
    row: dict[str, Any] = {"id": case.id, "kind": case.kind, "rate": case.rate}
    try:
        reading, _ = await cis_read_mod.read_cis_document(None, None, cfg, text=case.text)
    except ExtractionError as exc:
        row.update(
            outcome="refused",
            error=f"{type(exc).__name__}: {exc}"[:300],
            raw=(exc.raw or "")[:600] if getattr(exc, "raw", None) else None,
            elapsed_s=round(time.perf_counter() - t0, 3),
            fields={},
            checks_exact=False,
            checks_got=None,
        )
        return row
    # the gold `rate` is the CIS deduction rate on statements (0/20/30 -> status) but the VAT rate on
    # invoices (5/20: the status does not touch invoice checks, so it stays at the default)
    status = RATE_STATUS.get(case.rate, "net") if case.kind == "cis_statement" else "net"
    settings = cis_mod.CisSettings(status=status)  # type: ignore[arg-type]
    code_reading, problems = from_reading(reading, case.id, settings)
    failing = sorted(c.code for c in code_reading.checks if not c.ok)
    scores = score_fields(reading, case)
    row.update(
        outcome="ok",
        error=None,
        raw=None,
        elapsed_s=round(time.perf_counter() - t0, 3),
        confidence=reading.confidence,
        problems=problems,
        fields=scores,
        fields_correct=sum(scores.values()),
        fields_total=len(scores),
        checks_want=sorted(case.expect_fail),
        checks_got=failing,
        checks_exact=failing == sorted(case.expect_fail),
        all_exact=all(scores.values()) and failing == sorted(case.expect_fail),
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
    field_names: list[str] = []
    for r in ok:
        for f in r["fields"]:
            if f not in field_names:
                field_names.append(f)
    per_field = {}
    for f in field_names:
        scoped = [r for r in ok if f in r["fields"]]
        per_field[f] = {
            "scored": len(scoped),
            "correct": sum(1 for r in scoped if r["fields"][f]),
            "accuracy_pct": pct(sum(1 for r in scoped if r["fields"][f]), len(scoped)),
        }
    by_kind: dict[str, dict[str, Any]] = {}
    for kind in sorted({r["kind"] for r in rows}):
        sub = [r for r in rows if r["kind"] == kind]
        sub_ok = [r for r in sub if r["outcome"] == "ok"]
        exact = sum(1 for r in sub_ok if r.get("all_exact"))
        by_kind[kind] = {
            "docs": len(sub),
            "answered": len(sub_ok),
            "all_exact": exact,
            "accuracy_pct": pct(exact, len(sub)),  # a refusal counts as wrong: a person gets nothing
            "checks_exact_pct": pct(sum(1 for r in sub_ok if r.get("checks_exact")), len(sub_ok)),
        }
    misses = sorted(
        (r for r in ok if not r.get("all_exact")),
        key=lambda r: (sum(not v for v in r["fields"].values()) + (0 if r.get("checks_exact") else 1)),
        reverse=True,
    )
    lat = [r["elapsed_s"] for r in rows if r.get("elapsed_s") is not None]
    return {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": (cfg.model if cfg else None),
        "base_url": (cfg.base_url if cfg else None),
        "stub": stub,
        "docs": total,
        "answered": len(ok),
        "refusals": refused,
        "refusal_pct": pct(refused, total),
        "checks_exact_pct": pct(sum(1 for r in ok if r.get("checks_exact")), len(ok)),
        "all_exact_pct": pct(sum(1 for r in ok if r.get("all_exact")), total),
        "per_field": per_field,
        "by_kind": by_kind,
        "latency_s": {
            "mean": round(statistics.fmean(lat), 3) if lat else None,
            "p50": percentile(lat, 0.5),
            "p95": percentile(lat, 0.95),
            "max": round(max(lat), 3) if lat else None,
            "total": round(sum(lat), 1),
        },
        "worst": [
            {
                "id": r["id"],
                "kind": r["kind"],
                "wrong_fields": sorted(f for f, v in r["fields"].items() if not v),
                "checks_want": r["checks_want"],
                "checks_got": r["checks_got"],
                "problems": r["problems"],
            }
            for r in misses[:10]
        ],
    }


def report_md(s: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    L = s["latency_s"]
    stub_note = " (STUB: a fake model, numbers mean nothing)" if s["stub"] else ""
    out = [
        "# CIS reader eval",
        "",
        f"Model `{s['model']}` at `{s['base_url']}`{stub_note}; {s['generated']}. "
        "Code under test: `app.ai.cis_read.read_cis_document` + `app.cis_readings.from_reading` "
        "(the same prompt, schema and code-side checks production uses).",
        "",
        f"- Documents: **{s['docs']}** ({s['answered']} answered, **{s['refusals']} refusals**, {s['refusal_pct']}%)",
        f"- Fully exact (every field right and the failing checks exactly `expect_check_fail`): "
        f"**{s['all_exact_pct']}%** of all documents (a refusal counts as wrong)",
        f"- Checks exactly right: {s['checks_exact_pct']}% of answered documents",
        f"- Latency: mean {L['mean']} s, p50 {L['p50']} s, p95 {L['p95']} s, max {L['max']} s (total {L['total']} s)",
        "",
        "## Per-field accuracy (answered documents that have the field; refusals count as wrong nowhere here)",
        "",
        "| Field | Scored | Correct | Accuracy |",
        "|---|---:|---:|---:|",
        *(f"| {f} | {v['scored']} | {v['correct']} | {v['accuracy_pct']}% |" for f, v in s["per_field"].items()),
        "",
        "## Per-kind accuracy (refusals count as wrong)",
        "",
        "| Kind | Docs | Answered | Fully exact | Accuracy | Checks exact (of answered) |",
        "|---|---:|---:|---:|---:|---:|",
        *(
            f"| {k} | {v['docs']} | {v['answered']} | {v['all_exact']} | {v['accuracy_pct']}% | "
            f"{v['checks_exact_pct']}% |"
            for k, v in s["by_kind"].items()
        ),
        "",
        "## Worst 10 misses",
        "",
        "| Id | Kind | Wrong fields | Checks want -> got | Problems |",
        "|---|---|---|---|---|",
        *(
            f"| {w['id']} | {w['kind']} | {', '.join(w['wrong_fields']) or '(fields all right)'} | "
            f"{w['checks_want']} -> {w['checks_got']} | {'; '.join(w['problems'])[:80]} |"
            for w in s["worst"]
        ),
        "",
        "Refusals (the model gave nothing usable):",
        "",
        *(f"- {r['id']} ({r['kind']}): {r['error']}" for r in rows if r["outcome"] != "ok"),
        "",
        "How it is scored: names fuzzily (>= 0.8, as in `harness.run_extraction`), amounts within a penny, "
        "UTRs digits-only, VAT numbers normalised by `app.checks.normalise_vat_number`; on statements the CIS "
        "settings take the payment status from the gold `rate` (0/20/30% -> gross/net/unverified), on invoices "
        "the gold `rate` is the VAT rate.",
    ]
    return "\n".join(out) + "\n"


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


async def main_async(args: argparse.Namespace) -> dict[str, Any] | None:
    cases = load_cases()
    if args.limit:
        step = max(1, len(cases) // args.limit)  # spread over statements and invoices, not just the first kind
        cases = cases[::step][: args.limit]
    kinds = Counter(c.kind for c in cases)
    print(f"{len(cases)} documents {dict(kinds)}", flush=True)
    if args.dry_run:
        for c in cases[: args.show]:
            print(f"  {c.id} {c.kind} rate={c.rate} expect_fail={c.expect_fail}")
        print(json.dumps({k: len([c for c in cases if c.kind == k]) for k in kinds}, indent=1))
        return None

    out = Path(args.out) if args.out else OUT
    out.mkdir(parents=True, exist_ok=True)
    results = out / "results.jsonl"
    if args.fresh and results.exists():
        results.unlink()
    done = {r["id"] for r in read_results(results)}
    cfg = AiConfig.resolve(mode="local", base_url=args.base, model=args.model)
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
                mark = "ok " if row["outcome"] == "ok" and row.get("all_exact") else "MISS"
                print(f"[{i}/{len(cases)}] {mark} {row['elapsed_s']:.1f}s {case.id} -> {row.get('outcome')}", flush=True)
    finally:
        _httpx.AsyncClient = original  # type: ignore[assignment]
    wanted = {c.id for c in cases}
    rows = [r for r in read_results(results) if r["id"] in wanted]
    summary = summarise(rows, cfg, args.stub)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "report.md").write_text(report_md(summary, rows), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=_default_base(), help="Ollama base URL (default OLLAMA_URL or localhost:11434)")
    ap.add_argument("--model", default=DEFAULT_OLLAMA_MODEL)
    ap.add_argument("--limit", type=int, default=0, help="0 = every document; otherwise a spread sample of that size")
    ap.add_argument("--dry-run", action="store_true", help="build cases and expectations, call no model, write nothing")
    ap.add_argument("--stub", action="store_true", help="in-process fake model (tests the pipeline, not the model)")
    ap.add_argument("--fresh", action="store_true", help="ignore and replace an earlier results.jsonl")
    ap.add_argument("--show", type=int, default=15, help="--dry-run: how many cases to print")
    ap.add_argument("--out", default=None, help="default evals/runs/cis_read/")
    summary = asyncio.run(main_async(ap.parse_args()))
    if summary:
        print(json.dumps({k: summary[k] for k in ("docs", "answered", "all_exact_pct", "refusals", "latency_s")}))


if __name__ == "__main__":
    main()
