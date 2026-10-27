"""Test mode (app/testmode.py): gold readings, the stub AI, the Graph look-alike and the shared fake storage."""

from __future__ import annotations

import base64
import hashlib
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import testmode
from app.ai import ask as ask_ai
from app.ai import extract as extract_ai
from app.ai import verify as verify_ai
from app.ai.config import TEST_AI_MODEL, AiConfig
from app.books import INBOX, Books, today
from app.checks import decide, run_checks
from app.facts import build_facts, default_period
from app.routes_books import get_books
from app.routes_mail import router as mail_router
from app.schemas import AskModelOutput, ExtractedDoc

STUB = "http://127.0.0.1:8780/__test/ai"


@pytest.fixture
def test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", "1")
    monkeypatch.setenv("ACCNOMOS_TEST_TODAY", testmode.DEFAULT_TODAY)
    monkeypatch.delenv("ACCNOMOS_TEST_AI_BASE", raising=False)
    monkeypatch.delenv("PORT", raising=False)


@pytest.fixture
def client(test_env: None) -> TestClient:
    app = FastAPI()
    app.include_router(testmode.router)
    app.include_router(mail_router)
    c = TestClient(app)
    assert c.post("/__test/reset").json()["ok"]
    return c


def test_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ACCNOMOS_TEST_MODE", raising=False)
    monkeypatch.setenv("ACCNOMOS_TEST_TODAY", "2001-01-01")
    assert today() == date.today()
    assert AiConfig.resolve(mode="local", base_url="http://agent:11434").base_url == "http://agent:11434"


def test_forces_stub_ai_and_pins_today(test_env: None) -> None:
    cfg = AiConfig.resolve(mode="key", base_url="https://api.meta.ai/v1", api_key="k")
    assert (cfg.mode, cfg.base_url, cfg.model, cfg.api_key) == ("local", STUB, TEST_AI_MODEL, None)
    assert today() == date(2026, 10, 27)


def test_every_gold_receipt_reads_and_standard_ones_pass() -> None:
    for file, gold in testmode.gold_receipts().items():
        doc = ExtractedDoc.model_validate(testmode.extracted_from_gold(gold))
        reading = verify_ai.VerifierReading.model_validate(testmode.verifier_reading_from_gold(gold))
        assert verify_ai.compare(doc, reading, "stub").agree_all, file
        if gold["gold_case"] == "standard":
            status, reasons = decide(run_checks(doc, known_hashes=set(), this_hash="x"))
            assert status == "proposed", (file, reasons)


def test_stub_ai_reads_gold_png_by_hash(client: TestClient) -> None:
    png = client.get("/__test/gold/001_standard.png").content
    listed = {g["file"]: g for g in client.get("/__test/gold").json()}
    assert listed["001_standard.json"]["png_sha256"] == hashlib.sha256(png).hexdigest()
    b64 = base64.b64encode(png).decode()

    def chat(system: str, image: str) -> dict:
        r = client.post("/__test/ai/api/chat", json={"messages": [{"role": "system", "content": system},
                                                                   {"role": "user", "content": "x", "images": [image]}]})
        return r

    r = chat(extract_ai.SYSTEM_PROMPT, b64)
    assert r.status_code == 200
    doc = ExtractedDoc.model_validate(extract_ai.parse_model_json(r.json()["message"]["content"]))
    assert (doc.supplier_name, doc.gross_total, doc.category_guess) == ("Novex Office Supplies Ltd", 51.9, "Office supplies")
    assert chat(verify_ai.VERIFIER_SYSTEM_PROMPT, b64).status_code == 200
    assert chat(extract_ai.SYSTEM_PROMPT, base64.b64encode(b"not a gold receipt").decode()).status_code == 422
    assert client.get("/__test/ai/api/tags").json()["models"][0]["name"] == TEST_AI_MODEL


async def test_stub_ask_reply_is_grounded(test_env: None) -> None:
    await testmode.reset()
    facts = await build_facts(Books(testmode.STATE.storage), default_period(today()))
    out = AskModelOutput.model_validate(testmode.ask_reply(facts))
    answer = ask_ai.ground(out, facts, TEST_AI_MODEL)
    assert answer.fallback_reason is None and len(answer.key_numbers) >= 2


def test_graph_lookalike_shares_storage_with_runtime(client: TestClient) -> None:
    g = "/__test/graph/v1.0"
    assert client.get(f"{g}/me/drive/special/approot").json()["id"] == testmode.GRAPH_ROOT_ID
    assert client.get(f"{g}/me/drive/special/approot:/00 Inbox").status_code == 404
    r = client.post(f"{g}/me/drive/items/{testmode.GRAPH_ROOT_ID}/children", json={"name": "_System", "folder": {}})
    assert r.status_code == 201
    sys_id = r.json()["id"]
    assert client.post(f"{g}/me/drive/items/{sys_id}/children", json={"name": "audit", "folder": {}}).status_code == 201
    assert client.get(f"{g}/me/drive/special/approot:/_System/audit").json()["folder"] == {"childCount": 0}
    assert client.post(f"{g}/me/drive/items/{testmode.GRAPH_ROOT_ID}/children", json={"name": "_System"}).status_code == 409

    png = client.get("/__test/gold/011_standard.png").content
    put = client.put(f"{g}/me/drive/special/approot:/00 Inbox/r.png:/content", content=png, headers={"Content-Type": "image/png"})
    assert put.status_code == 201 and put.json()["size"] == len(png)
    names = {i["name"]: i for i in client.get(f"{g}/me/drive/special/approot/children").json()["value"]}
    assert set(names) == {"00 Inbox", "_System"} and names["00 Inbox"]["size"] == len(png)
    inbox = client.get(f"{g}/me/drive/special/approot:/00 Inbox:/children").json()["value"]
    assert [(i["name"], i["file"]["mimeType"]) for i in inbox] == [("r.png", "image/png")]
    assert client.get(f"{g}/me/drive/root:/Accnomos/00 Inbox/r.png").json()["name"] == "r.png"  # work-account paths


async def test_runtime_dependencies_use_the_fakes(client: TestClient) -> None:
    class Req:
        headers = {"X-Graph-Token": "test-token"}

    gen = get_books(Req())  # type: ignore[arg-type]
    books = await gen.__anext__()
    assert books.storage is testmode.STATE.storage
    await books.storage.write(f"{INBOX}/a.png", b"x")
    assert "00 Inbox/a.png" in client.get("/__test/state").json()["files"]

    r = client.post("/mail/scan", json={"dry_run": True}, headers={"X-Graph-Token": "test-token", "X-User": "sam@example.co.uk"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] and len(body["items"]) == len(testmode.MAIL_GOLD)  # the newsletter's .ics is skipped
    assert [p for p in testmode.STATE.storage.files if p.startswith(INBOX)] == ["00 Inbox/a.png"]  # nothing copied
