"""Tax summary, for books kept outside the UK (app/region.py): the tax charged on sales against the tax paid on
purchases, month by month over the chosen period, and the net position. It is what a GST, VAT or sales-tax return
outside the UK starts from; Accnomos files nothing for these countries, it only gives the figures and the CSV.

Worked out by code from the approved ledger entries, the same way the UK VAT return finds them
(accnomos_ledger.vat_side: a sale or purchase, its reversal, a manual journal with tax): the tax is what reached
2200 VAT control (named for the books' own tax), the net is the event's own net.
"""

from __future__ import annotations

from datetime import date

from accnomos_ledger import LedgerEvent, vat_side
from app.deadlines import MONTHS, add_months
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
)
from app.journal import VAT_CONTROL
from app.region import rules_for

ID = "tax-summary"


def _months(start: date, end: date) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    first = start.replace(day=1)
    while first <= end:
        nxt = add_months(first, 1)
        out.append((max(first, start), min(end, date.fromordinal(nxt.toordinal() - 1))))
        first = nxt
    return out


def figures(events: list[LedgerEvent], start: date, end: date) -> list[dict[str, str | int | None]]:
    """One row per calendar month in [start, end]: sales and purchases net, tax on each, and the net tax."""
    rows: list[dict[str, str | int | None]] = []
    for s, e in _months(start, end):
        sales_net = sales_tax = buy_net = buy_tax = 0
        for ev in events:
            if ev.date < s or ev.date > e:
                continue
            side = vat_side(ev)
            if side is None:
                continue
            where, sign = side
            on_control = [ln for ln in ev.lines if ln.account == VAT_CONTROL]
            net = sign * abs(ev.net or 0)
            if where == "sales":
                sales_net += net
                sales_tax += sum(ln.credit - ln.debit for ln in on_control)
            else:
                buy_net += net
                buy_tax += sum(ln.debit - ln.credit for ln in on_control)
        rows.append(
            {
                "month": f"{MONTHS[s.month - 1]} {s.year}",
                "sales_net": sales_net,
                "sales_tax": sales_tax,
                "purchases_net": buy_net,
                "purchases_tax": buy_tax,
                "net_tax": sales_tax - buy_tax,
            }
        )
    return rows


async def build(ctx: ExportContext) -> ReportDoc:
    rules = await rules_for(ctx.books)
    name = rules.label
    events = await ctx.events()
    rows = figures(events, ctx.start, ctx.end)
    keys = ("sales_net", "sales_tax", "purchases_net", "purchases_tax", "net_tax")
    total = {k: sum(int(r[k] or 0) for r in rows) for k in keys}
    cols = columns(
        ("month", "Month"),
        ("sales_net", "Sales (net)", "money"),
        ("sales_tax", f"{name} on sales", "money"),
        ("purchases_net", "Purchases (net)", "money"),
        ("purchases_tax", f"{name} on purchases", "money"),
        ("net_tax", f"Net {name} (positive: to pay)", "money"),
    )
    body = [Row(cells=r) for r in rows] + [Row(cells={"month": "Total", **total}, style="total")]
    owe = total["net_tax"]
    position = (
        f"Net position: {name} to pay {owe / 100:,.2f} {rules.currency}"
        if owe >= 0
        else f"Net position: {name} to claim back {-owe / 100:,.2f} {rules.currency}"
    )
    return doc_from(
        ID,
        f"{name} summary",
        span_label(ctx.start, ctx.end),
        [Section(title=f"{name} charged and paid, by month", columns=cols, rows=body, note=position)],
        basis=[
            f"Amounts in {rules.currency}. {name} on sales is what your approved sales charged; {name} on purchases "
            "is what you paid on approved purchases and claimed back.",
            "For your own return: Accnomos files nothing with a tax office outside the UK.",
        ],
    )


register(
    ExportSpec(
        id=ID,
        group="taxes",
        title="Tax summary",
        description="Tax charged on sales against tax paid on purchases, by month, and the net position.",
        build=build,
        formats=("csv", "xlsx"),
        region="intl",
    )
)
