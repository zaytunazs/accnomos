"""Support (app/support): help articles and retrieval, the support assistant's cited answers and ticket card, and the
tickets API with the in-memory registry: users see only their own tickets, admin routes are admin only, internal notes
never reach the user, and a card makes one ticket however often it is approved."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app.billing import registry as R
from app.billing import service as S
from app.books import Books
from app.support import help as H
from app.support.store import support_store

ROOT = Path(__file__).resolve().parents[3]
USER = "sam@example.co.uk"
OTHER = "pat@example.co.uk"
BOSS = "boss@accnomos.example"
H_USER = {"X-Graph-Token": "tok-sam", "X-User": USER}
H_OTHER = {"X-Graph-Token": "tok-pat", "X-User": OTHER}
H_ADMIN = {"X-Graph-Token": "tok-boss", "X-User": BOSS}


@pytest.fixture
def reg(monkeypatch: pytest.MonkeyPatch):
    r = R.MemoryRegistry()
    R.install(r)
    S.forget()
    monkeypatch.setenv("ADMIN_EMAILS", BOSS)
    yield r
    R.install(None)
    S.forget()


@pytest.fixture
def client(reg):
    from app.main import app

    return TestClient(app)


def _ticket(c: TestClient, headers: dict[str, str], subject: str = "Upload button does nothing", **extra) -> dict:
    body = {"subject": subject, "category": "bug", "body": "I press Add a receipt and nothing opens.", **extra}
    r = c.post("/support/tickets", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["ticket"]


# --------------------------------------------------------------------------- #
# Articles and retrieval
# --------------------------------------------------------------------------- #


def test_runtime_copy_of_the_articles_matches_the_website_source() -> None:
    src = ROOT / "apps/web/src/content/help/articles.json"
    if not src.exists():
        pytest.skip("apps/web is not in this checkout")
    assert json.loads(src.read_text()) == json.loads(H.ARTICLES_PATH.read_text()), (
        "run python tools/sync_help_articles.py"
    )


def test_articles_have_stable_unique_ids_and_steps() -> None:
    ids = [a.id for a in H.articles()]
    assert len(ids) == len(set(ids))
    for a in H.articles():
        assert a.steps, a.id
        assert all(r in ids for r in a.related), a.id
    for needed in ("sign-up-connect-storage", "upload-receipts", "review-approve", "bank-feeds",
                   "invoices-paypal-links", "sync-paypal", "paypal-disputes", "bill-pay-paypal", "vat-return",
                   "month-end", "voice-assistant", "android-app", "contact-support", "paypal-help"):  # fmt: skip
        assert needed in ids


@pytest.mark.parametrize(
    ("question", "article"),
    [
        ("how do I sync paypal", "sync-paypal"),
        ("how do I upload a zip of receipts", "upload-receipts"),
        ("my bank feed keeps asking me to reconnect", "bank-feeds"),
        ("how do I submit my VAT return to HMRC", "vat-return"),
        ("how do I respond to a paypal dispute", "paypal-disputes"),
        ("how can I pay a supplier with paypal", "bill-pay-paypal"),
        ("how do I close the month", "month-end"),
        ("how do I add a paypal link to an invoice", "invoices-paypal-links"),
        ("The PayPal sync is not working, I get an error", "sync-paypal"),
        ("I want to contact support", "contact-support"),
    ],
)
def test_retrieval_finds_the_article(question: str, article: str) -> None:
    assert H.search(question)[0].article.id == article


def test_answer_quotes_the_article_and_never_invents_steps() -> None:
    found = H.answer("how do I sync paypal")
    assert found.article is not None and found.article.id == "sync-paypal"
    assert "(/help/sync-paypal)" in found.answer_md
    for line in found.answer_md.splitlines():
        if line[:2].rstrip(".").isdigit():  # a numbered step: its words are the article's own
            body = line.split(".** ", 1)[1]
            assert body in found.article.text()


def test_no_match_says_so_and_offers_a_ticket() -> None:
    found = H.answer("how do I fly a kite on the moon")
    assert found.article is None and found.offer_ticket
    assert "won't guess" in found.answer_md


def test_books_questions_stay_with_the_books_assistant() -> None:
    for q in ("how much did I spend on fuel", "how can I see my profit for October", "my profit looks wrong",
              "send a £100 invoice to JM Trading", "what is my VAT bill this quarter"):  # fmt: skip
        assert not H.route_from_ask(q), q
    for q in ("how do I connect my bank feed", "the paypal sync is not working", "I want to raise a ticket"):
        assert H.route_from_ask(q), q


def test_public_article_endpoints(client: TestClient) -> None:
    rows = client.get("/support/articles").json()
    assert any(r["id"] == "paypal-help" and r["path"] == "/help/paypal-help" for r in rows)
    one = client.get("/support/articles/vat-return").json()
    assert one["steps"][0]["title"] and one["troubleshooting"]
    assert client.get("/support/articles/nope").status_code == 404


# --------------------------------------------------------------------------- #
# The assistant and its ticket card
# --------------------------------------------------------------------------- #


def test_assist_cites_the_article(client: TestClient) -> None:
    r = client.post("/support/assist", json={"question": "How do I close the month?"}, headers=H_USER)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["citations"][0]["id"] == "month-end" and out["citations"][0]["path"] == "/help/month-end"
    assert out["ticket_card"] is None  # solved by the article: no ticket offered


def test_assist_needs_a_sign_in(client: TestClient) -> None:
    assert client.post("/support/assist", json={"question": "how do I sign up"}).status_code == 401


def test_bug_report_gets_a_ticket_card_and_approving_it_twice_makes_one_ticket(client: TestClient, reg) -> None:
    q = "The upload button is not working, I get an error for my £1,250.00 receipt"
    out = client.post("/support/assist", json={"question": q, "page": "/review"}, headers=H_USER).json()
    card = out["ticket_card"]
    assert card["kind"] == "create_support_ticket" and card["preview"]["category"] == "bug"
    assert "1,250" not in json.dumps(card["preview"])  # amounts are masked unless the user ticks financial details
    body = {
        "action": card,
        "attach_errors": True,
        "recent_errors": [{"method": "POST", "path": "/books/scan", "status": 500, "message": "Failed for £9.99"}],
    }
    first = client.post("/support/tickets/from-card", json=body, headers=H_USER)
    assert first.status_code == 201, first.text
    again = client.post("/support/tickets/from-card", json=body, headers=H_USER).json()
    assert first.json()["created"] is True and again["created"] is False
    assert again["ticket"]["id"] == first.json()["ticket"]["id"]
    t = first.json()["ticket"]
    assert t["source"] == "assistant" and t["page"] == "/review"
    assert t["context"]["recent_errors"][0]["message"] == "Failed for £•••"
    assert "paypal" not in t["context"] and "conversation" not in t["context"]


def test_a_changed_card_is_refused(client: TestClient) -> None:
    out = client.post("/support/assist", json={"question": "report a bug: sync crashes"}, headers=H_USER).json()
    card = out["ticket_card"]
    card["preview"]["subject"] = "Something else"
    r = client.post("/support/tickets/from-card", json={"action": card}, headers=H_USER)
    assert r.status_code == 403


def test_a_card_from_another_sign_in_is_refused(client: TestClient) -> None:
    card = client.post("/support/assist", json={"question": "contact support"}, headers=H_USER).json()["ticket_card"]
    assert client.post("/support/tickets/from-card", json={"action": card}, headers=H_OTHER).status_code == 403


def test_financial_details_only_when_ticked(client: TestClient) -> None:
    t = _ticket(client, H_USER, "Wrong total £45.00", include_financial=False)
    assert "£•••" in t["subject"]
    convo = [{"role": "user", "text": "why is box 1 £250.00"}]
    t2 = _ticket(client, H_USER, "Box 1 £250.00", include_financial=True, conversation=convo)
    assert t2["subject"] == "Box 1 £250.00" and t2["context"]["conversation"] == convo


def test_books_assistant_answers_how_to_with_a_citation_and_a_ticket_card(client: TestClient) -> None:
    from app.main import app
    from app.routes_books import get_books

    books = Books(FakeStorageProvider())

    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    try:
        r = client.post("/books/ask", json={"question": "how do I connect my bank feed"}, headers=H_USER)
        assert r.status_code == 200, r.text
        a = r.json()
        assert a["citations"][0] == "help:bank-feeds" and a["model"] == "code"
        assert a["suggested_actions"][0] == {"label": "Open the guide: Connect a bank feed and reconcile",
                                             "kind": "open_help", "arg": "bank-feeds"}  # fmt: skip
        bug = client.post("/books/ask", json={"question": "I want to raise a ticket"}, headers=H_USER).json()
        card = bug["proposed_action"]
        assert card["kind"] == "create_support_ticket" and card["tap_only"] is False
        done = client.post("/actions/approve", json={"action": card}, headers=H_USER)
        assert done.status_code == 200, done.text
        assert "support ticket" in done.json()["summary_md"]
        mine = client.get("/support/tickets", headers=H_USER).json()
        assert mine["total"] == 1 and mine["items"][0]["context"]["consent"] == {
            "errors": False, "paypal": False, "financial": False}  # fmt: skip
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Tickets: ownership and admin
# --------------------------------------------------------------------------- #


def test_users_see_only_their_own_tickets(client: TestClient) -> None:
    mine = _ticket(client, H_USER)
    theirs = _ticket(client, H_OTHER, "PayPal sync fails")
    listed = client.get("/support/tickets", headers=H_USER).json()
    assert [t["id"] for t in listed["items"]] == [mine["id"]]
    assert client.get(f"/support/tickets/{theirs['id']}", headers=H_USER).status_code == 404
    r = client.post(f"/support/tickets/{theirs['id']}/messages", json={"body": "hi"}, headers=H_USER)
    assert r.status_code == 404
    assert "account_id" not in listed["items"][0] or listed["items"][0]["account_id"] is None


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/admin/support/tickets"),
        ("GET", "/admin/support/tickets/x"),
        ("POST", "/admin/support/tickets/x/messages"),
        ("PATCH", "/admin/support/tickets/x"),
    ],
)
def test_admin_routes_are_admin_only(client: TestClient, method: str, path: str) -> None:
    body = {"body": "x"} if method == "POST" else {"status": "solved"} if method == "PATCH" else None
    assert client.request(method, path, json=body, headers=H_USER).status_code == 403
    assert client.request(method, path, json=body).status_code == 401


def test_admin_queue_reply_note_and_status(client: TestClient, reg) -> None:
    t = _ticket(client, H_USER)
    q = client.get("/admin/support/tickets?status=open", headers=H_ADMIN).json()
    assert q["total"] == 1 and q["counts"] == {"open": 1, "pending": 0, "solved": 0}
    assert q["items"][0]["email"] == USER and q["items"][0]["account_id"]

    note = client.post(f"/admin/support/tickets/{t['id']}/messages",
                       json={"body": "Looks like the picker", "internal": True}, headers=H_ADMIN)  # fmt: skip
    assert note.status_code == 201 and note.json()["emailed"] is False
    reply = client.post(f"/admin/support/tickets/{t['id']}/messages",
                        json={"body": "Fixed now, try again", "email_user": False}, headers=H_ADMIN).json()  # fmt: skip
    assert reply["status"] == "pending" and reply["last_reply_by"] == "admin"
    assert "Not emailed" in reply["email_note"]

    user_view = client.get(f"/support/tickets/{t['id']}", headers=H_USER).json()
    bodies = [m["body"] for m in user_view["messages"]]
    assert "Looks like the picker" not in bodies and "Fixed now, try again" in bodies
    assert all(m["author_email"] is None for m in user_view["messages"])

    solved = client.patch(f"/admin/support/tickets/{t['id']}", json={"status": "solved"}, headers=H_ADMIN).json()
    assert solved["status"] == "solved" and solved["solved_at"]
    back = client.post(f"/support/tickets/{t['id']}/messages", json={"body": "Still broken"}, headers=H_USER).json()
    assert back["status"] == "open" and back["solved_at"] is None
    assert [a["action"] for a in reg.audit] == ["support_note", "support_reply", "support_status"]


def test_admin_reply_is_emailed_from_the_admins_mailbox(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.support import routes

    sent: list = []

    class Sender:
        async def send(self, mail) -> None:
            sent.append(mail)

    monkeypatch.setattr(routes, "is_test_mode", lambda: False)
    monkeypatch.setattr("app.accounts.mail_sender", lambda token, request: Sender())
    t = _ticket(client, H_USER)
    out = client.post(f"/admin/support/tickets/{t['id']}/messages", json={"body": "On it"}, headers=H_ADMIN).json()
    assert out["emailed"] is True and out["email_note"] is None
    assert sent[0].to == USER and f"#{t['number']}" in sent[0].subject and "On it" in sent[0].body_text


def test_admin_reply_stays_in_app_when_email_fails(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.support import routes

    class Broken:
        async def send(self, mail) -> None:
            raise RuntimeError("Graph said no")

    monkeypatch.setattr(routes, "is_test_mode", lambda: False)
    monkeypatch.setattr("app.accounts.mail_sender", lambda token, request: Broken())
    t = _ticket(client, H_USER)
    out = client.post(f"/admin/support/tickets/{t['id']}/messages", json={"body": "On it"}, headers=H_ADMIN).json()
    assert out["emailed"] is False and "in the app" in out["email_note"]
    assert out["messages"][-1]["body"] == "On it"


def test_support_off_without_a_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import app

    R.install(None)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("ACCNOMOS_TEST_MODE", raising=False)
    assert support_store() is None
    c = TestClient(app)
    out = c.post("/support/assist", json={"question": "contact support"}, headers=H_USER).json()
    assert out["ticket_card"] is None and "not set up" in out["ticket_note"]


def test_paypal_help_without_books_is_honest(client: TestClient) -> None:
    from app.main import app
    from app.routes_books import get_books

    async def no_books():
        from fastapi import HTTPException

        raise HTTPException(401, "no storage")
        yield  # pragma: no cover

    app.dependency_overrides[get_books] = no_books
    try:
        out = client.get("/support/paypal", headers=H_USER).json()
    finally:
        app.dependency_overrides.clear()
    # the panel calls get_books directly, not as a dependency: a real request without storage gives available False
    assert "Resolution Centre" in json.dumps(out["links"]) and "no API" in out["no_case_api"]


@pytest.mark.asyncio
async def test_paypal_help_reads_connection_and_last_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.requests import Request

    from app import online_payments as op
    from app import routes_books
    from app.support import routes

    books = Books(FakeStorageProvider())

    async def fake_books(request):
        yield books

    async def status(_books):
        return [op.ProviderStatus(provider="paypal", label="PayPal", available=True, test_mode=True, connected=True,
                                  account="MERCHANT1234", can_match=True)]  # fmt: skip

    async def disputes(_books, sample=False):
        from app.paypal_disputes import DisputeList

        return DisputeList(connected=True, disputes=[], problem="PayPal could not be asked about disputes: 503")

    monkeypatch.setattr(routes_books, "get_books", fake_books)
    monkeypatch.setattr(op, "status", status)
    monkeypatch.setattr("app.paypal_disputes.list_disputes", disputes)
    req = Request({"type": "http", "headers": [], "method": "GET", "path": "/support/paypal"})
    out = await routes.paypal_help_for(req)
    assert out.available and out.connected and out.account == "••••1234"
    assert out.problem and "503" in out.problem
