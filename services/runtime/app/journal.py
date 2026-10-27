"""Draft a balanced double-entry journal (integer pence) from an extracted document.

Purchases:  Dr expense (per VAT code) net, Dr 2200 VAT control VAT, Cr bank/cash/creditors.
Sales:      Dr 1100 Debtors gross, Cr 4000 Sales net (per VAT code), Cr 2200 VAT control VAT.

VAT codes: 20%->S, 5%->R, 0%->Z, rate null or no supplier VAT number->N, non-GBP->O.
For N and O the VAT is not reclaimable, so on purchases it is folded into the expense.

The balancing leg is computed from the debit/credit legs, so the draft always balances
even when the printed totals do not; ARITH_* checks flag that case for review.
"""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum

from app.checks import normalise_vat_number, p
from app.schemas import MILEAGE_CATEGORY, ExtractedDoc, ExtractedLine, JournalLine

try:
    from accnomos_ledger.events import VatCode  # pyright: ignore[reportAssignmentType]  (same members as the fallback)
except ImportError:  # runtime used without packages/ledger on sys.path

    class VatCode(StrEnum):  # type: ignore[no-redef]
        S = "S"
        R = "R"
        Z = "Z"
        E = "E"
        O = "O"  # noqa: E741
        N = "N"


VAT_CONTROL = "2200 VAT control"
BANK = "1200 Bank"
CASH = "1210 Cash"
CREDITORS = "2100 Creditors"
DEBTORS = "1100 Debtors"
SALES = "4000 Sales"
#: The business owes the owner/director the mileage allowance: they paid for the journeys themselves.
OWNER_LOAN = "2300 Owner / director loan"

CATEGORY_ACCOUNTS: dict[str, str] = {
    "Materials": "5000 Materials",
    "Tools & small equipment": "5100 Tools & small equipment",
    "Office supplies": "7500 Office supplies",
    "Motor expenses": "7300 Motor expenses",
    MILEAGE_CATEGORY: "7310 Motor — mileage allowance",
    "Travel": "7400 Travel",
    "Subsistence": "7410 Subsistence",
    "Software & subscriptions": "7510 Software & subscriptions",
    "Telephone & internet": "7550 Telephone & internet",
    "Rent": "7100 Rent",
    "Utilities": "7200 Utilities",
    "Insurance": "7700 Insurance",
    "Professional fees": "7600 Professional fees",
    "Advertising": "6200 Advertising",
    "Postage": "7520 Postage",
    "Bank charges": "7900 Bank charges",
}
SUNDRY = "7999 Sundry expenses"
RECLAIMABLE = {"S", "R", "Z"}


def _code(code: str) -> str:
    """Ledger value for a VatCode letter (S/R/Z/E/O/N); validates it against the enum."""
    return str(VatCode(code).value)


def line_vat_code(doc: ExtractedDoc, line: ExtractedLine | None) -> str:
    """VatCode member name for a line (or for the whole doc when `line` is None)."""
    if doc.currency != "GBP":
        return "O"
    if normalise_vat_number(doc.supplier_vat_number) is None:
        return "N"
    rate = line.vat_rate if line is not None else _doc_rate(doc)
    return {20: "S", 5: "R", 0: "Z"}.get(int(rate), "N") if rate is not None else "N"


def _doc_rate(doc: ExtractedDoc) -> float | None:
    if doc.vat_total <= 0:
        return 0 if doc.lines and all(ln.vat_rate == 0 for ln in doc.lines) else None
    rates = [ln.vat_rate for ln in doc.lines if ln.vat_rate]
    return max(rates, key=rates.count) if rates else 20


def _settlement_account(doc: ExtractedDoc) -> str:
    if doc.category_guess == MILEAGE_CATEGORY:
        return OWNER_LOAN
    match doc.payment_method:
        case "cash":
            return CASH
        case "card" | "bank_transfer" | "direct_debit" | "cheque":
            return BANK
        case _:
            return CREDITORS


def _groups(doc: ExtractedDoc) -> dict[str, tuple[int, int]]:
    """Net and VAT pence per VatCode name. Uses lines when they reconcile to totals."""
    groups: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    lines_ok = doc.lines and abs(sum(p(ln.net) for ln in doc.lines) - p(doc.net_total)) <= 1
    if lines_ok:
        for ln in doc.lines:
            g = groups[line_vat_code(doc, ln)]
            g[0] += p(ln.net)
            g[1] += p(ln.vat)
        # Use the printed VAT total, put any rounding difference on the largest VAT group.
        diff = p(doc.vat_total) - sum(g[1] for g in groups.values())
        if diff and abs(diff) <= max(1, len(doc.lines) // 2):
            biggest = max(groups, key=lambda k: groups[k][1])
            groups[biggest][1] += diff
    else:
        groups[line_vat_code(doc, None)] = [p(doc.net_total), p(doc.vat_total)]
    return {k: (v[0], v[1]) for k, v in groups.items()}


def draft_journal(doc: ExtractedDoc) -> list[JournalLine]:
    """Return a balanced journal draft for `doc` (sum debits == sum credits)."""
    groups = _groups(doc)
    out: list[JournalLine] = []

    if doc.doc_type == "sales_invoice":
        vat_total = 0
        for name, (net, vat) in groups.items():
            out.append(JournalLine(account=SALES, credit_pence=net, vat_code=_code(name)))
            vat_total += vat
        if vat_total:
            out.append(
                JournalLine(
                    account=VAT_CONTROL, credit_pence=vat_total, vat_code=_code(max(groups, key=lambda k: groups[k][1]))
                )
            )
        credits = sum(j.credit_pence for j in out)
        out.insert(0, JournalLine(account=DEBTORS, debit_pence=credits, vat_code=None))
        return out

    expense = CATEGORY_ACCOUNTS.get(doc.category_guess, SUNDRY)
    reclaim: dict[str, int] = defaultdict(int)
    for name, (net, vat) in groups.items():
        if name in RECLAIMABLE:
            out.append(JournalLine(account=expense, debit_pence=net, vat_code=_code(name)))
            reclaim[name] += vat
        else:  # not reclaimable: VAT is part of the cost
            out.append(JournalLine(account=expense, debit_pence=net + vat, vat_code=_code(name)))
    for name, vat in reclaim.items():
        if vat:
            out.append(JournalLine(account=VAT_CONTROL, debit_pence=vat, vat_code=_code(name)))
    debits = sum(j.debit_pence for j in out)
    out.append(JournalLine(account=_settlement_account(doc), credit_pence=debits, vat_code=None))
    return out


def is_balanced(journal: list[JournalLine]) -> bool:
    return sum(j.debit_pence for j in journal) == sum(j.credit_pence for j in journal)


def with_expense_account(journal: list[JournalLine], account: str) -> list[JournalLine]:
    """Purchase journal with every expense debit moved to `account` (VAT and settlement untouched)."""
    if any(j.account == DEBTORS for j in journal):  # sales: no expense leg to override
        return journal
    return [
        j.model_copy(update={"account": account}) if j.debit_pence and j.account != VAT_CONTROL else j for j in journal
    ]
