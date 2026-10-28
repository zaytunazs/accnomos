"""Property documents eval: landlord letting statements and bills through the generic extraction reader.

    cd evals && python -m harness.property_docs --dry-run             # build the cases, call no model
    cd evals && python -m harness.property_docs --stub                # whole pipeline against an in-process fake model
    cd evals && python -m harness.property_docs                       # Glimmer on the Spark (Ollama :11434)

There is no property-specific reader in the app: ``services/runtime/app/property.py`` works out every
figure in code from approved entries, and nothing in ``app/ai/`` reads letting paperwork. So this harness
scores the existing generic extraction reader (``app.ai.extract.extract_document``: the same prompt, strict
JSON schema and validation the Inbox uses) on the gold landlord documents, and says so in the report. The
day a dedicated property reader lands, this harness is where it plugs in.

Cases: every landlord in ``evals/gold/landlord/landlord_*/`` (six landlords, 18 documents each: 12 monthly
letting statements over two properties and 6 bills). ``expectations.json`` holds each document's kind, date,
property, lines and HMRC category figures; the reader sees only the ``statements/`` / ``bills/`` text file.

Scoring, per document
---------------------
* ``category``: the model's single ``category_guess`` against a harness-chosen set of defensible generic
  categories (letting statements -> Sales; insurance -> Insurance; mortgage statements -> Bank charges or
  Sundry, the generic list has no interest category; invoices follow their gold HMRC figure: repairs ->
  Tools & small equipment / Materials, gas safety -> Sundry, replacement domestic items -> Tools & small
  equipment / Sundry, ground rent and service charge -> Rent).
* ``property``: the expected property's address tokens (street and postcode from ``names.json``) found in
  the model's JSON. The generic schema has no property field, so this measures whether the address
  survives the reading at all.
* ``amount``: the model's ``gross_total`` within a penny of the document's headline total: statements ->
  the "Paid to landlord" payout; bills -> the "Total" line when one is printed, the largest line when an
  "of which" breakdown is printed (premium including IPT, payments made including capital), else the sum
  of the positive lines.
* ``date``: the model's date against the gold date.

Writes ``evals/runs/property_docs/{results.jsonl, summary.json, report.md}``. Resumable: ids already in
results.jsonl are skipped (``--fresh`` starts again). One request at a time, so the production runtime on
the same machine keeps priority.
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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "services" / "runtime", REPO / "packages" / "ledger" / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from app.ai import extract as extract_mod  # noqa: E402
from app.ai.config import DEFAULT_OLLAMA_BASE, DEFAULT_OLLAMA_MODEL, AiConfig  # noqa: E402
from app.ai.extract import ExtractionError  # noqa: E402

GOLD = REPO / "evals" / "gold" / "landlord"
OUT = REPO / "evals" / "runs" / "property_docs"

NO_PROPERTY_READER = (
    "There is no property-specific reader in the app (`services/runtime/app/property.py` works out every "
    "figure in code from approved entries; nothing in `app/ai/` reads letting paperwork). This eval scores "
    "the existing generic extraction reader (`app.ai.extract.extract_document`) on the landlord documents: "
    "category, property, amount and date, as below."
)

# Gold HMRC figure category -> defensible generic-reader categories.
INVOICE_CATEGORIES: dict[str, set[str]] = {
    "repairs": {"Tools & small equipment", "Materials"},
    "other": {"Sundry"},
    "domestic_items": {"Tools & small equipment", "Sundry"},
    "premises": {"Rent"},
}
KIND_CATEGORIES: dict[str, set[str]] = {
    "letting_statement": {"Sales"},
    "insurance": {"Insurance"},
    "mortgage_statement": {"Bank charges", "Sundry"},
}

FIELDS = ("category", "property", "amount", "date")


@dataclass
class Case:
    """One gold landlord document with its expectation."""

    id: str
    landlord: str
    kind: str
    title: str
    text: str
    date: str
    property: str
    tokens: set[str]
    categories: set[str]
    amount_pence: int

    @property
    def primary_category(self) -> str:
        return sorted(self.categories)[0]


def _tokens(names: dict[str, Any], prop: str) -> set[str]:
    out = set()
    for part in (names.get(prop, {}).get("address", ""), names.get(prop, {}).get("postcode", "")):
        for tok in re.split(r"[^a-z0-9]+", str(part).lower()):
            if len(tok) > 2 and tok not in {"the", "flat", "house"}:
                out.add(tok)
    squashed = re.sub(r"[^a-z0-9]", "", str(names.get(prop, {}).get("postcode", "")).lower())
    if squashed:
        out.add(squashed)
    return out


def _expected_total(doc: dict[str, Any]) -> int:
    """The document's headline total in pence (see the module docstring for the rule)."""
    lines = [(str(label), int(pence)) for label, pence in doc["lines"]]
    if doc["kind"] == "letting_statement":
        for label, pence in lines:
            if label.strip().lower().startswith("paid to landlord"):
                return abs(pence)
        return abs(min(pence for _, pence in lines))
    for label, pence in lines:
        if label.strip().lower() == "total":
            return pence
    if any("of which" in label.lower() for label, _ in lines):
        return max(pence for _, pence in lines)
    return sum(pence for _, pence in lines if pence > 0)


def _invoice_categories(doc: dict[str, Any]) -> set[str]:
    cats: set[str] = set()
    for fig in doc.get("figures", []):
        cats |= INVOICE_CATEGORIES.get(fig.get("category", ""), {"Sundry"})
    return cats or {"Sundry"}


def _bill_files(bills: Path) -> dict[str, Path]:
    """Bill text files by ISO date (parsed from the printed `Date: DD/MM/YYYY`)."""
    out = {}
    for p in sorted(bills.glob("*.txt")):
        m = re.search(r"Date:\s*(\d{2})/(\d{2})/(\d{4})", p.read_text(encoding="utf-8"))
        if m:
            out[f"{m.group(3)}-{m.group(2)}-{m.group(1)}"] = p
    return out


def load_cases() -> list[Case]:
    out: list[Case] = []
    for landlord in sorted(GOLD.iterdir()):
        if not landlord.is_dir():
            continue
        exp = json.loads((landlord / "expectations.json").read_text(encoding="utf-8"))
        names = json.loads((landlord / "names.json").read_text(encoding="utf-8"))
        bills = _bill_files(landlord / "bills")
        for doc in exp["documents"]:
            prop = doc["property"]
            if doc["kind"] == "letting_statement":
                path = landlord / "statements" / f"{doc['date'][:7]}_{prop}.txt"
            else:
                path = bills[doc["date"]]
            categories = _invoice_categories(doc) if doc["kind"] == "invoice" else set(KIND_CATEGORIES[doc["kind"]])
            out.append(
                Case(
                    id=f"{landlord.name}/{path.stem}",
                    landlord=landlord.name,
                    kind=doc["kind"],
                    title=doc["title"],
                    text=path.read_text(encoding="utf-8"),
                    date=doc["date"],
                    property=prop,
                    tokens=_tokens(names, prop),
                    categories=categories,
                    amount_pence=_expected_total(doc),
                )
            )
    ids = [c.id for c in out]
    assert len(set(ids)) == len(ids), "duplicate case ids"
    return out


# -------------------------------------------------------------------------------- stub model


def _counterparty(names_path: Path, case: Case) -> str:
    names = json.loads(names_path.read_text(encoding="utf-8"))
    if case.kind == "letting_statement":
        return str(names["people"]["agent"])
    title = case.title.lower()
    if "gas safety" in title or "cp12" in title:
        return str(names["people"]["gas"])
    if "boiler" in title:
        return str(names["people"]["plumber"])
    if "washing machine" in title:
        return str(names["people"]["appliances"])
    if "ground rent" in title or "service charge" in title:
        return str(names["people"]["block"])
    if case.kind == "insurance":
        return str(names["people"]["insurer"])
    return str(names["people"]["lender"])


def _stub_payload(case: Case, faults: bool = True) -> str:
    """A fake Ollama reply for the document: the gold figures, with deterministic faults."""
    key = sum(ord(ch) for ch in case.text)
    if faults and key % 29 == 0:
        return "Here is the extraction: some text without JSON"  # invalid JSON
    landlord = case.landlord
    names = json.loads((GOLD / landlord / "names.json").read_text(encoding="utf-8"))
    total = case.amount_pence / 100
    category = case.primary_category
    if faults and key % 31 == 0:  # a plain miss on category
        category = next(c for c in ("Sundry", "Sales", "Rent") if c not in case.categories)
    if faults and key % 37 == 0:  # a pound-plus miss on the amount
        total = round(total + 1.0, 2)
    address = names.get(case.property, {}).get("address", "")
    obj = {
        "doc_type": "sales_invoice" if case.kind == "letting_statement" else "purchase_invoice",
        "supplier_name": _counterparty(GOLD / landlord / "names.json", case),
        "supplier_vat_number": None,
        "customer_name": names["people"]["landlord"],
        "invoice_number": None,
        "original_invoice_number": None,
        "date": case.date,
        "currency": "GBP",
        "lines": [
            {
                "description": f"{case.title} ({address})",
                "qty": 1.0,
                "unit_price": total,
                "net": total,
                "vat_rate": 0.0,
                "vat": 0.0,
            }
        ],
        "net_total": total,
        "vat_total": 0.0,
        "gross_total": total,
        "payment_method": "unknown",
        "card_last4": None,
        "category_guess": category,
        "confidence": 0.9,
    }
    return json.dumps(obj)


class _StubResponse:
    def __init__(self, text: str) -> None:
        self._text = text

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return {"message": {"content": self._text}}


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
        match = next((c for c in _cached_cases() if c.text.strip() in text), None)
        if match is None:
            return _StubResponse("no document recognised")
        return _StubResponse(_stub_payload(match))


_CASES_CACHE: list[Case] | None = None


def _cached_cases() -> list[Case]:
    global _CASES_CACHE
    if _CASES_CACHE is None:
        _CASES_CACHE = load_cases()
    return _CASES_CACHE


# -------------------------------------------------------------------------------- run


def _money_eq(pounds: Any, pence: int) -> bool:
    try:
        return pounds is not None and abs(round(float(pounds) * 100) - pence) <= 1
    except (TypeError, ValueError):
        return False


async def run_case(case: Case, cfg: AiConfig) -> dict[str, Any]:
    t0 = time.perf_counter()
    row: dict[str, Any] = {"id": case.id, "landlord": case.landlord, "kind": case.kind, "title": case.title}
    try:
        doc, _ = await extract_mod.extract_document(None, None, cfg, text=case.text)
    except ExtractionError as exc:
        row.update(
            outcome="refused",
            error=f"{type(exc).__name__}: {exc}"[:300],
            raw=(exc.raw or "")[:600] if getattr(exc, "raw", None) else None,
            elapsed_s=round(time.perf_counter() - t0, 3),
            fields={},
        )
        return row
    blob = doc.model_dump_json().lower()
    scores = {
        "category": doc.category_guess in case.categories,
        "property": any(tok in blob for tok in case.tokens),
        "amount": _money_eq(doc.gross_total, case.amount_pence),
        "date": doc.date == case.date,
    }
    row.update(
        outcome="ok",
        error=None,
        raw=None,
        elapsed_s=round(time.perf_counter() - t0, 3),
        confidence=doc.confidence,
        fields=scores,
        got={
            "category": doc.category_guess,
            "amount": doc.gross_total,
            "date": doc.date,
        },
        want={
            "category": sorted(case.categories),
            "amount": case.amount_pence / 100,
            "date": case.date,
            "property": case.property,
        },
        all_exact=all(scores.values()),
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
    per_field = {
        f: {
            "scored": len(ok),
            "correct": sum(1 for r in ok if r["fields"][f]),
            "accuracy_pct": pct(sum(1 for r in ok if r["fields"][f]), len(ok)),
        }
        for f in FIELDS
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
        }
    misses = sorted(
        (r for r in ok if not r.get("all_exact")),
        key=lambda r: sum(not v for v in r["fields"].values()),
        reverse=True,
    )
    lat = [r["elapsed_s"] for r in rows if r.get("elapsed_s") is not None]
    return {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": (cfg.model if cfg else None),
        "base_url": (cfg.base_url if cfg else None),
        "stub": stub,
        "reader": "generic",
        "docs": total,
        "answered": len(ok),
        "refusals": refused,
        "refusal_pct": pct(refused, total),
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
                "got": r["got"],
                "want": r["want"],
            }
            for r in misses[:10]
        ],
    }


def report_md(s: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    L = s["latency_s"]
    stub_note = " (STUB: a fake model, numbers mean nothing)" if s["stub"] else ""
    out = [
        "# Property documents eval",
        "",
        f"Model `{s['model']}` at `{s['base_url']}`{stub_note}; {s['generated']}. "
        "Code under test: `app.ai.extract.extract_document` (the generic reader).",
        "",
        NO_PROPERTY_READER,
        "",
        f"- Documents: **{s['docs']}** ({s['answered']} answered, **{s['refusals']} refusals**, {s['refusal_pct']}%)",
        f"- Fully exact (category, property, amount and date all right): **{s['all_exact_pct']}%** of all "
        "documents (a refusal counts as wrong)",
        f"- Latency: mean {L['mean']} s, p50 {L['p50']} s, p95 {L['p95']} s, max {L['max']} s (total {L['total']} s)",
        "",
        "## Per-field accuracy (answered documents)",
        "",
        "| Field | Scored | Correct | Accuracy |",
        "|---|---:|---:|---:|",
        *(f"| {f} | {v['scored']} | {v['correct']} | {v['accuracy_pct']}% |" for f, v in s["per_field"].items()),
        "",
        "## Per-kind accuracy (refusals count as wrong)",
        "",
        "| Kind | Docs | Answered | Fully exact | Accuracy |",
        "|---|---:|---:|---:|---:|",
        *(
            f"| {k} | {v['docs']} | {v['answered']} | {v['all_exact']} | {v['accuracy_pct']}% |"
            for k, v in s["by_kind"].items()
        ),
        "",
        "## Worst 10 misses",
        "",
        "| Id | Kind | Wrong fields | Got | Want |",
        "|---|---|---|---|---|",
        *(
            f"| {w['id']} | {w['kind']} | {', '.join(w['wrong_fields'])} | "
            f"category={w['got']['category']} amount={w['got']['amount']} date={w['got']['date']} | "
            f"category in {w['want']['category']} amount={w['want']['amount']} date={w['want']['date']} "
            f"property={w['want']['property']} |"
            for w in s["worst"]
        ),
        "",
        "Refusals (the model gave nothing usable):",
        "",
        *(f"- {r['id']} ({r['kind']}): {r['error']}" for r in rows if r["outcome"] != "ok"),
        "",
        "How it is scored: category against harness-chosen defensible generic categories (the generic schema "
        "has no landlord categories); property by the expected address tokens surviving anywhere in the model's "
        "JSON (the schema has no property field); amount within a penny of the headline total (payout for "
        "statements; printed Total, largest `of which` line, or sum of positives for bills); date exactly.",
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
        step = max(1, len(cases) // args.limit)  # spread over landlords and kinds, not just the first folder
        cases = cases[::step][: args.limit]
    by_kind = Counter(c.kind for c in cases)
    print(f"{len(cases)} documents {dict(by_kind)}", flush=True)
    if args.dry_run:
        for c in cases[: args.show]:
            print(f"  {c.id} {c.kind} {c.date} {sorted(c.categories)} {c.amount_pence / 100:.2f}")
        print(json.dumps({k: len([c for c in cases if c.kind == k]) for k in by_kind}, indent=1))
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
                print(
                    f"[{i}/{len(cases)}] {mark} {row['elapsed_s']:.1f}s {case.id} -> {row.get('outcome')}",
                    flush=True,
                )
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
    ap.add_argument("--out", default=None, help="default evals/runs/property_docs/")
    summary = asyncio.run(main_async(ap.parse_args()))
    if summary:
        print(json.dumps({k: summary[k] for k in ("docs", "answered", "all_exact_pct", "refusals", "latency_s")}))


if __name__ == "__main__":
    main()
