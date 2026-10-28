"""Making Tax Digital for Income Tax (self-employment), user-restricted, through the same envelope as VAT.

Versions and paths are HMRC's live documentation, checked 28 Oct 2026 (docs/HMRC.md has the URLs):

    Business Details 2.0               GET  /individuals/business/details/{nino}/list
    Obligations 3.0                    GET  /obligations/details/{nino}/income-and-expenditure
                                       GET  /obligations/details/{nino}/crystallisation
    Self Employment Business 5.0       PUT  /individuals/business/self-employment/{nino}/{businessId}
                                            /cumulative/{taxYear}    (GET the same path to read it back)
    Individual Calculations 8.0        POST {calc}/trigger/{calculationType}
                                       GET  {calc}  and  {calc}/{calculationId}
                                       POST {calc}/{calculationId}/{calculationType}   (final declaration)
                                       where {calc} = /individuals/calculations/{nino}/self-assessment/{taxYear}
    Self Assessment Test Support 1.0   POST /individuals/self-assessment-test-support/business/{nino}  (sandbox)
    Create Test User 1.0               POST /create-test-user/individuals  (app-restricted, sandbox)

Scopes: read:self-assessment / write:self-assessment. Individual Calculations 8.0 rather than 9.0: 9.0 is listed
"[test only]", Sandbox only, while 8.0 is "Sandbox and Production" with the same four endpoints we use.

Sandbox only. Every route here refuses (403) when HMRC_BASE is production, unless RELAY_ITSA_PRODUCTION=1 is set
as well; nothing in this repository sets it. Writes (the cumulative update and the final declaration) also need
`confirmed: true` in the body, which the page sends only after the user ticks its confirmation, and the final
declaration needs HMRC's declaration text word for word.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .routes import Envelope, Relay, UserToken, _envelope, _fraud_headers, configured

router = APIRouter()

BUSINESS_DETAILS_VERSION = "2.0"
OBLIGATIONS_VERSION = "3.0"
SE_BUSINESS_VERSION = "5.0"
CALCULATIONS_VERSION = "8.0"
TEST_SUPPORT_VERSION = "1.0"
ITSA_SCOPES = "read:self-assessment write:self-assessment"
#: Test users for this API: an individual with a NINO, an SA UTR and an MTD Income Tax ID (Create Test User 1.0).
TEST_USER_SERVICES = ["national-insurance", "self-assessment", "mtd-income-tax"]

#: Verbatim from HMRC's Income Tax MTD end-to-end service guide, "Agreeing to the declaration" (checked 28 Oct 2026).
#: Same text as services/runtime/app/itsa.py FINAL_DECLARATION and apps/web/src/lib/itsa.ts.
FINAL_DECLARATION = (
    "I declare that the information and tax return I have submitted are (taken together) correct and complete to "
    "the best of my knowledge. I understand that I may have to pay financial penalties and face prosecution if I "
    "give false information."
)

Nino = Annotated[str, Path(pattern=r"^[A-Z]{2}\d{6}[A-D]$")]
BusinessId = Annotated[str, Path(pattern=r"^X[A-Z0-9]IS\d{11}$")]
TaxYear = Annotated[str, Path(pattern=r"^20\d{2}-\d{2}$")]
CalculationId = Annotated[
    str, Path(pattern=r"^([0-9]{8}|[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$")
]
# Self-Employment Business 5.0 request schema: numbers to 2 dp, +/-99999999999.99; income 0 or more.
Money = Annotated[
    Decimal, Field(max_digits=13, decimal_places=2, ge=Decimal("-99999999999.99"), le=Decimal("99999999999.99"))
]
Income = Annotated[Decimal, Field(max_digits=13, decimal_places=2, ge=0, le=Decimal("99999999999.99"))]


def itsa_allowed(r: Annotated[Relay, Depends(configured)]) -> Relay:
    if not r.settings.sandbox and not r.settings.relay_itsa_production:
        raise HTTPException(403, "MTD Income Tax is sandbox only (set RELAY_ITSA_PRODUCTION=1 to use production)")
    return r


def sandbox_only(r: Annotated[Relay, Depends(configured)]) -> Relay:
    if not r.settings.sandbox:
        raise HTTPException(403, "Only available against the HMRC sandbox (HMRC_BASE must be https://test-…)")
    return r


Itsa = Annotated[Relay, Depends(itsa_allowed)]
Sandbox = Annotated[Relay, Depends(sandbox_only)]


def tax_year_bounds(tax_year: str) -> tuple[date, date]:
    start, end = int(tax_year[:4]), int(tax_year[5:])
    if (start + 1) % 100 != end:
        raise HTTPException(400, "taxYear must be one year, e.g. 2026-27")
    return date(start, 4, 6), date(start + 1, 4, 5)


# --- bodies ------------------------------------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def hmrc_json(self) -> dict:
        """None fields dropped, Decimals as JSON numbers, nested models likewise."""
        out: dict = {}
        for k, v in self:
            if v is None:
                continue
            out[k] = (
                v.hmrc_json()
                if isinstance(v, _Strict)
                else float(v)
                if isinstance(v, Decimal)
                else (v.isoformat() if isinstance(v, date) else v)
            )
        return out


class PeriodDates(_Strict):
    periodStartDate: date
    periodEndDate: date


class PeriodIncome(_Strict):
    turnover: Income | None = None
    other: Income | None = None
    taxTakenOffTradingIncome: Income | None = None


class PeriodExpenses(_Strict):
    consolidatedExpenses: Money | None = None
    costOfGoods: Money | None = None
    paymentsToSubcontractors: Money | None = None
    wagesAndStaffCosts: Money | None = None
    carVanTravelExpenses: Money | None = None
    premisesRunningCosts: Money | None = None
    maintenanceCosts: Money | None = None
    adminCosts: Money | None = None
    businessEntertainmentCosts: Money | None = None
    advertisingCosts: Money | None = None
    interestOnBankOtherLoans: Money | None = None
    financeCharges: Money | None = None
    irrecoverableDebts: Money | None = None
    professionalFees: Money | None = None
    depreciation: Money | None = None
    otherExpenses: Money | None = None


class PeriodDisallowableExpenses(_Strict):
    costOfGoodsDisallowable: Money | None = None
    paymentsToSubcontractorsDisallowable: Money | None = None
    wagesAndStaffCostsDisallowable: Money | None = None
    carVanTravelExpensesDisallowable: Money | None = None
    premisesRunningCostsDisallowable: Money | None = None
    maintenanceCostsDisallowable: Money | None = None
    adminCostsDisallowable: Money | None = None
    businessEntertainmentCostsDisallowable: Money | None = None
    advertisingCostsDisallowable: Money | None = None
    interestOnBankOtherLoansDisallowable: Money | None = None
    financeChargesDisallowable: Money | None = None
    irrecoverableDebtsDisallowable: Money | None = None
    professionalFeesDisallowable: Money | None = None
    depreciationDisallowable: Money | None = None
    otherExpensesDisallowable: Money | None = None


class CumulativeSummary(_Strict):
    """Create or Amend a Self-Employment Cumulative Period Summary, request body (schema
    createAmendCumulativePeriodSummary/request.json). HMRC: income and expenses must be sent even when zero."""

    periodDates: PeriodDates
    periodIncome: PeriodIncome
    periodExpenses: PeriodExpenses
    periodDisallowableExpenses: PeriodDisallowableExpenses | None = None

    @model_validator(mode="after")
    def _rules(self) -> CumulativeSummary:
        d = self.periodDates
        if d.periodEndDate < d.periodStartDate:
            raise ValueError("periodEndDate is before periodStartDate (HMRC RULE_END_DATE_BEFORE_START_DATE)")
        e = self.periodExpenses
        itemised = any(v is not None for k, v in e if k != "consolidatedExpenses")
        if e.consolidatedExpenses is not None and itemised:
            raise ValueError(
                "send consolidatedExpenses or itemised expenses, not both (HMRC RULE_BOTH_EXPENSES_SUPPLIED)"
            )
        return self


class CumulativeBody(Envelope):
    summary: CumulativeSummary
    confirmed: Literal[True]  # the user ticked the confirmation on the page


class ObligationsBody(Envelope):
    model_config = ConfigDict(populate_by_name=True)
    from_: date | None = Field(None, alias="from")
    to: date | None = None
    status: Literal["open", "fulfilled"] | None = None
    business_id: str | None = Field(None, pattern=r"^X[A-Z0-9]IS\d{11}$")

    @model_validator(mode="after")
    def _range(self) -> ObligationsBody:
        if (self.from_ is None) != (self.to is None):
            raise ValueError("send both from and to, or neither (HMRC: mandatory together)")
        if self.from_ and self.to and not 0 <= (self.to - self.from_).days <= 366:
            raise ValueError("from and to must be in order and at most 366 days apart (HMRC)")
        return self


class FinalObligationsBody(Envelope):
    tax_year: str | None = Field(None, pattern=r"^20\d{2}-\d{2}$")
    status: Literal["open", "fulfilled"] | None = None


class TriggerBody(Envelope):
    calculation_type: Literal["in-year", "intent-to-finalise", "intent-to-amend"] = "in-year"


class ListCalculationsBody(Envelope):
    calculation_type: (
        Literal["in-year", "intent-to-finalise", "intent-to-amend", "final-declaration", "confirm-amendment"] | None
    ) = None


class FinalDeclarationBody(Envelope):
    calculation_type: Literal["final-declaration", "confirm-amendment"] = "final-declaration"
    declaration: str
    confirmed: Literal[True]

    @model_validator(mode="after")
    def _declared(self) -> FinalDeclarationBody:
        if self.declaration != FINAL_DECLARATION:
            raise ValueError("declaration must be HMRC's declaration text, word for word")
        return self


class TestBusiness(_Strict):
    """Self Assessment Test Support 1.0, Create a Test Business: the fields mandatory for self-employment."""

    tradingName: str = Field("Accnomos sandbox trade", min_length=1, max_length=105)
    tradingType: str = Field("Plastering", min_length=1, max_length=35)
    businessAddressLineOne: str = Field("1 Test Street", min_length=1, max_length=35)
    businessAddressPostcode: str = Field("SW16 1AA", pattern=r"^[A-Z]{1,2}[0-9][0-9A-Z]?\s?[0-9][A-Z]{2}$")
    accountingType: Literal["CASH", "ACCRUALS"] = "ACCRUALS"
    commencementDate: date = date(2020, 4, 6)


class TestBusinessBody(Envelope):
    business: TestBusiness = TestBusiness()
    tax_year: str = Field(pattern=r"^20\d{2}-\d{2}$")


# --- helpers -----------------------------------------------------------------------------------------------------


async def _call(
    r: Relay, request: Request, token: str, body: Envelope, method: str, path: str, version: str, **kw
) -> dict:
    fraud = _fraud_headers(r, request, body)
    resp = await r.hmrc.request(
        method, path, bearer=token, version=version, headers=fraud, gov_test_scenario=body.gov_test_scenario, **kw
    )
    return _envelope(resp, fraud, body)


def _cumulative_path(nino: str, business_id: str, tax_year: str) -> str:
    return f"/individuals/business/self-employment/{nino}/{business_id}/cumulative/{tax_year}"


def _calc_path(nino: str, tax_year: str) -> str:
    return f"/individuals/calculations/{nino}/self-assessment/{tax_year}"


# --- routes ------------------------------------------------------------------------------------------------------


@router.post("/itsa/{nino}/businesses")
async def businesses(r: Itsa, request: Request, token: UserToken, nino: Nino, body: Envelope) -> dict:
    """Business Details 2.0, List All Businesses → {listOfBusinesses: [{typeOfBusiness, businessId, ...}]}."""
    return await _call(
        r, request, token, body, "GET", f"/individuals/business/details/{nino}/list", BUSINESS_DETAILS_VERSION
    )


@router.post("/itsa/{nino}/obligations")
async def obligations(r: Itsa, request: Request, token: UserToken, nino: Nino, body: ObligationsBody) -> dict:
    """Obligations 3.0, income and expenditure obligations for self-employment businesses."""
    params = {
        "typeOfBusiness": "self-employment",
        "businessId": body.business_id,
        "fromDate": body.from_.isoformat() if body.from_ else None,
        "toDate": body.to.isoformat() if body.to else None,
        "status": body.status,
    }
    return await _call(
        r,
        request,
        token,
        body,
        "GET",
        f"/obligations/details/{nino}/income-and-expenditure",
        OBLIGATIONS_VERSION,
        params=params,
    )


@router.post("/itsa/{nino}/final-declaration-obligations")
async def final_obligations(
    r: Itsa, request: Request, token: UserToken, nino: Nino, body: FinalObligationsBody
) -> dict:
    """Obligations 3.0, final declaration (crystallisation) obligations."""
    params = {"taxYear": body.tax_year, "status": body.status}
    return await _call(
        r,
        request,
        token,
        body,
        "GET",
        f"/obligations/details/{nino}/crystallisation",
        OBLIGATIONS_VERSION,
        params=params,
    )


@router.post("/itsa/{nino}/self-employment/{business_id}/cumulative/{tax_year}")
async def submit_cumulative(
    r: Itsa,
    request: Request,
    token: UserToken,
    nino: Nino,
    business_id: BusinessId,
    tax_year: TaxYear,
    body: CumulativeBody,
) -> dict:
    """Self-Employment Business 5.0, Create or Amend a Cumulative Period Summary (PUT; HMRC answers 204)."""
    start, end = tax_year_bounds(tax_year)
    if tax_year < "2025-26":
        raise HTTPException(400, "the cumulative endpoint takes tax years from 2025-26")
    d = body.summary.periodDates
    if not (start <= d.periodStartDate <= end and start <= d.periodEndDate <= end):
        raise HTTPException(422, f"period dates must fall within the {tax_year} tax year ({start} to {end})")
    return await _call(
        r,
        request,
        token,
        body,
        "PUT",
        _cumulative_path(nino, business_id, tax_year),
        SE_BUSINESS_VERSION,
        json=body.summary.hmrc_json(),
    )


@router.post("/itsa/{nino}/self-employment/{business_id}/cumulative/{tax_year}/view")
async def view_cumulative(
    r: Itsa, request: Request, token: UserToken, nino: Nino, business_id: BusinessId, tax_year: TaxYear, body: Envelope
) -> dict:
    tax_year_bounds(tax_year)
    return await _call(
        r, request, token, body, "GET", _cumulative_path(nino, business_id, tax_year), SE_BUSINESS_VERSION
    )


@router.post("/itsa/{nino}/calculations/{tax_year}/trigger", status_code=202)
async def trigger_calculation(
    r: Itsa, request: Request, token: UserToken, nino: Nino, tax_year: TaxYear, body: TriggerBody
) -> dict:
    """Individual Calculations 8.0, Trigger (202 {calculationId}). HMRC: wait at least 5 seconds before retrieving."""
    tax_year_bounds(tax_year)
    path = f"{_calc_path(nino, tax_year)}/trigger/{body.calculation_type}"
    return await _call(r, request, token, body, "POST", path, CALCULATIONS_VERSION)


@router.post("/itsa/{nino}/calculations/{tax_year}/list")
async def list_calculations(
    r: Itsa, request: Request, token: UserToken, nino: Nino, tax_year: TaxYear, body: ListCalculationsBody
) -> dict:
    tax_year_bounds(tax_year)
    return await _call(
        r,
        request,
        token,
        body,
        "GET",
        _calc_path(nino, tax_year),
        CALCULATIONS_VERSION,
        params={"calculationType": body.calculation_type},
    )


@router.post("/itsa/{nino}/calculations/{tax_year}/{calculation_id}/view")
async def view_calculation(
    r: Itsa,
    request: Request,
    token: UserToken,
    nino: Nino,
    tax_year: TaxYear,
    calculation_id: CalculationId,
    body: Envelope,
) -> dict:
    """Individual Calculations 8.0, Retrieve. HMRC answers 404 while the calculation is still running."""
    tax_year_bounds(tax_year)
    path = f"{_calc_path(nino, tax_year)}/{calculation_id}"
    return await _call(r, request, token, body, "GET", path, CALCULATIONS_VERSION)


@router.post("/itsa/{nino}/calculations/{tax_year}/{calculation_id}/final-declaration")
async def final_declaration(
    r: Itsa,
    request: Request,
    token: UserToken,
    nino: Nino,
    tax_year: TaxYear,
    calculation_id: CalculationId,
    body: FinalDeclarationBody,
) -> dict:
    """Individual Calculations 8.0, Submit a Self Assessment Final Declaration (HMRC answers 204)."""
    tax_year_bounds(tax_year)
    path = f"{_calc_path(nino, tax_year)}/{calculation_id}/{body.calculation_type}"
    return await _call(r, request, token, body, "POST", path, CALCULATIONS_VERSION)


@router.post("/itsa/{nino}/test-business", status_code=201)
async def create_test_business(
    r: Sandbox, request: Request, token: UserToken, nino: Nino, body: TestBusinessBody
) -> dict:
    """Sandbox only: Self Assessment Test Support 1.0, Create a Test Business (a self-employment for `tax_year`).
    HMRC purges test businesses 7 days after creation."""
    start, end = tax_year_bounds(body.tax_year)
    b = body.business
    payload = {
        "typeOfBusiness": "self-employment",
        **b.hmrc_json(),
        "businessAddressCountryCode": "GB",
        "firstAccountingPeriodStartDate": start.isoformat(),
        "firstAccountingPeriodEndDate": end.isoformat(),
        "quarterlyTypeChoice": {"quarterlyPeriodType": "standard", "taxYearOfChoice": body.tax_year},
    }
    return await _call(
        r,
        request,
        token,
        body,
        "POST",
        f"/individuals/self-assessment-test-support/business/{nino}",
        TEST_SUPPORT_VERSION,
        json=payload,
    )


@router.post("/hmrc/test-user/individual", status_code=201)
async def create_test_individual(r: Sandbox) -> dict:
    """Sandbox only: Create Test User 1.0, an individual enrolled for MTD Income Tax (→ userId, password, nino,
    mtdItId, saUtr, ...)."""
    resp = await r.hmrc.request(
        "POST",
        "/create-test-user/individuals",
        bearer=await r.oauth.app_token(),
        json={"serviceNames": TEST_USER_SERVICES},
    )
    return resp.json()
