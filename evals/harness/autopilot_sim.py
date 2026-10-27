"""Autopilot L2 safety eval: rule-based posting over the seeded demo books, scored against gold.

    cd evals && python -m harness.autopilot_sim --verifier on    # Glimmer reads twice (extractor + verifier prompt)
    cd evals && python -m harness.autopilot_sim --verifier off   # VERIFIER=off: one reading
    cd evals && python -m harness.autopilot_sim --report         # report.md + summary.json from both runs

What it does, all in memory (FakeStorageProvider) and through the app's own code:

1. Books: `tools/seed_demo.seed()` fills a fake OneDrive with the fictional company's plan (40 ledger events),
   without its 25 inbox documents, which are fed below instead.
2. Rules the demo user would plausibly have saved:
   * history: every seeded purchase approval, as if "Always do this" had been ticked (the same two writes
     `approve(always=True)` makes: the account rule and `rule_from_proposal` -> `save_rule`);
   * regular: the seeded books share no supplier with the inbox, so for every other purchase supplier in the
     gold set one earlier bill (the gold reading, dated 91 days before, invoice number "-prev") is put through
     the seed's own propose step and `approve(..., always=True)`. This is the case Autopilot exists for (a
     supplier you have approved before) and what puts each document within reach of a rule.
3. Each document is written to 00 Inbox on its own and `scan_inbox_detailed()` runs with Autopilot on (L2) and
   the VAT period that contains the document's date (scanned when it arrived). Passes, each on a fresh copy
   of the books: `inbox` (the seed's 25 documents, rendered as the seed renders them), `messy` and `clean` (the
   200-document gold set as phone photos / clean scans), `dupes` (posted purchases again: a new photo of each,
   and the identical file for ten).
4. Per document: would-post (Autopilot posted it) / proposed / needs-a-look, then against gold:
   * false post: posted, but a field differs from gold (supplier, VAT number, date, net, VAT, total, side, or
     the ledger event's net/VAT), or gold says it needs a look, or it is a duplicate (the same document is
     already in the books: the dupes pass, and gold documents the seed itself posted);
   * missed post: gold says Autopilot should post it (the same rule decision on a perfect reading, not a
     duplicate, expected status proposed) and it did not;
   * correct post: posted and not a false post.

Nothing is stubbed except the model backend selection: `--verifier off` sets VERIFIER=off (select_backend
returns None); otherwise the verifier runs on Glimmer via Ollama, as the demo does in local mode.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable
from functools import partial
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "tools"), str(REPO / "evals")]  # also runnable as evals/harness/autopilot_sim.py
import seed_demo as sd  # noqa: E402  (puts this checkout's packages and runtime first on sys.path)

from accnomos_connectors import FakeStorageProvider  # noqa: E402

from app import autopilot  # noqa: E402
from app.ai.config import AiConfig  # noqa: E402
from app.ai.verify import normalise_name, select_backend  # noqa: E402
from app.approve import _remember, approve  # noqa: E402
from app.books import Books  # noqa: E402
from app.checks import decide, normalise_vat_number, run_checks  # noqa: E402
from app.deadlines import period_containing  # noqa: E402
from app.inbox import apply_rule, scan_inbox_detailed  # noqa: E402
from app.journal import draft_journal  # noqa: E402
from app.paths import INBOX  # noqa: E402
from app.repair import repair  # noqa: E402
from app.schemas import ExtractedDoc, Proposal  # noqa: E402
from app.testmode import extracted_from_gold, gold_receipts  # noqa: E402

from harness.render import render_receipt  # noqa: E402
from harness.run_extraction import expected_status, gold_side  # noqa: E402

TODAY = date(2026, 10, 27)
OUT = REPO / "evals" / "runs" / "autopilot_l2"
PASSES = ("inbox", "clean", "messy", "dupes")
EXACT_DUPES = 10
HANDWRITTEN = {"edge_handwritten", "edge_torn_faded"}
CLASSES = ("clean", "messy", "handwritten", "duplicate", "no_vrn")
DUP_KINDS = {"new_photo": "posted receipt, new photo, same date", "exact_file": "posted receipt, identical file",
             "seeded_copy": "gold document the seed posted re-dated, fed with its own date"}
TWO_X = f"more than {autopilot.MAX_TIMES_TYPICAL}x the usual"


@dataclass
class Doc:
    """One document to feed: the image, and what a perfect reading of it says."""

    id: str
    pass_: str
    render: str  # clean | messy
    image: Callable[[], bytes]  # rendered when fed
    gold: dict[str, Any]  # gold receipt JSON, re-dated where the seed re-dated it
    gold_file: str
    dup: str = ""  # "" | "new_photo" (posted receipt, photographed again) | "exact_file" | "seeded_copy" (see documents())
    expect: str = "proposed"
    cls: str = field(init=False)

    @property
    def duplicate(self) -> bool:
        return bool(self.dup)

    def __post_init__(self) -> None:
        case = self.gold.get("gold_case") or ""
        if self.duplicate:
            self.cls = "duplicate"
        elif case in HANDWRITTEN:
            self.cls = "handwritten"
        elif not (self.gold.get("supplier") or {}).get("vat_number"):
            self.cls = "no_vrn"
        else:
            self.cls = self.render


def redated(gold: dict[str, Any], d: sd.PlannedDoc) -> dict[str, Any]:
    """The gold receipt as the seed printed it: its date, and an invoice number with any suffix."""
    return gold | {"date": d.date.isoformat(), "invoice_number": d.extracted.get("invoice_number"), "printed_text": d.text}


# --------------------------------------------------------------------------- #
# Books and rules
# --------------------------------------------------------------------------- #


async def build_books(plan: sd.Plan, golds: dict[str, dict[str, Any]]) -> tuple[FakeStorageProvider, dict[str, str]]:
    """Seeded books plus the saved rules; returns the storage and supplier key -> 'history' | 'regular'."""
    storage = FakeStorageProvider()
    await sd.seed(storage, replace(plan, inbox=[]), say=lambda _msg: None)
    books = Books(storage)
    origin: dict[str, str] = {}
    refused: dict[str, str] = {}
    for p in await books.list_proposals("posted"):  # what approve(always=True) writes, for each seeded purchase
        rule = autopilot.rule_from_proposal(p, sd.USER) if p.mileage_claim is None else None
        if rule is not None:
            await _remember(books, p, sd.USER)
            await autopilot.save_rule(books, rule)
            origin[rule.supplier_key] = "history"
    for n, (f, g) in enumerate(sorted(golds.items())):
        name = (g.get("supplier") or {}).get("name") or ""
        key = autopilot.supplier_key(name)
        if not key or key in origin or gold_side(g) != "purchase":
            continue
        prior = sd._planned(f, g, date.fromisoformat(g["date"]) - timedelta(days=91), sd.GOLD_BUSINESS, 900 + n, suffix="-prev")
        prior.file_name = f"SAMPLE prior {n:03d}.png"
        p = await sd._propose(books, prior, plan)
        try:
            await approve(books, p.id, sd.USER, always=True, rebuild=False)
        except ValueError as exc:  # EUR (ApprovalError); a credit note's negative lines (pydantic, not ApprovalError)
            refused[key] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:120]}"
            continue
        if any(r.supplier_key == key for r in await autopilot.load_rules(books)):
            origin[key] = "regular"
    if refused:
        print(f"No rule for {len(refused)} suppliers whose earlier bill could not be approved: "
              f"{Counter(refused.values()).most_common(3)}", flush=True)
    return storage, origin


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #


def documents(plan: sd.Plan, golds: dict[str, dict[str, Any]], passes: list[str], limit: int) -> list[Doc]:
    """The gold set contains the documents the seed posted (re-dated into the seeded periods, otherwise the same
    print and invoice number): fed again with their original date they are `seeded_copy` duplicates."""
    posted_golds = {d.gold for d in plan.posted}
    docs: list[Doc] = []
    if "inbox" in passes:
        for d in plan.inbox:
            docs.append(Doc(f"inbox/{d.gold}", "inbox", "clean", partial(sd.render_png, d.text), redated(golds[d.gold], d),
                            d.gold, expect=d.expect))
    for render in ("clean", "messy"):
        if render not in passes:
            continue
        for i, (f, g) in enumerate(sorted(golds.items())):
            png = partial(render_receipt, g["printed_text"], messy=render == "messy", seed=i, damage=g.get("damage"))
            docs.append(Doc(f"{render}/{f}", render, render, png, g, f, dup="seeded_copy" if f in posted_golds else "",
                            expect=expected_status(g)))
    if "dupes" in passes:
        purchases = [d for d in plan.posted if d.extracted["doc_type"] != "sales_invoice"]
        for i, d in enumerate(purchases):
            docs.append(Doc(f"dupes/photo/{d.gold}@{d.date}", "dupes", "messy", partial(render_receipt, d.text, messy=True,
                            seed=1000 + i), redated(golds[d.gold], d), d.gold, dup="new_photo"))
        for d in purchases[:EXACT_DUPES]:
            docs.append(Doc(f"dupes/exact/{d.gold}@{d.date}", "dupes", "clean", partial(sd.render_png, d.text),
                            redated(golds[d.gold], d), d.gold, dup="exact_file"))
    if limit:
        per: dict[str, int] = Counter()
        docs = [d for d in docs if (per.update([d.pass_]) or per[d.pass_] <= limit)]
    return docs


def shard_of(docs: list[Doc], k: int, n: int) -> list[Doc]:
    """The k-th of n contiguous slices of each pass (1-based)."""
    out = []
    for pass_ in PASSES:
        batch = [d for d in docs if d.pass_ == pass_]
        size = -(-len(batch) // n)
        out += batch[(k - 1) * size:k * size]
    return out


def period_of(d: Doc, plan: sd.Plan) -> tuple[date, date]:
    return period_containing(date.fromisoformat(d.gold["date"]), plan.current[0].month)


async def ideal(books: Books, d: Doc, plan: sd.Plan) -> dict[str, Any]:
    """What Autopilot decides on a perfect reading of `d` with the books as they are (duplicates aside)."""
    doc = ExtractedDoc.model_validate(extracted_from_gold(d.gold))
    start, end = period_of(d, plan)
    checks = repair(doc, sd.GOLD_BUSINESS) + run_checks(doc, known_hashes=set(), this_hash="", period_start=start, period_end=end)
    status, reasons = decide(checks)
    p = Proposal(id="ideal", doc_sha256="", extracted=doc, checks=checks, status=status, reasons=reasons,
                 suggested_filename="", journal_draft=draft_journal(doc), model="gold", elapsed_s=0)
    apply_rule(p, books.match_rule(doc, await books.load_rules()))
    rule = autopilot.match(p, await autopilot.load_rules(books))
    decision = autopilot.evaluate(p, rule)
    return {"auto_approve": decision.auto_approve, "reasons": decision.reasons, "rule": rule.supplier_key if rule else None}


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


def _money_eq(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(round(a * 100) - round(b * 100)) <= 1


def field_diffs(gold: dict[str, Any], ex: dict[str, Any], event: dict[str, Any] | None) -> list[str]:
    out = []
    if normalise_name(gold["supplier"]["name"]) != normalise_name(ex["supplier_name"]):
        out.append("supplier")
    if normalise_vat_number(gold["supplier"].get("vat_number")) != normalise_vat_number(ex["supplier_vat_number"]):
        out.append("vat_number")
    if gold["date"] != ex["date"]:
        out.append("date")
    for k, label in (("net_total", "net"), ("vat_total", "vat"), ("gross_total", "gross")):
        if not _money_eq(gold[k], ex[k]):
            out.append(label)
    if gold_side(gold) != ("sale" if ex["doc_type"] == "sales_invoice" else "purchase"):
        out.append("side")
    if event is not None:
        if event.get("net") is None or abs(event["net"] - round(gold["net_total"] * 100)) > 1:
            out.append("event_net")
        if event.get("vat") is None or abs(event["vat"] - round(gold["vat_total"] * 100)) > 1:
            out.append("event_vat")
    return out


async def feed(books: Books, d: Doc, cfg: AiConfig, plan: sd.Plan, origin: dict[str, str]) -> dict[str, Any]:
    gold_decision = await ideal(books, d, plan)
    gold_decision["rule_origin"] = origin.get(gold_decision["rule"] or "")
    name = f"{d.id.replace('/', '_').replace('@', '_')}.png"
    path = f"{INBOX}/{name}"
    await books.storage.write(path, d.image())
    period = plan.current if d.pass_ == "inbox" else period_of(d, plan)
    t0 = time.perf_counter()
    try:
        proposals, errors = await scan_inbox_detailed(books, cfg, 1, sd.GOLD_BUSINESS, True, period)
    except Exception as exc:  # recorded, not fatal: one document must not end a four-hour run
        proposals, errors = [], [{"error": f"{type(exc).__name__}: {exc}"[:300]}]
    secs = round(time.perf_counter() - t0, 2)
    rec: dict[str, Any] = {
        "id": d.id, "pass": d.pass_, "render": d.render, "class": d.cls, "gold_file": d.gold_file,
        "gold_case": d.gold.get("gold_case"), "duplicate": d.duplicate, "dup_kind": d.dup, "expected_status": d.expect,
        "seconds": secs,
        "gold_decision": gold_decision,
        "should_post": bool(gold_decision["auto_approve"] and not d.duplicate and d.expect == "proposed"),
    }
    if not proposals:
        books.storage.files.pop(path, None)  # an unreadable file stays in the Inbox; take it out so it can't block the next
        return rec | {"error": (errors[0]["error"] if errors else "no proposal"), "outcome": "error", "posted": False}
    p = proposals[0]
    posted = p.decided_by == autopilot.AUTOPILOT
    reasons = p.autopilot.reasons if p.autopilot else []
    refusals = [] if posted else reasons
    v = p.verification
    rec |= {
        "error": None,
        "proposal_id": p.id,
        "status": p.status,
        "posted": posted,
        "outcome": "would_post" if posted else ("proposed" if p.status == "proposed" else "needs_a_look"),
        "rule": p.autopilot.supplier_key if p.autopilot else None,
        "rule_origin": origin.get(p.autopilot.supplier_key or "") if p.autopilot else None,
        "autopilot_reasons": reasons,
        "two_x_refused": any(TWO_X in r for r in refusals),
        "two_x_only": bool(refusals) and all(TWO_X in r for r in refusals),
        "verifier": None if v is None else {"agree_all": v.agree_all, "error": v.error, "elapsed_s": v.elapsed_s,
                                            "differs": [k for k, f in v.fields.items() if not f.agree]},
        "extracted": p.extracted.model_dump(mode="json", include={"doc_type", "supplier_name", "supplier_vat_number", "date",
                                                                   "net_total", "vat_total", "gross_total"}),
        "event_id": p.event_id,
    }
    return rec


def grade(rec: dict[str, Any], gold: dict[str, Any], event: dict[str, Any] | None) -> None:
    """Fill in diffs, false/correct/missed post. For a document left in Review, `would_be_false` says whether
    posting it anyway would have been a false post (used for the 2x rule's effect)."""
    if rec["error"]:
        rec |= {"diffs": [], "false_post": False, "correct_post": False, "missed_post": rec["should_post"], "would_be_false": None}
        return
    diffs = field_diffs(gold, rec["extracted"], event if rec["posted"] else None)
    bad = bool(diffs) or rec["duplicate"] or rec["expected_status"] != "proposed"
    rec |= {"diffs": diffs, "false_post": rec["posted"] and bad, "correct_post": rec["posted"] and not bad,
            "missed_post": rec["should_post"] and not rec["posted"], "would_be_false": bad}


async def run_pass(base: FakeStorageProvider, origin: dict[str, str], docs: list[Doc], cfg: AiConfig, plan: sd.Plan,
                   sink: Any) -> list[dict[str, Any]]:
    books = Books(copy.deepcopy(base))
    out = []
    for i, d in enumerate(docs, start=1):
        rec = await feed(books, d, cfg, plan, origin)
        event = None
        if rec.get("event_id"):
            event = next((e.model_dump(mode="json") for e in await books.list_events() if e.id == rec["event_id"]), None)
        grade(rec, d.gold, event)
        sink.write(json.dumps(rec, ensure_ascii=False) + "\n")  # as it goes: a stopped run keeps what it did
        sink.flush()
        out.append(rec)
        mark = " FALSE POST" if rec["false_post"] else ""
        print(f"[{d.pass_} {i}/{len(docs)}] {d.id} {rec['seconds']}s {rec['outcome']}{mark}", flush=True)
    return out


async def simulate(args: argparse.Namespace) -> list[Path]:
    if args.verifier == "off":
        os.environ["VERIFIER"] = "off"
    elif (os.environ.get("VERIFIER") or "").lower() in ("off", "0", "false", "no"):
        raise SystemExit("--verifier on, but VERIFIER=off is set in the environment")
    cfg = AiConfig.resolve(mode="local", model=args.model)
    plan = sd.build_plan(sd.GOLD_BUSINESS, today=TODAY)
    golds = gold_receipts()
    t0 = time.perf_counter()
    base, origin = await build_books(plan, golds)
    print(f"Books seeded with {Counter(origin.values())} rules in {time.perf_counter() - t0:.1f}s", flush=True)
    docs = documents(plan, golds, args.passes, args.limit)
    k, n = map(int, args.shard.split("/"))
    docs = shard_of(docs, k, n) if n > 1 else docs
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for pass_ in PASSES:  # one file per pass (and shard), so each can be re-run on its own
        batch = [d for d in docs if d.pass_ == pass_]
        if not batch:
            continue
        path = out / f"verifier_{args.verifier}_{pass_}{f'_{k}of{n}' if n > 1 else ''}.jsonl"
        meta = {"verifier": args.verifier, "backend": (b.label() if (b := select_backend(cfg)) else None),
                "config": cfg.public(), "today": TODAY.isoformat(), "rules": dict(Counter(origin.values())), "pass": pass_,
                "limit": args.limit, "shard": args.shard}
        with path.open("w", encoding="utf-8") as sink:
            sink.write(json.dumps({"meta": meta}) + "\n")
            await run_pass(base, origin, batch, cfg, plan, sink)
        paths.append(path)
    return paths


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


def load(out: Path, mode: str) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Every pass file for this verifier mode, in pass order; the meta of the first, with all passes listed."""
    meta: dict[str, Any] | None = None
    recs: list[dict[str, Any]] = []
    for pass_ in PASSES:
        for path in sorted(out.glob(f"verifier_{mode}_{pass_}*.jsonl")):  # the whole pass, or its shards
            lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
            meta = meta or lines[0]["meta"] | {"passes": []}
            meta["passes"].append(path.stem.removeprefix(f"verifier_{mode}_"))
            recs += lines[1:]
    return (meta, recs) if meta else None


def tally(recs: list[dict[str, Any]], history_only: bool = False) -> dict[str, Any]:
    """Counts and rates. `history_only`: as if only the seeded history's rules existed (posts by other rules dropped)."""
    def posted(r: dict[str, Any]) -> bool:
        return r["posted"] and (not history_only or r.get("rule_origin") == "history")

    def should(r: dict[str, Any]) -> bool:
        return r["should_post"] and (not history_only or r["gold_decision"]["rule_origin"] == "history")

    n = len(recs)
    posts = sum(posted(r) for r in recs)
    false = sum(posted(r) and r["false_post"] for r in recs)
    should_n = sum(should(r) for r in recs)
    missed = sum(should(r) and not posted(r) for r in recs)
    pct = lambda k, d: round(k / d, 4) if d else None  # noqa: E731
    return {
        "docs": n, "errors": sum(bool(r["error"]) for r in recs),
        "would_post": posts, "proposed": sum(r.get("outcome") == "proposed" for r in recs),
        "needs_a_look": sum(r.get("outcome") == "needs_a_look" for r in recs),
        "false_posts": false, "correct_posts": posts - false, "should_post": should_n, "missed_posts": missed,
        "false_post_rate": pct(false, n), "false_share_of_posts": pct(false, posts), "missed_rate": pct(missed, should_n),
    }


def two_x(recs: list[dict[str, Any]]) -> dict[str, int]:
    only = [r for r in recs if r.get("two_x_only")]
    return {
        "refused_with_2x_among_reasons": sum(bool(r.get("two_x_refused")) for r in recs),
        "refused_by_2x_alone": len(only),
        "of_which_would_be_false_posts": sum(bool(r["would_be_false"]) for r in only),
        "of_which_would_be_correct_posts": sum(r["would_be_false"] is False for r in only),
    }


def times(recs: list[dict[str, Any]]) -> dict[str, float | None]:
    s = sorted(r["seconds"] for r in recs if not r["error"])
    if not s:
        return {"mean": None, "median": None, "p95": None, "max": None}
    return {"mean": round(statistics.mean(s), 1), "median": round(statistics.median(s), 1),
            "p95": round(s[min(len(s) - 1, int(0.95 * len(s)))], 1), "max": round(s[-1], 1)}


def refusal_kind(reason: str) -> str:
    if reason.startswith("Check "):
        return " ".join(reason.split()[1:3]).rstrip(":")
    for needle, kind in (("VAT number", "VAT number differs"), ("VAT treatment", "VAT treatment differs"), (TWO_X, "over 2x"),
                         ("Proposal is", "not proposed"), ("the rule is for", "side differs"), ("total is zero", "zero total")):
        if needle in reason:
            return kind
    return reason[:40]


def summarise(meta: dict[str, Any], recs: list[dict[str, Any]]) -> dict[str, Any]:
    by_class = {c: tally([r for r in recs if r["class"] == c]) for c in CLASSES}
    by_pass = {p: tally([r for r in recs if r["pass"] == p]) for p in PASSES}
    by_dup = {k: tally([r for r in recs if r.get("dup_kind") == k]) for k in DUP_KINDS}
    false = [{"id": r["id"], "class": r["class"], "diffs": r["diffs"], "duplicate": r["duplicate"],
              "expected_status": r["expected_status"], "rule_origin": r.get("rule_origin"), "extracted": r.get("extracted")}
             for r in recs if r["false_post"]]
    reasons = Counter(refusal_kind(x) for r in recs if not r["posted"] and not r["error"] and r.get("rule")
                      for x in r["autopilot_reasons"])
    return {"meta": meta, "all": tally(recs), "history_rules_only": tally(recs, history_only=True), "by_class": by_class,
            "by_pass": by_pass, "by_duplicate_kind": by_dup, "two_x": two_x(recs), "seconds": times(recs),
            "verifier_seconds": times([{"seconds": r["verifier"]["elapsed_s"], "error": None} for r in recs
                                       if r.get("verifier") and r["verifier"]["elapsed_s"]]),
            "refusal_reasons": dict(reasons.most_common()), "false_posts": false}


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f} %"


def report(out: Path) -> Path:
    runs = {}
    for mode in ("on", "off"):
        if loaded := load(out, mode):
            runs[mode] = summarise(*loaded)
    if not runs:
        raise SystemExit(f"no runs in {out}")
    (out / "summary.json").write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8")
    modes = list(runs)
    head = lambda: "| | " + " | ".join(f"verifier {m}" for m in modes) + " |\n|---|" + "---:|" * len(modes)  # noqa: E731
    row = lambda label, f: f"| {label} | " + " | ".join(f(runs[m]) for m in modes) + " |"  # noqa: E731
    a = {m: runs[m]["all"] for m in modes}
    lines = [
        "# Autopilot L2 safety eval: false posts",
        "",
        "## Headline",
        "",
        *(f"- **Verifier {m}: {runs[m]['all']['false_posts']} false posts in {runs[m]['all']['docs']} documents = "
          f"{_pct(runs[m]['all']['false_post_rate'])}** (clean documents: {runs[m]['by_class']['clean']['false_posts']}"
          f"/{runs[m]['by_class']['clean']['docs']} = {_pct(runs[m]['by_class']['clean']['false_post_rate'])}); "
          f"{a[m]['would_post']} posted, {a[m]['missed_posts']} of {a[m]['should_post']} expected posts missed."
          for m in modes),
        "",
        "A false post is a document Autopilot posted where a field differs from gold, gold says it needs a look, or the "
        "same document is already in the books. Rates are per document fed.",
        "",
        "## Overall",
        "",
        head(),
        row("Documents", lambda s: str(s["all"]["docs"])),
        row("Would post (Autopilot posted)", lambda s: str(s["all"]["would_post"])),
        row("Proposed (left in Review)", lambda s: str(s["all"]["proposed"])),
        row("Needs a look", lambda s: str(s["all"]["needs_a_look"])),
        row("Extraction errors", lambda s: str(s["all"]["errors"])),
        row("**False posts**", lambda s: f"**{s['all']['false_posts']} ({_pct(s['all']['false_post_rate'])})**"),
        row("False posts as a share of posts", lambda s: _pct(s["all"]["false_share_of_posts"])),
        row("Correct posts", lambda s: str(s["all"]["correct_posts"])),
        row("Missed posts (of expected)", lambda s: f"{s['all']['missed_posts']} of {s['all']['should_post']}"),
        row("Seeded-history rules only: false posts", lambda s: f"{s['history_rules_only']['false_posts']} of "
            f"{s['history_rules_only']['would_post']} posts"),
        "",
        "## False-post rate by document class",
        "",
        "| Class | " + " | ".join(f"docs | posted | false | rate (verifier {m})" for m in modes) + " |",
        "|---|" + "---:|---:|---:|---:|" * len(modes),
        *(f"| {c} | " + " | ".join(
            f"{runs[m]['by_class'][c]['docs']} | {runs[m]['by_class'][c]['would_post']} | {runs[m]['by_class'][c]['false_posts']} | "
            f"{_pct(runs[m]['by_class'][c]['false_post_rate'])}" for m in modes) + " |" for c in CLASSES),
        "",
        "Duplicates by kind:",
        "",
        "| Duplicate | " + " | ".join(f"docs | posted | false (verifier {m})" for m in modes) + " |",
        "|---|" + "---:|---:|---:|" * len(modes),
        *(f"| {label} | " + " | ".join(
            f"{runs[m]['by_duplicate_kind'][k]['docs']} | {runs[m]['by_duplicate_kind'][k]['would_post']} | "
            f"{runs[m]['by_duplicate_kind'][k]['false_posts']}" for m in modes) + " |" for k, label in DUP_KINDS.items()),
        "",
        "## By pass",
        "",
        "| Pass | " + " | ".join(f"docs | posted | false | missed (verifier {m})" for m in modes) + " |",
        "|---|" + "---:|---:|---:|---:|" * len(modes),
        *(f"| {p} | " + " | ".join(
            f"{runs[m]['by_pass'][p]['docs']} | {runs[m]['by_pass'][p]['would_post']} | {runs[m]['by_pass'][p]['false_posts']} | "
            f"{runs[m]['by_pass'][p]['missed_posts']}/{runs[m]['by_pass'][p]['should_post']}" for m in modes) + " |"
          for p in PASSES if any(runs[m]["by_pass"][p]["docs"] for m in modes)),
        "",
        f"## The ≤{autopilot.MAX_TIMES_TYPICAL}× typical total rule",
        "",
        head(),
        row("Refusals naming the 2× rule", lambda s: str(s["two_x"]["refused_with_2x_among_reasons"])),
        row("Refused by the 2× rule alone", lambda s: str(s["two_x"]["refused_by_2x_alone"])),
        row("… which would have been false posts", lambda s: str(s["two_x"]["of_which_would_be_false_posts"])),
        row("… which would have been correct posts", lambda s: str(s["two_x"]["of_which_would_be_correct_posts"])),
        "",
        "## Time per document (one scan of one document, seconds)",
        "",
        head(),
        *(row(k, lambda s, k=k: str(s["seconds"][k])) for k in ("mean", "median", "p95", "max")),
        row("Verifier reading, mean", lambda s: str(s["verifier_seconds"]["mean"])),
        "",
        "## Why Autopilot left rule matches in Review",
        "",
        *(f"- verifier {m}: " + ", ".join(f"{k} {v}" for k, v in list(runs[m]["refusal_reasons"].items())[:12])
          for m in modes),
        "",
        "## Every false post",
        "",
    ]
    for m in modes:
        lines.append(f"### Verifier {m}")
        lines.append("")
        fps = runs[m]["false_posts"]
        if not fps:
            lines.append("None.")
        for f in fps:
            why = ", ".join(f["diffs"]) or ("duplicate" if f["duplicate"] else f"gold: {f['expected_status']}")
            lines.append(f"- `{f['id']}` ({f['class']}, {f['rule_origin']} rule): {why}")
        lines.append("")
    meta = runs[modes[0]]["meta"]
    lines += [
        "## Set-up",
        "",
        f"Model: {meta['config']['model']} ({meta['config']['mode']}); verifier on = the same model with the verifier "
        f"prompt ({runs.get('on', {}).get('meta', {}).get('backend')}). Books: `tools/seed_demo.py` plan for "
        f"{sd.GOLD_BUSINESS}, today {meta['today']}. Rules: {meta['rules']}. Passes: {', '.join(meta['passes'])}"
        + (f", first {meta['limit']} per pass" if meta["limit"] else "") + ".",
        "",
        "Reproduce: `cd evals && python -m harness.autopilot_sim --verifier on && python -m harness.autopilot_sim "
        "--verifier off && python -m harness.autopilot_sim --report`.",
        "",
    ]
    path = out / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verifier", choices=("on", "off"), default="on")
    ap.add_argument("--passes", default=",".join(PASSES), help=f"comma-separated, from {', '.join(PASSES)}")
    ap.add_argument("--limit", type=int, default=0, help="first N documents per pass (0 = all)")
    ap.add_argument("--shard", default="1/1", help="k/n: only the k-th of n contiguous slices of each pass, each on fresh "
                    "books (for runs that must fit a time limit)")
    ap.add_argument("--model", default=None, help="override OLLAMA_MODEL")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--report", action="store_true", help="only write report.md and summary.json from the runs in --out")
    args = ap.parse_args()
    args.passes = [p for p in args.passes.split(",") if p]
    if not args.report:
        print("wrote " + ", ".join(map(str, asyncio.run(simulate(args)))))
    print(f"wrote {report(Path(args.out))}")


if __name__ == "__main__":
    main()
