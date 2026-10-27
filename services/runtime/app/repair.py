"""Deterministic repairs applied to a model extraction before the checks run.

Found by the Claude-as-judge pass over 60 synthetic receipts (27 Oct): two systematic model errors
that code can correct safely, each recorded as a Check so the user sees what was changed.
Repairs to figures (REPAIR_CODES) are also listed on the proposal as `repaired_by_code`; never silent.
"""

from __future__ import annotations

import difflib
import re

from app.checks import gbp, p
from app.schemas import Check, ExtractedDoc

_STOP = re.compile(r"\b(ltd|limited|plc|llp|the|and|&|co|company|uk)\b", re.I)


def _norm(name: str | None) -> str:
    return re.sub(r"\s+", " ", _STOP.sub(" ", (name or "").lower())).strip()


def _similar(a: str | None, b: str | None) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def orient_doc_type(doc: ExtractedDoc, business_name: str | None) -> Check | None:
    """Decide sale vs purchase from the books owner's point of view.

    The model only sees the paper; it cannot know whose books these are. If the owner's business
    is the supplier the document is a sale; if the owner is the customer (or no customer is named
    and it was paid by card/cash at a till) it is a purchase.
    """
    before = doc.doc_type
    purchase_kind = "purchase_invoice" if doc.invoice_number else "receipt"
    if business_name:
        # We only ever issue sales invoices as ourselves: a sale iff the supplier is our business.
        if _similar(doc.supplier_name, business_name) >= 0.8:
            doc.doc_type = "sales_invoice"
        elif doc.doc_type == "sales_invoice":
            doc.doc_type = purchase_kind
    elif doc.doc_type == "sales_invoice" and not doc.customer_name and doc.payment_method in {"card", "cash", "direct_debit"}:
        doc.doc_type = purchase_kind  # paid at a till or by DD with no customer named: something we bought
    if doc.doc_type != before:
        return Check(code="DOC_TYPE_ORIENTED", ok=True, severity="warn", message=f"Treated as {doc.doc_type} (model said {before})")
    return None


def _single_rate(doc: ExtractedDoc) -> float | None:
    """The one non-zero VAT rate every line carries, else None (mixed, unknown or no lines)."""
    rates = {ln.vat_rate for ln in doc.lines}
    if len(rates) != 1 or None in rates:
        return None
    rate = rates.pop()
    return rate if rate else None


def repair_vat_inclusive_totals(doc: ExtractedDoc) -> Check | None:
    """Fix totals where the VAT-inclusive TOTAL was read as the net. Only from the document's own figures.

    Three signatures (VAT > 0 in each; when every line has one rate, the repaired VAT must be that rate of
    the repaired net, to the same tolerance VAT_MATH uses):
    * net == gross and net + VAT != gross: the total was copied into net, so net = gross - VAT;
    * net x (1 + rate) == gross but VAT != gross - net: VAT misread, so VAT = gross - net;
    * net + VAT == gross but VAT is the VAT *share* of net (net x rate / (100 + rate)), not rate x net:
      the printed total was taken as net and VAT added on top, so gross = that total, net = total - VAT.
    """
    net, vat, gross = p(doc.net_total), p(doc.vat_total), p(doc.gross_total)
    if vat <= 0:
        return None
    rate = _single_rate(doc)
    tol = 2 + len(doc.lines)

    def vat_fits(n: int) -> bool:
        return rate is None or abs(round(n * rate / 100) - vat) <= tol

    if abs(net + vat - gross) > 1:
        if abs(net - gross) <= 1 and vat_fits(gross - vat):
            doc.net_total = (gross - vat) / 100
            msg = f"Net {gbp(net)} was the VAT-inclusive total; net set to total {gbp(gross)} − VAT {gbp(vat)} = {gbp(gross - vat)}"
        elif rate is not None and abs(round(net * (100 + rate) / 100) - gross) <= 1:
            doc.vat_total = (gross - net) / 100
            msg = f"VAT {gbp(vat)} did not fit net {gbp(net)} and total {gbp(gross)} at {rate:g}%; VAT set to {gbp(gross - net)}"
        else:
            return None
    elif rate is not None and abs(round(net * rate / 100) - vat) > tol and abs(round(net * rate / (100 + rate)) - vat) <= tol:
        doc.gross_total, doc.net_total = net / 100, (net - vat) / 100
        msg = f"VAT had been added on top of the VAT-inclusive total {gbp(net)}; total set to {gbp(net)}, net to {gbp(net - vat)}"
    else:
        return None
    return Check(code="TOTALS_REPAIRED", ok=True, severity="warn", message=msg)


def repair_line_totals(doc: ExtractedDoc) -> Check | None:
    """Fix lines where the printed line TOTAL was read as the unit price and multiplied by qty again.

    Signature: every multi-quantity line has net == qty x unit_price, the line nets overshoot the
    printed net total, and using unit_price AS the line net makes the lines add up to the total.
    """
    multi = [ln for ln in doc.lines if ln.qty and ln.qty > 1]
    if not multi or not doc.lines:
        return None
    net_total = round(doc.net_total * 100)
    as_is = round(sum(ln.net for ln in doc.lines) * 100)
    if abs(as_is - net_total) <= max(1, len(doc.lines) // 2):
        return None  # lines already reconcile
    repaired = round(sum((ln.unit_price if ln in multi else ln.net) for ln in doc.lines) * 100)
    gross_total = round(doc.gross_total * 100)
    repaired_gross = round(sum(((ln.unit_price if ln in multi else ln.net) + (ln.vat if ln not in multi else ln.vat / ln.qty)) for ln in doc.lines) * 100)
    if abs(repaired - net_total) > max(1, len(doc.lines) // 2) and abs(repaired_gross - gross_total) > max(1, len(doc.lines) // 2):
        return None
    fixed = 0
    for ln in multi:
        if abs(ln.net - ln.qty * ln.unit_price) <= 0.011:
            line_total = ln.unit_price
            ln.unit_price = round(line_total / ln.qty, 4)
            ln.net = round(line_total, 2)
            ln.vat = round(ln.vat / ln.qty, 2)
            fixed += 1
    if not fixed:
        return None
    return Check(code="LINES_REPAIRED", ok=True, severity="warn", message=f"{fixed} line(s): printed line total had been read as unit price; corrected")


REPAIR_CODES = ("TOTALS_REPAIRED", "LINES_REPAIRED")


def repair(doc: ExtractedDoc, business_name: str | None) -> list[Check]:
    """Orientation, then totals, then lines."""
    notes = [orient_doc_type(doc, business_name), repair_vat_inclusive_totals(doc), repair_line_totals(doc)]
    return [n for n in notes if n is not None]
