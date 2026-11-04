"""Bank feeds in the demo sandbox (app/routes_bankfeeds.py, app/bank_feeds.py; docs/BANK_FEED_SANDBOX_DEMO.md): a demo
session connects TrueLayer's sandbox test bank only, into its own in-memory books, with a state bound to that demo.
TrueLayer is the fake in app/bankfeed_fakes.py; nothing here talks to TrueLayer."""

from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, parse_qsl, urlsplit

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from test_bank_feeds import BINDING, TODAY, WEB, _env  # sibling module: pytest puts tests/ on the path

from accnomos_connectors import FakeStorageProvider
from app import bank_feeds, bankfeed_fakes, demo, truelayer
from app import books as books_mod
from app.bank_feeds import FEEDS, binding_hash
from app.bankfeed_fakes import FAKES
from app.books import INBOX, Books
from app.routes_bank import router as bank_router
from app.routes_bankfeeds import router as bankfeeds_router
from app.routes_books import get_books
from app.routes_books import router as books_router

BANK_PAGE = f"{WEB}/bank"


async def small_build(day):  # noqa: ANN001, ANN201
    st = FakeStorageProvider()
    await st.write("README.txt", b"SAMPLE - FICTIONAL COMPANY")
    await st.write(f"{INBOX}/SAMPLE 01.png", b"\x89PNG sample")
    await st.ensure_folder("_System/Ledger/events")
    return demo.Snapshot(day, st, "Bramblewood Joinery Ltd", 0.01)


@pytest.fixture(autouse=True)
def _env_and_fakes(monkeypatch: pytest.MonkeyPatch):
    _env(monkeypatch)
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_SECRET", "s" * 40)
    monkeypatch.setattr(demo, "BUILD", small_build)
    monkeypatch.setattr(demo, "CREATE_LIMITER", None)
    monkeypatch.setattr(books_mod, "today", lambda tz=None: TODAY)
    monkeypatch.setattr(bank_feeds, "today", lambda tz=None: TODAY)
    demo.reset_for_tests()
    bankfeed_fakes.reset()
    bankfeed_fakes.install()
    bank_feeds._spent.clear()
    yield
    truelayer.TRANSPORT = None
    demo.reset_for_tests()


#: The server's real books (a signed-in user's OneDrive): a demo must never write here.
REAL = FakeStorageProvider()


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(demo.router)
    app.include_router(books_router)
    app.include_router(bankfeeds_router)
    app.include_router(bank_router)
    real_get_books = get_books

    async def books_or_real(request: Request) -> Books:
        s = demo.from_request(request)
        return s.books() if s is not None else Books(REAL)

    app.dependency_overrides[real_get_books] = books_or_real
    REAL.files.clear()
    return TestClient(app)


def _session(client: TestClient) -> tuple[dict[str, str], demo.DemoSession]:
    r = client.post("/demo/session")
    assert r.status_code == 200, r.text
    token = r.json()["session"]
    s = demo.STORE.get(demo.unsign(token) or "")
    assert s is not None
    return {demo.HEADER: token, "X-User": demo.USER}, s


def _ok(r) -> dict:  # noqa: ANN001
    assert r.status_code == 200, r.text
    return r.json()


def _start(client: TestClient, h: dict[str, str]) -> str:
    body = {"redirect_to": BANK_PAGE, "binding_hash": binding_hash(BINDING)}
    return _ok(client.post("/books/bankfeeds/start", json=body, headers=h))["url"]


def _back(client: TestClient, url: str) -> dict[str, str]:
    """Play TrueLayer's mock bank: sign in, agree, and come back through the runtime's callback."""
    state = parse_qs(urlsplit(url).query)["state"][0]
    back = client.get(
        "/books/bankfeeds/callback", params={"code": FAKES.new_code(), "state": state}, follow_redirects=False
    )
    assert back.status_code == 303 and back.headers["location"].startswith(f"{BANK_PAGE}#"), back.text
    return dict(parse_qsl(urlsplit(back.headers["location"]).fragment))


def _connect_body(frag: dict[str, str]) -> dict[str, str]:
    return {"code": frag["code"], "state": frag["state"], "binding": BINDING}


def test_demo_status_offers_the_test_bank_with_its_public_login(client: TestClient) -> None:
    h, _ = _session(client)
    got = _ok(client.get("/books/bankfeeds", headers=h))
    assert got["available"] and got["sandbox"] and got["demo"] and got["connections"] == []
    assert got["label"] == "Bank sandbox (TrueLayer test bank) — no real bank data"
    assert got["test_login"] == {
        "username": "john",
        "password": "doe",
        "source_url": "https://docs.truelayer.com/docs/mock-users",
    }
    # Outside a demo: no demo label and no test login.
    plain = _ok(client.get("/books/bankfeeds", headers={"X-Graph-Token": "t", "X-User": "sam@example.com"}))
    assert not plain["demo"] and plain["test_login"] is None and plain["label"] is None


async def test_demo_connects_the_sandbox_bank_and_syncs_into_its_own_books(client: TestClient) -> None:
    h, s = _session(client)
    url = _start(client, h)
    q = parse_qs(urlsplit(url).query)
    assert q["providers"] == ["uk-cs-mock"]  # TrueLayer's mock bank only
    token = h[demo.HEADER]
    assert token not in url and s.id not in url  # the session id never travels through TrueLayer
    payload = json.loads(base64.urlsafe_b64decode(q["state"][0].split(".")[0] + "=="))
    assert payload["d"] == bank_feeds.demo_hash(s.id)

    status = _ok(client.post("/books/bankfeeds/connect", json=_connect_body(_back(client, url)), headers=h))
    [conn] = status["connections"]
    assert conn["sandbox"] and conn["bank"] == bankfeed_fakes.BANK and status["demo"]

    got = _ok(client.post("/books/bankfeeds/sync", headers=h))
    assert got["new_lines"] == 6
    lines = await s.books().stored_bank_lines()
    assert len(lines) == 6 and all(ln.feed_id for ln in lines)
    assert FEEDS.strip("/") in s.storage.files
    stored = s.storage.files[FEEDS.strip("/")].decode()
    assert "fake-refresh" not in stored and "fake-access" not in stored  # sealed, never the access token
    # The bank lines page shows them (matching and rules run on them as on a statement's).
    assert [x["bank"] for x in _ok(client.get("/books/bank/statements", headers=h))] == ["feed"]
    unmatched = _ok(client.get("/books/bank/unmatched", headers=h))
    assert "B&Q WARRINGTON" in {u["line"]["description"] for u in unmatched}  # ready to match or settle

    assert REAL.files == {}  # the server's real books were never touched
    other, _ = _session(client)  # and another demo has no connection
    assert _ok(client.get("/books/bankfeeds", headers=other))["connections"] == []


def test_the_connection_ends_with_the_demo_session(client: TestClient) -> None:
    h, s = _session(client)
    _ok(client.post("/books/bankfeeds/connect", json=_connect_body(_back(client, _start(client, h))), headers=h))
    demo.STORE.drop(s.id)  # what the idle TTL does
    assert client.get("/books/bankfeeds", headers=h).status_code == 401


def test_a_state_from_another_demo_or_from_outside_is_refused(client: TestClient) -> None:
    a, _ = _session(client)
    b, _ = _session(client)
    frag = _back(client, _start(client, a))
    r = client.post("/books/bankfeeds/connect", json=_connect_body(frag), headers=b)
    assert r.status_code == 400 and "another demo session" in r.json()["detail"]
    assert _ok(client.get("/books/bankfeeds", headers=b))["connections"] == []

    # A signed-in user's state cannot be finished in a demo, nor a demo's by a signed-in user.
    st = bank_feeds.make_state(BANK_PAGE, binding_hash(BINDING), demo.USER)
    with pytest.raises(bank_feeds.BankFeedError, match="another demo session"):
        bank_feeds._finish(st, BINDING, demo.USER, "some-demo-id")
    st = bank_feeds.make_state(BANK_PAGE, binding_hash(BINDING), demo.USER, "some-demo-id")
    with pytest.raises(bank_feeds.BankFeedError, match="another demo session"):
        bank_feeds._finish(st, BINDING, demo.USER, None)


def test_the_state_is_signed(client: TestClient) -> None:
    st = bank_feeds.make_state(BANK_PAGE, binding_hash(BINDING), demo.USER, "demo-a")
    payload, sig = st.split(".")
    body = json.loads(base64.urlsafe_b64decode(payload + "=="))
    body["d"] = bank_feeds.demo_hash("demo-b")
    forged = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).rstrip(b"=").decode()
    with pytest.raises(bank_feeds.StateError, match="bad signature"):
        bank_feeds.read_state(f"{forged}.{sig}")
    assert bank_feeds.read_state(st)["demo"] == bank_feeds.demo_hash("demo-a")


@pytest.mark.parametrize("live", [False, True])
def test_refused_in_a_demo_unless_the_server_is_on_the_sandbox(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, live: bool
) -> None:
    if live:  # pointed at live banks (allowed for signed-in users): never for a demo
        monkeypatch.setenv("TRUELAYER_ENV", "live")
        monkeypatch.setenv("BANKFEEDS_LIVE", "1")
        why = bank_feeds.DEMO_NOT_SANDBOX
    else:  # no TrueLayer credentials at all
        _env(monkeypatch, on=False)
        why = bank_feeds.DEMO_OFF
    h, _ = _session(client)
    got = _ok(client.get("/books/bankfeeds", headers=h))
    assert not got["available"] and got["reason"] == why and got["test_login"] is None
    body = {"redirect_to": BANK_PAGE, "binding_hash": binding_hash(BINDING)}
    for path, payload in (
        ("/books/bankfeeds/start", body),
        ("/books/bankfeeds/connect", {"code": "c", "state": "s", "binding": BINDING}),
        ("/books/bankfeeds/sync", None),
    ):
        r = client.post(path, json=payload, headers=h)
        assert r.status_code == 403, (path, r.text)
        assert r.json()["detail"].startswith("Connecting a bank feed is switched off in the demo sandbox.")
        assert why in r.json()["detail"]
    assert not FAKES.requests  # nothing reached TrueLayer


async def test_a_base64_credentials_id_from_truelayer_is_accepted() -> None:
    """TrueLayer's sandbox sends credentials ids like "Ab+c/D==": kept as a stable, path-safe id."""

    class Api:
        async def me(self, access: str) -> dict:
            return {"credentials_id": "6L7SJ6mNv5q+cqd5/TaHL5Ij5mIx==", "provider": {"display_name": "MOCK"}}

        async def accounts(self, access: str) -> list:
            return []

    cred, bank, *_ = await bank_feeds._describe(Api(), "tok")  # noqa: SLF001
    again, *_ = await bank_feeds._describe(Api(), "tok")  # noqa: SLF001
    assert cred == again and cred.startswith("tl_") and bank_feeds.ID_RE.match(cred) and bank == "MOCK"
