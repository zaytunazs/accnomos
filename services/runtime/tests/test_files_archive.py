"""Files page, archive by year, Clean up and backups, on fake storage (app/files.py, app/archive.py, app/backups.py).

The books: one posted purchase from August 2024 whose receipt is filed in 01 Receipts/2024-08, a bank statement
from 2025, a report, an invoice record and a VAT return (both left alone), a copy of the receipt in the Inbox (a
duplicate), and this year's receipt. Today is pinned to 28 October 2026 (tax year 2026-27).
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_connectors.base import FileRef
from accnomos_ledger import LedgerEvent, Line, VatCode
from app import archive, audit_view, backups
from app import files as fm
from app.books import Books, follow
from app.schemas import ExtractedDoc, Proposal

USER = "sam@example.co.uk"
H = {"X-Graph-Token": "tok", "X-User": USER}
TODAY = date(2026, 10, 28)
PID = "ab12cd34ef56ab78"
EID = "e" * 32
RECEIPT = "01 Receipts/2024-08/2024-08-14 Novex £51.90.pdf"
STATEMENT = "04 Bank statements/2025-01-31_starling.csv"
REPORT = "07 Reports/2025-03-31 Profit and loss.xlsx"
NEW_RECEIPT = "01 Receipts/2026-10/2026-10-02 Screwfix £12.00.pdf"
INVOICE = "03 Sales/invoices/INV-0001.json"
VAT_RETURN = "06 VAT returns/24A3/return.json"
INBOX_COPY = "00 Inbox/scan0001.pdf"
PDF = b"%PDF-1.4 the Novex receipt"


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
        doc_sha256=hashlib.sha256(PDF).hexdigest(),
        extracted=doc,
        checks=[],
        status="posted",
        reasons=[],
        suggested_filename="2024-08-14 Novex £51.90.pdf",
        journal_draft=[],
        model="stub",
        elapsed_s=1.0,
        file_path=RECEIPT,
        event_id=EID,
    )


@pytest.fixture(autouse=True)
def _today(monkeypatch: pytest.MonkeyPatch) -> None:
    for mod in (fm, archive, backups):
        monkeypatch.setattr(mod, "current_date", lambda: TODAY)


@pytest.fixture
async def books() -> Books:
    fake = FakeStorageProvider()
    b = Books(fake)
    await b.ensure_tree()
    await b.post_event(_event())
    await b.save_proposal(_proposal())
    await fake.write(RECEIPT, PDF)
    await fake.write(INBOX_COPY, PDF)  # the same bytes: a duplicate
    await fake.write(STATEMENT, b"Date,Amount\n2025-01-31,-51.90\n")
    await b.write_json(
        "_System/bank/" + "b" * 64 + ".json",
        [
            {
                "id": "c" * 16,
                "date": "2025-01-31",
                "amount_pence": -5190,
                "description": "NOVEX",
                "source_file": STATEMENT,
                "status": "unmatched",
            }
        ],
    )
    await fake.write(REPORT, b"xlsx bytes " * 50)
    await fake.write(NEW_RECEIPT, b"%PDF-1.4 this year")
    await fake.write(INVOICE, b'{"number": "INV-0001"}')
    await fake.write(VAT_RETURN, b'{"periodKey": "24A3"}')
    await fake.write("README.txt", b"These are your books.")
    await b.audit(f"user:{USER}", "approved", {"proposal": PID})
    return b


def _fake(b: Books) -> FakeStorageProvider:
    assert isinstance(b.storage, FakeStorageProvider)
    return b.storage


def _events(b: Books) -> dict[str, bytes]:
    return {p: d for p, d in _fake(b).files.items() if p.startswith("_System/Ledger/events/")}


async def _audit_actions(b: Books) -> list[str]:
    raw = _fake(b).files[f"_System/audit/{datetime.now(UTC):%Y-%m}.jsonl"]
    return [json.loads(line)["action"] for line in raw.decode().splitlines()]


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
# Years and dates
# --------------------------------------------------------------------------- #


def test_tax_and_financial_years() -> None:
    assert fm.year_of(date(2026, 4, 5)).label == "2025-26"
    assert fm.year_of(date(2026, 4, 6)).label == "2026-27"
    fy = fm.year_of(date(2026, 1, 15), "financial", 12, 31)
    assert (fy.label, fy.start, fy.end) == ("2026", date(2026, 1, 1), date(2026, 12, 31))
    fy = fm.year_of(date(2026, 3, 1), "financial", 2, 29)  # a 29 February year end in a non-leap year
    assert (fy.start, fy.end) == (date(2026, 3, 1), date(2027, 2, 28))
    assert fm.year_of(date(2025, 6, 1), "financial", 3, 31).label == "2025-26"


def test_a_document_is_dated_by_its_link_then_its_name_then_its_folder_then_modified() -> None:
    mod = datetime(2023, 1, 2, tzinfo=UTC)
    assert fm.file_date("01 Receipts/2024-08/x.pdf", mod, date(2024, 7, 1)) == (date(2024, 7, 1), "document")
    assert fm.file_date("01 Receipts/2024-08/2024-08-14 a.pdf", mod) == (date(2024, 8, 14), "name")
    assert fm.file_date("01 Receipts/2024-08/a.pdf", mod) == (date(2024, 8, 1), "folder")
    assert fm.file_date("06 VAT returns/2026-Q2/a.json", mod) == (date(2026, 6, 30), "folder")
    assert fm.file_date("07 Reports/a.xlsx", mod) == (date(2023, 1, 2), "modified")


# --------------------------------------------------------------------------- #
# Overview, index, duplicates
# --------------------------------------------------------------------------- #


async def test_overview_counts_folders_and_years_and_finds_the_duplicate(books: Books) -> None:
    ov = await fm.overview(books)
    folders = {u.folder: u for u in ov.folders}
    assert folders["01 Receipts"].files == 2
    assert folders["_System"].files >= 3  # event, proposal, bank lines, audit
    assert ov.total_files == sum(u.files for u in ov.folders)
    years = {y.year: y.files for y in ov.years}
    assert years["2024-25"] == 3  # the receipt (its document's date), the statement and the report (their names)
    assert ov.largest[0].path == REPORT
    [group] = ov.duplicates
    assert {f.path for f in group.files} == {RECEIPT, INBOX_COPY}
    keep = next(f for f in group.files if f.keep)
    assert keep.path == RECEIPT and keep.linked  # the copy the books point at is the one kept
    assert ov.duplicate_bytes == len(PDF)


async def test_duplicates_without_a_listed_hash_are_found_by_reading_same_size_files(books: Books) -> None:
    class NoHash(FakeStorageProvider):
        def _ref(self, path: str, is_folder: bool = False) -> FileRef:
            return super()._ref(path, is_folder).model_copy(update={"content_hash": None})

    plain = NoHash()
    plain.files, plain.folders = dict(_fake(books).files), set(_fake(books).folders)
    groups = await fm.duplicates(Books(plain), [r for r in await plain.list("00 Inbox")] + [plain._ref(RECEIPT)], set())
    assert [sorted(f.path for f in g.files) for g in groups] == [sorted([INBOX_COPY, RECEIPT])]


async def test_index_carries_the_ledger_amount_and_marks_protected_files(books: Books) -> None:
    idx = await fm.index(books)
    by = {f.path: f for f in idx.files}
    receipt = by[RECEIPT]
    assert receipt.linked and receipt.linked.amount_pence == 5190 and receipt.linked.event_id == EID
    assert receipt.date == date(2024, 8, 14) and receipt.tax_year == "2024-25" and receipt.kind == "pdf"
    assert by[STATEMENT].linked and by[STATEMENT].linked.bank_lines == 1
    assert by[INVOICE].protected and by[VAT_RETURN].protected and by["README.txt"].protected
    assert not any(p.startswith("_System/") for p in by)
    assert "_System" not in idx.folders and "01 Receipts/2024-08" in idx.folders


# --------------------------------------------------------------------------- #
# Archive by year, links, undo
# --------------------------------------------------------------------------- #


async def test_archive_preview_lists_years_and_refuses_the_current_one(books: Books) -> None:
    pv = await archive.preview(books, None)
    labels = {y.label: y for y in pv.years}
    assert labels["2026-27"].current and not labels["2024-25"].current
    with pytest.raises(archive.ArchiveError, match="the year we are in"):
        await archive.preview(books, "2026-27")
    with pytest.raises(archive.ArchiveError, match="nothing from 1999-00"):
        await archive.preview(books, "1999-00")
    pv = await archive.preview(books, "2024-25")
    assert {m.old for m in pv.moves} == {RECEIPT, STATEMENT, REPORT}  # REPORT is dated 31 March 2025: 2024-25
    assert all(m.new == f"Archive/2024-25/{m.old}" for m in pv.moves)


async def test_archive_moves_documents_keeps_links_and_never_touches_the_ledger(books: Books) -> None:
    events_before = _events(books)
    r = await archive.run(books, "2024-25", USER)
    files = _fake(books).files
    assert f"Archive/2024-25/{RECEIPT}" in files and RECEIPT not in files
    assert f"Archive/2024-25/{STATEMENT}" in files
    assert NEW_RECEIPT in files and INVOICE in files and VAT_RETURN in files and INBOX_COPY in files
    assert _events(books) == events_before  # ledger events: same paths, same bytes

    # Links: the proposal and the bank line lead to the archived copies, without their files being rewritten.
    fresh = Books(_fake(books))
    assert (await fresh.get_proposal(PID)).file_path == f"Archive/2024-25/{RECEIPT}"
    assert [p.file_path for p in await fresh.list_proposals()] == [f"Archive/2024-25/{RECEIPT}"]
    assert [ln.source_file for ln in await fresh.stored_bank_lines()] == [f"Archive/2024-25/{STATEMENT}"]
    assert [s.path for s in await fresh.bank_statements()] == [f"Archive/2024-25/{STATEMENT}"]
    stored = json.loads(files["_System/archive/map.json"])["moved"]
    assert stored[RECEIPT] == f"Archive/2024-25/{RECEIPT}"
    idx = {f.path: f for f in (await fm.index(fresh)).files}
    assert idx[f"Archive/2024-25/{RECEIPT}"].linked.amount_pence == 5190  # type: ignore[union-attr]
    assert idx[f"Archive/2024-25/{RECEIPT}"].archived

    assert [run.id for run in await archive.list_runs(books)] == [r.id]
    assert "files_archived" in await _audit_actions(books)


async def test_undo_moves_everything_back_and_links_follow(books: Books) -> None:
    r = await archive.run(books, "2024-25", USER, make_zip=True)
    assert r.zips[0].path == "Archive/2024-25.zip"
    done = await archive.undo(books, r.id, USER)
    files = _fake(books).files
    assert RECEIPT in files and STATEMENT in files and REPORT in files
    assert not any(p.startswith("Archive/2024-25/") for p in files)
    assert "Archive/2024-25.zip" not in files
    assert f"_Trash/{TODAY}/Archive/2024-25.zip" in files  # the zip is never deleted
    assert done.undone_by == USER
    assert (await Books(_fake(books)).get_proposal(PID)).file_path == RECEIPT
    with pytest.raises(archive.ArchiveError, match="already been undone"):
        await archive.undo(books, r.id, USER)
    # Archive again after the undo: the map stays one hop and has no cycle.
    await archive.run(books, "2024-25", USER)
    moved = await books.moved_paths()
    assert follow(moved, RECEIPT) == f"Archive/2024-25/{RECEIPT}"
    assert f"Archive/2024-25/{RECEIPT}" not in moved
    assert (await Books(_fake(books)).get_proposal(PID)).file_path == f"Archive/2024-25/{RECEIPT}"
    assert "archive_undone" in await _audit_actions(books)


async def test_undo_skips_a_file_the_user_has_moved_since(books: Books) -> None:
    r = await archive.run(books, "2024-25", USER)
    await _fake(books).move(f"Archive/2024-25/{REPORT}", "07 Reports/mine.xlsx")
    done = await archive.undo(books, r.id, USER)
    assert done.undo_skipped == [f"Archive/2024-25/{REPORT}"]
    assert RECEIPT in _fake(books).files


async def test_the_year_zip_holds_every_file_and_a_manifest_with_hashes(books: Books) -> None:
    r = await archive.run(books, "2024-25", USER, make_zip=True)
    raw = _fake(books).files[r.zips[0].path or ""]
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        man = json.loads(z.read("manifest.json"))
        assert {e["path"] for e in man["files"]} == {RECEIPT, STATEMENT, REPORT}
        for e in man["files"]:
            assert hashlib.sha256(z.read(e["path"])).hexdigest() == e["sha256"]
    assert f"Archive/2024-25/{RECEIPT}" in _fake(books).files  # the folder stays: the zip is a copy


def test_record_moves_has_no_chains_or_cycles() -> None:
    import asyncio

    async def go() -> dict[str, str]:
        b = Books(FakeStorageProvider())
        await b.record_moves([("a", "b")])
        await b.record_moves([("b", "c")])
        assert await b.moved_paths() == {"a": "c", "b": "c"}
        await b.record_moves([("c", "a")])  # back where it started
        return await b.moved_paths()

    moved = asyncio.run(go())
    assert follow(moved, "a") == "a" and follow(moved, "b") == "a" and follow(moved, "c") == "a"


# --------------------------------------------------------------------------- #
# Move, rename, Clean up
# --------------------------------------------------------------------------- #


async def test_move_and_rename_record_redirects_and_refuse_protected_files(books: Books) -> None:
    [m] = await fm.move_files(books, [RECEIPT], "07 Reports/Old receipts", USER)
    assert m.new == "07 Reports/Old receipts/2024-08-14 Novex £51.90.pdf"
    assert (await Books(_fake(books)).get_proposal(PID)).file_path == m.new
    r = await fm.rename_file(books, m.new, '  Novex: "August"?  ', USER)
    assert r.new == "07 Reports/Old receipts/Novex August.pdf"
    assert (await Books(_fake(books)).get_proposal(PID)).file_path == r.new
    with pytest.raises(fm.FileError, match="looks after itself"):
        await fm.move_files(books, [INVOICE], "07 Reports", USER)
    with pytest.raises(fm.FileError, match="cannot be moved into"):
        await fm.move_files(books, [NEW_RECEIPT], "_System/docs", USER)
    with pytest.raises(fm.FileError):
        await fm.rename_file(books, VAT_RETURN, "x.json", USER)
    with pytest.raises(fm.FileError, match="letters or numbers"):
        await fm.rename_file(books, NEW_RECEIPT, " ... ", USER)
    slash = await fm.rename_file(books, NEW_RECEIPT, "October/Screwfix", USER)
    assert slash.new == "01 Receipts/2026-10/October Screwfix.pdf"  # a path becomes a plain name
    await _fake(books).write("07 Reports/Old receipts/other.pdf", b"o")
    with pytest.raises(FileExistsError):
        await fm.rename_file(books, r.new, "OTHER", USER)  # OneDrive names ignore case
    actions = await _audit_actions(books)
    assert "files_moved" in actions and "file_renamed" in actions


async def test_rename_keeps_the_extension_and_refuses_a_taken_name(books: Books) -> None:
    await _fake(books).write("07 Reports/b.xlsx", b"b")
    r = await fm.rename_file(books, REPORT, "Profit and loss 2024-25", USER)
    assert r.new == "07 Reports/Profit and loss 2024-25.xlsx"
    with pytest.raises(FileExistsError):
        await fm.rename_file(books, r.new, "B.xlsx", USER)


async def test_clean_up_moves_a_duplicate_to_trash_and_refuses_linked_documents(books: Books) -> None:
    [m] = await fm.trash_files(books, [INBOX_COPY], USER)
    assert m.new == f"_Trash/{TODAY}/{INBOX_COPY}"
    assert _fake(books).files[m.new] == PDF  # moved, not deleted
    with pytest.raises(fm.FileError, match="linked from your books"):
        await fm.trash_files(books, [RECEIPT], USER)
    with pytest.raises(fm.FileError, match="linked from your books"):
        await fm.trash_files(books, [STATEMENT], USER)
    assert "files_trashed" in await _audit_actions(books)
    assert not (await fm.overview(books)).duplicates


# --------------------------------------------------------------------------- #
# Backups
# --------------------------------------------------------------------------- #


async def test_backup_zip_holds_all_of_system_with_a_manifest_and_checksum(books: Books) -> None:
    res = await backups.back_up(books, f"user:{USER}")
    b = res.backup
    assert b.path == f"Backups/accnomos-backup-{TODAY}.zip"
    files = _fake(books).files
    raw = files[b.path]
    assert files[f"{b.path}.sha256"].decode() == f"{hashlib.sha256(raw).hexdigest()}  {b.name}\n"
    system = {p for p in files if p.startswith("_System/")}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        man = json.loads(z.read("manifest.json"))
        assert set(z.namelist()) - {"manifest.json"} == {e["path"] for e in man["files"]}
        assert {e["path"] for e in man["files"]} <= system
        for prefix in ("_System/Ledger/events/", "_System/proposals/", "_System/audit/", "_System/bank/"):
            assert any(e["path"].startswith(prefix) for e in man["files"]), prefix
        for e in man["files"]:
            assert hashlib.sha256(z.read(e["path"])).hexdigest() == e["sha256"]
            if not e["path"].startswith("_System/audit/"):  # the backup's own audit line came after the zip
                assert e["sha256"] == hashlib.sha256(files[e["path"]]).hexdigest()
    assert man["files_sha256"] == backups.files_digest(man["files"])
    v = await backups.verify(books, b.path, USER)
    assert v.ok and v.checksum == "ok" and v.problems == []
    second = await backups.back_up(books, f"user:{USER}")
    assert second.backup.name == f"accnomos-backup-{TODAY} (2).zip"
    assert [x.name for x in await backups.list_backups(books)] == [second.backup.name, b.name]


async def test_verify_catches_a_changed_zip_and_a_missing_checksum(books: Books) -> None:
    b = (await backups.back_up(books, f"user:{USER}")).backup
    fake = _fake(books)
    good = fake.files[b.path]
    fake.files[b.path] = good + b"x"
    v = await backups.verify(books, b.path, USER)
    assert not v.ok and v.checksum == "mismatch"
    fake.files[b.path] = good
    del fake.files[f"{b.path}.sha256"]
    v = await backups.verify(books, b.path, USER)
    assert not v.ok and v.checksum == "missing"
    with pytest.raises(FileNotFoundError):
        await backups.verify(books, RECEIPT, USER)  # only files in Backups/ named like a backup
    assert "backup_verified" in await _audit_actions(books)


async def test_retention_keeps_the_newest_and_moves_the_rest_to_trash(books: Books) -> None:
    await backups.save_settings(books, backups.FileSettings(backup_keep=2), USER)
    made = [(await backups.back_up(books, f"user:{USER}", day=date(2026, m, 1))).backup.path for m in (6, 7, 8, 9)]
    kept = [b.path for b in await backups.list_backups(books)]
    assert kept == [made[3], made[2]]
    files = _fake(books).files
    for old in made[:2]:
        assert old not in files
        assert f"_Trash/{TODAY}/{old}" in files and f"_Trash/{TODAY}/{old}.sha256" in files


async def test_restore_preview_then_refusal_without_confirmation_then_restore(books: Books) -> None:
    b = (await backups.back_up(books, f"user:{USER}")).backup
    fake = _fake(books)
    contacts = "_System/Contacts/contacts.json"
    await fake.write(contacts, b"[]")  # made after the backup: restore never deletes it
    rules = "_System/rules.json"
    await fake.write(rules, b"[]")
    b2 = (await backups.back_up(books, f"user:{USER}")).backup
    await fake.write(rules, b'[{"changed": true}]')  # changed since b2
    del fake.files[f"_System/proposals/{PID}.json"]  # lost since b2
    [audit_file] = [p for p in fake.files if p.startswith("_System/audit/") and p.endswith(".jsonl")]
    pv = await backups.restore_preview(books, b2.path)
    st = {i.path: i.status for i in pv.items}
    assert st[rules] == "changed" and st[f"_System/proposals/{PID}.json"] == "new"
    assert st[audit_file] == "kept"  # the audit log grew since: append-only, never replaced
    assert all(s == "same" for p, s in st.items() if p.startswith("_System/Ledger/events/"))
    assert pv.needs_confirmation and not pv.books_empty

    with pytest.raises(backups.ConfirmationNeeded):
        await backups.restore(books, b2.path, USER, None)
    with pytest.raises(backups.ConfirmationNeeded):
        await backups.restore(books, b2.path, USER, "restore please")
    assert fake.files[rules] == b'[{"changed": true}]'  # nothing written by the refusals

    audit_before = fake.files[audit_file]
    res = await backups.restore(books, b2.path, USER, "RESTORE")
    assert (res.restored, res.replaced) == (1, 1)
    assert fake.files[rules] == b"[]" and f"_System/proposals/{PID}.json" in fake.files
    assert fake.files[contacts] == b"[]"  # not in b? it is in b2: same; still there either way
    assert res.trash and any(p.startswith(res.trash) and p.endswith("rules.json") for p in fake.files)
    assert fake.files[audit_file].startswith(audit_before)  # the audit file was appended to, never replaced
    assert "backup_restored" in await _audit_actions(books)
    assert b.path in fake.files


async def test_restore_into_empty_books_needs_no_confirmation(books: Books) -> None:
    b = (await backups.back_up(books, f"user:{USER}")).backup
    empty = FakeStorageProvider()
    for p in (b.path, f"{b.path}.sha256"):
        empty.files[p] = _fake(books).files[p]
    target = Books(empty)
    pv = await backups.restore_preview(target, b.path)
    assert pv.books_empty and not pv.needs_confirmation and pv.counts["changed"] == 0
    res = await backups.restore(target, b.path, USER, None)
    assert res.replaced == 0 and res.restored == pv.counts["new"]
    assert {p for p in _fake(books).files if p.startswith("_System/Ledger/")} <= set(empty.files)
    assert (await target.get_proposal(PID)).event_id == EID


async def test_a_backup_naming_a_path_outside_system_is_refused(books: Books) -> None:
    buf = io.BytesIO()
    entries: list[dict[str, Any]] = [{"path": "../evil.txt", "size": 1, "sha256": hashlib.sha256(b"x").hexdigest()}]
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../evil.txt", b"x")
        z.writestr("manifest.json", json.dumps({"files": entries, "files_sha256": backups.files_digest(entries)}))
    raw = buf.getvalue()
    path = f"Backups/accnomos-backup-{TODAY}.zip"
    await _fake(books).write(path, raw)
    await _fake(books).write(f"{path}.sha256", f"{hashlib.sha256(raw).hexdigest()}  x\n".encode())
    v = await backups.verify(books, path, USER)
    assert not v.ok and any("outside _System" in p for p in v.problems)
    with pytest.raises(backups.BackupError, match="does not pass its checks"):
        await backups.restore(books, path, USER, "RESTORE")


async def test_monthly_backup_runs_once_a_month_and_only_when_switched_on(books: Books) -> None:
    assert await backups.maybe_monthly(books) is None  # off by default
    await backups.save_settings(books, backups.FileSettings(monthly_backup=True), USER)
    first = await backups.maybe_monthly(books)
    assert first is not None and first.backup.day == TODAY
    assert await backups.maybe_monthly(books) is None  # this month has one
    raw = _fake(books).files[f"_System/audit/{datetime.now(UTC):%Y-%m}.jsonl"].decode().splitlines()
    assert json.loads(raw[-1])["actor"] == "agent:backup"


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


def test_routes_overview_index_archive_undo_and_backups(client: TestClient, books: Books) -> None:
    assert client.get("/files/overview", headers=H).json()["duplicates"]
    assert any(f["path"] == RECEIPT for f in client.get("/files/index", headers=H).json()["files"])
    assert client.post("/files/archive/preview", json={"up_to": "2026-27"}, headers=H).status_code == 400
    r = client.post("/files/archive", json={"up_to": "2024-25", "zip": True}, headers=H)
    assert r.status_code == 200, r.text
    run_id = r.json()["id"]
    assert client.get("/files/archive/runs", headers=H).json()[0]["id"] == run_id
    assert client.post(f"/files/archive/runs/{run_id}/undo", headers=H).status_code == 200
    assert client.post(f"/files/archive/runs/{run_id}/undo", headers=H).status_code == 409
    assert client.post("/files/archive/runs/nothere/undo", headers=H).status_code == 404

    made = client.post("/backups", headers=H).json()["backup"]
    assert client.post("/backups/verify", json={"path": made["path"]}, headers=H).json()["ok"]
    pv = client.post("/backups/restore/preview", json={"path": made["path"]}, headers=H).json()
    assert pv["needs_confirmation"] and pv["confirm_word"] == "RESTORE"
    refused = client.post("/backups/restore", json={"path": made["path"]}, headers=H)
    assert refused.status_code == 409 and "type RESTORE" in refused.json()["detail"]
    ok = client.post("/backups/restore", json={"path": made["path"], "confirm": "RESTORE"}, headers=H)
    assert ok.status_code == 200, ok.text
    s = client.put("/backups/settings", json={"backup_keep": 1, "monthly_backup": True}, headers=H)
    assert s.json() == {"backup_keep": 1, "monthly_backup": True}
    assert client.get("/backups", headers=H).json()["settings"]["backup_keep"] == 1
    assert client.post("/backups/auto", headers=H).json()["ran"] is False  # one is dated this month already


def test_route_writes_need_x_user_and_refuse_bad_input(client: TestClient) -> None:
    no_user = {"X-Graph-Token": "tok"}
    for path, body in (
        ("/files/move", {"paths": [RECEIPT], "to": "07 Reports"}),
        ("/files/rename", {"path": RECEIPT, "name": "x"}),
        ("/files/trash", {"paths": [INBOX_COPY]}),
        ("/files/archive", {"up_to": "2024-25"}),
        ("/backups", None),
        ("/backups/restore", {"path": "Backups/x.zip"}),
    ):
        r = client.post(path, json=body, headers=no_user)
        assert r.status_code in (400, 422) and "x-user" in r.text.lower(), path
    assert client.post("/files/trash", json={"paths": [RECEIPT]}, headers=H).status_code == 400
    assert client.post("/files/move", json={"paths": [RECEIPT], "to": "_System"}, headers=H).status_code == 400
    missing = client.post("/files/rename", json={"path": "07 Reports/none.xlsx", "name": "x"}, headers=H)
    assert missing.status_code == 404
    assert client.post("/files/move", json={"paths": [RECEIPT], "to": "x", "extra": 1}, headers=H).status_code == 422


def test_every_new_audit_action_reads_as_a_sentence() -> None:
    s = audit_view.summarise
    assert s("files_moved", {"to": "07 Reports", "moved": [{}, {}]}) == "Moved 2 files to 07 Reports"
    assert s("file_renamed", {"old": "a/b.pdf", "new": "a/c.pdf"}) == "Renamed b.pdf to c.pdf"
    assert s("files_archived", {"files": 3, "up_to": "2024-25", "years": ["2024-25"], "zips": ["x"]}) == (
        "Archived 3 files up to 2024-25 into 2024-25 and zipped them"
    )
    assert s("backup_created", {"file": "Backups/x.zip", "files": 9, "retired": ["y"]}) == (
        "Backed up your books: 9 files in x.zip; 1 older backup moved to _Trash"
    )
    assert s("backup_verified", {"file": "Backups/x.zip", "ok": True}) == "Checked x.zip: checksum and every file match"
    assert s("backup_restored", {"file": "Backups/x.zip", "restored": 2, "replaced": 1}).startswith("Restored x.zip")
    assert audit_view.actor_of("agent:backup") == ("agent", "Backup")
