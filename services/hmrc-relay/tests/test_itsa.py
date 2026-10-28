"""MTD Income Tax (self-employment) through the relay, against fakes that answer with HMRC's own examples.

Every fake checks the request against HMRC's live documentation, checked 28 Oct 2026 (fixtures/itsa/README.md lists
the source of each payload; docs/HMRC.md the API pages): method, path, `Accept: application/vnd.hmrc.{v}+json`,
query names, body, and the fraud-prevention headers, which go exactly as for VAT.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from relay.itsa import FINAL_DECLARATION, TEST_USER_SERVICES

from .conftest import web_facts

FIX = Path(__file__).parent / "fixtures" / "itsa"
NINO = "TC663795B"
BIZ = "XAIS12345678910"
CALC = "f2fb30e5-4ab6-4a29-b3c1-c7264259ff1c"
BASE = "https://test-api.service.hmrc.gov.uk"
H = {"X-HMRC-Access-Token": "AT1", "X-Forwarded-For": "203.0.113.9", "X-Client-Port": "50123"}


def fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def env(**kw) -> dict:
    return {"client_facts": web_facts(), "method": "WEB_APP_VIA_SERVER", **kw}


class Fake:
    """One expected HMRC call: checks it, records it, answers like HMRC."""

    def __init__(
        self, method: str, path: str, version: str, status: int = 200, body: dict | None = None, base: str = BASE
    ):
        self.method, self.path, self.version, self.status, self.body = method, path, version, status, body
        self.base = base
        self.seen: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        assert req.method == self.method, req.method
        assert req.url.path == self.path, req.url.path
        assert f"{req.url.scheme}://{req.url.host}" == self.base
        assert req.headers["accept"] == f"application/vnd.hmrc.{self.version}+json"
        assert req.headers["authorization"] == "Bearer AT1"
        # the same fraud-prevention headers as VAT (spec v3.3, WEB_APP_VIA_SERVER)
        assert req.headers["gov-client-connection-method"] == "WEB_APP_VIA_SERVER"
        assert req.headers["gov-client-public-ip"] == "203.0.113.9"
        assert req.headers["gov-client-browser-js-user-agent"].startswith("Mozilla/5.0")
        assert req.headers["gov-vendor-forwarded"] == "by=203.0.113.6&for=203.0.113.9"
        self.seen.append(req)
        headers = {"X-CorrelationId": "corr-itsa"}
        if self.body is None:
            return httpx.Response(self.status, headers=headers)
        return httpx.Response(self.status, json=self.body, headers=headers)


# --- Business Details 2.0 ----------------------------------------------------------------------------------------


async def test_list_businesses(client_for):
    fake = Fake(
        "GET", f"/individuals/business/details/{NINO}/list", "2.0", body=fixture("business_details_2.0_list.json")
    )
    r = await client_for(fake).post(f"/itsa/{NINO}/businesses", json=env(gov_test_scenario="STATEFUL"), headers=H)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["hmrc"]["listOfBusinesses"][0] == {
        "typeOfBusiness": "self-employment",
        "businessId": BIZ,
        "tradingType": "Plastering",
        "tradingName": "RCDTS",
    }
    assert out["correlation_id"] == "corr-itsa" and out["fraud_headers_missing"] == []
    assert fake.seen[0].headers["gov-test-scenario"] == "STATEFUL"
    assert "authorization" not in {k.lower() for k in out["sent_headers"]}


@pytest.mark.parametrize("nino", ["tc663795b", "TC663795", "TC663795E", "AB12345C"])
async def test_bad_nino_never_reaches_hmrc(client_for, nino):
    def never(_: httpx.Request) -> httpx.Response:
        raise AssertionError("HMRC must not be called")

    r = await client_for(never).post(f"/itsa/{nino}/businesses", json=env(), headers=H)
    assert r.status_code == 422


# --- Obligations 3.0 ---------------------------------------------------------------------------------------------


async def test_obligations_query_names(client_for):
    fake = Fake(
        "GET",
        f"/obligations/details/{NINO}/income-and-expenditure",
        "3.0",
        body=fixture("obligations_3.0_income_and_expenditure_ty26-27.json"),
    )
    r = await client_for(fake).post(
        f"/itsa/{NINO}/obligations",
        json=env(**{"from": "2026-04-06", "to": "2027-04-05", "status": "open", "business_id": BIZ}),
        headers=H,
    )
    assert r.status_code == 200, r.text
    q = parse_qs(urlsplit(str(fake.seen[0].url)).query)
    assert q == {
        "typeOfBusiness": ["self-employment"],
        "businessId": [BIZ],
        "fromDate": ["2026-04-06"],
        "toDate": ["2027-04-05"],
        "status": ["open"],
    }
    details = r.json()["hmrc"]["obligations"][0]["obligationDetails"]
    assert {d["periodStartDate"] for d in details} == {"2026-04-06"}  # cumulative: every period starts 6 April


@pytest.mark.parametrize(
    "extra",
    [
        {"from": "2026-04-06"},  # HMRC: from and to are mandatory together
        {"from": "2026-04-06", "to": "2027-04-08"},  # more than 366 days
        {"from": "2027-04-05", "to": "2026-04-06"},
        {"status": "O"},  # VAT's letters are not Income Tax's words
        {"business_id": "XAIS123"},
    ],
)
async def test_obligations_refused_before_hmrc(client_for, extra):
    r = await client_for(lambda _: httpx.Response(500)).post(f"/itsa/{NINO}/obligations", json=env(**extra), headers=H)
    assert r.status_code == 422


async def test_final_declaration_obligations(client_for):
    fake = Fake(
        "GET",
        f"/obligations/details/{NINO}/crystallisation",
        "3.0",
        body=fixture("obligations_3.0_crystallisation.json"),
    )
    r = await client_for(fake).post(
        f"/itsa/{NINO}/final-declaration-obligations", json=env(tax_year="2026-27"), headers=H
    )
    assert r.status_code == 200 and r.json()["hmrc"]["obligations"][0]["dueDate"] == "2020-01-31"
    assert parse_qs(urlsplit(str(fake.seen[0].url)).query) == {"taxYear": ["2026-27"]}


# --- Self-Employment Business 5.0, cumulative period summary --------------------------------------------------------


def hmrc_example_for(tax_year_start: int) -> dict:
    """HMRC's non-consolidated example request, moved into the given tax year."""
    body = fixture("se_business_5.0_cumulative_request.json")
    body["periodDates"] = {"periodStartDate": f"{tax_year_start}-04-06", "periodEndDate": f"{tax_year_start}-07-05"}
    return body


async def test_submit_cumulative_sends_hmrc_example_unchanged(client_for):
    path = f"/individuals/business/self-employment/{NINO}/{BIZ}/cumulative/2025-26"
    fake = Fake("PUT", path, "5.0", status=204)
    example = fixture("se_business_5.0_cumulative_request.json")  # dated 2025-26 by HMRC
    r = await client_for(fake).post(
        f"/itsa/{NINO}/self-employment/{BIZ}/cumulative/2025-26", json=env(summary=example, confirmed=True), headers=H
    )
    assert r.status_code == 200, r.text
    assert json.loads(fake.seen[0].content) == example  # byte-for-byte the documented body, numbers included
    assert fake.seen[0].headers["content-type"] == "application/json"
    assert r.json()["hmrc"] is None and r.json()["correlation_id"] == "corr-itsa"  # HMRC: 204 No Content


async def test_consolidated_example_is_accepted(client_for):
    path = f"/individuals/business/self-employment/{NINO}/{BIZ}/cumulative/2025-26"
    fake = Fake("PUT", path, "5.0", status=204)
    example = fixture("se_business_5.0_cumulative_request_consolidated.json")
    r = await client_for(fake).post(
        f"/itsa/{NINO}/self-employment/{BIZ}/cumulative/2025-26", json=env(summary=example, confirmed=True), headers=H
    )
    assert r.status_code == 200, r.text
    assert json.loads(fake.seen[0].content) == example


def _mutate(body: dict, change: str) -> dict:
    b = json.loads(json.dumps(body))
    match change:
        case "unconfirmed":
            pass
        case "three_dp":
            b["periodExpenses"]["adminCosts"] = 1.234
        case "negative_turnover":
            b["periodIncome"]["turnover"] = -1
        case "unknown_field":
            b["periodExpenses"]["coffee"] = 1
        case "both_expenses":
            b["periodExpenses"]["consolidatedExpenses"] = 10
        case "end_before_start":
            b["periodDates"]["periodEndDate"] = "2026-04-01"
        case "other_tax_year":
            b["periodDates"]["periodEndDate"] = "2027-04-06"
        case "too_big":
            b["periodExpenses"]["otherExpenses"] = 100000000000
    return b


@pytest.mark.parametrize(
    "change",
    [
        "unconfirmed",
        "three_dp",
        "negative_turnover",
        "unknown_field",
        "both_expenses",
        "end_before_start",
        "other_tax_year",
        "too_big",
    ],
)
async def test_cumulative_refused_before_hmrc(client_for, change):
    def never(_: httpx.Request) -> httpx.Response:
        raise AssertionError("HMRC must not be called")

    body = env(summary=_mutate(hmrc_example_for(2026), change), confirmed=change != "unconfirmed")
    r = await client_for(never).post(f"/itsa/{NINO}/self-employment/{BIZ}/cumulative/2026-27", json=body, headers=H)
    assert r.status_code in (400, 422), r.text


@pytest.mark.parametrize("tax_year", ["2024-25", "2026-28"])
async def test_cumulative_tax_year_rules(client_for, tax_year):
    start = int(tax_year[:4])
    r = await client_for(lambda _: httpx.Response(500)).post(
        f"/itsa/{NINO}/self-employment/{BIZ}/cumulative/{tax_year}",
        json=env(summary=hmrc_example_for(start), confirmed=True),
        headers=H,
    )
    assert r.status_code == 400


async def test_hmrc_rule_error_comes_back_with_its_status(client_for):
    err = {"code": "RULE_EARLY_DATA_SUBMISSION_NOT_ACCEPTED", "message": "Cannot submit more than 10 days early"}
    r = await client_for(lambda _: httpx.Response(400, json=err)).post(
        f"/itsa/{NINO}/self-employment/{BIZ}/cumulative/2026-27",
        json=env(summary=hmrc_example_for(2026), confirmed=True),
        headers=H,
    )
    assert r.status_code == 400 and r.json()["code"] == "RULE_EARLY_DATA_SUBMISSION_NOT_ACCEPTED"


async def test_view_cumulative(client_for):
    fake = Fake("GET", f"/individuals/business/self-employment/{NINO}/{BIZ}/cumulative/2026-27", "5.0", body={"x": 1})
    r = await client_for(fake).post(
        f"/itsa/{NINO}/self-employment/{BIZ}/cumulative/2026-27/view", json=env(), headers=H
    )
    assert r.status_code == 200 and r.json()["hmrc"] == {"x": 1}


# --- Individual Calculations 8.0 ---------------------------------------------------------------------------------


async def test_trigger_list_retrieve(client_for):
    calc = f"/individuals/calculations/{NINO}/self-assessment/2026-27"
    fakes = {
        ("POST", f"{calc}/trigger/in-year"): Fake(
            "POST", f"{calc}/trigger/in-year", "8.0", 202, fixture("calculations_8.0_trigger.json")
        ),
        ("GET", calc): Fake("GET", calc, "8.0", body=fixture("calculations_8.0_list_ty25-26_onwards.json")),
        ("GET", f"{calc}/{CALC}"): Fake(
            "GET", f"{calc}/{CALC}", "8.0", body=fixture("calculations_8.0_retrieve_ty26-27.json")
        ),
    }
    c = client_for(lambda req: fakes[(req.method, req.url.path)](req))
    t = await c.post(f"/itsa/{NINO}/calculations/2026-27/trigger", json=env(calculation_type="in-year"), headers=H)
    assert t.status_code == 202 and t.json()["hmrc"] == {"calculationId": CALC}
    lst = await c.post(f"/itsa/{NINO}/calculations/2026-27/list", json=env(calculation_type="in-year"), headers=H)
    assert lst.json()["hmrc"]["calculations"][1]["calculationType"] == "in-year"
    assert parse_qs(urlsplit(str(fakes[("GET", calc)].seen[0].url)).query) == {"calculationType": ["in-year"]}
    got = await c.post(f"/itsa/{NINO}/calculations/2026-27/{CALC}/view", json=env(), headers=H)
    tc = got.json()["hmrc"]["calculation"]["taxCalculation"]
    assert "totalIncomeTaxAndNicsDue" in tc and "nics" in tc  # the runtime's calculation report reads these


async def test_trigger_refuses_unknown_type(client_for):
    r = await client_for(lambda _: httpx.Response(500)).post(
        f"/itsa/{NINO}/calculations/2026-27/trigger", json=env(calculation_type="final-declaration"), headers=H
    )
    assert r.status_code == 422


async def test_final_declaration_needs_hmrc_text_and_confirmation(client_for):
    path = f"/individuals/calculations/{NINO}/self-assessment/2026-27/{CALC}/final-declaration"
    fake = Fake("POST", path, "8.0", status=204)
    c = client_for(fake)
    url = f"/itsa/{NINO}/calculations/2026-27/{CALC}/final-declaration"
    assert (await c.post(url, json=env(declaration="I agree", confirmed=True), headers=H)).status_code == 422
    assert (await c.post(url, json=env(declaration=FINAL_DECLARATION, confirmed=False), headers=H)).status_code == 422
    assert (await c.post(url, json=env(declaration=FINAL_DECLARATION), headers=H)).status_code == 422
    assert not fake.seen
    r = await c.post(url, json=env(declaration=FINAL_DECLARATION, confirmed=True), headers=H)
    assert r.status_code == 200 and r.json()["hmrc"] is None and len(fake.seen) == 1
    assert fake.seen[0].content == b""  # HMRC's endpoint takes no body: the calculation ID says what is agreed


async def test_bad_calculation_id(client_for):
    r = await client_for(lambda _: httpx.Response(500)).post(
        f"/itsa/{NINO}/calculations/2026-27/not-a-calc/view", json=env(), headers=H
    )
    assert r.status_code == 422


# --- sandbox only ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (f"/itsa/{NINO}/businesses", env()),
        (f"/itsa/{NINO}/obligations", env()),
        (f"/itsa/{NINO}/self-employment/{BIZ}/cumulative/2026-27", env(summary=hmrc_example_for(2026), confirmed=True)),
        (f"/itsa/{NINO}/calculations/2026-27/trigger", env()),
        (
            f"/itsa/{NINO}/calculations/2026-27/{CALC}/final-declaration",
            env(declaration=FINAL_DECLARATION, confirmed=True),
        ),
        (f"/itsa/{NINO}/test-business", env(tax_year="2026-27")),
        ("/hmrc/test-user/individual", None),
    ],
)
async def test_production_refused_without_the_switch(client_for, path, body):
    def never(_: httpx.Request) -> httpx.Response:
        raise AssertionError("HMRC must not be called")

    c = client_for(never, hmrc_base="https://api.service.hmrc.gov.uk")
    r = await c.post(path, json=body, headers=H) if body is not None else await c.post(path)
    assert r.status_code == 403


async def test_production_switch_opens_itsa_routes_only(client_for):
    fake = Fake(
        "GET",
        f"/individuals/business/details/{NINO}/list",
        "2.0",
        body={"listOfBusinesses": []},
        base="https://api.service.hmrc.gov.uk",
    )
    c = client_for(fake, hmrc_base="https://api.service.hmrc.gov.uk", relay_itsa_production=True)
    assert (await c.post(f"/itsa/{NINO}/businesses", json=env(), headers=H)).status_code == 200
    assert (await c.post("/hmrc/test-user/individual")).status_code == 403  # test tools stay sandbox only


# --- sandbox setup -----------------------------------------------------------------------------------------------


async def test_create_test_individual(client_for):
    seen = {}

    def hmrc(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "APP", "expires_in": 14400})
        seen["req"] = req
        return httpx.Response(201, json={"userId": "u", "password": "p", "nino": NINO, "mtdItId": "XNIT00000068707"})

    r = await client_for(hmrc).post("/hmrc/test-user/individual")
    assert r.status_code == 201 and r.json()["nino"] == NINO
    assert seen["req"].url.path == "/create-test-user/individuals"
    assert json.loads(seen["req"].content) == {"serviceNames": TEST_USER_SERVICES}
    assert seen["req"].headers["authorization"] == "Bearer APP"


async def test_create_test_business(client_for):
    fake = Fake("POST", f"/individuals/self-assessment-test-support/business/{NINO}", "1.0", 201, {"businessId": BIZ})
    r = await client_for(fake).post(f"/itsa/{NINO}/test-business", json=env(tax_year="2026-27"), headers=H)
    assert r.status_code == 201 and r.json()["hmrc"] == {"businessId": BIZ}
    sent = json.loads(fake.seen[0].content)
    # the fields Test Support 1.0 makes mandatory for a self-employment, and a full tax-year accounting period
    assert sent["typeOfBusiness"] == "self-employment" and sent["businessAddressCountryCode"] == "GB"
    assert {"tradingName", "tradingType", "businessAddressLineOne", "businessAddressPostcode"} <= set(sent)
    assert (sent["firstAccountingPeriodStartDate"], sent["firstAccountingPeriodEndDate"]) == (
        "2026-04-06",
        "2027-04-05",
    )


# --- OAuth scopes ------------------------------------------------------------------------------------------------


async def test_authorize_asks_for_income_tax_scopes(client_for):
    c = client_for(lambda _: httpx.Response(500))
    r = await c.get(
        "/hmrc/authorize",
        params={
            "redirect_to": "http://localhost:3000/self-employment",
            "code_challenge": "c" * 43,
            "scope": "read:self-assessment write:self-assessment",
        },
    )
    assert parse_qs(urlsplit(r.json()["url"]).query)["scope"] == ["read:self-assessment write:self-assessment"]
    default = await c.get("/hmrc/authorize", params={"redirect_to": "http://localhost:3000/vat"})
    assert parse_qs(urlsplit(default.json()["url"]).query)["scope"] == ["read:vat write:vat"]
    bad = await c.get("/hmrc/authorize", params={"redirect_to": "http://localhost:3000/x", "scope": "read:everything"})
    assert bad.status_code == 400


def test_declaration_text_is_the_same_everywhere():
    """HMRC's final declaration lives in three places (relay, runtime, web); they must not drift apart."""
    root = Path(__file__).resolve().parents[3]

    def flat(s: str) -> str:
        return " ".join(s.replace('" +', " ").replace('"', " ").split())

    for f in ("services/runtime/app/itsa.py", "apps/web/src/lib/itsa.ts"):
        assert flat(FINAL_DECLARATION) in flat((root / f).read_text()), f
