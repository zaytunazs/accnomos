"""A4 invoice PDF in the usual UK layout (fpdf2, core Helvetica, no network, no fonts to ship).

Supplier block and logo, "Invoice" with number / date / due date, customer block, the lines, the VAT summary by
rate, totals, payment terms and bank details, and a footer with the VAT registration number. Every figure comes
from the invoice as code priced it (app/invoicing.py); this file only lays them out.

Core fonts cover Latin-1 only (which includes £); other characters are swapped for the nearest plain one.
"""

from __future__ import annotations

import io
import logging
from datetime import date

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from fpdf.fonts import FontFace

from app.invoicing import CIS_WORDING, REVERSE_CHARGE_WORDING, VAT_LABELS, Invoice, InvoiceProfile, money, uk_date

log = logging.getLogger(__name__)

INK = (31, 41, 51)
MUTED = (107, 114, 128)
TEAL = (13, 110, 110)
RULE = (214, 211, 201)
LEFT, RIGHT, WIDTH = 15.0, 195.0, 180.0
_PLAIN = str.maketrans(
    {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...", "•": "-", " ": " ", "€": "EUR "}
)


_CONTROL = {c: None for c in (*range(0x00, 0x20), 0x7F) if c != 0x0A}  # newlines stay (multi-line notes)


def text(s: str | None) -> str:
    """Typed-in text as the core font can draw it: no control characters, Latin-1 only."""
    return (s or "").translate(_PLAIN).translate(_CONTROL).encode("latin-1", "replace").decode("latin-1")


def _qty(inv_line_qty: object) -> str:
    s = f"{inv_line_qty}"
    return s.rstrip("0").rstrip(".") if "." in s else s


#: fpdf2 replaces its page-count alias everywhere in the output, typed-in text included; the default "{nb}" could be
#: typed into a customer name. This one cannot: text() drops control characters.
PAGES_ALIAS = "\x1enb\x1e"


class _InvoicePdf(FPDF):
    def __init__(self, footer_text: str) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self._footer_text = footer_text
        self.set_margins(LEFT, 15, 210 - RIGHT)
        self.set_auto_page_break(auto=True, margin=22)
        self.alias_nb_pages(PAGES_ALIAS)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_draw_color(*RULE)
        self.line(LEFT, self.get_y() - 2, RIGHT, self.get_y() - 2)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(WIDTH * 0.8, 5, text(self._footer_text))
        self.cell(WIDTH * 0.2, 5, f"Page {self.page_no()} of {PAGES_ALIAS}", align="R")


def _footer_text(profile: InvoiceProfile) -> str:
    parts = [profile.name.strip()]
    if profile.company_number:
        parts.append(f"Company no {profile.company_number}")
    if profile.vrn:
        parts.append(f"VAT reg no {profile.vrn}")
    return " · ".join(p for p in parts if p)


def render_invoice(
    inv: Invoice,
    profile: InvoiceProfile,
    logo: bytes | None = None,
    *,
    credit_for: str | None = None,
    paid_on: date | None = None,
    quote: bool = False,
) -> bytes:
    """The invoice; with `credit_for` (the invoice number), the same layout as a credit note against it
    (app/credit_notes.CreditNote.as_invoice): no due date or payment terms, "Total credit". With `paid_on`,
    a PAID stamp with the date under the title. With `quote`, a quote (app/routes_cis.py): "valid until" instead
    of the due date, and no payment details. A reverse-charge invoice carries HMRC's wording and the VAT the
    customer accounts for; a CIS invoice shows the deduction on labour and what is payable after it."""
    credit = credit_for is not None
    pdf = _InvoicePdf(_footer_text(profile))
    pdf.set_title(text(f"{'Credit note' if credit else 'Quote' if quote else 'Invoice'} {inv.number}"))
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
    title = "CREDIT NOTE" if credit else "QUOTE" if quote else "INVOICE"
    pdf.cell(RIGHT - 120, 10, title, align="R", new_x=XPos.LEFT, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9.5)
    if credit:
        meta = [
            ("Credit note number", inv.number),
            ("Date", uk_date(inv.issue_date)),
        ]
        if credit_for:
            meta.append(("Credits invoice", credit_for))
    elif quote:
        meta = [
            ("Quote number", inv.number),
            ("Quote date", uk_date(inv.issue_date)),
            ("Valid until", uk_date(inv.due_date)),
        ]
    else:
        meta = [
            ("Invoice number", inv.number),
            ("Invoice date", uk_date(inv.issue_date)),
            ("Due date", uk_date(inv.due_date)),
        ]
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
    if paid_on and not credit:
        pdf.set_x(120)
        pdf.set_text_color(*TEAL)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(RIGHT - 120, 7, text(f"PAID {uk_date(paid_on)}"), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
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
        for ln in inv.lines:
            row = table.row()
            row.cell(text(ln.description + (" (materials)" if inv.cis and ln.materials else "")))
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
    if inv.reverse_charge:
        pdf.set_text_color(*INK)
        pdf.cell(70, 5, text("VAT the customer accounts for (reverse charge)"))
        pdf.cell(25, 5, text(money(inv.reverse_charge_vat_pence)), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    vat_bottom = pdf.get_y()

    pdf.set_xy(125, y)
    for label, value, bold in (
        ("Subtotal (net)", inv.net_pence, False),
        ("VAT", inv.vat_pence, False),
        ("Total credit" if credit else "Total" if quote else "Total due", inv.total_pence, True),
    ):
        pdf.set_x(125)
        pdf.set_font("Helvetica", "B" if bold else "", 11 if bold else 9.5)
        pdf.set_text_color(*(INK if bold else MUTED))
        pdf.cell(35, 6.5, label)
        pdf.set_text_color(*INK)
        pdf.cell(RIGHT - 160, 6.5, text(money(value)), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_draw_color(*TEAL)
    pdf.line(125, pdf.get_y() + 0.5, RIGHT, pdf.get_y() + 0.5)
    if (c := inv.cis) and not credit:
        pdf.ln(2)
        for label, value, bold in (
            ("CIS labour", c.labour_pence, False),
            ("CIS materials", c.materials_pence, False),
            (f"Less CIS deduction {c.rate}%", -c.deduction_pence, False),
            ("Payable after CIS", c.payable_pence, True),
        ):
            pdf.set_x(125)
            pdf.set_font("Helvetica", "B" if bold else "", 10 if bold else 9)
            pdf.set_text_color(*(INK if bold else MUTED))
            pdf.cell(35, 5.5, text(label))
            pdf.set_text_color(*INK)
            pdf.cell(RIGHT - 160, 5.5, text(money(value)), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    words = [REVERSE_CHARGE_WORDING] if inv.reverse_charge else []
    if inv.cis and not credit:
        words.append(CIS_WORDING)
    if words:
        pdf.set_y(max(vat_bottom, pdf.get_y()) + 4)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*INK)
        for w in words:
            pdf.multi_cell(WIDTH, 5, text(w), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        vat_bottom = pdf.get_y()

    if credit:
        pdf.set_y(max(vat_bottom, pdf.get_y()) + 8)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*INK)
        credit_words = (
            f"This credit note reduces invoice {credit_for} by {money(inv.total_pence)}, VAT included."
            if credit_for
            else f"This credit note is for {money(inv.total_pence)}, VAT included."
        )
        pdf.multi_cell(
            WIDTH,
            5,
            text(credit_words),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        for extra in (inv.notes, profile.footer_note):
            if extra:
                pdf.ln(3)
                pdf.set_text_color(*MUTED)
                pdf.multi_cell(WIDTH, 4.5, text(extra), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        return bytes(pdf.output())

    if quote:
        pdf.set_y(max(vat_bottom, pdf.get_y()) + 8)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*INK)
        pdf.multi_cell(
            WIDTH,
            5,
            text(f"This is a quote, not a VAT invoice. It is valid until {uk_date(inv.due_date)}."),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        for extra in (inv.notes, profile.footer_note):
            if extra:
                pdf.ln(3)
                pdf.set_text_color(*MUTED)
                pdf.multi_cell(WIDTH, 4.5, text(extra), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        return bytes(pdf.output())

    # --- Payment -----------------------------------------------------------
    pdf.set_y(max(vat_bottom, pdf.get_y()) + 8)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(WIDTH, 5, "PAYMENT", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*INK)
    days = (inv.due_date - inv.issue_date).days
    terms = (
        "Payment due on receipt."
        if days <= 0
        else f"Payment terms: {days} days. Please pay by {uk_date(inv.due_date)}."
    )
    pdf.cell(WIDTH, 5, text(terms), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    b = profile.bank
    if b.is_set():
        rows = [
            ("Account name", b.account_name or profile.name),
            ("Sort code", b.sort_code),
            ("Account number", b.account_number),
        ]
        if b.iban:
            rows.append(("IBAN", b.iban))
        rows.append(("Reference", inv.number))
        for label, value in rows:
            if value:
                pdf.set_text_color(*MUTED)
                pdf.cell(32, 5, label)
                pdf.set_text_color(*INK)
                pdf.cell(WIDTH - 32, 5, text(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if link := inv.payment_link:  # app/online_payments.py: the customer can pay through the business's own account
        pdf.set_text_color(*MUTED)
        pdf.cell(32, 5, "Pay online")
        pdf.set_text_color(*TEAL)
        pdf.multi_cell(WIDTH - 32, 5, text(link.url), link=link.url, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if link.test_mode:
            pdf.set_text_color(*MUTED)
            pdf.cell(32, 5, "")
            pdf.cell(WIDTH - 32, 5, "TEST MODE: this link takes no real money.", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for extra in (inv.notes, profile.footer_note):
        if extra:
            pdf.ln(3)
            pdf.set_text_color(*MUTED)
            pdf.multi_cell(WIDTH, 4.5, text(extra), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    return bytes(pdf.output())


# --------------------------------------------------------------------------- #
# Payroll: report tables and payslips (app/payroll_reports.py, app/routes_payrun.py)
# --------------------------------------------------------------------------- #


class _DocPdf(_InvoicePdf):
    def __init__(self, footer_text: str, landscape: bool = False) -> None:
        FPDF.__init__(self, orientation="L" if landscape else "P", unit="mm", format="A4")
        self._footer_text = footer_text
        self._right = 282.0 if landscape else RIGHT
        self.set_margins(LEFT, 15, (297.0 if landscape else 210.0) - self._right)
        self.set_auto_page_break(auto=True, margin=22)
        self.alias_nb_pages(PAGES_ALIAS)

    def footer(self) -> None:
        width = self._right - LEFT
        self.set_y(-15)
        self.set_draw_color(*RULE)
        self.line(LEFT, self.get_y() - 2, self._right, self.get_y() - 2)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(width * 0.8, 5, text(self._footer_text))
        self.cell(width * 0.2, 5, f"Page {self.page_no()} of {PAGES_ALIAS}", align="R")


def render_table(
    title: str,
    subtitle: str,
    headers: list[str],
    rows: list[list[str]],
    totals: list[str] | None,
    numeric: list[bool],
    notes: list[str],
    *,
    landscape: bool = True,
    employer: str = "",
    weights: list[float] | None = None,
) -> bytes:
    """A report as an A4 table: title, subtitle, header row, rows, a totals row and the notes underneath."""
    pdf = _DocPdf(text(" · ".join(p for p in (employer, "Prepared with Accnomos") if p)), landscape)
    pdf.set_title(text(title))
    pdf.set_creator("Accnomos")
    pdf.add_page()
    width = pdf._right - LEFT
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 14)
    pdf.multi_cell(width, 7, text(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(width, 5, text(subtitle), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    n = max(1, len(headers))
    size = 7 if n > 12 else 8 if n > 7 else 9
    pdf.set_font("Helvetica", "", size)
    pdf.set_text_color(*INK)
    # Wider columns for text, narrower for numbers.
    weights = weights or [1.0 if num else 1.6 for num in numeric] or [1.0]
    total_w = sum(weights)
    widths = tuple(width * w / total_w for w in weights)
    align = tuple("RIGHT" if num else "LEFT" for num in numeric)
    head = FontFace(emphasis="BOLD", fill_color=(237, 242, 240))
    with pdf.table(
        col_widths=widths,
        text_align=align,  # type: ignore[arg-type]
        headings_style=head,
        line_height=size * 0.55,
        borders_layout="HORIZONTAL_LINES",
        width=width,
    ) as table:
        r = table.row()
        for h in headers:
            r.cell(text(h))
        for row in rows:
            r = table.row()
            for v in row:
                r.cell(text(v))
        if totals:
            r = table.row()
            for v in totals:
                r.cell(text(v), style=FontFace(emphasis="BOLD"))
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*MUTED)
    for note in notes:
        pdf.multi_cell(width, 4, text(note), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    return bytes(pdf.output())


def render_payslip(
    employer: str,
    employee: str,
    meta: list[tuple[str, str]],
    payments: list[tuple[str, str]],
    deductions: list[tuple[str, str]],
    net: str,
    year_to_date: list[tuple[str, str]],
    employer_costs: list[tuple[str, str]],
    notes: list[str],
) -> bytes:
    """A one-page payslip: who and when, payments, deductions, net pay, year to date, the employer's costs."""
    pdf = _DocPdf(text(" · ".join(p for p in (employer, "Payslip prepared with Accnomos") if p)))
    pdf.set_title(text(f"Payslip {employee}"))
    pdf.set_creator("Accnomos")
    pdf.add_page()
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(110, 6, text(employer or "Employer"))
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*TEAL)
    pdf.cell(RIGHT - LEFT - 110, 8, "PAYSLIP", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(WIDTH, 6, text(employee), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    for label, value in meta:
        pdf.set_text_color(*MUTED)
        pdf.cell(45, 4.8, text(label))
        pdf.set_text_color(*INK)
        pdf.cell(WIDTH - 45, 4.8, text(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    def block(title: str, items: list[tuple[str, str]], x: float, w: float, y: float) -> float:
        pdf.set_xy(x, y)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*MUTED)
        pdf.cell(w, 5, title.upper(), new_x=XPos.LEFT, new_y=YPos.NEXT)
        pdf.set_draw_color(*RULE)
        pdf.line(x, pdf.get_y(), x + w, pdf.get_y())
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(*INK)
        for label, value in items:
            pdf.set_x(x)
            pdf.cell(w * 0.65, 5.5, text(label))
            pdf.cell(w * 0.35, 5.5, text(value), align="R", new_x=XPos.LEFT, new_y=YPos.NEXT)
        return pdf.get_y()

    top = pdf.get_y()
    half = (WIDTH - 8) / 2
    a = block("Payments", payments, LEFT, half, top)
    b = block("Deductions", deductions, LEFT + half + 8, half, top)
    pdf.set_y(max(a, b) + 3)
    pdf.set_fill_color(237, 242, 240)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(WIDTH * 0.65, 9, "  Net pay", fill=True)
    pdf.cell(WIDTH * 0.35, 9, text(net) + "  ", align="R", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)
    top = pdf.get_y()
    a = block("This tax year", year_to_date, LEFT, half, top)
    b = block("Paid by your employer", employer_costs, LEFT + half + 8, half, top)
    pdf.set_y(max(a, b) + 4)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*MUTED)
    for note in notes:
        pdf.multi_cell(WIDTH, 4, text(note), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    return bytes(pdf.output())
