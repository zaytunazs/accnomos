"""OAuth state (10-minute TTL, one-time use, signed) and redirect allow-list bypass attempts."""

import time

import httpx
import pytest

from relay import oauth as oauth_mod
from relay.oauth import OAuth, StateError

from .conftest import make_settings

TOKENS = {"access_token": "AT1", "refresh_token": "RT2", "expires_in": 14400}


def never(_: httpx.Request) -> httpx.Response:
    raise AssertionError("HMRC must not be called")


def tokens(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=TOKENS)


def make_oauth() -> OAuth:
    return OAuth(make_settings(), httpx.AsyncClient(transport=httpx.MockTransport(never)))


# --- state ------------------------------------------------------------------------------------------------

def test_state_ttl_is_ten_minutes(monkeypatch):
    o = make_oauth()
    t0 = time.time()
    state = o.make_state("https://app.accnomos.example/cb", pkce=False)
    monkeypatch.setattr(oauth_mod.time, "time", lambda: t0 + 599)
    assert o.read_state(state).redirect_to == "https://app.accnomos.example/cb"
    monkeypatch.setattr(oauth_mod.time, "time", lambda: t0 + 601)
    with pytest.raises(StateError, match="expired"):
        o.read_state(state)


def test_state_is_one_time_per_step():
    o = make_oauth()
    state = o.make_state("https://app.accnomos.example/cb", pkce=True)
    o.read_state(state, use="callback")
    o.read_state(state, use="exchange")  # the PKCE exchange is a different step of the same flow
    for step in ("callback", "exchange"):
        with pytest.raises(StateError, match="already used"):
            o.read_state(state, use=step)


def test_spent_states_are_forgotten_after_expiry(monkeypatch):
    o = make_oauth()
    t0 = time.time()
    o.read_state(o.make_state("http://localhost/cb", pkce=False), use="callback")
    assert len(o._spent) == 1
    monkeypatch.setattr(oauth_mod.time, "time", lambda: t0 + 601)
    o.read_state(o.make_state("http://localhost/cb", pkce=False), use="callback")
    assert len(o._spent) == 1  # the expired nonce was pruned, the new one recorded


@pytest.mark.parametrize("bad", ["", ".", "a.b.c", "!!!.???", "e30.", "notbase64.sig"])
def test_malformed_state_rejected(bad):
    with pytest.raises(StateError):
        make_oauth().read_state(bad)


def test_state_from_another_secret_rejected():
    other = OAuth(make_settings(hmrc_client_secret="different"), httpx.AsyncClient())
    with pytest.raises(StateError, match="bad signature"):
        make_oauth().read_state(other.make_state("https://app.accnomos.example/cb", pkce=False))


def test_state_payload_cannot_be_swapped():
    o = make_oauth()
    good = o.make_state("https://app.accnomos.example/cb", pkce=False)
    evil = o.make_state("https://app.accnomos.example/other", pkce=False)
    with pytest.raises(StateError, match="bad signature"):
        o.read_state(f"{evil.split('.')[0]}.{good.split('.')[1]}")


async def test_callback_replay_refused(client_for):
    c = client_for(tokens)
    state = (await c.get("/hmrc/authorize", params={"redirect_to": "https://app.accnomos.example/cb"})).json()["state"]
    assert (await c.get("/hmrc/callback", params={"code": "C", "state": state})).status_code == 303
    r = await c.get("/hmrc/callback", params={"code": "C", "state": state})
    assert r.status_code == 400 and r.json()["code"] == "INVALID_STATE"


async def test_exchange_replay_refused(client_for):
    c = client_for(tokens)
    state = (await c.get("/hmrc/authorize", params={"redirect_to": "http://localhost:3000/cb",
                                                     "code_challenge": "c" * 43})).json()["state"]
    body = {"code": "C", "state": state, "code_verifier": "v" * 43}
    assert (await c.post("/hmrc/exchange", json=body)).status_code == 200
    r = await c.post("/hmrc/exchange", json=body)
    assert r.status_code == 400 and r.json()["code"] == "INVALID_STATE"


# --- redirect allow-list ----------------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://app.accnomos.example/cb",
    "https://APP.accnomos.example/cb?x=1",
    "http://localhost:3000/cb",
    "http://127.0.0.1/cb",
])
def test_redirect_allowed(url):
    assert make_settings().redirect_allowed(url)


@pytest.mark.parametrize("url", [
    "https://evil.example/cb",
    "https://app.accnomos.example.evil.example/cb",       # suffix
    "https://evilapp.accnomos.example/cb",
    "https://app.accnomos.example@evil.example/cb",       # userinfo: the host is evil.example
    "https://user:pw@app.accnomos.example/cb",            # userinfo on the right host: still refused
    "https://app.accnomos.example\\@evil.example/cb",     # backslash (browsers read it as a slash)
    "https://app.accnomos.example\t.evil.example/cb",     # tab, dropped by urlsplit but not by us
    "https://app.accnomos.example/cb\r\nSet-Cookie: x=1",  # header injection
    "http://app.accnomos.example/cb",                     # downgrade to http
    "https://app.accnomos.example:8443/cb",               # other port
    "//app.accnomos.example/cb",                          # scheme-relative
    "/cb",
    "javascript:alert(1)",
    "data:text/html,hi",
    "https:app.accnomos.example",
    "http://localhost.evil.example/cb",
    "http://127.0.0.1.nip.io/cb",
    "http://localhost@evil.example/cb",
    "https://localhost/cb",                               # the dev exception covers plain http only
    "",
])
def test_redirect_bypass_attempts_refused(url):
    assert not make_settings().redirect_allowed(url)


@pytest.mark.parametrize("url", ["https://app.accnomos.example@evil.example/cb", "https://evil.example/#https://app.accnomos.example"])
async def test_authorize_refuses_bypass_redirects(client_for, url):
    r = await client_for(never).get("/hmrc/authorize", params={"redirect_to": url})
    assert r.status_code == 400
