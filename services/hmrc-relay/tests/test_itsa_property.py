"""MTD Income Tax, UK property (relay/itsa_property.py): paths, versions, validation and the sandbox-only guard,
against HMRC's own example bodies (tests/fixtures/itsa_property/README.md). HMRC is an httpx.MockTransport."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from .conftest import web_facts

FIX = Path(__file__).parent / "fixtures" / "itsa_property"
NINO, BID = "TC663795B", "XPIS12345678901"
H = {"X-HMRC-Access-Token": "AT1"}
BASE = "https://test-api.service.hmrc.gov.uk"


def fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def body(**kw) -> dict:
    return {"client_facts": web_facts(), "method": "WEB_APP_VIA_SERVER", **kw}


class Recorder:
    def __init__(self, status: int = 204, payload: dict | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.status, self.payload = status, payload

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if self.payload is None:
            return httpx.Response(self.status, headers={"X-CorrelationId": "corr-1"})
        return httpx.Response(self.status, json=self.payload, headers={"X-CorrelationId": "corr-1"})


def never(_: httpx.Request) -> httpx.Response:
    raise AssertionError("HMRC must not be called")


def cumulative_2026(example: str = "uk_cumulative_6.0_request.json") -> dict:
    s = fixture(example)
    return {**s, "fromDate": "2026-04-06", "toDate": "2026-07-05"}


@pytest.mark.parametrize("example", ["uk_cumulative_6.0_request.json", "uk_cumulative_6.0_consolidated_request.json"])
async def test_cumulative_puts_hmrcs_example_unchanged(client_for, example):
    rec = Recorder()
    summary = cumulative_2026(example)
    r = await client_for(rec).post(
        f"/itsa/{NINO}/property/{BID}/cumulative/2026-27", json=body(summary=summary, confirmed=True), headers=H
    )
    assert r.status_code == 200, r.text
    assert r.json()["correlation_id"] == "corr-1" and r.json()["hmrc"] is None  # HMRC answers 204
    (req,) = rec.requests
    assert req.method == "PUT"
    assert str(req.url) == f"{BASE}/individuals/business/property/uk/{NINO}/{BID}/cumulative/2026-27"
    assert req.headers["Accept"] == "application/vnd.hmrc.6.0+json"
    assert req.headers["Authorization"] == "Bearer AT1" and "gov-client-device-id" in req.headers
    assert json.loads(req.content) == summary


async def test_cumulative_needs_confirmation_and_valid_figures(client_for):
    c = client_for(never)
    path = f"/itsa/{NINO}/property/{BID}/cumulative/2026-27"
    s = cumulative_2026()
    assert (await c.post(path, json=body(summary=s), headers=H)).status_code == 422  # no confirmed
    both = {**s, "ukProperty": {"expenses": {"consolidatedExpenses": 1, "repairsAndMaintenance": 2}}}
    r = await c.post(path, json=body(summary=both, confirmed=True), headers=H)
    assert r.status_code == 422 and "RULE_BOTH_EXPENSES_SUPPLIED" in r.text
    negative = {**s, "ukProperty": {"income": {"periodAmount": -1}}}
    assert (await c.post(path, json=body(summary=negative, confirmed=True), headers=H)).status_code == 422
    three_dp = {**s, "ukProperty": {"income": {"periodAmount": 1.005}}}
    assert (await c.post(path, json=body(summary=three_dp, confirmed=True), headers=H)).status_code == 422
    empty = {**s, "ukProperty": {}}
    assert (await c.post(path, json=body(summary=empty, confirmed=True), headers=H)).status_code == 422
    unknown = {**s, "ukProperty": {"income": {"furnishedHolidayLet": 1}}}
    assert (await c.post(path, json=body(summary=unknown, confirmed=True), headers=H)).status_code == 422
    outside = {**s, "toDate": "2027-04-06"}
    assert (await c.post(path, json=body(summary=outside, confirmed=True), headers=H)).status_code == 422
    early = f"/itsa/{NINO}/property/{BID}/cumulative/2024-25"
    r = await c.post(early, json=body(summary=fixture("uk_cumulative_6.0_request.json"), confirmed=True), headers=H)
    assert r.status_code == 400 and "2025-26" in r.text
    assert (await c.post(path, json=body(summary=s, confirmed=True))).status_code == 401  # no HMRC token
    bad_id = f"/itsa/{NINO}/property/NOTABUSINESS/cumulative/2026-27"
    assert (await c.post(bad_id, json=body(summary=s, confirmed=True), headers=H)).status_code == 422


async def test_view_annual_obligations_businesses_paths(client_for):
    rec = Recorder(200, {"ok": True})
    c = client_for(rec)
    await c.post(f"/itsa/{NINO}/property/{BID}/cumulative/2026-27/view", json=body(), headers=H)
    annual = {"ukProperty": {"allowances": {"costOfReplacingDomesticItems": 567.34}}}
    await c.post(f"/itsa/{NINO}/property/{BID}/annual/2026-27", json=body(submission=annual, confirmed=True), headers=H)
    await c.post(
        f"/itsa/{NINO}/property/obligations",
        json=body(**{"from": "2026-04-06", "to": "2027-04-05", "status": "open", "business_id": BID}),
        headers=H,
    )
    await c.post(f"/itsa/{NINO}/property/businesses", json=body(), headers=H)
    got = [(q.method, str(q.url), q.headers["Accept"]) for q in rec.requests]
    assert got == [
        (
            "GET",
            f"{BASE}/individuals/business/property/uk/{NINO}/{BID}/cumulative/2026-27",
            "application/vnd.hmrc.6.0+json",
        ),
        (
            "PUT",
            f"{BASE}/individuals/business/property/uk/{NINO}/{BID}/annual/2026-27",
            "application/vnd.hmrc.6.0+json",
        ),
        (
            "GET",
            f"{BASE}/obligations/details/{NINO}/income-and-expenditure?typeOfBusiness=uk-property&businessId={BID}"
            "&fromDate=2026-04-06&toDate=2027-04-05&status=open",
            "application/vnd.hmrc.3.0+json",
        ),
        ("GET", f"{BASE}/individuals/business/details/{NINO}/list", "application/vnd.hmrc.2.0+json"),
    ]
    assert json.loads(rec.requests[1].content) == annual


async def test_annual_takes_only_what_accnomos_knows(client_for):
    c = client_for(never)
    path = f"/itsa/{NINO}/property/{BID}/annual/2026-27"
    capital = {"ukProperty": {"allowances": {"annualInvestmentAllowance": 1}}}
    assert (await c.post(path, json=body(submission=capital, confirmed=True), headers=H)).status_code == 422
    ok = {"ukProperty": {"allowances": {"costOfReplacingDomesticItems": 1}}}
    assert (await c.post(path, json=body(submission=ok), headers=H)).status_code == 422  # not confirmed


async def test_obligations_dates_go_together(client_for):
    c = client_for(never)
    r = await c.post(f"/itsa/{NINO}/property/obligations", json=body(**{"from": "2026-04-06"}), headers=H)
    assert r.status_code == 422


async def test_test_business_matches_hmrcs_uk_property_example(client_for):
    rec = Recorder(201, {"businessId": BID})
    r = await client_for(rec).post(f"/itsa/{NINO}/property/test-business", json=body(tax_year="2026-27"), headers=H)
    assert r.status_code == 201 and r.json()["hmrc"] == {"businessId": BID}
    sent = json.loads(rec.requests[0].content)
    example = fixture("test_support_1.0_create_business_uk_property.json")
    assert sent["typeOfBusiness"] == example["typeOfBusiness"] == "uk-property"
    assert set(sent) <= set(example)  # only fields HMRC's own example uses
    assert sent["quarterlyTypeChoice"] == {"quarterlyPeriodType": "standard", "taxYearOfChoice": "2026-27"}
    assert str(rec.requests[0].url) == f"{BASE}/individuals/self-assessment-test-support/business/{NINO}"


async def test_production_is_refused_unless_explicitly_allowed(client_for):
    prod = {"hmrc_base": "https://api.service.hmrc.gov.uk"}
    c = client_for(never, **prod)
    s = cumulative_2026()
    r = await c.post(f"/itsa/{NINO}/property/{BID}/cumulative/2026-27", json=body(summary=s, confirmed=True), headers=H)
    assert r.status_code == 403 and "sandbox only" in r.text
    assert (await c.post(f"/itsa/{NINO}/property/businesses", json=body(), headers=H)).status_code == 403
    r = await c.post(f"/itsa/{NINO}/property/test-business", json=body(tax_year="2026-27"), headers=H)
    assert r.status_code == 403
    rec = Recorder()
    allowed = client_for(rec, relay_itsa_production=True, **prod)
    r = await allowed.post(
        f"/itsa/{NINO}/property/{BID}/cumulative/2026-27", json=body(summary=s, confirmed=True), headers=H
    )
    assert r.status_code == 200 and str(rec.requests[0].url).startswith("https://api.service.hmrc.gov.uk/")
    r = await allowed.post(f"/itsa/{NINO}/property/test-business", json=body(tax_year="2026-27"), headers=H)
    assert r.status_code == 403  # test support never runs against production


async def test_authorize_accepts_the_self_assessment_scopes(client_for):
    c = client_for(never)
    params = {"redirect_to": "https://app.accnomos.example/cb", "scope": "read:self-assessment write:self-assessment"}
    r = await c.get("/hmrc/authorize", params=params)
    assert r.status_code == 200 and "scope=read%3Aself-assessment+write%3Aself-assessment" in r.json()["url"]
    r = await c.get("/hmrc/authorize", params={**params, "scope": "read:vat admin"})
    assert r.status_code == 400
