"""Intake format limits (app/formats.py, docs/SECURITY.md): 25 MB, 50 million pixels, 20 PDF pages, type sniffed
from the bytes; refusals are clean messages on every path in (Inbox scan, POST /extract, Outlook intake)."""

from __future__ import annotations

import struct
import sys
import time
import types
import zlib
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeMailProvider, FakeStorageProvider, MailMessage
from app import pipeline
from app.ai.config import AiConfig, ai_config_from_request
from app.books import Books, now
from app.formats import (
    MAX_BYTES,
    MAX_PDF_PAGES,
    MAX_PIXELS,
    MAX_TEXT_CHARS,
    RENDER_MAX_SIDE,
    FormatError,
    prepare,
    render_scale,
)
from app.inbox import scan_inbox_detailed
from app.intake import BODY_MAX_CHARS, scan_mail
from app.main import app

LOCAL = AiConfig(mode="local", base_url="http://ollama.invalid", model="stub")


def png_header(width: int, height: int) -> bytes:
    """A PNG that declares `width` × `height` but carries almost no data: what an image bomb looks like."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"")) + chunk(b"IEND", b"")


class FakePdfium(types.ModuleType):
    """Stands in for pypdfium2 so the page limit and password refusal are tested whether or not it is installed."""

    class PdfiumError(RuntimeError):
        pass

    def __init__(self, pages: int = 1, error: str | None = None) -> None:
        super().__init__("pypdfium2")
        self.pages, self.error, self.closed = pages, error, False
        outer = self

        class PdfDocument:
            def __init__(self, data: bytes) -> None:
                if outer.error:
                    raise FakePdfium.PdfiumError(outer.error)

            def __len__(self) -> int:
                return outer.pages

            def __getitem__(self, i: int) -> object:
                raise AssertionError("no page may be read when the document is refused")

            def close(self) -> None:
                outer.closed = True

        self.PdfDocument = PdfDocument


# --------------------------------------------------------------------------- size


def test_over_25_mb_is_refused_before_anything_is_decoded() -> None:
    with pytest.raises(FormatError, match="limit is 25 MB"):
        prepare(b"%PDF-" + b"\x00" * MAX_BYTES, "big.pdf")


def test_empty_file_is_refused() -> None:
    with pytest.raises(FormatError, match="empty"):
        prepare(b"", "r.jpg")


# --------------------------------------------------------------------------- pixels


@pytest.mark.parametrize("side", [8_000, 20_000, 100_000])  # 64 MP (ours), 400 MP and 10 GP (Pillow's own guard too)
def test_image_bombs_are_refused_from_the_header(side: int) -> None:
    started = time.perf_counter()
    with pytest.raises(FormatError, match="pixel"):
        prepare(png_header(side, side), "bomb.png")
    assert time.perf_counter() - started < 1  # nothing was decoded


def test_a_48_megapixel_phone_photo_is_within_the_limit() -> None:
    assert MAX_PIXELS >= 8064 * 6048


def test_pdf_render_is_capped_however_big_the_page_claims_to_be() -> None:
    for w_pt, h_pt in [(595, 842), (14_400, 14_400), (1, 1_000_000), (0, 0)]:
        s = render_scale(w_pt, h_pt)
        assert max(w_pt, 1) * s <= RENDER_MAX_SIDE + 1 and max(h_pt, 1) * s <= RENDER_MAX_SIDE + 1
        assert (max(w_pt, 1) * s) * (max(h_pt, 1) * s) <= MAX_PIXELS


# --------------------------------------------------------------------------- PDF


def test_pdf_over_20_pages_is_refused_without_reading_a_page(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePdfium(pages=MAX_PDF_PAGES + 1)
    monkeypatch.setitem(sys.modules, "pypdfium2", fake)
    with pytest.raises(FormatError, match="21 pages; up to 20"):
        prepare(b"%PDF-1.7 batch", "batch.pdf")
    assert fake.closed


def test_password_protected_pdf_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules, "pypdfium2", FakePdfium(error="Failed to load document (PDFium: Incorrect password)")
    )
    with pytest.raises(FormatError, match="password-protected"):
        prepare(b"%PDF-1.7 locked", "locked.pdf")


def test_real_pdf_over_20_pages() -> None:
    pytest.importorskip("pypdfium2")
    from fpdf import FPDF

    pdf = FPDF()
    for _ in range(MAX_PDF_PAGES + 1):
        pdf.add_page()
    with pytest.raises(FormatError, match="up to 20"):
        prepare(bytes(pdf.output()), "batch.pdf")


def test_damaged_pdf_is_refused_cleanly() -> None:
    pytest.importorskip("pypdfium2")
    with pytest.raises(FormatError, match="damaged or not a PDF"):
        prepare(b"%PDF-1.7\nthis is not a pdf", "x.pdf")


# --------------------------------------------------------------------------- type sniffing


def test_type_comes_from_the_bytes_not_the_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    with pytest.raises(FormatError, match="PDF"):  # a PDF named .jpg still goes down the PDF path
        prepare(b"%PDF-1.7 ...", "photo.jpg")
    with pytest.raises(FormatError, match="not one"):
        prepare(b"\xff\xd8\xff not a pdf", "invoice.pdf")


def test_other_image_types_are_refused() -> None:
    with pytest.raises(FormatError, match="GIF images are not accepted"):
        prepare(
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,"
            b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            "open.png",
        )


def test_binary_dressed_as_text_is_refused() -> None:
    with pytest.raises(FormatError, match="binary"):
        prepare(b"MZ\x90\x00\x03\x00", "receipt.eml.txt")


# --------------------------------------------------------------------------- every path in


@pytest.fixture
def no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*_a: object, **_kw: object) -> None:
        raise AssertionError("a refused file must never reach a model")

    monkeypatch.setattr(pipeline, "extract_document", boom)
    monkeypatch.setattr(pipeline, "verify", boom)


async def test_inbox_refusals_become_cards_and_oversize_is_never_downloaded(
    no_model: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStorageProvider()
    fake.files.update(
        {
            "00 Inbox/bomb.png": png_header(20_000, 20_000),
            "00 Inbox/huge.pdf": b"%PDF-" + b"\x00" * MAX_BYTES,
        }
    )
    read = fake.read
    reads: list[str] = []

    async def counting_read(path: str) -> bytes:
        reads.append(path)
        return await read(path)

    monkeypatch.setattr(fake, "read", counting_read)
    proposals, errors = await scan_inbox_detailed(Books(fake), LOCAL)
    (bomb,) = proposals
    assert bomb.status == "needs_a_look" and bomb.file_path == "02 Needs a look/bomb.png"
    assert bomb.checks[0].code == "UNREADABLE" and "pixel" in bomb.checks[0].message
    assert errors == [{"path": "00 Inbox/huge.pdf", "error": "File is over 25 MB; not read"}]
    assert "00 Inbox/huge.pdf" not in reads and "00 Inbox/huge.pdf" in fake.files


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[ai_config_from_request] = lambda: LOCAL
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(ai_config_from_request, None)


def test_extract_route_refusals(client: TestClient, no_model: None, monkeypatch: pytest.MonkeyPatch) -> None:
    def post(name: str, data: bytes, ctype: str) -> tuple[int, str]:
        r = client.post("/extract", files={"file": (name, data, ctype)})
        return r.status_code, r.json()["detail"]

    assert post("x.gif", b"GIF89a", "image/gif")[0] == 415
    status, detail = post("bomb.png", png_header(20_000, 20_000), "image/png")
    assert status == 422 and "pixel" in detail
    monkeypatch.setitem(sys.modules, "pillow_heif", None)
    status, detail = post("IMG.HEIC", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 32, "image/heic")
    assert status == 422 and "export the photo as JPEG" in detail
    monkeypatch.setitem(sys.modules, "pypdfium2", FakePdfium(pages=40))
    status, detail = post("batch.pdf", b"%PDF-1.7", "application/pdf")
    assert status == 422 and "40 pages" in detail


# --------------------------------------------------------------------------- Outlook intake: email bodies


async def test_a_hostile_subject_cannot_leave_the_inbox_folder() -> None:
    fake, mail = FakeStorageProvider(), FakeMailProvider()
    subject = '../../_System/Rules/rules.json\\..\x00:*?"<>|#% receipt'
    mail.add(
        MailMessage(id="m", received_at=now(), from_address="billing@saas.example", subject=subject),
        body="Total £12.00",
    )
    (name,) = (await scan_mail(Books(fake), mail, user="sam@bramblewood.example")).saved
    assert "/" not in name and "\\" not in name and "\x00" not in name and name.endswith(".eml.txt")
    assert [p for p in fake.files if not p.startswith("_System/")] == [f"00 Inbox/{name}"]
    assert not any(p.startswith("_System/Rules") for p in fake.files)


async def test_a_huge_body_is_cut_before_it_is_saved() -> None:
    fake, mail = FakeStorageProvider(), FakeMailProvider()
    mail.add(
        MailMessage(id="m", received_at=now(), from_address="billing@saas.example", subject="Your receipt"),
        body="Total £12.00\n" + "x" * (BODY_MAX_CHARS * 5),
    )
    (name,) = (await scan_mail(Books(fake), mail, user="sam@bramblewood.example")).saved
    assert len(fake.files[f"00 Inbox/{name}"]) < BODY_MAX_CHARS + 1_000
    assert len(prepare(b"Total \xc2\xa31\n" + b"y" * (MAX_TEXT_CHARS * 3), name).text or "") == MAX_TEXT_CHARS
