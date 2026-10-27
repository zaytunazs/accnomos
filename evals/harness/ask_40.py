"""Ask eval: 40 prompts over the seeded fictional books, through the app's own Ask path, Glimmer and Qwen.

    cd evals && python -m harness.ask_40                  # both models; writes runs/ask_40/{report.md,result.json}
    cd evals && python -m harness.ask_40 --models glimmer  # one model

The books are the demo seed (tools/seed_demo.py, "Bramblewood Joinery Ltd", built for 27 Oct 2026) applied to a
Books on fake storage, so no OneDrive is involved. Every prompt goes through app.routes_ask._answer (day-plan intent,
then instruction -> action card, then facts pack + model + grounding), with the period fixed to Jul-Sep 2026 so
the previous period is Apr-Jun. The model's raw reply is captured before grounding.

Gold answers are computed by code from the facts pack (app/facts.py) at run time, never typed in. Scores:
  numbers_exact      every gold figure (or name) appears in the shipped answer or its key numbers
  citation_present   at least one citation, all of them in FACTS.sources (questions about one entry: that entry's file)
  no_invented_figure the model's raw reply quotes no figure missing from the facts (grounding would replace it)
Three questions the facts cannot answer check that no figure is invented and the answer says so. Five instructions
must come back as action cards (or one follow-up question), not as answers.
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import json
import re
import sys
import time
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for extra in (REPO / "services" / "runtime", REPO / "packages" / "ledger" / "src", REPO / "packages" / "connectors" / "src",
              REPO / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import seed_demo  # noqa: E402
from accnomos_connectors import FakeStorageProvider  # noqa: E402

from app import routes_ask  # noqa: E402
from app.ai import ask as ask_ai  # noqa: E402
from app.ai.config import AiConfig  # noqa: E402
from app.ai.extract import parse_model_json  # noqa: E402
from app.books import Books  # noqa: E402
from app.facts import build_facts  # noqa: E402
from app.schemas import AskAnswer, AskModelOutput, AskPeriod, AskRequest  # noqa: E402
from app.vat_cycle import VatCycle  # noqa: E402

BUSINESS = "Bramblewood Joinery Ltd"
SEED_DAY = date(2026, 10, 27)
PERIOD = AskPeriod(start=date(2026, 7, 1), end=date(2026, 9, 30))
MODELS = {
    "glimmer": AiConfig(mode="local", base_url="http://localhost:11434", model="muse-glimmer:30b"),
    "qwen": AiConfig(mode="key", base_url="http://localhost:8000/v1", model="qwen3.8-27b", api_key="local-vllm"),
}

F = dict[str, Any]
Gold = Callable[[F], list[str]]


def this(*path: str) -> Gold:
    return lambda f: [_get(f["this_period"], path)]


def prev(*path: str) -> Gold:
    return lambda f: [_get(f["previous_period"], path)]


def derived(key: str) -> Gold:
    return lambda f: [f["derived"][key]]


def _get(node: Any, path: tuple[str, ...]) -> str:
    for k in path:
        node = node[k]
    return str(node)


def supplier(rank: int) -> Gold:
    return lambda f: [f["top_suppliers"][rank]["name"], f["top_suppliers"][rank]["net"]]


def customer(rank: int) -> Gold:
    return lambda f: [f["top_customers"][rank]["name"], f["top_customers"][rank]["net"]]


def named(table: str, name: str, field: str) -> Gold:
    return lambda f: [str(next(t[field] for t in f[table] if t["name"] == name))]


def txn(who: str, field: str, day: str | None = None) -> Gold:
    return lambda f: [_txn(f, who, day)[field]]


def _txn(f: F, who: str, day: str | None) -> F:
    return next(t for t in f["largest_transactions"] if t["counterparty"] == who and (day is None or t["date"] == day))


def largest(f: F) -> list[str]:
    return [f["largest_transactions"][0]["gross"]]


# (id, prompt, gold, citation: "vat" = any listed source, ("txn", who, day) = that entry's file, None = unanswerable)
QUESTIONS: list[tuple[str, str, Gold | None, Any]] = [
    ("vat_box5", "How much VAT do I owe for this quarter?", this("vat", "box5"), "vat"),
    ("vat_box1", "What is the Box 1 figure on my VAT return?", this("vat", "box1"), "vat"),
    ("vat_box4", "How much VAT can I reclaim this quarter?", this("vat", "box4"), "vat"),
    ("vat_box6", "What are my total sales excluding VAT for Box 6?", this("vat", "box6"), "vat"),
    ("vat_box7", "What goes in Box 7 this quarter?", this("vat", "box7"), "vat"),
    ("vat_prev_box5", "How much VAT did I owe last quarter?", prev("vat", "box5"), "vat"),
    ("vat_delta", "By how much has my VAT bill changed since last quarter?", derived("box5_delta_vs_prev"), "vat"),
    ("vat_pct", "By what percentage did my VAT bill go up compared with last quarter?", derived("box5_change_pct_vs_prev"), "vat"),
    ("vat_prev_box4", "How much VAT did I reclaim last quarter?", prev("vat", "box4"), "vat"),
    ("vat_prev_box6", "What was Box 6 last quarter?", prev("vat", "box6"), "vat"),
    ("vat_box4_delta", "How much less VAT am I reclaiming than last quarter?", derived("box4_delta_vs_prev"), "vat"),
    ("vat_position", "Do I have to pay HMRC this quarter or will they repay me, and how much?", this("vat", "box5"), "vat"),
    ("sales_net", "What were my net sales this quarter?", this("totals", "sales", "net"), "vat"),
    ("purchases_net", "How much did I spend on purchases this quarter, before VAT?", this("totals", "purchases", "net"), "vat"),
    ("sales_count", "How many sales entries are there this quarter?", this("totals", "sales", "count"), "vat"),
    ("purchases_count", "How many purchase entries are in the books this quarter?", this("totals", "purchases", "count"), "vat"),
    ("sales_growth", "How much did my net sales grow compared with last quarter?", derived("sales_net_delta_vs_prev"), "vat"),
    ("purchases_pct", "By what percentage did my purchases change from last quarter?", derived("purchases_net_change_pct_vs_prev"), "vat"),
    ("prev_sales_net", "What were my net sales last quarter?", prev("totals", "sales", "net"), "vat"),
    ("sales_vat", "How much VAT did I charge on my sales this quarter?", this("totals", "sales", "vat"), "vat"),
    ("entries", "How many approved entries are in the books for this quarter?", this("entries"), "vat"),
    ("prev_purchases_net", "What did I spend on purchases last quarter, net of VAT?", prev("totals", "purchases", "net"), "vat"),
    ("top_supplier", "Who was my biggest supplier this quarter and how much did I spend with them?", supplier(0), "vat"),
    ("oakhurst_net", "How much did I spend with Oakhurst Timber & Tools this quarter?", named("top_suppliers", "Oakhurst Timber & Tools", "net"), "vat"),
    ("top_customer", "Who is my biggest customer this quarter and how much did they spend?", customer(0), "vat"),
    ("hartwell_net", "How much did Hartwell Property Maintenance buy from me this quarter, before VAT?", named("top_customers", "Hartwell Property Maintenance", "net"), "vat"),
    ("sterling_count", "How many invoices did Sterling & Co. Architects get this quarter?", named("top_customers", "Sterling & Co. Architects", "count"), "vat"),
    ("largest", "What was my largest single transaction this quarter, including VAT?", largest, "largest"),
    ("harrowgate_gross", "How much was the Harrowgate Interiors invoice on 19 September including VAT?", txn("Harrowgate Interiors", "gross"), ("txn", "Harrowgate Interiors", None)),
    ("oakhurst_vat", "How much VAT was on the Oakhurst Timber & Tools purchase?", txn("Oakhurst Timber & Tools", "vat"), ("txn", "Oakhurst Timber & Tools", None)),
    ("reduced_rate", "How much did I spend on reduced-rate (5 %) purchases this quarter, net?", this("totals", "by_vat_code", "purchases:R", "net"), "vat"),
    ("no_vat_invoice", "How much did I spend on purchases with no VAT invoice (code N) this quarter?", this("totals", "by_vat_code", "purchases:N", "net"), "vat"),
    ("bank_balance", "What is my bank balance today?", None, None),
    ("corp_tax", "How much corporation tax will I owe for this year?", None, None),
    ("fuel_2025", "What did I spend on fuel in March 2025?", None, None),
]
#: Instructions: the expected action kind. A card (or one follow-up question) passes; an answer does not.
INSTRUCTIONS: list[tuple[str, str, str]] = [
    ("act_invoice", "Send a £450 invoice to Sterling & Co. Architects for the staircase repair", "create_invoice"),
    ("act_chase", "Chase the overdue invoice INV-0002", "chase_invoice"),
    ("act_mileage", "Log 42 miles in the director's car yesterday from the workshop to Harrogate", "log_mileage"),
    ("act_timesheet", "Record 6 hours for Sam Ashdown on the office partitions job today", "log_timesheet"),
    ("act_invoice_vat", "Bill Hartwell Property Maintenance £1,200 plus VAT for the office doors", "create_invoice"),
]
SMALL = {"0": "no|none|zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven",
         "8": "eight", "9": "nine", "10": "ten", "16": "sixteen", "19": "nineteen", "21": "twenty-one"}
DECLINE = re.compile(r"\b(don['’]t|do not|can['’]t|cannot|isn['’]t|is not|aren['’]t|no)\b.{0,60}?\b(tell|have|show|see|includ\w*|cover|data|figures?|information|record|available)",
                     re.IGNORECASE | re.DOTALL)
_NUM = re.compile(r"[-−]?£?\d[\d,]*(?:\.\d+)?")


def _values(text: str) -> set[Decimal]:
    out: set[Decimal] = set()
    for t in _NUM.findall(text):
        try:
            out.add(abs(Decimal(t.replace("−", "-").replace("£", "").replace(",", ""))))
        except InvalidOperation:
            continue
    return out


def has_gold(gold: str, text: str) -> bool:
    """A figure by value (pct also as a whole percent), a count also in words, a name case-insensitively."""
    try:
        want = abs(Decimal(gold))
    except InvalidOperation:
        return gold.lower() in text.lower()
    vals = _values(text)
    if want in vals:
        return True
    if gold in SMALL and re.search(rf"\b({SMALL[gold]})\b", text, re.IGNORECASE):
        return True
    return False


def shipped_text(a: AskAnswer) -> str:
    return " ".join([a.answer_md, *(k.value for k in a.key_numbers)])


async def seeded_books() -> Books:
    plan = seed_demo.build_plan(BUSINESS, SEED_DAY)
    fake = FakeStorageProvider()
    await seed_demo.seed(fake, plan, say=lambda _m: None)
    return Books(fake)


async def ask_one(books: Books, cfg: AiConfig, prompt: str, raw: list[str]) -> AskAnswer:
    raw.clear()
    req = AskRequest(question=prompt, period=PERIOD)
    return await routes_ask._answer(req, books, cfg, BUSINESS, "eval-graph-token", VatCycle())


def score_question(qid: str, prompt: str, gold: Gold | None, cite: Any, facts: F, a: AskAnswer, raw: list[str]) -> dict[str, Any]:
    known = ask_ai.KnownNumbers(facts, prompt)  # the same rule as grounding: the user's own figures count as known
    raw_invented: list[str] = []
    raw_ok = bool(raw)
    for text in raw:
        try:
            out = AskModelOutput.model_validate(parse_model_json(text))
        except Exception:  # noqa: BLE001  unparsed raw reply: grounding falls back, nothing invented reaches the user
            raw_ok = False
            continue
        raw_invented += known.unknown(out.answer_md, all_tokens=False)
        for kn in out.key_numbers:
            raw_invented += known.unknown(kn.value, all_tokens=True)
    text = shipped_text(a)
    sources = set(facts["sources"])
    rec: dict[str, Any] = {
        "id": qid, "answer": a.answer_md, "key_numbers": [k.value for k in a.key_numbers], "citations": a.citations,
        "fallback": a.fallback_reason, "card": a.proposed_action is not None, "raw_parsed": raw_ok,
        "raw_invented": sorted(set(raw_invented)), "no_invented_figure": raw_ok and not raw_invented,
        "shipped_invented": known.unknown(a.answer_md, all_tokens=False),
    }
    rec["citation_present"] = bool(a.citations) and set(a.citations) <= sources
    if isinstance(cite, tuple):
        rec["citation_present"] = rec["citation_present"] and _txn(facts, cite[1], cite[2])["source"] in a.citations
    elif cite == "largest":
        rec["citation_present"] = rec["citation_present"] and facts["largest_transactions"][0]["source"] in a.citations
    if gold is None:
        rec["gold"] = None
        rec["declined"] = bool(DECLINE.search(a.answer_md)) and a.fallback_reason is None
        rec["numbers_exact"] = None
    else:
        rec["gold"] = [str(g) for g in gold(facts)]
        rec["numbers_exact"] = all(has_gold(g, text) for g in rec["gold"])
    return rec


#: The current model's list of raw Ask replies (one task per model, so each sees its own list).
_RAW: contextvars.ContextVar[list[str]] = contextvars.ContextVar("raw_replies")


def capture_raw_replies() -> None:
    """Wrap ask_ai._call_model so the Ask reply is kept before grounding; the call itself is unchanged."""
    real_call = ask_ai._call_model

    async def capture(messages, cfg, *args, **kwargs):  # type: ignore[no-untyped-def]
        text = await real_call(messages, cfg, *args, **kwargs)
        output = args[0] if args else kwargs.get("output", AskModelOutput)
        if output is AskModelOutput and (raw := _RAW.get(None)) is not None:
            raw.append(text)
        return text

    ask_ai._call_model = capture  # type: ignore[assignment]


async def run_model(name: str, cfg: AiConfig, books: Books, facts: F) -> dict[str, Any]:
    raw: list[str] = []
    _RAW.set(raw)
    recs: list[dict[str, Any]] = []
    for qid, prompt, gold, cite in QUESTIONS:
        t0 = time.monotonic()
        a = await ask_one(books, cfg, prompt, raw)
        rec = score_question(qid, prompt, gold, cite, facts, a, raw)
        rec.update(prompt=prompt, seconds=round(time.monotonic() - t0, 1))
        recs.append(rec)
        print(f"[{name}] {qid}: exact={rec['numbers_exact']} cite={rec['citation_present']} "
              f"invented={rec['raw_invented'] or '-'} fallback={bool(rec['fallback'])}", flush=True)
    for qid, prompt, kind in INSTRUCTIONS:
        t0 = time.monotonic()
        a = await ask_one(books, cfg, prompt, raw)
        got = a.proposed_action.kind if a.proposed_action else ("clarification" if a.clarification else "answer")
        recs.append({"id": qid, "prompt": prompt, "expected_kind": kind, "got": got, "answer": a.answer_md,
                     "card": a.proposed_action is not None, "card_right_kind": got == kind,
                     "clarification": a.clarification is not None, "seconds": round(time.monotonic() - t0, 1)})
        print(f"[{name}] {qid}: {got}", flush=True)
    return {"model": cfg.model, "records": recs, "summary": summarise(recs)}


def rescore(res: dict[str, Any]) -> dict[str, Any]:
    """Recompute numbers_exact from the stored answers (scoring changes need no new model calls)."""
    for r in res.values():
        for x in r["records"]:
            if x.get("gold"):
                x["gold"] = [str(g) for g in x["gold"]]
                text = " ".join([x["answer"], *x["key_numbers"]])
                x["numbers_exact"] = all(has_gold(g, text) for g in x["gold"])
            elif "declined" in x:
                x["declined"] = bool(DECLINE.search(x["answer"])) and x["fallback"] is None
        r["summary"] = summarise(r["records"])
    return res


def summarise(recs: list[dict[str, Any]]) -> dict[str, Any]:
    qs = [r for r in recs if "expected_kind" not in r]
    gold = [r for r in qs if r["gold"] is not None]
    none = [r for r in qs if r["gold"] is None]
    acts = [r for r in recs if "expected_kind" in r]
    return {
        "questions": len(qs), "with_gold": len(gold),
        "numbers_exact": sum(r["numbers_exact"] for r in gold),
        "citation_present": sum(r["citation_present"] for r in gold),
        "no_invented_figure": sum(r["no_invented_figure"] for r in qs),
        "raw_unparsed": sum(not r["raw_parsed"] for r in qs),
        "fallbacks": sum(bool(r["fallback"]) for r in qs),
        "shipped_invented": sum(bool(r["shipped_invented"]) for r in qs),
        "unanswerable": len(none), "declined": sum(r["declined"] for r in none),
        "instructions": len(acts), "cards": sum(r["card"] for r in acts), "cards_right_kind": sum(r["card_right_kind"] for r in acts),
        "clarifications": sum(r["clarification"] for r in acts),
        "answered_instead": sum(r["got"] == "answer" for r in acts),
        "seconds": round(sum(r["seconds"] for r in recs), 1),
    }


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({100 * a / b:.0f} %)" if b else "n/a"


def report_md(res: dict[str, Any]) -> str:
    out = ["# Ask: 40 prompts over the seeded books", "",
           "Generated by `cd evals && python -m harness.ask_40`. Books: the demo seed (`tools/seed_demo.py`, Bramblewood",
           "Joinery Ltd, built for 27 Oct 2026) on fake storage. Period Jul-Sep 2026 (previous Apr-Jun). Every prompt runs",
           "through `app.routes_ask._answer`; gold answers are computed from the facts pack (`app/facts.py`) at run time.", "",
           "| | " + " | ".join(res) + " |", "|---|" + "---:|" * len(res)]
    rows = [
        ("Numbers exact (32 questions with a gold figure)", lambda s: pct(s["numbers_exact"], s["with_gold"])),
        ("Citation present and valid", lambda s: pct(s["citation_present"], s["with_gold"])),
        ("No invented figure in the raw reply (replies that parsed)", lambda s: pct(s["no_invented_figure"], s["questions"] - s["raw_unparsed"])),
        ("Raw reply not parsed", lambda s: str(s["raw_unparsed"])),
        ("Answers replaced by the code fallback", lambda s: str(s["fallbacks"])),
        ("Invented figures reaching the user", lambda s: str(s["shipped_invented"])),
        ("Unanswerable: says the books don't show it", lambda s: pct(s["declined"], s["unanswerable"])),
        ("Instructions → action card of the right kind", lambda s: pct(s["cards_right_kind"], s["instructions"])),
        ("Instructions → follow-up question", lambda s: str(s["clarifications"])),
        ("Instructions answered as questions", lambda s: str(s["answered_instead"])),
        ("Total seconds", lambda s: str(s["seconds"])),
    ]
    for label, fn in rows:
        out.append(f"| {label} | " + " | ".join(fn(r["summary"]) for r in res.values()) + " |")
    out += ["", "Numbers exact counts the shipped answer: when grounding replaces the model's words with the code fallback,",
            "the fallback only quotes the VAT boxes and totals, so a question about something else scores as wrong.",
            "The unanswerable check is a phrase match on the answer and only counts model-written answers.", "",
            "## Reading the numbers", "",
            "- Glimmer: median about 49 s per prompt; 4 of 35 questions ran into the app's 120 s Ask timeout (`TIMEOUT_S` in",
            "  `app/ai/ask.py`) with nothing else using Ollama, so the user got the code fallback (right figures, no wording).",
            "  Those count as unparsed and, unless the fallback happens to quote the gold figure, as not exact.",
            "- Both models once quoted this quarter's figure for a question about last quarter (Glimmer `vat_prev_box4`, Qwen",
            "  `prev_purchases_net`): grounding cannot catch that, because the figure is in the facts.",
            "- The first run (before `25c4e2f`) replaced \"fuel in March 2025\" with the fallback on both models because the year",
            "  from the question counted as invented; grounding now accepts figures from the question.",
            "- A follow-up question instead of a card: Glimmer asked for quantities on \"£1,200 plus VAT for the office doors\",",
            "  Qwen asked for the start and end of the mileage journey (the prompt gave only \"from the workshop to Harrogate\").",
            ""]
    for name, r in res.items():
        out += [f"## {name} ({r['model']})", "", "| Id | Exact | Cited | Invented (raw) | Fallback | Note |", "|---|---|---|---|---|---|"]
        for x in r["records"]:
            if "expected_kind" in x:
                out.append(f"| {x['id']} | | | | | expected `{x['expected_kind']}`, got `{x['got']}` |")
                continue
            note = "gold: " + ", ".join(x["gold"]) if x["gold"] else ("declined" if x.get("declined") else "did not say it can't tell")
            yn = lambda v: "-" if v is None else ("yes" if v else "**no**")  # noqa: E731
            out.append(f"| {x['id']} | {yn(x['numbers_exact'])} | {yn(x['citation_present'])} | {', '.join(x['raw_invented']) or '-'} | "
                       f"{'yes' if x['fallback'] else '-'} | {note} |")
        out.append("")
    return "\n".join(out) + "\n"


async def main_async(names: list[str], out: Path) -> dict[str, Any]:
    capture_raw_replies()
    books = await seeded_books()
    facts = await build_facts(books, PERIOD, BUSINESS)
    results = await asyncio.gather(*(run_model(n, MODELS[n], books, facts) for n in names))
    res = dict(zip(names, results, strict=True))
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    (out / "report.md").write_text(report_md(res), encoding="utf-8")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models", nargs="+", choices=list(MODELS), default=list(MODELS))
    ap.add_argument("--out", type=Path, default=REPO / "evals" / "runs" / "ask_40")
    ap.add_argument("--only", nargs="+", help="prompt ids (a quick check; the report then covers only these)")
    ap.add_argument("--report-only", action="store_true", help="re-score <out>/result.json and rewrite the report")
    args = ap.parse_args()
    if args.report_only:
        res = rescore(json.loads((args.out / "result.json").read_text(encoding="utf-8")))
        (args.out / "result.json").write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        (args.out / "report.md").write_text(report_md(res), encoding="utf-8")
        for n, r in res.items():
            print(n, json.dumps(r["summary"]))
        return
    if args.only:
        QUESTIONS[:] = [q for q in QUESTIONS if q[0] in args.only]
        INSTRUCTIONS[:] = [i for i in INSTRUCTIONS if i[0] in args.only]
    res = asyncio.run(main_async(args.models, args.out))
    for n, r in res.items():
        print(n, json.dumps(r["summary"]))


if __name__ == "__main__":
    main()
