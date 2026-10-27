"""Relay request hardening (relay/security.py): tokens, limits, safe errors, strict bodies, VRN/period keys."""

import logging

import httpx
import pytest

from .conftest import web_facts

TOKEN = "hmrc-access-token-very-secret"


def never(_: httpx.Request) -> httpx.Response:
    raise AssertionError("HMRC must not be called")


def envelope(**kw) -> dict:
    return {"client_facts": web_facts(), "method": "WEB_APP_VIA_SERVER", **kw}


async def test_oversized_access_token_rejected(client_for):
    r = await client_for(never).post("/vat/123456789/liabilities", headers={"X-HMRC-Access-Token": "a" * 8193},
                                     json=envelope(**{"from": "2026-01-01", "to": "2026-03-31"}))
    assert r.status_code == 431


async def test_access_token_refused_over_plain_http(client_for):
    r = await client_for(never).post("/vat/123456789/liabilities",
                                     headers={"X-HMRC-Access-Token": TOKEN, "X-Forwarded-Proto": "http"},
                                     json=envelope(**{"from": "2026-01-01", "to": "2026-03-31"}))
    assert r.status_code == 400 and "HTTPS" in r.json()["detail"]


async def test_rate_limit(client_for):
    c = client_for(never, rate_limit_per_min=2)
    assert [(await c.get("/vat/check/123456789/x")).status_code for _ in range(2)] == [422, 422]  # bad VRN, not 429
    r = await c.get("/vat/check/123456789/x")
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert (await c.get("/health")).status_code == 200  # never limited


async def test_body_cap(client_for):
    r = await client_for(never).post("/hmrc/refresh", content=b'{"refresh_token": "' + b"x" * 300_000 + b'"}',
                                     headers={"Content-Type": "application/json"})
    assert r.status_code == 413


async def test_unexpected_error_is_safe_and_scrubbed(client_for, caplog):
    def explode(req: httpx.Request) -> httpx.Response:
        raise RuntimeError(f"boom with {req.headers['authorization']}")  # not an httpx error: escapes the client

    with caplog.at_level(logging.ERROR):
        r = await client_for(explode).post("/vat/123456789/liabilities", headers={"X-HMRC-Access-Token": TOKEN},
                                           json=envelope(**{"from": "2026-01-01", "to": "2026-03-31"}))
    assert r.status_code == 500 and set(r.json()) == {"detail", "correlation_id"}
    assert TOKEN not in r.text and "Traceback" not in r.text
    logged = caplog.text + "".join(rec.exc_text or "" for rec in caplog.records)
    assert r.json()["correlation_id"] in logged and TOKEN not in logged


def test_access_log_hides_the_oauth_code_and_still_formats():
    """uvicorn's AccessFormatter unpacks record.args, so scrubbing must keep it a tuple; the callback's code goes."""
    from uvicorn.logging import AccessFormatter

    from relay.security import install_log_scrubbing

    install_log_scrubbing()
    record = logging.getLogger("uvicorn.access").makeRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", "/hmrc/callback?code=auth-code-secret&state=abc.def", "1.1", 307), None)
    line = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False).format(record)
    assert "auth-code-secret" not in line and "code=[redacted]&state=abc.def" in line and line.endswith('HTTP/1.1" 307 Temporary Redirect')


async def test_hmrc_error_message_is_scrubbed(client_for):
    def hmrc(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": "INVALID_CREDENTIALS", "message": f"Bearer {TOKEN} is not valid"})

    r = await client_for(hmrc).post("/vat/123456789/liabilities", headers={"X-HMRC-Access-Token": TOKEN},
                                    json=envelope(**{"from": "2026-01-01", "to": "2026-03-31"}))
    assert r.status_code == 401 and TOKEN not in r.text


async def test_cors_preflight_cached(client_for):
    r = await client_for(never).options("/hmrc/refresh", headers={
        "Origin": "https://app.accnomos.example", "Access-Control-Request-Method": "POST"})
    assert r.headers["access-control-max-age"] == "600"


# --- strict input ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("path", "body"), [
    ("/hmrc/refresh", {"refresh_token": "RT", "client_secret": "x"}),
    ("/hmrc/exchange", {"code": "C", "state": "s.s", "code_verifier": "v" * 43, "redirect_uri": "https://evil"}),
    ("/vat/123456789/liabilities", envelope(**{"from": "2026-01-01", "to": "2026-03-31", "vrn": "999999999"})),
    ("/vat/123456789/liabilities", {**envelope(**{"from": "2026-01-01", "to": "2026-03-31"}),
                                     "client_facts": {**web_facts(), "public_ip": "1.2.3.4"}}),
    ("/vat/123456789/liabilities", envelope(**{"from": "2026-01-01", "to": "2026-03-31",
                                               "gov_test_scenario": "X\r\nInjected: 1"})),
])
async def test_unknown_or_malformed_fields_rejected(client_for, path, body):
    r = await client_for(never).post(path, headers={"X-HMRC-Access-Token": TOKEN}, json=body)
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("vrn", ["12345678", "1234567890", "GB123456789", "12345678X", "../12345"])
async def test_vrn_format(client_for, vrn):
    c = client_for(never)
    r = await c.post(f"/vat/{vrn}/obligations", headers={"X-HMRC-Access-Token": TOKEN},
                     json=envelope(**{"from": "2026-01-01", "to": "2026-03-31"}))
    assert r.status_code in (404, 422)
    assert (await c.get(f"/vat/check/{vrn}")).status_code in (404, 422)


@pytest.mark.parametrize("key", ["A1", "A1#11", "..%2F", "A1 1"])
async def test_period_key_format(client_for, key):
    r = await client_for(never).post(f"/vat/123456789/returns/{key}/view", headers={"X-HMRC-Access-Token": TOKEN},
                                     json=envelope())
    assert r.status_code in (404, 422)
