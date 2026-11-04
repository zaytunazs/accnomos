"""Document crop: SAM parser (fixture), code fallback box, and 'original when uncertain'."""

from __future__ import annotations

import base64
import io
import json
import random
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.ai import crop
from app.ai.config import AiConfig, apply_route
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


def test_parser_reads_captured_reply():
    boxes = parse_sam_boxes(FIXTURE)
    # x2/y2 are inclusive on the wire; boxes here are half-open
    assert boxes == [((21, 187, 637, 716), pytest.approx(0.93361, abs=1e-4))]
    assert pick_sam_box(boxes, (959, 733)) == (21, 187, 637, 716)


def _reply(text: str) -> dict:
    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}


def test_parser_box_tokens_by_key_and_picks_largest_confident_box():
    text = (
        "<0f>0<|box;x1=212;y1=88;x2=730;y2=1203;w=1000;h=1300;c=0.97|><|mask;x=0;y=0;c=0.97;data=1,1,!a|>"
        ",1<|box;y1=900;x1=800;y2=1099;x2=959;h=1300;w=1000;c=0.62|><|mask;x=0;y=0;data=1,1,~b|>"
        ",2<|box;x1=0;y1=0;x2=999;y2=1299;w=1000;h=1300;c=0.21|><|mask;x=0;y=0;data=1,1,!c|>\n"
    )
    boxes = parse_sam_boxes(_reply(text))
    assert [b for b, _ in boxes] == [(212, 88, 731, 1204), (800, 900, 960, 1100), (0, 0, 1000, 1300)]
    assert [s for _, s in boxes] == [0.97, 0.62, 0.21]
    # the full-frame box has score 0.21 and is ignored
    assert pick_sam_box(boxes, (1000, 1300)) == (212, 88, 731, 1204)
    # no confidence asked for: the box still counts
    assert parse_sam_boxes(_reply("<0f>0<|box;x1=1;y1=2;x2=9;y2=9;w=10;h=10|><|mask;x=0;y=0;data=1,1,!a|>")) == [
        ((1, 2, 10, 10), None)
    ]
    # zero matches is an empty output_text, not an error
    assert parse_sam_boxes(_reply("")) == []
    assert parse_sam_boxes({"output": []}) == []


def test_parser_tolerates_json_detections():
    js = {"detections": [{"score": 0.97, "box": [212, 88, 731, 1204]}, {"score": 0.21, "box": [0, 0, 9, 9]}]}
    boxes = parse_sam_boxes({"output_text": json.dumps(js)})
    assert boxes == [((212, 88, 731, 1204), 0.97), ((0, 0, 9, 9), 0.21)]


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


async def test_sam_sees_exif_upright_pixels(monkeypatch):
    monkeypatch.setenv("SAM_CROP", "1")
    upright = Image.open(io.BytesIO(_photo()))  # 900 x 1200 as the user sees it
    exif = Image.Exif()
    exif[0x0112] = 6  # stored rotated; viewers turn it 90° clockwise
    buf = io.BytesIO()
    upright.rotate(90, expand=True).save(buf, format="JPEG", exif=exif)
    sizes: list[tuple[int, int]] = []

    async def fake(noun, data_url, cfg):
        sizes.append(_size(base64.b64decode(data_url.split(",", 1)[1])))
        return {"output_text": json.dumps({"box": [190, 140, 660, 1060], "score": 0.9})}

    monkeypatch.setattr(crop, "_call_sam", fake)
    r = await crop_document(buf.getvalue(), KEY_CFG)
    assert sizes == [(900, 1200)]
    assert r.method == "sam" and r.box == pad_box((190, 140, 660, 1060), (900, 1200))


async def test_phone_mpo_jpeg_stays_jpeg_and_other_formats_pass_through():
    img = Image.open(io.BytesIO(_photo()))
    buf = io.BytesIO()
    img.save(buf, format="MPO", save_all=True, append_images=[img.copy()])
    assert Image.open(io.BytesIO(buf.getvalue())).format == "MPO"
    r = await crop_document(buf.getvalue())
    assert r.method == "code" and Image.open(io.BytesIO(r.image_bytes)).format == "JPEG"

    gif = io.BytesIO()
    img.save(gif, format="GIF")
    r = await crop_document(gif.getvalue())
    assert r.method == "none" and r.image_bytes == gif.getvalue()


def test_request_body_shape():
    body = crop.sam_request_body("receipt", "data:image/png;base64,AAA")
    assert body["model"] == "sam-3.1"
    assert body["input"][0]["type"] == "message" and body["input"][0]["role"] == "user"
    content = body["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "receipt"}
    assert content[1] == {"type": "input_image", "image_url": "data:image/png;base64,AAA"}
    # the docs want strings here, not JSON booleans
    assert body["metadata"] == {"include_confidence": "true", "mask_encoding": "one_bit"}


# --- SAM on the server's chain ------------------------------------------------


def _chain(*names: str, route=None) -> AiConfig:
    """The server's chain, as app/ai/providers.py builds it (no network)."""
    from app.ai import providers

    env = {"AI_PROVIDERS": ",".join(names), "META_API_KEY": "server-key", "OLLAMA_BASE": "http://glimmer.test"}
    cfg = providers.chain_config(env)
    return apply_route(cfg, route) if route else cfg


def test_sam_config_picks_the_meta_provider_from_the_chain(monkeypatch):
    monkeypatch.setenv("SAM_CROP", "1")
    meta_first = _chain("meta", "spark")
    assert crop.sam_config(meta_first).provider == "meta"
    glimmer_first = _chain("spark", "meta")  # the meta provider is a fallback: SAM still uses it
    sam = crop.sam_config(glimmer_first)
    assert sam is not None and sam.provider == "meta" and sam.auth_headers() == {"Authorization": "Bearer server-key"}
    assert crop.sam_config(_chain("spark")) is None  # no Meta key on this server
    own = crop.sam_config(KEY_CFG)  # the user's own key
    assert own is not None and own.api_key == "test"
    # routes that keep work off the Meta API
    assert crop.sam_config(_chain("meta", "spark", route="local_only")) is None
    assert crop.sam_config(_chain("meta", "spark", route="local_first")) is None
    assert crop.sam_config(_chain("meta", "spark", route="meta_first")).provider == "meta"
    monkeypatch.delenv("SAM_CROP")
    assert crop.sam_config(meta_first) is None


async def test_sam_runs_on_server_chain_and_falls_back_to_code_on_timeout(monkeypatch):
    import httpx

    monkeypatch.setenv("SAM_CROP", "1")
    used: list[tuple[str, str]] = []

    async def fake(noun, data_url, cfg):
        used.append((cfg.provider, cfg.api_key))
        return _reply("<0f>0<|box;x1=190;y1=140;x2=659;y2=1059;w=900;h=1200;c=0.95|><|mask;x=0;y=0;data=1,1,!a|>")

    monkeypatch.setattr(crop, "_call_sam", fake)
    r = await crop_document(_photo(), _chain("spark", "meta"))
    assert used == [("meta", "server-key")]
    assert r.method == "sam" and r.box == pad_box((190, 140, 660, 1060), (900, 1200))

    async def slow(noun, data_url, cfg):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(crop, "_call_sam", slow)
    r = await crop_document(_photo(), _chain("meta", "spark"))
    assert r.method == "code" and r.details["sam"]["reason"] == "error: ReadTimeout"

    async def never(noun, data_url, cfg):
        raise AssertionError("SAM must not be called")

    monkeypatch.setattr(crop, "_call_sam", never)
    assert (await crop_document(_photo(), _chain("meta", "spark", route="local_only"))).method == "code"
    monkeypatch.setenv("CROP_MODE", "code")
    assert (await crop_document(_photo(), _chain("meta", "spark"))).method == "code"


async def test_call_sam_sends_the_chain_providers_auth(monkeypatch):
    import httpx

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=FIXTURE)

    real = httpx.AsyncClient

    def client(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)

    monkeypatch.setattr(crop.httpx, "AsyncClient", client)
    monkeypatch.setenv("SAM_CROP", "1")
    meta = crop.sam_config(_chain("spark", "meta"))
    assert meta is not None
    data = await crop._call_sam("receipt", "data:image/png;base64,AAA", meta)
    assert seen["url"] == "https://api.meta.ai/v1/responses"
    assert seen["auth"] == "Bearer server-key"
    assert seen["body"]["model"] == "sam-3.1"
    assert parse_sam_boxes(data)[0][0] == (21, 187, 637, 716)


# --- pipeline wiring ----------------------------------------------------------


async def test_process_image_extracts_cropped_bytes_and_records_crop(monkeypatch):
    from app import pipeline
    from app.schemas import ExtractedDoc

    seen: list[bytes] = []

    async def fake_extract(image_bytes, mime, cfg):
        seen.append(image_bytes)
        doc = ExtractedDoc(
            doc_type="receipt",
            supplier_name="Wickes",
            supplier_vat_number=None,
            customer_name=None,
            invoice_number=None,
            date="2026-10-26",
            currency="GBP",
            lines=[],
            net_total=10,
            vat_total=2,
            gross_total=12,
            payment_method="card",
            card_last4=None,
            category_guess="Materials",
            confidence=0.9,
        )
        return doc, {"backend": "local", "model": "stub"}

    monkeypatch.setattr(pipeline, "extract_document", fake_extract)
    local = AiConfig(mode="local", base_url="http://x", model="m")
    data = _photo()
    p = await pipeline.process_image(data, "image/png", local)
    assert p.doc_sha256 == pipeline.sha256_hex(data)  # hash of the original, not the crop
    assert seen[0] != data and _size(seen[0]) == (
        p.crop["box"][2] - p.crop["box"][0],
        p.crop["box"][3] - p.crop["box"][1],
    )
    assert p.crop["method"] == "code"
    chip = [c for c in p.checks if c.code == "CROP"]
    assert chip and chip[0].ok and chip[0].message.startswith("Cropped by code")
    assert not any(r.startswith("CROP") for r in p.reasons)

    p2 = await pipeline.process_image(_photo(paper=(10, 10, 890, 1190)), "image/png", local)
    assert p2.crop["method"] == "none" and not any(c.code == "CROP" for c in p2.checks)
