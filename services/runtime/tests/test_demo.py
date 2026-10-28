"""The demo sandbox (app/demo.py): sessions, isolation, limits, and that nothing in a demo reaches Graph, Outlook or
HMRC. The snapshot here is a small stand-in; the real seed (tools/seed_demo.py) has its own tests and the web e2e
(apps/web/e2e/sandbox.spec.ts) runs the real one."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app import demo, routes_books, routes_contacts, routes_invoices, routes_mail, routes_plan, security, testmode
from app.ai.config import is_test_mode
from app.books import INBOX
from app.routes_actions import _mail_sender, graph_token
from app.routes_books import get_books
from app.routes_books import router as books_router
from app.routes_contacts import get_address_book
from app.routes_invoices import get_sender
from app.routes_lookup import router as lookup_router
from app.routes_mail import get_mail
from app.routes_plan import get_calendar

SECRET = "s" * 40
G = "/demo/graph/v1.0/me/drive/special/approot"
built: list[date] = []  # days the stand-in seed ran for


async def small_build(day: date) -> demo.Snapshot:
    """A stand-in for the full seed: a few files, one in 00 Inbox."""
    built.append(day)
    st = FakeStorageProvider()
    await st.write("README.txt", b"SAMPLE - FICTIONAL COMPANY")
    await st.write(f"{INBOX}/SAMPLE 01.png", b"\x89PNG sample")
    await st.ensure_folder("_System/Ledger/events")
    return demo.Snapshot(day, st, "Bramblewood Joinery Ltd", 0.01)


@pytest.fixture
def demo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DEMO_SECRET", SECRET)
    monkeypatch.delenv("ACCNOMOS_TEST_MODE", raising=False)
    monkeypatch.setattr(demo, "BUILD", small_build)
    monkeypatch.setattr(demo, "CREATE_LIMITER", None)
    built.clear()
    demo.reset_for_tests()
    yield
    demo.reset_for_tests()


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(demo.router)
    app.include_router(books_router)
    app.include_router(lookup_router)

    @app.exception_handler(demo.DemoLimit)
    async def limit(_r, exc: demo.DemoLimit) -> JSONResponse:  # noqa: ANN001
        return JSONResponse(status_code=413, content={"detail": str(exc)})

    return app


@pytest.fixture
def client(demo_env: None) -> TestClient:
    return TestClient(_app())


def _start(client: TestClient, **headers: str) -> dict[str, str]:
    r = client.post("/demo/session", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["label"] == "SAMPLE — FICTIONAL COMPANY" and body["business"] == "Bramblewood Joinery Ltd"
    return {demo.HEADER: body["session"], "X-User": demo.USER}


def _names(client: TestClient, h: dict[str, str], folder: str = INBOX) -> set[str]:
    r = client.get(f"{G}:/{folder}:/children", headers=h)
    assert r.status_code == 200, r.text
    return {i["name"] for i in r.json()["value"]}


# --------------------------------------------------------------------------- #
# Switching it on
# --------------------------------------------------------------------------- #


def test_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert not demo.enabled()


@pytest.mark.parametrize("secret", [None, "", "short-secret"])
def test_refused_without_a_demo_secret(monkeypatch: pytest.MonkeyPatch, secret: str | None) -> None:
    monkeypatch.setenv("DEMO_MODE", "1")
    if secret is None:
        monkeypatch.delenv("DEMO_SECRET", raising=False)
    else:
        monkeypatch.setenv("DEMO_SECRET", secret)
    before = security.UNLIMITED_PREFIXES
    with pytest.raises(RuntimeError, match="DEMO_SECRET"):
        demo.enable()
    assert before == security.UNLIMITED_PREFIXES  # nothing was switched on


def test_a_demo_header_never_falls_back_to_graph_when_demo_mode_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setattr(routes_books, "GraphStorageProvider", _boom)
    r = TestClient(_app()).get("/books/proposals", headers={demo.HEADER: "x.y", "X-Graph-Token": "real-token"})
    assert r.status_code == 401 and "isn't switched on" in r.json()["detail"]


def test_the_image_guard_on_test_mode_is_untouched(demo_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Demo mode is allowed in the runtime image; test mode still is not, and demo mode never turns it on."""
    monkeypatch.setenv("ACCNOMOS_IMAGE", "1")
    monkeypatch.setattr(security, "UNLIMITED_PREFIXES", ())
    demo.enable()
    assert security.UNLIMITED_PREFIXES == ("/demo/graph/",)
    assert not is_test_mode()
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", "1")
    with pytest.raises(RuntimeError, match="refused in the runtime image"):
        testmode.enable()


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #


def test_a_session_starts_on_the_sample_books_and_is_signed(client: TestClient) -> None:
    h = _start(client)
    token = h[demo.HEADER]
    raw, _, sig = token.partition(".")
    assert len(raw) >= 32 and len(sig) == 32 and demo.unsign(token) == raw
    assert _names(client, h) == {"SAMPLE 01.png"}
    assert client.get("/demo/session", headers=h).json()["idle_ttl_s"] == 7200
    assert client.get("/books/proposals", headers=h).json() == []


@pytest.mark.parametrize("token", ["", "nonsense", "abc.def", "a" * 32 + "." + "0" * 32])
def test_forged_or_unknown_sessions_are_refused(client: TestClient, token: str) -> None:
    _start(client)
    for path in ("/demo/session", "/books/proposals", f"{G}/children"):
        assert client.get(path, headers={demo.HEADER: token}).status_code == 401


def test_a_token_signed_with_another_secret_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    h = _start(client)
    monkeypatch.setenv("DEMO_SECRET", "t" * 40)
    assert client.get("/demo/session", headers=h).status_code == 401


def test_two_sessions_never_see_each_others_writes(client: TestClient) -> None:
    a, b = _start(client), _start(client)
    put = client.put(f"{G}:/{INBOX}/mine.png:/content", content=b"\x89PNG a", headers=a)
    assert put.status_code == 201, put.text
    assert _names(client, a) == {"SAMPLE 01.png", "mine.png"}
    assert _names(client, b) == {"SAMPLE 01.png"}
    assert client.get(f"{G}:/{INBOX}/mine.png:/content", headers=b).status_code == 404
    # The books side (get_books) too: a rule saved in A is not in B, nor in a session started afterwards.
    client.post("/books/rebuild", headers=a)
    assert any(f.startswith("Books") for f in _names(client, a, ""))
    assert not any(f.startswith("Books") for f in _names(client, b, ""))
    c = _start(client)
    assert _names(client, c) == {"SAMPLE 01.png"}
    assert built == [built[0]]  # seeded once; every session is a copy


def test_reset_drops_the_old_session_and_starts_a_fresh_one(client: TestClient) -> None:
    a = _start(client)
    client.put(f"{G}:/{INBOX}/mine.png:/content", content=b"x", headers=a)
    fresh = _start(client, **{demo.HEADER: a[demo.HEADER]})
    assert client.get("/demo/session", headers=a).status_code == 401
    assert _names(client, fresh) == {"SAMPLE 01.png"}


def test_leaving_the_demo_ends_the_session(client: TestClient) -> None:
    h = _start(client)
    assert client.delete("/demo/session", headers=h).status_code == 204
    assert client.get("/books/proposals", headers=h).status_code == 401
    assert len(demo.STORE) == 0


def _session(sid: str, limits: demo.Limits, t: float, added: int = 0) -> demo.DemoSession:
    st = demo.DemoStorage(None, limits)
    st.added_bytes = added
    return demo.DemoSession(
        id=sid,
        storage=st,
        mail=demo._mailbox(),
        sender=demo.FakeMailSender(),
        contacts=demo.FakeContactsProvider(),
        calendar=demo._calendar(date(2026, 10, 27)),
        business="B",
        today=date(2026, 10, 27),
        created=t,
        last_used=t,
    )


def test_idle_sessions_expire_after_the_ttl() -> None:
    now = [0.0]
    store = demo.SessionStore(demo.Limits(idle_ttl_s=7200), clock=lambda: now[0])
    store.add(_session("a", store.limits, 0))
    now[0] = 7000
    assert store.get("a") is not None  # used: the idle clock starts again
    now[0] = 7000 + 7199
    assert store.get("a") is not None
    now[0] += 7201
    assert store.get("a") is None and len(store) == 0


def test_least_recently_used_sessions_go_first_past_the_cap() -> None:
    now = [0.0]
    store = demo.SessionStore(demo.Limits(max_sessions=2), clock=lambda: now[0])
    store.add(_session("a", store.limits, 0))
    store.add(_session("b", store.limits, 0))
    store.get("a")  # b is now the least recently used
    store.add(_session("c", store.limits, 0))
    assert list(store.sessions) == ["a", "c"] and store.evicted == 1


def test_all_sessions_added_bytes_are_capped() -> None:
    store = demo.SessionStore(demo.Limits(total_bytes=100), clock=lambda: 0.0)
    store.add(_session("a", store.limits, 0, added=60))
    store.add(_session("b", store.limits, 0, added=60))  # over 100 together: the older one goes
    assert list(store.sessions) == ["b"]


async def test_storage_limits() -> None:
    lim = demo.Limits(file_bytes=10, session_files=2, session_bytes=15)
    base = FakeStorageProvider()
    await base.write("big.bin", b"x" * 500)  # the snapshot's own bytes never count
    st = demo.DemoStorage(base, lim)
    with pytest.raises(demo.DemoLimit, match="10 MB|limited"):
        await st.write("a", b"x" * 11)
    await st.write("a", b"x" * 10)
    await st.write("a", b"y" * 10)  # overwriting is not a new file and adds nothing
    with pytest.raises(demo.DemoLimit, match="MB of new files"):
        await st.write("b", b"x" * 6)
    await st.write("b", b"x" * 5)
    with pytest.raises(demo.DemoLimit, match="new files"):
        await st.write("c", b"")
    assert (st.added_files, st.added_bytes) == (2, 15)
    assert "a" not in base.files  # the snapshot is untouched


def test_an_upload_over_the_limit_is_a_413(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo, "LIMITS", demo.Limits(file_bytes=4))
    h = _start(client)
    r = client.put(f"{G}:/{INBOX}/big.png:/content", content=b"12345", headers=h)
    assert r.status_code == 413


def test_session_starts_are_rate_limited_per_ip(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo, "CREATE_LIMITER", security.TokenBucket(2))
    _start(client)
    _start(client)
    r = client.post("/demo/session")
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1


def test_graph_calls_are_rate_limited_per_session(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo, "GRAPH_LIMITER", security.TokenBucket(1))
    a, b = _start(client), _start(client)
    assert client.get(f"{G}/children", headers=a).status_code == 200
    assert client.get(f"{G}/children", headers=a).status_code == 429
    assert client.get(f"{G}/children", headers=b).status_code == 200  # another session has its own budget


def test_a_failed_seed_is_a_503_and_retried(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(day: date) -> demo.Snapshot:
        raise ValueError("gold set missing")

    monkeypatch.setattr(demo, "BUILD", broken)
    r = client.post("/demo/session")
    assert r.status_code == 503 and "gold" not in r.text
    monkeypatch.setattr(demo, "BUILD", small_build)
    _start(client)


def test_seeding_starts_on_the_first_health_check(demo_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "UNLIMITED_PREFIXES", ())
    demo.enable()
    assert demo._builds == {}  # importing the app never waits on, or competes with, the seed
    assert demo.status()["ready"] is False
    (b,) = demo._builds.values()
    assert b.done.wait(30) and demo.status()["ready"] is True and len(built) == 1


async def test_waiters_share_one_build(demo_env: None) -> None:
    day = date(2026, 10, 27)
    snaps = await asyncio.gather(*(demo.snapshot(day) for _ in range(5)))
    assert built == [day] and all(s is snaps[0] for s in snaps)


# --------------------------------------------------------------------------- #
# Nothing real is reachable from a demo
# --------------------------------------------------------------------------- #


def _boom(*_a: object, **_k: object) -> None:
    raise AssertionError("a demo request built a Microsoft Graph client")


class _Req:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


async def test_no_graph_mail_or_calendar_client_is_built_in_a_demo(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for mod, name in (
        (routes_books, "GraphStorageProvider"),
        (routes_mail, "GraphMailProvider"),
        (routes_contacts, "GraphContactsProvider"),
        (routes_plan, "GraphCalendarProvider"),
        (routes_invoices, "GraphMailSender"),
    ):
        monkeypatch.setattr(mod, name, _boom)
    h = _start(client)
    # A Graph token sent alongside is ignored: the demo header wins, so it can never reach a real OneDrive.
    req = _Req({**h, "X-Graph-Token": "a-real-looking-token"})
    s = demo.require(req)  # type: ignore[arg-type]

    books = await get_books(req).__anext__()  # type: ignore[arg-type]
    assert getattr(books.storage, "inner", books.storage) is s.storage
    assert await get_mail(req).__anext__() is s.mail  # type: ignore[arg-type]
    assert await get_address_book(req).__anext__() is s.contacts  # type: ignore[arg-type]
    assert await get_calendar(req).__anext__() is s.calendar  # type: ignore[arg-type]
    sender = await get_sender(req).__anext__()  # type: ignore[arg-type]
    assert sender is s.sender
    assert _mail_sender("ignored", req)() is s.sender  # type: ignore[arg-type]
    assert graph_token(req) == s.token_key  # type: ignore[arg-type]

    # The sender only records: nothing is sent.
    from accnomos_connectors.base import OutgoingMail

    await sender.send(OutgoingMail(to="someone@example.com", subject="Invoice", body_text="Hi", attachments=[]))
    assert [m.to for m in s.sender.sent] == ["someone@example.com"]

    # Everything in a demo is answered from memory; the routes run with the Graph clients broken.
    for path in ("/books/proposals", "/books/summary", "/books/rules"):
        assert client.get(path, headers=h).status_code == 200, path


def test_lookups_are_refused_in_a_demo(client: TestClient) -> None:
    """Companies House and HMRC's VAT-number check are external calls: a demo never makes them."""
    h = _start(client)
    for path in ("/lookup/companies?q=Bramblewood", "/lookup/vat/GB123456789"):
        r = client.get(path, headers=h)
        assert r.status_code == 403 and "demo sandbox" in r.json()["detail"]


def test_demo_session_header_is_a_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "x-demo-session" in security.SECRET_HEADERS
    assert "abc123" not in security.scrub("X-Demo-Session: abc123def456")


async def test_require_without_a_header_is_401(demo_env: None) -> None:
    with pytest.raises(HTTPException) as exc:
        demo.require(_Req({}))  # type: ignore[arg-type]
    assert exc.value.status_code == 401
