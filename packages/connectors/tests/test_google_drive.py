"""GoogleDriveStorageProvider against the in-memory Drive (accnomos_connectors.fake_drive)."""

import asyncio
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


def _live(drive: FakeDrive, name: str) -> list[dict]:
    return [i for i in drive.items.values() if i["name"] == name and not i["trashed"]]


async def test_two_first_requests_end_with_one_root_and_keep_both_files(drive):
    async with httpx.AsyncClient(transport=drive.transport()) as client:
        a = GoogleDriveStorageProvider(drive.token, client=client)
        b = GoogleDriveStorageProvider(drive.token, client=client)
        await asyncio.gather(a.write("00 Inbox/a.jpg", b"a"), b.write("00 Inbox/b.jpg", b"b"))
        assert len(_live(drive, "Accnomos")) == 1 and len(_live(drive, "00 Inbox")) == 1
        fresh = GoogleDriveStorageProvider(drive.token, client=client)
        assert {f.name for f in await fresh.list("00 Inbox")} == {"a.jpg", "b.jpg"}


async def test_racing_create_only_claims_have_exactly_one_winner(drive, storage):
    await storage.ensure_folder("_System/claims")
    async with httpx.AsyncClient(transport=drive.transport()) as client:
        tabs = [GoogleDriveStorageProvider(drive.token, client=client) for _ in range(3)]
        results = await asyncio.gather(
            *(t.write("_System/claims/e1.json", f"tab{i}".encode(), create_only=True) for i, t in enumerate(tabs)),
            return_exceptions=True,
        )
    wins = [r for r in results if not isinstance(r, BaseException)]
    assert len(wins) == 1 and sum(isinstance(r, FileExistsError) for r in results) == 2
    assert len(_live(drive, "e1.json")) == 1
    assert await storage.read("_System/claims/e1.json") == drive.content[wins[0].id]


async def test_racing_plain_writes_leave_one_file(drive, storage):
    await storage.ensure_folder("_System")
    async with httpx.AsyncClient(transport=drive.transport()) as client:
        a = GoogleDriveStorageProvider(drive.token, client=client)
        b = GoogleDriveStorageProvider(drive.token, client=client)
        await asyncio.gather(a.write("_System/x.json", b"1"), b.write("_System/x.json", b"2"))
    assert len(_live(drive, "x.json")) == 1
    assert await storage.read("_System/x.json") in (b"1", b"2")


async def test_if_match_on_a_file_that_is_gone_is_a_conflict(storage, drive):
    ref = await storage.write("_System/y.json", b"{}")
    drive.items[ref.id]["trashed"] = True  # removed on another device
    with pytest.raises(ConflictError):
        await storage.write("_System/y.json", b"{1}", if_match=ref.etag)
    assert not _live(drive, "y.json")
