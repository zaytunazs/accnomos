"""/lookup/*: Companies House and HMRC's VAT check (app/company_lookup.py). Read-only suggestions: nothing is saved.

Signed-in callers only (`X-Graph-Token`), so the server's Companies House key is not an open proxy. Errors come
back as `{"error": <code>, "detail": <message>}`: 503 `companies_house_not_configured` /
`vat_check_not_configured`, 400 `bad_query`, 404 `not_found`, 429 `rate_limited` (with Retry-After), 502
`lookup_unavailable`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel

from app import company_lookup as lookup

router = APIRouter(prefix="/lookup", tags=["lookup"])


def signed_in(request: Request) -> None:
    if not request.headers.get("X-Graph-Token", "").strip().removeprefix("Bearer ").strip():
        raise HTTPException(status_code=401, detail="X-Graph-Token header required")


class LookupStatus(BaseModel):
    companies_house: bool  # COMPANIES_HOUSE_API_KEY is set (or test mode): the web app shows Look up
    vat_check: bool  # HMRC_RELAY_URL is set (or test mode): the web app shows Check VAT number
    sample: bool  # test mode: every answer is a fictional SAMPLE


@router.get("/status", response_model=LookupStatus)
async def status() -> LookupStatus:
    """Which look-ups this server can do. No credentials needed: it says only whether they are configured."""
    return LookupStatus(
        companies_house=lookup.configured(), vat_check=lookup.vat_check_configured(), sample=lookup.is_test_mode()
    )


@router.get("/companies", response_model=lookup.CompanySearch, dependencies=[Depends(signed_in)])
async def companies(q: str = Query(min_length=2, max_length=160)) -> lookup.CompanySearch:
    """Companies House matches for a name (or the one company for a company number)."""
    return await lookup.search(q)


@router.get("/companies/{number}", response_model=lookup.CompanyMatch, dependencies=[Depends(signed_in)])
async def company(number: str = Path(max_length=12)) -> lookup.CompanyMatch:
    return await lookup.profile(number)


@router.get("/vat/{vrn}", response_model=lookup.VatCheck, dependencies=[Depends(signed_in)])
async def vat(vrn: str = Path(max_length=20), requester: str | None = Query(None, max_length=20)) -> lookup.VatCheck:
    """HMRC Check a UK VAT number through the relay, without keeping the answer (POST /contacts/vat-check keeps it
    on the contact)."""
    return await lookup.check_vat(vrn, requester)
