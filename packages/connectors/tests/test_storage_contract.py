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
