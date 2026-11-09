"""A Google account end to end (app/accounts.py): the books in Google Drive, through the in-memory Drive transport
(accnomos_connectors.fake_drive), with test mode off so the real providers are built."""

from __future__ import annotations

import importlib.util

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import google_drive
from accnomos_connectors.fake_drive import FakeDrive
from app import accounts, identity
from app.main import app

pytestmark = pytest.mark.real_identity

HAS_WORKSPACE = importlib.util.find_spec("accnomos_connectors.google_workspace") is not None


@pytest.fixture
def drive(monkeypatch: pytest.MonkeyPatch) -> FakeDrive:
    monkeypatch.delenv("ACCNOMOS_TEST_MODE", raising=False)
    fake = FakeDrive(token="g-token", email="Owner@Example.com", name="Ada Owner")
    monkeypatch.setattr(google_drive, "TRANSPORT", fake.transport())
    identity.reset()
    yield fake
    identity.reset()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


GOOGLE = {"X-Graph-Token": "g-token", "X-Account-Kind": "google"}


def test_books_live_in_google_drive(drive: FakeDrive, client: TestClient) -> None:
    root = drive.add("Accnomos")
    inbox = drive.add("00 Inbox", root)
    drive.add("receipt.jpg", inbox, b"jpeg")
    r = client.get("/books/inbox", headers=GOOGLE)
    assert r.status_code == 200, r.text
    assert [f["path"] for f in r.json()] == ["00 Inbox/receipt.jpg"]
    assert any(c.startswith("GET /drive/v3/files") for c in drive.calls)


def test_bearer_authorization_is_accepted_for_google(drive: FakeDrive, client: TestClient) -> None:
    r = client.get("/books/inbox", headers={"Authorization": "Bearer g-token", "X-Account-Kind": "google"})
    assert r.status_code == 200, r.text
    assert drive.find("Accnomos") is not None  # made on first use


def test_authorization_alone_is_not_a_graph_token(client: TestClient) -> None:
    r = client.get("/books/inbox", headers={"Authorization": "Bearer g-token"})  # no kind: Microsoft
    assert r.status_code == 401


def test_a_refused_google_token_asks_to_sign_in_again(drive: FakeDrive, client: TestClient) -> None:
    r = client.get("/books/inbox", headers={**GOOGLE, "X-Graph-Token": "expired"})
    assert r.status_code == 401


def test_an_unknown_kind_is_400(client: TestClient) -> None:
    r = client.get("/books/inbox", headers={**GOOGLE, "X-Account-Kind": "dropbox"})
    assert r.status_code == 400 and "google" in r.json()["detail"]


def test_shared_books_are_refused_for_google(drive: FakeDrive, client: TestClient) -> None:
    headers = {**GOOGLE, "X-Books-Drive-Id": "b!drive", "X-Books-Item-Id": "ITEM1"}
    r = client.get("/books/inbox", headers=headers)
    assert r.status_code == 400 and r.json()["detail"] == accounts.NO_SHARING
    r = client.get("/accountant/portal", headers={**GOOGLE, "X-User": "owner@example.com"})
    assert r.status_code == 400 and r.json()["detail"] == accounts.NO_SHARING


async def test_identity_is_googles_userinfo(drive: FakeDrive) -> None:
    me = await identity.verified_identity("g-token", None, "google")
    assert me.email == "owner@example.com" and me.name == "Ada Owner"
    await identity.verified_identity("g-token", None, "google")
    assert sum(c == "GET /v1/userinfo" for c in drive.calls) == 1  # remembered, like Graph /me
    with pytest.raises(identity.HTTPException) as refused:
        await identity.verified_identity("forged", None, "google")
    assert refused.value.status_code == 401 and "Google" in refused.value.detail


@pytest.mark.skipif(HAS_WORKSPACE, reason="google_workspace is in this build")
def test_gmail_contacts_are_501_until_google_workspace_lands(drive: FakeDrive, client: TestClient) -> None:
    r = client.get("/contacts/import/outlook", headers=GOOGLE)
    assert r.status_code == 501
    with pytest.raises(Exception) as exc:
        accounts.google_class("GoogleMailProvider")
    assert getattr(exc.value, "status_code", None) == 501


async def test_test_mode_never_calls_google(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import testmode

    monkeypatch.setattr(google_drive, "TRANSPORT", None)
    testmode.install_google_fakes()
    assert google_drive.TRANSPORT is not None
    identity.reset()
    me = await identity.verified_identity("any-test-token", None, "google")
    assert me.email == "sam@example.co.uk"
    identity.reset()
