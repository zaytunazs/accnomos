"""Bulk upload (01 Bulk upload): safe zips, batch summary, confirm-all routing, launch check.

Against FakeStorageProvider with a stubbed classifier (no model calls).
"""

from __future__ import annotations

import asyncio
import io
import sys
import zipfile
from pathlib import Path

import pytest

from accnomos_connectors import FakeStorageProvider

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import bulk  # noqa: E402
from app.books import Books, DocMeta  # noqa: E402
from app.bulk import (  # noqa: E402
    BulkError,
    BulkRow,
    category_of,
    confirm_job,
    plan_unpack,
    start_job,
    summarise,
)
from app.launchcheck import _hex, _modified_after, launch_check  # noqa: E402
from app.paths import BANK, BULK, INBOX  # noqa: E402
from app.pipeline import sha256_hex  # noqa: E402
from app.schemas import ExtractedDoc, Proposal  # noqa: E402


def _doc(doc_type: str = "receipt", supplier: str = "Screwfix", gross: float = 38.47) -> ExtractedDoc:
    return ExtractedDoc(
        doc_type=doc_type,  # type: ignore[arg-type]
        supplier_name=supplier,
        supplier_vat_number=None,
        customer_name=None,
        invoice_number=None,
        date="2026-10-21",
        currency="GBP",
        lines=[],
        net_total=gross,
        vat_total=0.0,
        gross_total=gross,
        payment_method="card",
        card_last4=None,
        category_guess="Sundry",
        confidence=0.9,
    )


def _proposal(name: str, data: bytes, doc_type: str = "receipt") -> Proposal:
    return Proposal(
        id=sha256_hex(data)[:12],
        doc_sha256=sha256_hex(data),
        extracted=_doc(doc_type),
        checks=[],
        status="proposed",
        reasons=[],
        suggested_filename=name,
        journal_draft=[],
        model="stub",
        elapsed_s=0.0,
    )


def _zip(**members: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _books() -> tuple[FakeStorageProvider, Books]:
    fake = FakeStorageProvider()
    return fake, Books(fake)


# --------------------------------------------------------------------------- #
# Zip safety
# --------------------------------------------------------------------------- #


def test_traversal_entries_are_skipped_and_honest_files_unpack() -> None:
    data = _zip(**{"../evil.txt": b"x", "/abs.txt": b"x", "ok/receipt.pdf": b"y" * 100, "ok/../../up.pdf": b"z"})
    members = plan_unpack(data, "batch.zip", max_files=200, max_bytes=200 * 1024 * 1024)
    assert [(m.name, m.note) for m in members] == [("receipt.pdf", "from batch.zip/ok")]
    assert all(not m.name.startswith((".", "/")) for m in members)


def test_windows_drive_and_empty_names_are_skipped() -> None:
    data = _zip(**{"C:/secret.txt": b"x", "ok/": b"", "..": b"x", "fine.jpg": b"y"})
    members = plan_unpack(data, "b.zip", max_files=200, max_bytes=200 * 1024 * 1024)
    assert [m.name for m in members] == ["fine.jpg"]


def test_file_count_cap_counts_the_whole_batch() -> None:
    data = _zip(**{f"f{i}.pdf": b"y" for i in range(5)})
    with pytest.raises(BulkError, match="more than 4 files"):
        plan_unpack(data, "b.zip", max_files=4, max_bytes=10**9, already_files=2)


def test_byte_cap_counts_the_whole_batch() -> None:
    data = _zip(**{"a.pdf": b"y" * 100})
    with pytest.raises(BulkError, match="more than 0 MB"):
        plan_unpack(data, "b.zip", max_files=200, max_bytes=50, already_bytes=0)


def test_unreadable_zip_is_an_error_not_a_crash() -> None:
    with pytest.raises(BulkError, match="not a readable zip"):
        plan_unpack(b"definitely not a zip", "b.zip", max_files=200, max_bytes=10**9)


def test_caps_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCNOMOS_BULK_MAX_FILES", "3")
    monkeypatch.setenv("ACCNOMOS_BULK_MAX_BYTES", "7")
    assert bulk.bulk_limits() == (3, 7)
    monkeypatch.setenv("ACCNOMOS_BULK_MAX_FILES", "nonsense")
    assert bulk.bulk_limits()[0] == bulk.DEFAULT_MAX_FILES


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #


def test_summary_buckets_and_counts() -> None:
    rows = [
        BulkRow(name="a", path="b/a", doc_type="receipt"),
        BulkRow(name="b", path="b/b", doc_type="purchase_invoice"),
        BulkRow(name="c", path="b/c", doc_type="sales_invoice"),
        BulkRow(name="d", path="b/d", doc_type="bank_statement"),
        BulkRow(name="e", path="b/e", doc_type="weird"),
        BulkRow(name="f", path="b/f", status="failed", reason="boom"),
    ]
    assert summarise(rows) == "2 receipts, 1 invoice, 1 bank statement, 2 unclear"
    assert category_of("credit_note") == "unclear"
    assert summarise([]) == "nothing to file"


# --------------------------------------------------------------------------- #
# Batch jobs with a stub classifier
# --------------------------------------------------------------------------- #


def _classifier(seen: dict[str, str], max_in_flight: list[int]) -> bulk.Classifier:
    in_flight = 0

    async def classify(name: str, data: bytes) -> Proposal:
        nonlocal in_flight
        in_flight += 1
        max_in_flight.append(in_flight)
        try:
            await asyncio.sleep(0.01)  # overlap, so the test can see the semaphore work
            kind = seen.get(name, "receipt")
            return _proposal(name, data, kind)
        finally:
            in_flight -= 1

    return classify


async def test_start_unpacks_classifies_and_summarises() -> None:
    fake, books = _books()
    await books.ensure_tree()
    await fake.write(f"{BULK}/batch.zip", _zip(**{"jan/receipt.pdf": b"a" * 500, "stmt.csv": b"1,2,3"}))
    await fake.write(f"{BULK}/loose.jpg", b"\xff\xd8" + b"b" * 500)

    max_in_flight: list[int] = []
    job = await start_job(
        books,
        None,  # type: ignore[arg-type]
        classifier=_classifier({"receipt.pdf": "receipt", "loose.jpg": "sales_invoice"}, max_in_flight),
    )
    assert job.summary == "1 receipt, 1 invoice, 1 bank statement"
    by_name = {r.name: r for r in job.rows}
    assert by_name["receipt.pdf"].source_note == "from batch.zip/jan"
    assert by_name["stmt.csv"].doc_type == "bank_statement"
    assert by_name["loose.jpg"].doc_type == "sales_invoice"
    assert max(max_in_flight) <= bulk.CLASSIFY_CONCURRENCY == 2
    # The zip is trashed (never deleted), its files are loose in the bulk folder.
    assert [f.name for f in await books.list_files(BULK) if f.name.endswith(".zip")] == []
    assert any(p.endswith("/batch.zip") for p in fake.files)
    assert (await books.get_proposal(by_name["receipt.pdf"].proposal_id or "")).source_note == ("from batch.zip/jan")


async def test_unreadable_files_stay_with_a_reason() -> None:
    fake, books = _books()
    await books.ensure_tree()
    await fake.write(f"{BULK}/notes.txt", b"hello")
    await fake.write(f"{BULK}/empty.pdf", b"")

    async def boom(name: str, data: bytes) -> Proposal:
        raise RuntimeError("reader down")

    job = await start_job(books, None, classifier=boom)  # type: ignore[arg-type]
    by_name = {r.name: r for r in job.rows}
    assert by_name["notes.txt"].status == "failed" and "Not a document" in (by_name["notes.txt"].reason or "")
    assert by_name["empty.pdf"].status == "failed"
    assert job.summary == "2 unclear"


async def test_confirm_all_routes_and_moves_files_out() -> None:
    fake, books = _books()
    await books.ensure_tree()
    await fake.write(f"{BULK}/receipt.pdf", b"a" * 500)
    await fake.write(f"{BULK}/stmt.csv", b"1,2,3")
    job = await start_job(books, None, classifier=_classifier({}, []))  # type: ignore[arg-type]

    confirmed = await confirm_job(books, job.id, edits={f"{BULK}/receipt.pdf": "sales_invoice"})
    assert confirmed.status == "confirmed"
    assert all(r.status == "routed" for r in confirmed.rows)
    assert [f.name for f in await books.list_files(BULK)] == []
    assert len(await books.list_files(f"{BANK}")) == 1  # the statement CSV
    proposal = await books.get_proposal(confirmed.rows[0].proposal_id or "")
    assert proposal.extracted.doc_type == "sales_invoice"
    assert (proposal.file_path or "").startswith("03 Sales/")


async def test_confirm_rejects_unknown_types_and_keeps_failures() -> None:
    fake, books = _books()
    await books.ensure_tree()
    await fake.write(f"{BULK}/receipt.pdf", b"a" * 500)
    job = await start_job(books, None, classifier=_classifier({}, []))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Unknown document type"):
        await confirm_job(books, job.id, edits={f"{BULK}/receipt.pdf": "ledger"})
    assert [f.name for f in await books.list_files(BULK)] == ["receipt.pdf"]


# --------------------------------------------------------------------------- #
# Launch check
# --------------------------------------------------------------------------- #


async def _filed(books: Books, name: str, data: bytes, filed_as: str | None = None) -> None:
    await books.save_doc(
        DocMeta(
            sha256=sha256_hex(data),
            source_name=name,
            mime="application/pdf",
            size=len(data),
            proposal_id="p1",
            filed_path=filed_as,
        )
    )


async def test_launch_check_new_changed_and_known() -> None:
    fake, books = _books()
    await books.ensure_tree()
    await _filed(books, "old.pdf", b"original-bytes")
    await fake.write(f"{BULK}/old.pdf", b"original-bytes")  # same bytes: already filed
    await fake.write(f"{BULK}/changed.pdf", b"v1-bytes")  # placeholder, replaced below
    await fake.write(f"{INBOX}/brand-new.jpg", b"z" * 100)
    await _filed(books, "changed.pdf", b"v1-bytes-different")

    # Same name, different bytes/size than the filed copy: changed, not new.
    await fake.write(f"{BULK}/changed.pdf", b"v2-bytes-much-longer")
    result = await launch_check(books)
    assert result.checked == 3
    assert result.new == [f"{INBOX}/brand-new.jpg"]
    assert [(c.path, c.reason) for c in result.changed] == [
        (f"{BULK}/changed.pdf", "different content than the filed copy under this name")
    ]


async def test_launch_check_same_bytes_are_known_and_resized_are_changed() -> None:
    fake, books = _books()
    await books.ensure_tree()
    await _filed(books, "scan.pdf", b"12345678")
    await fake.write(f"{BULK}/scan.pdf", b"12345678")
    result = await launch_check(books)  # same bytes: the filed copy
    assert result.new == [] and result.changed == []

    await fake.write(f"{BULK}/scan.pdf", b"123456789-different-size")
    result = await launch_check(books)
    assert [c.path for c in result.changed] == [f"{BULK}/scan.pdf"]


def test_hex_only_trusts_sha256() -> None:
    assert _hex("sha256:" + "a" * 64) == "a" * 64
    assert _hex("quickXorHash:abc") is None
    assert _hex(None) is None
    assert _hex("no-colon") is None


def test_modified_after_needs_a_clearly_newer_date() -> None:
    from datetime import UTC, datetime

    saved = [{"saved_at": "2026-10-20T10:00:00+00:00", "size": 5, "sha256": "x"}]
    assert _modified_after(datetime(2026, 10, 21, tzinfo=UTC), saved) is True
    assert _modified_after(datetime(2026, 10, 20, 10, 0, 30, tzinfo=UTC), saved) is False
    assert _modified_after(None, saved) is False


async def test_launch_check_lists_only_and_never_downloads_documents() -> None:
    fake, books = _books()
    await books.ensure_tree()
    await fake.write(f"{BULK}/a.pdf", b"a" * 100)
    await fake.write(f"{INBOX}/b.jpg", b"b" * 100)
    downloads = [p for p in list(fake.files) if not p.startswith("_System")]
    reads: list[str] = []
    real_read = fake.read

    async def spy(path: str) -> bytes:
        reads.append(path)
        return await real_read(path)

    fake.read = spy  # type: ignore[method-assign]
    try:
        result = await launch_check(books)
    finally:
        fake.read = real_read  # type: ignore[method-assign]
    assert result.checked == 2 and result.new == [f"{BULK}/a.pdf", f"{INBOX}/b.jpg"]
    assert not any(r in downloads for r in reads), f"documents were downloaded: {reads}"
