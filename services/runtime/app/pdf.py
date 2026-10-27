"""A4 invoice PDF in the usual UK layout (fpdf2, core Helvetica, no network, no fonts to ship).

Supplier block and logo, "Invoice" with number / date / due date, customer block, the lines, the VAT summary by
rate, totals, payment terms and bank details, and a footer with the VAT registration number. Every figure comes
from the invoice as code priced it (app/invoicing.py); this file only lays them out.

Core fonts cover Latin-1 only (which includes £); other characters are swapped for the nearest plain one.
"""

from __future__ import annotations

import io
import logging

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from fpdf.fonts import FontFace

from app.invoicing import VAT_LABELS, Invoice, InvoiceProfile, money, uk_date

log = logging.getLogger(__name__)

INK = (31, 41, 51)
MUTED = (107, 114, 128)
TEAL = (13, 110, 110)
RULE = (214, 211, 201)
LEFT, RIGHT, WIDTH = 15.0, 195.0, 180.0
_PLAIN = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...", "•": "-", " ": " ", "€": "EUR "})


def text(s: str | None) -> str:
    return (s or "").translate(_PLAIN).encode("latin-1", "replace").decode("latin-1")


def _qty(inv_line_qty: object) -> str:
    s = f"{inv_line_qty}"
    return s.rstrip("0").rstrip(".") if "." in s else s


class _InvoicePdf(FPDF):
    def __init__(self, footer_text: str) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self._footer_text = footer_text
        self.set_margins(LEFT, 15, 210 - RIGHT)
        self.set_auto_page_break(auto=True, margin=22)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_draw_color(*RULE)
        self.line(LEFT, self.get_y() - 2, RIGHT, self.get_y() - 2)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(WIDTH * 0.8, 5, text(self._footer_text))
        self.cell(WIDTH * 0.2, 5, f"Page {self.page_no()} of {{nb}}", align="R")


def _footer_text(profile: InvoiceProfile) -> str:
    parts = [profile.name.strip()]
    if profile.company_number:
        parts.append(f"Company no {profile.company_number}")
    if profile.vrn:
        parts.append(f"VAT reg no {profile.vrn}")
    return " · ".join(p for p in parts if p)


def render_invoice(inv: Invoice, profile: InvoiceProfile, logo: bytes | None = None) -> bytes:
    pdf = _InvoicePdf(_footer_text(profile))
    pdf.set_title(text(f"Invoice {inv.number}"))
    pdf.set_author(text(profile.name))
    pdf.set_creator("Accnomos")
    pdf.add_page()

    # --- Supplier block (left) and title (right) ---------------------------
    top = pdf.get_y()
    if logo:
        try:
            pdf.image(io.BytesIO(logo), x=LEFT, y=top, h=18)
            pdf.set_y(top + 21)
        except Exception:  # noqa: BLE001  a bad logo must not stop the invoice
            log.warning("invoice logo could not be drawn; rendering without it")
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
    supplier_bottom = pdf.get_y()

    pdf.set_xy(120, top)
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(*TEAL)
    pdf.cell(RIGHT - 120, 10, "INVOICE", align="R", new_x=XPos.LEFT, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9.5)
    meta = [("Invoice number", inv.number), ("Invoice date", uk_date(inv.issue_date)), ("Due date", uk_date(inv.due_date))]
    if inv.reference:
        meta.append(("Your reference", inv.reference))
    for label, value in meta:
        pdf.set_x(120)
        pdf.set_text_color(*MUTED)
        pdf.cell(35, 5.5, label)
        pdf.set_text_color(*INK)
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.cell(RIGHT - 155, 5.5, text(value), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9.5)

    # --- Customer block ----------------------------------------------------
    pdf.set_y(max(supplier_bottom, pdf.get_y()) + 8)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(100, 5, "BILL TO", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.set_text_color(*INK)
    pdf.cell(100, 5.5, text(inv.customer.name), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    for line in (inv.customer.address or "").splitlines():
        if line.strip():
            pdf.cell(100, 4.5, text(line.strip()), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if inv.customer.vrn:
        pdf.cell(100, 4.5, text(f"VAT no: {inv.customer.vrn}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(6)

    # --- Lines -------------------------------------------------------------
    pdf.set_font("Helvetica", "", 9)
    pdf.set_draw_color(*RULE)
    with pdf.table(
        col_widths=(86, 18, 28, 16, 32), text_align=("LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"),
        borders_layout="HORIZONTAL_LINES", line_height=6, first_row_as_headings=True, width=WIDTH,
        headings_style=FontFace(emphasis="BOLD", color=MUTED), padding=1,
    ) as table:
        head = table.row()
        for h in ("Description", "Qty", "Unit price", "VAT", "Net"):
            head.cell(h)
        for ln in inv.lines:
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
    for r in inv.vat_summary:
        pdf.set_text_color(*INK)
        pdf.cell(45, 5, text(VAT_LABELS[r.vat_code]))
        pdf.set_text_color(*MUTED)
        pdf.cell(25, 5, text(f"net {money(r.net_pence)}"), align="R")
        pdf.cell(25, 5, text(f"VAT {money(r.vat_pence)}"), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    vat_bottom = pdf.get_y()

    pdf.set_xy(125, y)
    for label, value, bold in (("Subtotal (net)", inv.net_pence, False), ("VAT", inv.vat_pence, False),
                               ("Total due", inv.total_pence, True)):
        pdf.set_x(125)
        pdf.set_font("Helvetica", "B" if bold else "", 11 if bold else 9.5)
        pdf.set_text_color(*(INK if bold else MUTED))
        pdf.cell(35, 6.5, label)
        pdf.set_text_color(*INK)
        pdf.cell(RIGHT - 160, 6.5, text(money(value)), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_draw_color(*TEAL)
    pdf.line(125, pdf.get_y() + 0.5, RIGHT, pdf.get_y() + 0.5)

    # --- Payment -----------------------------------------------------------
    pdf.set_y(max(vat_bottom, pdf.get_y()) + 8)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(WIDTH, 5, "PAYMENT", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*INK)
    days = (inv.due_date - inv.issue_date).days
    terms = "Payment due on receipt." if days <= 0 else f"Payment terms: {days} days. Please pay by {uk_date(inv.due_date)}."
    pdf.cell(WIDTH, 5, text(terms), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    b = profile.bank
    if b.is_set():
        rows = [("Account name", b.account_name or profile.name), ("Sort code", b.sort_code), ("Account number", b.account_number)]
        if b.iban:
            rows.append(("IBAN", b.iban))
        rows.append(("Reference", inv.number))
        for label, value in rows:
            if value:
                pdf.set_text_color(*MUTED)
                pdf.cell(32, 5, label)
                pdf.set_text_color(*INK)
                pdf.cell(WIDTH - 32, 5, text(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for extra in (inv.notes, profile.footer_note):
        if extra:
            pdf.ln(3)
            pdf.set_text_color(*MUTED)
            pdf.multi_cell(WIDTH, 4.5, text(extra), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    return bytes(pdf.output())
