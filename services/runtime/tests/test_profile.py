"""Profiles (app/profile.py): profile.json round trip, kind gating, and two linked accounts never mixing.

Each profile is its own Microsoft account. In test mode a token "test-token.<account>" is another account with a
OneDrive of its own (app/testmode.py TEST_ACCOUNT_TOKEN), which is how these tests sign in as two people.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app import cache, profile, testmode
from app.books import Books
from app.routes_dashboard import router as dashboard_router
from app.routes_invoices import router as invoices_router
from app.routes_payroll import router as payroll_router
from app.routes_profile import router as profile_router
from app.routes_reports import router as reports_router
from app.routes_vat import router as vat_router

A = {"X-Graph-Token": "test-token", "X-User": "sam@sambuilds.example"}
B = {"X-Graph-Token": "test-token.jo", "X-User": "jo@personal.example"}

COMPANY = {"name": "Sam Builds Ltd", "kind": "company", "settings": {"company_number": "01234567"}}
PERSONAL = {"name": "Jo at home", "kind": "personal"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", "1")
    monkeypatch.setenv("ACCNOMOS_TEST_TODAY", testmode.DEFAULT_TODAY)
    monkeypatch.delenv("ACCNOMOS_TEST_AI_BASE", raising=False)
    app = FastAPI()
    for r in (
        testmode.router,
        profile_router,
        vat_router,
        invoices_router,
        payroll_router,
        reports_router,
        dashboard_router,
    ):
        app.include_router(r)
    app.add_middleware(testmode.TenantMiddleware)
    c = TestClient(app, headers={testmode.TENANT_HEADER: "profiles"})
    assert c.post("/__test/reset", headers=A).json()["ok"]
    assert c.post("/__test/reset", headers=B).json()["ok"]
    return c


def _drive(token: str) -> FakeStorageProvider:
    suffix = testmode.account_suffix({b"x-graph-token": token.encode()})
    return testmode.STATES[f"profiles{suffix}"].storage


# --------------------------------------------------------------------------- #
# profile.json
# --------------------------------------------------------------------------- #


def test_no_profile_yet_is_a_vat_registered_company(client: TestClient) -> None:
    got = client.get("/profile", headers={**A, "X-Business-Name": "Sam Builds Ltd"}).json()
    assert (got["exists"], got["kind"], got["name"]) == (False, "company", "Sam Builds Ltd")
    assert got["settings"]["vat_registered"] is True
    assert {"vat", "invoices", "payroll"} <= set(got["features"])
    assert "self_employment" not in got["features"]


def test_round_trip(client: TestClient) -> None:
    body = {
        "name": "  Sam   Builds Ltd ",
        "kind": "sole_trader",
        "settings": {"utr": "12345 67890", "vat_number": "gb 123 4567 89", "accounting_period_start": "01-01"},
        "linked": [
            {"username": "jo@personal.example", "name": "Jo at home", "kind": "personal"},
            {"username": "SAM@sambuilds.example"},  # the account itself is never listed
        ],
    }
    saved = client.put("/profile", headers=A, json=body)
    assert saved.status_code == 200, saved.text
    got = client.get("/profile", headers=A).json()
    assert got == saved.json()
    assert got["name"] == "Sam Builds Ltd"
    assert got["settings"] == {
        "vat_number": "GB123456789",
        "vat_registered": True,  # a VAT number and nothing said: registered
        "utr": "1234567890",
        "accounting_period_start": "01-01",
    }
    assert [a["username"] for a in got["linked"]] == ["jo@personal.example"]
    assert "self_employment" in got["features"] and "vat" in got["features"]
    on_disk = json.loads(_drive("test-token").files[profile.PROFILE])
    assert on_disk["kind"] == "sole_trader" and "features" not in on_disk and "exists" not in on_disk
    audit = b"".join(v for k, v in _drive("test-token").files.items() if k.startswith("_System/audit/"))
    assert b'"profile_saved"' in audit

    # linked left out keeps what was saved
    client.put("/profile", headers=A, json={"name": "Sam", "kind": "sole_trader", "settings": {"utr": "1234567890"}})
    assert [a["username"] for a in client.get("/profile", headers=A).json()["linked"]] == ["jo@personal.example"]


@pytest.mark.parametrize(
    ("body", "says"),
    [
        ({"name": "X", "kind": "company", "settings": {"vat_number": "123"}}, "9 digits"),
        ({"name": "X", "kind": "company", "settings": {"company_number": "12"}}, "Companies House"),
        ({"name": "X", "kind": "sole_trader", "settings": {"utr": "abc"}}, "10 digits"),
        ({"name": "X", "kind": "sole_trader", "settings": {"accounting_period_start": "13-01"}}, "MM-DD"),
        ({"name": "X", "kind": "personal", "settings": {"vat_number": "GB123456789"}}, "vat_number"),
        ({"name": "   ", "kind": "personal"}, "name"),
    ],
)
def test_bad_settings_are_a_sentence(client: TestClient, body: dict, says: str) -> None:
    r = client.put("/profile", headers=A, json=body)
    assert r.status_code == 400, r.text
    assert says in r.json()["detail"]


def test_saving_needs_a_user(client: TestClient) -> None:
    r = client.put("/profile", headers={"X-Graph-Token": "test-token"}, json=PERSONAL)
    assert r.status_code == 400


def test_a_hand_edited_file_falls_back_to_the_defaults() -> None:
    assert profile.from_file({"kind": "llc"}).exists is False
    assert profile.from_file({"kind": "company", "settings": {"vat_number": "nope"}}).exists is False
    p = profile.from_file({"kind": "personal", "name": "Me", "linked": [{"username": "not an email"}]})
    assert (p.exists, p.kind, p.linked) == (True, "personal", [])


# --------------------------------------------------------------------------- #
# Kind gating
# --------------------------------------------------------------------------- #

VAT_ROUTES = ["/books/vat", "/books/vat/periods", "/books/deadlines", "/reports/vat"]
OTHER_GATED = ["/invoices", "/invoices/profile", "/payroll/runs"]


def test_personal_books_have_no_vat_invoices_or_payroll(client: TestClient) -> None:
    assert client.put("/profile", headers=B, json=PERSONAL).status_code == 200
    for path in VAT_ROUTES + OTHER_GATED:
        r = client.get(path, headers=B)
        assert r.status_code == 404, path
        assert "personal profile" in r.json()["detail"], path
    assert client.post("/invoices", headers=B, json={}).status_code == 404  # gated before the body is looked at
    feats = client.get("/profile", headers=B).json()["features"]
    assert not {"vat", "invoices", "payroll"} & set(feats)


def test_vat_pages_need_a_vat_registered_business(client: TestClient) -> None:
    assert client.put("/profile", headers=A, json=COMPANY).status_code == 200  # no VAT number: not registered
    for path in VAT_ROUTES:
        r = client.get(path, headers=A)
        assert r.status_code == 404 and "not VAT-registered" in r.json()["detail"], path
    for path in OTHER_GATED:
        assert client.get(path, headers=A).status_code == 200, path
    on = {**COMPANY, "settings": {"company_number": "01234567", "vat_registered": True}}
    assert client.put("/profile", headers=A, json=on).status_code == 200
    for path in VAT_ROUTES:
        assert client.get(path, headers=A).status_code == 200, path


def _dashboard(client: TestClient, who: dict[str, str]) -> dict:
    r = client.get("/books/dashboard", headers=who, params={"today": "2026-10-27"})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_dashboard_vat_tile_is_only_for_vat_registered_businesses(client: TestClient) -> None:
    # No profile yet: a VAT-registered company, as before profiles.
    d = _dashboard(client, A)
    assert d["vat_applies"] is True and d["vat"] is not None
    # A company that is not VAT-registered: no VAT block, and "vat" is not an unavailable section either.
    assert client.put("/profile", headers=A, json=COMPANY).status_code == 200
    d = _dashboard(client, A)
    assert (d["vat_applies"], d["vat"]) == (False, None)
    assert "vat" not in d["unavailable"]
    assert d["cash"] is not None and d["attention"] is not None  # the other tiles are still worked out
    # Personal books: never VAT.
    assert client.put("/profile", headers=B, json=PERSONAL).status_code == 200
    d = _dashboard(client, B)
    assert (d["vat_applies"], d["vat"]) == (False, None)
    # A sole trader who is VAT-registered gets the tile back.
    sole = {"name": "Sam", "kind": "sole_trader", "settings": {"vat_number": "GB123456789"}}
    assert client.put("/profile", headers=A, json=sole).status_code == 200
    d = _dashboard(client, A)
    assert d["vat_applies"] is True and d["vat"] is not None


def test_an_unreadable_profile_keeps_the_vat_tile(client: TestClient) -> None:
    _drive("test-token").files[profile.PROFILE] = b"{not json"
    d = _dashboard(client, A)
    assert d["vat_applies"] is True and d["vat"] is not None


def test_books_with_no_profile_keep_every_feature(client: TestClient) -> None:
    for path in VAT_ROUTES + OTHER_GATED:
        assert client.get(path, headers=A).status_code == 200, path


# --------------------------------------------------------------------------- #
# Two accounts never mix
# --------------------------------------------------------------------------- #


def test_each_account_has_its_own_books(client: TestClient) -> None:
    client.put("/profile", headers=A, json=COMPANY)
    client.put("/profile", headers=B, json=PERSONAL)
    assert client.get("/profile", headers=A).json()["name"] == "Sam Builds Ltd"
    assert client.get("/profile", headers=B).json()["name"] == "Jo at home"
    assert _drive("test-token") is not _drive("test-token.jo")
    assert json.loads(_drive("test-token.jo").files[profile.PROFILE])["kind"] == "personal"
    # each audit trail has only its own account's line
    a_audit = b"".join(v for k, v in _drive("test-token").files.items() if k.startswith("_System/audit/"))
    b_audit = b"".join(v for k, v in _drive("test-token.jo").files.items() if k.startswith("_System/audit/"))
    assert b"sam@sambuilds.example" in a_audit and b"jo@personal.example" not in a_audit
    assert b"jo@personal.example" in b_audit and b"sam@sambuilds.example" not in b_audit


def test_account_suffix_only_for_well_formed_test_tokens() -> None:
    def suffix(raw: bytes, header: bytes = b"x-graph-token") -> str:
        return testmode.account_suffix({header: raw})

    assert suffix(b"test-token") == ""
    assert suffix(b"test-token.jo") == "~jo"
    assert suffix(b"Bearer test-token.jo", b"authorization") == "~jo"  # the browser's Graph look-alike calls
    assert suffix(b"test-token.JO") == "" and suffix(b"test-token.a/b") == "" and suffix(b"x.test-token.jo") == ""


def test_cache_keys_differ_per_account() -> None:
    assert cache.user_cache_key("token-a") != cache.user_cache_key("token-b")
    assert cache.user_cache_key("t", "tenant") != cache.user_cache_key("t")
    assert cache.user_cache_key("token-a") == cache.user_cache_key("token-a")  # stable: the next request hits


async def test_the_immutable_cache_never_serves_one_account_to_another() -> None:
    cache.clear()
    path = "_System/Ledger/events/2026-10/20261027T000000Z-runtime-ev1.json"
    a_drive, b_drive = FakeStorageProvider(), FakeStorageProvider()
    a_drive.files[path] = b'{"who": "a"}'
    b_drive.files[path] = b'{"who": "b"}'
    a = Books(a_drive, cache_key=cache.user_cache_key("token-a"))
    b = Books(b_drive, cache_key=cache.user_cache_key("token-b"))
    assert await a.storage.read(path) == b'{"who": "a"}'  # now in the cross-request cache, for account a only
    assert await b.storage.read(path) == b'{"who": "b"}'
    # A fresh request by b, with a's bytes cached: still b's file
    b2 = Books(b_drive, cache_key=cache.user_cache_key("token-b"))
    assert await b2.storage.read(path) == b'{"who": "b"}'
    assert cache.get_cached(cache.user_cache_key("token-a"), path) == b'{"who": "a"}'
    cache.clear()
