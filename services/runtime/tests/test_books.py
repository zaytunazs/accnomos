"""Scan -> approve/reject -> rules -> summary against FakeStorageProvider, with extraction stubbed."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from accnomos_connectors.base import ConflictError
from accnomos_ledger.events import LedgerEvent

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline  # noqa: E402
from app.ai.config import AiConfig  # noqa: E402
from app.approve import ApprovalError, ProposalStateError, approve, reject  # noqa: E402
from app.books import AUDIT, CURSORS, DOCS, EVENTS, RULES, Books  # noqa: E402
from app.inbox import scan_inbox  # noqa: E402
from app.schemas import ExtractedDoc, ExtractedLine  # noqa: E402

CFG = AiConfig(mode="local", base_url="http://ollama.invalid", model="stub")
SCREWFIX = b"screwfix-jpeg"
SCREWFIX_2 = b"screwfix-jpeg-another-day"
TOOLSTATION = b"toolstation-jpeg"
FILED = "01 Receipts/2026-10/2026-10-21 Screwfix £38.47.jpg"


def _doc(supplier: str = "Screwfix", **kw: object) -> ExtractedDoc:
    base: dict[str, object] = dict(
        doc_type="receipt",
        supplier_name=supplier,
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


DOCS_BY_BYTES = {SCREWFIX: _doc(), SCREWFIX_2: _doc(date="2026-10-22"), TOOLSTATION: _doc("Toolstation")}


@pytest.fixture(autouse=True)
def stub_extract(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    calls: list[bytes] = []

    async def fake_extract(data: bytes, mime: str, cfg: AiConfig) -> tuple[ExtractedDoc, dict[str, str]]:
        calls.append(data)
        return DOCS_BY_BYTES[data], {"backend": "stub", "model": cfg.model}

    async def no_verifier(*_a: object, **_kw: object) -> None:
        return None

    monkeypatch.setattr(pipeline, "extract_document", fake_extract)
    monkeypatch.setattr(pipeline, "verify", no_verifier)
    return calls


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
def books(fake: FakeStorageProvider) -> Books:
    return Books(fake)


def _audit(fake: FakeStorageProvider) -> list[dict]:
    lines: list[dict] = []
    for path, data in sorted(fake.files.items()):
        if path.startswith(f"{AUDIT}/"):
            lines += [json.loads(x) for x in data.decode().splitlines()]
    return lines


def _events(fake: FakeStorageProvider) -> list[LedgerEvent]:
    return [LedgerEvent.model_validate_json(d) for p, d in fake.files.items() if p.startswith(f"{EVENTS}/")]


async def test_scan_files_good_receipt_and_parks_duplicate(fake: FakeStorageProvider, books: Books) -> None:
    fake.files.update(
        {
            "00 Inbox/a-receipt.jpg": SCREWFIX,
            "00 Inbox/b-copy.jpg": SCREWFIX,  # same bytes again
            "00 Inbox/c-invoice.pdf": b"%PDF-1.7",
            "00 Inbox/notes.txt": b"hello",  # only an email body saved by intake (.eml.txt) is a text document
        }
    )
    proposals = await scan_inbox(books, CFG)

    good, dup, pdf = proposals
    assert good.status == "proposed" and good.file_path == FILED and fake.files[FILED] == SCREWFIX
    assert dup.status == "needs_a_look" and dup.file_path == "02 Needs a look/2026-10-21 Screwfix £38.47.jpg"
    assert any(c.code == "DUPLICATE" and not c.ok for c in dup.checks)
    assert pdf.status == "needs_a_look" and pdf.file_path == "02 Needs a look/c-invoice.pdf"
    assert [c.code for c in pdf.checks] == ["UNREADABLE"]  # a truncated PDF (or no PDF reader on this server)
    assert [p for p in fake.files if p.startswith("00 Inbox/")] == ["00 Inbox/notes.txt"]
    assert await books.known_hashes() == {good.doc_sha256, pdf.doc_sha256}
    assert len([p for p in fake.files if p.startswith(f"{DOCS}/")]) == 2
    assert {p.id for p in await books.list_proposals()} == {good.id, dup.id, pdf.id}
    assert [a["action"] for a in _audit(fake)] == ["proposed"] * 3
    assert all(a["actor"] == "agent:extractor" for a in _audit(fake))
    assert "last_scan" in json.loads(fake.files[CURSORS])


async def test_name_collision_gets_numbered(fake: FakeStorageProvider, books: Books) -> None:
    fake.files[FILED] = b"something else already there"
    fake.files["00 Inbox/r.jpg"] = SCREWFIX
    (p,) = await scan_inbox(books, CFG)
    assert p.file_path == "01 Receipts/2026-10/2026-10-21 Screwfix £38.47 (2).jpg"


async def test_scan_respects_limit(fake: FakeStorageProvider, books: Books) -> None:
    fake.files.update({"00 Inbox/1.jpg": SCREWFIX, "00 Inbox/2.jpg": TOOLSTATION})
    assert len(await scan_inbox(books, CFG, limit=1)) == 1
    assert list(fake.files).count("00 Inbox/2.jpg") == 1


async def test_approve_posts_balanced_event_with_audit_and_rule(fake: FakeStorageProvider, books: Books) -> None:
    fake.files["00 Inbox/r.jpg"] = SCREWFIX
    (p,) = await scan_inbox(books, CFG)

    posted = await approve(books, p.id, "sam@example.co.uk", always=True)

    (event,) = _events(fake)
    assert sum(ln.debit for ln in event.lines) == sum(ln.credit for ln in event.lines) == 3847
    assert (event.kind, event.net, event.vat, event.evidence) == ("purchase", 3206, 641, [p.doc_sha256])
    assert event.approved_by == "sam@example.co.uk" and event.proposal_id == p.id
    (path,) = [k for k in fake.files if k.startswith(f"{EVENTS}/")]
    assert path.startswith(f"{EVENTS}/2026-10/") and path.endswith(f"-runtime-{event.id}.json")

    stored = await books.get_proposal(p.id)
    assert stored.status == posted.status == "posted" and stored.event_id == event.id
    assert stored.decided_by == "sam@example.co.uk"
    assert _audit(fake)[-1]["action"] == "approved" and _audit(fake)[-1]["actor"] == "user:sam@example.co.uk"
    (rule,) = json.loads(fake.files[RULES])
    assert rule["match"] == {"supplier_regex": "Screwfix"} and rule["account"] == "5100 Tools & small equipment"

    with pytest.raises(ProposalStateError):
        await approve(books, p.id, "sam@example.co.uk")


async def test_always_with_edited_account_applies_on_next_scan(fake: FakeStorageProvider, books: Books) -> None:
    fake.files["00 Inbox/r.jpg"] = SCREWFIX
    (p,) = await scan_inbox(books, CFG)
    await approve(books, p.id, "sam@example.co.uk", edits={"account": "5000 Materials"}, always=True)
    assert _events(fake)[0].lines[0].account == "5000 Materials"

    fake.files.update({"00 Inbox/s.jpg": SCREWFIX_2, "00 Inbox/t.jpg": TOOLSTATION})
    screwfix, toolstation = await scan_inbox(books, CFG)
    assert screwfix.account_override == "5000 Materials"
    assert screwfix.journal_draft[0].account == "5000 Materials"
    assert any(c.code == "RULE_APPLIED" for c in screwfix.checks)
    assert toolstation.account_override is None
    assert not any(c.code == "RULE_APPLIED" for c in toolstation.checks)


async def test_approving_a_needs_a_look_doc_refiles_it(fake: FakeStorageProvider, books: Books) -> None:
    fake.files["00 Inbox/scan.pdf"] = b"%PDF"
    (p,) = await scan_inbox(books, CFG)
    with pytest.raises(ApprovalError, match="Nothing to post"):
        await approve(books, p.id, "sam@example.co.uk")

    edits = {"supplier_name": "Screwfix", "net_total": 10, "vat_total": 2, "gross_total": 12, "category": "Materials"}
    posted = await approve(books, p.id, "sam@example.co.uk", edits=edits)
    assert posted.file_path is not None and posted.file_path.startswith("01 Receipts/")
    assert _events(fake)[0].lines[-1].credit == 1200


async def test_bad_edits_are_refused(fake: FakeStorageProvider, books: Books) -> None:
    fake.files["00 Inbox/r.jpg"] = SCREWFIX
    (p,) = await scan_inbox(books, CFG)
    with pytest.raises(ApprovalError):
        await approve(books, p.id, "sam@example.co.uk", edits={"approved_by": "agent"})
    with pytest.raises(ApprovalError):
        await approve(books, p.id, "sam@example.co.uk", edits={"category": "Yachts"})
    assert _events(fake) == []


async def test_reject_moves_file_to_needs_a_look(fake: FakeStorageProvider, books: Books) -> None:
    fake.files["00 Inbox/r.jpg"] = SCREWFIX
    (p,) = await scan_inbox(books, CFG)

    rejected = await reject(books, p.id, "sam@example.co.uk", "personal purchase")

    assert rejected.status == "rejected" and rejected.reject_reason == "personal purchase"
    assert rejected.file_path == "02 Needs a look/2026-10-21 Screwfix £38.47.jpg"
    assert FILED not in fake.files and rejected.file_path in fake.files
    assert (await books.get_proposal(p.id)).status == "rejected"
    assert _audit(fake)[-1]["action"] == "rejected"
    assert _events(fake) == []


async def test_audit_retries_once_on_conflict(books: Books, fake: FakeStorageProvider, monkeypatch) -> None:
    await books.audit("user:a", "first", {})
    real_write, failures = fake.write, [1]

    async def flaky_write(path: str, data: bytes, *, if_match: str | None = None):
        if failures and path.startswith(AUDIT):
            failures.pop()
            await real_write(path, (await fake.read(path)) + b'{"other":"device"}\n')  # someone else appends
            raise ConflictError(path)
        return await real_write(path, data, if_match=if_match)

    monkeypatch.setattr(fake, "write", flaky_write)
    await books.audit("user:a", "second", {})
    assert [a.get("action", "other") for a in _audit(fake)] == ["first", "other", "second"]


async def test_post_event_refuses_to_overwrite(books: Books, fake: FakeStorageProvider) -> None:
    fake.files["00 Inbox/r.jpg"] = SCREWFIX
    (p,) = await scan_inbox(books, CFG)
    await approve(books, p.id, "sam@example.co.uk")
    with pytest.raises(FileExistsError):
        await books.post_event(_events(fake)[0])


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


@pytest.fixture
def client(fake: FakeStorageProvider):
    from app.main import app
    from app.routes_books import get_books

    async def override() -> Books:
        return Books(fake)

    app.dependency_overrides[get_books] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


H = {"X-Graph-Token": "tok", "X-User": "sam@example.co.uk", "X-AI-Mode": "local"}


def test_routes_scan_approve_reject_summary(client: TestClient, fake: FakeStorageProvider) -> None:
    fake.files.update({"00 Inbox/a.jpg": SCREWFIX, "00 Inbox/b.jpg": TOOLSTATION, "00 Inbox/c.jpg": SCREWFIX})
    result = client.post("/books/scan", headers=H).json()
    scanned = result["proposals"]
    assert result["errors"] == []
    assert [p["status"] for p in scanned] == ["proposed", "proposed", "needs_a_look"]
    a, b, _dup = (p["id"] for p in scanned)

    assert len(client.get("/books/proposals?status=proposed", headers=H).json()) == 2
    assert client.get(f"/books/proposals/{a}", headers=H).json()["id"] == a
    assert client.get("/books/proposals/deadbeefdeadbeef", headers=H).status_code == 404

    no_user = {k: v for k, v in H.items() if k != "X-User"}
    assert client.post(f"/books/proposals/{a}/approve", headers=no_user, json={}).status_code == 400

    r = client.post(f"/books/proposals/{a}/approve", headers=H, json={"always": True})
    assert r.status_code == 200 and r.json()["status"] == "posted"
    assert client.post(f"/books/proposals/{a}/approve", headers=H, json={}).status_code == 409
    r = client.post(f"/books/proposals/{b}/reject", headers=H, json={"reason": "not ours"})
    assert r.status_code == 200 and r.json()["file_path"].startswith("02 Needs a look/")

    s = client.get("/books/summary", headers=H).json()
    assert (s["proposed"], s["needs_a_look"], s["posted_this_month"]) == (0, 1, 1)
    assert s["last_scan"] is not None


def test_books_routes_need_a_graph_token() -> None:
    from app.main import app

    client = TestClient(app)
    assert client.get("/books/summary").status_code == 401
    assert client.get("/books/summary", headers={"X-Graph-Token": "t", "X-Account-Kind": "team"}).status_code == 400


def test_today_is_the_london_date(monkeypatch: pytest.MonkeyPatch) -> None:
    """00:30 BST on the 1st is the 1st in London, still the 30th in UTC."""
    import app.books as books_mod
    from datetime import UTC
    from datetime import date as real_date
    from datetime import datetime as real_datetime

    fixed = real_datetime(2026, 9, 30, 23, 30, tzinfo=UTC)  # 1 Oct, 00:30 BST

    class _FixedDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return fixed if tz is None else fixed.astimezone(tz)

    class _FixedDate(real_date):
        @classmethod
        def today(cls) -> real_date:
            return real_date(2026, 9, 30)

    monkeypatch.setattr(books_mod, "datetime", _FixedDateTime)
    monkeypatch.setattr(books_mod, "date", _FixedDate)
    assert books_mod.today() == real_date(2026, 10, 1)
    assert books_mod.now().utcoffset() == books_mod.LONDON.utcoffset(fixed)
