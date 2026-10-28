"""HTTP surface. User tokens arrive per request in `X-HMRC-Access-Token`; nothing is stored."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urldefrag, urlencode

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .fraud_headers import ClientFacts, Method, build_headers, missing, request_meta
from .hmrc_client import HmrcClient, HmrcError
from .oauth import ALLOWED_SCOPES, SCOPES, OAuth
from .settings import Settings

router = APIRouter()

Vrn = Annotated[str, Path(pattern=r"^\d{9}$")]
Money = Annotated[
    Decimal, Field(max_digits=15, decimal_places=2, ge=Decimal("-9999999999999.99"), le=Decimal("9999999999999.99"))
]
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
    meta = request_meta(
        request.headers,
        peer.host if peer else None,
        peer.port if peer else None,
        getattr(request.state, "received_at", None),
    )
    return build_headers(body.method, body.client_facts, meta, r.settings)


def _sent(resp: httpx.Response) -> dict[str, str]:
    """Headers actually sent to HMRC, minus credentials and transport noise, for the client's audit log."""
    return {
        k: v
        for k, v in resp.request.headers.items()
        if k.lower().startswith("gov-") or k.lower() in {"accept", "content-type"}
    }


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
    resp = await r.hmrc.request(
        method, path, bearer=token, headers=fraud, gov_test_scenario=body.gov_test_scenario, **kw
    )
    return _envelope(resp, fraud, body)


# --- OAuth -----------------------------------------------------------------------------------------------


@router.get("/hmrc/authorize")
async def authorize(
    r: Configured, redirect_to: str, code_challenge: str | None = None, scope: str = Query(SCOPES, max_length=200)
) -> dict:
    """Build the HMRC consent URL. With `code_challenge` (S256) the callback hands back the code instead of
    tokens and the client finishes via POST /hmrc/exchange with its verifier, which only it holds. `scope` is
    space-separated, from read:vat write:vat read:self-assessment write:self-assessment (VAT's two by default)."""
    if not r.settings.redirect_allowed(redirect_to):
        raise HTTPException(400, "redirect_to is not an allowed origin (RELAY_ALLOWED_REDIRECTS)")
    scopes = scope.split()
    if not scopes or not set(scopes) <= ALLOWED_SCOPES:
        raise HTTPException(400, f"scope must be from: {' '.join(sorted(ALLOWED_SCOPES))}")
    url, state = r.oauth.authorize_url(urldefrag(redirect_to).url, code_challenge, " ".join(dict.fromkeys(scopes)))
    return {"url": url, "state": state}


@router.get("/hmrc/callback")
async def callback(
    r: Configured, state: str, code: str | None = None, error: str | None = None, error_description: str | None = None
) -> RedirectResponse:
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
        frag = {
            **{
                k: tokens[k]
                for k in ("access_token", "refresh_token", "expires_in", "scope", "token_type")
                if k in tokens
            },
            "state": state,
        }
    return RedirectResponse(
        f"{st.redirect_to}#{urlencode(frag)}",
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


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
    return await _vat(
        r, request, token, body, "POST", f"/organisations/vat/{vrn}/returns", json=body.return_.hmrc_json()
    )


@router.post("/vat/{vrn}/returns/{period_key}/view")
async def view_return(
    r: Configured,
    request: Request,
    token: UserToken,
    vrn: Vrn,
    period_key: Annotated[str, Path(pattern=r"^[A-Za-z0-9#]{4}$")],
    body: Envelope,
) -> dict:
    return await _vat(
        r, request, token, body, "GET", f"/organisations/vat/{vrn}/returns/{period_key.replace('#', '%23')}"
    )


@router.post("/vat/{vrn}/liabilities")
async def liabilities(r: Configured, request: Request, token: UserToken, vrn: Vrn, body: DateRange) -> dict:
    params = {"from": body.from_.isoformat(), "to": body.to.isoformat()}
    return await _vat(r, request, token, body, "GET", f"/organisations/vat/{vrn}/liabilities", params=params)


@router.post("/vat/{vrn}/payments")
async def payments(r: Configured, request: Request, token: UserToken, vrn: Vrn, body: DateRange) -> dict:
    params = {"from": body.from_.isoformat(), "to": body.to.isoformat()}
    return await _vat(r, request, token, body, "GET", f"/organisations/vat/{vrn}/payments", params=params)


# --- application-restricted ----------------------------------------------------------------------------------


#: Check a UK VAT number v2.0: application-restricted, bearer token with the `read:vat` scope (HMRC OAS, verified
#: 27 Oct 2026; version 1.0 was removed on 17 February 2025).
VAT_CHECK_SCOPE = "read:vat"
VAT_CHECK_VERSION = "2.0"
VAT_CHECK_PATH = "/organisations/vat/check-vat-number/lookup"
VRN_INPUT = re.compile(r"^(?:GB)?(\d{9}|\d{12})$")


def parse_vrn(raw: str, what: str = "VAT number") -> str:
    """'GB 123 4567 89', 'gb123456789' or '123456789' -> '123456789' (9 or 12 digits, as HMRC takes them).
    400 for anything else. GD/HA (government/health) and XI numbers are not checked by this API."""
    s = re.sub(r"[\s.\-]", "", raw.upper())
    m = VRN_INPUT.fullmatch(s)
    if not m:
        raise HTTPException(400, f"{what} must be GB followed by 9 or 12 digits")
    return m.group(1)


def mod97_ok(digits: str) -> bool | None:
    """The 9-digit check digits (old scheme, or the 1999+ scheme that adds 55). None for 12-digit branch numbers.
    Informational only: HMRC's own sandbox test numbers (e.g. 553557881) fail it, so it never blocks a check."""
    if len(digits) != 9:
        return None
    w = sum(int(c) * k for c, k in zip(digits[:7], range(8, 1, -1), strict=True)) + int(digits[7:])
    return w % 97 == 0 or (w + 55) % 97 == 0


def _address(a: dict | None) -> str | None:
    if not isinstance(a, dict):
        return None
    parts = [a.get(f"line{i}") for i in range(1, 6)] + [a.get("postcode")]
    if (cc := a.get("countryCode")) and cc != "GB":
        parts.append(cc)
    text = ", ".join(str(p).strip() for p in parts if p and str(p).strip())
    return text or None


async def _lookup(r: Relay, path: str) -> httpx.Response:
    return await r.hmrc.request("GET", path, bearer=await r.oauth.app_token(VAT_CHECK_SCOPE), version=VAT_CHECK_VERSION)


@router.get("/hmrc/vat-check/{vrn}")
async def vat_check(r: Configured, vrn: str, requester: str | None = Query(None, max_length=20)) -> dict:
    """Is `vrn` VAT-registered, and to whom? With `requester` (the user's own VRN) HMRC also returns a
    consultation number that proves the check was made. 200 with `registered: false` when HMRC says the
    number does not match a registered business (its 404). Bodies are never logged."""
    target = parse_vrn(vrn)
    own = parse_vrn(requester, "Your VAT number") if requester else None
    source = "hmrc-sandbox" if r.settings.sandbox else "hmrc"
    checked_at = datetime.now(UTC).isoformat(timespec="seconds")
    base = {"vrn": f"GB{target}", "checksum_ok": mod97_ok(target), "checked_at": checked_at, "source": source}
    try:
        resp = await _lookup(r, f"{VAT_CHECK_PATH}/{target}" + (f"/{own}" if own else ""))
    except HmrcError as e:
        if e.status == 404:
            return {**base, "registered": False, "name": None, "address": None, "consultation_number": None}
        if e.status == 403 and own:
            raise HTTPException(400, "HMRC doesn't recognise your own VAT number (requester)") from e
        raise
    data = resp.json() if resp.content else {}
    t = data.get("target") or {}
    return {
        **base,
        "registered": True,
        "name": t.get("name"),
        "address": _address(t.get("address")),
        "consultation_number": data.get("consultationNumber"),
        "hmrc_processing_date": data.get("processingDate"),
    }


@router.get("/vat/check/{vrn}")
async def check_vrn(r: Configured, vrn: Vrn) -> dict:
    """HMRC's raw answer; the app uses GET /hmrc/vat-check/{vrn}."""
    return (await _lookup(r, f"{VAT_CHECK_PATH}/{vrn}")).json()


@router.get("/vat/check/{vrn}/{requester_vrn}")
async def check_vrn_with_reference(r: Configured, vrn: Vrn, requester_vrn: Vrn) -> dict:
    return (await _lookup(r, f"{VAT_CHECK_PATH}/{vrn}/{requester_vrn}")).json()


@router.post("/hmrc/test-user", status_code=201)
async def create_test_user(r: Sandbox) -> dict:
    resp = await r.hmrc.request(
        "POST", "/create-test-user/organisations", bearer=await r.oauth.app_token(), json={"serviceNames": ["mtd-vat"]}
    )
    return resp.json()


@router.post("/hmrc/validate-headers")
async def validate_headers(r: Sandbox, request: Request, body: Envelope) -> dict:
    fraud = _fraud_headers(r, request, body)
    resp = await r.hmrc.request(
        "GET", "/test/fraud-prevention-headers/validate", bearer=await r.oauth.app_token(), headers=fraud
    )
    return _envelope(resp, fraud, body)


@router.get("/hmrc/validation-feedback")
async def validation_feedback(r: Sandbox, method: Annotated[Method, Query()]) -> dict:
    resp = await r.hmrc.request(
        "GET",
        "/test/fraud-prevention-headers/vat-mtd/validation-feedback",
        bearer=await r.oauth.app_token(),
        params={"connectionMethod": method},
    )
    return resp.json()
