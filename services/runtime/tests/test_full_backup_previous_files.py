"""Back up now (app/full_backup.py) and earlier files never read (app/previous_files.py), on fake storage.

The books: one posted purchase whose receipt is filed in 01 Receipts (linked), plus files nobody processed: a photo
in 00 Inbox, a PDF dropped by hand into 01 Receipts/2025-03, one in 02 Needs a look, and a .txt note that is not a
document type the app reads. Books.xlsx exists.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_ledger import LedgerEvent, Line, VatCode
from app import backups, full_backup, previous_files
from app import files as fm
from app.books import Books
from app.schemas import ExtractedDoc, Proposal

USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
PID = "ab12cd34ef56ab78"
EID = "e" * 32
LINKED = "01 Receipts/2024-08/2024-08-14 Novex £51.90.pdf"
INBOX_PHOTO = "00 Inbox/IMG_2041.jpg"
BY_HAND = "01 Receipts/2025-03/screwfix.pdf"
NEEDS_LOOK = "02 Needs a look/old scan.pdf"
NOTE = "01 Receipts/notes.txt"


def _event() -> LedgerEvent:
    return LedgerEvent(
        id=EID,
        kind="purchase",
        date=date(2024, 8, 14),
        lines=[
            Line(account="5000 Materials", debit=4_325, vat_code=VatCode.STANDARD),
            Line(account="2200 VAT control", debit=865),
            Line(account="1200 Bank", credit=5_190),
        ],
        net=4_325,
        vat=865,
        counterparty="Novex Office Supplies Ltd",
        approved_by=USER,
        approved_at=datetime(2024, 8, 20, tzinfo=UTC),
    )


def _proposal() -> Proposal:
    doc = ExtractedDoc(
        doc_type="purchase_invoice",
        supplier_name="Novex Office Supplies Ltd",
        supplier_vat_number=None,
        customer_name=None,
        invoice_number=None,
        date="2024-08-14",
        currency="GBP",
        lines=[],
        net_total=43.25,
        vat_total=8.65,
        gross_total=51.90,
        payment_method=None,
        card_last4=None,
        category_guess="Materials",
        confidence=0.9,
    )
    return Proposal(
        id=PID,
        doc_sha256=hashlib.sha256(b"novex").hexdigest(),
        extracted=doc,
        checks=[],
        status="posted",
        reasons=[],
        suggested_filename="2024-08-14 Novex £51.90.pdf",
        journal_draft=[],
        model="stub",
        elapsed_s=1.0,
        file_path=LINKED,
        event_id=EID,
    )


@pytest.fixture
async def books() -> Books:
    fake = FakeStorageProvider()
    b = Books(fake)
    await b.ensure_tree()
    await b.post_event(_event())
    await b.save_proposal(_proposal())
    await fake.write(LINKED, b"novex")
    await fake.write(INBOX_PHOTO, b"\xff\xd8 a photo")
    await fake.write(BY_HAND, b"%PDF-1.4 by hand")
    await fake.write(NEEDS_LOOK, b"%PDF-1.4 old")
    await fake.write(NOTE, b"remember the van")
    await fake.write("Books.xlsx", b"PK xlsx bytes")
    return b


def _fake(b: Books) -> FakeStorageProvider:
    assert isinstance(b.storage, FakeStorageProvider)
    return b.storage


async def _audit(b: Books) -> list[dict]:
    raw = _fake(b).files[f"_System/audit/{datetime.now(UTC):%Y-%m}.jsonl"]
    return [json.loads(line) for line in raw.decode().splitlines()]


@pytest.fixture
def client(books: Books):
    from app.main import app
    from app.routes_books import get_books

    async def override() -> Books:
        return books

    app.dependency_overrides[get_books] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Back up now
# --------------------------------------------------------------------------- #


async def test_a_full_backup_is_a_dated_folder_apart_from_the_books(books: Books) -> None:
    steps: list[str] = []
    result: full_backup.FullBackup | None = None
    async for item in full_backup.back_up_full(books, USER):
        if isinstance(item, full_backup.Progress):
            steps.append(item.step)
        else:
            result = item
    assert steps == list(full_backup.STEPS)
    assert result is not None and result.complete
    assert result.folder.startswith("Accnomos Backups/")
    assert len(result.name) == len("2026-10-29-1432")
    files = _fake(books).files
    names = {f.name for f in result.files}
    assert names == {"books-system.zip", "Books.xlsx", "documents-index.json", "RESTORE.txt"}
    for f in result.files:  # the manifest's sha256 is each file's
        assert hashlib.sha256(files[f"{result.folder}/{f.name}"]).hexdigest() == f.sha256
    man = json.loads(files[f"{result.folder}/manifest.json"])
    assert man["format"] == full_backup.FORMAT and man["created_by"] == USER
    with zipfile.ZipFile(io.BytesIO(files[f"{result.folder}/books-system.zip"])) as z:
        inside = set(z.namelist())
    assert any(n.startswith("_System/Ledger/events/") for n in inside)
    assert f"_System/proposals/{PID}.json" in inside and "manifest.json" in inside
    assert files[f"{result.folder}/Books.xlsx"] == b"PK xlsx bytes"
    index = json.loads(files[f"{result.folder}/documents-index.json"])
    assert {f["path"] for f in index["files"]} >= {LINKED, BY_HAND, INBOX_PHOTO}
    assert "type RESTORE" in files[f"{result.folder}/RESTORE.txt"].decode()
    # The live books are untouched and the old Backups/ zips are not where this goes.
    assert not any(p.startswith("Backups/") for p in files)
    [line] = [a for a in await _audit(books) if a["action"] == "full_backup_created"]
    assert line["actor"] == f"user:{USER}" and line["refs"]["folder"] == result.folder


async def test_a_second_backup_in_the_same_minute_gets_its_own_folder_and_both_are_listed(books: Books) -> None:
    first = await full_backup.run(books, USER)
    second = await full_backup.run(books, USER)
    assert second.folder != first.folder and second.name.startswith(first.name)
    listed = await full_backup.list_full(books)
    assert [b.folder for b in listed][:2] == [second.folder, first.folder]
    assert all(b.complete and b.ledger_files for b in listed)


async def test_a_full_backup_verifies_and_restores_through_the_usual_restore(books: Books) -> None:
    done = await full_backup.run(books, USER)
    assert done.system_zip
    v = await backups.verify(books, done.system_zip, USER)
    assert v.ok, v.problems
    _fake(books).files[f"_System/proposals/{PID}.json"] = b"{}"  # damage the live copy
    preview = await backups.restore_preview(books, done.system_zip)
    assert preview.counts["changed"] == 1 and preview.needs_confirmation
    res = await backups.restore(books, done.system_zip, USER, "RESTORE")
    assert res.replaced == 1
    assert json.loads(_fake(books).files[f"_System/proposals/{PID}.json"])["id"] == PID


async def test_backups_folder_is_protected_and_not_a_document(books: Books) -> None:
    done = await full_backup.run(books, USER)
    assert fm.is_protected(f"{done.folder}/Books.xlsx")
    assert not fm.move_target_ok(done.folder)
    assert all(not f.path.startswith("Accnomos Backups/") for f in (await fm.index(books)).files)


async def test_a_listing_shows_a_backup_that_stopped_part_way_as_incomplete(books: Books) -> None:
    await _fake(books).write("Accnomos Backups/2026-01-02-0304/books-system.zip", b"half")
    [b] = await full_backup.list_full(books)
    assert b.name == "2026-01-02-0304" and not b.complete


def test_back_up_now_route_streams_progress_then_the_backup(client: TestClient) -> None:
    res = client.post("/backups/full?stream=1", headers=H)
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/event-stream")
    events = [b.split("\n") for b in res.text.strip().split("\n\n")]
    kinds = [e[0].removeprefix("event: ") for e in events]
    assert kinds[-1] == "backup" and kinds.count("progress") == len(full_backup.STEPS)
    backup = json.loads(events[-1][1].removeprefix("data: "))
    listed = client.get("/backups/full", headers=H).json()
    assert listed["backups"][0]["folder"] == backup["folder"]


def test_back_up_now_needs_a_user(client: TestClient) -> None:
    assert client.post("/backups/full", headers={"X-Graph-Token": "tok"}).status_code in (400, 401, 422)


# --------------------------------------------------------------------------- #
# Earlier files never read
# --------------------------------------------------------------------------- #


async def test_find_lists_unread_documents_in_inbox_receipts_and_needs_a_look(books: Books) -> None:
    found = await previous_files.find(books)
    assert {f.path for f in found.files} == {INBOX_PHOTO, BY_HAND, NEEDS_LOOK}  # not the linked one, not the .txt
    assert found.count == 3 and found.left_alone == 0
    assert {f.folder for f in found.files} == {"00 Inbox", "01 Receipts", "02 Needs a look"}


async def test_queue_moves_the_chosen_files_into_the_inbox_and_audits(books: Books) -> None:
    res = await previous_files.queue(books, [BY_HAND, INBOX_PHOTO], USER)
    assert res.queued == 2 and res.already_in_inbox == 1
    assert [(m.old, m.new) for m in res.moved] == [(BY_HAND, "00 Inbox/screwfix.pdf")]
    files = _fake(books).files
    assert "00 Inbox/screwfix.pdf" in files and BY_HAND not in files
    actions = [a["action"] for a in await _audit(books)]
    assert "previous_files_queued" in actions and "files_moved" in actions


async def test_queue_refuses_files_that_are_not_waiting(books: Books) -> None:
    with pytest.raises(previous_files.FileError):
        await previous_files.queue(books, [LINKED], USER)  # already in the books
    with pytest.raises(previous_files.FileError):
        await previous_files.queue(books, ["_System/proposals/x.json"], USER)
    with pytest.raises(previous_files.FileError):
        await previous_files.queue(books, [], USER)


async def test_leave_remembers_and_they_are_not_offered_again(books: Books) -> None:
    assert await previous_files.leave(books, [NEEDS_LOOK], USER) == 1
    found = await previous_files.find(books)
    assert NEEDS_LOOK not in {f.path for f in found.files} and found.left_alone == 1
    assert NEEDS_LOOK in _fake(books).files  # nothing moved
    assert "previous_files_left" in [a["action"] for a in await _audit(books)]


def test_previous_files_routes(client: TestClient) -> None:
    found = client.get("/files/previous", headers=H).json()
    assert found["count"] == 3
    bad = client.post("/files/previous/queue", headers=H, json={"paths": [LINKED]})
    assert bad.status_code == 409
    ok = client.post("/files/previous/queue", headers=H, json={"paths": [NEEDS_LOOK]})
    assert ok.status_code == 200 and ok.json()["queued"] == 1
    left = client.post("/files/previous/leave", headers=H, json={"paths": [INBOX_PHOTO]})
    assert left.json() == {"left": 1}
    assert client.get("/files/previous", headers=H).json()["count"] == 2  # the moved one is in the Inbox now
