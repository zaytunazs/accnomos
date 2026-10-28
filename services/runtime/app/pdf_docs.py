"""A4 PDFs for the other sales and purchase documents: quotes, purchase orders and customer statements.

Same look as the invoice (app/pdf.py): supplier block and logo, a title with the document's numbers on the right, the
other party, a table, totals and a footer with the company and VAT numbers. Every figure is as code worked it out
(app/quotes.py, app/purchase_orders.py, app/statements.py); this file only lays them out. Latin-1 core fonts only.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from fpdf.enums import XPos, YPos
from fpdf.fonts import FontFace

from app.invoicing import VAT_LABELS, InvoiceLine, InvoiceProfile, VatSummaryRow, money, uk_date
from app.pdf import INK, LEFT, MUTED, RIGHT, RULE, TEAL, WIDTH, _footer_text, _InvoicePdf, _qty, text

log = logging.getLogger(__name__)


@dataclass
class Party:
    label: str  # "PREPARED FOR", "SUPPLIER", "DELIVER TO"
    name: str
    lines: list[str] = field(default_factory=list)


@dataclass
class TradeDoc:
    title: str  # "QUOTE", "PURCHASE ORDER"
    pdf_title: str
    meta: list[tuple[str, str]]
    parties: list[Party]
    lines: Sequence[InvoiceLine]
    vat_summary: Sequence[VatSummaryRow]
    net_pence: int
    vat_pence: int
    total_pence: int
    total_label: str = "Total"
    stamp: str | None = None  # "ACCEPTED 3 November 2026"
    paragraphs: list[str] = field(default_factory=list)  # under the totals


def _supplier_block(pdf: _InvoicePdf, profile: InvoiceProfile, logo: bytes | None) -> tuple[float, float]:
    top = pdf.get_y()
    if logo:
        try:
            pdf.image(io.BytesIO(logo), x=LEFT, y=top, h=18)
            pdf.set_y(top + 21)
        except Exception:  # noqa: BLE001  a bad logo must not stop the document
            log.warning("logo could not be drawn; rendering without it")
            pdf.set_y(top)
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(100, 6, text(profile.name or "Your business name"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    for line in [*profile.address.splitlines(), profile.email, profile.phone]:
        if line and line.strip():
            pdf.cell(100, 4.5, text(line.strip()), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if profile.vrn:
        pdf.cell(100, 4.5, text(f"VAT reg no: {profile.vrn}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    return top, pdf.get_y()


def _title_block(pdf: _InvoicePdf, top: float, doc: TradeDoc) -> None:
    pdf.set_xy(120, top)
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*TEAL)
    pdf.cell(RIGHT - 120, 10, doc.title, align="R", new_x=XPos.LEFT, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9.5)
    for label, value in doc.meta:
        pdf.set_x(120)
        pdf.set_text_color(*MUTED)
        pdf.cell(35, 5.5, text(label))
        pdf.set_text_color(*INK)
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.cell(RIGHT - 155, 5.5, text(value), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9.5)
    if doc.stamp:
        pdf.set_x(120)
        pdf.set_text_color(*TEAL)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(RIGHT - 120, 7, text(doc.stamp), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _party(pdf: _InvoicePdf, p: Party, x: float, width: float) -> None:
    pdf.set_x(x)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(width, 5, text(p.label), new_x=XPos.LEFT, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.set_text_color(*INK)
    pdf.cell(width, 5.5, text(p.name), new_x=XPos.LEFT, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    for line in p.lines:
        if line.strip():
            pdf.cell(width, 4.5, text(line.strip()), new_x=XPos.LEFT, new_y=YPos.NEXT)


def render_trade_document(doc: TradeDoc, profile: InvoiceProfile, logo: bytes | None = None) -> bytes:
    pdf = _InvoicePdf(_footer_text(profile))
    pdf.set_title(text(doc.pdf_title))
    pdf.set_author(text(profile.name))
    pdf.set_creator("Accnomos")
    pdf.add_page()
    top, supplier_bottom = _supplier_block(pdf, profile, logo)
    _title_block(pdf, top, doc)

    # --- Other parties, side by side ---------------------------------------
    start = max(supplier_bottom, pdf.get_y()) + 8
    bottoms = []
    for n, p in enumerate(doc.parties[:2]):
        pdf.set_y(start)
        _party(pdf, p, LEFT + n * 95, 90)
        bottoms.append(pdf.get_y())
    pdf.set_x(LEFT)
    pdf.set_y(max(bottoms, default=start) + 6)

    # --- Lines -------------------------------------------------------------
    pdf.set_font("Helvetica", "", 9)
    pdf.set_draw_color(*RULE)
    with pdf.table(
        col_widths=(86, 18, 28, 16, 32),
        text_align=("LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"),
        borders_layout="HORIZONTAL_LINES",
        line_height=6,
        first_row_as_headings=True,
        width=WIDTH,
        headings_style=FontFace(emphasis="BOLD", color=MUTED),
        padding=1,
    ) as table:
        head = table.row()
        for h in ("Description", "Qty", "Unit price", "VAT", "Net"):
            head.cell(h)
        for ln in doc.lines:
            row = table.row()
            row.cell(text(ln.description))
            row.cell(text(f"{_qty(ln.quantity)}{f' {ln.unit}' if ln.unit else ''}"))
            row.cell(text(money(ln.unit_price_pence)))
            row.cell(f"{ln.vat_rate}%" if ln.vat_code in ("S", "R", "Z") else ln.vat_code)
            row.cell(text(money(ln.net_pence)))
    pdf.ln(4)

    # --- VAT summary (left) and totals (right) -----------------------------
    if pdf.get_y() > 230:
        pdf.add_page()
    y = pdf.get_y()
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(95, 5, "VAT SUMMARY", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 8.5)
    for r in doc.vat_summary:
        pdf.set_text_color(*INK)
        pdf.cell(45, 5, text(VAT_LABELS[r.vat_code]))
        pdf.set_text_color(*MUTED)
        pdf.cell(25, 5, text(f"net {money(r.net_pence)}"), align="R")
        pdf.cell(25, 5, text(f"VAT {money(r.vat_pence)}"), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    vat_bottom = pdf.get_y()
    pdf.set_xy(125, y)
    for label, value, bold in (
        ("Subtotal (net)", doc.net_pence, False),
        ("VAT", doc.vat_pence, False),
        (doc.total_label, doc.total_pence, True),
    ):
        pdf.set_x(125)
        pdf.set_font("Helvetica", "B" if bold else "", 11 if bold else 9.5)
        pdf.set_text_color(*(INK if bold else MUTED))
        pdf.cell(35, 6.5, text(label))
        pdf.set_text_color(*INK)
        pdf.cell(RIGHT - 160, 6.5, text(money(value)), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_draw_color(*TEAL)
    pdf.line(125, pdf.get_y() + 0.5, RIGHT, pdf.get_y() + 0.5)

    pdf.set_y(max(vat_bottom, pdf.get_y()) + 8)
    for n, para in enumerate(doc.paragraphs):
        if not para.strip():
            continue
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*(INK if n == 0 else MUTED))
        pdf.multi_cell(WIDTH, 4.8, text(para), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2.5)
    return bytes(pdf.output())


# --------------------------------------------------------------------------- #
# Customer statement
# --------------------------------------------------------------------------- #


@dataclass
class StatementRow:
    date: date
    details: str
    reference: str
    charge_pence: int  # invoices (positive), credit notes (negative as a credit shown in the Credit column)
    credit_pence: int  # payments and credit notes received, positive
    balance_pence: int


@dataclass
class OpenRow:
    reference: str
    date: date
    due: date
    total_pence: int
    owed_pence: int
    days_overdue: int


def render_statement(
    *,
    name: str,
    address: list[str],
    start: date | None,
    end: date,
    opening_pence: int,
    closing_pence: int,
    rows: Sequence[StatementRow],
    open_items: Sequence[OpenRow],
    credit_pence: int,
    profile: InvoiceProfile,
    logo: bytes | None = None,
) -> bytes:
    pdf = _InvoicePdf(_footer_text(profile))
    pdf.set_title(text(f"Statement for {name}"))
    pdf.set_author(text(profile.name))
    pdf.set_creator("Accnomos")
    pdf.add_page()
    top, supplier_bottom = _supplier_block(pdf, profile, logo)
    period = f"{uk_date(start)} to {uk_date(end)}" if start else f"up to {uk_date(end)}"
    _title_block(
        pdf,
        top,
        TradeDoc(
            title="STATEMENT",
            pdf_title="",
            meta=[("Statement date", uk_date(end)), ("Period", period), ("Amount due", money(closing_pence))],
            parties=[],
            lines=[],
            vat_summary=[],
            net_pence=0,
            vat_pence=0,
            total_pence=0,
        ),
    )
    pdf.set_y(max(supplier_bottom, pdf.get_y()) + 8)
    _party(pdf, Party("TO", name, address), LEFT, 90)
    pdf.set_x(LEFT)
    pdf.ln(6)

    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(WIDTH, 5, "ACTIVITY", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_draw_color(*RULE)
    with pdf.table(
        col_widths=(24, 62, 28, 22, 22, 22),
        text_align=("LEFT", "LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT"),
        borders_layout="HORIZONTAL_LINES",
        line_height=5.5,
        first_row_as_headings=True,
        width=WIDTH,
        headings_style=FontFace(emphasis="BOLD", color=MUTED),
        padding=1,
    ) as table:
        head = table.row()
        for h in ("Date", "Details", "Reference", "Charges", "Credits", "Balance"):
            head.cell(h)
        if start:
            row = table.row()
            for c in ("", "Balance brought forward", "", "", "", money(opening_pence)):
                row.cell(text(c))
        for r in rows:
            row = table.row()
            row.cell(f"{r.date:%d/%m/%Y}")
            row.cell(text(r.details))
            row.cell(text(r.reference))
            row.cell(text(money(r.charge_pence)) if r.charge_pence else "")
            row.cell(text(money(r.credit_pence)) if r.credit_pence else "")
            row.cell(text(money(r.balance_pence)))
    pdf.ln(5)

    if pdf.get_y() > 215:
        pdf.add_page()
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(WIDTH, 5, "OUTSTANDING", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 8.5)
    if open_items:
        with pdf.table(
            col_widths=(40, 28, 28, 28, 28, 28),
            text_align=("LEFT", "LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT"),
            borders_layout="HORIZONTAL_LINES",
            line_height=5.5,
            first_row_as_headings=True,
            width=WIDTH,
            headings_style=FontFace(emphasis="BOLD", color=MUTED),
            padding=1,
        ) as table:
            head = table.row()
            for h in ("Invoice", "Dated", "Due", "Total", "Still owed", "Overdue"):
                head.cell(h)
            for o in open_items:
                row = table.row()
                row.cell(text(o.reference))
                row.cell(f"{o.date:%d/%m/%Y}")
                row.cell(f"{o.due:%d/%m/%Y}")
                row.cell(text(money(o.total_pence)))
                row.cell(text(money(o.owed_pence)))
                row.cell(f"{o.days_overdue} days" if o.days_overdue > 0 else "")
    else:
        pdf.set_text_color(*INK)
        pdf.cell(WIDTH, 5, "Nothing is outstanding.", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)
    pdf.set_x(125)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*INK)
    pdf.cell(35, 6.5, "Amount due")
    pdf.cell(RIGHT - 160, 6.5, text(money(closing_pence)), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_draw_color(*TEAL)
    pdf.line(125, pdf.get_y() + 0.5, RIGHT, pdf.get_y() + 0.5)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 9)
    if credit_pence:
        pdf.set_text_color(*INK)
        pdf.multi_cell(
            WIDTH,
            4.8,
            text(f"{money(credit_pence)} is held as a credit on your account and is not included above."),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.ln(2)
    b = profile.bank
    if b.is_set() and closing_pence > 0:
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*MUTED)
        pdf.cell(WIDTH, 5, "HOW TO PAY", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9)
        for label, value in (
            ("Account name", b.account_name or profile.name),
            ("Sort code", b.sort_code),
            ("Account number", b.account_number),
            ("IBAN", b.iban or ""),
        ):
            if value:
                pdf.set_text_color(*MUTED)
                pdf.cell(32, 5, label)
                pdf.set_text_color(*INK)
                pdf.cell(WIDTH - 32, 5, text(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if profile.footer_note:
        pdf.ln(3)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(WIDTH, 4.5, text(profile.footer_note), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    return bytes(pdf.output())
