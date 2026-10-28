"""Core accounting reports, by code from the approved ledger events.

Accounts are placed by their four-digit code (the chart in app/journal.py, laid out like Sage's UK default):

    0001-0999  Fixed assets            debit balance
    1000-1999  Current assets          debit balance   (1100 Debtors, 1200 Bank, 1210 Cash)
    2000-2999  Current liabilities     credit balance  (2100 Creditors, 2200 VAT control, 2210 Payroll, 2300 Owner loan)
    3000-3999  Capital and reserves    credit balance
    4000-8999  Profit and loss         as app/reports.py (sales, cost of sales, overheads)
    anything else (no code, 9xxx)      unclassified: shown on its own line so nothing disappears

There is no year-end close in the books. A report for a period therefore takes balance-sheet accounts cumulatively
to the period's end and profit-and-loss accounts for the period only, and the profit made before the period is one
line, RETAINED ("3200 Profit and loss brought forward"). That makes the trial balance balance, the balance sheet's
profit for the period equal the P&L's net profit, and the general ledger's closing balances equal the trial balance.
tests/test_exports.py proves all three.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Literal

from accnomos_ledger import LedgerEvent
from app import reports as rp
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

Klass = Literal[
    "fixed_assets",
    "current_assets",
    "current_liabilities",
    "capital",
    "sales",
    "cost_of_sales",
    "overheads",
    "unclassified",
]
KLASS_LABELS: dict[str, str] = {
    "fixed_assets": "Fixed assets",
    "current_assets": "Current assets",
    "current_liabilities": "Current liabilities",
    "capital": "Capital and reserves",
    "sales": "Sales",
    "cost_of_sales": "Cost of sales",
    "overheads": "Overheads",
    "unclassified": "Unclassified (no account code)",
}
RETAINED = "3200 Profit and loss brought forward"
PL_KLASSES = {"sales", "cost_of_sales", "overheads"}
BANK_RANGE = range(1200, 1300)


def klass(account: str) -> Klass:
    code = rp.account_code(account)
    if code is None:
        return "unclassified"
    if code < 1000:
        return "fixed_assets"
    if code < 2000:
        return "current_assets"
    if code < 3000:
        return "current_liabilities"
    if code < 4000:
        return "capital"
    sec = rp.section_of(account)
    return sec if sec is not None else "unclassified"


def is_pl(account: str) -> bool:
    return klass(account) in PL_KLASSES


def split_account(account: str) -> tuple[str, str]:
    """'7500 Office supplies' -> ('7500', 'Office supplies'); no code -> ('', account)."""
    code = rp.account_code(account)
    if code is None:
        return "", account.strip()
    return account.strip()[:4], account.strip()[4:].strip()


def _sort_key(account: str) -> tuple[int, str]:
    code = rp.account_code(account)
    return (code if code is not None else 99_999, account)


def movements(events: Iterable[LedgerEvent], start: date | None = None, end: date | None = None) -> dict[str, int]:
    """Account -> debits − credits (pence) for events dated in [start, end] (either end open)."""
    out: dict[str, int] = defaultdict(int)
    for e in events:
        if (start is not None and e.date < start) or (end is not None and e.date > end):
            continue
        for ln in e.lines:
            out[ln.account] += ln.debit - ln.credit
    return out


def period_balances(events: Sequence[LedgerEvent], start: date, end: date) -> dict[str, int]:
    """Balance-sheet accounts to `end`, P&L accounts for [start, end], and RETAINED (debit − credit, so a profit
    before the period is negative). The values sum to zero, because every event balances."""
    out: dict[str, int] = defaultdict(int)
    before = 0
    for account, v in movements(events, None, end).items():
        if not is_pl(account):
            out[account] += v
    for account, v in movements(events, None, start.fromordinal(start.toordinal() - 1)).items():
        if is_pl(account):
            before += v
    for account, v in movements(events, start, end).items():
        if is_pl(account):
            out[account] += v
    if before:
        out[RETAINED] += before
    return {a: v for a, v in out.items() if v}


def pl_net(events: Iterable[LedgerEvent], start: date | None, end: date | None) -> int:
    """Net profit (positive) from P&L accounts in [start, end]."""
    return -sum(v for a, v in movements(events, start, end).items() if is_pl(a))


# --------------------------------------------------------------------------- #
# Trial balance
# --------------------------------------------------------------------------- #

TB_COLUMNS = columns(
    ("code", "Code"), ("account", "Account"), ("debit", "Debit", "money"), ("credit", "Credit", "money")
)


def trial_balance(events: Sequence[LedgerEvent], start: date, end: date) -> Section:
    rows: list[Row] = []
    dr = cr = 0
    for account, v in sorted(period_balances(events, start, end).items(), key=lambda kv: _sort_key(kv[0])):
        code, name = split_account(account)
        rows.append(
            Row(cells={"code": code, "account": name, "debit": v if v > 0 else None, "credit": -v if v < 0 else None})
        )
        dr += max(v, 0)
        cr += max(-v, 0)
    rows.append(Row(cells={"code": "", "account": "Total", "debit": dr, "credit": cr}, style="total"))
    return Section(
        title="Trial balance",
        columns=TB_COLUMNS,
        rows=rows,
        note=(
            f"Balance-sheet accounts to {uk_day(end)}; profit-and-loss accounts for {span_label(start, end)}. "
            f"Profit before {uk_day(start)} is one line, {RETAINED}."
        ),
    )


# --------------------------------------------------------------------------- #
# General ledger
# --------------------------------------------------------------------------- #

GL_COLUMNS = columns(
    ("account", "Account"),
    ("date", "Date", "date"),
    ("entry", "Entry"),
    ("details", "Details"),
    ("reference", "Reference"),
    ("debit", "Debit", "money"),
    ("credit", "Credit", "money"),
    ("balance", "Balance", "money"),
)


def details(ev: LedgerEvent, memo: str | None = None) -> str:
    who = ev.counterparty or ""
    what = {"purchase": "Purchase", "sale": "Sale", "bank": "Bank", "adjustment": "Adjustment", "reversal": "Reversal"}
    parts = [what.get(ev.kind, ev.kind), who, memo or ""]
    if ev.kind == "reversal" and ev.reverses:
        parts.append(f"undoes {ev.reverses[:8]}")
    return " · ".join(p for p in parts if p)


def general_ledger(events: Sequence[LedgerEvent], start: date, end: date, refs: dict[str, str]) -> Section:
    opening: dict[str, int] = defaultdict(int)
    for account, v in movements(events, None, start.fromordinal(start.toordinal() - 1)).items():
        opening[RETAINED if is_pl(account) else account] += v
    lines: dict[str, list[tuple[LedgerEvent, int, int, str | None]]] = defaultdict(list)
    for e in sorted(events, key=lambda e: (e.date, e.approved_at, e.id)):
        if start <= e.date <= end:
            for ln in e.lines:
                lines[ln.account].append((e, ln.debit, ln.credit, ln.memo))
    rows: list[Row] = []
    accounts = sorted({a for a, v in opening.items() if v} | set(lines), key=_sort_key)
    for account in accounts:
        bal = opening.get(account, 0)
        rows.append(Row(cells={"account": account}, style="heading"))
        rows.append(Row(cells={"account": account, "details": "Opening balance", "balance": bal}))
        dr = cr = 0
        for e, d, c, memo in lines.get(account, []):
            bal += d - c
            dr += d
            cr += c
            rows.append(
                Row(
                    cells={
                        "account": account,
                        "date": e.date.isoformat(),
                        "entry": e.id[:8],
                        "details": details(e, memo),
                        "reference": refs.get(e.id, ""),
                        "debit": d or None,
                        "credit": c or None,
                        "balance": bal,
                    }
                )
            )
        rows.append(
            Row(
                cells={"account": account, "details": "Closing balance", "debit": dr, "credit": cr, "balance": bal},
                style="subtotal",
            )
        )
    return Section(
        title="General ledger",
        columns=GL_COLUMNS,
        rows=rows,
        note="Balances are debit positive. Profit-and-loss accounts open at zero; earlier profit is in "
        f"{RETAINED}, as on the trial balance.",
    )


# --------------------------------------------------------------------------- #
# Balance sheet
# --------------------------------------------------------------------------- #

BS_COLUMNS = columns(("line", "Line"), ("amount", "Amount", "money"))


class BalanceSheetFigures:
    def __init__(self, events: Sequence[LedgerEvent], start: date, end: date) -> None:
        bal = period_balances(events, start, end)
        self.by_klass: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for account, v in sorted(bal.items(), key=lambda kv: _sort_key(kv[0])):
            if account == RETAINED or is_pl(account):
                continue
            k = klass(account)
            sign = 1 if k in ("fixed_assets", "current_assets", "unclassified") else -1
            self.by_klass[k].append((account, sign * v))
        self.fixed = sum(v for _, v in self.by_klass["fixed_assets"])
        self.current = sum(v for _, v in self.by_klass["current_assets"])
        self.unclassified = sum(v for _, v in self.by_klass["unclassified"])
        self.liabilities = sum(v for _, v in self.by_klass["current_liabilities"])
        self.net_current = self.current + self.unclassified - self.liabilities
        self.net_assets = self.fixed + self.net_current
        self.capital = sum(v for _, v in self.by_klass["capital"])
        self.brought_forward = -bal.get(RETAINED, 0)
        self.profit = pl_net(events, start, end)
        self.equity = self.capital + self.brought_forward + self.profit


def balance_sheet(events: Sequence[LedgerEvent], start: date, end: date) -> tuple[Section, BalanceSheetFigures]:
    f = BalanceSheetFigures(events, start, end)
    rows: list[Row] = []

    def block(k: str, total_label: str, total: int) -> None:
        rows.append(Row(cells={"line": KLASS_LABELS[k]}, style="heading"))
        for account, v in f.by_klass[k]:
            rows.append(Row(cells={"line": f"  {account}", "amount": v}))
        rows.append(Row(cells={"line": total_label, "amount": total}, style="subtotal"))

    block("fixed_assets", "Total fixed assets", f.fixed)
    block("current_assets", "Total current assets", f.current)
    if f.by_klass["unclassified"]:
        block("unclassified", "Total unclassified", f.unclassified)
    block("current_liabilities", "Total current liabilities", f.liabilities)
    rows.append(Row(cells={"line": "Net current assets", "amount": f.net_current}, style="subtotal"))
    rows.append(Row(cells={"line": "Net assets", "amount": f.net_assets}, style="total"))
    rows.append(Row(cells={"line": KLASS_LABELS["capital"]}, style="heading"))
    for account, v in f.by_klass["capital"]:
        rows.append(Row(cells={"line": f"  {account}", "amount": v}))
    rows.append(
        Row(cells={"line": f"  Profit and loss brought forward (before {uk_day(start)})", "amount": f.brought_forward})
    )
    rows.append(Row(cells={"line": f"  Profit for the period ({span_label(start, end)})", "amount": f.profit}))
    rows.append(Row(cells={"line": "Total capital and reserves", "amount": f.equity}, style="total"))
    return Section(title=f"Balance sheet at {uk_day(end)}", columns=BS_COLUMNS, rows=rows), f


# --------------------------------------------------------------------------- #
# P&L with comparatives
# --------------------------------------------------------------------------- #

PLC_COLUMNS = columns(
    ("line", "Line"),
    ("now", "This period", "money"),
    ("prev", "Previous period", "money"),
    ("last", "Same period last year", "money"),
    ("change", "Change vs previous", "money"),
)


def pl_comparative(
    events: Sequence[LedgerEvent], span: tuple[date, date], prev: tuple[date, date], last: tuple[date, date]
) -> tuple[Section, rp.ProfitAndLoss]:
    now, was, year = (rp.profit_and_loss(events, *s) for s in (span, prev, last))
    rows: list[Row] = []

    def amounts(pl: rp.ProfitAndLoss, which: str) -> dict[str, int]:
        sec: rp.PlSection = getattr(pl, which)
        return {r.account: r.amount_pence for r in sec.rows}

    for title, which in (
        ("Sales", "sales"),
        ("Cost of sales", "cost_of_sales"),
        (None, "gross"),
        ("Overheads", "overheads"),
    ):
        if which == "gross":
            g = (now.gross_profit_pence, was.gross_profit_pence, year.gross_profit_pence)
            rows.append(
                Row(
                    cells={"line": "Gross profit", "now": g[0], "prev": g[1], "last": g[2], "change": g[0] - g[1]},
                    style="total",
                )
            )
            continue
        rows.append(Row(cells={"line": title}, style="heading"))
        a, b, c = amounts(now, which), amounts(was, which), amounts(year, which)
        for account in sorted(set(a) | set(b) | set(c), key=_sort_key):
            n, p, y = a.get(account, 0), b.get(account, 0), c.get(account, 0)
            rows.append(Row(cells={"line": f"  {account}", "now": n, "prev": p, "last": y, "change": n - p}))
        t = tuple(getattr(pl, which).total_pence for pl in (now, was, year))
        rows.append(
            Row(
                cells={
                    "line": f"Total {(title or '').lower()}",
                    "now": t[0],
                    "prev": t[1],
                    "last": t[2],
                    "change": t[0] - t[1],
                },
                style="subtotal",
            )
        )
    n = (now.net_profit_pence, was.net_profit_pence, year.net_profit_pence)
    rows.append(
        Row(
            cells={
                "line": "Net profit (loss negative)",
                "now": n[0],
                "prev": n[1],
                "last": n[2],
                "change": n[0] - n[1],
            },
            style="total",
        )
    )
    note = f"This period {span_label(*span)}; previous {span_label(*prev)}; last year {span_label(*last)}."
    return Section(title="Profit and loss", columns=PLC_COLUMNS, rows=rows, note=note), now


# --------------------------------------------------------------------------- #
# Cash book, journal listing, audit trail, fixed assets and expenses
# --------------------------------------------------------------------------- #

CASH_COLUMNS = columns(
    ("account", "Account"),
    ("date", "Date", "date"),
    ("details", "Details"),
    ("reference", "Reference"),
    ("in", "Money in", "money"),
    ("out", "Money out", "money"),
    ("balance", "Balance", "money"),
)


def cash_book(events: Sequence[LedgerEvent], start: date, end: date, refs: dict[str, str]) -> Section:
    accounts = sorted(
        {ln.account for e in events for ln in e.lines if (rp.account_code(ln.account) or 0) in BANK_RANGE},
        key=_sort_key,
    )
    rows: list[Row] = []
    for account in accounts:
        bal = movements(events, None, start.fromordinal(start.toordinal() - 1)).get(account, 0)
        rows.append(Row(cells={"account": account}, style="heading"))
        rows.append(Row(cells={"account": account, "details": "Opening balance", "balance": bal}))
        got = paid = 0
        for e in sorted(events, key=lambda e: (e.date, e.approved_at, e.id)):
            if not start <= e.date <= end:
                continue
            for ln in e.lines:
                if ln.account != account:
                    continue
                bal += ln.debit - ln.credit
                got += ln.debit
                paid += ln.credit
                rows.append(
                    Row(
                        cells={
                            "account": account,
                            "date": e.date.isoformat(),
                            "details": details(e, ln.memo),
                            "reference": refs.get(e.id, e.id[:8]),
                            "in": ln.debit or None,
                            "out": ln.credit or None,
                            "balance": bal,
                        }
                    )
                )
        rows.append(
            Row(
                cells={"account": account, "details": "Closing balance", "in": got, "out": paid, "balance": bal},
                style="subtotal",
            )
        )
    return Section(
        title="Cash book",
        columns=CASH_COLUMNS,
        rows=rows,
        note="Bank and cash accounts (codes 1200-1299) as the ledger records them. Reconcile against your statements.",
    )


JOURNAL_COLUMNS = columns(
    ("date", "Date", "date"),
    ("entry", "Entry"),
    ("kind", "Kind"),
    ("account", "Account"),
    ("details", "Details"),
    ("debit", "Debit", "money"),
    ("credit", "Credit", "money"),
    ("vat", "VAT code"),
)


def journal_listing(events: Sequence[LedgerEvent], start: date, end: date) -> Section:
    rows: list[Row] = []
    dr = cr = 0
    for e in sorted((e for e in events if start <= e.date <= end), key=lambda e: (e.date, e.approved_at, e.id)):
        rows.append(
            Row(
                cells={"date": e.date.isoformat(), "entry": e.id[:8], "kind": e.kind, "details": details(e)},
                style="heading",
            )
        )
        for ln in e.lines:
            dr += ln.debit
            cr += ln.credit
            rows.append(
                Row(
                    cells={
                        "date": e.date.isoformat(),
                        "entry": e.id[:8],
                        "kind": e.kind,
                        "account": ln.account,
                        "details": ln.memo or "",
                        "debit": ln.debit or None,
                        "credit": ln.credit or None,
                        "vat": ln.vat_code.value if ln.vat_code else "",
                    }
                )
            )
    rows.append(Row(cells={"account": "Total", "debit": dr, "credit": cr}, style="total"))
    return Section(title="Journal listing", columns=JOURNAL_COLUMNS, rows=rows)


AUDIT_COLUMNS = columns(
    ("approved_at", "Posted (UTC)"),
    ("approved_by", "Approved by"),
    ("date", "Entry date", "date"),
    ("entry", "Entry id"),
    ("kind", "Kind"),
    ("counterparty", "Counterparty"),
    ("amount", "Amount", "money"),
    ("proposal", "Review card"),
    ("links", "Reverses / credits"),
    ("evidence", "Evidence (document sha256)"),
    ("file", "Ledger file"),
)


def audit_trail(events: Sequence[LedgerEvent], start: date, end: date, paths: dict[str, str]) -> Section:
    rows: list[Row] = []
    for e in sorted((e for e in events if start <= e.date <= end), key=lambda e: (e.approved_at, e.id)):
        rows.append(
            Row(
                cells={
                    "approved_at": f"{e.approved_at:%d/%m/%Y %H:%M}",
                    "approved_by": e.approved_by,
                    "date": e.date.isoformat(),
                    "entry": e.id,
                    "kind": e.kind,
                    "counterparty": e.counterparty or "",
                    "amount": sum(ln.debit for ln in e.lines),
                    "proposal": e.proposal_id or "",
                    "links": e.reverses or e.credits or "",
                    "evidence": ", ".join(e.evidence),
                    "file": paths.get(e.id, ""),
                }
            )
        )
    return Section(
        title="Audit trail of postings",
        columns=AUDIT_COLUMNS,
        rows=rows,
        note="Every posted entry, in the order it was approved. Entries are never edited: a correction is a new entry "
        "that reverses the old one. Agents never approve; the approver is the signed-in person.",
    )


# --------------------------------------------------------------------------- #
# Aged debtors and creditors, document by document
# --------------------------------------------------------------------------- #

AGED_COLUMNS = columns(
    ("name", "Name"),
    ("reference", "Reference"),
    ("date", "Date", "date"),
    ("due", "Due", "date"),
    ("age", "Days overdue", "int"),
    ("bucket", "Age band"),
    ("gross", "Document total", "money"),
    ("owed", "Outstanding", "money"),
)
BUCKET_LABELS = {
    "current": "Not yet due",
    "0-30": "1-30 days",
    "31-60": "31-60 days",
    "61-90": "61-90 days",
    "90+": "Over 90 days",
}


def aged_detail(table: object, title: str) -> Section:
    from app.contacts import AgedTable

    assert isinstance(table, AgedTable)
    rows: list[Row] = []
    for r in table.rows:
        for d in sorted(r.documents, key=lambda d: (d.date, d.event_id)):
            rows.append(
                Row(
                    cells={
                        "name": r.name,
                        "reference": d.reference or d.event_id[:8],
                        "date": d.date.isoformat(),
                        "due": d.due_date.isoformat(),
                        "age": d.age_days,
                        "bucket": BUCKET_LABELS.get(d.bucket, d.bucket),
                        "gross": d.gross_pence,
                        "owed": d.amount_pence,
                    }
                )
            )
        rows.append(Row(cells={"name": f"Total {r.name}", "owed": r.total_pence}, style="subtotal"))
    rows.append(Row(cells={"name": "Total", "owed": table.total_pence}, style="total"))
    bands = ", ".join(f"{BUCKET_LABELS[b]} {table.buckets[b] / 100:,.2f}" for b in BUCKET_LABELS)
    return Section(title=title, columns=AGED_COLUMNS, rows=rows, note=f"By age band (£): {bands}.")


# --------------------------------------------------------------------------- #
# Trial balance by date range, general ledger summary, account transactions, exceptions
# --------------------------------------------------------------------------- #

RANGE_COLUMNS = columns(
    ("code", "Code"),
    ("account", "Account"),
    ("opening", "Opening balance", "money"),
    ("debit", "Debits", "money"),
    ("credit", "Credits", "money"),
    ("closing", "Closing balance", "money"),
)


def trial_balance_range(events: Sequence[LedgerEvent], start: date, end: date) -> Section:
    """Opening balance, debits, credits and closing balance per account for [start, end] (debit positive). Opening
    and closing follow the trial balance's convention, so the closing column is the trial balance."""
    day_before = start.fromordinal(start.toordinal() - 1)
    opening: dict[str, int] = defaultdict(int)
    for account, v in movements(events, None, day_before).items():
        opening[RETAINED if is_pl(account) else account] += v
    dr: dict[str, int] = defaultdict(int)
    cr: dict[str, int] = defaultdict(int)
    for e in events:
        if start <= e.date <= end:
            for ln in e.lines:
                dr[ln.account] += ln.debit
                cr[ln.account] += ln.credit
    rows: list[Row] = []
    totals = [0, 0, 0, 0]
    for account in sorted({a for a, v in opening.items() if v} | set(dr) | set(cr), key=_sort_key):
        o, d, c = opening.get(account, 0), dr.get(account, 0), cr.get(account, 0)
        code, name = split_account(account)
        rows.append(
            Row(cells={"code": code, "account": name, "opening": o, "debit": d, "credit": c, "closing": o + d - c})
        )
        for i, v in enumerate((o, d, c, o + d - c)):
            totals[i] += v
    rows.append(
        Row(
            cells={
                "account": "Total",
                "opening": totals[0],
                "debit": totals[1],
                "credit": totals[2],
                "closing": totals[3],
            },
            style="total",
        )
    )
    return Section(
        title="Trial balance by date range",
        columns=RANGE_COLUMNS,
        rows=rows,
        note="Debit positive, credit negative. Opening and closing totals are zero and debits equal credits when the "
        "books balance.",
    )


SUMMARY_COLUMNS = columns(
    ("code", "Code"),
    ("account", "Account"),
    ("type", "Type"),
    ("debit", "Debits", "money"),
    ("credit", "Credits", "money"),
    ("net", "Net movement", "money"),
    ("closing", "Closing balance", "money"),
)


def general_ledger_summary(events: Sequence[LedgerEvent], start: date, end: date) -> Section:
    tb = trial_balance_range(events, start, end)
    rows = []
    for r in tb.rows:
        c = r.cells
        if r.style == "total":
            rows.append(Row(cells={**c, "net": int(c["debit"] or 0) - int(c["credit"] or 0)}, style="total"))
            continue
        account = f"{c['code']} {c['account']}".strip()
        rows.append(
            Row(
                cells={
                    "code": c["code"],
                    "account": c["account"],
                    "type": KLASS_LABELS[klass(account)] if account != RETAINED else "Capital and reserves",
                    "debit": c["debit"],
                    "credit": c["credit"],
                    "net": int(c["debit"] or 0) - int(c["credit"] or 0),
                    "closing": c["closing"],
                }
            )
        )
    return Section(title="General ledger summary", columns=SUMMARY_COLUMNS, rows=rows)


TXN_COLUMNS = columns(
    ("account", "Account"),
    ("date", "Date", "date"),
    ("details", "Details"),
    ("reference", "Reference"),
    ("debit", "Debit", "money"),
    ("credit", "Credit", "money"),
    ("vat", "VAT code"),
    ("entry", "Entry"),
)


def account_transactions(events: Sequence[LedgerEvent], start: date, end: date, refs: dict[str, str]) -> Section:
    lines = [(ln.account, e, ln) for e in events if start <= e.date <= end for ln in e.lines]
    lines.sort(key=lambda t: (_sort_key(t[0]), t[1].date, t[1].approved_at, t[1].id))
    rows: list[Row] = []
    dr = cr = 0
    for account, e, ln in lines:
        dr += ln.debit
        cr += ln.credit
        rows.append(
            Row(
                cells={
                    "account": account,
                    "date": e.date.isoformat(),
                    "details": details(e, ln.memo),
                    "reference": refs.get(e.id, ""),
                    "debit": ln.debit or None,
                    "credit": ln.credit or None,
                    "vat": ln.vat_code.value if ln.vat_code else "",
                    "entry": e.id[:8],
                }
            )
        )
    rows.append(Row(cells={"account": "Total", "debit": dr, "credit": cr}, style="total"))
    return Section(title="Account transactions", columns=TXN_COLUMNS, rows=rows)


EXCEPTION_COLUMNS = columns(
    ("rule", "Rule"),
    ("date", "Date", "date"),
    ("entry", "Entry"),
    ("account", "Account"),
    ("amount", "Amount", "money"),
    ("why", "Why it is flagged"),
)
#: A whole number of pounds at or above this is a "round amount" (estimates and transfers often are; receipts rarely).
ROUND_FROM_PENCE = 50_000
ROUND_STEP_PENCE = 10_000
LATE_DAYS = 90
#: Debit-normal account classes; a credit balance on one of them (or a debit balance on any other) is unexpected.
DEBIT_NORMAL = {"fixed_assets", "current_assets", "cost_of_sales", "overheads"}


def ledger_exceptions(events: Sequence[LedgerEvent], start: date, end: date) -> Section:
    """Postings worth a second look, flagged by fixed rules. A flag is a prompt to check, not an error."""
    rows: list[Row] = []
    inside = sorted((e for e in events if start <= e.date <= end), key=lambda e: (e.date, e.id))
    for e in inside:
        gross = sum(ln.debit for ln in e.lines)
        if gross >= ROUND_FROM_PENCE and gross % ROUND_STEP_PENCE == 0:
            rows.append(
                Row(
                    cells={
                        "rule": "Round amount",
                        "date": e.date.isoformat(),
                        "entry": e.id[:8],
                        "account": "",
                        "amount": gross,
                        "why": f"{details(e)}: a whole multiple of £100",
                    }
                )
            )
        if e.date.weekday() >= 5:
            rows.append(
                Row(
                    cells={
                        "rule": "Weekend date",
                        "date": e.date.isoformat(),
                        "entry": e.id[:8],
                        "account": "",
                        "amount": gross,
                        "why": f"{details(e)}: dated on a {e.date:%A}",
                    }
                )
            )
        late = (e.approved_at.date() - e.date).days
        if late > LATE_DAYS:
            rows.append(
                Row(
                    cells={
                        "rule": "Late posting",
                        "date": e.date.isoformat(),
                        "entry": e.id[:8],
                        "account": "",
                        "amount": gross,
                        "why": f"approved {late} days after its date",
                    }
                )
            )
        for ln in e.lines:
            if klass(ln.account) == "unclassified":
                rows.append(
                    Row(
                        cells={
                            "rule": "No account code",
                            "date": e.date.isoformat(),
                            "entry": e.id[:8],
                            "account": ln.account,
                            "amount": ln.debit or -ln.credit,
                            "why": "the account has no four-digit code, so no report can place it",
                        }
                    )
                )
    for account, v in sorted(period_balances(events, start, end).items(), key=lambda kv: _sort_key(kv[0])):
        k = klass(account)
        if account == RETAINED or k == "unclassified" or (k == "sales" and v < 0) or (k == "capital"):
            continue
        if (k in DEBIT_NORMAL) != (v > 0):
            side = "credit" if v < 0 else "debit"
            rows.append(
                Row(
                    cells={
                        "rule": "Unexpected sign",
                        "date": end.isoformat(),
                        "entry": "",
                        "account": account,
                        "amount": v,
                        "why": f"{KLASS_LABELS[k].lower()} account with a {side} balance",
                    }
                )
            )
    return Section(
        title="General ledger exceptions",
        columns=EXCEPTION_COLUMNS,
        rows=rows,
        note=f"Rules: round amounts (£{ROUND_FROM_PENCE // 100:,} or more, whole £100s), weekend dates, approval more "
        f"than {LATE_DAYS} days after the entry date, accounts with no code, and balances on the unexpected side "
        "(for example an overdrawn bank or a negative expense) at the period end. Amounts are debit positive.",
    )


# --------------------------------------------------------------------------- #
# Registered reports
# --------------------------------------------------------------------------- #

BASIS = rp.BASIS


async def _refs(ctx: ExportContext) -> dict[str, str]:
    return (await ctx.ledger()).refs


def _one(
    spec_id: str, title: str, ctx: ExportContext, section: Section, events: Sequence[LedgerEvent], **kw: object
) -> ReportDoc:
    return doc_from(spec_id, title, span_label(ctx.start, ctx.end), [section], sample=rp.is_sample(events), **kw)  # type: ignore[arg-type]


async def build_trial_balance(ctx: ExportContext) -> ReportDoc:
    ev = await ctx.events()
    return _one("trial-balance", "Trial balance", ctx, trial_balance(ev, ctx.start, ctx.end), ev, basis=[BASIS])


async def build_trial_balance_range(ctx: ExportContext) -> ReportDoc:
    ev = await ctx.events()
    return _one(
        "trial-balance-range",
        "Trial balance by date range",
        ctx,
        trial_balance_range(ev, ctx.start, ctx.end),
        ev,
        basis=[BASIS],
    )


async def build_general_ledger(ctx: ExportContext) -> ReportDoc:
    ev = await ctx.events()
    return _one(
        "general-ledger",
        "General ledger detail",
        ctx,
        general_ledger(ev, ctx.start, ctx.end, await _refs(ctx)),
        ev,
        basis=[BASIS],
    )


async def build_general_ledger_summary(ctx: ExportContext) -> ReportDoc:
    ev = await ctx.events()
    return _one(
        "general-ledger-summary",
        "General ledger summary",
        ctx,
        general_ledger_summary(ev, ctx.start, ctx.end),
        ev,
        basis=[BASIS],
    )


async def build_exceptions(ctx: ExportContext) -> ReportDoc:
    ev = await ctx.events()
    return _one(
        "general-ledger-exceptions", "General ledger exceptions", ctx, ledger_exceptions(ev, ctx.start, ctx.end), ev
    )


async def build_journal(ctx: ExportContext) -> ReportDoc:
    ev = await ctx.events()
    return _one("journal-report", "Journal report", ctx, journal_listing(ev, ctx.start, ctx.end), ev)


async def build_audit(ctx: ExportContext) -> ReportDoc:
    ev = await ctx.events()
    return _one(
        "audit-trail", "Audit trail of postings", ctx, audit_trail(ev, ctx.start, ctx.end, await ctx.event_paths()), ev
    )


async def build_account_transactions(ctx: ExportContext) -> ReportDoc:
    ev = await ctx.events()
    return _one(
        "account-transactions",
        "Account transactions",
        ctx,
        account_transactions(ev, ctx.start, ctx.end, await _refs(ctx)),
        ev,
    )


async def build_cash_book(ctx: ExportContext) -> ReportDoc:
    ev = await ctx.events()
    return _one("cash-book", "Cash book", ctx, cash_book(ev, ctx.start, ctx.end, await _refs(ctx)), ev)


for _spec in (
    ExportSpec(
        "trial-balance",
        "taxes",
        "Trial balance",
        "Debit and credit balance per account at the period end; totals agree.",
        build_trial_balance,
    ),
    ExportSpec(
        "trial-balance-range",
        "taxes",
        "Trial balance by date range",
        "Opening balance, debits, credits and closing balance per account.",
        build_trial_balance_range,
    ),
    ExportSpec(
        "general-ledger",
        "taxes",
        "General ledger detail",
        "Every line by account, with opening, running and closing balances.",
        build_general_ledger,
    ),
    ExportSpec(
        "general-ledger-summary",
        "taxes",
        "General ledger summary",
        "Debits, credits, net movement and closing balance per account.",
        build_general_ledger_summary,
    ),
    ExportSpec(
        "general-ledger-exceptions",
        "taxes",
        "General ledger exceptions",
        "Round amounts, weekend dates, late postings and balances on the unexpected side.",
        build_exceptions,
    ),
    ExportSpec("journal-report", "taxes", "Journal report", "Every posted entry with its lines.", build_journal),
    ExportSpec(
        "account-transactions",
        "transactions",
        "Account transactions",
        "Every ledger line in the period, by account.",
        build_account_transactions,
    ),
    ExportSpec(
        "audit-trail",
        "transactions",
        "Audit trail of postings",
        "Who approved each entry, when, and from which document.",
        build_audit,
    ),
    ExportSpec(
        "cash-book",
        "reconciliations",
        "Cash book",
        "Money in and out of bank and cash accounts, with balances.",
        build_cash_book,
    ),
):
    register(_spec)
