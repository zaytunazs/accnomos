"""VAT return from the user's own ledger events — computed by code, never by a model (PRD §3.2)."""

from __future__ import annotations

from datetime import date

from accnomos_ledger import VatReturn, compute_vat_return
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.books import Books
from app.routes_books import get_books

router = APIRouter(prefix="/books", tags=["vat"])


class VatBox(BaseModel):
    box: int
    label: str
    amount: str  # pounds, as HMRC will receive it (2 dp for 1-5, whole for 6-9)
    entries: int


class VatReturnView(BaseModel):
    period_key: str
    start: date
    end: date
    boxes: list[VatBox]
    event_ids: list[str]
    warnings: list[str]
    hmrc_body: dict
    events_in_period: int


LABELS = {
    1: "VAT due on sales",
    2: "VAT due on acquisitions from NI/EU",
    3: "Total VAT due (1 + 2)",
    4: "VAT reclaimed on purchases",
    5: "Net VAT to pay HMRC (3 − 4)",
    6: "Total sales excluding VAT",
    7: "Total purchases excluding VAT",
    8: "Supplies of goods to NI/EU",
    9: "Acquisitions of goods from NI/EU",
}


def quarter_bounds(today: date) -> tuple[date, date, str]:
    """Default to the last complete calendar quarter (e.g. on 27 Oct → 1 Jul–30 Sep)."""
    this_q_start = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
    prev_q_end = this_q_start - date.resolution  # last day of the previous quarter
    prev_q_start = date(prev_q_end.year, ((prev_q_end.month - 1) // 3) * 3 + 1, 1)
    key = f"{prev_q_start.year % 100:02d}A{(prev_q_start.month - 1) // 3 + 1}"
    return prev_q_start, prev_q_end, key


def period_key_for(start: date) -> str:
    return f"{start.year % 100:02d}A{(start.month - 1) // 3 + 1}"


def box_amounts(ret: VatReturn) -> dict[int, str]:
    """The 9 boxes as HMRC will receive them: pounds to 2 dp for 1-5, whole pounds for 6-9."""
    return {
        1: f"{ret.vat_due_sales:.2f}", 2: f"{ret.vat_due_acquisitions:.2f}", 3: f"{ret.total_vat_due:.2f}",
        4: f"{ret.vat_reclaimed:.2f}", 5: f"{ret.net_vat_due:.2f}", 6: str(ret.total_sales_ex_vat),
        7: str(ret.total_purchases_ex_vat), 8: str(ret.goods_supplied_ni_eu), 9: str(ret.acquisitions_ni_eu),
    }


@router.get("/vat", response_model=VatReturnView)
async def vat_return(
    start: date | None = Query(None),
    end: date | None = Query(None),
    period_key: str | None = Query(None),
    books: Books = Depends(get_books),
) -> VatReturnView:
    if start is None or end is None:
        s, e, k = quarter_bounds(date.today())
        start, end, period_key = start or s, end or e, period_key or k
    period_key = period_key or period_key_for(start)
    events = await books.list_events(start, end)
    ret = compute_vat_return(events, period_key, start, end)
    sales = [e for e in events if e.kind == "sale"]
    purchases = [e for e in events if e.kind == "purchase"]
    counts = {1: len(sales), 2: 0, 3: len(sales), 4: len(purchases), 5: len(events), 6: len(sales), 7: len(purchases), 8: 0, 9: 0}
    amounts = box_amounts(ret)
    return VatReturnView(
        period_key=period_key, start=start, end=end,
        boxes=[VatBox(box=i, label=LABELS[i], amount=amounts[i], entries=counts[i]) for i in range(1, 10)],
        event_ids=ret.event_ids, warnings=ret.warnings, hmrc_body=ret.to_hmrc(finalised=False),
        events_in_period=len(events),
    )
