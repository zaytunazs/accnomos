"""Outlook intake (F10) against FakeMailProvider + FakeStorageProvider: filtering, scoring, dedupe, dry run, size limits."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from accnomos_connectors import FakeMailProvider, FakeStorageProvider, MailAttachment, MailMessage
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.books import AUDIT, DOCS, RULES, Books  # noqa: E402
from app.intake import SEEN, SEEN_MAX, scan_mail, score, skip_reason, target_name  # noqa: E402

USER = "sam@sambuilds.co.uk"
NOW = datetime.now(UTC)
PDF = b"%PDF-1.7 screwfix invoice " + b"x" * 20_000
JPG = b"\xff\xd8 toolstation receipt " + b"y" * 30_000


def _msg(id_: str, subject: str = "Your invoice", sender: str = "orders@screwfix.com", days_ago: float = 1, name: str = "Screwfix") -> MailMessage:
    return MailMessage(id=id_, received_at=NOW - timedelta(days=days_ago), from_address=sender, from_name=name, subject=subject)


def _att(id_: str, name: str, data: bytes = PDF, ctype: str = "application/pdf", inline: bool = False, size: int | None = None) -> tuple[MailAttachment, bytes]:
    return MailAttachment(id=id_, name=name, content_type=ctype, size=len(data) if size is None else size, is_inline=inline), data


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
def books(fake: FakeStorageProvider) -> Books:
    return Books(fake)


@pytest.fixture
def mail() -> FakeMailProvider:
    return FakeMailProvider()


def _inbox(fake: FakeStorageProvider) -> list[str]:
    return sorted(p.split("/", 1)[1] for p in fake.files if p.startswith("00 Inbox/"))


# ---------------------------------------------------------------------- #
# Filtering and scoring
# ---------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("name", "ctype", "size", "inline", "reason"),
    [
        ("invoice.pdf", "application/pdf", 50_000, False, None),
        ("receipt.HEIC", "application/octet-stream", 900_000, False, None),  # by extension
        ("IMG_2041.jpg", "image/jpeg", 2_000_000, False, None),
        ("logo.png", "image/png", 50_000, True, "inline"),
        ("invoice.pdf", "application/pdf", 50_000, True, None),  # Apple Mail: inline PDFs are real attachments
        ("image001.png", "image/png", 12_000, False, "signature"),
        ("image001.png", "image/png", 400_000, False, None),  # big enough to be a photo
        ("invite.ics", "text/calendar", 20_000, False, "calendar"),
        ("terms.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 50_000, False, "type"),
        ("tiny.pdf", "application/pdf", 9_000, False, "too_small"),
        ("huge.pdf", "application/pdf", 16 * 1024 * 1024, False, "too_large"),
    ],
)
def test_skip_reason(name: str, ctype: str, size: int, inline: bool, reason: str | None) -> None:
    assert skip_reason(MailAttachment(id="a", name=name, content_type=ctype, size=size, is_inline=inline)) == reason


def test_score() -> None:
    pdf = MailAttachment(id="a", name="INV-20931.pdf", content_type="application/pdf", size=40_000)
    photo = MailAttachment(id="b", name="IMG_2041.jpg", content_type="image/jpeg", size=40_000)
    plain = MailAttachment(id="c", name="document.pdf", content_type="application/pdf", size=40_000)
    assert score(_msg("1", "Your Screwfix order"), pdf, USER) == 0.9  # external + subject + filename + pdf
    assert score(_msg("1", "Photos from the weekend", "friend@gmail.com"), photo, USER) == 0.15
    assert score(_msg("1", "Newsletter", "news@shop.com"), plain, USER) == 0.3  # an external PDF alone is not enough
    # Own domain earns nothing for "external"; forwarding yourself a receipt still passes on keywords.
    assert score(_msg("1", "Fwd: receipt", "sam@sambuilds.co.uk"), photo, USER) == 0.3
    assert score(_msg("1", "Fwd: receipt", "sam@sambuilds.co.uk"), pdf, USER) == 0.75
    # On a public mail domain, sharing the domain does not make the sender "you".
    assert score(_msg("1", "Receipt", "shop@gmail.com"), photo, "me@gmail.com") == 0.45
    # 'border' is not an 'order'; UK 'remittance advice' counts.
    assert score(_msg("1", "Border collie pics", "a@b.com"), photo, USER) == 0.15
    assert score(_msg("1", "Remittance advice", "a@b.com"), photo, USER) == 0.45


def test_score_known_supplier_from_rules() -> None:
    from app.books import Rule, RuleMatch

    rules = [Rule(match=RuleMatch(supplier_regex="screwfix"), account="Tools")]
    pdf = MailAttachment(id="a", name="document.pdf", content_type="application/pdf", size=40_000)
    assert score(_msg("1", "Hello"), pdf, USER) == 0.3
    assert score(_msg("1", "Hello"), pdf, USER, rules) == 0.55


def test_target_name_is_safe() -> None:
    m = _msg("1", sender="billing@mail.example.com")
    m.received_at = datetime(2026, 10, 21, 23, 30, tzinfo=UTC)
    a = MailAttachment(id="a", name='Invoice: #12/34 "Oct"?.PDF', size=1)
    assert target_name(m, a) == "2026-10-21_mail.example.com_Invoice_ _12_34 _Oct.pdf"
    assert target_name(m, MailAttachment(id="a", name="x" * 300 + ".pdf", size=1)).endswith("x.pdf")


# ---------------------------------------------------------------------- #
# The scan
# ---------------------------------------------------------------------- #


async def test_scan_saves_candidates_and_writes_audit_trail(books: Books, fake: FakeStorageProvider, mail: FakeMailProvider) -> None:
    mail.add(_msg("m1", "Your Screwfix invoice"), _att("a1", "Invoice 123.pdf"), _att("sig", "image001.png", b"s" * 5000, "image/png"))
    mail.add(_msg("m2", "Receipt for your purchase", "noreply@toolstation.com", 2, "Toolstation"), _att("a2", "receipt.jpg", JPG, "image/jpeg"))
    mail.add(_msg("m3", "Lunch on Friday?", "friend@gmail.com"), _att("a3", "menu.jpg", JPG + b"z", "image/jpeg"))  # score 0.15
    mail.add(_msg("old", "Invoice", days_ago=30), _att("a4", "old-invoice.pdf", PDF + b"old"))  # outside 14 days

    r = await scan_mail(books, mail, since_days=14, user=USER)

    day1 = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
    day2 = (NOW - timedelta(days=2)).strftime("%Y-%m-%d")
    assert r.scanned == 3 and r.candidates == 2 and r.skipped_duplicates == 0 and r.errors == []
    assert r.saved == [f"{day1}_screwfix.com_Invoice 123.pdf", f"{day2}_toolstation.com_receipt.jpg"]
    assert _inbox(fake) == sorted(r.saved)
    assert fake.files[f"00 Inbox/{r.saved[0]}"] == PDF

    seen = json.loads(fake.files[SEEN])
    assert [(s["message_id"], s["attachment_id"]) for s in seen] == [("m1", "a1"), ("m2", "a2")]
    assert seen[0]["sha256"] == hashlib.sha256(PDF).hexdigest() and seen[0]["saved_as"] == f"00 Inbox/{r.saved[0]}"
    log_files = [p for p in fake.files if p.startswith("_System/Intake/log/")]
    assert len(log_files) == 1
    lines = [json.loads(x) for x in fake.files[log_files[0]].decode().splitlines()]
    assert [ln["subject"] for ln in lines] == ["Your Screwfix invoice", "Receipt for your purchase"]
    assert all(ln["score"] >= 0.4 for ln in lines)
    audit = [json.loads(x) for p, d in fake.files.items() if p.startswith(AUDIT) for x in d.decode().splitlines()]
    assert audit[-1]["action"] == "mail_scanned" and audit[-1]["refs"]["saved"] == 2


async def test_rescan_is_deduplicated_without_downloading(books: Books, fake: FakeStorageProvider, mail: FakeMailProvider) -> None:
    mail.add(_msg("m1"), _att("a1", "invoice.pdf"))
    assert len((await scan_mail(books, mail, user=USER)).saved) == 1
    mail.calls.clear()

    r = await scan_mail(books, mail, user=USER)

    assert r.saved == [] and r.skipped_duplicates == 1 and r.candidates == 1
    assert not any(c.startswith("download:") for c in mail.calls)
    assert len(_inbox(fake)) == 1 and len(json.loads(fake.files[SEEN])) == 1


async def test_same_bytes_from_another_message_or_already_in_books_are_duplicates(books: Books, fake: FakeStorageProvider, mail: FakeMailProvider) -> None:
    fake.files["00 Inbox/IMG_2041.jpg"] = JPG  # uploaded by hand earlier
    filed = PDF + b"filed"
    fake.files[f"{DOCS}/{hashlib.sha256(filed).hexdigest()}.json"] = b"{}"  # processed and filed already
    mail.add(_msg("m1", "Receipt"), _att("a1", "receipt.jpg", JPG, "image/jpeg"))
    mail.add(_msg("m2", "Invoice"), _att("a2", "invoice.pdf", filed))
    mail.add(_msg("m3", "Invoice"), _att("a3", "invoice.pdf"), _att("a3b", "invoice-copy.pdf"))  # same bytes twice

    r = await scan_mail(books, mail, user=USER)

    assert r.skipped_duplicates == 3 and len(r.saved) == 1
    assert len(_inbox(fake)) == 2


async def test_dry_run_writes_nothing(books: Books, fake: FakeStorageProvider, mail: FakeMailProvider) -> None:
    mail.add(_msg("m1"), _att("a1", "invoice.pdf"))
    before = dict(fake.files)

    r = await scan_mail(books, mail, dry_run=True, user=USER)

    assert r.dry_run and len(r.saved) == 1 and r.items[0].score >= 0.4
    assert fake.files == before
    # A real scan afterwards still imports it.
    assert len((await scan_mail(books, mail, user=USER)).saved) == 1


async def test_name_clash_gets_a_suffix(books: Books, fake: FakeStorageProvider, mail: FakeMailProvider) -> None:
    mail.add(_msg("m1"), _att("a1", "invoice.pdf"))
    mail.add(_msg("m2"), _att("a2", "invoice.pdf", PDF + b"other month"))

    r = await scan_mail(books, mail, user=USER)

    stem = r.saved[0].removesuffix(".pdf")
    assert sorted(r.saved) == sorted([f"{stem}.pdf", f"{stem} (2).pdf"])


async def test_large_attachment_is_saved_and_oversize_is_ignored(books: Books, fake: FakeStorageProvider, mail: FakeMailProvider) -> None:
    big = b"%PDF" + b"b" * (5 * 1024 * 1024)
    mail.add(_msg("m1"), _att("a1", "invoice.pdf", big))
    mail.add(_msg("m2"), _att("a2", "statement.pdf", b"%PDF" + b"h" * (15 * 1024 * 1024 + 1)))
    mail.add(_msg("m3"), _att("a3", "invoice-small.pdf", b"%PDF tiny"))

    r = await scan_mail(books, mail, user=USER)

    assert len(r.saved) == 1 and fake.files[f"00 Inbox/{r.saved[0]}"] == big
    assert "download:m2/a2" not in mail.calls and "download:m3/a3" not in mail.calls


async def test_seen_list_is_capped(books: Books, fake: FakeStorageProvider, mail: FakeMailProvider) -> None:
    fake.files[SEEN] = json.dumps([{"sha256": f"{i:064x}", "message_id": f"x{i}", "attachment_id": "a", "saved_as": "", "at": ""} for i in range(SEEN_MAX)]).encode()
    mail.add(_msg("m1"), _att("a1", "invoice.pdf"))

    await scan_mail(books, mail, user=USER)

    seen = json.loads(fake.files[SEEN])
    assert len(seen) == SEEN_MAX and seen[-1]["message_id"] == "m1" and seen[0]["message_id"] == "x1"


async def test_one_failing_attachment_does_not_stop_the_scan(books: Books, fake: FakeStorageProvider, mail: FakeMailProvider) -> None:
    mail.add(_msg("m1"), _att("a1", "invoice.pdf"))
    mail.add(_msg("m2"), _att("a2", "invoice2.pdf", PDF + b"2"))
    original = mail.download_attachment

    async def flaky(message_id: str, attachment_id: str) -> bytes:
        if message_id == "m1":
            raise RuntimeError("Graph 500")
        return await original(message_id, attachment_id)

    mail.download_attachment = flaky  # type: ignore[method-assign]
    r = await scan_mail(books, mail, user=USER)

    assert len(r.saved) == 1 and len(r.errors) == 1 and r.errors[0]["attachment"] == "invoice.pdf"


# ---------------------------------------------------------------------- #
# Route
# ---------------------------------------------------------------------- #


def test_route(fake: FakeStorageProvider, mail: FakeMailProvider) -> None:
    from app.main import app
    from app.routes_books import get_books
    from app.routes_mail import get_mail

    mail.add(_msg("m1"), _att("a1", "invoice.pdf"))

    async def books_override():
        yield Books(fake)

    async def mail_override():
        yield mail

    app.dependency_overrides[get_books] = books_override
    app.dependency_overrides[get_mail] = mail_override
    try:
        client = TestClient(app)
        dry = client.post("/mail/scan", json={"since_days": 7, "dry_run": True}, headers={"X-Graph-Token": "t", "X-User": USER})
        real = client.post("/mail/scan", headers={"X-Graph-Token": "t", "X-User": USER})
        bad = client.post("/mail/scan", json={"since_days": 0}, headers={"X-Graph-Token": "t"})
    finally:
        app.dependency_overrides.clear()
    assert dry.status_code == 200 and dry.json()["dry_run"] is True and len(dry.json()["saved"]) == 1
    assert real.status_code == 200 and real.json()["saved"] == dry.json()["saved"]
    assert set(real.json()) >= {"scanned", "candidates", "saved", "skipped_duplicates", "dry_run", "errors"}
    assert bad.status_code == 422
    assert RULES not in fake.files  # intake never writes rules


def test_route_needs_a_graph_token() -> None:
    from app.main import app

    assert TestClient(app).post("/mail/scan").status_code == 401
