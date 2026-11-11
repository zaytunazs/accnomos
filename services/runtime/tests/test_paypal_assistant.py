"""Talk to your accountant about PayPal (app/paypal_assistant.py): PayPal reminders and payment-link messages behind the
approve card, and the PayPal money questions answered by code. The model is stubbed; PayPal is an httpx MockTransport
(direct sandbox mode) that records every request, so the tests check exactly what is sent, and that nothing is sent
before Approve."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any
from urllib.parse import unquote

import httpx
import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeMailSender, FakeStorageProvider
from accnomos_ledger.events import LedgerEvent, Line
from app import actions, invoicing, online_payments, payment_providers
from app import paypal_assistant as pa
from app.actions import IntentModelOutput
from app.ai import ask as ask_ai
from app.ai import remind
from app.ai.config import AiConfig
from app.books import Books, now
from app.books import today as london_today
from app.contacts import CONTACTS, Contact
from app.invoicing import PaymentLink
from app.schemas import AskPeriod, Clarification

CFG = AiConfig(mode="local", base_url="http://ollama.invalid", model="stub-model")
TOKEN = "graph-token-1"
USER = "sam@example.co.uk"
H = {"X-Graph-Token": TOKEN, "X-User": USER, "X-AI-Mode": "local", "X-AI-Model": "stub-model"}
TODAY = london_today()
PERIOD = AskPeriod(start=TODAY.replace(day=1), end=TODAY)
PP_ID = "INV2-AB12-CD34-EF56-GH78"

REQUESTS: list[httpx.Request] = []
REMIND_STATUS = {"code": 204}


def _paypal(request: httpx.Request) -> httpx.Response:
    REQUESTS.append(request)
    path = request.url.path
    if path == "/v1/oauth2/token":
        return httpx.Response(200, json={"access_token": "A21-sandbox", "expires_in": 32400})
    if path == f"/v2/invoicing/invoices/{PP_ID}/remind" and request.method == "POST":
        if REMIND_STATUS["code"] != 204:
            return httpx.Response(REMIND_STATUS["code"], json={"name": "UNPROCESSABLE_ENTITY", "message": "nope"})
        return httpx.Response(204)
    if path == "/v2/invoicing/invoices" and request.method == "POST":
        return httpx.Response(201, json={"id": "INV2-NEW1-0001"})
    if path == "/v2/invoicing/invoices/INV2-NEW1-0001/send":
        return httpx.Response(200, json={})
    if path == "/v2/invoicing/invoices/INV2-NEW1-0001":
        url = "https://www.sandbox.paypal.com/invoice/p/#INV2-NEW1-0001"
        return httpx.Response(200, json={"id": "INV2-NEW1-0001", "detail": {"metadata": {"recipient_view_url": url}}})
    return httpx.Response(404, json={"name": "NOT_FOUND", "message": path})


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    for k in ("ACCNOMOS_TEST_MODE", "PAYMENTS_LIVE", "PAYPAL_BASE", "STRIPE_SECRET_KEY", "STRIPE_DIRECT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PAYPAL_DIRECT", "1")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "sandbox-client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "sandbox-secret")
    REQUESTS.clear()
    REMIND_STATUS["code"] = 204
    payment_providers._paypal_tokens.clear()  # noqa: SLF001
    payment_providers.TRANSPORT = httpx.MockTransport(_paypal)

    async def no_model(*_a: Any, **_k: Any) -> str:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(remind, "_call_model", no_model)  # email reminders: written by code
    yield
    payment_providers.TRANSPORT = None


def contact(name: str, email: str | None, phone: str | None = None) -> dict[str, Any]:
    from app.autopilot import supplier_key

    key = supplier_key(name)
    return Contact(
        id=key.replace("-", "")[:16].ljust(16, "0"),
        kind="customer",
        name=name,
        normalised_key=key,  # type: ignore[arg-type]
        email=email,
        phone=phone,
    ).model_dump(mode="json")


async def _invoice(
    books: Books, name: str, email: str | None, pence: int, due: date, sender: FakeMailSender
) -> invoicing.Invoice:
    draft = invoicing.InvoiceDraft.model_validate(
        {
            "customer": {"name": name, "email": email},
            "issue_date": due - timedelta(days=30),
            "due_date": due,
            "lines": [{"description": "Work", "quantity": "1", "unit_price_pence": pence, "vat_code": "O"}],
        }
    )
    inv = await invoicing.create_invoice(books, draft, USER)
    return await invoicing.send_invoice(books, sender, inv.number, USER, b"%PDF-1.4 test", to=email or "x@y.example")


@pytest.fixture
async def books() -> Books:
    b = Books(FakeStorageProvider())
    await b.write_json(
        CONTACTS,
        [
            contact("JM Trading Ltd", "accounts@jmtrading.example", "07700 900123"),
            contact("Hartley Builders", "pay@hartley.example"),
            contact("Moss & Co", "moss@moss.example"),
        ],
    )
    await b.write_json(invoicing.PROFILE, {"name": "Sam Electrical", "address": "1 High St"})
    await b.write_json(
        online_payments.PROVIDERS,
        {
            "paypal": {
                "merchant_id": online_payments.DIRECT_PAYPAL_MERCHANT,
                "sandbox": True,
                "connected_at": now().isoformat(),
                "connected_by": USER,
            }
        },
    )
    sender = FakeMailSender()
    jm = await _invoice(b, "JM Trading Ltd", "accounts@jmtrading.example", 12_000, TODAY - timedelta(days=26), sender)
    jm.payment_link = PaymentLink(
        provider="paypal",
        url=f"https://www.sandbox.paypal.com/invoice/p/#{PP_ID}",
        amount_pence=12_000,
        test_mode=True,
        provider_ref=PP_ID,
        account_ref=online_payments.DIRECT_PAYPAL_MERCHANT,
        ref="abc123",
        created_by=USER,
    )
    await invoicing.save_invoice(b, jm)
    await _invoice(b, "Hartley Builders", "pay@hartley.example", 45_050, TODAY - timedelta(days=3), sender)
    await _invoice(b, "Moss & Co", "moss@moss.example", 9_900, TODAY + timedelta(days=10), sender)  # not due yet
    return b


def out(kind: str, **kw: Any) -> IntentModelOutput:
    fields = {f: None for f in IntentModelOutput.model_fields if f != "kind"}
    return IntentModelOutput(kind=kind, **{**fields, **kw})  # type: ignore[arg-type]


def stub_model(monkeypatch: pytest.MonkeyPatch, replies: dict[str, str]) -> None:
    """The model's reply per call name (action_intent, payment_message, ask_owed, ask_paypal_fees, ...)."""

    async def fake(messages: list[dict], cfg: AiConfig, schema: dict, name: str) -> str:
        if name not in replies:
            raise httpx.ConnectError(f"no stub for {name}")
        return replies[name]

    monkeypatch.setattr(ask_ai, "call_json_model", fake)


def paypal_calls() -> list[httpx.Request]:
    return [r for r in REQUESTS if r.url.path != "/v1/oauth2/token"]


# --------------------------------------------------------------------------- #
# Reading the instruction
# --------------------------------------------------------------------------- #


def test_code_reroutes_a_paypal_or_everyone_chase():
    q = "send a PayPal reminder to everyone who owes me"
    got = pa.reroute(out("chase_invoice", customer_ref="everyone"), q)
    assert got.kind == "remind_unpaid"
    assert pa.parse(got, q) == pa.RemindIntent(customer_ref=None)  # "everyone" is never a customer name
    one = pa.parse(out("remind_unpaid", customer_ref="JM Trading"), "remind JM Trading through PayPal")
    assert one == pa.RemindIntent(customer_ref="JM Trading")
    plain = pa.reroute(out("chase_invoice", customer_ref="JM"), "chase JM Trading")
    assert plain.kind == "chase_invoice"  # no PayPal, one customer: the email reminder card as before
    link = pa.reroute(out("chase_invoice", customer_ref="JM"), "text JM Trading the payment link")
    assert link.kind == "payment_link_message"
    assert actions.looks_like_action("WhatsApp JM Trading the payment link")


# --------------------------------------------------------------------------- #
# PayPal reminders
# --------------------------------------------------------------------------- #


async def test_everyone_overdue_gets_a_card_and_nothing_is_sent_before_approve(books: Books):
    got = await pa.resolve_remind(books, pa.RemindIntent(), CFG, TODAY)
    assert isinstance(got, actions.Draft), got
    rows = {r["invoice"]: r for r in got.preview["reminders"]}
    assert [r["customer"] for r in got.preview["reminders"]] == ["JM Trading Ltd", "Hartley Builders"]  # most late
    jm = next(r for r in rows.values() if r["customer"] == "JM Trading Ltd")
    hb = next(r for r in rows.values() if r["customer"] == "Hartley Builders")
    assert jm["channel"] == "paypal" and jm["paypal_invoice_id"] == PP_ID and jm["days_overdue"] == 26
    assert hb["channel"] == "email" and hb["days_overdue"] == 3 and hb["invoice"] in hb["body"]
    assert got.preview["total_pence"] == 12_000 + 45_050
    assert "£570.50" in got.summary_md and "26 days overdue" in got.summary_md
    assert any("not due yet" in w for w in got.preview["warnings"])  # Moss & Co left out
    card = actions.new_action(got, TOKEN)
    assert card.tap_only  # it sends: the Approve button only, never a spoken yes
    assert paypal_calls() == []


async def test_approving_sends_paypal_and_email_reminders_once(books: Books):
    got = await pa.resolve_remind(books, pa.RemindIntent(), CFG, TODAY)
    assert isinstance(got, actions.Draft)
    card = actions.new_action(got, TOKEN)
    sender = FakeMailSender()
    ctx = actions.Context(books=books, user=USER, graph_token=TOKEN, mail_sender=lambda: sender)
    voice = actions.Context(books=books, user=USER, graph_token=TOKEN, via="voice", approval_heard="yes")
    with pytest.raises(actions.ActionError) as refused:
        await actions.approve(card, voice)
    assert refused.value.status == 403 and paypal_calls() == []
    done = await actions.approve(card, ctx)
    again = await actions.approve(card, ctx)
    assert again.status == "already_done"
    calls = paypal_calls()
    assert [(c.method, c.url.path) for c in calls] == [("POST", f"/v2/invoicing/invoices/{PP_ID}/remind")]
    assert "PayPal-Auth-Assertion" not in calls[0].headers  # direct mode: the sandbox app's own account
    assert json.loads(calls[0].content) == {"send_to_recipient": True, "send_to_invoicer": False}
    assert len(sender.sent) == 1 and sender.sent[0].to == "pay@hartley.example"
    assert {s["channel"] for s in done.result["sent"]} == {"paypal", "email"} and done.result["failed"] == []
    jm = next(i for i in await invoicing.list_invoices(books, "sent") if i.customer.name == "JM Trading Ltd")
    assert [r.step for r in jm.reminders] == ["paypal"]


async def test_one_customer_and_a_paypal_failure_does_not_stop_the_email(books: Books):
    REMIND_STATUS["code"] = 422
    got = await pa.resolve_remind(books, pa.RemindIntent(), CFG, TODAY)
    assert isinstance(got, actions.Draft)
    sender = FakeMailSender()
    ctx = actions.Context(books=books, user=USER, graph_token=TOKEN, mail_sender=lambda: sender)
    done = await actions.approve(actions.new_action(got, TOKEN), ctx)
    assert [f["invoice"] for f in done.result["failed"]] == [got.preview["reminders"][0]["invoice"]]
    assert "Not sent" in done.summary_md and len(sender.sent) == 1
    one = await pa.resolve_remind(books, pa.RemindIntent(customer_ref="Hartley"), CFG, TODAY)
    assert isinstance(one, actions.Draft) and [r["customer"] for r in one.preview["reminders"]] == ["Hartley Builders"]
    nobody = await pa.resolve_remind(books, pa.RemindIntent(customer_ref="Zed Ltd"), CFG, TODAY)
    assert isinstance(nobody, Clarification) and nobody.field == "customer"


async def test_a_paid_invoice_is_not_reminded(books: Books):
    got = await pa.resolve_remind(books, pa.RemindIntent(customer_ref="JM Trading"), CFG, TODAY)
    assert isinstance(got, actions.Draft)
    jm = await invoicing.get_invoice(books, got.preview["reminders"][0]["invoice"])
    jm.status = "paid"
    await invoicing.save_invoice(books, jm)
    with pytest.raises(actions.ActionError):
        await actions.approve(
            actions.new_action(got, TOKEN), actions.Context(books=books, user=USER, graph_token=TOKEN)
        )
    assert paypal_calls() == []


# --------------------------------------------------------------------------- #
# A payment-link message
# --------------------------------------------------------------------------- #


def _message(text: str) -> str:
    return json.dumps({"message": text})


async def test_the_model_words_it_code_adds_the_link_and_nothing_is_sent(books: Books, monkeypatch):
    jm = next(i for i in await invoicing.list_invoices(books, "sent") if i.customer.name == "JM Trading Ltd")
    good = f"Hi JM, invoice {jm.number} for £120.00 is now overdue. Could you pay it with the link below? Thanks, Sam"
    stub_model(monkeypatch, {"payment_message": _message(good)})
    got = await pa.resolve_message(books, pa.LinkMessageIntent(customer_ref="JM Trading"), CFG, TODAY)
    assert isinstance(got, actions.Draft), got
    assert got.preview["message"] == good and got.preview["phone"] == "447700900123"
    assert got.preview["add_link"] is None and got.preview["link_url"].endswith(PP_ID)
    card = actions.new_action(got, TOKEN)
    assert not card.tap_only  # nothing is sent: the user sends it from their own phone
    done = await actions.approve(card, actions.Context(books=books, user=USER, graph_token=TOKEN))
    msg = done.result["message"]
    assert msg.startswith(good) and msg.endswith(f"#{PP_ID}") and "TEST MODE" in msg
    assert done.result["whatsapp_url"].startswith("https://wa.me/447700900123?text=")
    assert unquote(done.result["whatsapp_url"].split("text=", 1)[1]) == msg
    assert done.result["sms_url"].startswith("sms:+447700900123?&body=")
    assert paypal_calls() == []  # the link was already there; nothing went to PayPal or anyone


@pytest.mark.parametrize(
    ("said", "why"),
    [
        ("Hi, invoice {n} for £120.00 is due. Pay here: https://evil.example/pay", "link"),
        ("Hi, invoice {n} for £120 is overdue, thanks.", "amount"),
        ("Hi, invoice {n} for £120.00 plus £15.00 late fee is overdue.", "figures"),
        ("Hi, your invoice for £120.00 is overdue.", "invoice number"),
    ],
)
async def test_a_message_that_does_not_check_out_is_written_by_code(books: Books, monkeypatch, said: str, why: str):
    jm = next(i for i in await invoicing.list_invoices(books, "sent") if i.customer.name == "JM Trading Ltd")
    stub_model(monkeypatch, {"payment_message": _message(said.format(n=jm.number))})
    got = await pa.resolve_message(books, pa.LinkMessageIntent(invoice_ref=jm.number), CFG, TODAY)
    assert isinstance(got, actions.Draft)
    assert jm.number in got.preview["message"] and "£120.00" in got.preview["message"]
    assert "http" not in got.preview["message"] and why in got.preview["warnings"][0]


async def test_no_link_yet_one_is_made_on_paypal_at_approve(books: Books, monkeypatch):
    stub_model(monkeypatch, {})  # model offline: code writes the words
    got = await pa.resolve_message(books, pa.LinkMessageIntent(customer_ref="Hartley"), CFG, TODAY)
    assert isinstance(got, actions.Draft)
    assert got.preview["add_link"] == "paypal" and got.preview["phone"] is None
    assert paypal_calls() == []  # proposing makes nothing
    done = await actions.approve(
        actions.new_action(got, TOKEN), actions.Context(books=books, user=USER, graph_token=TOKEN)
    )
    assert [c.url.path for c in paypal_calls()][0] == "/v2/invoicing/invoices"
    assert done.result["payment_link"].endswith("INV2-NEW1-0001") and "£450.50" in done.result["message"]
    assert done.result["whatsapp_url"].startswith("https://wa.me/?text=")


def test_phone_numbers_and_share_links():
    assert pa.uk_mobile("07700 900123") == "447700900123"
    assert pa.uk_mobile("+44 7700 900123") == "447700900123"
    assert pa.uk_mobile("0044 7700 900123") == "447700900123"
    assert pa.uk_mobile("n/a") is None and pa.uk_mobile(None) is None
    wa, sms = pa.share_links("Pay £1 & thanks", "447700900123")
    assert wa == "https://wa.me/447700900123?text=Pay%20%C2%A31%20%26%20thanks"
    assert sms == "sms:+447700900123?&body=Pay%20%C2%A31%20%26%20thanks"


# --------------------------------------------------------------------------- #
# Questions answered by code
# --------------------------------------------------------------------------- #


async def _paypal_payment(books: Books, gross: int, fee: int, when: date) -> None:
    await books.post_event(
        LedgerEvent(
            kind="bank",
            date=when,
            lines=[Line(account="1240 PayPal clearing", debit=gross), Line(account="1100 Debtors", credit=gross)],
            approved_by=USER,
            approved_at=now(),
            counterparty="JM Trading Ltd",
        )
    )
    await books.post_event(online_payments.fee_event("paypal", f"PAY-{gross}", "INV-0001", when, fee, USER))


@pytest.mark.parametrize(
    ("q", "kind"),
    [
        ("what did PayPal cost me this quarter?", "fees"),
        ("How much have PayPal fees been?", "fees"),
        ("how much is sitting in PayPal?", "held"),
        ("what's my PayPal balance", "held"),
        ("send a PayPal reminder to everyone who owes me", None),
        ("what did I spend on fuel", None),
    ],
)
def test_question_kinds(q: str, kind: str | None):
    assert pa.question_kind(q) == kind


async def test_paypal_fees_by_code(books: Books, monkeypatch):
    none = await pa.question_answer("what did PayPal cost me this quarter?", books, CFG, PERIOD, TODAY)
    assert none is not None and "No PayPal fees" in none.answer_md and none.model == "code"
    await _paypal_payment(books, 12_000, 438, TODAY)
    await _paypal_payment(books, 8_000, 292, TODAY)
    stub_model(monkeypatch, {"ask_paypal_fees": json.dumps({"answer_md": "PayPal took £9.99.", "confidence": "high"})})
    got = await pa.question_answer("what did PayPal cost me this quarter?", books, CFG, PERIOD, TODAY)
    assert got is not None
    keys = {k.label.split(",")[0]: k.value for k in got.key_numbers}
    assert keys["PayPal fees"] == "£7.30" and keys["Received through PayPal"] == "£200.00"
    assert keys["Fees as % of received"] == "3.7%"
    assert got.model == "code" and "£9.99" not in got.answer_md and "£7.30" in got.answer_md  # invented: code's words
    stub_model(
        monkeypatch,
        {
            "ask_paypal_fees": json.dumps(
                {"answer_md": "PayPal fees came to £7.30, 3.7% of £200.00.", "confidence": "high"}
            )
        },
    )
    ok = await pa.question_answer("what did PayPal cost me this quarter?", books, CFG, PERIOD, TODAY)
    assert ok is not None and ok.model == "stub-model" and ok.answer_md.startswith("PayPal fees came to £7.30")


async def test_money_sitting_in_paypal_is_the_clearing_balance(books: Books, monkeypatch):
    stub_model(monkeypatch, {})
    await _paypal_payment(books, 12_000, 438, TODAY)
    got = await pa.question_answer("how much is sitting in PayPal?", books, CFG, PERIOD, TODAY)
    assert got is not None
    assert got.key_numbers[0].value == "£115.62"  # 120.00 received less the 4.38 fee, not paid out yet
    assert "£115.62" in got.answer_md and "1 unpaid invoice with a PayPal link" in got.answer_md


async def test_who_owes_me_carries_the_paypal_link_status(books: Books, monkeypatch):
    from app import ask_more

    stub_model(monkeypatch, {})
    got = await ask_more.owed_answer("who owes me money?", "debtors", books, CFG, PERIOD, TODAY)
    assert "1 of the unpaid invoices has a PayPal link; 2 have no payment link" in got.answer_md


# --------------------------------------------------------------------------- #
# Through the Ask route, typed and spoken
# --------------------------------------------------------------------------- #


def _client(books: Books):
    from app.main import app
    from app.routes_books import get_books

    async def override():
        yield books

    app.dependency_overrides[get_books] = override
    return app, TestClient(app)


def test_ask_route_reminder_card_and_owed_question(books: Books, monkeypatch):
    stub_model(monkeypatch, {"action_intent": out("remind_unpaid", customer_ref=None).model_dump_json()})
    app, client = _client(books)
    try:
        card = client.post("/books/ask", json={"question": "send a PayPal reminder to everyone who owes me"}, headers=H)
        owed = client.post("/books/ask", json={"question": "who owes me money?"}, headers=H)
        fees = client.post("/books/ask", json={"question": "what did PayPal cost me this quarter?"}, headers=H)
    finally:
        app.dependency_overrides.clear()
    assert card.status_code == 200, card.text
    action = card.json()["proposed_action"]
    assert action["kind"] == "remind_unpaid" and action["tap_only"] and len(action["preview"]["reminders"]) == 2
    assert owed.json()["proposed_action"] is None and "PayPal link" in owed.json()["answer_md"]
    assert "No PayPal fees" in fees.json()["answer_md"]
    assert paypal_calls() == []


def test_spoken_request_takes_the_same_path(books: Books, monkeypatch):
    from app.ai import stt, voice
    from app.schemas import Transcription

    class Heard:
        text = "WhatsApp JM Trading the payment link"
        by = Transcription(provider="muse", label="Muse Voice Transcribe", model="muse-voice-transcribe-1.0")

    async def fake_transcribe(wav, providers, **_):
        return Heard()

    async def fake_wav(data, ctype, name):
        return b"RIFF"

    monkeypatch.setattr(stt, "chain", lambda cfg: ["muse"])
    monkeypatch.setattr(stt, "transcribe", fake_transcribe)
    monkeypatch.setattr(voice, "require_ffmpeg", lambda: None)
    monkeypatch.setattr(voice, "to_wav", fake_wav)
    stub_model(monkeypatch, {"action_intent": out("payment_link_message", customer_ref="JM Trading").model_dump_json()})
    app, client = _client(books)
    try:
        r = client.post("/books/ask/voice", files={"audio": ("q.webm", b"\x1a\x45", "audio/webm")}, headers=H)
        card = r.json()["proposed_action"]
        ok = client.post("/actions/approve", json={"action": card, "via": "voice", "heard": "yes please"}, headers=H)
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    assert card["kind"] == "payment_link_message" and card["transcribed_by"]["provider"] == "muse"
    assert ok.status_code == 200, ok.text
    assert ok.json()["result"]["whatsapp_url"].startswith("https://wa.me/447700900123")
