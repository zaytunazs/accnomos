import asyncio
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from relay.oauth import OAuth

from .conftest import make_settings, web_facts

TOKENS = {
    "access_token": "AT1",
    "refresh_token": "RT2",
    "expires_in": 14400,
    "scope": "read:vat write:vat",
    "token_type": "bearer",
}
RETURN = {
    "periodKey": "A1#1",
    "vatDueSales": 1000.10,
    "vatDueAcquisitions": 0,
    "totalVatDue": 1000.10,
    "vatReclaimedCurrPeriod": 1200.00,
    "netVatDue": 199.90,
    "totalValueSalesExVAT": 5000,
    "totalValuePurchasesExVAT": 6000,
    "totalValueGoodsSuppliedExVAT": 0,
    "totalAcquisitionsExVAT": 0,
    "finalised": True,
}


def never(_: httpx.Request) -> httpx.Response:
    raise AssertionError("HMRC must not be called")


# --- CORS (the PWA calls the relay straight from the browser) ----------------------------------------------


@pytest.mark.parametrize("origin", ["https://app.accnomos.example", "http://localhost:3000"])
async def test_cors_preflight_allows_pwa_origins(client_for, origin):
    r = await client_for(never).options(
        "/vat/123456789/obligations",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-hmrc-access-token",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == origin
    assert "x-hmrc-access-token" in r.headers["access-control-allow-headers"].lower()


async def test_cors_rejects_other_origins(client_for):
    r = await client_for(never).get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


async def test_health(client_for):
    r = await client_for(never).get("/health")
    assert set(r.json()) == {"ok", "service", "version", "sandbox", "configured", "uptime_s"}
    assert r.json()["sandbox"] is True and r.json()["configured"] is True


# --- OAuth -----------------------------------------------------------------------------------------------


async def test_authorize_url_has_no_secret(client_for):
    r = await client_for(never).get(
        "/hmrc/authorize", params={"redirect_to": "https://app.accnomos.example/cb", "code_challenge": "x" * 43}
    )
    url = urlsplit(r.json()["url"])
    q = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://test-www.tax.service.gov.uk/oauth/authorize"
    assert q["scope"] == ["read:vat write:vat"] and q["code_challenge_method"] == ["S256"]
    assert q["state"] == [r.json()["state"]] and "client_secret" not in q


async def test_authorize_rejects_foreign_redirect(client_for):
    r = await client_for(never).get("/hmrc/authorize", params={"redirect_to": "https://evil.example/cb"})
    assert r.status_code == 400


async def test_callback_puts_tokens_in_fragment(client_for):
    seen = {}

    def hmrc(req: httpx.Request) -> httpx.Response:
        assert str(req.url) == "https://test-api.service.hmrc.gov.uk/oauth/token"
        seen.update(parse_qs(req.content.decode()))
        return httpx.Response(200, json=TOKENS)

    c = client_for(hmrc)
    state = (await c.get("/hmrc/authorize", params={"redirect_to": "https://app.accnomos.example/cb?x=1"})).json()[
        "state"
    ]
    r = await c.get("/hmrc/callback", params={"code": "C0DE", "state": state})
    assert r.status_code == 303
    loc = urlsplit(r.headers["location"])
    assert (loc.netloc, loc.path, loc.query) == ("app.accnomos.example", "/cb", "x=1")
    frag = parse_qs(loc.fragment)
    assert frag["access_token"] == ["AT1"] and frag["refresh_token"] == ["RT2"] and frag["expires_in"] == ["14400"]
    assert frag["state"] == [state]
    assert seen["client_secret"] == ["csecret"] and seen["grant_type"] == ["authorization_code"]


async def test_callback_pkce_returns_code_then_exchange(client_for):
    def hmrc(req: httpx.Request) -> httpx.Response:
        assert parse_qs(req.content.decode())["code_verifier"] == ["v" * 43]
        return httpx.Response(200, json=TOKENS)

    c = client_for(hmrc)
    state = (
        await c.get("/hmrc/authorize", params={"redirect_to": "http://localhost:5173/cb", "code_challenge": "c" * 43})
    ).json()["state"]
    r = await c.get("/hmrc/callback", params={"code": "C0DE", "state": state})
    frag = parse_qs(urlsplit(r.headers["location"]).fragment)
    assert frag == {"code": ["C0DE"], "state": [state]}
    r = await c.post("/hmrc/exchange", json={"code": "C0DE", "state": state, "code_verifier": "v" * 43})
    assert r.json()["access_token"] == "AT1"


async def test_callback_rejects_tampered_state(client_for):
    c = client_for(never)
    state = (await c.get("/hmrc/authorize", params={"redirect_to": "http://localhost/cb"})).json()["state"]
    r = await c.get("/hmrc/callback", params={"code": "C", "state": state.replace(".", ".x")})
    assert r.status_code == 400 and r.json()["code"] == "INVALID_STATE"


async def test_refresh_lock_serialises_concurrent_refreshes():
    calls, inflight, peak = 0, 0, 0

    async def hmrc(req: httpx.Request) -> httpx.Response:
        nonlocal calls, inflight, peak
        calls += 1
        inflight += 1
        peak = max(peak, inflight)
        await asyncio.sleep(0.05)
        inflight -= 1
        assert parse_qs(req.content.decode())["client_secret"] == ["csecret"]
        return httpx.Response(200, json={**TOKENS, "access_token": f"AT{calls}"})

    oauth = OAuth(make_settings(), httpx.AsyncClient(transport=httpx.MockTransport(hmrc)))
    same = await asyncio.gather(*(oauth.refresh("RT-A") for _ in range(5)))
    assert peak == 1 and calls == 1  # one HMRC call; the single-use token is not spent twice
    assert {t["access_token"] for t in same} == {"AT1"}
    await asyncio.gather(oauth.refresh("RT-B"), oauth.refresh("RT-C"))
    assert calls == 3 and oauth._refresh_locks == {}


async def test_refresh_error_is_mapped(client_for):
    c = client_for(lambda _: httpx.Response(400, json={"error": "invalid_grant", "error_description": "expired"}))
    r = await c.post("/hmrc/refresh", json={"refresh_token": "old"})
    assert r.status_code == 400 and r.json()["code"] == "invalid_grant"


# --- VAT -------------------------------------------------------------------------------------------------


def body(**kw) -> dict:
    return {"client_facts": web_facts(), "method": "WEB_APP_VIA_SERVER", **kw}


async def test_submit_return_sends_headers_and_echoes_them(client_for):
    sent: dict = {}

    def hmrc(req: httpx.Request) -> httpx.Response:
        sent["req"] = req
        return httpx.Response(
            201,
            json={"processingDate": "2026-10-27T09:30:02.000Z", "formBundleNumber": "256660290587"},
            headers={"Receipt-ID": "r-1", "X-CorrelationId": "corr-1"},
        )

    c = client_for(hmrc)
    r = await c.post(
        "/vat/123456789/returns",
        json=body(**{"return": RETURN}, gov_test_scenario="SOME_SCENARIO"),
        headers={"X-HMRC-Access-Token": "AT1", "X-Forwarded-For": "203.0.113.9"},
    )
    assert r.status_code == 201, r.text
    req = sent["req"]
    assert str(req.url) == "https://test-api.service.hmrc.gov.uk/organisations/vat/123456789/returns"
    assert req.headers["authorization"] == "Bearer AT1"
    assert req.headers["accept"] == "application/vnd.hmrc.1.0+json"
    assert req.headers["gov-test-scenario"] == "SOME_SCENARIO"
    assert req.headers["gov-client-public-ip"] == "203.0.113.9"
    assert req.headers["gov-vendor-forwarded"] == "by=203.0.113.6&for=203.0.113.9"
    assert json.loads(req.content) == RETURN
    out = r.json()
    assert out["hmrc"]["formBundleNumber"] == "256660290587" and out["receipt_id"] == "r-1"
    assert "authorization" not in {k.lower() for k in out["sent_headers"]}
    assert out["fraud_headers_missing"] == ["Gov-Client-Public-Port"]  # behind a proxy without X-Client-Port


@pytest.mark.parametrize(
    "change",
    [
        {"totalValueSalesExVAT": 5000.5},  # whole pounds only
        {"netVatDue": -199.90},  # absolute value
        {"vatReclaimedCurrPeriod": 1200.001},  # 2 dp
        {"periodKey": "A1#"},  # 4 chars
        {"totalVatDue": 999.00},  # box 3 != box 1 + box 2
        {"netVatDue": 10.00},  # box 5 != |box 3 - box 4|
    ],
)
async def test_submit_return_validated_before_hmrc(client_for, change):
    r = await client_for(never).post(
        "/vat/123456789/returns", json=body(**{"return": RETURN | change}), headers={"X-HMRC-Access-Token": "AT1"}
    )
    assert r.status_code == 422


async def test_vat_requires_user_token(client_for):
    r = await client_for(never).post(
        "/vat/123456789/obligations", json=body(**{"from": "2026-01-01", "to": "2026-12-31"})
    )
    assert r.status_code == 401


async def test_obligations_and_view_paths(client_for):
    urls = []

    def hmrc(req: httpx.Request) -> httpx.Response:
        urls.append(str(req.url))
        return httpx.Response(200, json={"obligations": []})

    c = client_for(hmrc)
    h = {"X-HMRC-Access-Token": "AT1"}
    await c.post(
        "/vat/123456789/obligations", json=body(**{"from": "2026-01-01", "to": "2026-12-31", "status": "O"}), headers=h
    )
    await c.post("/vat/123456789/returns/A1%231/view", json=body(), headers=h)
    assert urls == [
        "https://test-api.service.hmrc.gov.uk/organisations/vat/123456789/obligations?from=2026-01-01&to=2026-12-31&status=O",
        "https://test-api.service.hmrc.gov.uk/organisations/vat/123456789/returns/A1%231",
    ]


async def test_hmrc_error_passthrough(client_for):
    c = client_for(lambda _: httpx.Response(403, json={"code": "CLIENT_OR_AGENT_NOT_AUTHORISED", "message": "no"}))
    r = await c.post(
        "/vat/123456789/payments",
        json=body(**{"from": "2026-01-01", "to": "2026-03-31"}),
        headers={"X-HMRC-Access-Token": "AT1"},
    )
    assert r.status_code == 403 and r.json()["code"] == "CLIENT_OR_AGENT_NOT_AUTHORISED"


# --- application-restricted --------------------------------------------------------------------------------


def app_restricted(api: dict[str, tuple[int, dict]], log: list):
    def hmrc(req: httpx.Request) -> httpx.Response:
        log.append(req)
        if req.url.path == "/oauth/token":
            assert parse_qs(req.content.decode())["grant_type"] == ["client_credentials"]
            return httpx.Response(200, json={"access_token": "APP", "expires_in": 14400})
        assert req.headers["authorization"] == "Bearer APP"
        status, payload = api[req.url.path]
        return httpx.Response(status, json=payload)

    return hmrc


async def test_test_user_and_cached_app_token(client_for):
    log: list[httpx.Request] = []
    user = {"userId": "945350439195", "password": "bLohysg8utsa", "vrn": "666119668"}
    c = client_for(app_restricted({"/create-test-user/organisations": (201, user)}, log))
    assert (await c.post("/hmrc/test-user")).json()["vrn"] == "666119668"
    assert (await c.post("/hmrc/test-user")).status_code == 201
    assert [r.url.path for r in log].count("/oauth/token") == 1
    assert json.loads(log[1].content) == {"serviceNames": ["mtd-vat"]}


async def test_test_user_refused_outside_sandbox(client_for):
    c = client_for(never, hmrc_base="https://api.service.hmrc.gov.uk")
    r = await c.post("/hmrc/test-user")
    assert r.status_code == 403


async def test_check_vat_number_uses_v2(client_for):
    log: list[httpx.Request] = []
    path = "/organisations/vat/check-vat-number/lookup/123456789/987654321"
    c = client_for(app_restricted({path: (200, {"target": {"vatNumber": "123456789"}})}, log))
    r = await c.get("/vat/check/123456789/987654321")
    assert r.json()["target"]["vatNumber"] == "123456789"
    assert log[-1].headers["accept"] == "application/vnd.hmrc.2.0+json"


async def test_validate_headers(client_for):
    log: list[httpx.Request] = []
    path = "/test/fraud-prevention-headers/validate"
    c = client_for(app_restricted({path: (200, {"code": "VALID_HEADERS"})}, log))
    r = await c.post("/hmrc/validate-headers", json=body())
    assert r.json()["hmrc"]["code"] == "VALID_HEADERS"
    assert log[-1].headers["gov-client-connection-method"] == "WEB_APP_VIA_SERVER"
    assert r.json()["fraud_headers_missing"] == []
