"""Document crop: SAM parser (fixture), code fallback box, and 'original when uncertain'."""

from __future__ import annotations

import io
import json
import random
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.ai import crop
from app.ai.config import AiConfig
from app.ai.crop import code_box, crop_document, iou, pad_box, parse_sam_boxes, pick_sam_box

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "sam_response.json").read_text())
TABLE = (104, 88, 72)
KEY_CFG = AiConfig(mode="key", base_url="https://api.example.test/v1", model="m", api_key="test")


def _photo(size=(900, 1200), paper=(200, 150, 650, 1050), fmt="PNG", bg=TABLE) -> bytes:
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    d.rectangle((paper[0], paper[1], paper[2] - 1, paper[3] - 1), fill=(250, 249, 245))
    for i in range(paper[1] + 30, paper[3] - 30, 28):  # some "text"
        d.rectangle((paper[0] + 25, i, paper[2] - 60, i + 10), fill=(30, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _size(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("CROP_MODE", raising=False)
    monkeypatch.delenv("SAM_CROP", raising=False)


# --- SAM parser ---------------------------------------------------------------


def test_parser_reads_fixture_and_picks_largest_confident_box():
    boxes = parse_sam_boxes(FIXTURE)
    assert [b for b, _ in boxes] == [(212, 88, 731, 1204), (800, 900, 960, 1100), (0, 0, 1000, 1300)]
    assert [s for _, s in boxes] == [0.97, 0.62, 0.21]
    # the full-frame box has score 0.21 and is ignored
    assert pick_sam_box(boxes, (1000, 1300)) == (212, 88, 731, 1204)


def test_parser_tolerates_other_shapes():
    plain = {"output_text": "Found 1 receipt at [10, 20, 110, 220] (mask: ...)"}
    assert [b for b, _ in parse_sam_boxes(plain)] == [(10, 20, 110, 220)]
    xywh = {"output_text": json.dumps({"objects": [{"bbox": {"x": 5, "y": 6, "w": 50, "h": 60}}]})}
    assert [b for b, _ in parse_sam_boxes(xywh)] == [(5, 6, 55, 66)]
    bare = {"output_text": json.dumps({"boxes": [[1, 2, 30, 40], [0, 0, 5, 5]]})}
    assert [b for b, _ in parse_sam_boxes(bare)] == [(1, 2, 30, 40), (0, 0, 5, 5)]
    assert parse_sam_boxes({"output": []}) == []
    assert parse_sam_boxes({"output_text": "no receipt here"}) == []
    assert parse_sam_boxes({"output_text": json.dumps({"box": [50, 50, 10, 10]})}) == []  # inverted


def test_pick_clamps_to_image():
    assert pick_sam_box([((-5, -5, 2000, 900), 0.9)], (1000, 800)) == (0, 0, 1000, 800)
    assert pick_sam_box([], (10, 10)) is None


# --- geometry / code fallback -------------------------------------------------


def test_pad_box_three_percent_and_clamped():
    assert pad_box((100, 100, 200, 300), (1000, 1000)) == (97, 94, 203, 306)
    assert pad_box((0, 0, 1000, 1000), (1000, 1000)) == (0, 0, 1000, 1000)


def test_code_box_finds_paper_on_table():
    img = Image.open(io.BytesIO(_photo()))
    box, info = code_box(img)
    assert box is not None, info
    assert iou(box, (200, 150, 650, 1050)) > 0.95


def test_code_box_ignores_smaller_second_paper():
    img = Image.open(io.BytesIO(_photo(size=(1200, 1200))))
    ImageDraw.Draw(img).rectangle((800, 700, 1100, 1000), fill=(245, 245, 240))
    box, info = code_box(img)
    assert box is not None, info
    assert iou(box, (200, 150, 650, 1050)) > 0.95


async def test_crop_keeps_format_and_crops():
    for fmt in ("PNG", "JPEG"):
        r = await crop_document(_photo(fmt=fmt))
        assert r.method == "code" and r.note == "Cropped by code"
        out = Image.open(io.BytesIO(r.image_bytes))
        assert out.format == fmt
        assert out.size == (r.box[2] - r.box[0], r.box[3] - r.box[1])
        assert iou(r.box, pad_box((200, 150, 650, 1050), (900, 1200))) > 0.95  # 3 % padding


# --- returns original when uncertain -----------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(_photo(paper=(10, 10, 890, 1190)), id="paper fills photo"),
        pytest.param(_photo(paper=(400, 500, 560, 700)), id="paper too small"),
        pytest.param(_photo(paper=(0, 0, 900, 1200), bg=(250, 250, 250)), id="blank white"),
    ],
)
async def test_returns_original_when_uncertain(data):
    r = await crop_document(data)
    assert r.method == "none" and r.box is None
    assert r.image_bytes is data


async def test_returns_original_on_noise():
    rng = random.Random(3)
    img = Image.new("L", (300, 300))
    img.putdata([rng.choice((20, 235)) for _ in range(300 * 300)])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    r = await crop_document(buf.getvalue())
    assert r.method == "none"


async def test_unreadable_bytes_and_off_switch(monkeypatch):
    r = await crop_document(b"not an image")
    assert r.method == "none" and r.image_bytes == b"not an image"
    monkeypatch.setenv("CROP_MODE", "off")
    data = _photo()
    assert (await crop_document(data)).image_bytes is data


# --- SAM path (network stubbed) -----------------------------------------------


async def test_sam_used_only_with_key_mode_and_flag(monkeypatch):
    calls: list[str] = []

    async def fake(noun, data_url, cfg):
        calls.append(noun)
        assert data_url.startswith("data:image/png;base64,")
        return {"output_text": json.dumps({"detections": [{"score": 0.9, "box": [190, 140, 660, 1060]}]})}

    monkeypatch.setattr(crop, "_call_sam", fake)
    local = AiConfig(mode="local", base_url="http://x", model="m")
    monkeypatch.setenv("SAM_CROP", "1")
    assert (await crop_document(_photo(), local)).method == "code"
    monkeypatch.delenv("SAM_CROP")
    assert (await crop_document(_photo(), KEY_CFG)).method == "code"
    assert calls == []

    monkeypatch.setenv("SAM_CROP", "1")
    r = await crop_document(_photo(), KEY_CFG)
    assert r.method == "sam" and r.note == "Cropped with SAM 3.1"
    assert r.box == pad_box((190, 140, 660, 1060), (900, 1200))
    assert calls == ["receipt"]


async def test_sam_falls_back_to_invoice_noun_then_code(monkeypatch):
    monkeypatch.setenv("SAM_CROP", "1")
    calls: list[str] = []

    async def empty(noun, data_url, cfg):
        calls.append(noun)
        return {"output_text": "[]"}

    monkeypatch.setattr(crop, "_call_sam", empty)
    r = await crop_document(_photo(), KEY_CFG)
    assert calls == ["receipt", "invoice"]
    assert r.method == "code"

    async def boom(noun, data_url, cfg):
        raise RuntimeError("HTTP 500")

    monkeypatch.setattr(crop, "_call_sam", boom)
    r = await crop_document(_photo(), KEY_CFG)
    assert r.method == "code" and r.details["sam"]["reason"].startswith("error")


def test_request_body_shape():
    body = crop.sam_request_body("receipt", "data:image/png;base64,AAA")
    assert body["model"] == "sam-3.1"
    content = body["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "receipt"}
    assert content[1]["type"] == "input_image"
