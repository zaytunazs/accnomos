"""/exports/*: the Reports & exports page's routes, over the registry in app/exports/registry.py.

    GET  /exports                      the catalogue: groups, every report with formats, params, modes, favourites
    GET  /exports/{id}                 a preview: the report as JSON (ReportDoc), each table cut to `rows` rows
    GET  /exports/{id}/file?format=    the file itself (CSV, XLSX, PDF, zip or JSON), as a download. Reads only
    POST /exports/{id}/save            the same file saved in 07 Reports (never overwriting), audited. Needs X-User
    GET  /exports/mappings/{package}   how each account in the books maps to the package, and its VAT names
    PUT  /exports/mappings/{package}   change some of them (_System/exports/mappings.json). Needs X-User
    GET  /exports/favourites           starred report ids (_System/exports/favourites.json)
    PUT  /exports/favourites           replace them. Needs X-User

Period parameters, as on /reports/*: `from` and `to` (both or neither; default the VAT period we are in now, from the
usual `stagger` / `start_month` / `months`), `as_of` (default `to`, else today), `mode` (a report's own choice, e.g.
journals of every entry or of the balances), and `today` for previews and tests. Nothing here posts to the ledger.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.books import Books
from app.books import today as current_date
from app.exports import registry as reg
from app.exports import writers
from app.exports.mapping import PACKAGES, VAT, Mapped, Target, load_mappings, resolve, save_mappings
from app.exports.vendors import chart
from app.paths import REPORTS, SYSTEM
from app.routes_books import get_books, require_user
from app.validation import Day, StrictBody
from app.vat_cycle import VatCycle, vat_cycle

router = APIRouter(prefix="/exports", tags=["exports"])
FAVOURITES = f"{SYSTEM}/exports/favourites.json"
TODAY = Query(None, description="for previews and tests; defaults to today")
MAX_PREVIEW_ROWS = 2000


class ReportInfo(BaseModel):
    id: str
    group: str
    title: str
    description: str
    formats: list[str]
    params: list[str]
    modes: list[dict[str, str]]
    package: str | None


class Catalogue(BaseModel):
    groups: list[dict[str, str]]
    reports: list[ReportInfo]
    favourites: list[str]
    packages: dict[str, str]


async def _favourites(books: Books) -> list[str]:
    raw = await books.read_json(FAVOURITES, None)
    ids = raw.get("ids") if isinstance(raw, dict) else None
    return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []


@router.get("", response_model=Catalogue)
async def catalogue(books: Books = Depends(get_books)) -> Catalogue:
    specs = reg.catalogue()
    known = [g for g, _ in reg.GROUPS]
    order = {g: i for i, g in enumerate(known)}
    reports = [
        ReportInfo(
            id=s.id,
            group=s.group,
            title=s.title,
            description=s.description,
            formats=list(s.formats),
            params=list(s.params),
            modes=[{"value": v, "label": label} for v, label in s.modes],
            package=s.package,
        )
        for s in sorted(specs.values(), key=lambda s: order.get(s.group, len(order)))
    ]
    extra = sorted({s.group for s in specs.values()} - set(known))
    groups = [{"id": g, "title": t} for g, t in reg.GROUPS] + [
        {"id": g, "title": g.replace("-", " ").capitalize()} for g in extra
    ]
    favs = [f for f in await _favourites(books) if f in specs]
    return Catalogue(groups=groups, reports=reports, favourites=favs, packages=PACKAGES)


# --------------------------------------------------------------------------- #
# Mappings and favourites (declared before /{export_id})
# --------------------------------------------------------------------------- #


class MappingView(BaseModel):
    package: str
    title: str
    accounts: list[Mapped]
    vat: dict[str, dict[str, str]]
    unmapped: int


def _package(package: str) -> str:
    if package not in PACKAGES:
        raise HTTPException(status_code=404, detail=f"unknown package {package!r}")
    return package


async def _view(books: Books, package: str) -> MappingView:
    mappings = await load_mappings(books)
    rows = [resolve(package, a, mappings) for a in chart(await books.list_events())]
    return MappingView(
        package=package,
        title=PACKAGES[package],
        accounts=rows,
        vat={side: dict(names) for side, names in VAT[package].items()},
        unmapped=sum(r.quality == "unmapped" for r in rows),
    )


@router.get("/mappings/{package}", response_model=MappingView)
async def get_mapping(package: str, books: Books = Depends(get_books)) -> MappingView:
    return await _view(books, _package(package))


class MappingBody(StrictBody):
    accounts: dict[str, Target | None] = Field(max_length=500)


@router.put("/mappings/{package}", response_model=MappingView)
async def put_mapping(
    package: str, body: MappingBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> MappingView:
    _package(package)
    for account, target in body.accounts.items():
        if len(account) > 200 or (target and (len(target.code) > 40 or len(target.name) > 200)):
            raise HTTPException(status_code=422, detail="account, code or name too long")
    await save_mappings(books, package, body.accounts)
    await books.audit(f"user:{user}", "export_mapping_changed", {"package": package, "accounts": sorted(body.accounts)})
    return await _view(books, package)


class Favourites(BaseModel):
    ids: list[str]


class FavouritesBody(StrictBody):
    ids: list[str] = Field(max_length=200)


@router.get("/favourites", response_model=Favourites)
async def get_favourites(books: Books = Depends(get_books)) -> Favourites:
    return Favourites(ids=await _favourites(books))


@router.put("/favourites", response_model=Favourites)
async def put_favourites(
    body: FavouritesBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> Favourites:
    specs = reg.catalogue()
    unknown = [i for i in body.ids if i not in specs]
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown reports: {', '.join(unknown[:5])}")
    ids = list(dict.fromkeys(body.ids))
    await books.write_json(FAVOURITES, {"version": 1, "ids": ids})
    await books.audit(f"user:{user}", "report_favourites_changed", {"ids": ids})
    return Favourites(ids=ids)


# --------------------------------------------------------------------------- #
# One report
# --------------------------------------------------------------------------- #


def _spec(export_id: str) -> reg.ExportSpec:
    spec = reg.get(export_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"no report {export_id!r}")
    return spec


def _context(
    spec: reg.ExportSpec,
    books: Books,
    cycle: VatCycle,
    today: date | None,
    start: date | None,
    end: date | None,
    as_of: date | None,
    mode: str | None,
) -> reg.ExportContext:
    day = today or current_date()
    if (start is None) != (end is None):
        raise HTTPException(status_code=422, detail="send both 'from' and 'to', or neither")
    if start is None or end is None:
        start, end = cycle.current(day)
    if end < start:
        raise HTTPException(status_code=422, detail="'to' is before 'from'")
    if (end - start).days > 3 * 366:
        raise HTTPException(status_code=422, detail="a report covers at most three years")
    modes = [v for v, _ in spec.modes]
    if mode is not None and mode not in modes:
        raise HTTPException(status_code=422, detail=f"mode must be one of: {', '.join(modes) or 'none'}")
    return reg.ExportContext(
        books=books,
        today=day,
        start=start,
        end=end,
        as_of=as_of or (end if end < day else day),
        cycle=cycle,
        mode=mode or (modes[0] if modes else None),
    )


def _period_slug(spec: reg.ExportSpec, ctx: reg.ExportContext) -> str:
    if "as_of" in spec.params:
        return f"at-{ctx.as_of.isoformat()}"
    if "period" in spec.params:
        return f"{ctx.start.isoformat()}-to-{ctx.end.isoformat()}"
    return ctx.today.isoformat()


def filename(spec: reg.ExportSpec, ctx: reg.ExportContext, fmt: str) -> str:
    """'trial-balance-2026-07-01-to-2026-09-30.csv'."""
    mode = f"-{ctx.mode}" if ctx.mode and spec.modes and ctx.mode != spec.modes[0][0] else ""
    return f"{spec.name}{mode}-{_period_slug(spec, ctx)}.{fmt}"


async def produce(spec: reg.ExportSpec, ctx: reg.ExportContext, fmt: str) -> bytes:
    if fmt not in spec.formats:
        raise HTTPException(status_code=422, detail=f"{spec.id} comes as {', '.join(spec.formats)}")
    if fmt in ("zip", "json"):
        if spec.raw is None:
            raise HTTPException(status_code=422, detail=f"{spec.id} has no {fmt} file")
        return await spec.raw(ctx)
    return writers.render(await spec.build(ctx), fmt)


@router.get("/{export_id}")
async def preview(
    export_id: str,
    start: date | None = Query(None, alias="from"),
    end: date | None = Query(None, alias="to"),
    as_of: date | None = Query(None),
    mode: str | None = Query(None),
    rows: int = Query(300, ge=1, le=MAX_PREVIEW_ROWS),
    today: date | None = TODAY,
    cycle: VatCycle = Depends(vat_cycle),
    books: Books = Depends(get_books),
) -> dict[str, Any]:
    """The report as JSON, each table cut to `rows` rows (`total_rows` says how many it has). Reads only."""
    spec = _spec(export_id)
    ctx = _context(spec, books, cycle, today, start, end, as_of, mode)
    doc = await spec.build(ctx)
    totals = [len(s.rows) for s in doc.sections]
    for s in doc.sections:
        s.rows = s.rows[:rows]
    return {
        "doc": doc.model_dump(mode="json"),
        "total_rows": totals,
        "truncated": any(t > rows for t in totals),
        "from": ctx.start.isoformat(),
        "to": ctx.end.isoformat(),
        "as_of": ctx.as_of.isoformat(),
        "mode": ctx.mode,
        "formats": list(spec.formats),
        "filenames": {f: filename(spec, ctx, f) for f in spec.formats},
    }


@router.get("/{export_id}/file")
async def download(
    export_id: str,
    format: str = Query(..., description="csv, xlsx, pdf, zip or json, as the report offers"),
    start: date | None = Query(None, alias="from"),
    end: date | None = Query(None, alias="to"),
    as_of: date | None = Query(None),
    mode: str | None = Query(None),
    today: date | None = TODAY,
    cycle: VatCycle = Depends(vat_cycle),
    books: Books = Depends(get_books),
) -> Response:
    """The file, as a download. Reads only; nothing is written to the books."""
    spec = _spec(export_id)
    ctx = _context(spec, books, cycle, today, start, end, as_of, mode)
    data = await produce(spec, ctx, format)
    name = filename(spec, ctx, format)
    return Response(
        content=data,
        media_type=reg.MEDIA[format],
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )


class SaveBody(StrictBody):
    format: str
    start: Day | None = Field(None, alias="from")
    end: Day | None = Field(None, alias="to")
    as_of: Day | None = None
    mode: str | None = None


class Saved(BaseModel):
    path: str  # "07 Reports/trial-balance-2026-07-01-to-2026-09-30.csv"
    name: str
    size: int
    web_url: str | None
    format: str


@router.post("/{export_id}/save", response_model=Saved)
async def save(
    export_id: str,
    body: SaveBody,
    today: date | None = TODAY,
    cycle: VatCycle = Depends(vat_cycle),
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> Saved:
    """Save the file in 07 Reports (a second one of the same name gets ' (2)'). Posts nothing to the ledger."""
    spec = _spec(export_id)
    ctx = _context(spec, books, cycle, today, body.start, body.end, body.as_of, body.mode)
    data = await produce(spec, ctx, body.format)
    await books.storage.ensure_folder(REPORTS)
    path = await books.free_path(REPORTS, filename(spec, ctx, body.format))
    ref = await books.storage.write(path, data)
    await books.audit(
        f"user:{user}",
        "report_saved",
        {
            "report": spec.id,
            "format": body.format,
            "path": path,
            "file": path,
            "from": ctx.start.isoformat(),
            "to": ctx.end.isoformat(),
        },
    )
    return Saved(path=path, name=path.rsplit("/", 1)[1], size=ref.size, web_url=ref.web_url, format=body.format)
