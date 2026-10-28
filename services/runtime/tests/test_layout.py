"""Old folder names -> current ones (app/layout.py), on fake storage."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app import layout, paths, testmode
from app.books import AUDIT, Books
from app.routes_books import router as books_router


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
def books(fake: FakeStorageProvider) -> Books:
    return Books(fake)


def _audit(fake: FakeStorageProvider) -> list[dict]:
    return [
        json.loads(x)
        for p, d in sorted(fake.files.items())
        if p.startswith(f"{AUDIT}/")
        for x in d.decode().splitlines()
    ]


async def _old_books(fake: FakeStorageProvider) -> None:
    """A folder as the previous version left it: web onboarding names plus what the runtime wrote."""
    for folder in (
        "00 Inbox",
        "01 Receipts",
        "02 Sales invoices",
        "03 Bank statements",
        "04 Needs a look",
        "05 VAT returns",
        "06 Reports",
        "_System/audit",
    ):
        await fake.ensure_folder(folder)
    await fake.write("03 Bank statements/2026-09-30_starling.csv", b"csv")
    await fake.write("04 Needs a look/2026-09-18 Howdens.pdf", b"pdf")
    await fake.write("04 Payroll/2026-09.csv", b"pay")
    await fake.write("05 VAT returns/2026-Q3/return.json", b"{}")
    await fake.write("03 Sales/invoices/INV-0001.json", b"{}")  # invoicing already used the current name


async def test_old_names_move_to_new_names_with_their_contents(fake: FakeStorageProvider, books: Books) -> None:
    await _old_books(fake)
    before = {p: d for p, d in fake.files.items()}
    status = await layout.migrate(books)

    assert {(m.old, m.new) for m in status.moved} == {
        ("03 Bank statements", paths.BANK),
        ("04 Needs a look", paths.NEEDS_A_LOOK),
        ("04 Payroll", paths.PAYROLL),
        ("05 VAT returns", paths.VAT_RETURNS),
        ("06 Reports", paths.REPORTS),
    }
    assert fake.files["04 Bank statements/2026-09-30_starling.csv"] == b"csv"
    assert fake.files["02 Needs a look/2026-09-18 Howdens.pdf"] == b"pdf"
    assert fake.files["05 Payroll/2026-09.csv"] == b"pay"
    assert fake.files["06 VAT returns/2026-Q3/return.json"] == b"{}"
    assert "07 Reports" in fake.folders
    for old in ("03 Bank statements", "04 Needs a look", "04 Payroll", "05 VAT returns", "06 Reports"):
        assert old not in fake.folders and not any(p.startswith(f"{old}/") for p in fake.files)
    # moved, never copied or deleted: the same bytes, one file each
    assert sorted(before.values()) == sorted(d for p, d in fake.files.items() if not p.startswith(f"{AUDIT}/"))

    (line,) = [a for a in _audit(fake) if a["action"] == "folders_renamed"]
    assert line["actor"] == layout.ACTOR and len(line["refs"]["moved"]) == 5


async def test_old_and_new_side_by_side_are_left_alone_and_reported(fake: FakeStorageProvider, books: Books) -> None:
    await _old_books(fake)  # "02 Sales invoices" (empty) next to "03 Sales"
    await fake.write("06 VAT returns/2026-Q4/return.json", b"new")  # and VAT returns under both names
    status = await layout.migrate(books)

    assert {(c.old, c.new, c.old_is_empty) for c in status.conflicts} == {
        ("02 Sales invoices", paths.SALES, True),
        ("05 VAT returns", paths.VAT_RETURNS, False),
    }
    assert fake.files["05 VAT returns/2026-Q3/return.json"] == b"{}"  # untouched
    assert fake.files["06 VAT returns/2026-Q4/return.json"] == b"new"
    assert "02 Sales invoices" in fake.folders
    assert status.warning and "05 VAT returns and 06 VAT returns" in status.warning
    assert ("05 VAT returns", "06 VAT returns") not in {(m.old, m.new) for m in status.moved}


class _Yielding(FakeStorageProvider):
    """Lets other requests run between listing the folder and moving in it, as Graph's round trips do."""

    async def list(self, path: str):  # noqa: ANN201
        await asyncio.sleep(0)
        return await super().list(path)


async def test_two_requests_checking_at_once_both_succeed_and_rename_once() -> None:
    fake = _Yielding()
    await _old_books(fake)
    await fake.write("06 VAT returns/2026-Q4/return.json", b"new")
    first, second = await asyncio.gather(layout.migrate(Books(fake)), layout.migrate(Books(fake)))
    assert "04 Bank statements/2026-09-30_starling.csv" in fake.files
    assert not any(f.startswith("03 Bank statements") for f in fake.files)
    moved = [(m.old, m.new) for s in (first, second) for m in s.moved]
    assert moved.count(("03 Bank statements", "04 Bank statements")) == 1  # one of them did it, once
    for status in (first, second):  # and each still reports what needs a person
        assert ("05 VAT returns", paths.VAT_RETURNS) in {(c.old, c.new) for c in status.conflicts}


async def test_idempotent(fake: FakeStorageProvider, books: Books) -> None:
    await _old_books(fake)
    await layout.migrate(books)
    files, folders = dict(fake.files), set(fake.folders)
    again = await layout.migrate(books)
    assert again.moved == [] and {c.old for c in again.conflicts} == {"02 Sales invoices"}
    assert fake.files == files and fake.folders == folders  # not even another audit line


async def test_new_books_and_missing_root_change_nothing(fake: FakeStorageProvider, books: Books) -> None:
    assert await layout.migrate(books) == layout.LayoutStatus()
    await books.ensure_tree()
    assert await layout.migrate(books) == layout.LayoutStatus()
    assert not _audit(fake)


async def test_case_insensitive_like_onedrive(fake: FakeStorageProvider, books: Books) -> None:
    await fake.write("03 bank Statements/a.csv", b"x")
    status = await layout.migrate(books)
    assert [(m.old, m.new) for m in status.moved] == [("03 bank Statements", paths.BANK)]
    assert fake.files["04 Bank statements/a.csv"] == b"x"


async def test_once_per_token(fake: FakeStorageProvider, books: Books, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(layout, "_SEEN", type(layout._SEEN)())
    calls = []
    real = layout.migrate

    async def counting(b: Books) -> layout.LayoutStatus:
        calls.append(1)
        return await real(b)

    monkeypatch.setattr(layout, "migrate", counting)
    await layout.on_first_contact(books, "token-a")
    await layout.on_first_contact(books, "token-a")
    await layout.on_first_contact(books, "token-b")
    assert len(calls) == 2


async def test_a_storage_error_does_not_break_the_request(books: Books, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(layout, "_SEEN", type(layout._SEEN)())

    async def broken(_path: str) -> list:
        raise RuntimeError("graph is down")

    monkeypatch.setattr(books.storage, "list", broken)
    assert await layout.on_first_contact(books, "t") is None
    assert "t" not in layout._SEEN  # tried again next time


async def test_paths_recorded_before_the_rename_still_resolve(fake: FakeStorageProvider, books: Books) -> None:
    await fake.write("04 Needs a look/a.pdf", b"pdf")
    await layout.migrate(books)
    p = SimpleNamespace(file_path="04 Needs a look/a.pdf", suggested_filename="a.pdf")  # a proposal saved earlier
    dest = await books.file_document(p, p.file_path, f"{paths.RECEIPTS}/2026-09")  # type: ignore[arg-type]
    assert dest == "01 Receipts/2026-09/a.pdf" and fake.files[dest] == b"pdf"


async def test_old_path_is_used_while_the_old_folder_is_still_there(fake: FakeStorageProvider, books: Books) -> None:
    await fake.write("04 Needs a look/a.pdf", b"old")
    await fake.write("02 Needs a look/b.pdf", b"new")  # conflict: nothing moves
    await layout.migrate(books)
    p = SimpleNamespace(file_path="04 Needs a look/a.pdf", suggested_filename="a.pdf")
    dest = await books.file_document(p, p.file_path, f"{paths.RECEIPTS}/2026-09")  # type: ignore[arg-type]
    assert fake.files[dest] == b"old"


def test_home_names_the_statement_where_it_is_now() -> None:
    from datetime import date

    from accnomos_ledger.bank import BankLine
    from app import dashboard

    line = BankLine(
        id="a" * 16,
        date=date(2026, 9, 30),
        amount_pence=-50,
        description="x",
        balance_pence=1050,
        source_file="03 Bank statements/2026-09-30_starling.csv",
        status="matched",
    )  # imported earlier
    cash = dashboard.cash_position([line])
    assert cash.statement == "04 Bank statements/2026-09-30_starling.csv"
    assert cash.bank == "starling" and cash.balance_pence == 1050


# --------------------------------------------------------------------------- #
# Wiring: get_books renames on first contact; GET /books/layout and /health
# --------------------------------------------------------------------------- #


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", "1")
    monkeypatch.setenv("ACCNOMOS_TEST_TODAY", testmode.DEFAULT_TODAY)
    app = FastAPI()
    app.include_router(testmode.router)
    app.include_router(books_router)
    c = TestClient(app)
    assert c.post("/__test/reset").json()["ok"]
    return c


H = {"X-Graph-Token": "test-token"}


async def test_first_request_renames_and_layout_reports_conflicts(client: TestClient) -> None:
    fake = testmode.STATE.storage
    await fake.write("03 Bank statements/a.csv", b"x")
    await fake.write("05 VAT returns/notes.txt", b"x")
    await fake.write("06 VAT returns/2026-Q4/return.json", b"{}")

    r = client.get("/books/layout", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["moved"] == []  # get_books already did it, before the route ran
    assert "04 Bank statements/a.csv" in fake.files
    assert body["conflicts"] == [{"old": "05 VAT returns", "new": "06 VAT returns", "old_is_empty": False}]
    assert "05 VAT returns and 06 VAT returns" in body["warning"]

    await fake.move("05 VAT returns/notes.txt", "06 VAT returns/notes.txt")  # the user tidies up
    assert client.get("/books/layout", headers=H).json()["conflicts"][0]["old_is_empty"] is True


def test_health_carries_counts_and_no_names(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import app

    monkeypatch.setattr(layout, "COUNTS", {"checks": 3, "folders_renamed": 5, "checks_with_conflicts": 1})
    body = TestClient(app).get("/health").json()
    assert body["folder_layout"]["checks_with_conflicts"] == 1 and "Files page" in body["folder_layout"]["warning"]
    assert "VAT" not in json.dumps(body)
