"""The document-type classifier calls the model; code's guess is only the fallback.

``app/scan_jobs.py`` asks ``app/ai/classify.py`` (one short model call) before anything is read in full. A
configured fake provider IS then called, both for a document with text (the text alone goes, no image) and for an
image without text (the image goes). Only when the provider errors or times out does the file reach confirm with
code's guess -- and the secret-free reason is logged, so a run of misses says why.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from accnomos_connectors import FakeStorageProvider

from app import scan_jobs
from app.ai import chain
from app.ai import classify as classify_ai
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError
from app.books import Books

BUSINESS = "Bramblewood Joinery Ltd"
TEXT = "INVOICE 1001 Amount due 120.00 Payment terms 30 days"
PHOTO = b"\xff\xd8 photo of a till receipt " + b"y" * 1000


def _cfg() -> AiConfig:
    return AiConfig(mode="local", base_url="http://127.0.0.1:1", model="m")


def _settings() -> scan_jobs.Settings:
    return scan_jobs.Settings(cfg=_cfg(), business_name=BUSINESS)


def _books(data: bytes, name: str) -> tuple[Books, scan_jobs.ScanFile]:
    fake = FakeStorageProvider()
    fake.files[f"00 Inbox/{name}"] = data
    return Books(fake), scan_jobs.ScanFile(name=name, path=f"00 Inbox/{name}")


def _patch(monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]) -> list[httpx.Request]:
    """Every model call answers from `handler`; returns the requests the provider saw."""
    seen: list[httpx.Request] = []
    real = httpx.AsyncClient

    def inner(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(
        classify_ai.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(inner), **kw)
    )
    return seen


def _reply(kind: str) -> httpx.Response:
    return httpx.Response(
        200, json={"message": {"content": json.dumps({"kind": kind, "confidence": 0.9, "reason": "fake"})}}
    )


def _body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)


async def test_model_is_called_for_a_document_with_text(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _patch(monkeypatch, lambda r: _reply("purchase_invoice"))
    books, f = _books(TEXT.encode(), "mail.eml.txt")  # an email body: text, no image
    await scan_jobs._classify(books, f, _settings())
    assert f.stage == "confirm"
    assert f.guess is not None and (f.guess.kind, f.guess.by) == ("purchase_invoice", "ai")
    assert len(seen) == 1  # the model was asked
    assert "images" not in _body(seen[0])["messages"][1]  # text alone: the image never goes


async def test_model_is_called_for_an_image_without_text(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _patch(monkeypatch, lambda r: _reply("receipt"))
    books, f = _books(PHOTO, "photo.jpg")
    await scan_jobs._classify(books, f, _settings())
    assert f.stage == "confirm"
    assert f.guess is not None and (f.guess.kind, f.guess.by) == ("receipt", "ai")
    assert len(seen) == 1
    assert _body(seen[0])["messages"][1]["images"]  # no text layer: the image goes


async def test_provider_error_falls_back_to_code_with_the_reason_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    seen = _patch(monkeypatch, lambda r: httpx.Response(503, json={"error": "down"}))
    books, f = _books(TEXT.encode(), "mail.eml.txt")
    with caplog.at_level(logging.WARNING, logger="accnomos.scan"):
        await scan_jobs._classify(books, f, _settings())
    assert len(seen) == 1  # the provider was tried; only its failure falls back
    assert f.stage == "confirm"
    assert f.guess is not None and (f.guess.kind, f.guess.by) == ("purchase_invoice", "code")
    assert f.message == "The AI could not say, so this guess is from code. Please check the type."
    assert "503" in caplog.text and "mail.eml.txt" in caplog.text  # the reason is recorded, without secrets
    assert "127.0.0.1" not in caplog.text


async def test_provider_timeout_falls_back_to_code_with_the_reason_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    seen = _patch(monkeypatch, slow)
    books, f = _books(TEXT.encode(), "mail.eml.txt")
    with caplog.at_level(logging.WARNING, logger="accnomos.scan"):
        await scan_jobs._classify(books, f, _settings())
    assert len(seen) == 1
    assert f.stage == "confirm"
    assert f.guess is not None and f.guess.by == "code"
    assert f.message == "The AI did not answer in time, so this guess is from code. Please check the type."
    assert "did not answer" in caplog.text


async def test_spent_budget_never_reaches_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _patch(monkeypatch, lambda r: _reply("receipt"))
    with chain.limits(deadline=time.monotonic() - 1):  # the document's time is already up
        with pytest.raises(ExtractionError, match="did not answer"):
            await classify_ai.classify(None, None, _cfg(), text=TEXT)
    assert seen == []  # nothing to ask with: no call, and the reason still says so
