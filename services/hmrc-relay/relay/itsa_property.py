"""Making Tax Digital for Income Tax, UK property business: user-restricted, through the same envelope as VAT.

The same design as the self-employment routes (relay/itsa.py on branch claude/self-employment): one stateless
POST per HMRC call carrying `client_facts` and `method` for the fraud-prevention headers, the user's own HMRC token
in `X-HMRC-Access-Token`, sandbox only, and writes only with `confirmed: true`. Paths here sit under
/itsa/{nino}/property/ so they never collide with the self-employment routes when both are merged.

Versions and paths are HMRC's own API definitions (github.com/hmrc/property-business-api
resources/public/api/conf/6.0/application.yaml, obligations-api conf/3.0, mtd-sa-test-support-api conf/1.0;
checked 28 Oct 2026; developer.service.hmrc.gov.uk publishes the same files):

    Business Details 2.0               GET  /individuals/business/details/{nino}/list
    Obligations 3.0                    GET  /obligations/details/{nino}/income-and-expenditure
                                            (typeOfBusiness=uk-property)
    Property Business 6.0              PUT  /individuals/business/property/uk/{nino}/{businessId}/cumulative/{taxYear}
                                       GET  the same path (retrieve)
                                       PUT  /individuals/business/property/uk/{nino}/{businessId}/annual/{taxYear}
    Self Assessment Test Support 1.0   POST /individuals/self-assessment-test-support/business/{nino} (sandbox)

Scopes: read:self-assessment / write:self-assessment. Property Business 6.0 is "BETA" with endpoints released in
production (conf/application.conf). The cumulative endpoint takes tax years from 2025-26 only.

Sandbox only: every route refuses (403) when HMRC_BASE is production, unless RELAY_ITSA_PRODUCTION=1 is set as
well; nothing in this repository sets it. In production Accnomos produces the file to submit instead
(services/runtime /property/mtd/{taxYear}/export).
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
PROPERTY_VERSION = "6.0"
TEST_SUPPORT_VERSION = "1.0"
FIRST_CUMULATIVE_TAX_YEAR = "2025-26"

Nino = Annotated[str, Path(pattern=r"^[A-Z]{2}\d{6}[A-D]$")]
BusinessId = Annotated[str, Path(pattern=r"^X[A-Z0-9]IS\d{11}$")]
TaxYear = Annotated[str, Path(pattern=r"^20\d{2}-\d{2}$")]
LIMIT = Decimal("99999999999.99")
# Property Business 6.0 request schema: 2 dp; income and the residential finance fields 0 or more, expenses signed.
Income = Annotated[Decimal, Field(max_digits=13, decimal_places=2, ge=0, le=LIMIT)]
Money = Annotated[Decimal, Field(max_digits=13, decimal_places=2, ge=-LIMIT, le=LIMIT)]


def property_allowed(r: Annotated[Relay, Depends(configured)]) -> Relay:
    if not r.settings.sandbox and not r.settings.relay_itsa_production:
        raise HTTPException(403, "MTD Income Tax is sandbox only (set RELAY_ITSA_PRODUCTION=1 to use production)")
    return r


def sandbox_only(r: Annotated[Relay, Depends(configured)]) -> Relay:
    if not r.settings.sandbox:
        raise HTTPException(403, "Only available against the HMRC sandbox (HMRC_BASE must be https://test-…)")
    return r


Allowed = Annotated[Relay, Depends(property_allowed)]
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
        """None fields dropped, Decimals as JSON numbers, dates as ISO strings, nested models likewise."""
        out: dict = {}
        for k, v in self:
            if v is None:
                continue
            if isinstance(v, _Strict):
                out[k] = v.hmrc_json()
            elif isinstance(v, list):
                out[k] = [x.hmrc_json() if isinstance(x, _Strict) else x for x in v]
            elif isinstance(v, Decimal):
                out[k] = float(v)
            elif isinstance(v, date):
                out[k] = v.isoformat()
            else:
                out[k] = v
        return out


class RentARoomIncome(_Strict):
    rentsReceived: Income


class RentARoomExpenses(_Strict):
    amountClaimed: Income


class UkIncome(_Strict):
    premiumsOfLeaseGrant: Income | None = None
    reversePremiums: Income | None = None
    periodAmount: Income | None = None
    taxDeducted: Income | None = None
    otherIncome: Income | None = None
    rentARoom: RentARoomIncome | None = None


class UkExpenses(_Strict):
    premisesRunningCosts: Money | None = None
    repairsAndMaintenance: Money | None = None
    financialCosts: Money | None = None
    professionalFees: Money | None = None
    costOfServices: Money | None = None
    other: Money | None = None
    travelCosts: Money | None = None
    consolidatedExpenses: Money | None = None
    residentialFinancialCost: Income | None = None
    residentialFinancialCostsCarriedForward: Income | None = None
    rentARoom: RentARoomExpenses | None = None

    @model_validator(mode="after")
    def _one_way(self) -> UkExpenses:
        # The schema: consolidatedExpenses "can be submitted with residentialFinancialCost,
        # residentialFinancialCostsCarriedForward and rentARoom" only.
        itemised = any(
            getattr(self, k) is not None
            for k in (
                "premisesRunningCosts",
                "repairsAndMaintenance",
                "financialCosts",
                "professionalFees",
                "costOfServices",
                "other",
                "travelCosts",
            )
        )
        if self.consolidatedExpenses is not None and itemised:
            raise ValueError(
                "send consolidatedExpenses or itemised expenses, not both (HMRC RULE_BOTH_EXPENSES_SUPPLIED)"
            )
        return self


class UkProperty(_Strict):
    income: UkIncome | None = None
    expenses: UkExpenses | None = None


class CumulativeSummary(_Strict):
    """Create or Amend a UK Property Cumulative Period Summary, request body
    (schemas/uk_property_cumulative_summary_create_and_amend/def1/request.json). `ukProperty` is required; the
    dates are left out for users with an annual ITSA status (HMRC: RULE_START_AND_END_DATE_NOT_ALLOWED)."""

    fromDate: date | None = None
    toDate: date | None = None
    ukProperty: UkProperty

    @model_validator(mode="after")
    def _dates(self) -> CumulativeSummary:
        if (self.fromDate is None) != (self.toDate is None):
            raise ValueError("send both fromDate and toDate, or neither")
        if self.fromDate and self.toDate and self.toDate < self.fromDate:
            raise ValueError("toDate is before fromDate (HMRC RULE_TO_DATE_BEFORE_FROM_DATE)")
        if self.ukProperty.income is None and self.ukProperty.expenses is None:
            raise ValueError("ukProperty needs income or expenses (HMRC RULE_INCORRECT_OR_EMPTY_BODY_SUBMITTED)")
        return self


class CumulativeBody(Envelope):
    summary: CumulativeSummary
    confirmed: Literal[True]  # the user ticked the confirmation on the page


class AnnualAllowances(_Strict):
    """The allowances Accnomos sends: replacement of domestic items (SA105 box 36). Capital allowances, the
    property income allowance and the adjustments are left to the user's accountant."""

    costOfReplacingDomesticItems: Income | None = None


class AnnualUkProperty(_Strict):
    allowances: AnnualAllowances | None = None


class AnnualSubmission(_Strict):
    ukProperty: AnnualUkProperty


class AnnualBody(Envelope):
    submission: AnnualSubmission
    confirmed: Literal[True]


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


class TestPropertyBusinessBody(Envelope):
    tax_year: str = Field(pattern=r"^20\d{2}-\d{2}$")
    accounting_type: Literal["CASH", "ACCRUALS"] = "CASH"  # cash is the landlord default (HMRC PIM1092)
    quarterly_period_type: Literal["standard", "calendar"] = "standard"


# --- helpers -----------------------------------------------------------------------------------------------------


async def _call(
    r: Relay, request: Request, token: str, body: Envelope, method: str, path: str, version: str, **kw
) -> dict:
    fraud = _fraud_headers(r, request, body)
    resp = await r.hmrc.request(
        method, path, bearer=token, version=version, headers=fraud, gov_test_scenario=body.gov_test_scenario, **kw
    )
    return _envelope(resp, fraud, body)


def _uk(nino: str, business_id: str, what: str, tax_year: str) -> str:
    return f"/individuals/business/property/uk/{nino}/{business_id}/{what}/{tax_year}"


def _from_2025(tax_year: str) -> tuple[date, date]:
    bounds = tax_year_bounds(tax_year)
    if tax_year < FIRST_CUMULATIVE_TAX_YEAR:
        raise HTTPException(400, "UK property updates take tax years from 2025-26 (earlier years used FHL rules)")
    return bounds


# --- routes ------------------------------------------------------------------------------------------------------


@router.post("/itsa/{nino}/property/businesses")
async def businesses(r: Allowed, request: Request, token: UserToken, nino: Nino, body: Envelope) -> dict:
    """Business Details 2.0, List All Businesses; the page picks the one with typeOfBusiness "uk-property"."""
    return await _call(
        r, request, token, body, "GET", f"/individuals/business/details/{nino}/list", BUSINESS_DETAILS_VERSION
    )


@router.post("/itsa/{nino}/property/obligations")
async def obligations(r: Allowed, request: Request, token: UserToken, nino: Nino, body: ObligationsBody) -> dict:
    """Obligations 3.0, income and expenditure obligations of the UK property business."""
    params = {
        "typeOfBusiness": "uk-property",
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


@router.post("/itsa/{nino}/property/{business_id}/cumulative/{tax_year}")
async def submit_cumulative(
    r: Allowed,
    request: Request,
    token: UserToken,
    nino: Nino,
    business_id: BusinessId,
    tax_year: TaxYear,
    body: CumulativeBody,
) -> dict:
    """Property Business 6.0, Create or Amend a UK Property Cumulative Period Summary (PUT; HMRC answers 204)."""
    start, end = _from_2025(tax_year)
    s = body.summary
    if s.fromDate and s.toDate and not (start <= s.fromDate <= end and start <= s.toDate <= end):
        raise HTTPException(422, f"period dates must fall within the {tax_year} tax year ({start} to {end})")
    return await _call(
        r,
        request,
        token,
        body,
        "PUT",
        _uk(nino, business_id, "cumulative", tax_year),
        PROPERTY_VERSION,
        json=s.hmrc_json(),
    )


@router.post("/itsa/{nino}/property/{business_id}/cumulative/{tax_year}/view")
async def view_cumulative(
    r: Allowed,
    request: Request,
    token: UserToken,
    nino: Nino,
    business_id: BusinessId,
    tax_year: TaxYear,
    body: Envelope,
) -> dict:
    _from_2025(tax_year)
    return await _call(r, request, token, body, "GET", _uk(nino, business_id, "cumulative", tax_year), PROPERTY_VERSION)


@router.post("/itsa/{nino}/property/{business_id}/annual/{tax_year}")
async def submit_annual(
    r: Allowed,
    request: Request,
    token: UserToken,
    nino: Nino,
    business_id: BusinessId,
    tax_year: TaxYear,
    body: AnnualBody,
) -> dict:
    """Property Business 6.0, Create and Amend a UK Property Business Annual Submission (PUT; HMRC answers 204)."""
    _from_2025(tax_year)
    return await _call(
        r,
        request,
        token,
        body,
        "PUT",
        _uk(nino, business_id, "annual", tax_year),
        PROPERTY_VERSION,
        json=body.submission.hmrc_json(),
    )


@router.post("/itsa/{nino}/property/test-business", status_code=201)
async def create_test_property_business(
    r: Sandbox, request: Request, token: UserToken, nino: Nino, body: TestPropertyBusinessBody
) -> dict:
    """Sandbox only: Self Assessment Test Support 1.0, Create a Test Business of type uk-property (HMRC's own
    example: examples/businesses/create_request_uk_property.json). HMRC purges test businesses after 7 days."""
    start, end = tax_year_bounds(body.tax_year)
    payload = {
        "typeOfBusiness": "uk-property",
        "firstAccountingPeriodStartDate": start.isoformat(),
        "firstAccountingPeriodEndDate": end.isoformat(),
        "accountingType": body.accounting_type,
        "commencementDate": date(start.year - 1, 4, 6).isoformat(),
        "quarterlyTypeChoice": {"quarterlyPeriodType": body.quarterly_period_type, "taxYearOfChoice": body.tax_year},
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
