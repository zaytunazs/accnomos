"""HTTP surface. User tokens arrive per request in `X-HMRC-Access-Token`; nothing is stored."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urldefrag, urlencode

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .fraud_headers import ClientFacts, Method, build_headers, missing, request_meta
from .hmrc_client import HmrcClient
from .oauth import OAuth
from .settings import Settings

router = APIRouter()

Vrn = Annotated[str, Path(pattern=r"^\d{9}$")]
Money = Annotated[Decimal, Field(max_digits=15, decimal_places=2, ge=Decimal("-9999999999999.99"),
                                 le=Decimal("9999999999999.99"))]
Pounds = Annotated[int, Field(ge=-9999999999999, le=9999999999999)]


@dataclass
class Relay:
    settings: Settings
    hmrc: HmrcClient
    oauth: OAuth


def relay(request: Request) -> Relay:
    return request.app.state.relay


def configured(r: Annotated[Relay, Depends(relay)]) -> Relay:
    if not r.settings.configured:
        raise HTTPException(503, "Relay is not configured with HMRC credentials")
    return r


def sandbox_only(r: Annotated[Relay, Depends(configured)]) -> Relay:
    if not r.settings.sandbox:
        raise HTTPException(403, "Only available against the HMRC sandbox (HMRC_BASE must be https://test-…)")
    return r


def user_token(x_hmrc_access_token: Annotated[str | None, Header()] = None) -> str:
    if not x_hmrc_access_token:
        raise HTTPException(401, "X-HMRC-Access-Token header required")
    return x_hmrc_access_token


Configured = Annotated[Relay, Depends(configured)]
Sandbox = Annotated[Relay, Depends(sandbox_only)]
UserToken = Annotated[str, Depends(user_token)]


# --- bodies ----------------------------------------------------------------------------------------------

class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")  # subclasses inherit it

    client_facts: ClientFacts
    method: Method
    gov_test_scenario: str | None = Field(None, pattern=r"^[A-Z0-9_]{1,80}$")


class DateRange(Envelope):
    model_config = ConfigDict(populate_by_name=True)
    from_: date = Field(alias="from")
    to: date


class ObligationsBody(DateRange):
    status: Literal["O", "F"] | None = None


class VatReturn(BaseModel):
    """The 11 fields HMRC requires, validated before anything leaves the relay."""

    model_config = ConfigDict(extra="forbid")

    periodKey: str = Field(pattern=r"^[A-Za-z0-9#]{4}$")
    vatDueSales: Money
    vatDueAcquisitions: Money
    totalVatDue: Money
    vatReclaimedCurrPeriod: Money
    netVatDue: Annotated[Decimal, Field(max_digits=13, decimal_places=2, ge=0, le=Decimal("99999999999.99"))]
    totalValueSalesExVAT: Pounds
    totalValuePurchasesExVAT: Pounds
    totalValueGoodsSuppliedExVAT: Pounds
    totalAcquisitionsExVAT: Pounds
    finalised: bool

    @model_validator(mode="after")
    def _boxes_add_up(self) -> VatReturn:
        if self.totalVatDue != self.vatDueSales + self.vatDueAcquisitions:
            raise ValueError("totalVatDue (box 3) must equal vatDueSales + vatDueAcquisitions (boxes 1 + 2)")
        if self.netVatDue != abs(self.totalVatDue - self.vatReclaimedCurrPeriod):
            raise ValueError("netVatDue (box 5) must equal |totalVatDue - vatReclaimedCurrPeriod| (|box 3 - box 4|)")
        return self

    def hmrc_json(self) -> dict:
        return {k: float(v) if isinstance(v, Decimal) else v for k, v in self.model_dump().items()}


class ReturnBody(Envelope):
    model_config = ConfigDict(populate_by_name=True)
    return_: VatReturn = Field(alias="return")


class RefreshBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1, max_length=4096)


class ExchangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=2048)
    code_verifier: str = Field(min_length=43, max_length=128)


# --- helpers ---------------------------------------------------------------------------------------------

def _fraud_headers(r: Relay, request: Request, body: Envelope) -> dict[str, str]:
    peer = request.client
    meta = request_meta(request.headers, peer.host if peer else None, peer.port if peer else None,
                        getattr(request.state, "received_at", None))
    return build_headers(body.method, body.client_facts, meta, r.settings)


def _sent(resp: httpx.Response) -> dict[str, str]:
    """Headers actually sent to HMRC, minus credentials and transport noise, for the client's audit log."""
    return {k: v for k, v in resp.request.headers.items()
            if k.lower().startswith("gov-") or k.lower() in {"accept", "content-type"}}


def _envelope(resp: httpx.Response, fraud: dict[str, str], body: Envelope) -> dict:
    return {
        "hmrc": resp.json() if resp.content else None,
        "sent_headers": _sent(resp),
        "fraud_headers_missing": missing(fraud, body.method),
        "correlation_id": resp.headers.get("X-CorrelationId"),
        "receipt_id": resp.headers.get("Receipt-ID"),
        "receipt_timestamp": resp.headers.get("Receipt-Timestamp"),
    }


async def _vat(r: Relay, request: Request, token: str, body: Envelope, method: str, path: str, **kw) -> dict:
    fraud = _fraud_headers(r, request, body)
    resp = await r.hmrc.request(method, path, bearer=token, headers=fraud,
                                gov_test_scenario=body.gov_test_scenario, **kw)
    return _envelope(resp, fraud, body)


# --- OAuth -----------------------------------------------------------------------------------------------

@router.get("/hmrc/authorize")
async def authorize(r: Configured, redirect_to: str, code_challenge: str | None = None) -> dict:
    """Build the HMRC consent URL. With `code_challenge` (S256) the callback hands back the code instead of
    tokens and the client finishes via POST /hmrc/exchange with its verifier, which only it holds."""
    if not r.settings.redirect_allowed(redirect_to):
        raise HTTPException(400, "redirect_to is not an allowed origin (RELAY_ALLOWED_REDIRECTS)")
    url, state = r.oauth.authorize_url(urldefrag(redirect_to).url, code_challenge)
    return {"url": url, "state": state}


@router.get("/hmrc/callback")
async def callback(r: Configured, state: str, code: str | None = None, error: str | None = None,
                   error_description: str | None = None) -> RedirectResponse:
    """HMRC redirects here. Tokens go back in the URL fragment so they never reach any server's logs."""
    st = r.oauth.read_state(state, use="callback")
    if not r.settings.redirect_allowed(st.redirect_to):
        raise HTTPException(400, "redirect_to is no longer allowed")
    if error or not code:
        frag = {"error": error or "missing_code", "error_description": error_description or "", "state": state}
    elif st.pkce:
        frag = {"code": code, "state": state}
    else:
        tokens = await r.oauth.exchange_code(code)
        frag = {**{k: tokens[k] for k in ("access_token", "refresh_token", "expires_in", "scope", "token_type")
                   if k in tokens}, "state": state}
    return RedirectResponse(f"{st.redirect_to}#{urlencode(frag)}", status_code=303,
                            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.post("/hmrc/exchange")
async def exchange(r: Configured, body: ExchangeBody) -> dict:
    """PKCE completion: the client posts the code from the fragment plus its code_verifier."""
    if not r.oauth.read_state(body.state, use="exchange").pkce:
        raise HTTPException(400, "state was not issued for a PKCE flow")
    return await r.oauth.exchange_code(body.code, body.code_verifier)


@router.post("/hmrc/refresh")
async def refresh(r: Configured, body: RefreshBody) -> dict:
    return await r.oauth.refresh(body.refresh_token)


# --- VAT (MTD) 1.0, user-restricted -------------------------------------------------------------------------

@router.post("/vat/{vrn}/obligations")
async def obligations(r: Configured, request: Request, token: UserToken, vrn: Vrn, body: ObligationsBody) -> dict:
    params = {"from": body.from_.isoformat(), "to": body.to.isoformat(), "status": body.status}
    return await _vat(r, request, token, body, "GET", f"/organisations/vat/{vrn}/obligations", params=params)


@router.post("/vat/{vrn}/returns", status_code=201)
async def submit_return(r: Configured, request: Request, token: UserToken, vrn: Vrn, body: ReturnBody) -> dict:
    return await _vat(r, request, token, body, "POST", f"/organisations/vat/{vrn}/returns",
                      json=body.return_.hmrc_json())


@router.post("/vat/{vrn}/returns/{period_key}/view")
async def view_return(r: Configured, request: Request, token: UserToken, vrn: Vrn,
                      period_key: Annotated[str, Path(pattern=r"^[A-Za-z0-9#]{4}$")], body: Envelope) -> dict:
    return await _vat(r, request, token, body, "GET",
                      f"/organisations/vat/{vrn}/returns/{period_key.replace('#', '%23')}")


@router.post("/vat/{vrn}/liabilities")
async def liabilities(r: Configured, request: Request, token: UserToken, vrn: Vrn, body: DateRange) -> dict:
    params = {"from": body.from_.isoformat(), "to": body.to.isoformat()}
    return await _vat(r, request, token, body, "GET", f"/organisations/vat/{vrn}/liabilities", params=params)


@router.post("/vat/{vrn}/payments")
async def payments(r: Configured, request: Request, token: UserToken, vrn: Vrn, body: DateRange) -> dict:
    params = {"from": body.from_.isoformat(), "to": body.to.isoformat()}
    return await _vat(r, request, token, body, "GET", f"/organisations/vat/{vrn}/payments", params=params)


# --- application-restricted ----------------------------------------------------------------------------------

@router.get("/vat/check/{vrn}")
async def check_vrn(r: Configured, vrn: Vrn) -> dict:
    resp = await r.hmrc.request("GET", f"/organisations/vat/check-vat-number/lookup/{vrn}",
                                bearer=await r.oauth.app_token(), version="2.0")
    return resp.json()


@router.get("/vat/check/{vrn}/{requester_vrn}")
async def check_vrn_with_reference(r: Configured, vrn: Vrn, requester_vrn: Vrn) -> dict:
    resp = await r.hmrc.request("GET", f"/organisations/vat/check-vat-number/lookup/{vrn}/{requester_vrn}",
                                bearer=await r.oauth.app_token(), version="2.0")
    return resp.json()


@router.post("/hmrc/test-user", status_code=201)
async def create_test_user(r: Sandbox) -> dict:
    resp = await r.hmrc.request("POST", "/create-test-user/organisations", bearer=await r.oauth.app_token(),
                                json={"serviceNames": ["mtd-vat"]})
    return resp.json()


@router.post("/hmrc/validate-headers")
async def validate_headers(r: Sandbox, request: Request, body: Envelope) -> dict:
    fraud = _fraud_headers(r, request, body)
    resp = await r.hmrc.request("GET", "/test/fraud-prevention-headers/validate", bearer=await r.oauth.app_token(),
                                headers=fraud)
    return _envelope(resp, fraud, body)


@router.get("/hmrc/validation-feedback")
async def validation_feedback(r: Sandbox, method: Annotated[Method, Query()]) -> dict:
    resp = await r.hmrc.request("GET", "/test/fraud-prevention-headers/vat-mtd/validation-feedback",
                                bearer=await r.oauth.app_token(), params={"connectionMethod": method})
    return resp.json()
