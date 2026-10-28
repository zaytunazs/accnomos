"""Bank-rule AI coding eval: every gold bank line through the real `suggest_ai` with a local model.

    cd evals && python -m harness.bank_ai --dry-run                  # build the lines + expectations, no model
    cd evals && python -m harness.bank_ai --stub                     # whole pipeline against an in-process fake model
    cd evals && python -m harness.bank_ai                            # Glimmer on the Spark (Ollama :11434)
    cd evals && python -m harness.bank_ai --base http://127.0.0.1:11434 --model muse-glimmer:30b --limit 20

The code under test is ``app.bank_reconcile.suggest_ai`` (the same prompt, JSON schema, parsing and the account /
VAT-code validation the Reconcile tab uses), called with the account list the runtime builds
(``CATEGORY_ACCOUNTS`` values plus Sundry). Only ``app.ai.ask.call_json_model`` is wrapped, to time each call and keep
the raw reply so a ``None`` from ``suggest_ai`` can be told apart: transport error, invalid JSON, wrong shape, an
account outside the list, or a VAT code outside S/R/Z/E/O/N.

Lines
-----
* ``evals/gold/bank/*.csv``: the hand-written October statements and the six two-month statements (Barclays, Starling,
  Tide, Monzo layouts), parsed by the real importer (``accnomos_ledger.bank.parse_bank_csv``).
* ``evals/gold/ledger2/bank_pairs/*_a.csv`` and ``*_b.csv``: Qwen-written statements; the re-export overlap is dropped
  by line id, so each line is asked once.

Expectation (derived by code, never by hand per line)
-----------------------------------------------------
1. Two-month statements: ``gold/bank/expected_matches.json`` says which gold document each row pays. A purchase
   document's ``gold_case`` gives the category the runtime's own extraction uses (the ``CATEGORY`` table of
   ``harness.bank_match``); a utility whose ``category_hint`` mentions phone / mobile / broadband / landline is
   Telephone & internet. Rows with no document use their ``kind``: insurance, rent and bank fee have an account;
   tax, payroll, drawings, transfer and income do not.
2. Everything else (hand-written statements, ledger2 pairs): an ordered keyword table on the description
   (``KEYWORDS``): fuel brands, merchants, telecoms, fees, HMRC.
3. Several lines have more than one defensible account (a hardware merchant is Materials or Tools). The expectation is
   a *set*; the line is right if the model's account is in it. ``primary`` is the first entry and is also reported.
4. Lines with no expense account on the runtime's list (money in, HMRC, payroll, drawings, transfers, sales-side
   documents) are **unscored**: the model is still asked, and its behaviour is reported, but they do not enter accuracy.

Writes ``evals/runs/bank_ai/{results.jsonl, summary.json, report.md}``. Resumable: lines already in results.jsonl are
skipped (``--fresh`` starts again). One request at a time, so the production runtime on the same machine keeps priority.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "services" / "runtime", REPO / "packages" / "ledger" / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from accnomos_ledger.bank import BankLine, parse_bank_csv  # noqa: E402
from app import bank_reconcile  # noqa: E402
from app.ai import ask as ask_mod  # noqa: E402
from app.ai.config import DEFAULT_OLLAMA_BASE, DEFAULT_OLLAMA_MODEL, AiConfig  # noqa: E402
from app.ai.extract import parse_model_json  # noqa: E402
from app.journal import CATEGORY_ACCOUNTS, SUNDRY  # noqa: E402
from harness.bank_match import CATEGORY  # noqa: E402

GOLD = REPO / "evals" / "gold"
OUT = REPO / "evals" / "runs" / "bank_ai"
ACCOUNTS = sorted(set(CATEGORY_ACCOUNTS.values()) | {SUNDRY})
VALID_VAT = {"S", "R", "Z", "E", "O", "N"}
PHONE_HINT = re.compile(r"phone|mobile|broadband|landline|internet|telecom|sim\b", re.IGNORECASE)

# Ordered: the first pattern that matches the (upper-cased) description decides. A category of None means "no expense
# account on the list" (unscored); a tuple lists the defensible categories, the first being the primary.
KEYWORDS: list[tuple[str, tuple[str, ...] | None]] = [
    (r"\bHMRC\b|\bVAT PAYMENT\b|\bPAYE\b|\bNIC\b|\bCORPORATION TAX\b", None),
    (r"\bTO SAVINGS\b|\bSAVINGS\b|\bPOT\b|\bTFR\b|\bTRANSFER\b|\bDRAWINGS\b|\bWAGES\b|\bPAYROLL\b|\bSALARY\b", None),
    (
        r"INV[- ]?\d|\bFTR PAYMENT RECEIVED\b|\bFURTHER PAYMENT\b|\bFPT IN\b|\bFPA RECEIPT\b|FSTER PAYMT IN|"
        r"\bRECEIVED\b",
        None,
    ),
    (r"\bFEE\b|\bFEES\b|\bCHARGE\b|\bCHARGES\b|\bSORTING FEE\b|\bOVERDRAFT\b|\bINTEREST\b", ("Bank charges",)),
    (r"\bINSURANCE\b", ("Insurance",)),
    (r"\bRENT\b|\bLETTINGS\b", ("Rent",)),
    (r"BROADBAND|MOBILE|PHONE|VODAFONE|\bBT\b|\bEE LIMITED\b|\bSKY\b|\bO2\b|TELECOM", ("Telephone & internet",)),
    (
        r"\bFUEL\b|\bSHELL\b|\bBP\b|\bTEXACO\b|\bESSO\b|\bTOTAL ENERGIES\b|\bOXIS ENERGY\b|\bPETROL\b",
        ("Motor expenses",),
    ),
    (r"\bADOBE\b|\bSOFTWARE\b|\bSUBSCRIPTION\b|\bXERO\b", ("Software & subscriptions",)),
    (r"\bPRET\b|\bCAFE\b|\bCOFFEE\b|\bGREGGS\b|\bBAKERY\b", ("Subsistence",)),
    (r"\bPARKING\b|\bRINGGO\b|\bTRAIN\b|\bTFL\b", ("Travel",)),
    (
        r"TIMBER|JOINERY SUPPL|WOODWORK|\bWICKES\b|TRAVIS PERKINS|\bGLASS\b|\bPAINT|\bFINISHES\b|VARNISH|"
        r"FASTENERS|NAILS|BUILDING SUPPLIES|\bELECTRICS\b",
        ("Materials", "Tools & small equipment"),
    ),
    (
        r"SCREWFIX|TOOLSTN|TOOLSTATION|\bTOOL\b|HARDWARE|MACHINERY|SAFETY|\bGLOVE|\bTOOLTRADE\b",
        ("Tools & small equipment", "Materials"),
    ),
]
KEYWORDS_RE = [(re.compile(p, re.IGNORECASE), cats) for p, cats in KEYWORDS]


@dataclass
class Case:
    """One bank line with its expectation. ``accounts`` empty means unscored."""

    id: str
    source: str  # which statement
    group: str  # "hand-written" | "two-month" | "ledger2"
    origin: str  # "gold_doc" | "keywords" | "kind"
    line: BankLine
    accounts: list[str] = field(default_factory=list)
    why: str = ""

    @property
    def scored(self) -> bool:
        return bool(self.accounts)


def to_accounts(categories: tuple[str, ...] | None) -> list[str]:
    return [CATEGORY_ACCOUNTS[c] for c in categories or () if c in CATEGORY_ACCOUNTS]


def keyword_expectation(description: str) -> tuple[list[str], str]:
    """(defensible accounts, why) from the ordered keyword table; ([], why) when no expense account applies."""
    for rx, cats in KEYWORDS_RE:
        if rx.search(description or ""):
            return to_accounts(cats), f"keyword /{rx.pattern[:40]}/"
    return [], "no keyword matched"


def doc_expectation(gold: dict[str, Any], amount_pence: int) -> tuple[list[str], str]:
    """Accounts for a line that pays a gold document (purchase side, money out only)."""
    if gold.get("side") != "purchase" or amount_pence >= 0 or gold.get("is_credit_note"):
        return [], "document is a sale or credit note: not an expense line"
    case = gold["gold_case"]
    if case not in CATEGORY:
        return [], f"gold case {case} has no category in harness.bank_match"
    cat = CATEGORY[case]
    if case == "utility" and PHONE_HINT.search(f"{gold.get('category_hint', '')} {gold['supplier']['name']}"):
        cat = "Telephone & internet"
    cats: tuple[str, ...] = (cat,)
    if case == "r_trade":
        cats = ("Tools & small equipment", "Materials")
    elif case == "pi_merchant":
        cats = ("Materials", "Tools & small equipment")
    elif case == "pi_subcontractor":
        cats = ("Professional fees",)
    accounts = to_accounts(cats)
    return accounts, f"gold document {gold['gold_case']}"


KIND_CATEGORY = {"insurance": ("Insurance",), "rent": ("Rent",), "bank fee": ("Bank charges",)}


def load_two_month_cases() -> list[Case]:
    matches = json.loads((GOLD / "bank" / "expected_matches.json").read_text(encoding="utf-8"))
    by_file: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for r in matches["rows"]:
        by_file[r["file"]][r["row"]] = r
    out: list[Case] = []
    for name, rows in sorted(by_file.items()):
        lines = parse_bank_csv((GOLD / "bank" / name).read_bytes(), name)
        for n, line in enumerate(lines, start=1):
            row = rows.get(n)
            c = Case(id=line.id, source=f"bank/{name}", group="two-month", origin="keywords", line=line)
            if row is None or row["amount_pence"] != line.amount_pence or row["date"] != line.date.isoformat():
                c.accounts, c.why = keyword_expectation(line.description)  # row numbering did not line up: fall back
            elif row["gold"]:
                g = json.loads((GOLD / "receipts" / row["gold"]).read_text(encoding="utf-8"))
                c.origin = "gold_doc"
                c.accounts, c.why = doc_expectation(g, line.amount_pence)
            elif row["kind"] in KIND_CATEGORY:
                c.origin = "kind"
                c.accounts, c.why = to_accounts(KIND_CATEGORY[row["kind"]]), f"statement kind {row['kind']}"
            else:
                c.origin = "kind"
                c.why = f"statement kind {row['kind']}: no expense account"
            out.append(c)
    return out


def load_hand_written_cases() -> list[Case]:
    out: list[Case] = []
    for name in ("barclays.csv", "monzo.csv", "starling.csv", "tide.csv"):
        for line in parse_bank_csv((GOLD / "bank" / name).read_bytes(), name):
            accounts, why = ([], "money in") if line.amount_pence >= 0 else keyword_expectation(line.description)
            if line.amount_pence == 0:
                why = "zero line"
            out.append(
                Case(
                    id=line.id,
                    source=f"bank/{name}",
                    group="hand-written",
                    origin="keywords",
                    line=line,
                    accounts=accounts,
                    why=why,
                )
            )
    return out


def load_ledger2_cases() -> list[Case]:
    out: list[Case] = []
    seen: set[str] = set()
    for p in sorted((GOLD / "ledger2" / "bank_pairs").glob("*.csv")):
        for line in parse_bank_csv(p.read_bytes(), p.name):
            if line.id in seen:
                continue
            seen.add(line.id)
            accounts, why = ([], "money in") if line.amount_pence >= 0 else keyword_expectation(line.description)
            out.append(
                Case(
                    id=f"{p.stem}:{line.id}",
                    source="ledger2/bank_pairs",
                    group="ledger2",
                    origin="keywords",
                    line=line,
                    accounts=accounts,
                    why=why,
                )
            )
    return out


def load_cases() -> list[Case]:
    cases = load_hand_written_cases() + load_two_month_cases() + load_ledger2_cases()
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):  # the same line twice would make a resumed run skip the wrong one
        dupes = [i for i, n in Counter(ids).items() if n > 1]
        for c in cases:
            if c.id in dupes:
                c.id = f"{c.source}:{c.id}"
    return cases


# ----------------------------------------------------------------------------------------------- model calls


class Recorder:
    """Wraps call_json_model: times the call and keeps the raw reply or the exception."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.raw: str | None = None
        self.error: str | None = None
        self.elapsed = 0.0

    async def __call__(self, messages: list[dict[str, str]], cfg: AiConfig, schema: dict[str, Any], name: str) -> str:
        self.raw, self.error = None, None
        t0 = time.perf_counter()
        try:
            self.raw = await self.inner(messages, cfg, schema, name)
            return self.raw
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised for suggest_ai to swallow as it does live
            self.error = f"{type(exc).__name__}: {exc}"[:300]
            raise
        finally:
            self.elapsed = time.perf_counter() - t0


def classify_failure(raw: str | None, error: str | None) -> str:
    """Why suggest_ai returned None, from what the model sent back."""
    if error:
        return "transport_error"
    if not raw or not raw.strip():
        return "empty_reply"
    try:
        data = parse_model_json(raw)
    except Exception:  # noqa: BLE001
        return "invalid_json"
    try:
        coding = bank_reconcile.AiCoding.model_validate(data)
    except Exception:  # noqa: BLE001
        return "invalid_shape"
    if coding.account not in ACCOUNTS:
        return "invalid_account"
    if (coding.vat_code or "").strip().upper() not in VALID_VAT | {""}:
        return "invalid_vat_code"
    return "refused_other"


async def run_case(case: Case, cfg: AiConfig, rec: Recorder) -> dict[str, Any]:
    got = await bank_reconcile.suggest_ai(case.line, cfg, ACCOUNTS)
    row: dict[str, Any] = {
        "id": case.id,
        "source": case.source,
        "group": case.group,
        "origin": case.origin,
        "description": case.line.description,
        "amount_pence": case.line.amount_pence,
        "expected": case.accounts,
        "why": case.why,
        "elapsed_s": round(rec.elapsed, 3),
        "outcome": "ok",
        "account": None,
        "vat_code": None,
        "contact": None,
        "reason": None,
        "raw": (rec.raw or "")[:600],
        "error": rec.error,
    }
    if got is None:
        row["outcome"] = classify_failure(rec.raw, rec.error)
        return row
    row.update(account=got.account, vat_code=got.vat_code, contact=got.contact, reason=got.reason)
    if case.scored:
        row["correct"] = got.account in case.accounts
        row["primary"] = got.account == case.accounts[0]
    return row


# ----------------------------------------------------------------------------------------------- stub model


def stub_model(messages: list[dict[str, str]], faults: bool = True) -> str:
    """A fake Glimmer for --stub and the tests: answers from the keyword table, with deterministic faults."""
    facts = json.loads(messages[-1]["content"].split("LINE:\n", 1)[1])
    accounts, _ = keyword_expectation(facts["description"])
    account = accounts[0] if accounts else SUNDRY
    key = sum(ord(ch) for ch in facts["description"]) + abs(facts["amount_pence"])
    if faults and key % 29 == 0:
        return "Sure! Here is the coding: account five thousand"  # invalid JSON
    if faults and key % 31 == 0:
        return json.dumps({"account": "9999 Made up account", "vat_code": "N", "contact": None, "reason": "x"})
    if faults and key % 37 == 0:
        return json.dumps({"account": account, "vat_code": "Q", "contact": None, "reason": "bad vat code"})
    if faults and key % 17 == 0:
        account = SUNDRY  # a plain miss
    return json.dumps({"account": account, "vat_code": "N", "contact": None, "reason": facts["description"][:40]})


async def stub_call(messages: list[dict[str, str]], cfg: AiConfig, schema: dict[str, Any], name: str) -> str:
    await asyncio.sleep(0)
    return stub_model(messages)


# ----------------------------------------------------------------------------------------------- summary / report


def pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def percentile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 3)


def summarise(rows: list[dict[str, Any]], cfg: AiConfig | None, stub: bool) -> dict[str, Any]:
    total = len(rows)
    outcomes = Counter(r["outcome"] for r in rows)
    scored = [r for r in rows if r["expected"]]
    answered = [r for r in scored if r["outcome"] == "ok"]
    right = [r for r in answered if r.get("correct")]
    primary = [r for r in answered if r.get("primary")]
    lat = [r["elapsed_s"] for r in rows]
    by_source: dict[str, dict[str, Any]] = {}
    for src in sorted({r["group"] for r in rows}):
        sub = [r for r in scored if r["group"] == src]
        ok = [r for r in sub if r.get("correct")]
        by_source[src] = {"scored": len(sub), "correct": len(ok), "accuracy_pct": pct(len(ok), len(sub))}
    by_expected: dict[str, dict[str, Any]] = {}
    for r in scored:
        d = by_expected.setdefault(r["expected"][0], {"scored": 0, "correct": 0})
        d["scored"] += 1
        d["correct"] += 1 if r.get("correct") else 0
    confusion = Counter((r["expected"][0], r["account"]) for r in answered if not r.get("correct"))
    unscored = [r for r in rows if not r["expected"]]
    return {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": (cfg.model if cfg else None),
        "base_url": (cfg.base_url if cfg else None),
        "stub": stub,
        "lines": total,
        "scored_lines": len(scored),
        "unscored_lines": len(unscored),
        "accuracy_pct": pct(len(right), len(scored)),  # refusals count as wrong: a person gets nothing
        "accuracy_when_answered_pct": pct(len(right), len(answered)),
        "primary_accuracy_pct": pct(len(primary), len(scored)),
        "outcomes": dict(outcomes),
        "refusals": sum(n for k, n in outcomes.items() if k != "ok"),
        "refusal_pct": pct(sum(n for k, n in outcomes.items() if k != "ok"), total),
        "invalid_json": outcomes.get("invalid_json", 0) + outcomes.get("invalid_shape", 0),
        "invalid_account": outcomes.get("invalid_account", 0),
        "invalid_vat_code": outcomes.get("invalid_vat_code", 0),
        "transport_errors": outcomes.get("transport_error", 0),
        "latency_s": {
            "mean": round(statistics.fmean(lat), 3) if lat else None,
            "p50": percentile(lat, 0.5),
            "p95": percentile(lat, 0.95),
            "max": round(max(lat), 3) if lat else None,
            "total": round(sum(lat), 1),
        },
        "by_source": by_source,
        "by_expected_account": {
            k: {**v, "accuracy_pct": pct(v["correct"], v["scored"])} for k, v in sorted(by_expected.items())
        },
        "top_confusions": [{"expected": e, "got": g, "n": n} for (e, g), n in confusion.most_common(10)],
        "unscored_answers": dict(Counter(r["account"] or r["outcome"] for r in unscored).most_common(8)),
        "vat_codes": dict(Counter(r["vat_code"] for r in rows if r["outcome"] == "ok")),
    }


def report_md(s: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    L = s["latency_s"]
    stub_note = " (STUB: a fake model, numbers mean nothing)" if s["stub"] else ""
    out = [
        "# Bank-rule AI coding eval",
        "",
        f"Model `{s['model']}` at `{s['base_url']}`{stub_note}; {s['generated']}. "
        "Code under test: `app.bank_reconcile.suggest_ai`.",
        "",
        f"- Lines asked: **{s['lines']}** ({s['scored_lines']} scored, {s['unscored_lines']} with no expense account, "
        "reported but not scored)",
        f"- **Accuracy: {s['accuracy_pct']}%** of scored lines (a refusal counts as wrong); "
        f"{s['accuracy_when_answered_pct']}% of those it answered; primary-account-only {s['primary_accuracy_pct']}%",
        f"- Refusals (no suggestion): **{s['refusals']}** ({s['refusal_pct']}%): "
        f"{ {k: v for k, v in s['outcomes'].items() if k != 'ok'} }",
        f"- Invalid JSON / shape: {s['invalid_json']}; account outside the list: {s['invalid_account']}; "
        f"bad VAT code: {s['invalid_vat_code']}; transport errors: {s['transport_errors']}",
        f"- Latency per line: mean {L['mean']} s, p50 {L['p50']} s, p95 {L['p95']} s, max {L['max']} s "
        f"(total {L['total']} s)",
        "",
        "## By statement set",
        "",
        "| Set | Scored | Correct | Accuracy |",
        "|---|---:|---:|---:|",
        *(f"| {k} | {v['scored']} | {v['correct']} | {v['accuracy_pct']}% |" for k, v in s["by_source"].items()),
        "",
        "## By expected account",
        "",
        "| Expected | Scored | Correct | Accuracy |",
        "|---|---:|---:|---:|",
        *(
            f"| {k} | {v['scored']} | {v['correct']} | {v['accuracy_pct']}% |"
            for k, v in s["by_expected_account"].items()
        ),
        "",
        "## Top confusions",
        "",
        *(f"- expected {c['expected']} -> got {c['got']}: {c['n']}" for c in s["top_confusions"]),
        "",
        f"## Lines with no expense account (not scored): what the model did\n\n{s['unscored_answers']}",
        "",
        "## Misses (scored lines the model answered wrongly, first 25)",
        "",
        "| Description | Amount | Expected | Got | Reason |",
        "|---|---:|---|---|---|",
    ]
    misses = [r for r in rows if r["expected"] and r["outcome"] == "ok" and not r.get("correct")][:25]
    out += [
        f"| {r['description'][:48]} | {r['amount_pence'] / 100:.2f} | {r['expected'][0]} | {r['account']} | "
        f"{(r['reason'] or '')[:50]} |"
        for r in misses
    ]
    refused = [r for r in rows if r["outcome"] != "ok"][:15]
    out += ["", "## Refusals (first 15)", "", "| Description | Outcome | Raw reply (start) |", "|---|---|---|"]
    out += [f"| {r['description'][:48]} | {r['outcome']} | {(r['raw'] or r['error'] or '')[:60]!r} |" for r in refused]
    out += [
        "",
        "How the expectation is derived: see the module docstring of `evals/harness/bank_ai.py` "
        "(gold document category, statement kind, or an ordered keyword table; sets of defensible accounts).",
    ]
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------------------------------------- main


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


async def main_async(args: argparse.Namespace) -> dict[str, Any] | None:
    cases = load_cases()
    if args.limit:
        step = max(1, len(cases) // args.limit)  # spread over the sets, not just the first statement
        cases = cases[::step][: args.limit]
    scored = sum(c.scored for c in cases)
    print(f"{len(cases)} lines ({scored} scored); origins {dict(Counter(c.origin for c in cases))}", flush=True)
    if args.dry_run:
        for c in cases[: args.show]:
            want = c.accounts or "-"
            print(f"  {c.source:34} {c.line.amount_pence / 100:>10.2f} {c.line.description[:42]:42} -> {want}")
        print(json.dumps(dict(Counter(c.accounts[0] if c.accounts else "(unscored)" for c in cases)), indent=1))
        return None

    out = Path(args.out) if args.out else OUT
    out.mkdir(parents=True, exist_ok=True)
    results = out / "results.jsonl"
    if args.fresh and results.exists():
        results.unlink()
    done = {r["id"] for r in read_results(results)}
    cfg = AiConfig.resolve(mode="local", base_url=args.base, model=args.model)
    inner = stub_call if args.stub else ask_mod.call_json_model
    rec = Recorder(inner)
    original = ask_mod.call_json_model
    ask_mod.call_json_model = rec  # suggest_ai imports it from app.ai.ask at call time
    try:
        with results.open("a", encoding="utf-8") as fh:
            if results.stat().st_size and not results.read_bytes().endswith(b"\n"):
                fh.write("\n")  # a kill left half a line: do not glue the next row onto it
            for i, case in enumerate(cases, start=1):
                if case.id in done:
                    continue
                row = await run_case(case, cfg, rec)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                mark = "ok " if row["outcome"] == "ok" and row.get("correct", True) else "MISS"
                print(
                    f"[{i}/{len(cases)}] {mark} {row['elapsed_s']:.1f}s {row['description'][:40]} -> "
                    f"{row['account'] or row['outcome']}",
                    flush=True,
                )
    finally:
        ask_mod.call_json_model = original
    wanted = {c.id for c in cases}
    rows = [r for r in read_results(results) if r["id"] in wanted]
    summary = summarise(rows, cfg, args.stub)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "report.md").write_text(report_md(summary, rows), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=DEFAULT_OLLAMA_BASE, help="Ollama base URL (default http://localhost:11434)")
    ap.add_argument("--model", default=DEFAULT_OLLAMA_MODEL)
    ap.add_argument("--limit", type=int, default=0, help="0 = every line; otherwise a spread sample of that size")
    ap.add_argument("--dry-run", action="store_true", help="build lines and expectations, call no model, write nothing")
    ap.add_argument("--stub", action="store_true", help="in-process fake model (tests the pipeline, not the model)")
    ap.add_argument("--fresh", action="store_true", help="ignore and replace an earlier results.jsonl")
    ap.add_argument("--show", type=int, default=15, help="--dry-run: how many lines to print")
    ap.add_argument("--out", default=None, help="default evals/runs/bank_ai/")
    summary = asyncio.run(main_async(ap.parse_args()))
    if summary:
        print(json.dumps({k: summary[k] for k in ("lines", "scored_lines", "accuracy_pct", "refusals", "latency_s")}))


if __name__ == "__main__":
    main()
