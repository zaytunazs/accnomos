"""Deterministic checks on an extracted document. Pure functions, no I/O.

All money comparisons are done in integer pence with a 1p tolerance, except the
sum-of-line-VAT comparison, which allows 0.5p per line (VAT is often computed on
the total, so per-line rounding legitimately drifts by up to half a penny a line).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.deadlines import MONTHS, period_containing, period_label, previous_period
from app.schemas import Check, ExtractedDoc, Status, VatStatus

VALID_RATES = (0, 5, 20)
FULL_INVOICE_THRESHOLD_GBP = 250.0
MIN_CONFIDENCE = 0.7
#: The check code of "Is <supplier> VAT-registered?"; the Review card offers the "isn't VAT-registered" tick for it.
SUPPLIER_VAT_UNKNOWN = "SUPPLIER_VAT_UNKNOWN"

_VAT_PATTERNS = (
    re.compile(r"^(GB|XI)\d{9}$"),  # standard
    re.compile(r"^(GB|XI)\d{12}$"),  # branch traders
    re.compile(r"^(GB|XI)(GD|HA)\d{3}$"),  # government departments / health authorities
)


def p(amount: float) -> int:
    """Pounds (float, 2 dp) to integer pence."""
    return round(amount * 100)


def gbp(pence: int) -> str:
    return f"£{pence / 100:,.2f}"


def normalise_vat_number(raw: str | None) -> str | None:
    """Upper-case, strip spaces/dots/hyphens and a 'VAT' label; add GB to bare digits."""
    if raw is None:
        return None
    s = re.sub(r"[\s.\-]", "", raw.upper())
    s = re.sub(r"^(VAT(REG)?(NO|NUMBER)?:?)", "", s)
    if not s:
        return None
    if s.isdigit() and len(s) in (9, 12):
        s = "GB" + s
    return s


def _chk(code: str, ok: bool, severity: str, message: str) -> Check:
    return Check(code=code, ok=ok, severity=severity, message=message)  # type: ignore[arg-type]


def check_arith_lines(doc: ExtractedDoc) -> Check:
    """qty x unit_price matches net (or net+VAT when prices are VAT-inclusive); VAT = net x rate."""
    problems: list[str] = []
    for i, ln in enumerate(doc.lines, 1):
        ext = round(ln.qty * ln.unit_price * 100)
        if abs(ext - p(ln.net)) > 1 and abs(ext - p(ln.net + ln.vat)) > 1:
            problems.append(f"line {i} {ln.qty:g} x {ln.unit_price:.2f} ≠ {ln.net:.2f}")
        rate = ln.vat_rate or 0
        expected_vat = round(ln.net * rate)  # net (£) x rate (%) = VAT in pence
        if abs(expected_vat - p(ln.vat)) > 1:
            problems.append(f"line {i} VAT {ln.vat:.2f} ≠ {rate:g}% of {ln.net:.2f}")
    if not doc.lines:
        return _chk("ARITH_LINES", True, "warn", "No line items to check")
    if problems:
        # The ledger posts TOTALS; line detail is evidence. Printed receipts often show VAT-inclusive
        # prices or round VAT per line, so a line mismatch is a warning when the totals themselves hold.
        severity = "warn" if totals_consistent(doc) else "fail"
        return _chk("ARITH_LINES", False, severity, "; ".join(problems))
    return _chk("ARITH_LINES", True, "fail", "Line arithmetic adds up")


def totals_consistent(doc: ExtractedDoc) -> bool:
    """net + VAT == gross (to 1p) — the invariant the ledger relies on."""
    return abs(p(doc.net_total) + p(doc.vat_total) - p(doc.gross_total)) <= 1


def check_arith_totals(doc: ExtractedDoc) -> Check:
    """net+VAT=gross is a hard fail. Lines-vs-totals mismatch is a warning when the totals hold."""
    net, vat, gross = p(doc.net_total), p(doc.vat_total), p(doc.gross_total)
    if abs(net + vat - gross) > 1:
        return _chk("ARITH_TOTALS", False, "fail", f"net {gbp(net)} + VAT {gbp(vat)} ≠ gross {gbp(gross)}")
    problems: list[str] = []
    if doc.lines:
        ln_net = sum(p(ln.net) for ln in doc.lines)
        ln_vat = sum(p(ln.vat) for ln in doc.lines)
        vat_tol = max(1, len(doc.lines) // 2)
        if abs(ln_net - net) > 1:
            problems.append(f"lines net {gbp(ln_net)} ≠ net total {gbp(net)}")
        if abs(ln_vat - vat) > vat_tol:
            problems.append(f"lines VAT {gbp(ln_vat)} ≠ VAT total {gbp(vat)}")
    if problems:
        return _chk("ARITH_TOTALS", False, "warn", "Totals hold; line detail differs: " + "; ".join(problems))
    return _chk("ARITH_TOTALS", True, "fail", "Totals add up")


def check_vat_math(doc: ExtractedDoc) -> Check:
    """When every line carries the same rate, VAT total must be net total x that rate (±2p + 1p/line)."""
    rates = {ln.vat_rate for ln in doc.lines if ln.vat_rate is not None}
    if len(rates) != 1 or any(ln.vat_rate is None for ln in doc.lines):
        return _chk("VAT_MATH", True, "warn", "Mixed or unknown rates; VAT checked via totals only")
    rate = rates.pop()
    expected = round(doc.net_total * rate)  # pence
    tol = 2 + len(doc.lines)
    if abs(expected - p(doc.vat_total)) > tol:
        return _chk(
            "VAT_MATH",
            False,
            "fail",
            f"VAT {doc.vat_total:.2f} ≠ {rate:g}% of net {doc.net_total:.2f} ({expected / 100:.2f})",
        )
    return _chk("VAT_MATH", True, "fail", f"VAT is {rate:g}% of net")


def check_vat_rates(doc: ExtractedDoc) -> Check:
    bad = sorted({ln.vat_rate for ln in doc.lines if ln.vat_rate is not None and ln.vat_rate not in VALID_RATES})
    if bad:
        return _chk("VAT_RATE_VALID", False, "fail", f"Unexpected UK VAT rate(s): {', '.join(f'{r:g}%' for r in bad)}")
    return _chk("VAT_RATE_VALID", True, "fail", "VAT rates are 0/5/20%")


def check_vat_number_format(doc: ExtractedDoc) -> Check:
    vn = normalise_vat_number(doc.supplier_vat_number)
    if vn is None:
        return _chk("VAT_NUMBER_FORMAT", True, "fail", "No VAT number printed")
    if any(pat.match(vn) for pat in _VAT_PATTERNS):
        return _chk("VAT_NUMBER_FORMAT", True, "fail", f"VAT number {vn} looks valid")
    return _chk("VAT_NUMBER_FORMAT", False, "fail", f"VAT number {doc.supplier_vat_number!r} is not a UK format")


@dataclass(frozen=True)
class SupplierKnowledge:
    """What the books know about a supplier's VAT registration (app/contacts.py `supplier_knowledge`).

    The default is a supplier the books have never seen.
    """

    vat_status: VatStatus = "unknown"
    vrn: str | None = None  # the VAT number the books hold for them, if any


UNKNOWN_SUPPLIER = SupplierKnowledge()


def check_vat_number_required(
    doc: ExtractedDoc,
    supplier: SupplierKnowledge = UNKNOWN_SUPPLIER,
    business_vat_registered: bool = True,
) -> Check:
    """VAT can only be reclaimed with the supplier's VAT number on the invoice.

    HMRC VAT Notice 700 s.16: simplified invoices (≤ £250 inc. VAT) must still show the
    supplier's VAT registration number; above £250 a full VAT invoice is needed. Rules, first match wins:

    1. a VAT number on the document: OK (approving it records the supplier as registered);
    2. the user's business is not VAT-registered: OK, it reclaims nothing;
    3. VAT charged, no VAT number: fail (for a supplier known to be registered, the card quotes their number);
    4. a purchase with no VAT, over £250, from a supplier the books don't know yet: SUPPLIER_VAT_UNKNOWN, a fail
       whose message is the question the card asks; ticking "isn't VAT-registered" on approval answers it;
    5. anything else (no VAT under £250, or a known supplier): OK.
    """
    if normalise_vat_number(doc.supplier_vat_number) is not None:
        return _chk("VAT_NUMBER_REQUIRED", True, "fail", "VAT number shown")
    if not business_vat_registered:
        return _chk(
            "VAT_NUMBER_REQUIRED", True, "fail", "Your business isn't VAT-registered, so no VAT number is needed"
        )
    if doc.vat_total > 0:
        if supplier.vat_status == "registered":
            usual = f"their VAT number is usually {supplier.vrn}" if supplier.vrn else "they are VAT-registered"
            msg = f"VAT charged but no VAT number shown; {usual}; the VAT can't be reclaimed without it"
        elif doc.gross_total > FULL_INVOICE_THRESHOLD_GBP:
            msg = "Over £250 needs a full VAT invoice with the supplier's VAT number"
        else:
            msg = "VAT charged but no VAT number shown, so the VAT can't be reclaimed"
        return _chk("VAT_NUMBER_REQUIRED", False, "fail", msg)
    if supplier.vat_status == "not_registered":
        return _chk(
            "VAT_NUMBER_REQUIRED", True, "fail", "No VAT charged; your books say this supplier isn't VAT-registered"
        )
    if (
        supplier.vat_status == "unknown"
        and doc.doc_type != "sales_invoice"
        and doc.gross_total > FULL_INVOICE_THRESHOLD_GBP
    ):
        name = doc.supplier_name.strip() or "this supplier"
        return _chk(
            SUPPLIER_VAT_UNKNOWN, False, "fail", f"Is {name} VAT-registered? Over £250 they should give a VAT invoice"
        )
    return _chk("VAT_NUMBER_REQUIRED", True, "fail", "No VAT charged, so no VAT number is needed")


def check_duplicate(known_hashes: set[str] | frozenset[str], this_hash: str) -> Check:
    if this_hash in known_hashes:
        return _chk("DUPLICATE", False, "fail", "This exact file has already been uploaded")
    return _chk("DUPLICATE", True, "fail", "Not seen before")


def check_currency(doc: ExtractedDoc) -> Check:
    # Severity is "fail": posting EUR amounts as GBP pence would be wrong until converted.
    if doc.currency != "GBP":
        return _chk("CURRENCY_GBP", False, "fail", f"In {doc.currency}, needs converting to GBP before posting")
    return _chk("CURRENCY_GBP", True, "fail", "In GBP")


def parse_iso_date(s: str) -> date | None:
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def check_date(doc: ExtractedDoc, period_start: date | None, period_end: date | None) -> list[Check]:
    d = parse_iso_date(doc.date)
    if d is None:
        return [_chk("DATE_VALID", False, "fail", f"Date {doc.date!r} is not YYYY-MM-DD")]
    out = [_chk("DATE_VALID", True, "fail", f"Dated {d.isoformat()}")]
    if period_start and period_end:
        out.append(check_date_in_period(d, period_start, period_end))
    elif period_start or period_end:
        inside = (period_start is None or d >= period_start) and (period_end is None or d <= period_end)
        msg = "Inside the VAT period" if inside else f"{d.isoformat()} is outside the current VAT period"
        out.append(_chk("DATE_IN_PERIOD", inside, "warn", msg))
    return out


def check_date_in_period(d: date, start: date, end: date) -> Check:
    """Only ever a warning: the ledger keeps the document's own date, so it goes on the return for that date."""
    if start <= d <= end:
        return _chk("DATE_IN_PERIOD", True, "warn", f"Inside the VAT period {period_label(start, end)}")
    months = (end.year - start.year) * 12 + end.month - start.month + 1
    its_start, its_end = period_containing(d, start.month, months)
    if d > end:
        where = "is after this VAT period ends"
    elif its_end == previous_period(start, months)[1]:
        where = "falls in the previous period"
    else:
        where = "falls in an earlier period"
    msg = (
        f"Dated {d.day} {MONTHS[d.month - 1]} {d.year} — {where}"
        f" ({period_label(its_start, its_end)}); it will go on that return"
    )
    return _chk("DATE_IN_PERIOD", False, "warn", msg)


def check_confidence(doc: ExtractedDoc) -> Check:
    ok = doc.confidence >= MIN_CONFIDENCE
    return _chk("CONFIDENCE", ok, "warn", f"Model confidence {doc.confidence:.2f}" + ("" if ok else " is low"))


def run_checks(
    doc: ExtractedDoc,
    *,
    known_hashes: set[str] | frozenset[str],
    this_hash: str,
    period_start: date | None = None,
    period_end: date | None = None,
    supplier: SupplierKnowledge = UNKNOWN_SUPPLIER,
    business_vat_registered: bool = True,
) -> list[Check]:
    """Run every check in a stable order."""
    return [
        check_arith_lines(doc),
        check_arith_totals(doc),
        check_vat_math(doc),
        check_vat_rates(doc),
        check_vat_number_format(doc),
        check_vat_number_required(doc, supplier, business_vat_registered),
        check_duplicate(known_hashes, this_hash),
        check_currency(doc),
        *check_date(doc, period_start, period_end),
        check_confidence(doc),
    ]


def decide(checks: list[Check]) -> tuple[Status, list[str]]:
    """Any failed `fail` check -> needs_a_look. Reasons list fails first, then warnings."""
    fails = [c for c in checks if not c.ok and c.severity == "fail"]
    warns = [c for c in checks if not c.ok and c.severity == "warn"]
    reasons = [f"{c.code}: {c.message}" for c in (*fails, *warns)]
    return ("needs_a_look" if fails else "proposed"), reasons
