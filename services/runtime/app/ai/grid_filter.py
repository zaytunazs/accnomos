"""Plain words to a grid filter for the Power grid add-on's ledger explorer (apps/web LedgerExplorer.tsx).

The user types "PayPal fees over £5 in October"; the user's AI returns strict JSON: a few conditions (column, operator,
value) and a sort. Code then checks every one against an allowlist of columns and operators for that grid and builds
the AG Grid filter model itself; nothing the model wrote is passed through as-is. The web checks it again
(lib/grid-core.ts validateGridFilter) before it reaches the grid.

The model can only narrow what is shown: there is no write, no posting, no tool. If no AI is set up, the model cannot be
reached, or nothing it proposed survives the checks, the words come back as `quick_filter` (a plain search), with the
reason.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.ai.ask import call_json_model
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError, parse_model_json
from app.schemas import strict_json_schema

ColKind = Literal["text", "number", "date"]

#: The ledger explorer's columns (keep in step with apps/web/src/lib/grid-core.ts LEDGER_COLUMNS). Money in pounds.
LEDGER_COLUMNS: dict[str, tuple[ColKind, str]] = {
    "date": ("date", "the date of the entry"),
    "account": ("text", 'the ledger account, code and name, e.g. "7900 Bank charges"'),
    "counterparty": ("text", "the supplier, customer or payee"),
    "memo": ("text", "the line's description"),
    "kind": ("text", "the kind of entry, e.g. receipt, invoice, paypal, bank, manual journal"),
    "vat_code": ("text", "VAT code letter: S, R, Z, E, O or N"),
    "debit": ("number", "debit amount in pounds"),
    "credit": ("number", "credit amount in pounds"),
    "amount": ("number", "the line's amount in pounds, whichever side it is on"),
}
GRIDS: dict[str, dict[str, tuple[ColKind, str]]] = {"ledger": LEDGER_COLUMNS}

OPS: dict[ColKind, tuple[str, ...]] = {
    "text": ("contains", "notContains", "equals", "notEqual", "startsWith", "endsWith"),
    "number": ("equals", "notEqual", "greaterThan", "greaterThanOrEqual", "lessThan", "lessThanOrEqual", "inRange"),
    "date": ("equals", "notEqual", "greaterThan", "lessThan", "inRange"),
}
MAX_CONDITIONS = 8
MAX_PER_COLUMN = 2  # AG Grid's default maxNumConditions
MAX_SORT = 3
TEXT_MAX = 100
MONEY_MAX = 100_000_000.0
ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Condition(BaseModel):
    column: str = Field(max_length=40)
    op: str = Field(max_length=30)
    value: str = Field(max_length=TEXT_MAX)
    value_to: str | None = Field(default=None, max_length=TEXT_MAX)


class SortSpec(BaseModel):
    column: str = Field(max_length=40)
    direction: Literal["asc", "desc"]


class ModelOutput(BaseModel):
    conditions: list[Condition] = Field(max_length=MAX_CONDITIONS * 2)
    sort: list[SortSpec] = Field(max_length=MAX_SORT * 2)
    summary: str = Field(max_length=200)


class GridFilterResult(BaseModel):
    filter_model: dict[str, Any]
    sort: list[dict[str, str]]
    quick_filter: str | None
    summary: str
    dropped: list[str]
    model: str
    fallback_reason: str | None = None


def system_prompt(grid: str) -> str:
    cols = GRIDS[grid]
    lines = "\n".join(f"- {cid} ({kind}): {desc}" for cid, (kind, desc) in cols.items())
    ops = "\n".join(f"- {kind}: {', '.join(o)}" for kind, o in OPS.items())
    return (
        "You turn a UK small business owner's request into a filter and sort for a grid of their ledger lines. "
        "You never change data: you only choose which rows are shown and in what order.\n"
        f"COLUMNS:\n{lines}\nOPERATORS by column type:\n{ops}\n"
        "Rules: 1) Use only the columns and operators listed. 2) Money values are plain pounds as a number in text, "
        'e.g. "5" or "1250.50", never with £. 3) Dates are YYYY-MM-DD; a month or year is one inRange condition with '
        "value the first day and value_to the last day; a month with no year means the most recent one on or before "
        "TODAY. 4) For text use contains unless the user is exact; match ACCOUNTS names where the user means an "
        "account (fees on PayPal are usually in a bank charges account with PayPal as the counterparty). "
        "5) value_to only for inRange, else null. 6) summary: one short plain sentence of what is shown. "
        "7) If nothing fits, return no conditions. Return JSON with conditions, sort and summary."
    )


def _day(v: str | None) -> str | None:
    if not v or not ISO_DAY.match(v.strip()):
        return None
    try:
        return date.fromisoformat(v.strip()).isoformat()
    except ValueError:
        return None


def _number(v: str | None) -> float | None:
    if v is None:
        return None
    try:
        n = float(v.strip().replace(",", "").lstrip("£"))
    except ValueError:
        return None
    if n != n or abs(n) > MONEY_MAX:  # NaN or absurd
        return None
    return int(n) if n.is_integer() else round(n, 2)


def _condition(kind: ColKind, c: Condition) -> dict[str, Any] | None:
    if c.op not in OPS[kind]:
        return None
    if kind == "text":
        text = c.value.strip()
        return {"filterType": "text", "type": c.op, "filter": text} if text else None
    if kind == "number":
        f = _number(c.value)
        if f is None:
            return None
        if c.op != "inRange":
            return {"filterType": "number", "type": c.op, "filter": f}
        to = _number(c.value_to)
        return (
            None if to is None or to < f else {"filterType": "number", "type": "inRange", "filter": f, "filterTo": to}
        )
    d = _day(c.value)
    if d is None:
        return None
    if c.op != "inRange":
        return {"filterType": "date", "type": c.op, "dateFrom": f"{d} 00:00:00", "dateTo": None}
    to_day = _day(c.value_to)
    if to_day is None or to_day < d:
        return None
    return {"filterType": "date", "type": "inRange", "dateFrom": f"{d} 00:00:00", "dateTo": f"{to_day} 00:00:00"}


def build(grid: str, out: ModelOutput) -> tuple[dict[str, Any], list[dict[str, str]], list[str]]:
    """The AG Grid filter model and sort from the model's output: only allowlisted columns and operators survive."""
    cols = GRIDS[grid]
    dropped: list[str] = []
    per_col: dict[str, list[dict[str, Any]]] = {}
    for n, c in enumerate(out.conditions):
        if n >= MAX_CONDITIONS:
            dropped.append(f"{c.column[:40]} (more than {MAX_CONDITIONS} conditions)")
            continue
        spec = cols.get(c.column)
        built = _condition(spec[0], c) if spec else None
        if built is None:
            dropped.append(f"{c.column[:40]} {c.op[:30]}".strip())
            continue
        conds = per_col.setdefault(c.column, [])
        if len(conds) >= MAX_PER_COLUMN:
            dropped.append(f"{c.column} (more than {MAX_PER_COLUMN} conditions)")
            continue
        conds.append(built)
    model: dict[str, Any] = {}
    for col, conds in per_col.items():
        model[col] = (
            conds[0] if len(conds) == 1 else {"filterType": cols[col][0], "operator": "AND", "conditions": conds}
        )
    sort: list[dict[str, str]] = []
    for s in out.sort:
        if s.column not in cols or any(x["colId"] == s.column for x in sort):
            dropped.append(f"sort by {s.column[:40]}")
            continue
        if len(sort) < MAX_SORT:
            sort.append({"colId": s.column, "sort": s.direction})
    return model, sort, dropped


def _fallback(text: str, model: str, reason: str) -> GridFilterResult:
    return GridFilterResult(
        filter_model={}, sort=[], quick_filter=text, summary="", dropped=[], model=model, fallback_reason=reason
    )


async def grid_filter(grid: str, text: str, today: date, accounts: list[str], cfg: AiConfig | None) -> GridFilterResult:
    """Never raises: on any trouble the words come back as a plain search, with the reason."""
    text = text.strip()
    if cfg is None:
        return _fallback(text, "code", "No AI is set up, so this is a plain search.")
    user = f"TODAY: {today.isoformat()}\nACCOUNTS: {json.dumps(accounts[:300], ensure_ascii=False)}\nREQUEST: {text}"
    messages = [{"role": "system", "content": system_prompt(grid)}, {"role": "user", "content": user}]
    try:
        raw = await call_json_model(messages, cfg, strict_json_schema(ModelOutput), "grid_filter")
        out = ModelOutput.model_validate(parse_model_json(raw))
    except (ExtractionError, ValidationError):
        return _fallback(text, cfg.model, "The AI's reply was not in the expected format, so this is a plain search.")
    except Exception as exc:  # noqa: BLE001  any model trouble: a plain search still works
        return _fallback(text, cfg.model, f"Your AI ({cfg.mode}) could not be reached ({type(exc).__name__}).")
    model, sort, dropped = build(grid, out)
    if not model and not sort:
        r = _fallback(text, cfg.model, "The AI found no filter it could use, so this is a plain search.")
        r.dropped = dropped
        return r
    return GridFilterResult(
        filter_model=model,
        sort=sort,
        quick_filter=None,
        summary=out.summary.strip()[:200],
        dropped=dropped,
        model=cfg.model,
    )
