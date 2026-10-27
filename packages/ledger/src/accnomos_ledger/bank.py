"""Bank statement lines and a forgiving CSV reader for the common UK bank export layouts.

Amounts are signed integer pence: money out is negative. Headers are sniffed case-insensitively,
so Starling, Monzo, Barclays, HSBC, Lloyds and similar exports all read without configuration.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel

BankLineStatus = Literal["unmatched", "matched", "suggested"]

DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d/%m/%y", "%d-%b-%Y", "%d %b %y")

#: Column role -> header names that mean it (lowercase, compared after stripping punctuation).
HEADERS: dict[str, tuple[str, ...]] = {
    "date": ("date", "transaction date", "posting date", "posted date", "value date"),
    "description": ("description", "details", "narrative", "transaction description", "transaction information", "memo", "name",
                    "counter party", "counterparty", "payee", "merchant"),
    "amount": ("amount", "amount (gbp)", "amount gbp", "value", "local amount"),
    "out": ("money out", "paid out", "debit", "debit amount", "out", "withdrawals"),
    "in": ("money in", "paid in", "credit", "credit amount", "in", "deposits"),
    "balance": ("balance", "balance (gbp)", "running balance", "balance gbp"),
    "reference": ("reference", "ref", "transaction reference", "notes"),
}


class BankLine(BaseModel):
    id: str
    date: date
    amount_pence: int  # signed: money out is negative
    description: str
    reference: str | None = None
    balance_pence: int | None = None
    source_file: str
    matched_event_id: str | None = None  # the first (or only) event this line pays for
    matched_event_ids: list[str] = []  # all of them, when one payment covers several events
    status: BankLineStatus = "unmatched"

    def event_ids(self) -> list[str]:
        return self.matched_event_ids or ([self.matched_event_id] if self.matched_event_id else [])


class BankCsvError(ValueError):
    """The file does not look like a bank statement we can read."""


def line_id(when: date, amount_pence: int, description: str, balance_pence: int | None) -> str:
    key = f"{when.isoformat()}|{amount_pence}|{description}|{'' if balance_pence is None else balance_pence}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def parse_date(text: str) -> date | None:
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(text: str | None) -> int | None:
    """'£1,234.50' -> 123450; '(12.00)', '-12.00', '12.00 DR' -> -1200; '12.00CR' -> 1200; blank -> None."""
    if text is None:
        return None
    s = text.strip().replace("£", "").replace(",", "").replace("GBP", "").strip()
    if not s:
        return None
    sign = 1
    upper = s.upper()
    if upper.endswith("DR") or upper.endswith("CR"):
        sign = -1 if upper.endswith("DR") else 1
        s = s[:-2].strip()
    if s.startswith("(") and s.endswith(")"):
        sign, s = -sign, s[1:-1].strip()
    if s.startswith("-"):
        sign, s = -sign, s[1:].strip()
    s = s.lstrip("+").replace("£", "").strip()
    try:
        return sign * int((Decimal(s) * 100).to_integral_value())
    except InvalidOperation:
        return None


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", h.strip().lower().replace("_", " ").lstrip("﻿")).strip()


def _columns(header: list[str]) -> dict[str, int]:
    """Role -> column index for a header row; first matching column wins."""
    names = [_norm_header(h) for h in header]
    found: dict[str, int] = {}
    for role, aliases in HEADERS.items():
        idx = next((i for i, n in enumerate(names) if n in aliases), None)
        if idx is not None and idx not in found.values():
            found[role] = idx
    return found


def _is_header(cols: dict[str, int]) -> bool:
    return "date" in cols and "description" in cols and ("amount" in cols or "out" in cols or "in" in cols)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _cell(row: list[str], cols: dict[str, int], role: str) -> str | None:
    i = cols.get(role)
    return row[i].strip() if i is not None and i < len(row) else None


def _signed_amount(row: list[str], cols: dict[str, int]) -> int | None:
    if "amount" in cols:
        return parse_amount(_cell(row, cols, "amount"))
    out, inn = parse_amount(_cell(row, cols, "out")), parse_amount(_cell(row, cols, "in"))
    if out is None and inn is None:
        return None
    return (inn or 0) - abs(out or 0)


def _row_to_line(row: list[str], cols: dict[str, int], source_file: str) -> BankLine | None:
    when = parse_date(_cell(row, cols, "date") or "")
    amount = _signed_amount(row, cols)
    if when is None or amount is None:
        return None
    description = re.sub(r"\s+", " ", _cell(row, cols, "description") or "").strip()
    balance = parse_amount(_cell(row, cols, "balance"))
    return BankLine(
        id=line_id(when, amount, description, balance), date=when, amount_pence=amount, description=description,
        reference=_cell(row, cols, "reference") or None, balance_pence=balance, source_file=source_file,
    )


def parse_bank_csv(data: bytes, source_file: str) -> list[BankLine]:
    """Every transaction row in a UK bank CSV export. Preamble rows before the header are skipped.

    Raises BankCsvError when no recognisable header row is found.
    """
    rows = list(csv.reader(io.StringIO(_decode(data))))
    start = next(((i, c) for i, r in enumerate(rows) if _is_header(c := _columns(r))), None)
    if start is None:
        raise BankCsvError("No Date / Description / Amount header found")
    header_at, cols = start
    lines: list[BankLine] = []
    seen: dict[str, int] = {}
    for row in rows[header_at + 1:]:
        line = _row_to_line(row, cols, source_file)
        if line is None:
            continue
        # Two identical rows without a balance column are still two payments: keep both, distinct ids.
        n = seen.get(line.id, 0)
        seen[line.id] = n + 1
        if n:
            line.id = hashlib.sha256(f"{line.id}#{n}".encode()).hexdigest()[:16]
        lines.append(line)
    return lines
