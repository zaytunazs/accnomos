"""Property documents eval: letting statements and bills through the property-specific reader.

    cd evals && python -m harness.property_docs --dry-run             # build the cases, call no model
    cd evals && python -m harness.property_docs --stub                # whole pipeline against an in-process fake model
    cd evals && python -m harness.property_docs                       # Glimmer on the Spark (Ollama :11434)

The code under test is ``app.ai.property_read.read_property_document`` (the same prompt, strict JSON schema and
validation production uses) followed by ``app.property_readings.from_reading`` (pounds to pence, the property
matched by code against the register, the lines checked against the printed totals in code). ``--stub`` fakes the
Ollama HTTP reply in-process: the real request path, prompt, response parsing and code checks run; only the bytes
from the model are canned.

Cases: every landlord in ``evals/gold/landlord/landlord_*/`` (six landlords, 18 documents each: 12 monthly
letting statements over two properties and 6 bills). ``expectations.json`` holds each document's kind, date,
property, lines and HMRC category figures; the reader sees only the ``statements/`` / ``bills/`` text file.

Scoring, per document
---------------------
* ``kind``: the model's document kind against the gold kind (letting_statement, insurance,
  mortgage_statement, invoice).
* ``property``: the property matched by code (address tokens against the register) against the gold property.
* per gold figure (``cat:<category>``, ``amt:<category>``): the category appears on a posted line (not an
  ``info`` headline and not repaid capital), and the category's lines add up to the figure within a penny.
  Statement fees and their VAT combine into the gold professional figure; a mortgage's capital never counts
  towards its finance figure.
* baseline: the same document through the generic extraction reader (``app.ai.extract.extract_document``,
  scored as before: category, property, amount, date) is kept as a ``baseline`` column: the report shows the
  new reader against it.

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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "services" / "runtime", REPO / "packages" / "ledger" / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from app import property as prop_mod  # noqa: E402
from app import property_readings as prop_read_mod  # noqa: E402
from app.ai import extract as extract_mod  # noqa: E402
from app.ai import property_read as property_read_mod  # noqa: E402
from app.ai.config import DEFAULT_OLLAMA_BASE, DEFAULT_OLLAMA_MODEL, AiConfig  # noqa: E402
from app.ai.extract import ExtractionError  # noqa: E402

GOLD = REPO / "evals" / "gold" / "landlord"
OUT = REPO / "evals" / "runs" / "property_docs"


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
    lines: list[tuple[str, int]] = field(default_factory=list)  # gold labels and pence, as printed
    figures: list[tuple[str, int]] = field(default_factory=list)  # gold (category, pence)

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
    """The document's headline total in pence (the generic baseline's rule, kept for that column)."""
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


# Gold HMRC figure category -> defensible generic-reader categories (the baseline column only).
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

BASELINE_FIELDS = ("category", "property", "amount", "date")


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
                    lines=[(str(label), int(pence)) for label, pence in doc["lines"]],
                    figures=[(str(f["category"]), int(f["pence"])) for f in doc.get("figures", [])],
                )
            )
    ids = [c.id for c in out]
    assert len(set(ids)) == len(ids), "duplicate case ids"
    return out


def _invoice_categories(doc: dict[str, Any]) -> set[str]:
    cats: set[str] = set()
    for fig in doc.get("figures", []):
        cats |= INVOICE_CATEGORIES.get(fig.get("category", ""), {"Sundry"})
    return cats or {"Sundry"}


def landlord_properties(landlord: str) -> list[prop_mod.Property]:
    """The register the code matches against: the gold landlord's two properties (ids flat/house)."""
    names = json.loads((GOLD / landlord / "names.json").read_text(encoding="utf-8"))
    out = []
    for key in ("flat", "house"):
        info = names.get(key, {})
        out.append(
            prop_mod.Property(
                id=key,
                name=f"The {key}",
                address=str(info.get("address", "")),
                postcode=str(info.get("postcode", "")),
                created_at="2026-01-01T00:00:00",
            )
        )
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


def _stub_lines(case: Case) -> list[dict[str, Any]]:
    """The gold lines in the new reader's shape: keyword categories, headlines marked info, capital flagged."""
    single = case.figures[0][0] if len(case.figures) == 1 else None
    out: list[dict[str, Any]] = []
    for label, pence in case.lines:
        low = label.strip().lower()
        amount = round(pence / 100, 2)
        if case.kind == "letting_statement":
            if low.startswith("paid to"):
                out.append({"description": label, "category": "rents", "amount": amount, "info": True})
            elif low.startswith("rent"):
                out.append({"description": label, "category": "rents", "amount": amount})
            else:
                out.append({"description": label, "category": "professional", "amount": amount})
        elif case.kind == "mortgage_statement":
            if "capital" in low:
                out.append({"description": label, "category": "finance_res", "amount": amount, "capital": True})
            elif "interest" in low:
                out.append({"description": label, "category": "finance_res", "amount": amount})
            else:
                out.append({"description": label, "category": "finance_res", "amount": amount, "info": True})
        elif case.kind == "insurance":
            out.append({"description": label, "category": "premises", "amount": amount, "info": "of which" in low})
        elif low == "total":
            out.append({"description": label, "category": single or "other", "amount": amount, "info": True})
        else:
            out.append({"description": label, "category": single or "other", "amount": amount})
    for line in out:
        line.setdefault("vat", None)
        line.setdefault("capital", False)
        line.setdefault("info", False)
        line.setdefault("replacement", "like for like" in case.title.lower())
    return out


def _stub_total(case: Case) -> float:
    lines = [(str(label), int(pence)) for label, pence in case.lines]
    if case.kind == "letting_statement":
        for label, pence in lines:
            if label.strip().lower().startswith("paid to landlord"):
                return round(abs(pence) / 100, 2)
    for label, pence in lines:
        if label.strip().lower() == "total":
            return round(pence / 100, 2)
    if case.kind == "mortgage_statement":
        return round(sum(p for _, p in lines if "of which" not in _.lower()) / 100, 2)
    if case.kind == "insurance":
        return round(sum(p for _, p in lines if "of which" not in _.lower()) / 100, 2)
    return round(sum(p for _, p in lines if p > 0) / 100, 2)


def _stub_payload(case: Case, faults: bool = True) -> str:
    """A fake Ollama reply for the document: the gold figures, with deterministic faults."""
    key = sum(ord(ch) for ch in case.text)
    if faults and key % 29 == 0:
        return "Here is the extraction: some text without JSON"  # invalid JSON
    lines = _stub_lines(case)
    total = _stub_total(case)
    if faults and key % 31 == 0 and lines:  # a plain miss on one line's category
        first = next((ln for ln in lines if not ln["info"] and not ln["capital"]), lines[0])
        first["category"] = next(c for c in ("rents", "other", "premises") if c != first["category"])
    if faults and key % 37 == 0 and lines:  # a pound-plus miss on the headline total and one line
        first = next((ln for ln in lines if not ln["info"] and not ln["capital"]), lines[0])
        first["amount"] = round(float(first["amount"]) + 1.0, 2)
        total = round(total + 1.0, 2)
    names = json.loads((GOLD / case.landlord / "names.json").read_text(encoding="utf-8"))
    info = names.get(case.property, {})
    address = f"{info.get('address', '')}, {info.get('town', '')} {info.get('postcode', '')}".strip(" ,")
    return json.dumps(
        {
            "kind": case.kind,
            "date": case.date,
            "period_start": None,
            "period_end": None,
            "counterparty": _counterparty(GOLD / case.landlord / "names.json", case),
            "property_text": f"{case.title}, {address}",
            "lines": lines,
            "total": total,
            "confidence": 0.9,
        }
    )


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
        props = (payload.get("format") or {}).get("properties", {})
        if "property_text" in props:
            return _StubResponse(_stub_payload(match))
        return _StubResponse(_stub_generic_payload(match))


def _stub_generic_payload(case: Case, faults: bool = True) -> str:
    """The baseline column's fake reply: the old generic-reader shape, with deterministic faults."""
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


def score_figures(
    code_reading: prop_read_mod.Reading, figures: list[tuple[str, int]]
) -> tuple[dict[str, bool], dict[str, Any], dict[str, Any]]:
    """Per gold figure: the category is on a posted line, and its lines add up to the figure."""
    fields: dict[str, bool] = {}
    got: dict[str, Any] = {}
    want: dict[str, Any] = {}
    for category, pence in figures:
        posted = [ln for ln in code_reading.lines if ln.category == category and not ln.info and not ln.capital]
        total = sum(ln.amount_pence for ln in posted)
        fields[f"cat:{category}"] = bool(posted)
        fields[f"amt:{category}"] = abs(abs(total) - pence) <= 1
        got[category] = round(total / 100, 2)
        want[category] = round(pence / 100, 2)
    return fields, got, want


async def run_baseline(case: Case, cfg: AiConfig) -> dict[str, Any]:
    """The same document through the generic extraction reader, kept as the baseline column."""
    try:
        doc, _ = await extract_mod.extract_document(None, None, cfg, text=case.text)
    except ExtractionError:
        return {"outcome": "refused", "fields": {}, "all_exact": False}
    blob = doc.model_dump_json().lower()
    fields = {
        "category": doc.category_guess in case.categories,
        "property": any(tok in blob for tok in case.tokens),
        "amount": _money_eq(doc.gross_total, case.amount_pence),
        "date": doc.date == case.date,
    }
    return {"outcome": "ok", "fields": fields, "all_exact": all(fields.values())}


async def run_case(case: Case, cfg: AiConfig) -> dict[str, Any]:
    t0 = time.perf_counter()
    row: dict[str, Any] = {"id": case.id, "landlord": case.landlord, "kind": case.kind, "title": case.title}
    baseline = await run_baseline(case, cfg)
    row["baseline"] = baseline
    try:
        reading, _ = await property_read_mod.read_property_document(None, None, cfg, text=case.text)
    except ExtractionError as exc:
        row.update(
            outcome="refused",
            error=f"{type(exc).__name__}: {exc}"[:300],
            raw=(exc.raw or "")[:600] if getattr(exc, "raw", None) else None,
            elapsed_s=round(time.perf_counter() - t0, 3),
            fields={},
            figures_got={},
            figures_want={c: round(p / 100, 2) for c, p in case.figures},
        )
        return row
    code_reading, problems = prop_read_mod.from_reading(reading, landlord_properties(case.landlord), case.id)
    fields = {"kind": reading.kind == case.kind, "property": code_reading.property_id == case.property}
    fig_fields, got, want = score_figures(code_reading, case.figures)
    fields.update(fig_fields)
    row.update(
        outcome="ok",
        error=None,
        raw=None,
        elapsed_s=round(time.perf_counter() - t0, 3),
        confidence=reading.confidence,
        problems=problems,
        checks={c.code: c.ok for c in code_reading.checks},
        fields=fields,
        figures_got=got,
        figures_want=want,
        property_got=code_reading.property_id,
        all_exact=all(fields.values()),
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
        "kind": {
            "scored": len(ok),
            "correct": sum(1 for r in ok if r["fields"].get("kind")),
            "accuracy_pct": pct(sum(1 for r in ok if r["fields"].get("kind")), len(ok)),
        },
        "property": {
            "scored": len(ok),
            "correct": sum(1 for r in ok if r["fields"].get("property")),
            "accuracy_pct": pct(sum(1 for r in ok if r["fields"].get("property")), len(ok)),
        },
    }
    line_cats = [(r, k) for r in ok for k in r["fields"] if k.startswith("cat:")]
    line_amts = [(r, k) for r in ok for k in r["fields"] if k.startswith("amt:")]
    per_field["line_category"] = {
        "scored": len(line_cats),
        "correct": sum(1 for r, k in line_cats if r["fields"][k]),
        "accuracy_pct": pct(sum(1 for r, k in line_cats if r["fields"][k]), len(line_cats)),
    }
    per_field["line_amount"] = {
        "scored": len(line_amts),
        "correct": sum(1 for r, k in line_amts if r["fields"][k]),
        "accuracy_pct": pct(sum(1 for r, k in line_amts if r["fields"][k]), len(line_amts)),
    }
    by_kind: dict[str, dict[str, Any]] = {}
    for kind in sorted({r["kind"] for r in rows}):
        sub = [r for r in rows if r["kind"] == kind]
        sub_ok = [r for r in sub if r["outcome"] == "ok"]
        exact = sum(1 for r in sub_ok if r.get("all_exact"))
        base_ok = [r for r in sub if r.get("baseline", {}).get("outcome") == "ok"]
        base_exact = sum(1 for r in base_ok if r["baseline"].get("all_exact"))
        by_kind[kind] = {
            "docs": len(sub),
            "answered": len(sub_ok),
            "all_exact": exact,
            "accuracy_pct": pct(exact, len(sub)),  # a refusal counts as wrong: a person gets nothing
            "baseline_exact": base_exact,
            "baseline_pct": pct(base_exact, len(sub)),
        }
    base_ok_all = [r for r in rows if r.get("baseline", {}).get("outcome") == "ok"]
    baseline = {
        "reader": "generic",
        "answered": len(base_ok_all),
        "all_exact": sum(1 for r in base_ok_all if r["baseline"].get("all_exact")),
        "all_exact_pct": pct(sum(1 for r in base_ok_all if r["baseline"].get("all_exact")), total),
        "per_field": {
            f: {
                "scored": len(base_ok_all),
                "correct": sum(1 for r in base_ok_all if r["baseline"]["fields"].get(f)),
                "accuracy_pct": pct(sum(1 for r in base_ok_all if r["baseline"]["fields"].get(f)), len(base_ok_all)),
            }
            for f in BASELINE_FIELDS
        },
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
        "reader": "property",
        "docs": total,
        "answered": len(ok),
        "refusals": refused,
        "refusal_pct": pct(refused, total),
        "all_exact_pct": pct(sum(1 for r in ok if r.get("all_exact")), total),
        "per_field": per_field,
        "by_kind": by_kind,
        "baseline": baseline,
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
                "got": {"figures": r["figures_got"], "property": r.get("property_got")},
                "want": {
                    "figures": r["figures_want"],
                    "property": next(c.property for c in _cached_cases() if c.id == r["id"]),
                },
            }
            for r in misses[:10]
        ],
    }


def report_md(s: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    L = s["latency_s"]
    b = s["baseline"]
    stub_note = " (STUB: a fake model, numbers mean nothing)" if s["stub"] else ""
    out = [
        "# Property documents eval",
        "",
        f"Model `{s['model']}` at `{s['base_url']}`{stub_note}; {s['generated']}. "
        "Code under test: `app.ai.property_read.read_property_document` + "
        "`app.property_readings.from_reading` (pounds to pence, the property matched by code, the lines checked "
        "against the printed totals). The generic extraction reader runs on every document as a baseline column.",
        "",
        f"- Documents: **{s['docs']}** ({s['answered']} answered, **{s['refusals']} refusals**, {s['refusal_pct']}%)",
        f"- Fully exact (kind, property and every line's category and amount right): **{s['all_exact_pct']}%** of "
        "all documents (a refusal counts as wrong); generic baseline **"
        f"{b['all_exact_pct']}%**",
        f"- Latency: mean {L['mean']} s, p50 {L['p50']} s, p95 {L['p95']} s, max {L['max']} s (total {L['total']} s)",
        "",
        "## Per-field accuracy (answered documents; line fields score every gold figure)",
        "",
        "| Field | Scored | Correct | Accuracy |",
        "|---|---:|---:|---:|",
        *(f"| {f} | {v['scored']} | {v['correct']} | {v['accuracy_pct']}% |" for f, v in s["per_field"].items()),
        "",
        "## Per-kind accuracy (refusals count as wrong; baseline is the generic reader's fully-exact share)",
        "",
        "| Kind | Docs | Answered | Fully exact | Accuracy | Baseline exact | Baseline |",
        "|---|---:|---:|---:|---:|---:|---:|",
        *(
            f"| {k} | {v['docs']} | {v['answered']} | {v['all_exact']} | {v['accuracy_pct']}% | "
            f"{v['baseline_exact']} | {v['baseline_pct']}% |"
            for k, v in s["by_kind"].items()
        ),
        "",
        "## Generic baseline per field (answered baseline documents)",
        "",
        "| Field | Scored | Correct | Accuracy |",
        "|---|---:|---:|---:|",
        *(f"| {f} | {v['scored']} | {v['correct']} | {v['accuracy_pct']}% |" for f, v in b["per_field"].items()),
        "",
        "## Worst 10 misses",
        "",
        "| Id | Kind | Wrong fields | Got | Want |",
        "|---|---|---|---|---|",
        *(
            f"| {w['id']} | {w['kind']} | {', '.join(w['wrong_fields'])} | "
            f"figures={w['got']['figures']} property={w['got']['property']} | "
            f"figures={w['want']['figures']} property={w['want']['property']} |"
            for w in s["worst"]
        ),
        "",
        "Refusals (the model gave nothing usable):",
        "",
        *(f"- {r['id']} ({r['kind']}): {r['error']}" for r in rows if r["outcome"] != "ok"),
        "",
        "How it is scored: kind against the gold kind; property by the code match against the two registered "
        "properties (never an invented id); each gold figure by its category on a posted line (headlines and "
        "repaid capital excluded) adding up within a penny. The baseline runs the generic reader with its old "
        "rules: category against defensible generic categories, property by address tokens anywhere in its JSON, "
        "amount within a penny of the headline total, date exactly.",
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
            figs = ", ".join(f"{cat} {pence / 100:.2f}" for cat, pence in c.figures)
            print(f"  {c.id} {c.kind} {c.date} {c.property} [{figs}]")
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
        print(json.dumps({"baseline": summary["baseline"]}))


if __name__ == "__main__":
    main()
