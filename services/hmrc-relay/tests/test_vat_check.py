"""GET /hmrc/vat-check/{vrn}: Check a UK VAT number v2.0 through the relay, against a faked HMRC."""

import logging
from urllib.parse import parse_qs

import httpx
import pytest

from relay.routes import mod97_ok, parse_vrn

LOOKUP = "/organisations/vat/check-vat-number/lookup"
# HMRC's own sandbox example (OAS v2.0): target 553557881, requester 146295999727.
FOUND = {
    "target": {
        "name": "Credite Sberger Donal Inc.",
        "vatNumber": "553557881",
        "address": {"line1": "131B Barton Hamlet", "postcode": "SW97 5CK", "countryCode": "GB"},
    },
    "processingDate": "2019-01-31T12:43:17+00:00",
}


def fake_hmrc(log: list[httpx.Request], answers: dict[str, tuple[int, dict]]):
    def hmrc(req: httpx.Request) -> httpx.Response:
        log.append(req)
        if req.url.path == "/oauth/token":
            form = parse_qs(req.content.decode())
            assert form["grant_type"] == ["client_credentials"] and form["scope"] == ["read:vat"]
            return httpx.Response(200, json={"access_token": "APPVAT", "expires_in": 14400, "scope": "read:vat"})
        assert req.headers["authorization"] == "Bearer APPVAT"
        assert req.headers["accept"] == "application/vnd.hmrc.2.0+json"
        status, payload = answers[req.url.path]
        return httpx.Response(status, json=payload)

    return hmrc


def never(_: httpx.Request) -> httpx.Response:
    raise AssertionError("HMRC must not be called")


async def test_registered_number_and_cached_scoped_token(client_for):
    log: list[httpx.Request] = []
    c = client_for(fake_hmrc(log, {f"{LOOKUP}/553557881": (200, FOUND)}))
    r = await c.get("/hmrc/vat-check/GB 553 5578 81")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["registered"] is True and j["vrn"] == "GB553557881"
    assert j["name"] == "Credite Sberger Donal Inc."
    assert j["address"] == "131B Barton Hamlet, SW97 5CK"
    assert j["source"] == "hmrc-sandbox" and j["consultation_number"] is None and j["checked_at"]
    assert j["checksum_ok"] is False  # HMRC's own test number fails mod-97: informational, never blocks
    assert (await c.get("/hmrc/vat-check/553557881")).status_code == 200
    assert [q.url.path for q in log].count("/oauth/token") == 1  # token cached until expiry


async def test_requester_gets_consultation_number(client_for):
    log: list[httpx.Request] = []
    ref = {**FOUND, "requester": "146295999727", "consultationNumber": "ypAeKRPlW"}
    c = client_for(fake_hmrc(log, {f"{LOOKUP}/553557881/146295999727": (200, ref)}))
    r = await c.get("/hmrc/vat-check/553557881", params={"requester": "GB146295999727"})
    assert r.json()["consultation_number"] == "ypAeKRPlW"


async def test_not_found_means_not_registered(client_for):
    log: list[httpx.Request] = []
    nf = {"code": "NOT_FOUND", "message": "targetVrn does not match a registered company"}
    c = client_for(fake_hmrc(log, {f"{LOOKUP}/123456789": (404, nf)}))
    r = await c.get("/hmrc/vat-check/123456789")
    assert r.status_code == 200
    assert r.json()["registered"] is False and r.json()["name"] is None


async def test_unknown_requester_is_a_400(client_for):
    log: list[httpx.Request] = []
    bad = {"code": "INVALID_REQUEST", "message": "requesterVrn does not match a registered company"}
    c = client_for(fake_hmrc(log, {f"{LOOKUP}/553557881/111111111": (403, bad)}))
    r = await c.get("/hmrc/vat-check/553557881?requester=111111111")
    assert r.status_code == 400 and "own VAT number" in r.json()["detail"]


async def test_hmrc_500_passes_through(client_for):
    log: list[httpx.Request] = []
    err = {"code": "INTERNAL_SERVER_ERROR", "message": "Unknown error"}
    c = client_for(fake_hmrc(log, {f"{LOOKUP}/553557881": (500, err)}))
    assert (await c.get("/hmrc/vat-check/553557881")).status_code == 500


@pytest.mark.parametrize("vrn", ["12345678", "1234567890", "XI123456789", "GBGD001", "12345678X", "..%2F1"])
async def test_invalid_vrn_never_reaches_hmrc(client_for, vrn):
    r = await client_for(never).get(f"/hmrc/vat-check/{vrn}")
    assert r.status_code in (400, 404), r.text


async def test_invalid_requester_never_reaches_hmrc(client_for):
    r = await client_for(never).get("/hmrc/vat-check/553557881?requester=12")
    assert r.status_code == 400


async def test_production_base_labels_source_hmrc(client_for):
    log: list[httpx.Request] = []
    c = client_for(fake_hmrc(log, {f"{LOOKUP}/553557881": (200, FOUND)}), hmrc_base="https://api.service.hmrc.gov.uk")
    assert (await c.get("/hmrc/vat-check/553557881")).json()["source"] == "hmrc"
    assert str(log[-1].url).startswith("https://api.service.hmrc.gov.uk/")


async def test_not_configured_is_503(client_for):
    r = await client_for(never, hmrc_client_id="", hmrc_client_secret="").get("/hmrc/vat-check/553557881")
    assert r.status_code == 503


async def test_rate_limited_per_client_ip(client_for):
    log: list[httpx.Request] = []
    c = client_for(fake_hmrc(log, {f"{LOOKUP}/553557881": (200, FOUND)}), rate_limit_per_min=2)
    assert [(await c.get("/hmrc/vat-check/553557881")).status_code for _ in range(3)] == [200, 200, 429]


async def test_bodies_never_logged(client_for, caplog):
    log: list[httpx.Request] = []
    c = client_for(fake_hmrc(log, {f"{LOOKUP}/553557881": (200, FOUND)}))
    with caplog.at_level(logging.DEBUG):
        await c.get("/hmrc/vat-check/553557881")
    assert "Barton Hamlet" not in caplog.text and "APPVAT" not in caplog.text


def test_parse_and_checksum_helpers():
    assert parse_vrn("gb 123-456.789") == "123456789"
    assert parse_vrn("GB123456789012") == "123456789012"
    assert mod97_ok("123456782") is True  # weights 8..2 give 112; 112 + 82 = 194 = 2 x 97
    assert mod97_ok("123456789") is False
    assert mod97_ok("123456789012") is None
