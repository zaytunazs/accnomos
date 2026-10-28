"""Bank feeds through TrueLayer (app/bank_feeds.py), against the fake in app/bankfeed_fakes.py, which answers with
the request and response shapes app/truelayer.py documents. Nothing here talks to TrueLayer."""

from __future__ import annotations

import base64
import json
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger.bank import BankLine, pair_duplicates, same_payment
from app import bank_feeds, bankfeed_fakes, truelayer
from app import books as books_mod
from app.bank_feeds import FEEDS, binding_hash, key_id, seal, to_line, unseal
from app.bankfeed_fakes import FAKES
from app.books import AUDIT, Books

USER = "sam@sambuilds.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
WEB = "http://localhost:3000"
BANK_PAGE = f"{WEB}/bank"
BINDING = "browser-only-secret-0123456789"
KEY = base64.b64encode(bytes(range(32))).decode()
TODAY = date(2026, 10, 27)
BARCLAYS = Path(__file__).resolve().parents[3] / "evals/gold/bank/barclays.csv"


def _env(monkeypatch: pytest.MonkeyPatch, *, on: bool = True) -> None:
    for k in (
        "ACCNOMOS_TEST_MODE",
        "TRUELAYER_CLIENT_ID",
        "TRUELAYER_CLIENT_SECRET",
        "BANKFEEDS_REDIRECT_URI",
        "BANKFEEDS_TOKEN_KEY",
        "TRUELAYER_ENV",
        "BANKFEEDS_LIVE",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CORS_ORIGINS", WEB)
    if on:
        monkeypatch.setenv("TRUELAYER_CLIENT_ID", bankfeed_fakes.CLIENT[0])
        monkeypatch.setenv("TRUELAYER_CLIENT_SECRET", bankfeed_fakes.CLIENT[1])
        monkeypatch.setenv("BANKFEEDS_REDIRECT_URI", "https://api.example/books/bankfeeds/callback")
        monkeypatch.setenv("BANKFEEDS_TOKEN_KEY", KEY)


class Clock:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.day = TODAY
        monkeypatch.setattr(books_mod, "today", lambda tz=None: self.day)
        monkeypatch.setattr(bank_feeds, "today", lambda tz=None: self.day)


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch):
    _env(monkeypatch)
    bankfeed_fakes.reset()
    bankfeed_fakes.install()
    bank_feeds._spent.clear()
    yield
    truelayer.TRANSPORT = None


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    return Clock(monkeypatch)


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
def books(fake: FakeStorageProvider) -> Books:
    return Books(fake)


@pytest.fixture
def client(books: Books, clock: Clock):
    from app.main import app
    from app.routes_books import get_books

    async def over_books() -> Books:
        return books

    app.dependency_overrides[get_books] = over_books
    yield TestClient(app)
    app.dependency_overrides.clear()


def _ok(r: httpx.Response) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


def _start(client: TestClient) -> str:
    return _ok(
        client.post(
            "/books/bankfeeds/start", json={"redirect_to": BANK_PAGE, "binding_hash": binding_hash(BINDING)}, headers=H
        )
    )["url"]


def _callback(client: TestClient, url: str) -> dict[str, str]:
    """Play the bank: the fake's picker answers a code; the runtime's callback forwards it in the fragment."""
    q = parse_qs(urlsplit(url).query)
    back = client.get(
        "/books/bankfeeds/callback",
        params={"code": FAKES.new_code(), "state": q["state"][0]},
        follow_redirects=False,
    )
    assert back.status_code == 303, back.text
    assert back.headers["location"].startswith(f"{BANK_PAGE}#")
    return dict(parse_qsl(urlsplit(back.headers["location"]).fragment))


def _connect(client: TestClient) -> dict:
    frag = _callback(client, _start(client))
    return _ok(
        client.post(
            "/books/bankfeeds/connect",
            json={"code": frag["code"], "state": frag["state"], "binding": BINDING},
            headers=H,
        )
    )


async def _audit(fake: FakeStorageProvider) -> list[dict]:
    out = []
    for f in await fake.list(AUDIT):
        if f.name.endswith(".jsonl"):
            out += [json.loads(x) for x in (await fake.read(f.path)).decode().splitlines() if x.strip()]
    return out


# --------------------------------------------------------------------------- #
# Off unless the server is set up; sandbox unless told otherwise
# --------------------------------------------------------------------------- #


def test_off_without_env_says_so_and_refuses_to_start(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    _env(monkeypatch, on=False)
    got = _ok(client.get("/books/bankfeeds", headers=H))
    assert got["available"] is False
    assert got["reason"] == "Bank feeds are not set up on this server yet. Upload a statement CSV instead."
    r = client.post(
        "/books/bankfeeds/start", json={"redirect_to": BANK_PAGE, "binding_hash": binding_hash(BINDING)}, headers=H
    )
    assert r.status_code == 503
    assert client.post("/books/bankfeeds/sync", headers=H).status_code == 503


def test_live_needs_its_own_switch_and_a_real_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUELAYER_ENV", "live")
    cfg, _, why = bank_feeds.config()
    assert cfg is None and why is not None and "only run in the sandbox" in why
    monkeypatch.setenv("BANKFEEDS_LIVE", "1")
    cfg, _, _ = bank_feeds.config()
    assert cfg is not None and cfg.auth_base == truelayer.LIVE_AUTH and not cfg.sandbox
    assert "uk-cs-mock" not in cfg.providers
    monkeypatch.setenv("BANKFEEDS_TOKEN_KEY", base64.b64encode(b"too short").decode())
    assert bank_feeds.config()[2] == "Bank feeds are switched off: the server's token key is not 32 bytes of base64."


def test_default_is_the_sandbox_with_the_mock_bank() -> None:
    cfg, key, why = bank_feeds.config()
    assert why is None and key is not None and cfg is not None
    assert cfg.auth_base == truelayer.SANDBOX_AUTH and cfg.api_base == truelayer.SANDBOX_API and cfg.sandbox
    assert "uk-cs-mock" in cfg.providers


# --------------------------------------------------------------------------- #
# The refresh token is sealed with the server key, bound to its connection
# --------------------------------------------------------------------------- #


def test_seal_round_trip_and_binding() -> None:
    key = bytes(range(32))
    sealed = seal("refresh-abc", key, "cred-1")
    assert "refresh-abc" not in sealed
    assert unseal(sealed, key, "cred-1") == "refresh-abc"
    assert unseal(sealed, key, "cred-2") is None  # copied onto another connection: unreadable
    assert unseal(sealed, bytes(32), "cred-1") is None  # another server key
    assert unseal("v1.garbage", key, "cred-1") is None
    assert seal("refresh-abc", key, "cred-1") != sealed  # a fresh nonce every time


# --------------------------------------------------------------------------- #
# Connect
# --------------------------------------------------------------------------- #


async def test_connect_stores_dates_and_a_sealed_token_only(client: TestClient, fake: FakeStorageProvider) -> None:
    url = _start(client)
    q = parse_qs(urlsplit(url).query)
    assert url.startswith(f"{truelayer.SANDBOX_AUTH}/?")
    assert q["scope"] == ["info accounts balance transactions offline_access"]
    assert q["response_type"] == ["code"] and q["client_id"] == [bankfeed_fakes.CLIENT[0]]
    assert "uk-cs-mock" in q["providers"][0]
    assert q["redirect_uri"] == ["https://api.example/books/bankfeeds/callback"]

    got = _connect(client)
    [conn] = got["connections"]
    assert conn["bank"] == bankfeed_fakes.BANK
    assert conn["accounts"] == [
        {
            "id": "fake-acc-0001",
            "name": "Business Current Account",
            "type": "TRANSACTION",
            "last4": "5678",
            "currency": "GBP",
        }
    ]
    assert conn["state"] == "ok" and conn["days_left"] == 90
    assert conn["reconfirm_by"] == "2027-01-25"
    assert conn["message"] == "Consent runs to 25 Jan 2027."
    assert "token" not in conn

    raw = (await fake.read(FEEDS)).decode()
    for t in FAKES.creds[conn["id"]].refresh | set(FAKES.access):
        assert t not in raw  # neither token in the clear
    stored = json.loads(raw)["connections"][0]
    assert stored["token"].startswith("v1.") and stored["key_id"] == key_id(bytes(range(32)))
    assert [a["action"] for a in await _audit(fake)] == ["bank_feed_connected"]

    token_call = next(r for r in FAKES.requests if r.url.path.endswith("/connect/token"))
    form = dict(parse_qsl(token_call.content.decode()))
    assert form["grant_type"] == "authorization_code"
    assert form["client_secret"] == bankfeed_fakes.CLIENT[1]
    assert form["redirect_uri"] == "https://api.example/books/bankfeeds/callback"


def test_connect_refuses_another_browser_another_user_and_a_reused_state(client: TestClient) -> None:
    frag = _callback(client, _start(client))
    body = {"code": frag["code"], "state": frag["state"], "binding": "someone-elses-browser-secret"}
    r = client.post("/books/bankfeeds/connect", json=body, headers=H)
    assert r.status_code == 400 and "another browser" in r.json()["detail"]
    r = client.post("/books/bankfeeds/connect", json={**body, "binding": BINDING}, headers=H)
    assert r.status_code == 400 and "expired" in r.json()["detail"]  # the state was spent by the first try

    frag = _callback(client, _start(client))
    r = client.post(
        "/books/bankfeeds/connect",
        json={"code": frag["code"], "state": frag["state"], "binding": BINDING},
        headers={**H, "X-User": "mallory@example.com"},
    )
    assert r.status_code == 400 and "someone else" in r.json()["detail"]


def test_start_only_comes_back_to_the_bank_page(client: TestClient) -> None:
    for where in ("https://evil.example/bank", f"{WEB}/settings"):
        r = client.post(
            "/books/bankfeeds/start", json={"redirect_to": where, "binding_hash": binding_hash(BINDING)}, headers=H
        )
        assert r.status_code == 400


def test_callback_with_a_bad_state_explains_in_plain_text(client: TestClient) -> None:
    r = client.get("/books/bankfeeds/callback", params={"code": "x", "state": "nope.nope"}, follow_redirects=False)
    assert r.status_code == 400 and "connect again" in r.text


def test_callback_passes_the_banks_refusal_on(client: TestClient) -> None:
    state = parse_qs(urlsplit(_start(client)).query)["state"][0]
    back = client.get(
        "/books/bankfeeds/callback", params={"error": "access_denied", "state": state}, follow_redirects=False
    )
    frag = dict(parse_qsl(urlsplit(back.headers["location"]).fragment))
    assert frag["error"] == "access_denied" and "code" not in frag


# --------------------------------------------------------------------------- #
# Sync into the bank lines, and duplicates against statement CSVs
# --------------------------------------------------------------------------- #


async def test_sync_files_the_lines_once(client: TestClient, fake: FakeStorageProvider, books: Books) -> None:
    _connect(client)
    got = _ok(client.post("/books/bankfeeds/sync", headers=H))
    assert got["new_lines"] == 6 and got["already_imported"] == 0 and got["already_fetched"] == 0
    assert got["filed_path"] == "04 Bank statements/2026-10-26_feed.csv"
    lines = await books.stored_bank_lines()
    assert [ln.amount_pence for ln in lines] == [-3847, 120000, -50000, -2399, 48000, -340]
    assert all(ln.feed_id and ln.source_file == got["filed_path"] for ln in lines)
    assert lines[1].reference == "INV-0042" and lines[0].balance_pence == 496153
    statements = _ok(client.get("/books/bank/statements", headers=H))
    assert [s["bank"] for s in statements] == ["feed"]

    tx_call = next(r for r in FAKES.requests if "/transactions" in r.url.path)
    assert dict(tx_call.url.params) == {"from": "2026-07-30", "to": "2026-10-27"}  # 89 days back on the first sync

    again = _ok(client.post("/books/bankfeeds/sync", headers=H))
    assert (
        again["new_lines"] == 0 and again["already_fetched"] == 3
    )  # the overlap window re-reads 3 and again["filed_path"] is None
    tx_calls = [r for r in FAKES.requests if "/transactions" in r.url.path]
    assert dict(tx_calls[-1].url.params)["from"] == "2026-10-20"  # last synced to, less the 7-day overlap
    [conn] = _ok(client.get("/books/bankfeeds", headers=H))["connections"]
    assert conn["synced_to"] == "2026-10-27" and conn["last_synced_at"]
    assert [a["action"] for a in await _audit(fake)].count("bank_feed_synced") == 2


async def test_csv_first_then_feed_drops_the_three_payments_already_there(client: TestClient, books: Books) -> None:
    with BARCLAYS.open("rb") as f:
        _ok(client.post("/books/bank/import", files={"file": ("barclays.csv", f, "text/csv")}, headers=H))
    _connect(client)
    got = _ok(client.post("/books/bankfeeds/sync", headers=H))
    assert got["new_lines"] == 3 and got["already_imported"] == 3
    feed = [ln for ln in await books.stored_bank_lines() if ln.feed_id]
    assert [ln.description for ln in feed] == ["B&Q WARRINGTON", "HARBOUR CAFE LTD", "COSTA COFFEE 1234"]
    assert len(await books.stored_bank_lines()) == 9


async def test_feed_first_then_csv_imports_only_what_the_feed_lacks(client: TestClient, books: Books) -> None:
    _connect(client)
    _ok(client.post("/books/bankfeeds/sync", headers=H))
    with BARCLAYS.open("rb") as f:
        got = _ok(client.post("/books/bank/import", files={"file": ("barclays.csv", f, "text/csv")}, headers=H))
    assert got["new_lines"] == 3 and got["from_feed"] == 3 and got["lines"] == 6
    csv_lines = [ln for ln in await books.stored_bank_lines() if not ln.feed_id]
    assert [ln.description for ln in csv_lines] == [
        "TOOLSTN 0412 CD 1234",
        "BUSINESS ACCOUNT FEE",
        "TRAVIS PERKINS 0099 ON 15 OCT",
    ]


async def test_one_bank_down_does_not_fail_the_sync(client: TestClient) -> None:
    _connect(client)
    FAKES.fail_transactions = True
    got = _ok(client.post("/books/bankfeeds/sync", headers=H))
    assert got["new_lines"] == 0
    assert got["connections"][0]["error"].startswith(bankfeed_fakes.BANK)


def _line(d: str, pence: int, desc: str, ref: str | None = None, lid: str = "") -> BankLine:
    return BankLine(
        id=lid or f"{d}{pence}{desc}"[:16],
        date=date.fromisoformat(d),
        amount_pence=pence,
        description=desc,
        reference=ref,
        source_file="x",
    )


def test_same_payment_needs_amount_date_and_a_word_or_reference() -> None:
    csv_ = _line("2026-10-01", -3847, "SCREWFIX DIRECT ON 30 SEP CLP")
    assert same_payment(_line("2026-10-01", -3847, "SCREWFIX DIRECT"), csv_)
    assert same_payment(_line("2026-10-03", -3847, "Screwfix"), csv_)  # posted two days later
    assert not same_payment(_line("2026-10-04", -3847, "SCREWFIX"), csv_)  # three days: another payment
    assert not same_payment(_line("2026-10-01", -3848, "SCREWFIX DIRECT"), csv_)  # a penny out
    assert not same_payment(_line("2026-10-01", -3847, "TOOLSTATION"), csv_)  # same money, someone else
    assert not same_payment(_line("2026-10-01", -3847, "CARD PAYMENT"), _line("2026-10-01", -3847, "DIRECT DEBIT"))
    assert same_payment(_line("2026-10-03", 120000, "BGC", "INV-0042"), _line("2026-10-03", 120000, "X", "inv 0042"))


def test_pairing_is_one_to_one() -> None:
    old = [
        _line("2026-10-26", -340, "COSTA COFFEE", lid="a" * 16),
        _line("2026-10-26", -340, "COSTA COFFEE", lid="b" * 16),
    ]
    new = [
        _line("2026-10-26", -340, "COSTA COFFEE 1234", lid="c" * 16),
        _line("2026-10-26", -340, "COSTA COFFEE 1234", lid="d" * 16),
        _line("2026-10-26", -340, "COSTA COFFEE 1234", lid="e" * 16),
    ]
    got = pair_duplicates(new, old)
    assert len(got) == 2 and len(set(got.values())) == 2  # the third coffee is a new payment


def test_to_line_signs_by_type_and_skips_what_it_cannot_read() -> None:
    base = {"transaction_id": "t1", "timestamp": "2026-10-01T10:00:00Z", "description": "  A   B ", "currency": "GBP"}
    debit = to_line({**base, "amount": 12.5, "transaction_type": "DEBIT"}, "c", "a")
    assert debit is not None and debit.amount_pence == -1250 and debit.description == "A B"
    assert to_line({**base, "amount": -12.5, "transaction_type": "CREDIT"}, "c", "a").amount_pence == 1250  # type: ignore[union-attr]
    assert to_line({**base, "amount": 1.234}, "c", "a") is None
    assert to_line({**base, "amount": 1, "currency": "EUR"}, "c", "a") is None
    assert to_line({**base, "amount": 1, "transaction_id": ""}, "c", "a") is None
    assert to_line({**base, "amount": 1, "timestamp": "yesterday"}, "c", "a") is None


# --------------------------------------------------------------------------- #
# Consent: 90 days, reconfirm before it ends, connect again after
# --------------------------------------------------------------------------- #


async def test_reconfirm_prompt_then_extend(client: TestClient, clock: Clock, fake: FakeStorageProvider) -> None:
    conn = _connect(client)["connections"][0]
    clock.day = TODAY + timedelta(days=80)
    [v] = _ok(client.get("/books/bankfeeds", headers=H))["connections"]
    assert v["state"] == "reconfirm" and v["days_left"] == 10
    assert v["message"] == "Your 90-day consent ends in 10 days (25 Jan 2027). Reconfirm to keep it going."

    r = client.post(f"/books/bankfeeds/{conn['id']}/reconfirm", json={}, headers=H)
    assert r.status_code == 400  # not without the user's yes
    got = _ok(client.post(f"/books/bankfeeds/{conn['id']}/reconfirm", json={"confirm": True}, headers=H))
    assert got["reauthorise"] is False
    assert got["connection"]["state"] == "ok" and got["connection"]["days_left"] == 90
    extend = next(r for r in FAKES.requests if r.url.path.endswith("/connections/extend"))
    assert json.loads(extend.content)["user_has_reconfirmed_consent"] is True
    assert "bank_feed_reconfirmed" in [a["action"] for a in await _audit(fake)]


def test_reconfirm_when_the_bank_wants_the_user_back(client: TestClient, clock: Clock) -> None:
    conn = _connect(client)["connections"][0]
    clock.day = TODAY + timedelta(days=85)
    FAKES.extend_needs_reauth = True
    got = _ok(client.post(f"/books/bankfeeds/{conn['id']}/reconfirm", json={"confirm": True}, headers=H))
    assert got["reauthorise"] is True and "connect again" in got["message"]


def test_after_expiry_nothing_is_read(client: TestClient, clock: Clock) -> None:
    conn = _connect(client)["connections"][0]
    clock.day = TODAY + timedelta(days=91)
    [v] = _ok(client.get("/books/bankfeeds", headers=H))["connections"]
    assert v["state"] == "expired" and "Connect again" in v["message"]
    before = len(FAKES.requests)
    got = _ok(client.post("/books/bankfeeds/sync", headers=H))
    assert got["connections"][0]["error"] == v["message"]
    assert len(FAKES.requests) == before  # not even a token refresh
    r = client.post(f"/books/bankfeeds/{conn['id']}/reconfirm", json={"confirm": True}, headers=H)
    assert r.status_code == 400


def test_a_changed_server_key_means_connect_again(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _connect(client)
    monkeypatch.setenv("BANKFEEDS_TOKEN_KEY", base64.b64encode(bytes(32)).decode())
    [v] = _ok(client.get("/books/bankfeeds", headers=H))["connections"]
    assert v["state"] == "key_changed"
    got = _ok(client.post("/books/bankfeeds/sync", headers=H))
    assert got["new_lines"] == 0 and "Connect again" in got["connections"][0]["error"]


async def test_disconnect_ends_it_at_truelayer_and_keeps_the_lines(client: TestClient, books: Books) -> None:
    conn = _connect(client)["connections"][0]
    _ok(client.post("/books/bankfeeds/sync", headers=H))
    assert client.post(f"/books/bankfeeds/{conn['id']}/disconnect", json={}, headers=H).status_code == 400
    got = _ok(client.post(f"/books/bankfeeds/{conn['id']}/disconnect", json={"confirm": True}, headers=H))
    assert got["status"]["connections"] == [] and got["warning"] is None
    assert conn["id"] in FAKES.deleted
    assert len(await books.stored_bank_lines()) == 6
    assert (
        client.post(f"/books/bankfeeds/{conn['id']}/disconnect", json={"confirm": True}, headers=H).status_code == 404
    )


async def test_a_hand_edited_file_loses_only_the_bad_connection(client: TestClient, books: Books) -> None:
    _connect(client)
    raw = await books.read_json(FEEDS, {})
    raw["connections"].append({"id": "../../etc", "bank": "x"})
    await books.write_json(FEEDS, raw)
    assert len(_ok(client.get("/books/bankfeeds", headers=H))["connections"]) == 1
