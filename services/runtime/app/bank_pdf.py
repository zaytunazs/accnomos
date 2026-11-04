"""A bank statement PDF as the CSV the bank import already reads (accnomos_ledger.bank.parse_bank_csv).

Most banks, in any country, offer a statement PDF; not all offer a CSV, and bank connections (app/bank_feeds.py)
reach UK banks only. So a PDF with a text layer is read by code, no model: each text line that starts with a date
and ends with an amount (and usually the running balance) is one transaction. The sign comes from the running
balance when there is one (it went down: money out), else from the amount as printed ("-12.50", "12.50 DR",
"(12.50)"). A scanned statement with no text layer is refused with a sentence: export a CSV instead.

The lines then go through the same import as a CSV: the same de-duplication, the same matching, and the PDF's own
CSV filed in 04 Bank statements. Nothing here posts anything.
"""

from __future__ import annotations

import csv
import io
import re
import threading
from datetime import date

from accnomos_ledger.bank import BankCsvError, parse_date

_LOCK = threading.Lock()  # PDFium is not thread-safe (app/formats.py)
MAX_PAGES = 60

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*"
DATE_RE = re.compile(
    rf"^(\d{{1,2}}[/.-]\d{{1,2}}[/.-]\d{{2,4}}|\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}[ -]{_MONTH}[ ,-]*\d{{2,4}})\s+(.*)$",
    re.IGNORECASE,
)
AMOUNT = r"\(?-?(?:[£€$₹₱₦₺]|[A-Z]{1,2}\$)?\d{1,3}(?:[,\s]\d{3})*\.\d{2}\)?(?:\s?(?:CR|DR|-))?"
OPENING_RE = re.compile(r"brought forward|carried forward|opening balance|closing balance|balance b/?f", re.I)
TAIL_RE = re.compile(rf"\s+({AMOUNT})(?:\s+({AMOUNT}))?\s*$", re.IGNORECASE)


def _to_date(text: str) -> date | None:
    t = re.sub(r"[.]", "/", text.strip())
    t = re.sub(r"\s*,\s*", " ", t)
    t = re.sub(r"(?i)\bsept\b", "Sep", t)
    t = re.sub(r"\s+", " ", t)
    if d := parse_date(t):
        return d
    # "3 November 2026" / "03-Nov-26" spellings the CSV parser lacks
    for sep in (" ", "-"):
        parts = t.split(sep)
        if (
            len(parts) == 3
            and parts[1][:3].isalpha()
            and (d := parse_date(f"{parts[0]} {parts[1][:3].title()} {parts[2]}"))
        ):
            return d
    return None


def _pence(text: str) -> int | None:
    t = text.strip().upper()
    sign = 1
    if t.endswith(("DR", "-")):
        sign, t = -1, t.removesuffix("DR").removesuffix("-").strip()
    elif t.endswith("CR"):
        t = t.removesuffix("CR").strip()
    if t.startswith("(") and t.endswith(")"):
        sign, t = -sign, t[1:-1]
    if t.startswith("-"):
        sign, t = -sign, t[1:]
    digits = re.sub(r"[^\d.]", "", t)
    if not re.fullmatch(r"\d+\.\d{2}", digits):
        return None
    whole, minor = digits.split(".")
    return sign * (int(whole) * 100 + int(minor))


def statement_lines(text: str) -> list[tuple[date, str, int, int | None]]:
    """(date, description, signed pence, balance pence or None) per transaction line of the statement's text."""
    out: list[tuple[date, str, int, int | None]] = []
    balance: int | None = None
    for raw in text.splitlines():
        line = " ".join(raw.split())
        m = DATE_RE.match(line)
        if not m:
            continue
        when = _to_date(m.group(1))
        tail = TAIL_RE.search(" " + m.group(2))
        if when is None or tail is None:
            continue
        description = (" " + m.group(2))[: tail.start()].strip()
        if not description:
            continue
        if OPENING_RE.search(description):  # not a payment: the balance the next lines move from
            balance = _pence(tail.group(2) or tail.group(1))
            continue
        first, second = _pence(tail.group(1)), _pence(tail.group(2)) if tail.group(2) else None
        if first is None:
            continue
        if second is not None:
            amount, new_balance = abs(first), second
            if balance is not None:
                amount = new_balance - balance  # the running balance says which way the money went
            elif first < 0:
                amount = first
            balance = new_balance
            out.append((when, description, amount, new_balance))
        else:
            out.append((when, description, first, None))
    return out


def _text(data: bytes) -> str:
    try:
        import pypdfium2 as pdfium  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - installed with the runtime
        raise BankCsvError("PDF statements cannot be read on this server; upload a CSV instead") from exc
    with _LOCK:
        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as exc:
            raise BankCsvError("This PDF could not be opened; upload the statement as a CSV instead") from exc
        try:
            pages = []
            for i in range(min(len(pdf), MAX_PAGES)):
                page = pdf[i]
                pages.append(page.get_textpage().get_text_range())
            return "\n".join(pages)
        finally:
            pdf.close()


def pdf_to_csv(data: bytes) -> bytes:
    """The statement PDF's transactions as a Date,Description,Amount,Balance CSV. Raises BankCsvError."""
    rows = statement_lines(_text(data).replace("\r", "\n"))
    if not rows:
        raise BankCsvError(
            "No transactions found in this PDF (a scanned statement has no text to read). "
            "Download the statement as a CSV from your bank instead."
        )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "Description", "Amount", "Balance"])
    for when, description, pence, balance in rows:
        w.writerow([when.isoformat(), description, _money(pence), "" if balance is None else _money(balance)])
    return buf.getvalue().encode("utf-8")


def _money(pence: int) -> str:
    sign = "-" if pence < 0 else ""
    return f"{sign}{abs(pence) // 100}.{abs(pence) % 100:02d}"
