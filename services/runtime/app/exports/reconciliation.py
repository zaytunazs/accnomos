"""Reconciliations: account summary, bank reconciliation, bank summary, uncoded and duplicate statement lines.

Statement lines are the ones imported on the Bank page (Books.stored_bank_lines, read once with the ledger). The books
keep one statement feed, matched against 1200 Bank, so the bank reconciliation is for that account. Matching is the
user's (or a confirmed suggestion's): this report reads it, never changes it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta

from accnomos_ledger import LedgerEvent
from accnomos_ledger.bank import BankLine
from app import reports as rp
from app.deadlines import add_months
from app.exports.accounts import _sort_key, details, movements
from app.exports.registry import (
    ExportContext,
    ExportSpec,
    ReportDoc,
    Row,
    Section,
    columns,
    doc_from,
    register,
    span_label,
    uk_day,
)
from app.exports.statements import is_cash
from app.journal import BANK

MONTH_COLUMNS = columns(
    ("account", "Account"),
    ("month", "Month"),
    ("opening", "Opening", "money"),
    ("debit", "Debits", "money"),
    ("credit", "Credits", "money"),
    ("closing", "Closing", "money"),
)


def account_summary(events: Sequence[LedgerEvent], start: date, end: date) -> Section:
    """Each account month by month: opening, debits, credits, closing (debit positive, cumulative from the start of
    the books, so profit-and-loss accounts show their running total too)."""
    accounts = sorted({ln.account for e in events if e.date <= end for ln in e.lines}, key=_sort_key)
    months: list[tuple[date, date]] = []
    m = date(start.year, start.month, 1)
    while m <= end:
        months.append((max(m, start), min(add_months(m, 1) - timedelta(days=1), end)))
        m = add_months(m, 1)
    rows: list[Row] = []
    for account in accounts:
        bal = movements(events, None, start - timedelta(days=1)).get(account, 0)
        block: list[Row] = []
        for s, e in months:
            dr = sum(ln.debit for ev in events if s <= ev.date <= e for ln in ev.lines if ln.account == account)
            cr = sum(ln.credit for ev in events if s <= ev.date <= e for ln in ev.lines if ln.account == account)
            block.append(
                Row(
                    cells={
                        "account": account,
                        "month": f"{s:%b %Y}",
                        "opening": bal,
                        "debit": dr,
                        "credit": cr,
                        "closing": bal + dr - cr,
                    }
                )
            )
            bal += dr - cr
        if any(r.cells["debit"] or r.cells["credit"] or r.cells["opening"] for r in block):
            rows.append(Row(cells={"account": account}, style="heading"))
            rows += block
    return Section(
        title="Account summary",
        columns=MONTH_COLUMNS,
        rows=rows,
        note="Debit positive. Balances run from the start of the books.",
    )


BANK_SUMMARY_COLUMNS = columns(
    ("account", "Account"),
    ("opening", "Opening balance", "money"),
    ("in", "Cash received", "money"),
    ("out", "Cash spent", "money"),
    ("closing", "Closing balance", "money"),
)


def bank_summary(events: Sequence[LedgerEvent], start: date, end: date) -> Section:
    accounts = sorted({ln.account for e in events for ln in e.lines if is_cash(ln.account)}, key=_sort_key)
    rows: list[Row] = []
    t = [0, 0, 0, 0]
    for account in accounts:
        opening = movements(events, None, start - timedelta(days=1)).get(account, 0)
        got = sum(ln.debit for e in events if start <= e.date <= end for ln in e.lines if ln.account == account)
        paid = sum(ln.credit for e in events if start <= e.date <= end for ln in e.lines if ln.account == account)
        rows.append(
            Row(cells={"account": account, "opening": opening, "in": got, "out": paid, "closing": opening + got - paid})
        )
        for i, v in enumerate((opening, got, paid, opening + got - paid)):
            t[i] += v
    rows.append(
        Row(cells={"account": "Total", "opening": t[0], "in": t[1], "out": t[2], "closing": t[3]}, style="total")
    )
    return Section(
        title="Bank summary",
        columns=BANK_SUMMARY_COLUMNS,
        rows=rows,
        note="Transfers between your own accounts count on both.",
    )


LINE_COLUMNS = columns(
    ("date", "Date", "date"),
    ("description", "Description"),
    ("reference", "Reference"),
    ("amount", "Amount", "money"),
    ("status", "Status"),
    ("file", "Statement file"),
)


def _line_row(ln: BankLine) -> Row:
    return Row(
        cells={
            "date": ln.date.isoformat(),
            "description": ln.description,
            "reference": ln.reference or "",
            "amount": ln.amount_pence,
            "status": ln.status,
            "file": ln.source_file,
        }
    )


def uncoded_lines(lines: Sequence[BankLine], start: date, end: date) -> Section:
    picked = sorted(
        (ln for ln in lines if ln.status == "unmatched" and start <= ln.date <= end), key=lambda ln: (ln.date, ln.id)
    )
    rows = [_line_row(ln) for ln in picked]
    rows.append(
        Row(
            cells={"description": f"Total ({len(picked)} lines)", "amount": sum(ln.amount_pence for ln in picked)},
            style="total",
        )
    )
    return Section(
        title="Uncoded statement lines",
        columns=LINE_COLUMNS,
        rows=rows,
        note="Statement lines not yet matched to an entry, marked a transfer or ignored. Money out is negative.",
    )


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def duplicate_lines(lines: Sequence[BankLine], start: date, end: date) -> Section:
    groups: dict[tuple[date, int, str], list[BankLine]] = defaultdict(list)
    for ln in lines:
        if start <= ln.date <= end:
            groups[(ln.date, ln.amount_pence, _norm(ln.description))].append(ln)
    rows: list[Row] = []
    for key in sorted(k for k, v in groups.items() if len(v) > 1):
        same = groups[key]
        rows.append(
            Row(
                cells={"description": f"{len(same)} lines alike", "date": key[0].isoformat(), "amount": key[1]},
                style="heading",
            )
        )
        rows += [_line_row(ln) for ln in sorted(same, key=lambda ln: (ln.source_file, ln.id))]
    return Section(
        title="Duplicate statement lines",
        columns=LINE_COLUMNS,
        rows=rows,
        note="Lines with the same date, amount and description (ignoring case and punctuation). Two real payments can "
        "look alike: check against the bank's own statement before removing either.",
    )


REC_COLUMNS = columns(("line", "Line"), ("date", "Date", "date"), ("amount", "Amount", "money"))


def bank_reconciliation(
    events: Sequence[LedgerEvent], lines: Sequence[BankLine], end: date
) -> tuple[Section, int | None]:
    """1200 Bank at `end` against the imported statement: (section, difference or None when the statement shows no
    running balance)."""
    ledger_balance = movements(events, None, end).get(BANK, 0)
    upto = sorted((ln for ln in lines if ln.date <= end), key=lambda ln: (ln.date, ln.id))
    matched = {
        eid for ln in upto for eid in [*ln.matched_event_ids, *([ln.matched_event_id] if ln.matched_event_id else [])]
    }
    first = upto[0].date if upto else None
    unmatched = [ln for ln in upto if ln.status == "unmatched"]
    unpresented = [
        (e, sum(ln.debit - ln.credit for ln in e.lines if ln.account == BANK))
        for e in events
        if first is not None
        and first <= e.date <= end
        and e.id not in matched
        and any(ln.account == BANK for ln in e.lines)
    ]
    with_balance = [ln for ln in upto if ln.balance_pence is not None]
    statement = with_balance[-1].balance_pence if with_balance else None
    rows: list[Row] = [
        Row(
            cells={"line": f"Balance in the books ({BANK}) at {uk_day(end)}", "amount": ledger_balance},
            style="subtotal",
        )
    ]
    rows.append(Row(cells={"line": "Plus statement lines not yet in the books"}, style="heading"))
    for ln in unmatched:
        rows.append(Row(cells={"line": f"  {ln.description}", "date": ln.date.isoformat(), "amount": ln.amount_pence}))
    rows.append(Row(cells={"line": "Less entries in the books not on the statement"}, style="heading"))
    for e, v in sorted(unpresented, key=lambda t: (t[0].date, t[0].id)):
        rows.append(Row(cells={"line": f"  {details(e)}", "date": e.date.isoformat(), "amount": -v}))
    expected = ledger_balance + sum(ln.amount_pence for ln in unmatched) - sum(v for _, v in unpresented)
    rows.append(Row(cells={"line": "Balance the statement should show", "amount": expected}, style="total"))
    diff: int | None = None
    if statement is not None:
        rows.append(
            Row(
                cells={
                    "line": "Balance on the statement",
                    "date": with_balance[-1].date.isoformat(),
                    "amount": statement,
                }
            )
        )
        diff = statement - expected
        rows.append(Row(cells={"line": "Difference (should be nil)", "amount": diff}, style="total"))
    else:
        rows.append(
            Row(cells={"line": "The imported statement has no running balance: compare with your bank's own figure."})
        )
    note = (
        "Entries before the first imported statement line are not listed. Statement lines marked a transfer or "
        "ignored count as dealt with."
    )
    return Section(title="Bank reconciliation", columns=REC_COLUMNS, rows=rows, note=note), diff


async def _bank_lines(ctx: ExportContext) -> list[BankLine]:
    return (await ctx.ledger()).bank_lines


async def build_account_summary(ctx: ExportContext) -> ReportDoc:
    ev = await ctx.events()
    return doc_from(
        "account-summary",
        "Account summary",
        span_label(ctx.start, ctx.end),
        [account_summary(ev, ctx.start, ctx.end)],
        sample=rp.is_sample(ev),
    )


async def build_bank_rec(ctx: ExportContext) -> ReportDoc:
    ev = await ctx.events()
    section, diff = bank_reconciliation(ev, await _bank_lines(ctx), ctx.as_of)
    warnings = [f"The statement and the books differ by {diff / 100:,.2f}."] if diff else []
    return doc_from(
        "bank-reconciliation",
        "Bank reconciliation",
        f"at {uk_day(ctx.as_of)}",
        [section],
        warnings=warnings,
        sample=rp.is_sample(ev),
    )


async def build_bank_summary(ctx: ExportContext) -> ReportDoc:
    ev = await ctx.events()
    return doc_from(
        "bank-summary",
        "Bank summary",
        span_label(ctx.start, ctx.end),
        [bank_summary(ev, ctx.start, ctx.end)],
        sample=rp.is_sample(ev),
    )


async def build_uncoded(ctx: ExportContext) -> ReportDoc:
    ev = await ctx.events()
    return doc_from(
        "uncoded-statement-lines",
        "Uncoded statement lines",
        span_label(ctx.start, ctx.end),
        [uncoded_lines(await _bank_lines(ctx), ctx.start, ctx.end)],
        sample=rp.is_sample(ev),
    )


async def build_duplicates(ctx: ExportContext) -> ReportDoc:
    ev = await ctx.events()
    return doc_from(
        "duplicate-statement-lines",
        "Duplicate statement lines",
        span_label(ctx.start, ctx.end),
        [duplicate_lines(await _bank_lines(ctx), ctx.start, ctx.end)],
        sample=rp.is_sample(ev),
    )


for _spec in (
    ExportSpec(
        "account-summary",
        "reconciliations",
        "Account summary",
        "Each account month by month: opening, debits, credits, closing.",
        build_account_summary,
    ),
    ExportSpec(
        "bank-reconciliation",
        "reconciliations",
        "Bank reconciliation",
        "The books' bank balance against the imported statement.",
        build_bank_rec,
        params=("as_of",),
    ),
    ExportSpec(
        "bank-summary",
        "reconciliations",
        "Bank summary",
        "Opening, received, spent and closing per bank and cash account.",
        build_bank_summary,
    ),
    ExportSpec(
        "uncoded-statement-lines",
        "reconciliations",
        "Uncoded statement lines",
        "Statement lines not yet matched or explained.",
        build_uncoded,
    ),
    ExportSpec(
        "duplicate-statement-lines",
        "reconciliations",
        "Duplicate statement lines",
        "Statement lines that look imported twice.",
        build_duplicates,
    ),
):
    register(_spec)
