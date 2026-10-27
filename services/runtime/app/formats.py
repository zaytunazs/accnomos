"""Turn whatever arrives (a phone photo, an iPhone HEIC, a PDF, an email body) into what the extractor reads.

Every document goes through `prepare()` before a model sees it. The type is sniffed from the bytes, not trusted
from the name; limits are checked before anything is decoded:

* JPEG/PNG/WebP -> EXIF orientation applied (re-encoded only when the photo was turned);
* HEIC/HEIF     -> an upright JPEG (needs `pillow-heif`; without it the file is refused with "export as JPEG");
* PDF           -> the text of every page (the first page's is sent) plus the first page rendered to PNG (needs
                   `pypdfium2`). A multi-page invoice is one document; a scanner batch of several receipts in one
                   PDF is *not* split (docs/INBOX.md). A scanned PDF has no text: the render alone is read;
* text          -> an email body saved by Outlook intake (`.eml.txt`), read as text with the same prompt.

Limits: 25 MB per file, 50 million pixels per image (image bombs), 20 PDF pages. Anything refused raises
`FormatError`, whose message is shown to the user as is.
"""

from __future__ import annotations

import io
import math
import warnings
from dataclasses import dataclass, field
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 50_000_000  # a 48 MP iPhone photo fits; a decompression bomb does not
MAX_PDF_PAGES = 20
MAX_TEXT_CHARS = 20_000  # of document text sent to the model
RENDER_DPI = 200
RENDER_MAX_SIDE = 2400  # px, longest side of a rendered PDF page
JPEG_QUALITY = 90

PDF_MIME = "application/pdf"
TEXT_MIME = "text/plain"
HEIC_MIME = "image/heic"
_IMAGE_MIME = {"JPEG": "image/jpeg", "MPO": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
_SAVE_AS = {"MPO": "JPEG"}
_ORIENTATION = 0x0112
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs", b"mif1", b"msf1"}

Kind = Literal["image", "pdf", "text"]

EXPORT_AS_JPEG = (
    "HEIC photos can't be read on this server: export the photo as JPEG and upload it again "
    "(on an iPhone: Settings › Camera › Formats › Most Compatible)"
)


class FormatError(ValueError):
    """The file is refused (too large, too many pixels or pages, unreadable, unsupported). Safe to show the user."""


@dataclass(frozen=True)
class Prepared:
    """What the extractor gets. `image` is JPEG/PNG/WebP bytes (`mime`); `text` is the document's own text."""

    kind: Kind
    image: bytes | None
    mime: str | None
    text: str | None = None
    pages: int = 1
    page_texts: list[str] = field(default_factory=list)  # PDF only, every page
    converted_from: str | None = None  # "HEIC" when the image is a JPEG made from a HEIC
    note: str = ""  # one line for the Review card, e.g. "PDF, 3 pages: page 1 read"

    @property
    def source_mime(self) -> str:
        """MIME type of the file as it will be filed (the JPEG for a converted HEIC)."""
        return {"pdf": PDF_MIME, "text": TEXT_MIME}.get(self.kind) or self.mime or "image/jpeg"


# --------------------------------------------------------------------------- sniffing


def is_pdf(data: bytes) -> bool:
    return b"%PDF-" in data[:1024]  # the spec lets junk come before the header


def is_heif(data: bytes) -> bool:
    return data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS


def _wants_text(hint: str) -> bool:
    hint = hint.lower().split(";")[0].strip()
    return hint == TEXT_MIME or hint.endswith(".txt")


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.0f} MB"


# --------------------------------------------------------------------------- images


def _open_checked(data: bytes) -> Image.Image:
    """Open (header only) and refuse more than MAX_PIXELS before a single pixel is decoded."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise FormatError(f"Image refused: too many pixels ({exc})") from exc
    w, h = img.size
    if w * h > MAX_PIXELS:
        raise FormatError(f"Image refused: {w} × {h} pixels is over the {MAX_PIXELS // 1_000_000} million pixel limit")
    return img


def _encode(img: Image.Image, fmt: str) -> bytes:
    buf = io.BytesIO()
    fmt = _SAVE_AS.get(fmt, fmt)
    if fmt == "JPEG":
        img.convert("RGB").save(buf, "JPEG", quality=JPEG_QUALITY)
    else:
        img.save(buf, fmt)
    return buf.getvalue()


def _image(data: bytes, hint_mime: str) -> Prepared:
    try:
        img = _open_checked(data)
    except (UnidentifiedImageError, OSError):
        # Not something Pillow knows: passed on untouched, and the model call says what it could not read.
        return Prepared("image", data, hint_mime)
    fmt = img.format or ""
    mime = _IMAGE_MIME.get(fmt)
    if mime is None:
        raise FormatError(f"{fmt or 'This'} images are not accepted; send a PDF, JPEG, PNG, WebP or HEIC")
    orientation = img.getexif().get(_ORIENTATION, 1)
    if orientation in (1, None):
        return Prepared("image", data, mime)
    try:
        upright = _encode(ImageOps.exif_transpose(img), fmt)
    except (OSError, ValueError) as exc:
        raise FormatError(f"Image could not be read: {exc}") from exc
    return Prepared("image", upright, mime, note="Photo turned upright (EXIF orientation)")


def _heic(data: bytes) -> Prepared:
    try:
        from pillow_heif import register_heif_opener  # type: ignore[import-not-found]
    except ImportError:
        raise FormatError(EXPORT_AS_JPEG) from None
    register_heif_opener()
    try:
        img = _open_checked(data)
        jpeg = _encode(ImageOps.exif_transpose(img), "JPEG")
    except FormatError:
        raise
    except Exception as exc:  # noqa: BLE001  libheif raises its own types
        raise FormatError(f"HEIC photo could not be read ({type(exc).__name__}); export it as JPEG") from exc
    return Prepared("image", jpeg, "image/jpeg", converted_from="HEIC", note="HEIC photo converted to JPEG")


# --------------------------------------------------------------------------- PDF


def render_scale(width_pt: float, height_pt: float) -> float:
    """Scale (pixels per point) for RENDER_DPI, capped by RENDER_MAX_SIDE and MAX_PIXELS: a page declared
    as 200 inches square renders small, not as a billion-pixel bitmap."""
    w, h = max(width_pt, 1.0), max(height_pt, 1.0)
    return min(RENDER_DPI / 72, RENDER_MAX_SIDE / max(w, h), math.sqrt(MAX_PIXELS / (w * h)))


def _pdf(data: bytes) -> Prepared:
    try:
        import pypdfium2 as pdfium  # type: ignore[import-not-found]
    except ImportError:
        raise FormatError("PDFs can't be read on this server yet") from None
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        why = "it is password-protected" if "password" in str(exc).lower() else "it is damaged or not a PDF"
        raise FormatError(f"PDF could not be opened: {why}") from exc
    try:
        pages = len(pdf)
        if pages == 0:
            raise FormatError("PDF has no pages")
        if pages > MAX_PDF_PAGES:
            raise FormatError(
                f"PDF has {pages} pages; up to {MAX_PDF_PAGES} are read. Split it and send the invoice on its own"
            )
        texts: list[str] = []
        for i in range(pages):
            page = pdf[i]
            textpage = page.get_textpage()
            texts.append(textpage.get_text_bounded().replace("\r\n", "\n").strip())
            textpage.close()
            page.close()
        first = pdf[0]
        width, height = first.get_size()
        png = _encode(first.render(scale=render_scale(width, height)).to_pil(), "PNG")
        first.close()
    except FormatError:
        raise
    except Exception as exc:  # noqa: BLE001  pdfium errors on a page are a broken file, not a server fault
        raise FormatError(f"PDF could not be read ({type(exc).__name__})") from exc
    finally:
        pdf.close()
    scanned = not texts[0]
    note = f"PDF, {pages} page{'s' if pages != 1 else ''}" + (": page 1 read" if pages > 1 else "")
    if scanned:
        note += "; no text layer (a scan), read from the image"
    return Prepared(
        "pdf", png, "image/png", text=texts[0][:MAX_TEXT_CHARS] or None, pages=pages, page_texts=texts, note=note
    )


# --------------------------------------------------------------------------- text


def _text(data: bytes) -> Prepared:
    if b"\x00" in data:
        raise FormatError("Text file refused: it contains binary data")
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n").strip()
    if not text:
        raise FormatError("Text file is empty")
    return Prepared("text", None, None, text=text[:MAX_TEXT_CHARS], note="Email text, read without an image")


# --------------------------------------------------------------------------- entry point


def prepare(data: bytes, hint: str) -> Prepared:
    """`hint` is the file name or the declared MIME type. Raises `FormatError`. CPU-bound: run it in a thread."""
    if len(data) > MAX_BYTES:
        raise FormatError(f"File is {_mb(len(data))}; the limit is {_mb(MAX_BYTES)}")
    if not data:
        raise FormatError("File is empty")
    if is_pdf(data):
        return _pdf(data)
    if is_heif(data):
        return _heic(data)
    if _wants_text(hint):
        return _text(data)
    hint_mime = hint.lower() if "/" in hint else guess_mime(hint) or "image/jpeg"
    if hint_mime == PDF_MIME:
        raise FormatError("File is named as a PDF but is not one")
    return _image(data, "image/jpeg" if hint_mime in ("image/jpg", HEIC_MIME, "image/heif") else hint_mime)


_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": HEIC_MIME,
    ".heif": "image/heif",
    ".pdf": PDF_MIME,
    ".txt": TEXT_MIME,
}


def guess_mime(name: str) -> str | None:
    """MIME type of the documents we accept, by extension; None for anything else."""
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return _BY_EXT.get(ext)
