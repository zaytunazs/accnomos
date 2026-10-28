"""/import/*: bring history over from Xero, QuickBooks Online, Sage, FreeAgent or a spreadsheet (app/import_history.py).

Same headers as /books/*. Every write needs `X-User`. Nothing is posted until `POST /import/post`, which the web
wizard sends only after the user has seen the opening entry and ticked that it is right.

    GET    /import                     the draft worked out: mapping, opening entry, open items, checks
    POST   /import/files               upload one export (multipart `file`; form `kind`, `vendor`, `side` optional)
    DELETE /import/files/{id}          drop a file from the draft (the saved upload stays in _System/Import/sources)
    PUT    /import                     vendor, conversion date, P&L treatment, account mapping
    DELETE /import                     start again (the draft only; posted balances are undone with /import/undo)
    POST   /import/post                post the opening entry {accept_warnings}
    GET    /import/opening             the import in force (or the last one, undone) and its reconciliation
    GET    /import/opening/report.csv  the reconciliation as CSV
    POST   /import/undo                reverse the opening entry and take the open items away
    GET    /import/templates/{kind}.csv  the spreadsheet templates
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app import import_formats as fmt
from app import import_history as ih
from app.books import Books
from app.routes_books import get_books, require_user
from app.validation import Day, StrictBody, UnsafeName, check_name

router = APIRouter(prefix="/import", tags=["import"])


@router.get("", response_model=ih.DraftView)
async def get_draft(books: Books = Depends(get_books)) -> ih.DraftView:
    return await ih.view(books)


@router.post("/files", response_model=ih.DraftView)
async def upload(
    file: UploadFile = File(...),
    kind: fmt.FileKind | None = Form(None),
    vendor: fmt.Vendor | None = Form(None),
    side: fmt.Side | None = Form(None),
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> ih.DraftView:
    try:
        name = check_name(file.filename or "export.csv")
    except UnsafeName as exc:
        raise HTTPException(status_code=400, detail=f"Bad file name: {exc}") from exc
    data = await file.read(fmt.MAX_FILE + 1)
    try:
        draft, _ = await ih.add_file(books, data, name, user, kind, vendor, side)
    except fmt.ImportFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await ih.view(books, draft)


@router.delete("/files/{file_id}", response_model=ih.DraftView)
async def remove_file(
    file_id: str, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> ih.DraftView:
    draft = await ih.load_draft(books)
    kept = [f for f in draft.files if f.id != file_id]
    if len(kept) == len(draft.files):
        raise HTTPException(status_code=404, detail="No such file in the import")
    draft.files = kept
    return await ih.view(books, await ih.save_draft(books, draft, user))


class DraftEdit(StrictBody):
    vendor: fmt.Vendor | None = None
    conversion_date: Day | None = None
    pl_treatment: ih.PlTreatment | None = None
    #: source account key -> Accnomos account ("0010 Motor vehicles"); null puts the suggestion back
    mapping: dict[str, str | None] = Field(default_factory=dict, max_length=2000)


@router.put("", response_model=ih.DraftView)
async def edit_draft(
    body: DraftEdit, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> ih.DraftView:
    draft = await ih.load_draft(books)
    if body.vendor is not None:
        draft.vendor = body.vendor
    if body.conversion_date is not None:
        draft.conversion_date = body.conversion_date
    if body.pl_treatment is not None:
        draft.pl_treatment = body.pl_treatment
    keys = {r.key for r in ih.mapping_rows(draft)}
    for key, target in body.mapping.items():
        if key not in keys:
            raise HTTPException(status_code=422, detail="That account is not in the trial balance you uploaded")
        if target is None:
            draft.mapping.pop(key, None)
            continue
        try:
            draft.mapping[key] = ih.validate_target(target)
        except ih.ImportPlanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await ih.view(books, await ih.save_draft(books, draft, user))


@router.delete("", response_model=ih.DraftView)
async def discard(books: Books = Depends(get_books), user: str = Depends(require_user)) -> ih.DraftView:
    await ih.save_draft(books, ih.Draft(), user)
    await books.audit(f"user:{user}", "import_discarded", {})
    return await ih.view(books)


class PostBody(StrictBody):
    accept_warnings: bool = False


@router.post("/post", response_model=ih.OpeningRecord)
async def post(
    body: PostBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> ih.OpeningRecord:
    try:
        return await ih.post(books, user, body.accept_warnings)
    except ih.ImportPlanError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class OpeningView(BaseModel):
    record: ih.OpeningRecord | None
    reconciliation: ih.Reconciliation | None


@router.get("/opening", response_model=OpeningView)
async def opening(books: Books = Depends(get_books)) -> OpeningView:
    rec = await ih.load_record(books)
    return OpeningView(record=rec, reconciliation=await ih.reconcile(books, rec) if rec else None)


@router.get("/opening/report.csv")
async def report(books: Books = Depends(get_books)) -> Response:
    rec = await ih.load_record(books)
    if rec is None:
        raise HTTPException(status_code=404, detail="No opening balances imported")
    body = ih.report_csv(await ih.reconcile(books, rec))
    name = f"opening-balances-{rec.balance_date.isoformat()}.csv"
    return Response(body, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/undo", response_model=ih.OpeningRecord)
async def undo(books: Books = Depends(get_books), user: str = Depends(require_user)) -> ih.OpeningRecord:
    try:
        return await ih.undo(books, user)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No opening balances to undo") from exc
    except ih.ImportUndoError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/templates/{kind}.csv")
async def template(kind: fmt.FileKind, _: Books = Depends(get_books)) -> Response:
    """Like every route, needs a Graph token (tests/test_security_routes.py), though it reads nothing."""
    return Response(
        fmt.TEMPLATES[kind].encode(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="accnomos-{kind.replace("_", "-")}.csv"'},
    )
