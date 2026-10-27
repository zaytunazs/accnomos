"""Test mode (app/testmode.py): gold readings, the stub AI, the Graph look-alike and the shared fake storage."""

from __future__ import annotations

import base64
import hashlib
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import security, testmode
from app.ai import ask as ask_ai
from app.ai import extract as extract_ai
from app.ai import verify as verify_ai
from app.ai.config import TEST_AI_MODEL, AiConfig, is_test_mode
from app.books import INBOX, Books, today
from app.checks import decide, run_checks
from app.facts import build_facts, default_period
from app.routes_actions import _mail_sender
from app.routes_books import get_books
from app.routes_contacts import get_address_book
from app.routes_invoices import get_sender
from app.routes_mail import get_mail
from app.routes_mail import router as mail_router
from app.routes_plan import get_calendar
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


@pytest.mark.parametrize("value", ["0", "", "true", "yes", " 1"])
def test_only_exactly_1_turns_it_on(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("ACCNOMOS_TEST_MODE", value)
    assert not is_test_mode()


def test_docker_image_pins_it_off() -> None:
    dockerfile = Path(__file__).resolve().parents[3] / "deploy" / "Dockerfile.runtime"
    lines = dockerfile.read_text(encoding="utf-8").splitlines()
    assert "ENV ACCNOMOS_TEST_MODE=0" in lines
    assert not any("ACCNOMOS_TEST_MODE=1" in ln or "evals" in ln for ln in lines if not ln.lstrip().startswith("#"))


def test_forces_stub_ai_and_pins_today(test_env: None) -> None:
    cfg = AiConfig.resolve(mode="key", base_url="https://api.meta.ai/v1", api_key="k")
    assert (cfg.mode, cfg.base_url, cfg.model, cfg.api_key) == ("local", STUB, TEST_AI_MODEL, None)
    assert today() == date(2026, 10, 27)


def test_reset_seeds_the_sample_invoice_profile_and_opt_in_bank_entries(client: TestClient) -> None:
    from app.invoicing import PROFILE

    files = client.get("/__test/state").json()["files"]
    assert files == [PROFILE]  # nothing else until a flow writes it
    assert b"SAMPLE" in testmode.STATE.storage.files[PROFILE]

    assert client.post("/__test/reset?seed=bank").json()["seed"] == "bank"
    events = [f for f in client.get("/__test/state").json()["files"] if f.startswith("_System/Ledger/events/")]
    assert len(events) == 4  # the four entries barclays.csv pays for
    assert client.post("/__test/reset?seed=nope").status_code == 400
    client.post("/__test/reset")  # opt-in: the next plain reset drops them again (other specs check VAT figures)
    assert client.get("/__test/state").json()["files"] == [PROFILE]


def test_pinned_today_drives_plan_my_thursday(test_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ask resolved "Thursday" from the real clock, so the e2e plan flow only passed in the week of 27 Oct 2026."""
    from app.planner import TZ, plan_intent

    monkeypatch.setenv("ACCNOMOS_TEST_TODAY", "2026-10-27")
    assert today(TZ) == date(2026, 10, 27)  # what routes_ask and routes_plan pass as "today"
    assert plan_intent("Plan my Thursday", today(TZ)) == date(2026, 10, 29)


def test_browser_ai_base_url_is_accepted_then_swapped(test_env: None) -> None:
    """The web build points the browser at the stub; the allow-list must not refuse it (the e2e Ask/AI test 400'd)."""
    cfg = AiConfig.from_headers({"X-AI-Mode": "local", "X-AI-Base-Url": "http://127.0.0.1:8781/__test/ai"})
    assert (cfg.base_url, cfg.model) == (STUB, TEST_AI_MODEL)


def test_test_routes_skip_the_rate_limit(test_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The browser's Graph and AI calls come to /__test in test mode; only real runtime routes use the per-IP budget."""
    monkeypatch.setattr(security, "UNLIMITED_PREFIXES", ())
    monkeypatch.setenv("CROP_MODE", "off")  # enable() setdefaults it; keep it from leaking into other tests
    testmode.enable()
    assert security.UNLIMITED_PREFIXES == ("/__test/",)
    app = FastAPI()
    app.include_router(testmode.router)
    app.add_middleware(security.SecurityMiddleware, limiter=security.TokenBucket(2))
    c = TestClient(app)
    assert all(c.get("/__test/gold").status_code == 200 for _ in range(5))
    assert [c.get("/books/x").status_code for _ in range(3)] == [404, 404, 429]


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
    r = client.post(f"{g}/me/drive/items/{testmode.GRAPH_ROOT_ID}/children", json={"name": "06 Reports", "folder": {}})
    assert r.status_code == 201
    sys_id = r.json()["id"]
    assert client.post(f"{g}/me/drive/items/{sys_id}/children", json={"name": "audit", "folder": {}}).status_code == 201
    assert client.get(f"{g}/me/drive/special/approot:/06 Reports/audit").json()["folder"] == {"childCount": 0}
    assert client.post(f"{g}/me/drive/items/{testmode.GRAPH_ROOT_ID}/children", json={"name": "06 Reports"}).status_code == 409

    png = client.get("/__test/gold/011_standard.png").content
    put = client.put(f"{g}/me/drive/special/approot:/00 Inbox/r.png:/content", content=png, headers={"Content-Type": "image/png"})
    assert put.status_code == 201 and put.json()["size"] == len(png)
    names = {i["name"]: i for i in client.get(f"{g}/me/drive/special/approot/children").json()["value"]}
    assert set(names) == {"00 Inbox", "06 Reports", "_System"} and names["00 Inbox"]["size"] == len(png)
    inbox = client.get(f"{g}/me/drive/special/approot:/00 Inbox:/children").json()["value"]
    assert [(i["name"], i["file"]["mimeType"]) for i in inbox] == [("r.png", "image/png")]
    assert client.get(f"{g}/me/drive/root:/Accnomos/00 Inbox/r.png").json()["name"] == "r.png"  # work-account paths


def test_graph_lookalike_errors_are_graph_shaped(client: TestClient) -> None:
    g = "/__test/graph/v1.0"
    assert client.get(f"{g}/me/drive/root/children").json()["error"]["code"] == "itemNotFound"  # not a books root
    assert client.post(f"{g}/me/drive/items/t-%%%/children", json={"name": "x"}).status_code == 404  # not one of our ids
    missing = testmode._id("no/such/folder")
    assert client.post(f"{g}/me/drive/items/{missing}/children", json={"name": "x"}).status_code == 404
    assert client.post(f"{g}/me/drive/items/{testmode.GRAPH_ROOT_ID}/children", json={"folder": {}}).status_code == 400
    assert client.get(f"{g}/me/drive/items/{testmode.GRAPH_ROOT_ID}/children").status_code == 400
    assert client.get(f"{g}/me/drive/special/approot:/nope:/children").status_code == 404
    assert client.get("/__test/gold/999_nope.png").status_code == 404


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

    contacts = get_address_book(Req())  # type: ignore[arg-type]
    assert await contacts.__anext__() is testmode.STATE.contacts
    assert len(testmode.STATE.contacts.contacts) == len(testmode.MAIL_GOLD)

    # Sending and the day planner: the in-memory sender and calendar, never Graph.
    assert await get_sender(Req()).__anext__() is testmode.STATE.sender  # type: ignore[arg-type]
    assert _mail_sender("test-token")() is testmode.STATE.sender
    assert await get_calendar(Req()).__anext__() is testmode.STATE.calendar  # type: ignore[arg-type]
    assert [e.body_preview for e in await testmode.STATE.calendar.list_events(date(2026, 10, 29))] == [testmode.SAMPLE]


async def test_dependencies_still_need_a_token_in_test_mode(test_env: None) -> None:
    from fastapi import HTTPException

    class Req:
        headers: dict[str, str] = {}

    for dep in (get_books, get_mail, get_address_book, get_sender, get_calendar):
        with pytest.raises(HTTPException) as exc:
            await dep(Req()).__anext__()  # type: ignore[arg-type]
        assert exc.value.status_code == 401


async def test_reset_seeds_sample_calendar(test_env: None) -> None:
    await testmode.reset()
    (cid,) = testmode.STATE.calendar.all_day
    ((date_, title, body),) = testmode.STATE.calendar.all_day[cid].values()
    assert (date_, body) == ("2026-11-07", "SAMPLE — FICTIONAL COMPANY") and "VAT return due" in title
