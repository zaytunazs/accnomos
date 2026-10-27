"""Duplicate routes: candidates with evidence and the model's view, dismiss, merge, undo."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app import contacts as cb
from app.autopilot import supplier_key
from app.books import AUDIT, Books

USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}


def _contact(cid: str, name: str, **kw: Any) -> cb.Contact:
    base: dict[str, Any] = {"kind": "supplier", "name": name, "normalised_key": supplier_key(name)}
    base.update(kw)
    return cb.Contact(id=cid, **base)


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
async def books(fake: FakeStorageProvider) -> Books:
    b = Books(fake)
    await cb.save_contacts(
        b,
        [
            _contact("a" * 16, "Screwfix", email="trade@screwfix.com"),
            _contact("b" * 16, "SCREWFIX DIRECT LTD", email="Trade@Screwfix.com", phone="0117 496 0123"),
            _contact("c" * 16, "Howdens", email="shared@example.co.uk", vrn="GB111111111"),
            _contact("d" * 16, "Howdens Joinery", email="shared@example.co.uk", vrn="GB222222222"),
        ],
    )
    return b


@pytest.fixture
def client(books: Books):
    from app.main import app
    from app.routes_books import get_books

    async def override_books() -> Books:
        return books

    app.dependency_overrides[get_books] = override_books
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_duplicates_show_evidence_and_blocked_without_ai(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """No model answers here (nothing listens on the AI base): the card still gets the code evidence."""
    import httpx

    def refuse(*a: Any, **k: Any) -> Any:
        raise httpx.ConnectError("nothing listening")

    monkeypatch.setattr("httpx.AsyncClient", refuse)
    body = client.get("/contacts/duplicates", headers=H).json()
    by_ids = {tuple(g["contact_ids"]): g for g in body["groups"]}
    same = by_ids[("a" * 16, "b" * 16)]
    assert "same email trade@screwfix.com" in same["evidence"] and not same["blocked"]
    assert same["ai"] is None  # the model could not answer; the evidence stands alone
    assert [c["name"] for c in same["contacts"]] == ["Screwfix", "SCREWFIX DIRECT LTD"]
    blocked = by_ids[("c" * 16, "d" * 16)]
    assert blocked["blocked"] and blocked["ai"]["same"] is False  # code rules VAT conflicts out itself


def test_duplicates_carry_the_models_view(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def judge(*a: Any, **k: Any) -> dict[str, Any]:
        return {"same": True, "confidence": 0.85, "keep_name": "Screwfix", "reason": "Same email and name."}

    from app.ai import duplicates as dup

    monkeypatch.setattr(dup, "judge_duplicate", judge)
    body = client.get("/contacts/duplicates", headers=H).json()
    same = next(g for g in body["groups"] if tuple(g["contact_ids"]) == ("a" * 16, "b" * 16))
    assert same["ai"] == {"same": True, "confidence": 0.85, "keep_name": "Screwfix", "reason": "Same email and name."}


def test_dismiss_never_suggests_again(client: TestClient, fake: FakeStorageProvider) -> None:
    assert len(client.get("/contacts/duplicates", headers=H).json()["groups"]) == 2
    r = client.post("/contacts/duplicates/dismiss", headers=H, json={"contact_ids": ["a" * 16, "b" * 16]})
    assert r.status_code == 200 and r.json() == {"dismissed": ["a" * 16, "b" * 16]}
    assert json.loads(fake.files[cb.NOT_SAME]) == [["a" * 16, "b" * 16]]
    groups = client.get("/contacts/duplicates", headers=H).json()["groups"]
    assert all("a" * 16 not in g["contact_ids"] or "b" * 16 not in g["contact_ids"] for g in groups)
    assert client.post("/contacts/duplicates/dismiss", headers=H, json={"contact_ids": ["a" * 16]}).status_code == 422
    assert client.post("/contacts/duplicates/dismiss", headers={"X-Graph-Token": "tok"}).status_code == 400


def test_merge_and_undo_round_trip(client: TestClient, fake: FakeStorageProvider) -> None:
    before = json.loads(fake.files[cb.CONTACTS])
    r = client.post("/contacts/merge", headers=H, json={"keep_id": "a" * 16, "merge_ids": ["b" * 16], "name": "Screwfix Ltd"})
    assert r.status_code == 200, r.text
    assert r.json()["contact"]["phone"] == "0117 496 0123"
    merge_id = r.json()["merge_id"]
    assert {c["id"] for c in json.loads(fake.files[cb.CONTACTS])} == {"a" * 16, "c" * 16, "d" * 16}

    u = client.post(f"/contacts/merge/{merge_id}/undo", headers=H)
    assert u.status_code == 200 and {c["id"] for c in u.json()["contacts"]} == {"a" * 16, "b" * 16, "c" * 16, "d" * 16}
    assert json.loads(fake.files[cb.CONTACTS]) == before
    assert client.post(f"/contacts/merge/{merge_id}/undo", headers=H).status_code == 404
    assert client.post("/contacts/merge/0123456789abcdef/undo", headers=H).status_code == 404


def test_merge_refusals_are_400(client: TestClient) -> None:
    assert client.post("/contacts/merge", headers=H, json={"keep_id": "a" * 16, "merge_ids": ["c" * 16, "d" * 16]}).status_code == 400  # VAT conflict
    assert client.post("/contacts/merge", headers=H, json={"keep_id": "0" * 16, "merge_ids": ["b" * 16]}).status_code == 400
    assert client.post("/contacts/merge", headers=H, json={"keep_id": "a" * 16, "merge_ids": ["a" * 16]}).status_code == 400
    assert client.post("/contacts/merge", headers={"X-Graph-Token": "tok"}, json={"keep_id": "a" * 16, "merge_ids": ["b" * 16]}).status_code == 400


def _audit(fake: FakeStorageProvider) -> list[str]:
    return [
        json.loads(x)["action"]
        for p, d in sorted(fake.files.items())
        if p.startswith(f"{AUDIT}/")
        for x in d.decode().splitlines()
    ]


def test_merge_and_dismiss_are_audited(client: TestClient, fake: FakeStorageProvider) -> None:
    merge_id = client.post("/contacts/merge", headers=H, json={"keep_id": "a" * 16, "merge_ids": ["b" * 16]}).json()["merge_id"]
    client.post("/contacts/duplicates/dismiss", headers=H, json={"contact_ids": ["c" * 16, "d" * 16]})
    client.post(f"/contacts/merge/{merge_id}/undo", headers=H)
    assert _audit(fake) == ["contacts_merged", "contacts_not_same", "contacts_merge_undone"]
