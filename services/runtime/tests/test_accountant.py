"""Accountant collaboration: invitations and revocation, the Accnomos-accountants opt-in and its consent, the portal,
read-only and edit access to a client's books, client queries, audit identity and cache isolation between clients.

Runs in test mode, where sharing is a FakeSharingWorld (packages/connectors fake.py) with the permission shapes of
Graph's driveItem invite (one permission per grant, roles read or write, inherited downwards)."""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from accnomos_connectors.base import SharedRoot
from accnomos_connectors.fake import FakeStorageProvider
from accnomos_connectors.msgraph import GraphError
from app import accountant, audit_view, portal, sharing, testmode
from app.books import Books
from app.main import read_only_books
from app.routes_accountant import router as accountant_router
from app.routes_audit import router as audit_router
from app.routes_books import router as books_router

OWNER = testmode.OWNER  # the signed-in test user: a client in some tests, the accountant in others
ANA = "ana@firm.example"
HEADERS = {"X-Graph-Token": "test-token", "X-Account-Kind": "personal", "X-User": OWNER}
C1 = {"X-Books-Drive-Id": "c1-drive", "X-Books-Item-Id": "c1-root"}  # Harbour Joinery: view and edit
C2 = {"X-Books-Drive-Id": "c2-drive", "X-Books-Item-Id": "c2-root"}  # Patel Lettings: view only


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", "1")
    monkeypatch.setenv("ACCNOMOS_TEST_TODAY", testmode.DEFAULT_TODAY)
    monkeypatch.delenv(accountant.TEAM_ENV, raising=False)
    app = FastAPI()
    for r in (testmode.router, books_router, accountant_router, audit_router):
        app.include_router(r)
    app.add_exception_handler(sharing.ReadOnlyBooks, read_only_books)  # type: ignore[arg-type]
    c = TestClient(app, headers=HEADERS)
    assert c.post("/__test/reset?seed=accountant").json()["ok"]
    return c


def _world():
    return testmode.current().world


def _own_lines(path: str) -> list[dict]:
    raw = testmode.current().storage.files.get(path, b"")
    return [json.loads(x) for x in raw.decode().splitlines() if x.strip()]


def _client_storage(drive: str, item: str) -> FakeStorageProvider:
    return _world().folders[(drive, item)][2]


# --------------------------------------------------------------------------- #
# Inviting your accountant
# --------------------------------------------------------------------------- #


def test_view_only_invitation_shares_the_folder_read_and_the_queries_folder_write(client: TestClient) -> None:
    r = client.post("/accountant/invitations", json={"email": "Ana@Firm.example", "name": "Ana", "role": "read"})
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["email"] == ANA and inv["method"] == "graph"
    assert [(g["path"], g["role"]) for g in inv["grants"]] == [("", "read"), ("_System/queries", "write")]
    root = testmode.OWN_ROOT
    assert _world().role_of(root, ANA) == "read"
    assert _world().role_of(root, ANA, "_System/queries/abc.json") == "write"
    assert _world().role_of(root, ANA, "_System/Ledger/events/x.json") == "read"
    saved = client.get("/accountant").json()
    assert [i["email"] for i in saved["invitations"]] == [ANA]
    assert saved["client_code"] == "t-drive:t-root"
    assert [ln["action"] for ln in _own_lines("_System/audit/2026-10.jsonl")][-1] == "accountant_invited"


def test_edit_invitation_is_one_write_permission(client: TestClient) -> None:
    inv = client.post("/accountant/invitations", json={"email": ANA, "role": "edit"}).json()
    assert [(g["path"], g["role"]) for g in inv["grants"]] == [("", "write")]
    assert _world().role_of(testmode.OWN_ROOT, ANA, "Books.xlsx") == "write"


def test_the_invitation_email_carries_the_client_code(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(accountant.WEB_ENV, "https://accnomos.example")
    msg = accountant._message("own", OWNER, testmode.OWN_ROOT, "See you Tuesday")
    assert "https://accnomos.example/accountant?client=t-drive:t-root" in msg and "See you Tuesday" in msg


def test_a_second_invitation_to_the_same_email_is_refused(client: TestClient) -> None:
    assert client.post("/accountant/invitations", json={"email": ANA}).status_code == 201
    r = client.post("/accountant/invitations", json={"email": ANA, "role": "edit"})
    assert r.status_code == 409 and "already has access" in r.json()["detail"]


def test_bad_email_and_unknown_fields_are_422(client: TestClient) -> None:
    assert client.post("/accountant/invitations", json={"email": "not-an-email"}).status_code == 422
    assert client.post("/accountant/invitations", json={"email": ANA, "role": "owner"}).status_code == 422
    assert client.post("/accountant/invitations", json={"email": ANA, "extra": 1}).status_code == 422


def test_microsoft_refusing_the_share_records_nothing_and_explains_the_options(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = testmode.sharing

    async def failing(user: str | None):
        p = await real(user)
        p.fail_invite = GraphError(403, "accessDenied")
        return p

    monkeypatch.setattr(testmode, "sharing", failing)
    r = client.post("/accountant/invitations", json={"email": ANA})
    assert r.status_code == 409
    assert "share that folder yourself in OneDrive" in r.json()["detail"] and "work or school" in r.json()["detail"]
    assert client.get("/accountant").json()["invitations"] == []
    assert _world().role_of(testmode.OWN_ROOT, ANA) is None


def test_half_an_invitation_is_undone_when_the_queries_grant_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = testmode.sharing

    async def second_fails(user: str | None):
        p = await real(user)
        original = p.invite

        async def invite(root, email, role, message, path=""):  # noqa: ANN001
            if path:
                raise GraphError(403, "accessDenied")
            return await original(root, email, role, message, path)

        p.invite = invite  # type: ignore[method-assign]
        return p

    monkeypatch.setattr(testmode, "sharing", second_fails)
    assert client.post("/accountant/invitations", json={"email": ANA, "role": "read"}).status_code == 409
    assert _world().role_of(testmode.OWN_ROOT, ANA) is None  # the folder permission was taken back


def test_revoke_removes_every_permission_and_the_accountant_loses_access(client: TestClient) -> None:
    inv = client.post("/accountant/invitations", json={"email": ANA, "role": "read"}).json()
    as_ana = {"X-User": ANA, "X-Books-Drive-Id": "t-drive", "X-Books-Item-Id": "t-root"}
    assert client.get("/queries", headers=as_ana).status_code == 200
    r = client.post(f"/accountant/invitations/{inv['id']}/revoke")
    assert r.status_code == 200 and r.json()["revoked_at"]
    assert _world().permissions[("t-drive", "t-root")] == {}
    assert client.get("/queries", headers=as_ana).status_code == 404
    assert client.post(f"/accountant/invitations/{inv['id']}/revoke").status_code == 200  # twice is harmless
    assert client.post("/accountant/invitations/nope/revoke").status_code == 404
    assert [ln["action"] for ln in _own_lines("_System/audit/2026-10.jsonl")][-1] == "accountant_removed"
    # A new invitation is allowed once the old one is revoked.
    assert client.post("/accountant/invitations", json={"email": ANA}).status_code == 201


def test_a_manual_share_is_recorded_without_calling_graph(client: TestClient) -> None:
    before = list(_world().calls)
    inv = client.post("/accountant/invitations", json={"email": ANA, "method": "manual"}).json()
    assert inv["grants"] == [] and inv["method"] == "manual"
    assert _world().calls == before
    assert client.post(f"/accountant/invitations/{inv['id']}/revoke").json()["revoked_at"]
    assert _world().calls == before


def test_only_the_owner_manages_access(client: TestClient) -> None:
    for call in (
        lambda: client.get("/accountant", headers={**C1, "X-Books-Access": "edit"}),
        lambda: client.post(
            "/accountant/invitations", json={"email": "x@y.example"}, headers={**C1, "X-Books-Access": "edit"}
        ),
        lambda: client.put("/accountant/profile", json={"name": "Hacked"}, headers={**C1, "X-Books-Access": "edit"}),
    ):
        assert call().status_code == 403


def test_profile_is_saved_in_the_books(client: TestClient) -> None:
    body = {"name": "Sam Builds", "kind": "sole_trader", "vat_registered": True, "vat_start_month": 2, "vat_months": 3}
    assert client.put("/accountant/profile", json=body).status_code == 200
    stored = json.loads(testmode.current().storage.files["_System/accountant.json"])
    assert stored["profile"]["kind"] == "sole_trader" and stored["profile"]["vat_start_month"] == 2


# --------------------------------------------------------------------------- #
# Reviews by Accnomos accountants
# --------------------------------------------------------------------------- #


def test_team_option_is_hidden_without_the_server_setting(client: TestClient) -> None:
    s = client.get("/accountant").json()
    assert s["team_available"] is False and s["team_email"] is None
    r = client.post("/accountant/team", json={"agree": True, "consent_version": accountant.CONSENT_VERSION})
    assert r.status_code == 404


def test_team_opt_in_needs_explicit_agreement_to_the_current_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(accountant.TEAM_ENV, "Reviews@Accnomos.example")
    s = client.get("/accountant").json()
    assert s["team_available"] and s["team_email"] == "reviews@accnomos.example"
    text = " ".join(s["consent_text"])
    for must in (
        "reviews@accnomos.example",
        "see everything",
        "View only",
        "change nothing",
        "Stop reviews",
        "never submit",
    ):
        assert must.lower() in text.lower(), must
    assert (
        client.post("/accountant/team", json={"agree": False, "consent_version": s["consent_version"]}).status_code
        == 409
    )
    assert client.post("/accountant/team", json={"agree": True, "consent_version": "2020-01-01"}).status_code == 409
    assert _world().role_of(testmode.OWN_ROOT, "reviews@accnomos.example") is None

    r = client.post("/accountant/team", json={"agree": True, "consent_version": s["consent_version"], "role": "read"})
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["kind"] == "team" and inv["consent"]["version"] == accountant.CONSENT_VERSION
    assert inv["consent"]["text_sha256"] == accountant.consent_sha256() and inv["consent"]["agreed_by"] == OWNER
    assert _world().role_of(testmode.OWN_ROOT, "reviews@accnomos.example") == "read"

    out = client.delete("/accountant/team")
    assert out.status_code == 200 and out.json()["revoked_at"]
    assert _world().role_of(testmode.OWN_ROOT, "reviews@accnomos.example") is None
    assert client.delete("/accountant/team").status_code == 404
    actions = [ln["action"] for ln in _own_lines("_System/audit/2026-10.jsonl")]
    assert actions[-2:] == ["accountant_team_opted_in", "accountant_team_opted_out"]


# --------------------------------------------------------------------------- #
# The portal
# --------------------------------------------------------------------------- #


def test_portal_lists_shared_books_folders_with_their_summary(client: TestClient) -> None:
    p = client.get("/accountant/portal").json()
    assert p["shared_with_me_ok"] is True
    by_name = {c["name"]: c for c in p["clients"]}
    assert set(by_name) == {"Harbour Joinery Ltd", "Patel Lettings"}  # the shared Photos folder is not books
    hj, pl = by_name["Harbour Joinery Ltd"], by_name["Patel Lettings"]
    assert (hj["kind"], hj["access"], hj["review_waiting"], hj["source"]) == ("business", "edit", 1, "shared_with_me")
    assert hj["vat"] == {"period": "Jul–Sep 2026", "due": "2026-11-07", "days_left": 11}
    assert pl["kind"] == "landlord" and pl["access"] == "read" and pl["vat"] is None and pl["vat_registered"] is False
    assert (pl["open_queries"], pl["waiting_on_client"], pl["waiting_on_you"]) == (1, 1, 0)
    assert hj["last_activity"].startswith("2026-")
    assert p["clients"][0]["name"] == "Harbour Joinery Ltd"  # soonest VAT deadline first


def test_portal_keeps_working_when_shared_with_me_stops(client: TestClient) -> None:
    _world().shared_with_me_works = False  # Microsoft: no data after November 2026
    assert client.get("/accountant/portal").json()["clients"] == []
    r = client.post(
        "/accountant/portal/clients", json={"code": "https://app.example/accountant?client=c2-drive:c2-root"}
    )
    assert r.status_code == 201, r.text
    p = client.get("/accountant/portal").json()
    assert [(c["name"], c["source"]) for c in p["clients"]] == [("Patel Lettings", "added")]
    saved = json.loads(testmode.current().storage.files[portal.CLIENTS])  # in the accountant's own books
    assert [(x["drive_id"], x["item_id"]) for x in saved] == [("c2-drive", "c2-root")]
    assert client.delete("/accountant/portal/clients/c2-drive:c2-root").json() == {"removed": True}
    assert client.delete("/accountant/portal/clients/c2-drive:c2-root").status_code == 404


def test_adding_a_client_code_checks_it(client: TestClient) -> None:
    assert client.post("/accountant/portal/clients", json={"code": "nonsense"}).status_code == 400
    assert client.post("/accountant/portal/clients", json={"code": "zz-drive:zz-root"}).status_code == 404
    r = client.post("/accountant/portal/clients", json={"code": "c1-drive:c1-photos"})  # shared, but not books
    assert r.status_code == 400 and "not a set of Accnomos books" in r.json()["detail"]


def test_a_client_who_stops_sharing_shows_as_an_error_not_a_crash(client: TestClient) -> None:
    client.post("/accountant/portal/clients", json={"code": "c1-drive:c1-root"})
    _world().permissions[("c1-drive", "c1-root")].clear()
    p = client.get("/accountant/portal").json()
    hj = next(c for c in p["clients"] if c["drive_id"] == "c1-drive")
    assert hj["error"] == "No longer shared with you." and hj["source"] == "added"


def test_parse_code_accepts_codes_and_links_only() -> None:
    assert portal.parse_code("b!x_Y-1:01ABC!7") == SharedRoot(drive_id="b!x_Y-1", item_id="01ABC!7")
    assert portal.parse_code("https://a.example/accountant?x=1&client=d%3Ai%21j") == SharedRoot(
        drive_id="d", item_id="i!j"
    )
    for bad in ("d/..:i", "d:i/x", ":i", "d:", "d:i:j"):
        with pytest.raises(ValueError):
            portal.parse_code(bad)


def test_next_vat_deadline_rolls_on_once_the_last_return_is_due() -> None:
    prof = accountant.ClientProfile(vat_start_month=1, vat_months=3)
    assert portal.next_vat_deadline(prof, date(2026, 11, 7)).due == date(2026, 11, 7)
    later = portal.next_vat_deadline(prof, date(2026, 11, 8))
    assert (later.period, later.due) == ("Oct–Dec 2026", date(2027, 2, 7))
    monthly = portal.next_vat_deadline(accountant.ClientProfile(vat_months=1), date(2026, 10, 27))
    assert (monthly.period, monthly.due) == ("Sep 2026", date(2026, 11, 7))


# --------------------------------------------------------------------------- #
# Opening a client: the same pages against the shared folder
# --------------------------------------------------------------------------- #


def test_the_same_routes_read_the_clients_books(client: TestClient) -> None:
    own = client.get("/books/proposals").json()
    theirs = client.get("/books/proposals", headers=C1).json()
    assert [p["id"] for p in theirs] == ["5eed0001"] and "5eed0001" not in [p["id"] for p in own]


def test_read_only_view_refuses_writes_but_queries_still_work(client: TestClient) -> None:
    r = client.post("/books/proposals/5eed0002/reject", json={"reason": "no"}, headers=C2)
    assert r.status_code == 403 and "read-only" in r.json()["detail"]
    stored = json.loads(_client_storage("c2-drive", "c2-root").files["_System/proposals/5eed0002.json"])
    assert stored["status"] == "proposed"
    # Opened read-only even though the client gave edit access: still refused.
    assert client.post("/books/proposals/5eed0001/reject", json={"reason": "no"}, headers=C1).status_code == 403
    # Asking for edit where the client gave view only: refused by the permission itself.
    assert (
        client.post("/books/proposals/5eed0002/reject", json={}, headers={**C2, "X-Books-Access": "edit"}).status_code
        == 403
    )
    q = client.post(
        "/queries", json={"subject": {"kind": "proposal", "ref": "5eed0002"}, "text": "Receipt?"}, headers=C2
    )
    assert q.status_code == 201, q.text
    files = _client_storage("c2-drive", "c2-root").files
    lines = [json.loads(x) for x in files["_System/queries/audit/2026-10.jsonl"].decode().splitlines()]
    assert lines[-1]["actor"] == f"accountant:{OWNER}" and lines[-1]["action"] == "query_opened"


def test_edit_view_writes_and_audits_under_the_accountants_identity(client: TestClient) -> None:
    edit = {**C1, "X-Books-Access": "edit", "X-User": OWNER}
    r = client.post("/books/proposals/5eed0001/reject", json={"reason": "Personal purchase"}, headers=edit)
    assert r.status_code == 200, r.text
    raw = _client_storage("c1-drive", "c1-root").files["_System/audit/2026-10.jsonl"].decode().splitlines()
    last = json.loads(raw[-1])
    assert last["actor"] == f"accountant:{OWNER}" and last["action"] == "rejected"
    audit = client.get("/audit?actor=accountant&from=2026-10-01&to=2027-06-30", headers=C1).json()["entries"]
    assert audit and audit[0]["actor_kind"] == "accountant" and audit[0]["actor_label"] == f"Accountant ({OWNER})"


def test_a_folder_not_shared_with_you_is_404_and_bad_headers_400(client: TestClient) -> None:
    assert (
        client.get("/books/proposals", headers={"X-Books-Drive-Id": "zz", "X-Books-Item-Id": "zz"}).status_code == 404
    )
    assert client.get("/books/proposals", headers={"X-Books-Drive-Id": "c1-drive"}).status_code == 400
    assert client.get("/books/proposals", headers={**C1, "X-Books-Item-Id": "../c2-root"}).status_code == 400
    assert client.get("/books/proposals", headers={**C1, "X-Books-Access": "owner"}).status_code == 400
    # Another person (not invited) cannot open Harbour Joinery's books.
    assert client.get("/books/proposals", headers={**C1, "X-User": "mallory@evil.example"}).status_code == 404


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #


def test_a_query_thread_between_accountant_and_client(client: TestClient) -> None:
    edit = {**C1, "X-Books-Access": "edit"}
    q = client.post(
        "/queries",
        json={
            "subject": {"kind": "transaction", "ref": "evt-1", "label": "Screwfix  £12.00"},
            "text": " What was this for? ",
        },
        headers=edit,
    ).json()
    assert (
        q["waiting_on"] == "client"
        and q["messages"][0]["role"] == "accountant"
        and q["messages"][0]["text"] == "What was this for?"
    )
    assert q["subject"]["label"] == "Screwfix £12.00"
    # The client (Jo, in their own books) sees it as waiting on them.
    jo = {"X-User": "jo@harbourjoinery.example"}
    testmode.current().storage, saved = _client_storage("c1-drive", "c1-root"), testmode.current().storage
    try:
        todo = client.get("/queries?waiting_on=client", headers=jo).json()
        assert [t["id"] for t in todo] == [q["id"]]
        after = client.post(
            f"/queries/{q['id']}/messages", json={"text": "Screws for the Harbour Lane job"}, headers=jo
        ).json()
        assert after["waiting_on"] == "accountant" and after["messages"][-1]["role"] == "client"
    finally:
        testmode.current().storage = saved
    done = client.post(f"/queries/{q['id']}/resolve", headers=edit).json()
    assert done["status"] == "resolved" and done["waiting_on"] is None and done["resolved_by"] == OWNER
    assert client.get("/queries?status=open", headers=C1).json() == []
    again = client.post(f"/queries/{q['id']}/messages", json={"text": "One more thing"}, headers=edit).json()
    assert again["status"] == "open"  # a reply reopens it


def test_query_ids_never_become_paths(client: TestClient) -> None:
    for bad in ("..%2Faccountant", "abc", "ZZZZZZZZZZZZ", "a1b2c3d4e5f6.json"):
        assert client.get(f"/queries/{bad}", headers=C2).status_code in (404, 405)
        assert client.post(f"/queries/{bad}/messages", json={"text": "x"}, headers=C2).status_code in (404, 405)
    assert client.get("/queries/a1b2c3d4e5f6", headers=C2).json()["subject"]["label"] == "October rent receipt"
    assert client.post("/queries", json={"text": "   "}, headers=C2).status_code == 422


def test_audit_kinds_have_sentences_and_accountant_actor() -> None:
    for kind in (
        "accountant_invited", "accountant_removed", "accountant_team_opted_in", "accountant_team_opted_out",
        "accountant_profile_saved", "accountant_client_added", "accountant_client_removed",
        "query_opened", "query_replied", "query_resolved",
    ):  # fmt: skip
        assert kind in audit_view.SUMMARIES
    refs = {"email": ANA, "role": "edit", "method": "manual"}
    assert audit_view.summarise("accountant_invited", refs, "") == (
        f"Gave {ANA} view and edit access to these books (shared in OneDrive by hand)"
    )
    assert audit_view.summarise("query_opened", {"about": "bank_line"}, "") == "Asked a query about a bank line"
    assert audit_view.actor_of(f"accountant:{ANA}") == ("accountant", f"Accountant ({ANA})")


# --------------------------------------------------------------------------- #
# Never mix clients' caches
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_immutable_cache_is_per_client_even_with_one_token() -> None:
    from app import cache

    cache.clear()
    path = "_System/Ledger/events/2026-10/e1.json"
    a, b, own = FakeStorageProvider(), FakeStorageProvider(), FakeStorageProvider()
    await a.write(path, b'{"client": "A"}')
    await b.write(path, b'{"client": "B"}')
    await own.write(path, b'{"client": "own"}')
    ra, rb = SharedRoot(drive_id="da", item_id="ia"), SharedRoot(drive_id="db", item_id="ib")
    keys = {sharing.client_cache_key("tok", ra), sharing.client_cache_key("tok", rb), cache.user_cache_key("tok")}
    assert len(keys) == 3
    for _ in range(2):  # the second round would be served from the cache
        assert await Books(a, cache_key=sharing.client_cache_key("tok", ra)).storage.read(path) == b'{"client": "A"}'
        assert await Books(b, cache_key=sharing.client_cache_key("tok", rb)).storage.read(path) == b'{"client": "B"}'
        assert await Books(own, cache_key=cache.user_cache_key("tok")).storage.read(path) == b'{"client": "own"}'
    # With B's storage emptied, B's key serves only what was cached for B, never A's bytes.
    b.files.clear()
    assert await Books(b, cache_key=sharing.client_cache_key("tok", rb)).storage.read(path) == b'{"client": "B"}'
    other = SharedRoot(drive_id="dc", item_id="ic")  # a third client never read before: storage, not the cache
    with pytest.raises(FileNotFoundError):
        await Books(FakeStorageProvider(), cache_key=sharing.client_cache_key("tok", other)).storage.read(path)
    cache.clear()


def test_portal_summaries_do_not_leak_between_clients(client: TestClient) -> None:
    p = {c["drive_id"]: c for c in client.get("/accountant/portal").json()["clients"]}
    assert p["c1-drive"]["open_queries"] == 0 and p["c2-drive"]["open_queries"] == 1
    c1 = [x["id"] for x in client.get("/queries", headers=C1).json()]
    c2 = [x["id"] for x in client.get("/queries", headers=C2).json()]
    assert c1 == [] and c2 == ["a1b2c3d4e5f6"]


@pytest.mark.asyncio
async def test_read_only_storage_allows_only_the_queries_folder() -> None:
    inner = FakeStorageProvider()
    ro = sharing.ReadOnlyStorage(inner)
    await ro.write("_System/queries/a1b2c3d4e5f6.json", b"{}")
    await ro.ensure_folder("_System/queries/audit")
    for bad in ("Books.xlsx", "_System/queriesX/a.json", "_System/accountant.json", "_System/Ledger/events/x.json"):
        with pytest.raises(sharing.ReadOnlyBooks):
            await ro.write(bad, b"x")
    with pytest.raises(sharing.ReadOnlyBooks):
        await ro.move("_System/queries/a1b2c3d4e5f6.json", "_System/queries/b.json")
    with pytest.raises(sharing.ReadOnlyBooks):
        await ro.ensure_folder("01 Receipts")


@pytest.mark.asyncio
async def test_a_graph_403_inside_a_clients_books_is_403_not_sign_in_again() -> None:
    from starlette.requests import Request

    from app.main import graph_error

    def request(headers: dict[str, str]) -> Request:
        raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
        return Request({"type": "http", "method": "POST", "path": "/", "headers": raw})

    shared = await graph_error(request(C2), GraphError(403, "accessDenied"))
    assert shared.status_code == 403 and b"view-only" in shared.body
    own = await graph_error(request({}), GraphError(403, "accessDenied"))
    assert own.status_code == 401  # your own books: the token lacks a scope, sign in again


def test_cors_lets_the_browser_send_the_client_headers() -> None:
    """A browser preflights X-Books-*; Playwright answers preflights itself when it routes requests, so the e2e
    suite cannot catch a missing header here."""
    from app.main import app

    r = TestClient(app).options(
        "/books/proposals",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-graph-token,x-books-drive-id,x-books-item-id,x-books-access",
        },
    )
    assert r.status_code == 200, r.text
    allowed = r.headers["access-control-allow-headers"].lower()
    for h in ("x-books-drive-id", "x-books-item-id", "x-books-access"):
        assert h in allowed
