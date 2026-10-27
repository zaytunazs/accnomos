"""Inbox triage, reply drafts and to-dos against FakeMailProvider + FakeStorageProvider, with the model stubbed."""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from accnomos_connectors import FakeMailProvider, FakeStorageProvider, MailMessage
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai import triage as triage_ai  # noqa: E402
from app.ai.config import AiConfig  # noqa: E402
from app.books import AUDIT, Books  # noqa: E402
from app.todos import TODOS, TodoIn, add_todo, delete_todo, list_todos  # noqa: E402
from app.triage import group_threads, skip_reason, triage_mail  # noqa: E402

USER = "sam@sambuilds.co.uk"
NOW = datetime.now(UTC)
TODAY = NOW.date()
CFG = AiConfig(mode="local", base_url="http://localhost:11434", model="muse-glimmer:30b")


def _msg(
    id_: str,
    sender: str,
    *,
    conv: str | None = None,
    subject: str = "Kitchen quote",
    preview: str = "Hi Sam,",
    hours_ago: float = 2,
    name: str = "",
    read: bool = True,
) -> MailMessage:
    return MailMessage(
        id=id_,
        received_at=NOW - timedelta(hours=hours_ago),
        from_address=sender,
        from_name=name,
        subject=subject,
        conversation_id=conv or id_,
        body_preview=preview,
        is_read=read,
        web_link=f"https://outlook.live.com/owa/?ItemID={id_}",
    )


@pytest.fixture
def fake() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture
def books(fake: FakeStorageProvider) -> Books:
    return Books(fake)


@pytest.fixture
def mail() -> FakeMailProvider:
    return FakeMailProvider()


def _audit(fake: FakeStorageProvider) -> list[dict]:
    lines = [
        ln
        for p, d in fake.files.items()
        if p.startswith(f"{AUDIT}/") and p.endswith(".jsonl")
        for ln in d.decode().splitlines()
    ]
    return [json.loads(ln) for ln in lines]


# ---------------------------------------------------------------------- #
# Filtering and grouping
# ---------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("sender", "subject", "preview", "reason"),
    [
        ("jo@client.co.uk", "Kitchen quote", "Hi Sam, could you", None),
        ("info@smallfirm.co.uk", "Order 12", "Morning", None),  # info@ is a person at a small firm
        ("noreply@screwfix.com", "Your order", "Thanks", "no_reply"),
        ("no-reply@accounts.example.com", "Sign-in", "New sign-in", "no_reply"),
        ("donotreply@bank.co.uk", "Statement", "Ready", "no_reply"),
        ("newsletter@toolstation.com", "Deals", "This week", "newsletter"),
        ("jo@client.co.uk", "Hi", "…click to unsubscribe", "newsletter"),
        ("events@supplier.com", "Join our webinar", "Thursday", "newsletter"),
        ("noreply@tax.service.gov.uk", "You have a new message", "HMRC", None),  # government is never dropped
        ("", "No sender", "", "no_reply"),
    ],
)
def test_skip_reason(sender: str, subject: str, preview: str, reason: str | None) -> None:
    assert skip_reason(_msg("m", sender, subject=subject, preview=preview)) == reason


def test_group_threads_by_conversation_and_drop_own_domain_threads() -> None:
    messages = [
        _msg("a1", "jo@client.co.uk", conv="A", hours_ago=30),
        _msg("a2", USER, conv="A", hours_ago=20),  # the user's own reply (cc'd) stays inside the thread
        _msg("a3", "jo@client.co.uk", conv="A", hours_ago=1),
        _msg("b1", "pat@sambuilds.co.uk", conv="B", hours_ago=3),  # a colleague only: internal
        _msg("c1", "accounts@timber.co.uk", conv="C", hours_ago=5),
        _msg("d1", "noreply@shop.com", conv="D", hours_ago=2),
    ]
    threads, skipped = group_threads(messages, USER, max_threads=20)
    assert [t.conversation_id for t in threads] == ["A", "C"]  # newest activity first
    assert [m.id for m in threads[0].messages] == ["a3", "a2", "a1"]
    assert threads[0].reply_target(USER).id == "a3"
    assert skipped == {"no_reply": 1, "newsletter": 0, "own_domain": 1}
    assert len(group_threads(messages, USER, max_threads=1)[0]) == 1


def test_public_mail_domain_users_do_not_drop_strangers_on_the_same_domain() -> None:
    threads, skipped = group_threads([_msg("x", "someone@gmail.com")], "sam@gmail.com", max_threads=5)
    assert len(threads) == 1 and skipped["own_domain"] == 0


# ---------------------------------------------------------------------- #
# Triage with a stubbed model
# ---------------------------------------------------------------------- #


def _answer(**over) -> str:
    out = {
        "category": "customer",
        "summary": "Jo wants the kitchen quote by Friday\nplease.",
        "needs_reply": True,
        "suggested_reply": "Hi Jo,\n\nThanks, I'll send the quote by [day].\n\nSam Builds",
        "todos": [
            {"text": "Send Jo the kitchen quote", "due": (TODAY + timedelta(days=3)).isoformat()},
            {"text": "send jo the kitchen quote", "due": None},  # duplicate (case-insensitive)
            {"text": "Order worktop", "due": "next Friday"},  # not a date
            {"text": "Renew van insurance", "due": "2031-01-01"},  # outside the window
        ],
    }
    return json.dumps({**out, **over})


async def test_triage_one_model_call_per_thread_with_previews_only(
    books: Books, fake: FakeStorageProvider, mail: FakeMailProvider, monkeypatch
) -> None:
    mail.add(_msg("a1", "jo@client.co.uk", conv="A", name="Jo Bloggs", preview="Hi Sam, " + "x" * 300, read=False))
    mail.add(_msg("c1", "accounts@timber.co.uk", conv="C", subject="Invoice 4471", preview="Please find £1,240.00 due"))
    mail.add(_msg("n1", "newsletter@toolstation.com", subject="Deals"))
    prompts: list[list[dict]] = []

    async def fake_model(messages, cfg):
        prompts.append(messages)
        return (
            _answer()
            if "jo@client" in messages[1]["content"]
            else _answer(
                category="supplier",
                summary="Timber invoice 4471",
                needs_reply=False,
                suggested_reply="ignored",
                todos=[],
            )
        )

    monkeypatch.setattr(triage_ai, "_call_model", fake_model)
    res = await triage_mail(books, mail, CFG, user=USER, business_name="Sam Builds", today=TODAY)

    assert len(prompts) == 2 and res.scanned == 3 and res.skipped["newsletter"] == 1
    facts = (
        json.loads(prompts[0][1]["content"].removeprefix("THREAD:\n"))
        if "jo@" in prompts[0][1]["content"]
        else json.loads(prompts[1][1]["content"].removeprefix("THREAD:\n"))
    )
    assert set(facts) == {"today", "business_name", "subject", "can_reply", "messages"}
    assert all(len(m["preview"]) <= 255 for m in facts["messages"])
    jo = next(t for t in res.threads if t.conversation_id == "A")
    assert jo.category == "customer" and jo.unread and jo.message_id == "a1"
    assert jo.web_link == "https://outlook.live.com/owa/?ItemID=a1"
    assert jo.summary == "Jo wants the kitchen quote by Friday please."  # one line
    assert jo.suggested_reply and jo.suggested_reply.startswith("Hi Jo")
    assert [(t.text, t.due) for t in jo.todos] == [
        ("Send Jo the kitchen quote", TODAY + timedelta(days=3)),
        ("Order worktop", None),
        ("Renew van insurance", None),
    ]
    timber = next(t for t in res.threads if t.conversation_id == "C")
    assert timber.suggested_reply is None and not timber.needs_reply  # no reply when none is needed
    line = _audit(fake)[-1]
    assert line["action"] == "mail_triaged" and line["refs"]["threads"] == 2
    assert "Jo" not in json.dumps(line)  # counts only, no mail content
    assert mail.drafts == [] and not any(c.startswith("create_reply_draft") for c in mail.calls)


async def test_reply_with_invented_figure_or_link_is_dropped(books: Books, mail: FakeMailProvider, monkeypatch) -> None:
    mail.add(_msg("a1", "jo@client.co.uk", conv="A", preview="Can you do the job for £450?"))
    mail.add(_msg("b1", "kim@client.co.uk", conv="B", preview="When can you start?"))
    mail.add(_msg("c1", "lee@client.co.uk", conv="C", preview="Thanks"))

    async def fake_model(messages, cfg):
        content = messages[1]["content"]
        if "jo@" in content:
            return _answer(suggested_reply="Yes, £450 is fine.")  # in the email: kept
        if "kim@" in content:
            return _answer(suggested_reply="I can start Monday for £1,900.")  # invented
        return _answer(suggested_reply="Book here: https://evil.example/pay")

    monkeypatch.setattr(triage_ai, "_call_model", fake_model)
    res = {t.conversation_id: t for t in (await triage_mail(books, mail, CFG, user=USER, today=TODAY)).threads}
    assert res["A"].suggested_reply == "Yes, £450 is fine." and res["A"].fallback_reason is None
    assert res["B"].suggested_reply is None and "1,900" in (res["B"].fallback_reason or "")
    assert res["C"].suggested_reply is None and "link" in (res["C"].fallback_reason or "")
    assert res["B"].summary.startswith("Jo wants")  # the rest of the answer is still used


async def test_no_reply_sender_never_gets_a_reply(books: Books, mail: FakeMailProvider, monkeypatch) -> None:
    mail.add(_msg("h1", "noreply@tax.service.gov.uk", name="HMRC", subject="Your VAT return is due"))
    seen: list[dict] = []

    async def fake_model(messages, cfg):
        seen.append(json.loads(messages[1]["content"].removeprefix("THREAD:\n")))
        return _answer(category="hmrc", suggested_reply="Dear HMRC")

    monkeypatch.setattr(triage_ai, "_call_model", fake_model)
    (t,) = (await triage_mail(books, mail, CFG, user=USER, today=TODAY)).threads
    assert seen[0]["can_reply"] is False
    assert t.category == "hmrc" and not t.needs_reply and t.suggested_reply is None


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (httpx.ConnectError("down"), "could not be reached"),
        (None, "not in the expected format"),
    ],
)
async def test_model_trouble_keeps_the_thread_with_a_code_summary(
    books: Books, mail: FakeMailProvider, monkeypatch, failure, reason
) -> None:
    mail.add(_msg("a1", "jo@client.co.uk", name="Jo Bloggs", subject="Kitchen quote"))

    async def fake_model(messages, cfg):
        if failure:
            raise failure
        return '{"category": "boss"}'

    monkeypatch.setattr(triage_ai, "_call_model", fake_model)
    (t,) = (await triage_mail(books, mail, CFG, user=USER, today=TODAY)).threads
    assert t.summary == "Jo Bloggs: Kitchen quote" and t.category == "other" and t.todos == []
    assert reason in (t.fallback_reason or "")


async def test_without_ai_no_model_is_called(books: Books, mail: FakeMailProvider, monkeypatch) -> None:
    mail.add(_msg("a1", "jo@client.co.uk"))

    async def forbidden(messages, cfg):
        raise AssertionError("no model without an AI config")

    monkeypatch.setattr(triage_ai, "_call_model", forbidden)
    res = await triage_mail(books, mail, None, user=USER, today=TODAY)
    assert res.model is None and "No AI" in (res.threads[0].fallback_reason or "")


# ---------------------------------------------------------------------- #
# To-dos
# ---------------------------------------------------------------------- #


async def test_todos_crud(books: Books, fake: FakeStorageProvider) -> None:
    assert await list_todos(books) == []
    src = {"message_id": "a1", "subject": "Kitchen quote", "web_link": "https://outlook.live.com/owa/?ItemID=a1"}
    later, created = await add_todo(
        books, TodoIn(text="  Send   quote ", due=TODAY + timedelta(days=5), source=src), USER
    )
    assert created and later.text == "Send quote"
    again, created = await add_todo(books, TodoIn(text="send quote", source=src), USER)
    assert not created and again.id == later.id  # same text from the same email: one entry
    sooner, _ = await add_todo(books, TodoIn(text="Ring the accountant", due=TODAY), USER)
    undated, _ = await add_todo(books, TodoIn(text="Tidy the van"), USER)
    assert [t.id for t in await list_todos(books)] == [sooner.id, later.id, undated.id]  # by due date, undated last
    assert TODOS in fake.files and json.loads(fake.files[TODOS])[0]["created_by"] == USER

    await delete_todo(books, later.id, USER)
    assert [t.id for t in await list_todos(books)] == [sooner.id, undated.id]
    with pytest.raises(KeyError):
        await delete_todo(books, later.id, USER)
    assert [ln["action"] for ln in _audit(fake)] == ["todo_added", "todo_added", "todo_added", "todo_deleted"]


def test_todo_source_link_must_be_https() -> None:
    with pytest.raises(ValueError):
        TodoIn(text="x", source={"web_link": "javascript:alert(1)"})


# ---------------------------------------------------------------------- #
# Routes
# ---------------------------------------------------------------------- #


@pytest.fixture
def client(fake: FakeStorageProvider, mail: FakeMailProvider):
    from app.main import app
    from app.routes_books import get_books
    from app.routes_mail import get_mail

    async def books_override():
        yield Books(fake)

    async def mail_override():
        yield mail

    app.dependency_overrides[get_books] = books_override
    app.dependency_overrides[get_mail] = mail_override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


H = {"X-Graph-Token": "t", "X-User": USER}


def test_draft_reply_creates_a_draft_and_audits(
    client: TestClient, fake: FakeStorageProvider, mail: FakeMailProvider
) -> None:
    mail.add(_msg("AAMk-a1=", "jo@client.co.uk"))
    r = client.post(
        "/mail/draft-reply", json={"message_id": "AAMk-a1=", "body": "  Hi Jo, Thursday works.  "}, headers=H
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"draft_id": "draft-1", "web_link": "https://outlook.office.com/mail/drafts/id/draft-1"}
    assert mail.drafts == [{"id": "draft-1", "reply_to": "AAMk-a1=", "body": "Hi Jo, Thursday works."}]
    line = _audit(fake)[-1]
    assert line["actor"] == f"user:{USER}" and line["action"] == "mail_draft_created"
    assert line["refs"] == {"reply_to": "AAMk-a1=", "draft": "draft-1", "chars": 22}


def test_draft_reply_validation(client: TestClient, mail: FakeMailProvider) -> None:
    mail.add(_msg("a1", "jo@client.co.uk"))
    assert client.post("/mail/draft-reply", json={"message_id": "gone", "body": "Hi"}, headers=H).status_code == 404
    assert client.post("/mail/draft-reply", json={"message_id": "a1", "body": "   "}, headers=H).status_code == 422
    assert client.post("/mail/draft-reply", json={"message_id": "../x", "body": "Hi"}, headers=H).status_code == 422
    assert (
        client.post("/mail/draft-reply", json={"message_id": "a1", "body": "Hi", "send": True}, headers=H).status_code
        == 422
    )
    no_user = client.post("/mail/draft-reply", json={"message_id": "a1", "body": "Hi"}, headers={"X-Graph-Token": "t"})
    assert no_user.status_code == 400
    assert mail.drafts == []


def test_triage_route(client: TestClient, mail: FakeMailProvider) -> None:
    mail.add(_msg("a1", "jo@client.co.uk"))
    r = client.post("/mail/triage", json={"since_days": 7, "max_threads": 20}, headers=H)  # no AI headers
    assert r.status_code == 200, r.text
    (t,) = r.json()["threads"]
    assert t["web_link"] and t["message_id"] == "a1" and t["fallback_reason"]
    assert client.post("/mail/triage", json={"since_days": 0}, headers=H).status_code == 422
    assert client.post("/mail/triage", json={"since_days": 7, "full_bodies": True}, headers=H).status_code == 422


def test_todos_routes(client: TestClient) -> None:
    r = client.post("/todos", json={"text": "Send quote", "due": date.today().isoformat()}, headers=H)
    assert r.status_code == 201
    assert client.post("/todos", json={"text": "Send quote"}, headers=H).status_code == 200
    assert [t["text"] for t in client.get("/todos", headers=H).json()] == ["Send quote"]
    assert client.post("/todos", json={"text": ""}, headers=H).status_code == 422
    assert client.delete(f"/todos/{r.json()['id']}", headers=H).status_code == 200
    assert client.delete(f"/todos/{r.json()['id']}", headers=H).status_code == 404
    assert client.get("/todos", headers=H).json() == []


def test_triage_route_calls_a_model_only_when_the_app_sends_one(
    client: TestClient, mail: FakeMailProvider, monkeypatch
) -> None:
    mail.add(_msg("a1", "jo@client.co.uk"))
    calls: list[str] = []

    async def fake_model(messages, cfg):
        calls.append(cfg.model)
        return _answer()

    monkeypatch.setattr(triage_ai, "_call_model", fake_model)
    assert client.post("/mail/triage", headers=H).json()["model"] is None  # no X-AI-Mode: never a server default
    assert calls == []
    ai = {"X-AI-Mode": CFG.mode, "X-AI-Base-Url": CFG.base_url, "X-AI-Model": CFG.model}
    r = client.post("/mail/triage", headers={**H, **ai}).json()
    assert calls == [CFG.model] and r["model"] == CFG.model and r["threads"][0]["category"] == "customer"


def test_draft_reply_without_mail_readwrite_is_401_and_not_audited(
    client: TestClient, fake: FakeStorageProvider, mail: FakeMailProvider, monkeypatch
) -> None:
    from accnomos_connectors import GraphError

    async def forbidden(message_id, body_text):
        raise GraphError(403, "ErrorAccessDenied")

    monkeypatch.setattr(mail, "create_reply_draft", forbidden)
    r = client.post("/mail/draft-reply", json={"message_id": "a1", "body": "Hi"}, headers=H)
    assert r.status_code == 401  # the app asks for consent again
    assert not any(ln["action"] == "mail_draft_created" for ln in _audit(fake))


def test_todos_file_that_is_not_a_list_is_409_and_left_alone(client: TestClient, fake: FakeStorageProvider) -> None:
    fake.files[TODOS] = b'{"hand": "edited"}'
    assert client.get("/todos", headers=H).status_code == 409
    assert client.post("/todos", json={"text": "Send quote"}, headers=H).status_code == 409
    assert fake.files[TODOS] == b'{"hand": "edited"}'


def test_routes_need_a_graph_token() -> None:
    from app.main import app

    c = TestClient(app)
    assert c.post("/mail/triage").status_code == 401
    assert c.post("/mail/draft-reply", json={"message_id": "a", "body": "b"}).status_code == 401
    assert c.get("/todos").status_code == 401
