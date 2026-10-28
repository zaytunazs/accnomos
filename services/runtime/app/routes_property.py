"""/property/*: landlords and UK property income (app/property.py). Same headers as /books/*; writes need `X-User`.

GET    /categories                 HMRC's property categories with their SA105 boxes and ledger accounts
GET    /settings  PUT /settings    landlord mode, quarter type, consolidated expenses, finance costs brought forward
GET    /properties                 the register;  POST adds one;  PUT /properties/{id} replaces one
POST   /entries                    a quick entry (rent in, a bill out), posted as the user's own approved journal
GET    /entries?tax_year=          entries on a property (tagged, or on the property accounts), newest first
PUT    /tags/{event_id}            tag an approved entry to a property (and category);  DELETE removes the tag
GET    /summary?tax_year=&to=      per property, per owner and the user's share; finance cost credit; warnings
GET    /mtd/{tax_year}?to=         the HMRC request bodies for the period (cumulative + annual) and SA105 boxes
POST   /mtd/{tax_year}/export      saves those bodies as a file in 07 Reports, ready to submit (production path)
POST   /submissions  GET /submissions?tax_year=   what was sent to HMRC's sandbox through the relay, and its answer

The runtime holds no HMRC token (as for VAT): the web submits through the relay (services/hmrc-relay
relay/itsa_property.py, sandbox only) and then records what it sent here.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app import property as pr
from app.books import Books, now
from app.books import today as current_date
from app.paths import REPORTS
from app.projection import SAMPLE_LABEL
from app.routes_books import get_books, require_user
from app.validation import Day, StrictBody

router = APIRouter(prefix="/property", tags=["property"])

TAX_YEAR = r"^20\d{2}-\d{2}$"
TaxYearQ = Annotated[str | None, Query(pattern=TAX_YEAR, max_length=7)]
TaxYearP = Annotated[str, Path(pattern=TAX_YEAR, max_length=7)]


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


def _year(tax_year: str | None, day: date) -> str:
    year = tax_year or pr.tax_year_of(day)
    try:
        pr.tax_year_bounds(year)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return year


async def _summary(
    books: Books, tax_year: str, to: date | None, income_above_pa: int | None = None
) -> tuple[pr.PropertySummary, pr.PropertySettings]:
    start, end = pr.tax_year_bounds(tax_year)
    settings = await pr.load_settings(books)
    try:
        s = pr.summarise(
            await books.list_events(start, min(to or end, end)),
            await pr.load_properties(books),
            await pr.load_tags(books),
            settings,
            tax_year,
            to,
            income_above_pa,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return s, settings


@router.get("/categories")
async def categories() -> list[dict[str, str]]:
    return [
        {"key": c.key, "label": c.label, "group": c.group, "box": c.box, "field": c.field, "account": c.account}
        for c in pr.CATEGORIES
    ]


@router.get("/settings", response_model=pr.PropertySettings)
async def get_settings(books: Books = Depends(get_books)) -> pr.PropertySettings:
    return await pr.load_settings(books)


@router.put("/settings", response_model=pr.PropertySettings)
async def put_settings(
    body: pr.PropertySettingsIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> pr.PropertySettings:
    return await pr.save_settings(books, body, user)


@router.get("/properties", response_model=list[pr.Property])
async def properties(books: Books = Depends(get_books)) -> list[pr.Property]:
    return await pr.load_properties(books)


@router.post("/properties", response_model=pr.Property, status_code=201)
async def post_property(
    body: pr.PropertyIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> pr.Property:
    try:
        return await pr.add_property(books, body, user)
    except pr.PropertyError as exc:
        raise _refused(exc) from exc


@router.put("/properties/{property_id}", response_model=pr.Property)
async def put_property(
    property_id: str, body: pr.PropertyIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> pr.Property:
    try:
        return await pr.update_property(books, property_id, body, user)
    except KeyError as exc:
        raise HTTPException(404, "No such property") from exc


class EntryOut(BaseModel):
    event_id: str
    date: date
    property_id: str | None
    category: str | None
    label: str
    amount_pence: int  # positive; `side` says which way
    side: Literal["income", "cost"]
    description: str | None
    undone: bool


@router.post("/entries", response_model=EntryOut, status_code=201)
async def post_entry(
    body: pr.EntryIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> EntryOut:
    try:
        event, tag = await pr.add_entry(books, body, user)
    except pr.PropertyError as exc:
        raise _refused(exc) from exc
    cat = pr.BY_KEY[tag.category or body.category]
    return EntryOut(
        event_id=event.id,
        date=event.date,
        property_id=tag.property_id,
        category=cat.key,
        label=cat.label,
        amount_pence=body.amount_pence,
        side="income" if cat.group == "income" else "cost",
        description=body.description,
        undone=False,
    )


@router.get("/entries", response_model=list[EntryOut])
async def entries(tax_year: TaxYearQ = None, books: Books = Depends(get_books)) -> list[EntryOut]:
    """Entries that are on a property: tagged ones, and untagged ones on the property accounts (to tag)."""
    year = _year(tax_year, current_date())
    start, end = pr.tax_year_bounds(year)
    events = await books.list_events(start, end)
    tags = await pr.load_tags(books)
    props = {p.id: p for p in await pr.load_properties(books)}
    undone = {e.reverses for e in events if e.reverses}
    out: list[EntryOut] = []
    for ev in events:
        if ev.kind == "reversal":
            continue
        tag = tags.get(ev.id)
        on_accounts = [ln for ln in ev.lines if ln.account in pr.BY_ACCOUNT]
        if tag is None and not on_accounts:
            continue
        use = props[tag.property_id].use if tag and tag.property_id in props else "residential"
        lines = pr._event_lines(ev, use, tag, property_accounts_only=tag is None)
        if not lines:
            continue
        cat = lines[0][0]
        total = sum(p for c, p in lines if (c.group == "income") == (cat.group == "income"))
        memo = next((ln.memo for ln in ev.lines if ln.memo), None) or ev.counterparty
        out.append(
            EntryOut(
                event_id=ev.id,
                date=ev.date,
                property_id=tag.property_id if tag else None,
                category=cat.key,
                label=cat.label,
                amount_pence=abs(total),
                side="income" if cat.group == "income" else "cost",
                description=memo,
                undone=ev.id in undone,
            )
        )
    return sorted(out, key=lambda e: (e.date, e.event_id), reverse=True)


class TagIn(StrictBody):
    property_id: str = Field(max_length=40)
    category: pr.CategoryKey | None = None


@router.put("/tags/{event_id}", status_code=204)
async def put_tag(
    event_id: str, body: TagIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> None:
    try:
        await pr.set_tag(books, event_id, pr.Tag(property_id=body.property_id, category=body.category), user)
    except FileNotFoundError as exc:
        raise HTTPException(404, "No such ledger entry") from exc
    except pr.PropertyError as exc:
        raise _refused(exc) from exc


@router.delete("/tags/{event_id}", status_code=204)
async def delete_tag(event_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)) -> None:
    try:
        await pr.set_tag(books, event_id, None, user)
    except FileNotFoundError as exc:
        raise HTTPException(404, "No such ledger entry") from exc
    except pr.PropertyError as exc:
        raise _refused(exc) from exc


@router.get("/summary", response_model=pr.PropertySummary)
async def summary(
    tax_year: TaxYearQ = None,
    to: Day | None = None,
    income_above_pa: Annotated[int | None, Query(ge=0, le=pr.MAX_PENCE)] = None,
    books: Books = Depends(get_books),
) -> pr.PropertySummary:
    """`income_above_pa`: adjusted total income above the personal allowance, pence, if the user knows it (it is
    the third limit on the finance cost credit and is not in these books)."""
    year = _year(tax_year, to or current_date())
    s, _ = await _summary(books, year, to, income_above_pa)
    return s


class MtdOut(BaseModel):
    tax_year: str
    period_end: date
    quarter_ends: list[date]
    cumulative: dict[str, Any]  # PUT /individuals/business/property/uk/{nino}/{businessId}/cumulative/{taxYear}
    annual: dict[str, Any]  # PUT /individuals/business/property/uk/{nino}/{businessId}/annual/{taxYear}
    consolidated_allowed: bool
    sa105: list[dict[str, Any]]
    summary: pr.PropertySummary


def _period_end(tax_year: str, to: date | None, quarters: Literal["standard", "calendar"], day: date) -> date:
    """`to`, else the end of the latest quarter that has ended (else the first quarter's end)."""
    if to is not None:
        return to
    ends = pr.quarter_ends(tax_year, quarters)
    done = [e for e in ends if e < day]
    return done[-1] if done else ends[0]


async def _mtd(books: Books, tax_year: str, to: date | None) -> MtdOut:
    settings = await pr.load_settings(books)
    end = _period_end(tax_year, to, settings.quarters, current_date())
    s, settings = await _summary(books, tax_year, end)
    if s.tax_year < pr.FIRST_CUMULATIVE_TAX_YEAR:
        raise HTTPException(422, "the cumulative endpoint takes tax years from 2025-26")
    if settings.consolidated_expenses and not pr.consolidated_allowed(s):
        s.warnings.append("Consolidated expenses are only for property income under £90,000; send them itemised.")
    return MtdOut(
        tax_year=tax_year,
        period_end=s.end,
        quarter_ends=pr.quarter_ends(tax_year, settings.quarters),
        cumulative=pr.cumulative_body(s, settings),
        annual=pr.annual_body(s),
        consolidated_allowed=pr.consolidated_allowed(s),
        sa105=pr.sa105_boxes(s),
        summary=s,
    )


@router.get("/mtd/{tax_year}", response_model=MtdOut)
async def mtd(tax_year: TaxYearP, to: Day | None = None, books: Books = Depends(get_books)) -> MtdOut:
    return await _mtd(books, _year(tax_year, current_date()), to)


class ExportIn(StrictBody):
    to: Day | None = None


class ExportOut(BaseModel):
    path: str
    name: str
    web_url: str | None


@router.post("/mtd/{tax_year}/export", response_model=ExportOut)
async def export(
    tax_year: TaxYearP,
    body: ExportIn | None = None,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> ExportOut:
    """A file with exactly what would be sent, for submission by the user's own MTD software or agent. Accnomos
    submits directly only to HMRC's sandbox; this file is the production path (docs/HMRC.md)."""
    out = await _mtd(books, _year(tax_year, current_date()), (body or ExportIn()).to)
    sample = any(p.name.startswith("SAMPLE") for p in await pr.load_properties(books))
    doc = {
        "label": SAMPLE_LABEL if sample else None,
        "what": "UK property income: Making Tax Digital for Income Tax update, ready to submit",
        "api": "Property Business (MTD) API 6.0",
        "made_at": now().isoformat(),
        "tax_year": out.tax_year,
        "period": {"from": out.summary.start.isoformat(), "to": out.period_end.isoformat()},
        "cumulative_period_summary": {
            "method": "PUT",
            "path": "/individuals/business/property/uk/{nino}/{businessId}/cumulative/" + out.tax_year,
            "body": out.cumulative,
        },
        "annual_submission": {
            "method": "PUT",
            "path": "/individuals/business/property/uk/{nino}/{businessId}/annual/" + out.tax_year,
            "body": out.annual,
        },
        "sa105_boxes": out.sa105,
        "warnings": out.summary.warnings,
        "basis": out.summary.basis,
    }
    name = f"{current_date().isoformat()}-uk-property-{out.tax_year}-to-{out.period_end.isoformat()}.json"
    await books.storage.ensure_folder(REPORTS)
    path = await books.free_path(REPORTS, name)
    ref = await books.storage.write(path, json.dumps(doc, indent=2, ensure_ascii=False).encode())
    await books.audit(f"user:{user}", "property_mtd_exported", {"path": path, "tax_year": out.tax_year})
    return ExportOut(path=path, name=path.rsplit("/", 1)[1], web_url=ref.web_url)


class SubmissionIn(StrictBody):
    tax_year: str = Field(pattern=TAX_YEAR, max_length=7)
    kind: Literal["cumulative", "annual"]
    period_end: Day | None = None  # cumulative only
    business_id: str = Field(pattern=r"^X[A-Z0-9]IS\d{11}$", max_length=15)
    sent: dict[str, Any]
    status: int = Field(ge=100, le=599)
    correlation_id: str | None = Field(default=None, max_length=200)
    hmrc: dict[str, Any] | None = None
    sandbox: Literal[True] = True  # direct submission is sandbox only


class Submission(SubmissionIn):
    at: str
    by: str
    matched_books: bool | None  # a cumulative update: was what was sent what the books say now?


@router.post("/submissions", response_model=Submission, status_code=201)
async def post_submission(
    body: SubmissionIn, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> Submission:
    if len(json.dumps(body.sent)) > 20_000 or len(json.dumps(body.hmrc or {})) > 50_000:
        raise HTTPException(413, "submission record too large")
    matched: bool | None = None
    if body.kind == "cumulative" and body.period_end is not None:
        expected = await _mtd(books, body.tax_year, body.period_end)
        matched = expected.cumulative == body.sent
    rec = Submission(**body.model_dump(), at=now().isoformat(), by=user, matched_books=matched)

    def change(raw: Any) -> Any:
        rows = raw if isinstance(raw, list) else []
        return [*rows[-199:], rec.model_dump(mode="json")]

    await books._update_json(pr.SUBMISSIONS, [], change)
    await books.audit(
        f"user:{user}",
        "property_mtd_submitted",
        {"tax_year": body.tax_year, "kind": body.kind, "status": body.status, "matched": matched, "sandbox": True},
    )
    return rec


@router.get("/submissions", response_model=list[Submission])
async def submissions(tax_year: TaxYearQ = None, books: Books = Depends(get_books)) -> list[Submission]:
    rows = await books.read_json(pr.SUBMISSIONS, [])
    out = []
    for r in rows if isinstance(rows, list) else []:
        try:
            s = Submission.model_validate(r)
        except ValueError:
            continue
        if tax_year is None or s.tax_year == tax_year:
            out.append(s)
    return list(reversed(out))
