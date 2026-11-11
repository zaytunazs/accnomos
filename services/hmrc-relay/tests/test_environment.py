"""HMRC_ENV: real users' VAT calls go to the sandbox (default) or to HMRC production with its own credentials; the
demo (X-HMRC-Environment: sandbox) always reaches the sandbox application; Income Tax never goes live."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx

from relay.settings import PRODUCTION_AUTH_BASE, PRODUCTION_BASE, Settings

from .conftest import web_facts

PROD = {"hmrc_env": "production", "hmrc_prod_client_id": "prod-cid", "hmrc_prod_client_secret": "prod-secret"}
SANDBOX_HDR = {"X-HMRC-Environment": "sandbox"}


def never(_: httpx.Request) -> httpx.Response:
    raise AssertionError("HMRC must not be called")


def body(**kw) -> dict:
    return {"client_facts": web_facts(), "method": "WEB_APP_VIA_SERVER", **kw}


def recorder(log: list[httpx.Request]):
    def hmrc(req: httpx.Request) -> httpx.Response:
        log.append(req)
        if req.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "APP", "expires_in": 14400})
        if req.url.path == "/create-test-user/organisations":
            return httpx.Response(201, json={"userId": "u", "password": "p", "vrn": "666119668"})
        return httpx.Response(200, json={"obligations": []})

    return hmrc


def test_settings_for_each_environment() -> None:
    s = Settings(_env_file=None, hmrc_client_id="sb", hmrc_client_secret="sbs", **PROD)
    live = s.for_environment("production")
    assert (live.hmrc_base, live.hmrc_auth_base, live.hmrc_client_id) == (
        PRODUCTION_BASE,
        PRODUCTION_AUTH_BASE,
        "prod-cid",
    )
    assert live.hmrc_client_secret.get_secret_value() == "prod-secret" and not live.sandbox and live.configured
    sb = s.for_environment("sandbox")
    assert sb.sandbox and sb.hmrc_client_id == "sb" and sb.hmrc_base.startswith("https://test-")
    assert Settings(_env_file=None).hmrc_env == "sandbox"  # the default: nothing reaches production by accident


async def test_status_default_is_sandbox(client_for):
    c = client_for(never)
    j = (await c.get("/hmrc/status")).json()
    assert j["environment"] == "sandbox" and j["vat"]["live_filing"] is False and j["vat"]["submit_available"] is True
    assert j["vat"]["note"] == "Filing to HMRC from Accnomos is planned."
    assert j["itsa"] == {
        "live_filing": False,
        "submit_available": True,
        "note": "Filing to HMRC from Accnomos is planned.",
    }
    assert j["demo_sandbox"] is True
    assert (await c.get("/health")).json()["environment"] == "sandbox"


async def test_status_production(client_for):
    j = (await client_for(never, **PROD).get("/hmrc/status")).json()
    assert j["environment"] == "production" and j["configured"] is True
    assert j["vat"] == {"live_filing": True, "submit_available": True, "note": None}
    assert j["itsa"]["live_filing"] is False and j["itsa"]["submit_available"] is False
    assert j["demo_sandbox"] is True


async def test_production_without_its_credentials_files_nothing(client_for):
    c = client_for(never, hmrc_env="production")
    j = (await c.get("/hmrc/status")).json()
    assert j["vat"]["live_filing"] is False and j["configured"] is False and j["vat"]["note"]
    r = await c.post(
        "/vat/123456789/obligations",
        json=body(**{"from": "2026-01-01", "to": "2026-12-31"}),
        headers={"X-HMRC-Access-Token": "t"},
    )
    assert r.status_code == 503


async def test_production_calls_go_to_hmrc_live_without_test_scenarios(client_for):
    log: list[httpx.Request] = []
    c = client_for(recorder(log), **PROD)
    r = await c.post(
        "/vat/123456789/obligations",
        json=body(**{"from": "2026-01-01", "to": "2026-12-31"}, gov_test_scenario="QUARTERLY_NONE_MET"),
        headers={"X-HMRC-Access-Token": "t"},
    )
    assert r.status_code == 200
    assert str(log[-1].url).startswith(f"{PRODUCTION_BASE}/organisations/vat/123456789/obligations")
    assert "gov-test-scenario" not in log[-1].headers

    url = (await c.get("/hmrc/authorize", params={"redirect_to": "https://app.accnomos.example/vat"})).json()["url"]
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}" == PRODUCTION_AUTH_BASE
    assert parse_qs(parts.query)["client_id"] == ["prod-cid"]


async def test_production_refuses_sandbox_tools_unless_the_demo_asks_for_the_sandbox(client_for):
    log: list[httpx.Request] = []
    c = client_for(recorder(log), **PROD)
    assert (await c.post("/hmrc/test-user")).status_code == 403
    assert log == []
    r = await c.post("/hmrc/test-user", headers=SANDBOX_HDR)
    assert r.status_code == 201 and r.json()["vrn"] == "666119668"
    assert all(str(q.url).startswith("https://test-api.service.hmrc.gov.uk/") for q in log)
    assert parse_qs(log[0].content.decode())["client_id"] == ["cid"]  # the sandbox application's credentials


async def test_demo_sign_in_round_trip_in_production_mode(client_for):
    """The demo starts sign-in on the sandbox application; HMRC's redirect has no header, so the callback tells the
    two applications apart by the state's signature."""
    c = client_for(never, **PROD)
    a = (
        await c.get(
            "/hmrc/authorize",
            params={"redirect_to": "https://app.accnomos.example/vat", "code_challenge": "x" * 43},
            headers=SANDBOX_HDR,
        )
    ).json()
    assert a["url"].startswith("https://test-www.tax.service.gov.uk/oauth/authorize")
    r = await c.get("/hmrc/callback", params={"state": a["state"], "code": "C"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("https://app.accnomos.example/vat#code=C")

    live = (
        await c.get(
            "/hmrc/authorize", params={"redirect_to": "https://app.accnomos.example/vat", "code_challenge": "x" * 43}
        )
    ).json()
    assert live["url"].startswith(PRODUCTION_AUTH_BASE)
    r = await c.get("/hmrc/callback", params={"state": live["state"], "code": "D"}, follow_redirects=False)
    assert r.status_code == 303 and "code=D" in r.headers["location"]
    assert (await c.get("/hmrc/callback", params={"state": "bad.sig", "code": "E"})).status_code == 400


async def test_environment_header(client_for):
    c = client_for(never)
    assert (
        await c.get(
            "/hmrc/authorize",
            params={"redirect_to": "http://localhost:3000/vat"},
            headers={"X-HMRC-Environment": "production"},
        )
    ).status_code == 409
    assert (
        await c.get(
            "/hmrc/authorize",
            params={"redirect_to": "http://localhost:3000/vat"},
            headers={"X-HMRC-Environment": "nonsense"},
        )
    ).status_code == 400
    ok = await c.get("/hmrc/authorize", params={"redirect_to": "http://localhost:3000/vat"}, headers=SANDBOX_HDR)
    assert ok.status_code == 200
    pre = await c.options(
        "/hmrc/test-user",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-hmrc-environment",
        },
    )
    assert "x-hmrc-environment" in pre.headers["access-control-allow-headers"].lower()
