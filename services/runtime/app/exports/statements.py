"""Financial statements: balance sheet, P&L with comparatives, cash flows (direct method), changes in equity,
executive summary, cash summary and the management report pack. By code from the approved ledger events.

Cash is the bank and cash accounts (codes 1200-1299). Every cash figure comes from the entries that touch them, so
the cash flow, the cash summary and the cash book agree on opening and closing cash (tests/test_exports.py).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta

from accnomos_ledger import LedgerEvent
from app import reports as rp
from app.exports.accounts import (
    BANK_RANGE,
    BASIS,
    KLASS_LABELS,
    balance_sheet,
    klass,
    movements,
    pl_comparative,
    pl_net,
)
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


def is_cash(account: str) -> bool:
    return (rp.account_code(account) or 0) in BANK_RANGE


def cash_balance(events: Sequence[LedgerEvent], end: date) -> int:
    return sum(v for a, v in movements(events, None, end).items() if is_cash(a))


def cash_events(events: Sequence[LedgerEvent], start: date, end: date) -> list[tuple[LedgerEvent, int]]:
    """(event, its effect on cash) for events in [start, end] that move cash; transfers between cash accounts net to 0
    and are left out."""
    out = []
    for e in events:
        if start <= e.date <= end:
            delta = sum(ln.debit - ln.credit for ln in e.lines if is_cash(ln.account))
            if delta:
                out.append((e, delta))
    return out


# --------------------------------------------------------------------------- #
# Statement of cash flows, direct method
# --------------------------------------------------------------------------- #

FLOW_LABELS = {
    "customers": "Receipts from customers",
    "suppliers": "Payments to suppliers",
    "payroll": "Payments to employees and HMRC for payroll",
    "vat": "VAT paid to or refunded by HMRC",
    "other_operating": "Other operating cash flows",
    "assets": "Purchase or sale of fixed assets",
    "financing": "Owner and loan funding (net)",
}
SECTIONS = (
    ("Operating activities", ("customers", "suppliers", "payroll", "vat", "other_operating")),
    ("Investing activities", ("assets",)),
    ("Financing activities", ("financing",)),
)


def flow_of(e: LedgerEvent) -> str:
    """Which cash-flow line an event's whole cash effect goes on: the line of its biggest non-cash leg."""
    legs = [ln for ln in e.lines if not is_cash(ln.account)]
    if not legs:
        return "other_operating"
    big = max(legs, key=lambda ln: (ln.debit + ln.credit, ln.account))
    code = rp.account_code(big.account)
    k = klass(big.account)
    if k == "sales" or code == 1100:
        return "customers"
    if code == 2200:
        return "vat"
    if code == 2210 or (code is not None and 7000 <= code <= 7099):
        return "payroll"
    if k in ("cost_of_sales", "overheads") or code == 2100:
        return "suppliers"
    if k == "fixed_assets":
        return "assets"
    if k == "capital" or (code is not None and 2300 <= code <= 2999):
        return "financing"
    return "other_operating"


FLOW_COLUMNS = columns(("line", "Line"), ("amount", "Amount", "money"))


def cash_flow(events: Sequence[LedgerEvent], start: date, end: date) -> tuple[Section, dict[str, int]]:
    by: dict[str, int] = defaultdict(int)
    for e, delta in cash_events(events, start, end):
        by[flow_of(e)] += delta
    opening = cash_balance(events, start - timedelta(days=1))
    rows: list[Row] = []
    net = 0
    for title, keys in SECTIONS:
        rows.append(Row(cells={"line": title}, style="heading"))
        sub = 0
        for k in keys:
            rows.append(Row(cells={"line": f"  {FLOW_LABELS[k]}", "amount": by.get(k, 0)}))
            sub += by.get(k, 0)
        rows.append(Row(cells={"line": f"Net cash from {title.lower()}", "amount": sub}, style="subtotal"))
        net += sub
    rows += [
        Row(cells={"line": "Net change in cash", "amount": net}, style="total"),
        Row(cells={"line": f"Cash at {uk_day(start - timedelta(days=1))}", "amount": opening}),
        Row(cells={"line": f"Cash at {uk_day(end)}", "amount": opening + net}, style="total"),
    ]
    note = (
        "Direct method: each entry that moves bank or cash (codes 1200-1299) goes, whole, on the line of its biggest "
        "other leg (a sale paid at once is a receipt from a customer, VAT included). Transfers between your own "
        "accounts are left out."
    )
    return Section(title="Statement of cash flows (direct method)", columns=FLOW_COLUMNS, rows=rows, note=note), {
        "opening": opening,
        "net": net,
        "closing": opening + net,
    }


# --------------------------------------------------------------------------- #
# Statement of changes in equity
# --------------------------------------------------------------------------- #

EQUITY_COLUMNS = columns(
    ("line", "Line"),
    ("capital", "Capital", "money"),
    ("retained", "Retained earnings", "money"),
    ("total", "Total", "money"),
)


def changes_in_equity(events: Sequence[LedgerEvent], start: date, end: date) -> tuple[Section, int]:
    before = start - timedelta(days=1)
    cap_open = -sum(v for a, v in movements(events, None, before).items() if klass(a) == "capital")
    ret_open = pl_net(events, None, before)
    introduced = drawn = 0
    for e in events:
        if start <= e.date <= end:
            for ln in e.lines:
                if klass(ln.account) == "capital":
                    introduced += ln.credit
                    drawn += ln.debit
    profit = pl_net(events, start, end)
    cap_close = cap_open + introduced - drawn
    ret_close = ret_open + profit
    rows = [
        Row(
            cells={
                "line": f"Balance at {uk_day(before)}",
                "capital": cap_open,
                "retained": ret_open,
                "total": cap_open + ret_open,
            }
        ),
        Row(cells={"line": "Profit (loss) for the period", "capital": 0, "retained": profit, "total": profit}),
        Row(cells={"line": "Capital introduced", "capital": introduced, "retained": 0, "total": introduced}),
        Row(cells={"line": "Drawings and distributions", "capital": -drawn, "retained": 0, "total": -drawn}),
        Row(
            cells={
                "line": f"Balance at {uk_day(end)}",
                "capital": cap_close,
                "retained": ret_close,
                "total": cap_close + ret_close,
            },
            style="total",
        ),
    ]
    note = (
        "Capital is the 3000-3999 accounts (credits introduce capital, debits are drawings or distributions); "
        "retained earnings are every profit and loss since the books began. A director's or owner's loan "
        "(2300) is a liability, not equity."
    )
    return Section(
        title="Statement of changes in equity", columns=EQUITY_COLUMNS, rows=rows, note=note
    ), cap_close + ret_close


# --------------------------------------------------------------------------- #
# Cash summary
# --------------------------------------------------------------------------- #


def cash_summary(events: Sequence[LedgerEvent], start: date, end: date) -> Section:
    """Cash in and out by the account on the other side: each cash entry's other legs, credit − debit, so the lines
    add up to the net change in cash exactly."""
    by: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e, _ in cash_events(events, start, end):
        for ln in e.lines:
            if not is_cash(ln.account):
                by[klass(ln.account)][ln.account] += ln.credit - ln.debit
    opening = cash_balance(events, start - timedelta(days=1))
    rows: list[Row] = [Row(cells={"line": f"Opening cash at {uk_day(start - timedelta(days=1))}", "amount": opening})]
    net = 0
    for k in (
        "sales",
        "cost_of_sales",
        "overheads",
        "current_assets",
        "current_liabilities",
        "capital",
        "fixed_assets",
        "unclassified",
    ):
        if not by.get(k):
            continue
        rows.append(Row(cells={"line": KLASS_LABELS[k]}, style="heading"))
        sub = 0
        for account, v in sorted(by[k].items(), key=lambda kv: (rp.account_code(kv[0]) or 0, kv[0])):
            rows.append(Row(cells={"line": f"  {account}", "amount": v}))
            sub += v
        rows.append(Row(cells={"line": f"Total {KLASS_LABELS[k].lower()}", "amount": sub}, style="subtotal"))
        net += sub
    rows += [
        Row(cells={"line": "Net cash movement", "amount": net}, style="total"),
        Row(cells={"line": f"Closing cash at {uk_day(end)}", "amount": opening + net}, style="total"),
    ]
    return Section(
        title="Cash summary",
        columns=FLOW_COLUMNS,
        rows=rows,
        note="Money in is positive, money out negative, by the account each payment or receipt was posted against.",
    )


# --------------------------------------------------------------------------- #
# Executive summary
# --------------------------------------------------------------------------- #

EXEC_COLUMNS = columns(
    ("measure", "Measure"), ("now", "This period"), ("prev", "Previous period"), ("change", "Change")
)


def _gbp(p: int) -> str:
    return f"{'-' if p < 0 else ''}£{abs(p) / 100:,.2f}"


def _pct(n: int, d: int) -> str:
    return "—" if d == 0 else f"{n / d * 100:.1f}%"


def _figures(events: Sequence[LedgerEvent], start: date, end: date) -> dict[str, int | float | None]:
    pl = rp.profit_and_loss(events, start, end)
    days = (end - start).days + 1
    bal = movements(events, None, end)
    debtors = bal.get("1100 Debtors", 0) + sum(
        v for a, v in bal.items() if (rp.account_code(a) or 0) in range(1101, 1200)
    )
    creditors = -sum(v for a, v in bal.items() if (rp.account_code(a) or 0) in range(2100, 2200))
    flows = cash_events(events, start, end)
    _, f = balance_sheet(events, start, end)
    costs = pl.cost_of_sales.total_pence + pl.overheads.total_pence
    return {
        "cash_open": cash_balance(events, start - timedelta(days=1)),
        "cash_close": cash_balance(events, end),
        "received": sum(d for _, d in flows if d > 0),
        "spent": -sum(d for _, d in flows if d < 0),
        "income": pl.sales.total_pence,
        "direct": pl.cost_of_sales.total_pence,
        "gross": pl.gross_profit_pence,
        "overheads": pl.overheads.total_pence,
        "net": pl.net_profit_pence,
        "debtors": debtors,
        "creditors": creditors,
        "net_assets": f.net_assets,
        "debtor_days": round(debtors / pl.sales.total_pence * days) if pl.sales.total_pence > 0 else None,
        "creditor_days": round(creditors / costs * days) if costs > 0 else None,
    }


def executive_summary(events: Sequence[LedgerEvent], span: tuple[date, date], prev: tuple[date, date]) -> Section:
    a, b = _figures(events, *span), _figures(events, *prev)
    rows: list[Row] = []

    def money(label: str, key: str) -> None:
        x, y = int(a[key] or 0), int(b[key] or 0)
        rows.append(Row(cells={"measure": label, "now": _gbp(x), "prev": _gbp(y), "change": _pct(x - y, abs(y))}))

    def days(label: str, key: str) -> None:
        x, y = a[key], b[key]
        show = lambda v: "—" if v is None else f"{v} days"  # noqa: E731
        change = "—" if x is None or y is None else f"{int(x) - int(y):+d} days"
        rows.append(Row(cells={"measure": label, "now": show(x), "prev": show(y), "change": change}))

    rows.append(Row(cells={"measure": "Cash"}, style="heading"))
    money("Cash at the start", "cash_open")
    money("Cash received", "received")
    money("Cash spent", "spent")
    money("Cash at the end", "cash_close")
    rows.append(Row(cells={"measure": "Profitability"}, style="heading"))
    money("Income", "income")
    money("Direct costs", "direct")
    money("Gross profit", "gross")
    rows.append(
        Row(
            cells={
                "measure": "Gross margin",
                "now": _pct(int(a["gross"] or 0), int(a["income"] or 0)),
                "prev": _pct(int(b["gross"] or 0), int(b["income"] or 0)),
                "change": "",
            }
        )
    )
    money("Overheads", "overheads")
    money("Net profit", "net")
    rows.append(Row(cells={"measure": "Balance sheet (at the period end)"}, style="heading"))
    money("Debtors", "debtors")
    money("Creditors", "creditors")
    money("Net assets", "net_assets")
    rows.append(Row(cells={"measure": "Performance"}, style="heading"))
    days("Debtor days (debtors ÷ income × days)", "debtor_days")
    days("Creditor days (creditors ÷ costs × days)", "creditor_days")
    return Section(
        title="Executive summary",
        columns=EXEC_COLUMNS,
        rows=rows,
        note=f"This period {span_label(*span)}; previous {span_label(*prev)}. Change is against the previous period.",
    )


# --------------------------------------------------------------------------- #
# Registered reports
# --------------------------------------------------------------------------- #


async def build_balance_sheet(ctx: ExportContext) -> ReportDoc:
    events = await ctx.events()
    section, f = balance_sheet(events, ctx.start, ctx.end)
    warnings = []
    if f.net_assets != f.equity:  # cannot happen while every event balances; said out loud if it ever does
        warnings.append(f"Net assets and capital and reserves differ by {(f.net_assets - f.equity) / 100:,.2f}.")
    if f.by_klass["unclassified"]:
        warnings.append("Some accounts have no four-digit code; they are shown as unclassified.")
    return doc_from(
        "balance-sheet",
        "Balance sheet",
        f"at {uk_day(ctx.end)}",
        [section],
        basis=[BASIS, "Balance-sheet accounts by code; no year-end has been closed, so earlier profit is one line."],
        warnings=warnings,
        sample=rp.is_sample(events),
    )


async def build_pl(ctx: ExportContext) -> ReportDoc:
    events = await ctx.events()
    section, _ = pl_comparative(events, (ctx.start, ctx.end), ctx.previous, ctx.last_year)
    return doc_from(
        "profit-and-loss",
        "Profit and loss",
        span_label(ctx.start, ctx.end),
        [section],
        basis=[BASIS],
        sample=rp.is_sample(events),
    )


async def build_cash_flow(ctx: ExportContext) -> ReportDoc:
    events = await ctx.events()
    section, _ = cash_flow(events, ctx.start, ctx.end)
    return doc_from(
        "cash-flow", "Statement of cash flows", span_label(ctx.start, ctx.end), [section], sample=rp.is_sample(events)
    )


async def build_equity(ctx: ExportContext) -> ReportDoc:
    events = await ctx.events()
    section, _ = changes_in_equity(events, ctx.start, ctx.end)
    return doc_from(
        "changes-in-equity",
        "Statement of changes in equity",
        span_label(ctx.start, ctx.end),
        [section],
        sample=rp.is_sample(events),
    )


async def build_executive(ctx: ExportContext) -> ReportDoc:
    events = await ctx.events()
    return doc_from(
        "executive-summary",
        "Executive summary",
        span_label(ctx.start, ctx.end),
        [executive_summary(events, (ctx.start, ctx.end), ctx.previous)],
        basis=[BASIS],
        sample=rp.is_sample(events),
    )


async def build_cash_summary(ctx: ExportContext) -> ReportDoc:
    events = await ctx.events()
    return doc_from(
        "cash-summary",
        "Cash summary",
        span_label(ctx.start, ctx.end),
        [cash_summary(events, ctx.start, ctx.end)],
        sample=rp.is_sample(events),
    )


async def build_management(ctx: ExportContext) -> ReportDoc:
    from app.contacts import aged
    from app.exports.receivables import aged_summary
    from app.exports.vat_reports import vat_return_section

    events = await ctx.events()
    pl, _ = pl_comparative(events, (ctx.start, ctx.end), ctx.previous, ctx.last_year)
    bs, _ = balance_sheet(events, ctx.start, ctx.end)
    balances = aged(await ctx.contacts(), await ctx.ledger(), ctx.end)
    vat, _ = vat_return_section(events, ctx.start, ctx.end, ctx.cycle.months)
    return doc_from(
        "management-report",
        "Management report",
        span_label(ctx.start, ctx.end),
        [
            executive_summary(events, (ctx.start, ctx.end), ctx.previous),
            pl,
            bs,
            aged_summary(balances.debtors, f"Aged receivables at {uk_day(ctx.end)}"),
            aged_summary(balances.creditors, f"Aged payables at {uk_day(ctx.end)}"),
            vat,
        ],
        basis=[BASIS, "The VAT figures are the 9 boxes for the report's own dates, which may not be a VAT period."],
        sample=rp.is_sample(events),
    )


for _spec in (
    ExportSpec(
        "balance-sheet",
        "financial",
        "Balance sheet",
        "Assets, liabilities, capital and reserves at the period end.",
        build_balance_sheet,
    ),
    ExportSpec(
        "profit-and-loss",
        "financial",
        "Profit and loss",
        "With the previous period and the same period last year.",
        build_pl,
    ),
    ExportSpec(
        "cash-flow",
        "financial",
        "Statement of cash flows (direct method)",
        "Cash from operating, investing and financing activities.",
        build_cash_flow,
    ),
    ExportSpec(
        "changes-in-equity",
        "financial",
        "Statement of changes in equity",
        "Capital and retained earnings, start to end.",
        build_equity,
    ),
    ExportSpec(
        "executive-summary",
        "financial",
        "Executive summary",
        "Cash, profitability, balance sheet and debtor and creditor days.",
        build_executive,
    ),
    ExportSpec(
        "cash-summary",
        "financial",
        "Cash summary",
        "Cash in and out by the account it was posted against.",
        build_cash_summary,
    ),
    ExportSpec(
        "management-report",
        "financial",
        "Management report",
        "Executive summary, P&L, balance sheet, aged balances and VAT in one.",
        build_management,
    ),
):
    register(_spec)
