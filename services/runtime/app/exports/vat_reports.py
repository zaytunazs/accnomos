"""HMRC-style VAT reports: the 9-box return, the transactions behind each box, the MTD digital-links trail and the
VAT reconciliation. The boxes are accnomos_ledger.compute_vat_return, unchanged: the same figures the VAT page
submits.

Box descriptions are HMRC's headings from "How to fill in and submit your VAT Return (VAT Notice 700/12)",
sections 3.2 to 3.10, https://www.gov.uk/guidance/how-to-fill-in-and-submit-your-vat-return-vat-notice-70012
(page last updated 19 December 2025; checked 28 October 2026). The digital-links trail follows "VAT Notice 700/22:
Making Tax Digital for VAT", paragraph 3.2.1 (digital links) and section 3.3 (the electronic account),
https://www.gov.uk/government/publications/vat-notice-70022-making-tax-digital-for-vat/vat-notice-70022-making-tax-digital-for-vat
(updated 1 April 2022; checked 28 October 2026).

The EC Sales List is not offered: since 1 January 2021 only Northern Ireland businesses selling goods to the EU
send one, and Accnomos records no NI/EU movements (boxes 2, 8 and 9 are always 0).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from accnomos_ledger import LedgerEvent, VatReturn, compute_vat_return, vat_side
from accnomos_ledger.vat import ON_RETURN
from app import reports as rp
from app.deadlines import period_id, recent_periods
from app.deadlines import period_label as vat_period_label
from app.exports.accounts import details
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
from app.journal import VAT_CONTROL

GUIDANCE = "https://www.gov.uk/guidance/how-to-fill-in-and-submit-your-vat-return-vat-notice-70012"
MTD_NOTICE = (
    "https://www.gov.uk/government/publications/vat-notice-70022-making-tax-digital-for-vat/"
    "vat-notice-70022-making-tax-digital-for-vat"
)
CHECKED = "28 October 2026"
#: HMRC's box headings, VAT Notice 700/12 sections 3.2-3.10, word for word.
BOXES: tuple[tuple[int, str], ...] = (
    (1, "VAT due in the period on sales and other outputs"),
    (2, "VAT due in the period on acquisitions of goods made in Northern Ireland from EU member states"),
    (3, "Total VAT due"),
    (4, "VAT reclaimed in the period on purchases and other inputs (including acquisitions from the EU)"),
    (5, "Net VAT to pay to HMRC or reclaim"),
    (6, "Total value of sales and all other outputs excluding any VAT"),
    (7, "The total value of purchases and all other inputs excluding any VAT"),
    (8, "Total value of all supplies of goods and related costs, excluding any VAT, to EU member states"),
    (9, "Total value of all acquisitions goods and related costs, excluding any VAT, from EU member states"),
)
BOX_COLUMNS = columns(
    ("box", "Box"), ("description", "Description"), ("amount", "£ and pence", "money"), ("whole", "Whole £", "pounds")
)


def _pence(d: object) -> int:
    from decimal import Decimal

    assert isinstance(d, Decimal)
    return int(d * 100)


def vat_return_section(events: Sequence[LedgerEvent], start: date, end: date, months: int) -> tuple[Section, VatReturn]:
    ret = compute_vat_return(list(events), period_id(start, months), start, end)
    values: dict[int, tuple[int | None, int | None]] = {
        1: (_pence(ret.vat_due_sales), None),
        2: (_pence(ret.vat_due_acquisitions), None),
        3: (_pence(ret.total_vat_due), None),
        4: (_pence(ret.vat_reclaimed), None),
        5: (_pence(ret.net_vat_due), None),
        6: (None, ret.total_sales_ex_vat),
        7: (None, ret.total_purchases_ex_vat),
        8: (None, ret.goods_supplied_ni_eu),
        9: (None, ret.acquisitions_ni_eu),
    }
    rows = [
        Row(
            cells={"box": f"Box {n}", "description": text, "amount": values[n][0], "whole": values[n][1]},
            style="total" if n in (3, 5) else "normal",
        )
        for n, text in BOXES
    ]
    owed = ret.total_vat_due - ret.vat_reclaimed
    rows.append(
        Row(
            cells={
                "box": "",
                "description": "To pay to HMRC"
                if owed > 0
                else "To reclaim from HMRC"
                if owed < 0
                else "Nothing to pay or reclaim",
            }
        )
    )
    note = (
        f"Period {vat_period_label(start, end)} ({uk_day(start)} to {uk_day(end)}), period key as Accnomos names it "
        f"{ret.period_key}. Boxes 1-5 in pounds and pence; boxes 6-9 in whole pounds, pence dropped. Box 5 is "
        f"box 3 minus box 4 without its sign. Descriptions as in VAT Notice 700/12 ({GUIDANCE}, checked {CHECKED})."
    )
    return Section(title="VAT return", columns=BOX_COLUMNS, rows=rows, note=note), ret


DETAIL_COLUMNS = columns(
    ("date", "Date", "date"),
    ("entry", "Entry"),
    ("kind", "Kind"),
    ("counterparty", "Counterparty"),
    ("reference", "Reference"),
    ("codes", "VAT codes"),
    ("net", "Net", "money"),
    ("vat", "VAT", "money"),
    ("boxes", "Boxes"),
)


def vat_detail(
    events: Sequence[LedgerEvent], start: date, end: date, months: int, refs: dict[str, str]
) -> list[Section]:
    ret = compute_vat_return(list(events), period_id(start, months), start, end)
    counted = set(ret.event_ids)
    by_id = {e.id: e for e in events}
    sides: dict[str, list[Row]] = {"sales": [], "purchases": []}
    totals = {"sales": [0, 0], "purchases": [0, 0]}
    for eid in ret.event_ids:
        e = by_id[eid]
        side, sign = vat_side(e) or ("purchases", -1)
        net, vat = sign * (e.net or 0), sign * (e.vat or 0)
        totals[side][0] += net
        totals[side][1] += vat
        sides[side].append(
            Row(
                cells={
                    "date": e.date.isoformat(),
                    "entry": e.id[:8],
                    "kind": e.kind,
                    "counterparty": e.counterparty or "",
                    "reference": refs.get(e.id, ""),
                    "codes": ", ".join(sorted({ln.vat_code.value for ln in e.lines if ln.vat_code})),
                    "net": net,
                    "vat": vat,
                    "boxes": "1 and 6" if side == "sales" else "4 and 7",
                }
            )
        )
    out: list[Section] = []
    for side, title, vat_box, net_box in (
        ("sales", "Sales: boxes 1 and 6", 1, 6),
        ("purchases", "Purchases: boxes 4 and 7", 4, 7),
    ):
        rows = sorted(sides[side], key=lambda r: (str(r.cells["date"]), str(r.cells["entry"])))
        net, vat = totals[side]
        rows.append(Row(cells={"counterparty": "Total", "net": net, "vat": vat}, style="total"))
        out.append(
            Section(
                title=title,
                columns=DETAIL_COLUMNS,
                rows=rows,
                note=f"VAT total = box {vat_box}. Net total, pence dropped, = box {net_box}. "
                "Undos and credit notes are negative.",
            )
        )
    left_out: list[Row] = []
    for e in sorted(events, key=lambda e: (e.date, e.id)):
        if not start <= e.date <= end or e.id in counted:
            continue
        if e.kind not in ("sale", "purchase", "reversal"):
            continue
        codes = {ln.vat_code for ln in e.lines if ln.vat_code is not None}
        why = (
            "no net amount recorded"
            if e.net is None
            else "outside the scope of VAT (code O)"
            if not codes & ON_RETURN
            else "not on the return"
        )
        left_out.append(
            Row(
                cells={
                    "date": e.date.isoformat(),
                    "entry": e.id[:8],
                    "kind": e.kind,
                    "counterparty": e.counterparty or "",
                    "codes": ", ".join(sorted(c.value for c in codes)),
                    "net": e.net,
                    "vat": e.vat,
                    "boxes": why,
                }
            )
        )
    out.append(
        Section(
            title="Entries in the period not on the return",
            columns=DETAIL_COLUMNS,
            rows=left_out,
            note="Adjustments (payroll, for example) and bank entries never reach the VAT boxes.",
        )
    )
    return out


LINK_COLUMNS = columns(
    ("document", "Source document"),
    ("card", "Review card"),
    ("file", "Ledger entry file"),
    ("account", "Ledger line"),
    ("debit", "Debit", "money"),
    ("credit", "Credit", "money"),
    ("code", "VAT code"),
    ("box", "Box"),
)


def digital_links(
    events: Sequence[LedgerEvent],
    start: date,
    end: date,
    months: int,
    paths: dict[str, str],
    proposals: dict[str, object],
    refs: dict[str, str],
) -> Section:
    """Source document -> ledger entry file -> each line -> the box it feeds, for every entry on the return."""
    ret = compute_vat_return(list(events), period_id(start, months), start, end)
    by_id = {e.id: e for e in events}
    rows: list[Row] = []
    for eid in sorted(ret.event_ids, key=lambda i: (by_id[i].date, i)):
        e = by_id[eid]
        side, _ = vat_side(e) or ("purchases", -1)
        p = proposals.get(e.proposal_id or "")
        source = getattr(p, "file_path", None) or getattr(p, "source_name", None) if p is not None else None
        doc = (
            source
            or (f"invoice {refs[e.id]}" if e.id in refs else "")
            or (f"sha256 {e.evidence[0][:16]}…" if e.evidence else "no document")
        )
        rows.append(
            Row(
                cells={
                    "document": doc,
                    "card": e.proposal_id or "",
                    "file": paths.get(e.id, ""),
                    "account": details(e),
                },
                style="heading",
            )
        )
        for ln in e.lines:
            if ln.account == VAT_CONTROL:
                box = "1" if side == "sales" else "4"
            elif rp.section_of(ln.account) is not None:
                box = "6" if side == "sales" else "7"
            else:
                box = ""
            rows.append(
                Row(
                    cells={
                        "document": doc,
                        "card": e.proposal_id or "",
                        "file": paths.get(e.id, ""),
                        "account": ln.account,
                        "debit": ln.debit or None,
                        "credit": ln.credit or None,
                        "code": ln.vat_code.value if ln.vat_code else "",
                        "box": box,
                    }
                )
            )
    note = (
        "Every figure on the return is carried by code: the document is read into a Review card, the approved card "
        "becomes one immutable ledger entry file, and the boxes are summed from those files (the entry's recorded net "
        "and VAT). Nothing is copied or typed between steps, which is what VAT Notice 700/22 paragraph 3.2.1 asks of "
        f"a digital link ({MTD_NOTICE}, checked {CHECKED})."
    )
    return Section(title="MTD digital links", columns=LINK_COLUMNS, rows=rows, note=note)


REC_COLUMNS = columns(
    ("period", "Period"),
    ("return_net", "Net VAT on the return (box 3 − box 4)", "money"),
    ("control_docs", "VAT control from invoices and receipts", "money"),
    ("difference", "Difference", "money"),
    ("paid", "Payments to HMRC and adjustments", "money"),
    ("balance", "VAT control balance at the period end", "money"),
)


def vat_reconciliation(events: Sequence[LedgerEvent], spans: Sequence[tuple[date, date]], months: int) -> Section:
    rows: list[Row] = []
    for start, end in sorted(spans):
        ret = compute_vat_return(list(events), period_id(start, months), start, end)
        net = _pence(ret.total_vat_due) - _pence(ret.vat_reclaimed)
        docs = other = 0
        for e in events:
            if not start <= e.date <= end:
                continue
            move = sum(ln.credit - ln.debit for ln in e.lines if ln.account == VAT_CONTROL)
            if e.kind in ("sale", "purchase", "reversal"):
                docs += move
            else:
                other += move
        balance = sum(
            ln.credit - ln.debit for e in events if e.date <= end for ln in e.lines if ln.account == VAT_CONTROL
        )
        rows.append(
            Row(
                cells={
                    "period": vat_period_label(start, end),
                    "return_net": net,
                    "control_docs": docs,
                    "difference": net - docs,
                    "paid": other,
                    "balance": balance,
                },
                style="normal" if net == docs else "subtotal",
            )
        )
    note = (
        f"{VAT_CONTROL} is credit positive here (owed to HMRC). A difference means an entry's recorded VAT and its VAT "
        "control line disagree, or VAT sits on an entry the return leaves out (code O): check those entries in the VAT "
        "detail report. Payments to HMRC are bank entries, so they show in their own column and never on the return."
    )
    return Section(title="VAT reconciliation", columns=REC_COLUMNS, rows=rows, note=note)


# --------------------------------------------------------------------------- #
# Registered reports
# --------------------------------------------------------------------------- #

BASIS = (
    "As approved: invoices count when raised, receipts when bought (Accnomos has no VAT cash accounting scheme or "
    "flat rate scheme); undos count in the period they were made."
)


async def build_return(ctx: ExportContext) -> ReportDoc:
    events = await ctx.events()
    section, ret = vat_return_section(events, ctx.start, ctx.end, ctx.cycle.months)
    return doc_from(
        "vat-return",
        "UK VAT return",
        span_label(ctx.start, ctx.end),
        [section],
        basis=[BASIS],
        warnings=ret.warnings,
        sample=rp.is_sample(events),
    )


async def build_detail(ctx: ExportContext) -> ReportDoc:
    events = await ctx.events()
    sections = vat_detail(events, ctx.start, ctx.end, ctx.cycle.months, (await ctx.ledger()).refs)
    return doc_from(
        "vat-detail", "VAT detail", span_label(ctx.start, ctx.end), sections, basis=[BASIS], sample=rp.is_sample(events)
    )


async def build_links(ctx: ExportContext) -> ReportDoc:
    ledger = await ctx.ledger()
    section = digital_links(
        ledger.events,
        ctx.start,
        ctx.end,
        ctx.cycle.months,
        await ctx.event_paths(),
        dict(ledger.proposals),
        ledger.refs,
    )
    return doc_from(
        "vat-digital-links",
        "MTD digital links",
        span_label(ctx.start, ctx.end),
        [section],
        sample=rp.is_sample(ledger.events),
    )


async def build_reconciliation(ctx: ExportContext) -> ReportDoc:
    events = await ctx.events()
    spans = recent_periods(ctx.end, ctx.cycle.start_month, ctx.cycle.months, previous=3)
    return doc_from(
        "vat-reconciliation",
        "VAT reconciliation",
        f"four VAT periods to {uk_day(ctx.end)}",
        [vat_reconciliation(events, spans, ctx.cycle.months)],
        sample=rp.is_sample(events),
    )


for _spec in (
    ExportSpec(
        "vat-return",
        "taxes",
        "UK VAT return",
        "The 9 boxes for a period, laid out and worded as HMRC's return.",
        build_return,
    ),
    ExportSpec(
        "vat-detail",
        "taxes",
        "VAT detail",
        "Every entry behind boxes 1, 4, 6 and 7, and what was left out.",
        build_detail,
    ),
    ExportSpec(
        "vat-digital-links",
        "taxes",
        "MTD digital links",
        "Source document to ledger line to box, for every entry on the return.",
        build_links,
    ),
    ExportSpec(
        "vat-reconciliation",
        "taxes",
        "VAT reconciliation",
        "The VAT control account against the returns, period by period.",
        build_reconciliation,
    ),
):
    register(_spec)
