"""Deterministic repairs applied to a model extraction before the checks run.

Found by the Claude-as-judge pass over 60 synthetic receipts (27 Oct): two systematic model errors
that code can correct safely, each recorded as a Check so the user sees what was changed.
Repairs to figures (REPAIR_CODES) are also listed on the proposal as `repaired_by_code`; never silent.
"""

from __future__ import annotations

import difflib
import itertools
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
    elif (
        doc.doc_type == "sales_invoice"
        and not doc.customer_name
        and doc.payment_method in {"card", "cash", "direct_debit"}
    ):
        doc.doc_type = purchase_kind  # paid at a till or by DD with no customer named: something we bought
    if doc.doc_type != before:
        return Check(
            code="DOC_TYPE_ORIENTED",
            ok=True,
            severity="warn",
            message=f"Treated as {doc.doc_type} (model said {before})",
        )
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
            msg = (
                f"Net {gbp(net)} was the VAT-inclusive total; "
                f"net set to total {gbp(gross)} − VAT {gbp(vat)} = {gbp(gross - vat)}"
            )
        elif rate is not None and abs(round(net * (100 + rate) / 100) - gross) <= 1:
            doc.vat_total = (gross - net) / 100
            msg = (
                f"VAT {gbp(vat)} did not fit net {gbp(net)} and total {gbp(gross)} at {rate:g}%; "
                f"VAT set to {gbp(gross - net)}"
            )
        else:
            return None
    elif (
        rate is not None
        and abs(round(net * rate / 100) - vat) > tol
        and abs(round(net * rate / (100 + rate)) - vat) <= tol
    ):
        doc.gross_total, doc.net_total = net / 100, (net - vat) / 100
        msg = (
            f"VAT had been added on top of the VAT-inclusive total {gbp(net)}; "
            f"total set to {gbp(net)}, net to {gbp(net - vat)}"
        )
    else:
        return None
    return Check(code="TOTALS_REPAIRED", ok=True, severity="warn", message=msg)


def _lines_tol(doc: ExtractedDoc) -> int:
    return max(1, len(doc.lines) // 2)


def _undo_double_qty(doc: ExtractedDoc, anchor: int) -> int:
    """Lines where the printed line TOTAL was read as the unit price and multiplied by qty again.

    Candidates are multi-quantity lines with net == qty x unit_price; the smallest set of them that, taking
    unit_price AS the line net, makes the lines add up to `anchor` is repaired. Returns lines fixed.
    """
    tol = _lines_tol(doc)
    nets = [p(ln.net) for ln in doc.lines]
    if abs(sum(nets) - anchor) <= tol:
        return 0
    cands = [
        i for i, ln in enumerate(doc.lines) if ln.qty > 1 and abs(p(ln.net) - round(ln.qty * ln.unit_price * 100)) <= 1
    ]
    if not cands or len(cands) > 12:
        return 0
    for size in range(1, len(cands) + 1):
        for subset in itertools.combinations(cands, size):
            if abs(sum(nets) - sum(nets[i] - p(doc.lines[i].unit_price) for i in subset) - anchor) <= tol:
                for i in subset:
                    ln = doc.lines[i]
                    line_total = ln.unit_price
                    ln.net, ln.vat, ln.unit_price = line_total, round(ln.vat / ln.qty, 2), round(line_total / ln.qty, 2)
                return len(subset)
    return 0


def _lines_to_net(doc: ExtractedDoc) -> int:
    """Line amounts that add up to the VAT-inclusive total: split each into net + VAT at its own rate.

    Kept only if the split lines then add up to the net and VAT totals. Returns lines changed.
    """
    tol = _lines_tol(doc)
    net, vat, gross = p(doc.net_total), p(doc.vat_total), p(doc.gross_total)
    incl = [p(ln.net) for ln in doc.lines]
    if (
        vat <= 0
        or abs(sum(incl) - net) <= tol
        or abs(sum(incl) - gross) > tol
        or any(ln.vat_rate is None for ln in doc.lines)
    ):
        return 0
    # incl is built from doc.lines and split from incl, so the lengths always match
    split = [(round(a * 100 / (100 + (ln.vat_rate or 0))), ln) for a, ln in zip(incl, doc.lines, strict=True)]
    if (
        abs(sum(n for n, _ in split) - net) > tol
        or abs(sum(a - n for a, (n, _) in zip(incl, split, strict=True)) - vat) > tol
    ):
        return 0
    for a, (n, ln) in zip(incl, split, strict=True):
        ln.net, ln.vat = n / 100, (a - n) / 100
    return len(split)


def _fix_unit_prices(doc: ExtractedDoc) -> int:
    """Lines whose printed total (already including the quantity) sits in the unit-price column.

    Only when the lines already add up to the net total, so the net is right and the unit price is not:
    unit_price = line total / qty; the net is never multiplied again. Returns lines changed.
    """
    if abs(sum(p(ln.net) for ln in doc.lines) - p(doc.net_total)) > _lines_tol(doc):
        return 0
    fixed = 0
    for ln in doc.lines:
        ext = round(ln.qty * ln.unit_price * 100)
        if (
            ln.qty > 1
            and abs(ext - p(ln.net)) > 1
            and abs(ext - p(ln.net + ln.vat)) > 1
            and (abs(p(ln.unit_price) - p(ln.net)) <= 1 or abs(p(ln.unit_price) - p(ln.net + ln.vat)) <= 1)
        ):
            ln.unit_price = round(ln.unit_price / ln.qty, 2)
            fixed += 1
    return fixed


def repair_lines(doc: ExtractedDoc) -> Check | None:
    """Quantity x unit price, line by line, so the lines add up to the net total.

    The anchor is the net total when net + VAT = gross, else gross - VAT (the printed TOTAL is the figure
    the model reads most reliably). When undoing a doubled quantity makes the lines meet that anchor and
    the net total disagreed with it, the net total is set to it too.
    """
    if not doc.lines:
        return None
    net, vat, gross = p(doc.net_total), p(doc.vat_total), p(doc.gross_total)
    anchor = net if abs(net + vat - gross) <= 1 else gross - vat
    notes: list[str] = []
    if doubled := _undo_double_qty(doc, anchor):
        notes.append(f"{doubled} line(s) had the printed line total multiplied by the quantity again; line total kept")
        if net != anchor:
            doc.net_total = anchor / 100
            notes.append(
                f"net set to the lines' sum {gbp(anchor)} (total {gbp(gross)} − VAT {gbp(vat)}), was {gbp(net)}"
            )
    if split := _lines_to_net(doc):
        notes.append(f"{split} line(s) were VAT-inclusive; split into net and VAT at each line's rate")
    if units := _fix_unit_prices(doc):
        notes.append(f"{units} line(s) showed the line total as the unit price; unit price = line total ÷ quantity")
    if not notes:
        return None
    return Check(code="LINES_REPAIRED", ok=True, severity="warn", message="; ".join(notes))


REPAIR_CODES = ("TOTALS_REPAIRED", "LINES_REPAIRED")


def own_credit_note(doc: ExtractedDoc, business_name: str | None) -> Check | None:
    """A credit note the business itself issued is a sale-side document: it belongs on Invoices, where it is
    linked to the invoice it credits. Reading it here as a supplier's would post it against purchases."""
    if doc.doc_type != "credit_note" or not business_name or _similar(doc.supplier_name, business_name) < 0.8:
        return None
    return Check(
        code="OWN_CREDIT_NOTE",
        ok=False,
        severity="fail",
        message="This is your own credit note to a customer: make it on Invoices with Create credit note",
    )


def repair(doc: ExtractedDoc, business_name: str | None) -> list[Check]:
    """Orientation, then totals, then lines (the line repair anchors on the repaired totals)."""
    notes = [
        orient_doc_type(doc, business_name),
        own_credit_note(doc, business_name),
        repair_vat_inclusive_totals(doc),
        repair_lines(doc),
    ]
    return [n for n in notes if n is not None]
