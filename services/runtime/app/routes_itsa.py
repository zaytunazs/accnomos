"""/books/self-employment/*: MTD Income Tax figures from the ledger, receipts of what was sent, and reports.

The runtime holds no HMRC token (as for VAT, app/routes_vat.py). The web page fetches HMRC's businesses,
obligations and calculations through the relay with the user's own HMRC token, submits through the relay after an
explicit confirmation, then posts what was sent and HMRC's answer here. This module:

* GET  summary         the cumulative SA103-style figures for a period, with the ledger lines behind each (code)
* POST receipts        keeps a submission receipt or an HMRC calculation in _System/itsa/{taxYear}/ and audits it;
                       a cumulative update is checked against the books, so a receipt says if what was sent matched
* GET  receipts        what was saved for a tax year, newest first
* GET  reports/{kind}  sa103 / quarterly / calculation as JSON rows, or ?format=csv|xlsx|pdf (app/itsa_reports.py)
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import Field, model_validator

from app import itsa
from app import itsa_reports as rep
from app.books import Books, now
from app.books import today as current_date
from app.paths import ITSA
from app.routes_books import get_books, require_user
from app.validation import StrictBody

router = APIRouter(prefix="/books/self-employment", tags=["self-employment"])

TaxYear = Annotated[str, Field(pattern=r"^20\d{2}-\d{2}$", max_length=7)]
BusinessId = Annotated[str, Field(pattern=r"^X[A-Z0-9]IS\d{11}$", max_length=15)]  # Business Details API 2.0
#: Individual Calculations 8.0 calculationId (HMRC's own pattern, anchored as a whole).
CALC_ID = r"^([0-9]{8}|[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$"
CalculationId = Annotated[str, Field(pattern=CALC_ID, max_length=36)]
Nino = Annotated[str, Field(pattern=r"^[A-Z]{2}\d{6}[A-D]$", max_length=9)]
Short = Annotated[str, Field(max_length=200)]  # IDs and timestamps HMRC sends back
HeaderValue = Annotated[str, Field(max_length=4096)]
INDEX = "receipts.json"


def _bounds(tax_year: str) -> tuple[date, date]:
    try:
        return itsa.tax_year_bounds(tax_year)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


async def _summary(books: Books, tax_year: str, period_end: date) -> itsa.SeSummary:
    start, _ = _bounds(tax_year)
    try:
        return itsa.se_summary(await books.list_events(start, period_end), tax_year, period_end)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


def _default_end(tax_year: str | None, period_end: date | None) -> tuple[str, date]:
    today = current_date()
    ty = tax_year or itsa.tax_year_of(period_end or today)
    start, end = _bounds(ty)
    return ty, period_end or min(max(today, start), end)


@router.get("/summary", response_model=itsa.SeSummary)
async def summary(
    tax_year: str | None = Query(None, pattern=r"^20\d{2}-\d{2}$", description="2026-27; default: this tax year"),
    period_end: date | None = Query(None, description="the obligation's end date; default: today"),
    books: Books = Depends(get_books),
) -> itsa.SeSummary:
    """Cumulative figures from 6 April to `period_end`, computed by code from the approved entries."""
    ty, end = _default_end(tax_year, period_end)
    return await _summary(books, ty, end)


class HmrcEnvelope(StrictBody):
    """The relay's answer (services/hmrc-relay/relay/routes.py `_envelope`), as the page received it."""

    hmrc: Any = None
    sent_headers: dict[str, HeaderValue] = {}
    fraud_headers_missing: list[Short] = []
    correlation_id: Short | None = None
    receipt_id: Short | None = None
    receipt_timestamp: Short | None = None


class ReceiptIn(StrictBody):
    kind: Literal["cumulative", "calculation", "final_declaration"]
    tax_year: TaxYear
    nino: Nino
    business_id: BusinessId | None = None
    period_end: date | None = None  # cumulative: the end date sent
    calculation_id: CalculationId | None = None  # calculation / final declaration
    sent: dict | None = None  # cumulative: the exact body sent to HMRC
    hmrc: HmrcEnvelope
    confirmed_at: datetime | None = None  # when the user ticked the confirmation (cumulative / final)
    declaration: Annotated[str, Field(max_length=1000)] | None = None  # final declaration: the text the user agreed to
    environment: Literal["sandbox", "production"] = "sandbox"

    @model_validator(mode="after")
    def _complete(self) -> ReceiptIn:
        if self.kind == "cumulative" and not (self.business_id and self.period_end and self.sent and self.confirmed_at):
            raise ValueError("a cumulative update needs business_id, period_end, sent and confirmed_at")
        if self.kind in ("calculation", "final_declaration") and not self.calculation_id:
            raise ValueError(f"{self.kind} needs calculation_id")
        if self.kind == "final_declaration" and (self.declaration != itsa.FINAL_DECLARATION or not self.confirmed_at):
            raise ValueError("a final declaration needs HMRC's declaration text, agreed (confirmed_at)")
        return self


def _stamp(ts: datetime) -> str:
    return ts.strftime("%Y%m%dT%H%M%SZ")


@router.post("/receipts", status_code=201)
async def save_receipt(body: ReceiptIn, books: Books = Depends(get_books), user: str = Depends(require_user)) -> dict:
    """Keep what was sent and HMRC's answer in the books, and add an audit line. Never calls HMRC."""
    _bounds(body.tax_year)
    ts = now()
    record: dict[str, Any] = {
        **body.model_dump(mode="json"),
        "saved_at": ts.isoformat(),
        "confirmed_by": user,
        "submitted_at": body.hmrc.receipt_timestamp or ts.isoformat(),
    }
    folder = f"{ITSA}/{body.tax_year}"
    if body.kind == "cumulative":
        assert body.period_end and body.business_id and body.sent is not None
        computed = await _summary(books, body.tax_year, body.period_end)
        record["matches_books"] = body.sent == computed.hmrc_body
        record["event_ids"] = computed.event_ids
        path = f"{folder}/{body.business_id}/update-to-{body.period_end.isoformat()}-{_stamp(ts)}.json"
        action, refs = (
            "itsa_update_submitted",
            {"period_end": body.period_end.isoformat(), "matches": record["matches_books"]},
        )
    elif body.kind == "calculation":
        path = f"{folder}/calculations/{body.calculation_id}.json"
        action, refs = "itsa_calculation_saved", {"calculation": body.calculation_id}
    else:
        path = f"{folder}/final-declaration-{body.calculation_id}.json"
        action, refs = "itsa_final_declaration_submitted", {"calculation": body.calculation_id}
    await books.write_json(path, record)
    entry = {
        "kind": body.kind,
        "path": path,
        "saved_at": ts.isoformat(),
        "business_id": body.business_id,
        "period_end": body.period_end.isoformat() if body.period_end else None,
        "calculation_id": body.calculation_id,
        "correlation_id": body.hmrc.correlation_id,
        "matches_books": record.get("matches_books"),
        "environment": body.environment,
    }
    await books._update_json(f"{folder}/{INDEX}", [], lambda old: [*(old if isinstance(old, list) else []), entry])
    await books.audit(
        f"user:{user}", action, {**refs, "tax_year": body.tax_year, "file": path, "environment": body.environment}
    )
    return {"path": path, **({"matches_books": record["matches_books"]} if "matches_books" in record else {})}


@router.get("/receipts")
async def receipts(tax_year: str = Query(..., pattern=r"^20\d{2}-\d{2}$"), books: Books = Depends(get_books)) -> dict:
    """The receipts index for a tax year, newest first. A missing or hand-edited index lists nothing, never a 500."""
    _bounds(tax_year)
    try:
        raw = await books.read_json(f"{ITSA}/{tax_year}/{INDEX}", [])
    except ValueError:
        raw = []
    items = [r for r in raw if isinstance(r, dict) and isinstance(r.get("path"), str)] if isinstance(raw, list) else []
    return {"tax_year": tax_year, "receipts": sorted(items, key=lambda r: str(r.get("saved_at")), reverse=True)}


async def _stored(books: Books, path: str, tax_year: str) -> dict:
    if not path.startswith(f"{ITSA}/{tax_year}/") or ".." in path or not path.endswith(".json"):
        raise HTTPException(400, "path must be a receipt in this tax year's folder")
    try:
        data = await books.read_json(path, None)
    except ValueError as e:
        raise HTTPException(422, "that receipt file is not valid JSON") from e
    if not isinstance(data, dict):
        raise HTTPException(404, "receipt not found")
    return data


Fmt = Literal["json", "csv", "xlsx", "pdf"]


def _out(report: rep.Report, fmt: Fmt) -> Any:
    if fmt == "json":
        return report.model_dump(mode="json")
    data = rep.render(report, fmt)
    name = f"{report.filename}.{fmt}"
    return Response(
        data,
        media_type=rep.MEDIA[fmt],
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "ETag": hashlib.sha256(data).hexdigest()[:16],
        },
    )


@router.get("/reports/sa103")
async def report_sa103(
    tax_year: str | None = Query(None, pattern=r"^20\d{2}-\d{2}$"),
    period_end: date | None = None,
    format: Fmt = "json",
    books: Books = Depends(get_books),
) -> Any:
    ty, end = _default_end(tax_year, period_end)
    return _out(rep.sa103_report(await _summary(books, ty, end)), format)


@router.get("/reports/quarterly")
async def report_quarterly(
    tax_year: str = Query(..., pattern=r"^20\d{2}-\d{2}$"),
    path: str = Query(..., max_length=300),
    format: Fmt = "json",
    books: Books = Depends(get_books),
) -> Any:
    data = await _stored(books, path, tax_year)
    if data.get("kind") != "cumulative":
        raise HTTPException(400, "that receipt is not a quarterly update")
    return _out(rep.quarterly_report(data), format)


@router.get("/reports/calculation")
async def report_calculation(
    tax_year: str = Query(..., pattern=r"^20\d{2}-\d{2}$"),
    calculation_id: str = Query(..., pattern=CALC_ID),
    format: Fmt = "json",
    books: Books = Depends(get_books),
) -> Any:
    """HMRC's calculation as saved by POST /receipts (kind calculation); HMRC's figures, labelled as HMRC's."""
    data = await _stored(books, f"{ITSA}/{tax_year}/calculations/{calculation_id}.json", tax_year)
    calc = ((data.get("hmrc") or {}).get("hmrc")) or {}
    if not isinstance(calc, dict):
        raise HTTPException(422, "the saved calculation has no HMRC body")
    return _out(rep.calculation_report(calc), format)
