"""Verifier: comparison normalisation, disagreement routing and backend selection. No network."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline  # noqa: E402
from app.ai import verify as verify_mod  # noqa: E402
from app.ai.config import AiConfig  # noqa: E402
from app.ai.extract import ExtractionError  # noqa: E402
from app.ai.verify import (  # noqa: E402
    DEFAULT_BASETEN_MODEL,
    VerifierReading,
    compare,
    field_agree,
    normalise_name,
    select_backend,
    verify,
)
from app.schemas import ExtractedDoc, ExtractedLine  # noqa: E402

LOCAL = AiConfig(mode="local", base_url="http://ollama.invalid", model="muse-glimmer:30b")
KEY = AiConfig(mode="key", base_url="https://api.meta.ai/v1", model="muse-spark-1.3", api_key="user-key")


def _doc(**kw: object) -> ExtractedDoc:
    base: dict[str, object] = dict(
        doc_type="receipt",
        supplier_name="Screwfix Direct Ltd",
        supplier_vat_number="GB 232 4567 89",
        customer_name=None,
        invoice_number=None,
        date="2026-10-21",
        currency="GBP",
        lines=[ExtractedLine(description="Drill bits", qty=1, unit_price=38.47, net=32.06, vat_rate=20, vat=6.41)],
        net_total=32.06,
        vat_total=6.41,
        gross_total=38.47,
        payment_method="card",
        card_last4="1234",
        category_guess="Tools & small equipment",
        confidence=0.95,
    )
    base.update(kw)
    return ExtractedDoc.model_validate(base)


def _reading(**kw: object) -> VerifierReading:
    base: dict[str, object] = dict(
        seller="SCREWFIX DIRECT LIMITED",
        vat_registration="232456789",
        issue_date="21/10/2026",
        amount_before_vat=32.06,
        vat_amount=6.41,
        amount_payable=38.47,
    )
    base.update(kw)
    return VerifierReading.model_validate(base)


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Screwfix Direct Ltd", "SCREWFIX DIRECT LIMITED"),
        ("Screwfix Direct Ltd.", "screwfix  direct"),
        ("Marks & Spencer plc", "Marks and Spencer"),
        ("B&Q", "B & Q"),
        ("Café Nero", "CAFE NERO"),
        ("O’Brien's Café", "OBRIENS CAFE"),
    ],
)
def test_names_agree_after_normalising(a: str, b: str) -> None:
    assert field_agree("name", a, b), (normalise_name(a), normalise_name(b))


@pytest.mark.parametrize(("a", "b"), [("Screwfix", "Toolstation"), ("Screwfix", ""), ("", "")])
def test_names_disagree(a: str, b: str) -> None:
    assert not field_agree("name", a, b)


def test_vat_number_compared_by_digits() -> None:
    assert field_agree("vat_number", "GB 232 4567 89", "232456789")
    assert field_agree("vat_number", "VAT Reg No: GB232-4567-89", "GB232456789")
    assert field_agree("vat_number", None, None)  # neither reading saw one
    assert not field_agree("vat_number", "GB232456789", None)
    assert not field_agree("vat_number", "GB232456789", "GB232456788")


def test_dates_compared_by_value() -> None:
    assert field_agree("date", "2026-10-21", "21/10/2026")
    assert field_agree("date", "2026-10-21", "21 October 2026")
    assert field_agree("date", "2026-10-01", "01.10.2026")
    assert not field_agree("date", "2026-10-21", "10/21/2026")  # US order is not a UK date
    assert not field_agree("date", "2026-10-21", "2026-10-12")
    assert not field_agree("date", "not a date", "not a date")


def test_money_by_pence_with_one_penny_tolerance() -> None:
    assert field_agree("money", 38.47, 38.47)
    assert field_agree("money", 38.47, 38.48)
    assert field_agree("money", 38.47, 38.46)
    assert not field_agree("money", 38.47, 38.49)
    assert not field_agree("money", 38.47, 3.847)


def test_compare_all_agree() -> None:
    v = compare(_doc(), _reading(), "ollama:x")
    assert v.agree_all
    assert set(v.fields) == {"supplier_name", "supplier_vat_number", "date", "net_total", "vat_total", "gross_total"}
    assert v.fields["date"].extractor == "2026-10-21" and v.fields["date"].verifier == "21/10/2026"


def test_compare_keeps_both_values_and_never_merges() -> None:
    doc = _doc()
    v = compare(doc, _reading(amount_payable=83.47), "ollama:x")
    assert not v.agree_all
    assert v.fields["gross_total"].model_dump() == {"extractor": 38.47, "verifier": 83.47, "agree": False}
    assert doc.gross_total == 38.47  # the extracted document is untouched


# --------------------------------------------------------------------------- #
# Backend selection
# --------------------------------------------------------------------------- #


def test_local_mode_stays_local_even_with_baseten_key() -> None:
    be = select_backend(LOCAL, {"BASETEN_API_KEY": "owner-key"})
    assert be is not None and be.kind == "ollama"
    assert be.base_url == LOCAL.base_url and be.api_key is None


def test_key_mode_prefers_baseten_when_owner_configured_it() -> None:
    be = select_backend(KEY, {"BASETEN_API_KEY": "owner-key"})
    assert be is not None and be.kind == "baseten"
    assert be.base_url == "https://inference.baseten.co/v1"
    assert be.model == DEFAULT_BASETEN_MODEL and be.api_key == "owner-key"


def test_verifier_model_env_overrides_baseten_model() -> None:
    env = {"BASETEN_API_KEY": "k", "BASETEN_MODEL": "a/b", "VERIFIER_MODEL": "meta-models/other"}
    assert select_backend(KEY, env).model == "meta-models/other"  # type: ignore[union-attr]
    assert select_backend(KEY, {"BASETEN_API_KEY": "k", "BASETEN_MODEL": "a/b"}).model == "a/b"  # type: ignore[union-attr]


def test_key_mode_without_baseten_uses_users_meta_key() -> None:
    be = select_backend(KEY, {"BASETEN_API_KEY": "  "})
    assert be is not None and be.kind == "meta"
    assert be.api_key == "user-key" and be.model == "muse-spark-1.3" and be.base_url == KEY.base_url


def test_verifier_can_be_switched_off() -> None:
    assert select_backend(KEY, {"VERIFIER": "off", "BASETEN_API_KEY": "k"}) is None


async def test_verify_reports_error_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*_a: object, **_kw: object) -> VerifierReading:
        raise ExtractionError("verifier ollama unreachable")

    monkeypatch.setattr(verify_mod, "read_independently", boom)
    v = await verify(b"img", _doc(), LOCAL, env={})
    assert v is not None and v.error and not v.agree_all and v.fields == {}


# --------------------------------------------------------------------------- #
# Pipeline routing
# --------------------------------------------------------------------------- #


@pytest.fixture
def stub_models(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    state: dict[str, object] = {"doc": _doc(), "reading": _reading(), "verify_calls": 0}

    async def fake_extract(data: bytes, mime: str, cfg: AiConfig) -> tuple[ExtractedDoc, dict[str, str]]:
        return state["doc"], {"backend": cfg.mode, "model": cfg.model}  # type: ignore[return-value]

    async def fake_read(image_bytes: bytes, mime: str, be: object) -> VerifierReading:
        state["verify_calls"] = int(state["verify_calls"]) + 1  # type: ignore[call-overload]
        reading = state["reading"]
        if isinstance(reading, Exception):
            raise reading
        return reading  # type: ignore[return-value]

    monkeypatch.setattr(pipeline, "extract_document", fake_extract)
    monkeypatch.setattr(verify_mod, "read_independently", fake_read)
    monkeypatch.delenv("VERIFIER", raising=False)
    return state


async def test_agreement_keeps_proposed_and_attaches_verification(stub_models: dict[str, object]) -> None:
    p = await pipeline.process_image(b"img", "image/jpeg", LOCAL)
    assert p.status == "proposed"
    assert p.verification is not None and p.verification.agree_all
    assert p.verification.model == "ollama:muse-glimmer:30b"
    chk = next(c for c in p.checks if c.code == "VERIFIER_AGREES")
    assert chk.ok and chk.message == "Verifier agrees · all 6 fields match"


@pytest.mark.parametrize(
    ("change", "shown"),
    [
        ({"seller": "Toolstation"}, "supplier Screwfix Direct Ltd vs Toolstation"),
        ({"issue_date": "12/10/2026"}, "date 2026-10-21 vs 12/10/2026"),
        ({"amount_payable": 83.47}, "total 38.47 vs 83.47"),
        ({"vat_amount": 6.14}, "VAT 6.41 vs 6.14"),
        ({"vat_registration": None}, "VAT number GB 232 4567 89 vs none"),
    ],
)
async def test_disagreement_needs_a_look_with_both_values(
    stub_models: dict[str, object], change: dict[str, object], shown: str
) -> None:
    stub_models["reading"] = _reading(**change)
    p = await pipeline.process_image(b"img", "image/jpeg", LOCAL)
    assert p.status == "needs_a_look"
    assert p.verification is not None and not p.verification.agree_all
    assert any(r.startswith("VERIFIER_AGREES: Second reading differs:") and shown in r for r in p.reasons), p.reasons
    assert p.extracted.model_dump() == _doc().model_dump()  # Extractor's values are never replaced


async def test_verifier_skipped_when_checks_already_failed(stub_models: dict[str, object]) -> None:
    stub_models["doc"] = _doc(gross_total=40.00)  # net + VAT != gross -> hard fail
    p = await pipeline.process_image(b"img", "image/jpeg", LOCAL)
    assert p.status == "needs_a_look"
    assert p.verification is None and stub_models["verify_calls"] == 0


async def test_verifier_outage_is_a_warning_not_agreement(stub_models: dict[str, object]) -> None:
    stub_models["reading"] = ExtractionError("verifier ollama unreachable")
    p = await pipeline.process_image(b"img", "image/jpeg", LOCAL)
    assert p.status == "proposed"
    assert p.verification is not None and p.verification.error and not p.verification.agree_all
    chk = next(c for c in p.checks if c.code == "VERIFIER_AGREES")
    assert not chk.ok and chk.severity == "warn"


# --------------------------------------------------------------------------- #
# Wire format and malformed responses (fake transport, no network)
# --------------------------------------------------------------------------- #


def test_legal_suffix_dropped_only_at_the_end() -> None:
    assert field_agree("name", "Smith & Co. Ltd", "Smith and Co")
    assert not field_agree("name", "UK Fuels Ltd", "Fuels Ltd")
    assert not field_agree("name", "Co-op Food", "Op Food")


def _fake_client(monkeypatch: pytest.MonkeyPatch, handler: object) -> None:
    real = httpx.AsyncClient

    def factory(*a: object, **kw: object) -> httpx.AsyncClient:
        kw["transport"] = httpx.MockTransport(handler)  # type: ignore[arg-type]
        return real(*a, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(verify_mod.httpx, "AsyncClient", factory)


async def test_baseten_request_uses_owner_key_and_never_the_users(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        content = json.dumps(_reading().model_dump())
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    _fake_client(monkeypatch, handler)
    v = await verify(b"img", _doc(), KEY, env={"BASETEN_API_KEY": "owner-key"})
    assert v is not None and v.agree_all and v.model == f"baseten:{DEFAULT_BASETEN_MODEL}"
    (req,) = seen
    assert str(req.url) == "https://inference.baseten.co/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer owner-key"
    body = json.loads(req.content)
    assert body["model"] == DEFAULT_BASETEN_MODEL
    assert "user-key" not in req.content.decode() and "user-key" not in str(req.headers)
    assert "Screwfix" not in json.dumps(body["messages"])  # the first reading is never shown to the verifier


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>gateway</html>"),
        httpx.Response(200, json={"error": "no choices"}),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": "not json at all"}}]}),
        httpx.Response(401, json={"error": "bad key"}),
    ],
)
async def test_malformed_verifier_response_is_an_error_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    _fake_client(monkeypatch, lambda _req: response)
    v = await verify(b"img", _doc(), KEY, env={})
    assert v is not None and v.error and not v.agree_all and v.fields == {}
