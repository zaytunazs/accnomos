"""Who a request is (app/identity.py): Graph `/me` for the token, never the `X-User` the client wrote."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors.base import Identity
from accnomos_connectors.fake import FakeStorageProvider
from accnomos_connectors.msgraph import GraphError
from app import identity, sharing
from app.books import Books
from app.main import app
from app.routes_books import get_books

pytestmark = pytest.mark.real_identity

ME = {"good-token": Identity(email="real.person@example.co.uk", name="Real Person")}


class FakeGraphMe:
    calls = 0

    def __init__(self, token: str) -> None:
        self.token = token

    async def whoami(self) -> Identity:
        FakeGraphMe.calls += 1
        if self.token not in ME:
            raise GraphError(401, "InvalidAuthenticationToken")
        return ME[self.token]

    async def aclose(self) -> None: ...


@pytest.fixture(autouse=True)
def fake_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    async def graph_for(token: str, user: str | None = None) -> FakeGraphMe:
        return FakeGraphMe(token)

    monkeypatch.setattr(sharing, "sharing_for", graph_for)
    monkeypatch.delenv("ACCNOMOS_TEST_MODE", raising=False)
    FakeGraphMe.calls = 0
    identity.reset()
    yield
    identity.reset()


async def test_verified_identity_remembers_by_token_for_ten_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    me = await identity.verified_identity("Bearer good-token", hint="someone.else@example.com")
    assert me.email == "real.person@example.co.uk"  # the hint is never read outside test mode
    await identity.verified_identity("good-token")
    assert FakeGraphMe.calls == 1
    assert all(len(k) == 64 and "good-token" not in k for k in identity._CACHE)  # a hash, not the token
    now = identity.time.monotonic()
    monkeypatch.setattr(identity.time, "monotonic", lambda: now + identity.TTL_SECONDS + 1)
    await identity.verified_identity("good-token")
    assert FakeGraphMe.calls == 2


async def test_a_refused_token_is_401_and_not_remembered() -> None:
    for _ in range(2):
        with pytest.raises(identity.HTTPException) as exc:
            await identity.verified_identity("forged")
        assert exc.value.status_code == 401
    assert FakeGraphMe.calls == 2 and not identity._CACHE
    with pytest.raises(identity.HTTPException) as blank:
        await identity.verified_identity("  ")
    assert blank.value.status_code == 401


async def test_the_cache_is_bounded() -> None:
    for i in range(identity._MAX + 20):
        ME[f"t{i}"] = Identity(email=f"u{i}@example.co.uk")
    try:
        for i in range(identity._MAX + 20):
            await identity.verified_identity(f"t{i}")
    finally:
        for i in range(identity._MAX + 20):
            ME.pop(f"t{i}")
    assert len(identity._CACHE) == identity._MAX


def test_the_audit_actor_is_the_verified_identity_not_x_user() -> None:
    fake = FakeStorageProvider()
    app.dependency_overrides[get_books] = lambda: Books(fake)
    try:
        client = TestClient(app)
        r = client.post(
            "/todos",
            json={"text": "Ring Hartley"},
            headers={"X-Graph-Token": "good-token", "X-User": "boss@victim.example"},
        )
        assert r.status_code in (200, 201), r.text
        forged = client.post(
            "/todos",
            json={"text": "Ring Hartley"},
            headers={"X-Graph-Token": "forged", "X-User": "boss@victim.example"},
        )
        assert forged.status_code == 401
    finally:
        app.dependency_overrides.clear()
    lines = [x for p, d in fake.files.items() if "audit" in p for x in d.decode().splitlines()]
    assert lines, "the to-do was audited"
    assert all('"actor": "user:real.person@example.co.uk"' in x and "victim" not in x for x in lines), lines


async def test_test_mode_answers_from_the_fakes_without_calling_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # the autouse fake_graph patch must not be what answers
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", "1")
    from app import testmode

    me = await identity.verified_identity("test-token", "Sam@Example.co.uk")
    assert me.email == "sam@example.co.uk"
    assert (await identity.verified_identity("test-token")).email == testmode.OWNER
    assert FakeGraphMe.calls == 0


def _request(headers: dict[str, str]):  # noqa: ANN202
    from starlette.requests import Request

    return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})


async def test_optional_user_is_the_verified_identity_or_none() -> None:
    from app.routes_books import optional_user

    good = _request({"X-Graph-Token": "good-token", "X-User": "boss@victim.example"})
    assert await optional_user(good, "boss@victim.example") == "real.person@example.co.uk"
    forged = _request({"X-Graph-Token": "forged", "X-User": "boss@victim.example"})
    assert await optional_user(forged, "boss@victim.example") is None  # never the unchecked header
    assert await optional_user(_request({"X-User": "x@example.com"}), "x@example.com") is None  # no token
    assert await optional_user(_request({"X-Graph-Token": "good-token"}), None) is None  # no X-User: nobody named
    assert FakeGraphMe.calls == 2


async def test_optional_user_when_graph_cannot_be_reached_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.routes_books import optional_user

    async def down(token: str, user: str | None = None) -> FakeGraphMe:
        raise GraphError(503, "serviceNotAvailable")

    monkeypatch.setattr(sharing, "sharing_for", down)
    assert await optional_user(_request({"X-Graph-Token": "good-token"}), "a@example.com") is None
