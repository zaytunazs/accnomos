"""Contract tests every StorageProvider must pass. Run against the fake now; Microsoft Graph via a
recorded fixture later. Add a provider by appending a fixture that yields it."""

import pytest
from accnomos_connectors import FakeStorageProvider
from accnomos_connectors.base import ConflictError

pytestmark = pytest.mark.asyncio


@pytest.fixture(params=["fake"])
def storage(request):
    return FakeStorageProvider()


async def test_folder_tree_and_listing(storage):
    for p in ["00 Inbox", "01 Receipts/2026-10", "04 Needs a look", "_System/audit"]:
        await storage.ensure_folder(p)
    names = [f.name for f in await storage.list("")]
    assert names[:3] == ["00 Inbox", "01 Receipts", "04 Needs a look"]


async def test_write_read_move_and_changes(storage):
    await storage.write("00 Inbox/r1.jpg", b"jpeg-bytes")
    assert await storage.read("00 Inbox/r1.jpg") == b"jpeg-bytes"
    moved = await storage.move("00 Inbox/r1.jpg", "01 Receipts/2026-10/2026-10-21 Screwfix £38.47.jpg")
    assert moved.name.startswith("2026-10-21")
    changed, cursor = await storage.changes(None)
    assert [c.path for c in changed] and cursor
    again, cursor2 = await storage.changes(cursor)
    assert again == [] and cursor2 == cursor


async def test_if_match_conflict(storage):
    ref = await storage.write("_System/rules.json", b"{}")
    await storage.write("_System/rules.json", b'{"a":1}')  # someone else edits
    with pytest.raises(ConflictError):
        await storage.write("_System/rules.json", b'{"b":2}', if_match=ref.etag)


async def test_move_a_folder_with_everything_in_it(storage):
    await storage.write("03 Bank statements/2026/a.csv", b"a")
    await storage.write("03 Bank statements/b.csv", b"b")
    await storage.ensure_folder("03 Bank statements/empty")
    await storage.write("03 Bank statements x/c.csv", b"c")  # same prefix, a different folder
    ref = await storage.move("03 Bank statements", "04 Bank statements")
    assert ref.is_folder and ref.path == "04 Bank statements"
    assert await storage.read("04 Bank statements/2026/a.csv") == b"a"
    assert await storage.read("04 Bank statements/b.csv") == b"b"
    assert {f.name for f in await storage.list("04 Bank statements")} == {"2026", "empty", "b.csv"}
    assert "03 Bank statements" not in {f.name for f in await storage.list("")}
    assert await storage.read("03 Bank statements x/c.csv") == b"c"
    with pytest.raises(FileNotFoundError):
        await storage.read("03 Bank statements/b.csv")


async def test_move_a_folder_onto_an_existing_one_refuses(storage):
    await storage.write("05 VAT returns/a.json", b"old")
    await storage.write("06 VAT returns/b.json", b"new")
    with pytest.raises(FileExistsError):
        await storage.move("05 VAT returns", "06 VAT returns")
    assert await storage.read("05 VAT returns/a.json") == b"old"
