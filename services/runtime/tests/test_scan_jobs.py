"""Background scan jobs (app/scan_jobs.py, app/routes_scan.py) with a slow fake model.

Covers: the start call answering at once; per-file progress uploaded -> reading -> confirm -> checking -> ready;
nothing read in full, filed or proposed before the user confirms the type; routing by the confirmed type (Review,
Sales, the bank-lines import, Needs a look); time limits per document and per AI call with their plain messages; the
work carrying on with no client polling; a job found again from the books under a new token; an interrupted job.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import inbox, pipeline, scan_jobs  # noqa: E402
from app.ai import chain  # noqa: E402
from app.ai import classify as classify_ai  # noqa: E402
from app.ai.classify import Guess  # noqa: E402
from app.ai.config import AiConfig  # noqa: E402
from app.ai.extract import ExtractionError  # noqa: E402
from app.books import Books, now  # noqa: E402
from app.schemas import ExtractedDoc, ExtractedLine  # noqa: E402

SCREWFIX = b"\xff\xd8 screwfix receipt " + b"y" * 30_000  # big enough for Outlook intake to keep
STORAGE_BILL = b"storage-invoice-jpeg"
OUR_SALE = b"our-sale-jpeg"
STATEMENT = b"""Date,Description,Amount,Balance
21/10/2026,CARD PAYMENT SCREWFIX 1234,-38.47,961.53
22/10/2026,ACME KITCHENS INV 42,"1,200.00","2,161.53"
"""
H = {
    "X-Graph-Token": "tok",
    "X-User": "sam@example.co.uk",
    "X-AI-Mode": "local",
    "X-Business-Name": "Bramblewood Joinery Ltd",
}


def _doc(supplier: str, doc_type: str = "receipt", **kw: object) -> ExtractedDoc:
    return ExtractedDoc.model_validate(
        dict(
            customer_name=kw.pop("customer_name", None),
            doc_type=doc_type,
            supplier_name=supplier,
            supplier_vat_number="GB 232 4567 89",
            invoice_number=None,
            date="2026-10-21",
            currency="GBP",
            lines=[ExtractedLine(description="Item", qty=1, unit_price=38.47, net=32.06, vat_rate=20, vat=6.41)],
            net_total=32.06,
            vat_total=6.41,
            gross_total=38.47,
            payment_method="card",
            card_last4=None,
            category_guess="Sundry",
            confidence=0.95,
        )
    )


READINGS = {
    SCREWFIX: _doc("Screwfix"),
    STORAGE_BILL: _doc("Big Yellow", "purchase_invoice"),
    OUR_SALE: _doc("Bramblewood Joinery Ltd", "sales_invoice", customer_name="Acme"),
}
KINDS = {SCREWFIX: "receipt", STORAGE_BILL: "purchase_invoice", OUR_SALE: "sales_invoice"}


class SlowModel:
    """Answers after `delay` seconds; records every call."""

    def __init__(self) -> None:
        self.classify_delay = 0.2
        self.extract_delay = 0.2
        self.classified: list[bytes] = []
        self.extracted: list[bytes] = []

    async def classify(self, image: bytes | None, mime: str | None, cfg: AiConfig, **_kw: Any) -> Guess:
        self.classified.append(image or b"")
        await asyncio.sleep(self.classify_delay)
        return Guess(kind=KINDS.get(image or b"", "other"), confidence=0.87, reason="Fake model")  # type: ignore[arg-type]

    async def extract(self, data: bytes, mime: str, cfg: AiConfig, **_kw: Any) -> tuple[ExtractedDoc, dict]:
        self.extracted.append(data)
        await asyncio.sleep(self.extract_delay)
        return READINGS[data], {"backend": "stub", "model": cfg.model}


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> SlowModel:
    m = SlowModel()

    async def no_verifier(*_a: object, **_kw: object) -> None:
        return None

    monkeypatch.setattr(scan_jobs.classify_ai, "classify", m.classify)
    monkeypatch.setattr(pipeline, "extract_document", m.extract)
    monkeypatch.setattr(pipeline, "verify", no_verifier)
    scan_jobs.reset_for_tests()
    return m


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
def client(fake: FakeStorageProvider, model: SlowModel):
    from app.main import app
    from app.routes_books import get_books
    from app.routes_scan import books_opener

    async def override() -> Books:
        return Books(fake)

    @asynccontextmanager
    async def opened():
        yield Books(fake)

    app.dependency_overrides[get_books] = override
    app.dependency_overrides[books_opener] = lambda: opened
    with TestClient(app) as c:  # one event loop for the whole test, so background tasks keep running
        yield c
    app.dependency_overrides.clear()


def _wait(client: TestClient, job_id: str, until: str = "done", seconds: float = 10) -> dict:
    deadline = time.monotonic() + seconds
    while True:
        job = client.get(f"/books/scan/jobs/{job_id}", headers=H).json()
        if job["status"] == until or time.monotonic() > deadline:
            return job
        time.sleep(0.05)


def _stages(job: dict) -> dict[str, str]:
    return {f["name"]: f["stage"] for f in job["files"]}


def test_start_answers_at_once_and_shows_progress(client: TestClient, fake: FakeStorageProvider, model) -> None:
    model.classify_delay = 0.5
    fake.files.update({"00 Inbox/currys.jpg": SCREWFIX, "00 Inbox/storage.jpg": STORAGE_BILL})
    t0 = time.monotonic()
    r = client.post("/books/scan/jobs", headers=H, json={"names": ["currys.jpg", "storage.jpg"]})
    assert r.status_code == 202 and time.monotonic() - t0 < 0.4  # never waits on the model
    job = r.json()
    assert job["status"] == "working" and job["progress"] == pytest.approx(0.1)
    assert set(_stages(job).values()) == {"uploaded"}

    seen: set[str] = set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(f"/books/scan/jobs/{job['id']}", headers=H).json()
        seen |= set(_stages(job).values())
        if job["status"] == "waiting":
            break
        time.sleep(0.05)
    assert "reading" in seen
    assert job["status"] == "waiting" and job["counts"]["to_confirm"] == 2
    guesses = {f["name"]: (f["guess"]["kind"], f["guess"]["confidence"]) for f in job["files"]}
    assert guesses == {"currys.jpg": ("receipt", 0.87), "storage.jpg": ("purchase_invoice", 0.87)}
    assert job["progress"] == pytest.approx(0.5)
    saved = json.loads(fake.files[f"_System/Scans/{job['id']}.json"])  # progress kept in the user's own books
    assert {f["stage"] for f in saved["files"]} == {"confirm"}


def test_nothing_is_read_filed_or_proposed_before_the_type_is_confirmed(client, fake, model) -> None:
    fake.files["00 Inbox/currys.jpg"] = SCREWFIX
    job = client.post("/books/scan/jobs", headers=H, json={}).json()
    job = _wait(client, job["id"], "waiting")
    time.sleep(0.3)
    assert model.extracted == []  # only the short "what is it?" call ran
    assert "00 Inbox/currys.jpg" in fake.files
    assert client.get("/books/proposals", headers=H).json() == []

    no_user = {k: v for k, v in H.items() if k != "X-User"}
    body = {"files": [{"name": "currys.jpg", "kind": "receipt"}]}
    assert client.post(f"/books/scan/jobs/{job['id']}/confirm", headers=no_user, json=body).status_code == 400
    r = client.post(f"/books/scan/jobs/{job['id']}/confirm", headers=H, json=body)
    assert r.status_code == 200 and _stages(r.json())["currys.jpg"] == "checking"
    assert client.post(f"/books/scan/jobs/{job['id']}/confirm", headers=H, json=body).status_code == 409

    job = _wait(client, job["id"])
    (f,) = job["files"]
    assert (f["stage"], f["route"], f["kind"], f["progress"]) == ("ready", "review", "receipt", 1.0)
    (p,) = client.get("/books/proposals", headers=H).json()
    assert p["id"] == f["proposal_id"] and p["status"] == "proposed"  # waits in Review: nothing is posted
    assert "00 Inbox/currys.jpg" not in fake.files
    audit = b"".join(v for k, v in fake.files.items() if k.startswith("_System/audit/")).decode()
    assert "scan_type_confirmed" in audit and "sam@example.co.uk" in audit


def test_routing_by_confirmed_type(client: TestClient, fake: FakeStorageProvider, model) -> None:
    fake.files.update(
        {
            "00 Inbox/sale.jpg": OUR_SALE,
            "00 Inbox/statement.csv": STATEMENT,
            "00 Inbox/payslip.jpg": b"a-payslip",
            "00 Inbox/letter.jpg": b"a-letter",
        }
    )
    job = _wait(client, client.post("/books/scan/jobs", headers=H, json={}).json()["id"], "waiting")
    guesses = {f["name"]: f["guess"] for f in job["files"]}
    assert guesses["statement.csv"]["kind"] == "bank_statement" and guesses["statement.csv"]["by"] == "code"
    assert len(model.classified) == 3  # the CSV never reaches the model
    confirm = [
        {"name": "sale.jpg", "kind": "sales_invoice"},
        {"name": "statement.csv", "kind": "bank_statement"},
        {"name": "payslip.jpg", "kind": "payslip"},
        {"name": "letter.jpg", "kind": "other"},
    ]
    client.post(f"/books/scan/jobs/{job['id']}/confirm", headers=H, json={"files": confirm})
    job = _wait(client, job["id"])
    by = {f["name"]: f for f in job["files"]}
    assert (by["sale.jpg"]["route"], by["sale.jpg"]["stage"]) == ("sales", "ready")
    assert (by["statement.csv"]["route"], by["statement.csv"]["stage"]) == ("bank", "ready")
    assert by["statement.csv"]["message"] == "2 new bank lines: match them on Bank."
    assert (by["payslip.jpg"]["route"], by["payslip.jpg"]["stage"]) == ("needs_a_look", "needs_a_look")
    assert "Payroll" in by["payslip.jpg"]["message"]
    assert by["letter.jpg"]["route"] == "needs_a_look"
    assert len(model.extracted) == 1  # only the sale was read in full
    assert len(client.get("/books/bank/lines", headers=H).json()) == 2
    assert not any(k.startswith("00 Inbox/") for k in fake.files)
    flagged = client.get("/books/proposals?status=needs_a_look", headers=H).json()
    assert {p["id"] for p in flagged} == {by["payslip.jpg"]["proposal_id"], by["letter.jpg"]["proposal_id"]}
    (sale,) = client.get("/books/proposals?status=proposed", headers=H).json()
    assert sale["extracted"]["doc_type"] == "sales_invoice"


def test_a_type_across_sides_sends_the_card_to_needs_a_look(client, fake, model) -> None:
    fake.files["00 Inbox/storage.jpg"] = STORAGE_BILL  # read as a bill
    job = _wait(client, client.post("/books/scan/jobs", headers=H, json={}).json()["id"], "waiting")
    client.post(
        f"/books/scan/jobs/{job['id']}/confirm",
        headers=H,
        json={"files": [{"name": "storage.jpg", "kind": "sales_invoice"}]},
    )
    (f,) = _wait(client, job["id"])["files"]
    assert f["stage"] == "needs_a_look"
    p = client.get(f"/books/proposals/{f['proposal_id']}", headers=H).json()
    assert p["extracted"]["doc_type"] == "sales_invoice"
    assert any(c["code"] == "DOC_KIND" and "Check who issued it" in c["message"] for c in p["checks"])


def test_classification_timeout_falls_back_to_codes_guess(client, fake, model, monkeypatch) -> None:
    model.classify_delay = 5
    monkeypatch.setattr(scan_jobs, "CLASSIFY_TIMEOUT_S", 0.2)
    monkeypatch.setattr(inbox, "GRACE_S", 0.1)
    fake.files["00 Inbox/currys.jpg"] = SCREWFIX
    t0 = time.monotonic()
    job = _wait(client, client.post("/books/scan/jobs", headers=H, json={}).json()["id"], "waiting")
    assert time.monotonic() - t0 < 3
    (f,) = job["files"]
    assert f["guess"] == {"kind": "receipt", "confidence": 0.3, "reason": scan_jobs.PHOTO_GUESS.reason, "by": "code"}
    assert f["message"] == "The AI did not answer in time, so this guess is from code. Please check the type."


def test_document_timeout_leaves_the_file_in_the_inbox_with_a_plain_message(client, fake, model, monkeypatch) -> None:
    model.extract_delay = 5
    monkeypatch.setattr(inbox, "DOC_TIMEOUT_S", 0.3)
    monkeypatch.setattr(inbox, "GRACE_S", 0.1)
    fake.files["00 Inbox/currys.jpg"] = SCREWFIX
    job = _wait(client, client.post("/books/scan/jobs", headers=H, json={}).json()["id"], "waiting")
    client.post(
        f"/books/scan/jobs/{job['id']}/confirm", headers=H, json={"files": [{"name": "currys.jpg", "kind": "receipt"}]}
    )
    t0 = time.monotonic()
    (f,) = _wait(client, job["id"])["files"]
    assert time.monotonic() - t0 < 3
    assert (f["stage"], f["route"]) == ("failed", "inbox")
    assert f["message"] == inbox.timeout_message(0.3)
    assert "00 Inbox/currys.jpg" in fake.files  # for the next scan


def test_work_continues_with_nobody_polling(client: TestClient, fake: FakeStorageProvider, model) -> None:
    """The user leaves the page: no request at all until the job is done, then a fresh token finds it."""
    fake.files["00 Inbox/currys.jpg"] = SCREWFIX
    job_id = client.post("/books/scan/jobs", headers=H, json={}).json()["id"]
    time.sleep(1.0)  # no polling
    saved = json.loads(fake.files[f"_System/Scans/{job_id}.json"])
    assert saved["files"][0]["stage"] == "confirm"
    client.post(
        f"/books/scan/jobs/{job_id}/confirm", headers=H, json={"files": [{"name": "currys.jpg", "kind": "receipt"}]}
    )
    time.sleep(1.0)
    saved = json.loads(fake.files[f"_System/Scans/{job_id}.json"])
    assert saved["files"][0]["stage"] == "ready"
    assert any(k.startswith("_System/Proposals/") or "proposal" in k.lower() for k in fake.files)
    scan_jobs.LIVE[job_id].owner = "a-token-that-has-since-been-refreshed"
    fresh = client.get(f"/books/scan/jobs/{job_id}", headers={**H, "X-Graph-Token": "new"}).json()
    assert fresh["status"] == "done"
    listed = client.get("/books/scan/jobs", headers=H).json()
    assert [j["id"] for j in listed["jobs"]] == [job_id] and listed["working"] == 0


def test_a_job_whose_work_stopped_reads_as_interrupted(client: TestClient, fake: FakeStorageProvider) -> None:
    job = scan_jobs.ScanJob(
        id="ab" * 16,
        created_at=now() - timedelta(hours=1),
        updated_at=now() - timedelta(hours=1),
        files=[scan_jobs.ScanFile(name="a.jpg", path="00 Inbox/a.jpg", stage="checking", kind="receipt")],
    )
    fake.files[f"_System/Scans/{job.id}.json"] = job.model_dump_json().encode()
    got = client.get(f"/books/scan/jobs/{job.id}", headers=H).json()
    assert got["interrupted"] is True and got["files"][0]["stage"] == "failed"
    assert "still in 00 Inbox" in got["files"][0]["message"]
    assert client.get("/books/scan/jobs/" + "cd" * 16, headers=H).status_code == 404
    assert client.get("/books/scan/jobs/not-an-id", headers=H).status_code == 404


def test_missing_and_path_names(client: TestClient, fake: FakeStorageProvider) -> None:
    assert client.post("/books/scan/jobs", headers=H, json={"names": ["../x.jpg"]}).status_code == 400
    job = client.post("/books/scan/jobs", headers=H, json={"names": ["gone.jpg"]}).json()
    assert job["status"] == "done" and job["files"][0]["message"].startswith("Not in 00 Inbox")


def test_plain_scan_leaves_files_a_job_is_reading(client: TestClient, fake: FakeStorageProvider, model) -> None:
    model.classify_delay = 1.0
    fake.files.update({"00 Inbox/currys.jpg": SCREWFIX, "00 Inbox/storage.jpg": STORAGE_BILL})
    client.post("/books/scan/jobs", headers=H, json={"names": ["currys.jpg"]})
    result = client.post("/books/scan", headers=H).json()
    assert [p["source_name"] for p in result["proposals"]] == ["storage.jpg"]
    assert "00 Inbox/currys.jpg" in fake.files


def test_plain_scan_has_a_document_budget(client: TestClient, fake: FakeStorageProvider, model, monkeypatch) -> None:
    model.extract_delay = 5
    monkeypatch.setattr(inbox, "DOC_TIMEOUT_S", 0.2)
    monkeypatch.setattr(inbox, "GRACE_S", 0.1)
    fake.files.update({"00 Inbox/a.jpg": SCREWFIX, "00 Inbox/b.jpg": STORAGE_BILL})
    t0 = time.monotonic()
    result = client.post("/books/scan", headers=H).json()
    assert time.monotonic() - t0 < 2
    assert [e["error"] for e in result["errors"]] == [inbox.timeout_message(0.2)] * 2


# --------------------------------------------------------------------------- #
# Per-call caps (app/ai/chain.py) and the classifier
# --------------------------------------------------------------------------- #


async def test_call_cap_cuts_off_a_slow_attempt() -> None:
    cfg = AiConfig(mode="local", base_url="http://x.invalid", model="m")

    async def slow(_c: AiConfig) -> str:
        await asyncio.sleep(5)
        return "late"

    t0 = time.monotonic()
    with chain.limits(call_s=0.1), pytest.raises(httpx.ReadTimeout):
        await chain.run(cfg, "test", slow)
    assert time.monotonic() - t0 < 1


async def test_a_spent_deadline_is_not_the_providers_fault() -> None:
    chain.BREAKER.reset()
    a = AiConfig(mode="local", base_url="http://a.invalid", model="m", provider="meta", in_chain=True)
    b = AiConfig(mode="local", base_url="http://b.invalid", model="m", provider="spark", in_chain=True)
    cfg = a.model_copy(update={"fallbacks": [b]})
    tried: list[str] = []

    async def slow(c: AiConfig) -> str:
        tried.append(c.provider)
        await asyncio.sleep(5)
        return "late"

    with chain.limits(deadline=time.monotonic() + 0.1), pytest.raises(chain.OutOfTime):
        await chain.run(cfg, "test", slow)
    assert tried == ["meta"]  # no failover once the document's time is up
    assert chain.BREAKER.failures.get("meta", 0) == 0


def test_attempt_limit_takes_the_least() -> None:
    c = AiConfig(mode="local", base_url="http://a.invalid", model="m", request_s=120)
    assert chain.attempt_limit(c) == 120
    with chain.limits(call_s=90):
        assert chain.attempt_limit(c) == 90
        with chain.limits(call_s=90, deadline=100.0):
            assert chain.attempt_limit(c, now=70.0) == 30


async def test_classifier_parses_the_models_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = AiConfig(mode="local", base_url="http://x.invalid", model="m")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["messages"][0]["content"] == classify_ai.SYSTEM_PROMPT
        assert "images" not in body["messages"][1]  # text first: no image when the PDF has words
        reply = {"kind": "bank_statement", "confidence": 85, "reason": "Balances listed"}
        return httpx.Response(200, json={"message": {"content": json.dumps(reply)}})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        classify_ai.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    g = await classify_ai.classify(None, None, cfg, text="Opening balance 100.00")
    assert (g.kind, g.confidence, g.by) == ("bank_statement", 0.85, "ai")

    def nonsense(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": '{"kind": "pizza", "confidence": 1, "reason": ""}'}})

    monkeypatch.setattr(
        classify_ai.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(nonsense), **kw)
    )
    with pytest.raises(ExtractionError):
        await classify_ai.classify(None, None, cfg, text="hello")


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("PAYSLIP Tax code 1257L Net pay", "payslip"),
        ("Statement of account Opening balance", "bank_statement"),
        ("CREDIT NOTE CN-12", "credit_note"),
        ("INVOICE 1001 Amount due", "purchase_invoice"),
        ("Bramblewood Joinery Ltd\nINVOICE 7", "sales_invoice"),
        ("Thank you for shopping TOTAL 3.20", "receipt"),
        ("Dear Sam, about your lease", "other"),
    ],
)
def test_codes_guess_from_the_words(text: str, kind: str) -> None:
    g = classify_ai.by_words(text, business_name="Bramblewood Joinery Ltd")
    assert g.kind == kind and g.by == "code" and g.confidence < 0.5


def test_email_intake_starts_the_same_job(client: TestClient, fake: FakeStorageProvider, model) -> None:
    from datetime import UTC, datetime

    from accnomos_connectors import FakeMailProvider, MailAttachment, MailMessage
    from app.main import app
    from app.routes_mail import get_mail

    mail = FakeMailProvider()
    mail.add(
        MailMessage(
            id="m1",
            received_at=datetime.now(UTC) - timedelta(hours=2),
            from_address="orders@screwfix.com",
            from_name="Screwfix",
            subject="Your receipt",
        ),
        (MailAttachment(id="a1", name="receipt.jpg", content_type="image/jpeg", size=len(SCREWFIX)), SCREWFIX),
    )

    async def mail_override():
        yield mail

    app.dependency_overrides[get_mail] = mail_override
    plain = client.post("/mail/scan", headers=H, json={"dry_run": True}).json()
    assert plain["scan_job_id"] is None  # older clients: files land in 00 Inbox only
    r = client.post("/mail/scan", headers=H, json={"read_now": True}).json()
    (name,) = r["saved"]
    job = _wait(client, r["scan_job_id"], "waiting")
    assert job["source"] == "email" and [(f["name"], f["guess"]["kind"]) for f in job["files"]] == [(name, "receipt")]
    client.post(f"/books/scan/jobs/{job['id']}/confirm", headers=H, json={"files": [{"name": name, "kind": "receipt"}]})
    (f,) = _wait(client, job["id"])["files"]
    assert f["stage"] == "ready"
    assert client.get(f"/books/proposals/{f['proposal_id']}", headers=H).json()["source_mailbox"]
