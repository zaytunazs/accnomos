"""Autopilot L1: rules from "Always do this", auto-approval only when nothing looks off, undo by reversal."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import pytest
from accnomos_connectors import FakeStorageProvider
from accnomos_ledger.events import LedgerEvent
from accnomos_ledger.vat import compute_vat_return
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import autopilot, pipeline  # noqa: E402
from app.ai.config import AiConfig  # noqa: E402
from app.approve import ApprovalError, ProposalStateError, approve, undo  # noqa: E402
from app.books import AUDIT, AUTOPILOT_AUDIT, AUTOPILOT_RULES, EVENTS, Books  # noqa: E402
from app.inbox import scan_inbox  # noqa: E402
from app.schemas import ExtractedDoc, ExtractedLine  # noqa: E402

CFG = AiConfig(mode="local", base_url="http://ollama.invalid", model="stub")
USER = "sam@example.co.uk"


def _doc(supplier: str = "Screwfix", gross: float = 38.47, **kw: object) -> ExtractedDoc:
    """A receipt that passes every check: one 20% line, VAT number printed, confident read."""
    net = round(gross / 1.2, 2)
    vat = round(gross - net, 2)
    base: dict[str, object] = dict(
        doc_type="receipt", supplier_name=supplier, supplier_vat_number="GB 232 4567 89", customer_name=None,
        invoice_number=None, date="2026-10-21", currency="GBP",
        lines=[ExtractedLine(description="Drill bits", qty=1, unit_price=gross, net=net, vat_rate=20, vat=vat)],
        net_total=net, vat_total=vat, gross_total=gross, payment_method="card", card_last4="1234",
        category_guess="Tools & small equipment", confidence=0.95,
    )
    base.update(kw)
    return ExtractedDoc.model_validate(base)


DOCS: dict[bytes, ExtractedDoc] = {
    b"first": _doc(),
    b"again": _doc("SCREWFIX LTD", gross=41.10, date="2026-10-24"),
    b"double": _doc(gross=76.94, date="2026-10-25"),  # exactly 2x the first: still allowed
    b"too-big": _doc(gross=80.00, date="2026-10-25"),
    b"low-confidence": _doc(confidence=0.5, date="2026-10-26"),
    b"other-vrn": _doc(supplier_vat_number="GB 999 9999 99", date="2026-10-26"),
    b"no-vrn": _doc(supplier_vat_number=None, vat_total=0, net_total=38.47,
                    lines=[ExtractedLine(description="Bits", qty=1, unit_price=38.47, net=38.47, vat_rate=0, vat=0)]),
    b"zero-rated": _doc(net_total=38.47, vat_total=0,
                        lines=[ExtractedLine(description="Bits", qty=1, unit_price=38.47, net=38.47, vat_rate=0, vat=0)]),
    b"toolstation": _doc("Toolstation"),
}


@pytest.fixture(autouse=True)
def stub_extract(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_extract(data: bytes, mime: str, cfg: AiConfig) -> tuple[ExtractedDoc, dict[str, str]]:
        return DOCS[data], {"backend": "stub", "model": cfg.model}

    monkeypatch.setattr(pipeline, "extract_document", fake_extract)


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
def books(fake: FakeStorageProvider) -> Books:
    return Books(fake)


def _events(fake: FakeStorageProvider) -> list[LedgerEvent]:
    return [LedgerEvent.model_validate_json(d) for p, d in sorted(fake.files.items()) if p.startswith(f"{EVENTS}/")]


def _jsonl(fake: FakeStorageProvider, prefix: str) -> list[dict]:
    return [json.loads(x) for p, d in sorted(fake.files.items()) if p.startswith(prefix) for x in d.decode().splitlines()]


async def _scan(fake: FakeStorageProvider, books: Books, *names: bytes, on: bool = True):
    for i, n in enumerate(names):
        fake.files[f"00 Inbox/{i}-{n.decode()}.jpg"] = n
    return await scan_inbox(books, CFG, autopilot_on=on)


async def _learn(fake: FakeStorageProvider, books: Books) -> None:
    """The user approves the first Screwfix receipt with "Always do this for Screwfix" ticked."""
    (p,) = await _scan(fake, books, b"first")
    await approve(books, p.id, USER, always=True)


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #


def test_supplier_key_normalises_names() -> None:
    assert autopilot.supplier_key("Screwfix") == autopilot.supplier_key("SCREWFIX LTD.") == "screwfix"
    assert autopilot.supplier_key("Screwfix Direct Limited") == "screwfix-direct"
    assert autopilot.supplier_key("Sainsbury's") == "sainsburys"
    assert autopilot.supplier_key("B&Q") == "b-and-q"
    assert autopilot.supplier_key("The Range") == "range"


async def test_remember_writes_rule_in_users_folder(fake: FakeStorageProvider, books: Books) -> None:
    await _learn(fake, books)
    (rule,) = json.loads(fake.files[AUTOPILOT_RULES])
    assert AUTOPILOT_RULES == "_System/Rules/rules.json"
    assert {k: rule[k] for k in ("supplier_key", "category", "vat_code", "side", "typical_gross_pence", "vrn", "hits")} == {
        "supplier_key": "screwfix", "category": "Tools & small equipment", "vat_code": "S", "side": "purchase",
        "typical_gross_pence": 3847, "vrn": "GB232456789", "hits": 0,
    }
    assert rule["created_from_proposal_id"] and rule["created_at"] and rule["created_by"] == USER


async def test_remembering_again_replaces_the_rule(fake: FakeStorageProvider, books: Books) -> None:
    await _learn(fake, books)
    (p,) = await _scan(fake, books, b"too-big")  # refused (over 2x), so the user approves it by hand
    await approve(books, p.id, USER, edits={"category": "Materials"}, always=True)
    (rule,) = await autopilot.load_rules(books)
    assert (rule.category, rule.typical_gross_pence, rule.created_from_proposal_id) == ("Materials", 8000, p.id)


async def test_no_rule_for_sales_invoices(fake: FakeStorageProvider, books: Books) -> None:
    DOCS[b"sale"] = _doc("My Business", doc_type="sales_invoice", customer_name="A Client", category_guess="Sales")
    try:
        (p,) = await _scan(fake, books, b"sale")
        await approve(books, p.id, USER, always=True)
    finally:
        del DOCS[b"sale"]
    assert await autopilot.load_rules(books) == []


# --------------------------------------------------------------------------- #
# Auto-approval
# --------------------------------------------------------------------------- #


async def test_matching_clean_proposal_is_auto_approved_with_audit(fake: FakeStorageProvider, books: Books) -> None:
    await _learn(fake, books)
    (p,) = await _scan(fake, books, b"again")

    assert p.status == "posted" and p.decided_by == "autopilot"
    assert p.autopilot is not None and p.autopilot.auto_approve and p.autopilot.supplier_key == "screwfix"
    event = _events(fake)[-1]
    assert event.approved_by == "autopilot" and event.proposal_id == p.id and event.id == p.event_id
    assert sum(ln.debit for ln in event.lines) == sum(ln.credit for ln in event.lines) == 4110
    assert (await books.get_proposal(p.id)).status == "posted"

    (line,) = _jsonl(fake, f"{AUTOPILOT_AUDIT}/")
    assert (line["action"], line["proposal"], line["event"], line["supplier_key"]) == ("approved", p.id, event.id, "screwfix")
    assert (line["gross_pence"], line["typical_gross_pence"]) == (4110, 3847)
    main = [a for a in _jsonl(fake, f"{AUDIT}/2") if a["action"] == "approved"]
    assert main[-1]["actor"] == "autopilot"
    assert (await autopilot.load_rules(books))[0].hits == 1


async def test_exactly_twice_typical_is_still_allowed(fake: FakeStorageProvider, books: Books) -> None:
    await _learn(fake, books)
    (p,) = await _scan(fake, books, b"double")
    assert p.status == "posted" and p.decided_by == "autopilot"


@pytest.mark.parametrize(("name", "reason"), [
    (b"too-big", "more than 2x the usual £38.47"),
    (b"low-confidence", "Check CONFIDENCE warned"),
    (b"other-vrn", "VAT number GB999999999 differs from GB232456789"),
    (b"no-vrn", "VAT number none differs from GB232456789"),
    (b"zero-rated", "VAT treatment Z differs from S"),
])
async def test_refusals_leave_proposal_for_review(fake: FakeStorageProvider, books: Books, name: bytes, reason: str) -> None:
    await _learn(fake, books)
    (p,) = await _scan(fake, books, name)

    assert p.status in ("proposed", "needs_a_look") and p.decided_by is None
    assert p.autopilot is not None and not p.autopilot.auto_approve
    assert any(reason in r for r in p.autopilot.reasons), p.autopilot.reasons
    assert (await books.get_proposal(p.id)).autopilot == p.autopilot  # the reasons are kept for Review
    assert len(_events(fake)) == 1 and _jsonl(fake, f"{AUTOPILOT_AUDIT}/") == []


async def test_failed_check_is_refused(fake: FakeStorageProvider, books: Books) -> None:
    await _learn(fake, books)
    (p,) = await _scan(fake, books, b"first")  # the very same file again: DUPLICATE fails
    assert p.status == "needs_a_look" and not p.autopilot.auto_approve  # type: ignore[union-attr]
    assert any("Check DUPLICATE failed" in r for r in p.autopilot.reasons)  # type: ignore[union-attr]


async def test_switched_off_and_no_rule(fake: FakeStorageProvider, books: Books) -> None:
    await _learn(fake, books)
    off, other = await _scan(fake, books, b"again", b"toolstation", on=False)
    assert off.status == "proposed" and off.autopilot.reasons == ["Autopilot is switched off"]  # type: ignore[union-attr]
    assert other.status == "proposed" and other.autopilot is None
    assert len(_events(fake)) == 1


def test_wrong_side_is_refused() -> None:
    from app.journal import draft_journal
    from app.schemas import Proposal

    doc = _doc(doc_type="sales_invoice", customer_name="A Client")
    p = Proposal(id="ab" * 16, doc_sha256="0" * 64, extracted=doc, checks=[], status="proposed", reasons=[],
                 suggested_filename="x.jpg", journal_draft=draft_journal(doc), model="stub", elapsed_s=0)
    rule = autopilot.AutopilotRule(supplier_key="screwfix", category="Materials", vat_code="S",
                                   typical_gross_pence=3847, vrn="GB232456789", created_from_proposal_id="cd" * 16)
    d = autopilot.evaluate(p, rule)
    assert not d.auto_approve and any("This is a sale" in r for r in d.reasons)


# --------------------------------------------------------------------------- #
# Undo
# --------------------------------------------------------------------------- #


async def test_undo_appends_balancing_reversal_and_reopens(fake: FakeStorageProvider, books: Books) -> None:
    await _learn(fake, books)
    (p,) = await _scan(fake, books, b"again")
    before = dict(fake.files)

    reversal, reopened = await undo(books, p.event_id, USER)  # type: ignore[arg-type]

    assert all(path in fake.files and fake.files[path] == data for path, data in before.items()
               if path.startswith(f"{EVENTS}/"))  # nothing deleted or edited
    assert reversal.kind == "reversal" and reversal.reverses == p.event_id and reversal.approved_by == USER
    assert sum(ln.debit for ln in reversal.lines) == sum(ln.credit for ln in reversal.lines) == 4110
    net: dict[str, int] = defaultdict(int)
    for e in _events(fake):
        if e.id in (p.event_id, reversal.id):
            for ln in e.lines:
                net[ln.account] += ln.debit - ln.credit
    assert set(net.values()) == {0}

    oct_ = compute_vat_return([e for e in _events(fake) if e.id in (p.event_id, reversal.id)], "26A4", date(2026, 10, 1), date(2026, 12, 31))
    assert oct_.vat_reclaimed == 0 and oct_.total_purchases_ex_vat == 0

    assert reopened is not None and reopened.status == "proposed" and reopened.event_id is None
    assert (await books.get_proposal(p.id)).undone_events == [p.event_id]
    assert [a["action"] for a in _jsonl(fake, f"{AUTOPILOT_AUDIT}/")] == ["approved", "undone"]

    with pytest.raises(ProposalStateError):
        await undo(books, p.event_id, USER)  # type: ignore[arg-type]
    with pytest.raises(ApprovalError):
        await undo(books, reversal.id, USER)

    again = await approve(books, p.id, USER)  # the user can decide again; a new event, not a clash
    assert again.status == "posted" and again.event_id not in (p.event_id, reversal.id)
    assert len(_events(fake)) == 4


async def test_undo_unknown_event(books: Books) -> None:
    with pytest.raises(FileNotFoundError):
        await undo(books, "deadbeefdeadbeef", USER)


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


H = {"X-Graph-Token": "tok", "X-User": USER, "X-AI-Mode": "local"}


def test_routes_remember_scan_undo_rules(client: TestClient, fake: FakeStorageProvider) -> None:
    fake.files["00 Inbox/a.jpg"] = b"first"
    (first,) = client.post("/books/scan", headers=H).json()["proposals"]
    r = client.post(f"/books/approve/{first['id']}", headers=H, json={"remember": True})
    assert r.status_code == 200 and r.json()["status"] == "posted"
    (rule,) = client.get("/books/rules", headers=H).json()
    assert rule["supplier_key"] == "screwfix" and rule["typical_gross_pence"] == 3847

    fake.files["00 Inbox/b.jpg"] = b"again"
    (off,) = client.post("/books/scan", headers={**H, "X-Autopilot": "off"}).json()["proposals"]
    assert off["status"] == "proposed" and off["autopilot"]["reasons"] == ["Autopilot is switched off"]

    fake.files["00 Inbox/c.jpg"] = b"double"
    (auto,) = client.post("/books/scan", headers=H).json()["proposals"]
    assert auto["status"] == "posted" and auto["decided_by"] == "autopilot"

    r = client.post(f"/books/undo/{auto['event_id']}", headers=H)
    assert r.status_code == 200 and r.json()["reversal"]["reverses"] == auto["event_id"]
    assert r.json()["proposal"]["status"] == "proposed"
    assert client.post(f"/books/undo/{auto['event_id']}", headers=H).status_code == 409
    assert client.post("/books/undo/deadbeefdeadbeef", headers=H).status_code == 404

    assert client.delete("/books/rules/screwfix", headers=H).status_code == 200
    assert client.get("/books/rules", headers=H).json() == []
    assert json.loads(fake.files["_System/rules.json"]) == []  # the account rule saved with it is gone too
    assert client.delete("/books/rules/screwfix", headers=H).status_code == 404
    assert client.delete("/books/rules/..%2Fx", headers=H).status_code == 404
