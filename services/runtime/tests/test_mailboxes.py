"""Linked mailboxes (app/mailboxes.py) and Outlook intake across them: the stored list, folder and sender filters,
one copy of a file that reached two mailboxes, the mailbox recorded on the proposal and in the audit trail, and no
token ever written or logged."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeMailProvider, FakeStorageProvider, MailAttachment, MailMessage
from app import mailboxes as mb
from app import pipeline
from app.ai.config import AiConfig
from app.books import AUDIT, Books
from app.inbox import scan_inbox
from app.intake import INTAKE_LOG, SEEN, scan_mail
from app.schemas import ExtractedDoc

USER = "sam@sambuilds.co.uk"
LINKED = "receipts@sambuilds-mail.example"
SHARED = "accounts@sambuilds.co.uk"
TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJub25lIn0.mailbox-token-for-tests.c2lnbmF0dXJl"
NOW = datetime.now(UTC)
SCREWFIX = b"%PDF-1.7 screwfix invoice " + b"x" * 20_000
TOOLSTATION = b"%PDF-1.7 toolstation invoice " + b"y" * 20_000
CFG = AiConfig(mode="local", base_url="http://ollama.invalid", model="stub")


def _msg(id_: str, sender: str = "orders@screwfix.com", subject: str = "Your invoice", days_ago: float = 1):
    return MailMessage(
        id=id_, received_at=NOW - timedelta(days=days_ago), from_address=sender, from_name="", subject=subject
    )


def _att(id_: str, data: bytes, name: str = "invoice.pdf") -> tuple[MailAttachment, bytes]:
    return MailAttachment(id=id_, name=name, content_type="application/pdf", size=len(data)), data


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
def books(fake: FakeStorageProvider) -> Books:
    return Books(fake)


def _audit(fake: FakeStorageProvider) -> list[dict]:
    lines: list[dict] = []
    for path, data in sorted(fake.files.items()):
        if path.startswith(f"{AUDIT}/") and path.endswith(".jsonl"):
            lines += [json.loads(x) for x in data.decode().splitlines()]
    return lines


def _inbox(fake: FakeStorageProvider) -> list[str]:
    return sorted(p for p in fake.files if p.startswith("00 Inbox/"))


# ---------------------------------------------------------------------- #
# Filters and validation
# ---------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("sender", "allow", "deny", "kept"),
    [
        ("orders@screwfix.com", [], [], True),
        ("orders@screwfix.com", ["screwfix.com"], [], True),
        ("orders@mail.screwfix.com", ["screwfix.com"], [], True),  # a domain covers its subdomains
        ("orders@notscrewfix.com", ["screwfix.com"], [], False),
        ("orders@screwfix.com", ["billing@screwfix.com"], [], False),  # an address is exact
        ("orders@screwfix.com", [], ["screwfix.com"], False),
        ("Orders@Screwfix.com", ["screwfix.com"], ["orders@screwfix.com"], False),  # deny wins
    ],
)
def test_sender_allowed(sender: str, allow: list[str], deny: list[str], kept: bool) -> None:
    assert mb.sender_allowed(sender, allow, deny) is kept


def test_normalising_input() -> None:
    assert mb.normalise_senders([" @Screwfix.com ", "screwfix.com", "", "BILLS@uber.com"]) == [
        "screwfix.com",
        "bills@uber.com",
    ]
    assert mb.normalise_folder("Inbox") == "inbox" and mb.normalise_folder("Receipts 2026") == "Receipts 2026"
    for bad in ("../inbox", "a/b", "x" * 101, ""):
        with pytest.raises(mb.MailboxError):
            mb.normalise_folder(bad)
    for bad in ("not an address", "a@b", "x@y..z"):
        with pytest.raises(mb.MailboxError):
            mb.normalise_address(bad)
    with pytest.raises(mb.MailboxError):
        mb.normalise_senders(["drop table;"])


# ---------------------------------------------------------------------- #
# The stored list
# ---------------------------------------------------------------------- #


async def test_add_update_remove_and_what_is_stored(books: Books, fake: FakeStorageProvider) -> None:
    assert [m.id for m in await mb.list_mailboxes(books, USER)] == [mb.PRIMARY_ID]  # always listed, never stored
    assert mb.MAILBOXES not in fake.files

    box = await mb.add_mailbox(books, address=" Receipts@SamBuilds-Mail.example ", kind="microsoft", user=USER)
    assert box.address == LINKED and box.folder == "all"
    shared = await mb.add_mailbox(books, address=SHARED, kind="shared", user=USER, folder="Inbox")
    with pytest.raises(mb.MailboxError) as dup:
        await mb.add_mailbox(books, address=LINKED, kind="microsoft", user=USER)
    assert dup.value.status == 409
    with pytest.raises(mb.MailboxError):
        await mb.add_mailbox(books, address=USER, kind="microsoft", user=USER)  # already read as the primary

    await mb.update_mailbox(books, box.id, user=USER, folder="Receipts", allow_senders=["screwfix.com"])
    await mb.update_mailbox(books, mb.PRIMARY_ID, user=USER, deny_senders=["@newsletters.example"])
    listed = await mb.list_mailboxes(books, USER)
    assert [(m.id, m.kind) for m in listed] == [
        (mb.PRIMARY_ID, "primary"),
        (box.id, "microsoft"),
        (shared.id, "shared"),
    ]
    assert listed[0].deny_senders == ["newsletters.example"] and listed[1].folder == "Receipts"

    with pytest.raises(mb.MailboxError):
        await mb.remove_mailbox(books, mb.PRIMARY_ID, user=USER)
    await mb.remove_mailbox(books, shared.id, user=USER)
    with pytest.raises(mb.MailboxError) as gone:
        await mb.remove_mailbox(books, shared.id, user=USER)
    assert gone.value.status == 404

    stored = json.loads(fake.files[mb.MAILBOXES])
    keys = {k for m in stored["mailboxes"] for k in m}
    assert not any("token" in k or "secret" in k for k in keys)
    actions = [a["action"] for a in _audit(fake)]
    assert actions.count("mailbox_added") == 2 and "mailbox_updated" in actions and "mailbox_removed" in actions


# ---------------------------------------------------------------------- #
# Scanning several mailboxes
# ---------------------------------------------------------------------- #


async def test_two_mailboxes_copy_a_shared_attachment_once_and_record_where_each_came_from(
    books: Books, fake: FakeStorageProvider
) -> None:
    primary, linked = FakeMailProvider(), FakeMailProvider()
    primary.add(_msg("p1"), _att("a1", SCREWFIX))
    linked.add(_msg("l1"), _att("a1", SCREWFIX, "copy-of-invoice.pdf"))  # the same bytes reached both mailboxes
    linked.add(_msg("l2", "sales@toolstation.com", "Invoice INV-2207"), _att("a2", TOOLSTATION))
    box = await mb.add_mailbox(books, address=LINKED, kind="microsoft", user=USER)

    first = await scan_mail(books, primary, user=USER)
    second = await scan_mail(books, linked, user=USER, mailbox=box)

    assert first.mailbox == USER and len(first.saved) == 1
    assert second.mailbox_id == box.id and second.mailbox == LINKED
    assert len(second.saved) == 1 and second.skipped_duplicates == 1
    assert [i.mailbox for i in second.items] == [LINKED]
    assert len(_inbox(fake)) == 2

    seen = json.loads(fake.files[SEEN])
    assert sorted((s["mailbox"], s["mailbox_id"]) for s in seen) == sorted([(USER, "primary"), (LINKED, box.id)])
    log = [json.loads(x) for p, d in fake.files.items() if p.startswith(INTAKE_LOG) for x in d.decode().splitlines()]
    assert sorted(line["mailbox"] for line in log) == sorted([USER, LINKED])
    scans = [a["refs"] for a in _audit(fake) if a["action"] == "mail_scanned"]
    assert [(s["mailbox"], s["saved"], s["skipped_duplicates"]) for s in scans] == [(USER, 1, 0), (LINKED, 1, 1)]

    # The linked mailbox's last check is kept with it. A rescan does not download what it copied; the duplicate is
    # downloaded and hashed again (as for one mailbox: only copied files go in the seen-list) and still not copied.
    (stored,) = [m for m in await mb.list_mailboxes(books, USER) if m.id == box.id]
    assert stored.last_scan_saved == 1 and stored.last_scan_at is not None and stored.last_scan_error is None
    linked.calls.clear()
    again = await scan_mail(books, linked, user=USER, mailbox=box)
    assert again.saved == [] and again.skipped_duplicates == 2
    assert [c for c in linked.calls if c.startswith("download:")] == ["download:l1/a1"]


async def test_message_ids_are_per_mailbox(books: Books, fake: FakeStorageProvider) -> None:
    """Two mailboxes may use the same message and attachment ids: the second is not mistaken for the first."""
    primary, linked = FakeMailProvider(), FakeMailProvider()
    primary.add(_msg("m1"), _att("a1", SCREWFIX))
    linked.add(_msg("m1", "sales@toolstation.com"), _att("a1", TOOLSTATION))
    box = await mb.add_mailbox(books, address=LINKED, kind="microsoft", user=USER)
    await scan_mail(books, primary, user=USER)
    assert len((await scan_mail(books, linked, user=USER, mailbox=box)).saved) == 1


async def test_folder_and_sender_lists_apply(books: Books, fake: FakeStorageProvider) -> None:
    linked = FakeMailProvider()
    linked.add(_msg("in-1"), _att("a1", SCREWFIX), folder="inbox")
    linked.add(_msg("ar-1", "sales@toolstation.com"), _att("a2", TOOLSTATION), folder="archive")
    linked.add(
        _msg("ar-2", "bills@spam.example", "Invoice"), _att("a3", b"%PDF-1.7 spam " + b"z" * 20_000), folder="archive"
    )
    box = await mb.add_mailbox(
        books, address=LINKED, kind="microsoft", user=USER, folder="archive", deny_senders=["spam.example"]
    )
    result = await scan_mail(books, linked, user=USER, mailbox=box, dry_run=True)
    assert [i.message_id for i in result.items] == ["ar-1"]
    assert result.filtered_senders == 1
    assert "list_messages:archive" in linked.calls

    allow_only = box.model_copy(update={"folder": "all", "deny_senders": [], "allow_senders": ["screwfix.com"]})
    result = await scan_mail(books, linked, user=USER, mailbox=allow_only, dry_run=True)
    assert [i.message_id for i in result.items] == ["in-1"] and result.filtered_senders == 2


async def test_proposal_and_audit_say_which_mailbox(
    books: Books, fake: FakeStorageProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_extract(data: bytes, mime: str, cfg: AiConfig) -> tuple[ExtractedDoc, dict[str, str]]:
        raise AssertionError("not reached: these PDFs are refused before any model call")

    monkeypatch.setattr(pipeline, "extract_document", fake_extract)
    primary, linked = FakeMailProvider(), FakeMailProvider()
    primary.add(_msg("p1"), _att("a1", SCREWFIX))
    linked.add(_msg("l1", "sales@toolstation.com"), _att("a2", TOOLSTATION))
    box = await mb.add_mailbox(books, address=SHARED, kind="shared", user=USER)
    await scan_mail(books, primary, user=USER)
    await scan_mail(books, linked, user=USER, mailbox=box)
    fake.files["00 Inbox/dropped-by-hand.pdf"] = b"%PDF-1.7 by hand"

    proposals = await scan_inbox(books, CFG)
    by_name = {p.source_name: p.source_mailbox for p in proposals}
    assert sorted(v for v in by_name.values() if v) == sorted([USER, SHARED])
    assert by_name["dropped-by-hand.pdf"] is None
    proposed = {a["refs"]["proposal"]: a["refs"].get("mailbox") for a in _audit(fake) if a["action"] == "proposed"}
    assert {p.id: p.source_mailbox for p in proposals} == proposed


# ---------------------------------------------------------------------- #
# Routes: one mailbox per request, its token in X-Mailbox-Token, never kept
# ---------------------------------------------------------------------- #


@pytest.fixture
def client(fake: FakeStorageProvider):
    from app.main import app
    from app.routes_books import get_books
    from app.routes_mail import get_mail, get_mail_factory

    primary, linked = FakeMailProvider(), FakeMailProvider()
    primary.add(_msg("p1"), _att("a1", SCREWFIX))
    linked.add(_msg("l1"), _att("a1", SCREWFIX))
    linked.add(_msg("l2", "sales@toolstation.com"), _att("a2", TOOLSTATION))
    opened: list[tuple[str, str, str]] = []

    async def books_override():
        yield Books(fake)

    async def mail_override():
        yield primary

    async def factory_override():
        def make(token: str, box: mb.Mailbox) -> FakeMailProvider:
            opened.append((token, box.address, box.kind))
            return linked

        yield make

    app.dependency_overrides[get_books] = books_override
    app.dependency_overrides[get_mail] = mail_override
    app.dependency_overrides[get_mail_factory] = factory_override
    try:
        yield TestClient(app), opened
    finally:
        app.dependency_overrides.clear()


HEADERS = {"X-Graph-Token": "storage-token-abcdef", "X-User": USER, "X-Account-Kind": "work"}


def test_routes_link_scan_each_mailbox_and_never_keep_a_token(
    client, fake: FakeStorageProvider, caplog: pytest.LogCaptureFixture
) -> None:
    c, opened = client
    caplog.set_level(logging.DEBUG)
    assert [m["id"] for m in c.get("/mail/mailboxes", headers=HEADERS).json()["mailboxes"]] == ["primary"]
    added = c.post("/mail/mailboxes", json={"address": SHARED, "kind": "shared"}, headers=HEADERS)
    assert added.status_code == 201, added.text
    box = added.json()

    no_token = c.post("/mail/scan", json={"mailbox": box["id"]}, headers=HEADERS)
    assert no_token.status_code == 401 and "X-Mailbox-Token" in no_token.json()["detail"]

    mine = c.post("/mail/scan", json={}, headers=HEADERS)
    theirs = c.post("/mail/scan", json={"mailbox": box["id"]}, headers={**HEADERS, "X-Mailbox-Token": TOKEN})
    assert mine.status_code == 200 and len(mine.json()["saved"]) == 1
    assert theirs.status_code == 200, theirs.text
    assert theirs.json()["mailbox"] == SHARED and len(theirs.json()["saved"]) == 1
    assert theirs.json()["skipped_duplicates"] == 1
    assert opened == [(TOKEN, SHARED, "shared")]  # the shared mailbox is read with the token sent for it

    listed = c.get("/mail/mailboxes", headers=HEADERS).json()["mailboxes"]
    assert [m["last_scan_saved"] for m in listed if m["id"] == box["id"]] == [1]
    unknown = c.post("/mail/scan", json={"mailbox": "abc123"}, headers={**HEADERS, "X-Mailbox-Token": TOKEN})
    assert unknown.status_code == 404

    stored = b"".join(fake.files.values())
    assert TOKEN.encode() not in stored and b"storage-token-abcdef" not in stored
    assert b"mailbox-token-for-tests" not in stored
    assert TOKEN not in caplog.text


def test_routes_validate_and_need_a_user(client) -> None:
    c, _ = client
    no_user = {k: v for k, v in HEADERS.items() if k != "X-User"}
    assert c.post("/mail/mailboxes", json={"address": LINKED, "kind": "microsoft"}, headers=no_user).status_code == 400
    personal = {**HEADERS, "X-Account-Kind": "personal"}
    shared = c.post("/mail/mailboxes", json={"address": SHARED, "kind": "shared"}, headers=personal)
    assert shared.status_code == 400 and "work or school" in shared.json()["detail"]
    assert c.post("/mail/mailboxes", json={"address": "nope", "kind": "microsoft"}, headers=HEADERS).status_code == 400
    assert c.post("/mail/mailboxes", json={"address": LINKED, "kind": "primary"}, headers=HEADERS).status_code == 422
    assert (
        c.post("/mail/mailboxes", json={"address": LINKED, "kind": "microsoft", "token": "x"}, headers=HEADERS)
    ).status_code == 422  # nowhere to put a token
    box = c.post("/mail/mailboxes", json={"address": LINKED, "kind": "microsoft"}, headers=HEADERS).json()
    patched = c.patch(
        f"/mail/mailboxes/{box['id']}", json={"folder": "Archive", "allow_senders": ["screwfix.com"]}, headers=HEADERS
    )
    assert patched.status_code == 200 and patched.json()["folder"] == "archive"
    assert c.patch(f"/mail/mailboxes/{box['id']}", json={"folder": "../x"}, headers=HEADERS).status_code == 400
    assert c.delete("/mail/mailboxes/primary", headers=HEADERS).status_code == 400
    assert c.delete(f"/mail/mailboxes/{box['id']}", headers=HEADERS).status_code == 200
    assert c.delete("/mail/mailboxes/BAD!", headers=HEADERS).status_code in (404, 422)


def test_mailbox_token_is_scrubbed_from_logs() -> None:
    from app import security

    token = security._request_secrets.set((TOKEN,))
    try:
        assert TOKEN not in security.scrub(f"failed with {TOKEN}")
    finally:
        security._request_secrets.reset(token)
    assert "abc.def" not in security.scrub("X-Mailbox-Token: abcdefgh.abc.def")
    assert "x-mailbox-token" in security.SECRET_HEADERS


# ---------------------------------------------------------------------- #
# Graph: /users/{address} for a shared mailbox, folders by name
# ---------------------------------------------------------------------- #


async def test_graph_reads_a_shared_mailbox_and_finds_a_folder_by_name() -> None:
    import httpx

    from accnomos_connectors.msgraph import GraphMailProvider

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode().split("?")[0]  # as sent: the folder id stays percent-encoded
        seen.append(f"{request.method} {path} {request.url.params.get('$filter', '')}")
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if request.url.path.endswith("/mailFolders"):
            hits = (
                [{"id": "AQMk=folder/1", "displayName": "Receipts"}]
                if "'Receipts'" in request.url.params.get("$filter", "")
                else []
            )
            return httpx.Response(200, json={"value": hits})
        return httpx.Response(200, json={"value": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    graph = GraphMailProvider(TOKEN, mailbox=SHARED, client=client)
    since = NOW - timedelta(days=14)
    await graph.list_messages(since, folder="Receipts")
    await graph.list_messages(since, folder="Receipts")  # the folder id is looked up once
    await graph.list_without_attachments(since)
    await graph.list_messages(since, folder="archive")
    await graph.list_messages(since)
    await graph.list_attachments("m-1")
    with pytest.raises(FileNotFoundError):
        await graph.list_messages(since, folder="It's not there")
    me = GraphMailProvider(TOKEN, client=client)
    await me.list_messages(since)
    await client.aclose()

    base = "/v1.0/users/accounts@sambuilds.co.uk"
    paths = [s.split(" ")[1] for s in seen]
    assert paths[:7] == [
        f"{base}/mailFolders",
        f"{base}/mailFolders/AQMk%3Dfolder%2F1/messages",
        f"{base}/mailFolders/AQMk%3Dfolder%2F1/messages",
        f"{base}/mailFolders/inbox/messages",
        f"{base}/mailFolders/archive/messages",
        f"{base}/messages",
        f"{base}/messages/m-1/attachments",
    ]
    assert "displayName eq 'It''s not there'" in seen[7]
    assert paths[-1] == "/v1.0/me/messages"
