"""Second read (pipeline.second_read_reason / reread_image): unsure or non-adding readings get one retry
at higher resolution and the reading that passes more checks wins. No model calls."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline  # noqa: E402
from app.ai.config import AiConfig  # noqa: E402
from app.ai.crop import reread_image  # noqa: E402
from app.ai.extract import ExtractionError  # noqa: E402
from app.schemas import ExtractedDoc, ExtractedLine  # noqa: E402

LOCAL = AiConfig(mode="local", base_url="http://x", model="m")


def _doc(net: float = 10.00, vat: float = 2.00, gross: float = 12.00, confidence: float = 0.9) -> ExtractedDoc:
    return ExtractedDoc(
        doc_type="receipt", supplier_name="Wickes", supplier_vat_number="GB123456789", customer_name=None,
        invoice_number=None, date="2026-10-26", currency="GBP",
        lines=[ExtractedLine(description="Screws", qty=1, unit_price=10.00, net=10.00, vat_rate=20, vat=2.00)],
        net_total=net, vat_total=vat, gross_total=gross, payment_method="card", card_last4=None,
        category_guess="Materials", confidence=confidence,
    )


def _png(size: tuple[int, int] = (400, 300)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 200, 190)).save(buf, format="PNG")
    return buf.getvalue()


class Reads:
    """What successive extract calls return (a doc or an exception), and the images they were given."""

    def __init__(self) -> None:
        self.queue: list[object] = []
        self.seen: list[bytes] = []


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> Reads:
    r = Reads()

    async def fake_extract(image_bytes, mime, cfg):
        r.seen.append(image_bytes)
        nxt = r.queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt, {"backend": "local", "model": "stub"}

    monkeypatch.setattr(pipeline, "extract_document", fake_extract)
    monkeypatch.setenv("VERIFIER", "off")
    monkeypatch.setenv("CROP_MODE", "off")
    return r


def _note(p) -> str:
    return next(c.message for c in p.checks if c.code == "SECOND_READ")


async def test_confident_reading_that_adds_up_is_read_once(reads: Reads) -> None:
    reads.queue.append(_doc())
    p = await pipeline.process_image(_png(), "image/png", LOCAL)
    assert len(reads.seen) == 1 and p.status == "proposed"
    assert not any(c.code == "SECOND_READ" for c in p.checks)


async def test_failing_arithmetic_is_re_read_and_the_better_reading_kept(reads: Reads) -> None:
    reads.queue += [_doc(net=10.00, vat=2.00, gross=15.00), _doc()]
    p = await pipeline.process_image(_png(), "image/png", LOCAL)
    assert len(reads.seen) == 2 and reads.seen[1] != reads.seen[0]  # the second read gets the upscaled image
    assert p.extracted.gross_total == 12.00 and p.status == "proposed"
    assert "arithmetic" in _note(p) and "kept the second" in _note(p)


async def test_low_confidence_triggers_one_retry_and_a_tie_keeps_the_first(reads: Reads) -> None:
    reads.queue += [_doc(confidence=0.6), _doc(confidence=0.6)]
    p = await pipeline.process_image(_png(), "image/png", LOCAL)
    assert len(reads.seen) == 2  # capped at one retry even though the second is also unsure
    assert "confidence 0.60" in _note(p) and "kept the first" in _note(p)


async def test_worse_second_reading_is_discarded(reads: Reads) -> None:
    reads.queue += [_doc(confidence=0.6), _doc(gross=99.00, confidence=0.9)]
    p = await pipeline.process_image(_png(), "image/png", LOCAL)
    assert p.extracted.gross_total == 12.00


async def test_second_read_error_keeps_the_first(reads: Reads) -> None:
    reads.queue += [_doc(confidence=0.6), ExtractionError("boom")]
    p = await pipeline.process_image(_png(), "image/png", LOCAL)
    assert p.extracted.gross_total == 12.00 and "first reading kept" in _note(p)


async def test_reread_image_upscales_and_keeps_format() -> None:
    img = Image.open(io.BytesIO(await reread_image(_png((400, 300)))))
    assert img.format == "PNG" and img.size == (800, 600)
    big = Image.open(io.BytesIO(await reread_image(_png((1600, 1200)))))
    assert max(big.size) == 2000
    assert await reread_image(b"not an image") == b"not an image"
