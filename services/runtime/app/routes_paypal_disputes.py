"""PayPal disputes on invoice payments (app/paypal_disputes.py). Same headers as /books/*.

    GET  /payments/online/paypal/disputes                         disputes, matched to invoices (reads only)
    POST /payments/online/paypal/disputes/{id}/evidence           build the evidence: facts, checked draft, PDF
    GET  /payments/online/paypal/disputes/{id}/evidence.pdf       the evidence PDF, for the preview
    POST /payments/online/paypal/disputes/{id}/evidence/send      {confirm: true}: send it to PayPal
    POST /payments/online/paypal/disputes/{id}/reversal           {confirm: true}: post the reversing entry (lost)

Nothing reaches PayPal without `confirm: true`, which the app sets only after the owner taps Send.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app import demo
from app import paypal_disputes as pd
from app.ai.config import AiConfig, ai_config_from_request
from app.books import Books
from app.invoicing import InvoiceError
from app.routes_books import get_books, require_user
from app.routes_online_payments import ConfirmBody

router = APIRouter(prefix="/payments/online/paypal/disputes", tags=["online payments"])


def _http(exc: InvoiceError) -> HTTPException:
    if str(exc) == "No such dispute":
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("", response_model=pd.DisputeList)
async def disputes(request: Request, books: Books = Depends(get_books)) -> pd.DisputeList:
    return await pd.list_disputes(books, sample=demo.is_demo_request(request))


@router.post("/{dispute_id}/evidence", response_model=pd.EvidenceProposal)
async def build(
    dispute_id: str,
    request: Request,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
    cfg: AiConfig = Depends(ai_config_from_request),
) -> pd.EvidenceProposal:
    """Drafting sends nothing: the owner previews the response and the PDF first."""
    try:
        return await pd.build_evidence(books, dispute_id, cfg, user, sample=demo.is_demo_request(request))
    except InvoiceError as exc:
        raise _http(exc) from exc


@router.get("/{dispute_id}/evidence.pdf")
async def pdf(dispute_id: str, books: Books = Depends(get_books)) -> Response:
    try:
        data = await pd.evidence_pdf(books, dispute_id)
    except (InvoiceError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Build the evidence first") from exc
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="dispute-{dispute_id}.pdf"'},
    )


@router.post("/{dispute_id}/evidence/send", response_model=pd.EvidenceProposal)
async def send(
    dispute_id: str,
    body: ConfirmBody,
    request: Request,
    books: Books = Depends(get_books),
    user: str = Depends(require_user),
) -> pd.EvidenceProposal:
    if body.confirm is not True:
        raise HTTPException(status_code=400, detail="Nothing was sent: approve in the app first (confirm: true)")
    try:
        return await pd.send_evidence(books, dispute_id, user, sample=demo.is_demo_request(request))
    except (InvoiceError, FileNotFoundError) as exc:
        raise (_http(exc) if isinstance(exc, InvoiceError) else HTTPException(404, "Build the evidence first")) from exc


@router.post("/{dispute_id}/reversal", response_model=pd.ReversalProposal)
async def reversal(
    dispute_id: str, body: ConfirmBody, books: Books = Depends(get_books), user: str = Depends(require_user)
) -> pd.ReversalProposal:
    if body.confirm is not True:
        raise HTTPException(status_code=400, detail="Nothing was posted: approve in the app first (confirm: true)")
    try:
        return await pd.post_reversal(books, dispute_id, user)
    except InvoiceError as exc:
        raise _http(exc) from exc
