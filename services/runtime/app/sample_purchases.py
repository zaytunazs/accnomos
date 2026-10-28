"""SAMPLE — FICTIONAL COMPANIES: a few months of approved purchases with line items, for the tests and test mode's
`purchases` seed (POST /__test/reset?seed=purchases). Each is a posted proposal (the receipt's reading, with its
lines) and the ledger event approved from it, as an approval writes them. Today is test mode's 27 Oct 2026.

What it shows: brown 50 mm tape from Parcelworks bought monthly (once as a cheaper 6-pack), clear 48 mm tape from
Boxmart that is cheaper per metre, a monthly software subscription and water bill, and one large one-off (a saw).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from accnomos_ledger import LedgerEvent, Line, VatCode
from app.books import Books
from app.journal import CATEGORY_ACCOUNTS, CREDITORS, VAT_CONTROL
from app.schemas import ExtractedDoc, ExtractedLine, Proposal

SAMPLE = "SAMPLE — FICTIONAL COMPANY"
TAPE_BROWN = "Tesa 50mm x 66m Brown Packing Tape"
TAPE_BROWN_6 = "Tesa Packing Tape Brown 50mm x 66m (6 pack)"
TAPE_CLEAR = "Packing Tape Clear 48mm x 66m"

# (date, supplier, category, VAT rate %, [(description, qty, unit price £)])
PURCHASES: list[tuple[date, str, str, int, list[tuple[str, float, float]]]] = [
    (date(2026, 6, 3), "Cloudnine Software Ltd", "Software & subscriptions", 20, [("Accounting software", 1, 12.0)]),
    (date(2026, 7, 3), "Cloudnine Software Ltd", "Software & subscriptions", 20, [("Accounting software", 1, 12.0)]),
    (date(2026, 7, 8), "Parcelworks Supplies Ltd", "Materials", 20, [(TAPE_BROWN, 6, 2.10)]),
    (date(2026, 7, 15), "Brightwater Utilities Ltd", "Utilities", 0, [("Water supply", 1, 38.0)]),
    (date(2026, 8, 3), "Cloudnine Software Ltd", "Software & subscriptions", 20, [("Accounting software", 1, 12.0)]),
    (date(2026, 8, 7), "Parcelworks Supplies Ltd", "Materials", 20, [(TAPE_BROWN, 6, 2.10)]),
    (date(2026, 8, 15), "Brightwater Utilities Ltd", "Utilities", 0, [("Water supply", 1, 38.0)]),
    (date(2026, 8, 20), "Boxmart Ltd", "Materials", 20, [(TAPE_CLEAR, 6, 1.65)]),
    (date(2026, 9, 3), "Cloudnine Software Ltd", "Software & subscriptions", 20, [("Accounting software", 1, 12.0)]),
    (date(2026, 9, 8), "Parcelworks Supplies Ltd", "Materials", 20, [(TAPE_BROWN_6, 1, 11.40)]),
    (date(2026, 9, 15), "Brightwater Utilities Ltd", "Utilities", 0, [("Water supply", 1, 38.0)]),
    (date(2026, 10, 3), "Cloudnine Software Ltd", "Software & subscriptions", 20, [("Accounting software", 1, 12.0)]),
    (
        date(2026, 10, 8),
        "Parcelworks Supplies Ltd",
        "Materials",
        20,
        [(TAPE_BROWN, 6, 2.10), ("Double wall cardboard boxes (pack of 25)", 1, 24.0)],
    ),
    (
        date(2026, 10, 14),
        "Boxmart Ltd",
        "Materials",
        20,
        [(TAPE_CLEAR, 6, 1.65), ("Bubble wrap roll 500mm x 100m", 1, 18.50)],
    ),
    (date(2026, 10, 15), "Brightwater Utilities Ltd", "Utilities", 0, [("Water supply", 1, 38.0)]),
    (date(2026, 10, 21), "Harbour Tools Ltd", "Tools & small equipment", 20, [("Mitre saw 254mm", 1, 289.0)]),
]


def _pence(pounds: Decimal) -> int:
    return int((pounds * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


async def seed_purchases(books: Books, user: str = "sam@sambuilds.example") -> int:
    """Write every sample purchase (proposal + ledger event); returns how many."""
    for n, (day, supplier, category, rate, lines) in enumerate(PURCHASES, start=1):
        pid = f"5a3d1e{n:06x}"
        nets = [_pence(Decimal(str(q)) * Decimal(str(u))) for _d, q, u in lines]
        vats = [int((Decimal(n_) * rate / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) for n_ in nets]
        net, vat = sum(nets), sum(vats)
        code = VatCode.STANDARD if rate else VatCode.ZERO
        at = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)
        doc = ExtractedDoc(
            doc_type="receipt",
            supplier_name=supplier,
            supplier_vat_number=None,
            customer_name=None,
            invoice_number=f"S-{n:04d}",
            date=day.isoformat(),
            currency="GBP",
            lines=[
                ExtractedLine(description=d, qty=q, unit_price=u, net=nets[i] / 100, vat_rate=rate, vat=vats[i] / 100)
                for i, (d, q, u) in enumerate(lines)
            ],
            net_total=net / 100,
            vat_total=vat / 100,
            gross_total=(net + vat) / 100,
            payment_method="card",
            card_last4=None,
            category_guess=category,
            confidence=1.0,
        )
        event = LedgerEvent(
            id=f"{pid}{n:02x}".ljust(32, "0"),
            kind="purchase",
            date=day,
            lines=[
                Line(account=CATEGORY_ACCOUNTS[category], debit=net, vat_code=code, memo=SAMPLE),
                *([Line(account=VAT_CONTROL, debit=vat)] if vat else []),
                Line(account=CREDITORS, credit=net + vat),
            ],
            net=net,
            vat=vat,
            counterparty=supplier,
            evidence=[f"{n:064x}"],
            approved_by=user,
            approved_at=at,
            proposal_id=pid,
        )
        proposal = Proposal(
            id=pid,
            doc_sha256=f"{n:064x}",
            extracted=doc,
            checks=[],
            status="posted",
            reasons=[SAMPLE],
            suggested_filename=f"{day.isoformat()} {supplier}.png",
            journal_draft=[],
            model="sample",
            elapsed_s=0.0,
            created_at=at,
            decided_by=user,
            decided_at=at,
            event_id=event.id,
        )
        await books.save_proposal(proposal)
        await books.post_event(event)
    return len(PURCHASES)
