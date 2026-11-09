"""GoogleDriveStorageProvider against the in-memory Drive (accnomos_connectors.fake_drive)."""

import hashlib

import httpx
import pytest

from accnomos_connectors import google_drive
from accnomos_connectors.base import ConflictError
from accnomos_connectors.fake_drive import FOLDER_MIME, ROOT_ID, FakeDrive
from accnomos_connectors.google_drive import GoogleDriveError, GoogleDriveStorageProvider, GoogleIdentity

pytestmark = pytest.mark.asyncio


@pytest.fixture
def drive():
    return FakeDrive()


@pytest.fixture
async def storage(drive):
    async def no_sleep(_s: float) -> None:
        return None

    async with httpx.AsyncClient(transport=drive.transport()) as client:
        yield GoogleDriveStorageProvider(drive.token, client=client, sleep=no_sleep)


async def test_root_is_one_accnomos_folder_in_my_drive(storage, drive):
    root = await storage.ensure_root()
    again = await GoogleDriveStorageProvider(drive.token, client=storage._client).ensure_root()
    assert root.is_folder and root.id == again.id
    roots = [i for i in drive.items.values() if i["name"] == "Accnomos"]
    assert len(roots) == 1 and roots[0]["parents"] == [ROOT_ID] and roots[0]["mimeType"] == FOLDER_MIME


async def test_write_lists_md5_hash_and_version_etag(storage, drive):
    ref = await storage.write("00 Inbox/r.jpg", b"jpeg")
    assert ref.content_hash == f"md5:{hashlib.md5(b'jpeg').hexdigest()}"
    assert ref.etag == '"v1"' and ref.size == 4
    assert drive.find("Accnomos/00 Inbox/r.jpg") is not None
    second = await storage.write("00 Inbox/r.jpg", b"jpeg2", if_match=ref.etag)
    assert second.etag == '"v2"' and second.id == ref.id  # updated in place, not a second file
    assert await storage.read("00 Inbox/r.jpg") == b"jpeg2"


async def test_duplicate_names_resolve_to_the_oldest(storage, drive):
    await storage.ensure_folder("_System")
    system = drive.find("Accnomos/_System")["id"]
    drive.add("rules.json", system, b"old")  # e.g. two devices created it at once
    drive.add("rules.json", system, b"newer")
    assert await storage.read("_System/rules.json") == b"old"
    assert [f.name for f in await storage.list("_System")] == ["rules.json"]
    with pytest.raises(FileExistsError):
        await storage.write("_System/rules.json", b"x", create_only=True)


async def test_duplicate_folders_resolve_to_the_oldest(storage, drive):
    root = (await storage.ensure_root()).id
    first = drive.add("00 Inbox", root)
    drive.add("00 Inbox", root)
    await storage.write("00 Inbox/a.txt", b"a")
    assert drive.find("Accnomos/00 Inbox/a.txt")["parents"] == [first]


async def test_if_match_on_a_changed_file_is_a_conflict(storage):
    ref = await storage.write("_System/x.json", b"{}")
    await storage.write("_System/x.json", b"{1}")
    with pytest.raises(ConflictError):
        await storage.write("_System/x.json", b"{2}", if_match=ref.etag)


async def test_missing_files_and_folders(storage):
    with pytest.raises(FileNotFoundError):
        await storage.read("nope/a.txt")
    with pytest.raises(FileNotFoundError):
        await storage.list("nope")
    with pytest.raises(FileNotFoundError):
        await storage.move("nope.txt", "b.txt")


async def test_a_file_move_renames_in_place(storage, drive):
    await storage.write("00 Inbox/a.jpg", b"a")
    ref = await storage.move("00 Inbox/a.jpg", "00 Inbox/b.jpg")
    assert ref.path == "00 Inbox/b.jpg"
    assert drive.find("Accnomos/00 Inbox/b.jpg")["id"] == ref.id
    await storage.write("00 Inbox/c.jpg", b"c")
    with pytest.raises(FileExistsError):
        await storage.move("00 Inbox/c.jpg", "00 Inbox/b.jpg")


async def test_large_files_use_a_resumable_session(storage, drive, monkeypatch):
    monkeypatch.setattr(google_drive, "SIMPLE_UPLOAD_MAX", 10)
    data = b"x" * 25
    ref = await storage.write("big.bin", data)
    assert await storage.read("big.bin") == data and ref.size == 25
    await storage.write("big.bin", data + b"y")
    assert await storage.read("big.bin") == data + b"y"
    assert not drive.sessions


async def test_changes_follow_writes_and_moves_and_skip_files_outside_the_books(storage, drive):
    await storage.write("00 Inbox/a.jpg", b"a")
    everything, cursor = await storage.changes(None)
    assert [c.path for c in everything] == ["00 Inbox/a.jpg"]
    await storage.write("00 Inbox/b.jpg", b"b")
    await storage.move("00 Inbox/a.jpg", "01 Receipts/2026-11/a.jpg")
    drive.add("elsewhere.txt", ROOT_ID, b"not ours")  # another file this app made, outside the books
    changed, cursor2 = await storage.changes(cursor)
    assert sorted(c.path for c in changed) == ["00 Inbox/b.jpg", "01 Receipts/2026-11/a.jpg"]
    fresh = GoogleDriveStorageProvider(drive.token, client=storage._client)  # no cached folder ids
    await storage.write("01 Receipts/2026-11/c.jpg", b"c")
    changed, _ = await fresh.changes(cursor2)
    assert [c.path for c in changed] == ["01 Receipts/2026-11/c.jpg"]


async def test_rate_limits_are_retried_and_other_errors_raised(storage, drive):
    drive.fail_next = [429, 503]
    await storage.ensure_root()
    drive.fail_next = [500]
    with pytest.raises(GoogleDriveError) as err:
        await storage.write("a.txt", b"a")
    assert err.value.status == 500


async def test_a_refused_token_is_a_401_error(drive):
    async with httpx.AsyncClient(transport=drive.transport()) as client:
        with pytest.raises(GoogleDriveError) as err:
            await GoogleDriveStorageProvider("wrong", client=client).ensure_root()
    assert err.value.status == 401


async def test_the_token_never_leaves_googleapis(storage):
    with pytest.raises(ValueError):
        await storage._request("GET", "https://evil.example.com/drive/v3/files")


async def test_unsafe_paths_are_refused(storage):
    with pytest.raises(ValueError):
        await storage.write("../escape.txt", b"x")


async def test_identity_from_userinfo(drive):
    async with httpx.AsyncClient(transport=drive.transport()) as client:
        me = await GoogleIdentity(drive.token, client=client).whoami()
    assert me.email == "owner@example.com" and me.name == "Owner"


async def test_module_transport_hook(drive, monkeypatch):
    monkeypatch.setattr(google_drive, "TRANSPORT", drive.transport())
    storage = GoogleDriveStorageProvider(drive.token)
    try:
        await storage.write("hello.txt", b"hi")
        assert await storage.read("hello.txt") == b"hi"
    finally:
        await storage.aclose()
