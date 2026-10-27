"""Bank statement lines and a forgiving CSV reader for the common UK bank export layouts.

Amounts are signed integer pence: money out is negative. Headers are sniffed case-insensitively,
so Starling, Monzo, Barclays, HSBC, Lloyds and similar exports all read without configuration.

The three column layouts we read (gold examples in evals/gold/bank/):

1. One signed amount column
   Barclays-style: Number, Date, Account, Amount, Subcategory, Memo  (Memo = description)
   Monzo-style:    Transaction ID, Date, Time, Type, Name, Emoji, Category, Amount, Currency, ...,
                   Notes and #tags, ..., Description, Money Out, Money In  (Name = description; Amount wins
                   over Money Out / Money In)
2. Signed amount plus counterparty and running balance
   Starling-style: Date, Counter Party, Reference, Type, Amount (GBP), Balance (GBP), Spending Category, Notes
3. Separate paid-in / paid-out columns
   Tide-style:     Date, Transaction ID, Transaction Type, Name/Description, Reference, Paid in, Paid out, Balance
   (HSBC and Lloyds exports use the same idea: Paid in/Paid out or Debit Amount/Credit Amount)

`detect_bank` names the bank from the header so filed statements read "2026-10-31_starling.csv".
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel

#: matched/transfer/ignored are the user's decisions (stored); suggested is computed on read.
BankLineStatus = Literal["unmatched", "matched", "suggested", "transfer", "ignored"]
RESOLVED: tuple[str, ...] = ("matched", "transfer", "ignored")
BankName = Literal["barclays", "starling", "tide", "monzo", "bank"]

DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d/%m/%y", "%d-%b-%Y", "%d %b %y")

#: Column role -> header names that mean it (lowercase, compared after stripping punctuation).
HEADERS: dict[str, tuple[str, ...]] = {
    "date": ("date", "transaction date", "posting date", "posted date", "value date"),
    "description": ("description", "details", "narrative", "transaction description", "transaction information", "memo", "name",
                    "counter party", "counterparty", "payee", "merchant", "name/description"),
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
    proposal_id: str | None = None  # an expense proposal made from this line ("create expense proposal")

    @property
    def resolved(self) -> bool:
        return self.status in RESOLVED

    def event_ids(self) -> list[str]:
        return self.matched_event_ids or ([self.matched_event_id] if self.matched_event_id else [])


class BankCsvError(ValueError):
    """The file does not look like a bank statement we can read."""


def reconciled_to(lines: Sequence[BankLine]) -> date | None:
    """Latest date up to which every bank line is matched, a transfer or ignored; None if the first day isn't."""
    open_days = sorted({ln.date for ln in lines if not ln.resolved})
    done_days = sorted({ln.date for ln in lines if ln.resolved})
    before = [d for d in done_days if not open_days or d < open_days[0]]
    return before[-1] if before else None


#: What to do with a bank line nothing in the ledger matches.
UnmatchedAction = Literal["create_expense_proposal", "mark_transfer", "ignore"]
TRANSFER_WORDS = re.compile(r"\b(transfer|tfr|savings?|own account|between accounts|pot|isa|sweep)\b", re.IGNORECASE)
IGNORE_WORDS = re.compile(r"\b(pending|reversal|reversed|declined|authorisation)\b", re.IGNORECASE)
FEE_WORDS = re.compile(r"\b(fee|fees|charge|charges|interest|commission)\b", re.IGNORECASE)


class ActionHint(BaseModel):
    action: UnmatchedAction
    reason: str


def suggest_action(line: BankLine) -> ActionHint:
    """The likeliest of the three actions for an unmatched line. A hint only: the user picks."""
    text = f"{line.description} {line.reference or ''}"
    if TRANSFER_WORDS.search(text):
        return ActionHint(action="mark_transfer", reason="Looks like money moved between your own accounts")
    if line.amount_pence == 0 or IGNORE_WORDS.search(text):
        return ActionHint(action="ignore", reason="A zero, pending or reversed line has nothing to book")
    if line.amount_pence < 0:
        fee = FEE_WORDS.search(text)
        return ActionHint(action="create_expense_proposal",
                          reason="A bank fee: book it as bank charges" if fee else "Money out with no receipt in the books yet")
    return ActionHint(action="ignore",
                      reason="Money in with no sale in the books: post the sales invoice, or ignore it if it isn't income")


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


#: Header columns that only one bank's export has (normalised), checked in order.
SIGNATURES: tuple[tuple[BankName, frozenset[str]], ...] = (
    ("monzo", frozenset({"transaction id", "emoji"})),
    ("starling", frozenset({"counter party", "spending category"})),
    ("barclays", frozenset({"number", "account", "subcategory", "memo"})),
    ("tide", frozenset({"transaction id", "transaction type", "paid in", "paid out"})),
)


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


def _header_row(data: bytes) -> tuple[int, list[list[str]], dict[str, int]]:
    rows = list(csv.reader(io.StringIO(_decode(data))))
    start = next(((i, c) for i, r in enumerate(rows) if _is_header(c := _columns(r))), None)
    if start is None:
        raise BankCsvError("No Date / Description / Amount header found")
    return start[0], rows, start[1]


def detect_bank(data: bytes) -> BankName:
    """Which bank's export this looks like, from its header row; "bank" when we can't tell.

    Raises BankCsvError when there is no header row at all.
    """
    at, rows, _ = _header_row(data)
    names = {_norm_header(h) for h in rows[at]}
    return next((bank for bank, needed in SIGNATURES if needed <= names), "bank")


def parse_bank_csv(data: bytes, source_file: str) -> list[BankLine]:
    """Every transaction row in a UK bank CSV export. Preamble rows before the header are skipped.

    Raises BankCsvError when no recognisable header row is found.
    """
    header_at, rows, cols = _header_row(data)
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
