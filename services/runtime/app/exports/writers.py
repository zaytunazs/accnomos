"""ReportDoc -> CSV, XLSX or PDF bytes. The same document makes all three, so the files always agree with the screen.

Money is integer pence in a ReportDoc. The CSV shows it as pounds with two decimals and a minus sign ("-43.25"), the
XLSX as a number formatted £ (projection.GBP), the PDF as "£1,234.56". Dates are dd/mm/yyyy in the CSV and PDF and
real dates in the XLSX. Text that Excel would run as a formula (=, +, -, @ at the start) is quoted with an apostrophe
by projection._safe_text, in every format, vendor import files included.

A vendor import file (ReportDoc.import_file set) is written exactly as its single section says: the headings are the
vendor's, the cells are already in the vendor's format, and only the dialect differs (header row, byte-order mark,
FreeAgent's "no quote marks" rule).
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date

from fpdf import FPDF
from fpdf.fonts import FontFace
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from app.exports.registry import Column, ReportDoc, Section
from app.pdf import PAGES_ALIAS, text
from app.projection import SAMPLE_LABEL, WHOLE_GBP, _safe_text, _table

CODE_NOTE = "Worked out by code from the approved ledger entries in _System/Ledger/events; no model involved."


def _pounds_text(pence: int) -> str:
    sign = "-" if pence < 0 else ""
    p = abs(pence)
    return f"{sign}{p // 100}.{p % 100:02d}"


def _gbp(pence: int) -> str:
    sign = "-" if pence < 0 else ""
    p = abs(pence)
    return f"{sign}£{p // 100:,}.{p % 100:02d}"


def _day(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value)
    return None


def cell_text(col: Column, value: object, *, pdf: bool = False) -> str:
    """One cell as text for the CSV (pdf=False) or the PDF."""
    if value is None or value == "":
        return ""
    if col.kind == "money" and isinstance(value, int):
        return _gbp(value) if pdf else _pounds_text(value)
    if col.kind == "pounds" and isinstance(value, int):
        return f"£{value:,}" if pdf else str(value)
    if col.kind == "date" and (d := _day(value)):
        return f"{d:%d/%m/%Y}"
    return str(value)


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #


def _plain(value: str) -> str:
    """FreeAgent's bank CSV: no quote marks, no commas, one line per row."""
    return re.sub(r"\s+", " ", value.replace('"', "").replace(",", " ")).strip()


def to_csv(doc: ReportDoc) -> bytes:
    buf = io.StringIO()
    imp = doc.import_file
    if imp is not None:
        if imp.bom:
            buf.write("﻿")
        (section,) = doc.sections
        plain = imp.package == "FreeAgent" and not imp.header
        writer = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_NONE if plain else csv.QUOTE_MINIMAL)
        if imp.header:
            writer.writerow([c.label for c in section.columns])
        for row in section.rows:
            cells = [str(_safe_text(row.cells.get(c.key) or "")) for c in section.columns]
            writer.writerow([_plain(c) for c in cells] if plain else cells)
        return buf.getvalue().encode("utf-8")

    buf.write("﻿")  # so Excel opens UTF-8 (£, –) as text, not mojibake
    writer = csv.writer(buf, lineterminator="\r\n")
    if doc.sample:
        writer.writerow([SAMPLE_LABEL])
    writer.writerow([doc.title])
    writer.writerow([doc.period])
    for section in doc.sections:
        writer.writerow([])
        if len(doc.sections) > 1 or section.title != doc.title:
            writer.writerow([_safe_text(section.title)])
        writer.writerow([c.label for c in section.columns])
        for row in section.rows:
            writer.writerow([_safe_text(cell_text(c, row.cells.get(c.key))) for c in section.columns])
        if section.note:
            writer.writerow([_safe_text(section.note)])
    writer.writerow([])
    for line in [*doc.basis, *doc.warnings, CODE_NOTE]:
        writer.writerow([_safe_text(line)])
    return buf.getvalue().encode("utf-8")


# --------------------------------------------------------------------------- #
# XLSX
# --------------------------------------------------------------------------- #

_BAD_SHEET = re.compile(r"[\[\]:*?/\\]")


def _sheet_name(title: str, taken: set[str]) -> str:
    base = _BAD_SHEET.sub(" ", title).strip()[:31] or "Sheet"
    name, n = base, 1
    while name.lower() in taken:
        n += 1
        suffix = f" ({n})"
        name = base[: 31 - len(suffix)] + suffix
    taken.add(name.lower())
    return name


def _xlsx_value(col: Column, value: object) -> object:
    if value is None or value == "":
        return None
    if col.kind == "money" and isinstance(value, int):
        return value / 100
    if col.kind == "date" and (d := _day(value)):
        return d
    return value


def _section_sheet(ws: Worksheet, section: Section) -> None:
    rows = [[_xlsx_value(c, r.cells.get(c.key)) for c in section.columns] for r in section.rows]
    money = [i for i, c in enumerate(section.columns, start=1) if c.kind == "money"]
    dates = [i for i, c in enumerate(section.columns, start=1) if c.kind == "date"]
    widths = [max(10, min(48, max([len(c.label), *(len(str(v or "")) for v in col)]) + 2)) for c, col in _cols(section)]
    _table(ws, [c.label for c in section.columns], rows, money=money, dates=dates, widths=widths)
    for i, c in enumerate(section.columns, start=1):
        if c.kind == "pounds":
            for (cell,) in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                cell.number_format = WHOLE_GBP
    for n, r in enumerate(section.rows, start=2):
        if r.style != "normal":
            for cell in ws[n]:
                cell.font = Font(bold=True)
    if section.note:
        ws.append([])
        ws.append([_safe_text(section.note)])


def _cols(section: Section) -> list[tuple[Column, list[object]]]:
    return [(c, [r.cells.get(c.key) for r in section.rows]) for c in section.columns]


def to_xlsx(doc: ReportDoc) -> bytes:
    wb = Workbook()
    about = wb.active
    if not isinstance(about, Worksheet):  # a new Workbook always starts with one worksheet
        raise RuntimeError("openpyxl Workbook() has no first worksheet")
    about.title = "About"
    lines = [doc.title, doc.period, f"Generated {doc.generated_at:%d/%m/%Y %H:%M} UTC.", CODE_NOTE, *doc.basis]
    if doc.import_file:
        lines += [f"{doc.import_file.package}: {doc.import_file.template}", doc.import_file.source]
    lines += doc.warnings
    if doc.sample:
        lines.insert(0, SAMPLE_LABEL)
    for line in lines:
        about.append([_safe_text(line)])
    about.cell(row=1, column=1).font = Font(bold=True)
    about.column_dimensions["A"].width = 110
    taken = {"about"}
    for section in doc.sections:
        ws = wb.create_sheet(_sheet_name(section.title, taken))
        _section_sheet(ws, section)
        if doc.sample:
            ws.append([])
            ws.append([SAMPLE_LABEL])
    if doc.import_file is not None:  # an import file in XLSX (QuickBooks takes both): headings in row 1, nothing else
        wb.remove(about)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #

INK = (31, 41, 51)
MUTED = (107, 114, 128)
HEAD = FontFace(emphasis="BOLD", fill_color=(236, 234, 226))
BOLD = FontFace(emphasis="BOLD")


class _ReportPdf(FPDF):
    def __init__(self, footer: str, landscape: bool) -> None:
        super().__init__(orientation="L" if landscape else "P", unit="mm", format="A4")
        self._footer = footer
        self.set_margins(12, 12, 12)
        self.set_auto_page_break(auto=True, margin=16)
        self.alias_nb_pages(PAGES_ALIAS)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*MUTED)
        w = self.w - 24
        self.cell(w * 0.8, 4, text(self._footer))
        self.cell(w * 0.2, 4, f"Page {self.page_no()} of {PAGES_ALIAS}", align="R")


def _weights(section: Section) -> list[float]:
    out = []
    for c, col in _cols(section):
        if c.kind in ("money", "pounds"):
            out.append(1.1)
        elif c.kind in ("date", "int"):
            out.append(0.8)
        else:
            longest = max([len(c.label), *(len(str(v or "")) for v in col)])
            out.append(min(3.2, max(1.0, longest / 14)))
    return out


def to_pdf(doc: ReportDoc) -> bytes:
    widest = max((len(s.columns) for s in doc.sections), default=1)
    pdf = _ReportPdf(f"{doc.title} · {doc.period} · {CODE_NOTE}", landscape=widest > 5)
    pdf.set_title(text(doc.title))
    pdf.set_creator("Accnomos")
    pdf.add_page()
    pdf.set_text_color(*INK)
    if doc.sample:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, text(SAMPLE_LABEL), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 8, text(doc.title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, text(doc.period), new_x="LMARGIN", new_y="NEXT")
    for line in doc.basis:
        pdf.multi_cell(0, 4, text(line), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*INK)
    for section in doc.sections:
        pdf.ln(3)
        if len(doc.sections) > 1 or section.title != doc.title:
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 6, text(section.title), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)
        if not section.rows:
            pdf.cell(0, 5, "Nothing in this period.", new_x="LMARGIN", new_y="NEXT")
            continue
        aligns = ["R" if c.kind in ("money", "pounds", "int") else "L" for c in section.columns]
        with pdf.table(
            col_widths=_weights(section),
            headings_style=HEAD,
            line_height=4.6,
            text_align=aligns,  # type: ignore[arg-type]
            first_row_as_headings=True,
            repeat_headings=1,
        ) as table:
            head = table.row()
            for c in section.columns:
                head.cell(text(c.label))
            for r in section.rows:
                row = table.row()
                style = BOLD if r.style != "normal" else None
                for c in section.columns:
                    row.cell(text(cell_text(c, r.cells.get(c.key), pdf=True)), style=style)
        if section.note:
            pdf.set_text_color(*MUTED)
            pdf.multi_cell(0, 4, text(section.note), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(*INK)
    if doc.warnings:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 5, "Check", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)
        for w in doc.warnings:
            pdf.multi_cell(0, 4, text(f"- {w}"), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def render(doc: ReportDoc, fmt: str) -> bytes:
    if fmt == "csv":
        return to_csv(doc)
    if fmt == "xlsx":
        return to_xlsx(doc)
    if fmt == "pdf":
        return to_pdf(doc)
    raise ValueError(f"a report cannot be written as {fmt}")


def row_count(doc: ReportDoc) -> int:
    return sum(len(s.rows) for s in doc.sections)
