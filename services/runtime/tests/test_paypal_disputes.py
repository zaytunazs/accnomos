"""PayPal disputes (app/paypal_disputes.py) and the business details on PayPal invoices, against the PayPal fake in
app/online_fakes.py, which answers with the shapes in PayPal's Disputes v1 and Invoicing v2 schemas (pages cited in
app/payment_providers.py, read 11 Nov 2026). Nothing here talks to PayPal."""

from __future__ import annotations

import hashlib
import importlib
import json
from email.parser import BytesParser
from email.policy import default

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from accnomos_connectors import FakeStorageProvider
from app import paypal_disputes as pd
from app.ai.config import AiConfig, ai_config_from_request
from app.books import Books
from app.invoicing import PROFILE, InvoiceProfile, get_invoice
from app.online_fakes import FAKES

ot = importlib.import_module("test_online_payments")  # sibling module: pytest puts tests/ on the path
DRAFT, H, PROFILE_JSON, TOTAL = ot.DRAFT, ot.H, ot.PROFILE_JSON, ot.TOTAL
_audit, _calls, _connect_paypal, _ok, _sent_invoice = ot._audit, ot._calls, ot._connect_paypal, ot._ok, ot._sent_invoice
_fakes, books, client, fake = ot._fakes, ot.books, ot.client, ot.fake  # its fixtures, the autouse one included

UNREACHABLE = AiConfig(mode="local", base_url="http://127.0.0.1:9/none", model="x")
BASE = "/payments/online/paypal/disputes"


@pytest.fixture(autouse=True)
def _no_ai():
    from app.main import app

    app.dependency_overrides[ai_config_from_request] = lambda: UNREACHABLE
    yield
    app.dependency_overrides.pop(ai_config_from_request, None)


def _paid(client: TestClient) -> tuple[str, dict, str]:
    """An invoice paid through its PayPal link and approved into the books: (number, link, transaction id)."""
    _connect_paypal(client)
    number = _sent_invoice(client)
    link = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "paypal"}, headers=H))["invoice"][
        "payment_link"
    ]
    tid = FAKES.pay_paypal(link["provider_ref"])
    _ok(client.post(f"/invoices/{number}/payment-link/approve", json={"payment_id": tid, "confirm": True}, headers=H))
    return number, link, tid


def _parts(req) -> dict[str, tuple[str, bytes]]:
    raw = b"Content-Type: " + req.headers["Content-Type"].encode() + b"\r\n\r\n" + req.content
    msg = BytesParser(policy=default).parsebytes(raw)
    out = {}
    for p in msg.iter_parts():
        name = str(dict(p.get_params(header="content-disposition") or [])["name"])
        out[name] = (p.get_content_type(), p.get_payload(decode=True))
    return out


# --------------------------------------------------------------------------- #
# Finding and matching
# --------------------------------------------------------------------------- #


def test_a_dispute_on_a_paypal_payment_is_matched_to_its_invoice(client: TestClient) -> None:
    number, link, tid = _paid(client)
    did = FAKES.open_dispute(link["provider_ref"])
    out = _ok(client.get(BASE, headers=H))
    assert out["connected"] and out["problem"] is None
    row = out["disputes"][0]
    assert (row["dispute_id"], row["invoice"], row["transaction_id"]) == (did, number, tid)
    assert row["amount_pence"] == TOTAL and row["can_send_evidence"] and row["proposal"] is None
    assert row["reason_text"] == "says the goods or service were not received"
    listing = _calls("/v1/customer/disputes")[0]
    assert listing.url.params["page_size"] == "50" and "PayPal-Auth-Assertion" in listing.headers


def test_a_dispute_on_a_payment_we_do_not_know_is_listed_but_never_answered(client: TestClient) -> None:
    _number, link, _tid = _paid(client)
    did = FAKES.open_dispute(link["provider_ref"])
    FAKES.disputes[did]["disputed_transactions"][0].update(seller_transaction_id="SOMEONEELSE", invoice_number="X-1")
    row = _ok(client.get(BASE, headers=H))["disputes"][0]
    assert row["invoice"] is None and not row["can_send_evidence"]
    r = client.post(f"{BASE}/{did}/evidence", headers=H)
    assert r.status_code == 400 and "not on a payment Accnomos knows about" in r.json()["detail"]


def test_not_connected_lists_nothing(client: TestClient) -> None:
    assert _ok(client.get(BASE, headers=H)) == {"connected": False, "disputes": [], "problem": None}


# --------------------------------------------------------------------------- #
# Evidence: built from the books, previewed, sent only on a yes
# --------------------------------------------------------------------------- #


def test_build_then_send_only_with_a_yes(client: TestClient, fake: FakeStorageProvider) -> None:
    number, link, tid = _paid(client)
    did = FAKES.open_dispute(link["provider_ref"])
    rec = _ok(client.post(f"{BASE}/{did}/evidence", headers=H))
    assert rec["status"] == "proposed" and rec["invoice"] == number and rec["fallback_reason"]  # AI unreachable
    facts = rec["facts"]
    assert facts["emailed"]["to"] == "accounts@harbourcafe.example" and facts["invoice_total"] == "£372.00"
    assert facts["payment"] == {"date": facts["payment"]["date"], "amount": "£372.00", "paypal_transaction": tid}
    assert number in rec["notes"] and "£372.00" in rec["notes"] and len(rec["notes"]) <= pd.NOTES_MAX
    pdf = fake.files[rec["pdf_path"]]
    assert pdf.startswith(b"%PDF") and hashlib.sha256(pdf).hexdigest() == rec["pdf_sha256"]
    doc = pdfium.PdfDocument(pdf)
    assert len(doc) >= 2  # the summary, then the invoice exactly as it was emailed
    first = doc[0].get_textpage().get_text_range()
    assert f"evidence for invoice {number}" in first and tid in first
    preview = client.get(f"{BASE}/{did}/evidence.pdf", headers=H)
    assert preview.status_code == 200 and preview.content == pdf
    assert not _calls(f"/v1/customer/disputes/{did}/provide-evidence")  # building sends nothing

    r = client.post(f"{BASE}/{did}/evidence/send", json={}, headers=H)
    assert r.status_code == 400 and not _calls(f"/v1/customer/disputes/{did}/provide-evidence")
    sent = _ok(client.post(f"{BASE}/{did}/evidence/send", json={"confirm": True}, headers=H))
    assert sent["status"] == "sent" and sent["sent_by"] == "sam@sambuilds.co.uk" and not sent["demo"]
    call = _calls(f"/v1/customer/disputes/{did}/provide-evidence")[0]
    assert call.headers["Content-Type"].startswith("multipart/form-data")
    parts = _parts(call)
    assert parts["input"][0] == "application/json"
    assert json.loads(parts["input"][1]) == {"evidences": [{"evidence_type": "OTHER", "notes": rec["notes"]}]}
    assert parts["evidence-file"] == ("application/pdf", pdf)
    assert FAKES.disputes[did]["status"] == "UNDER_REVIEW"
    actions = [a["action"] for a in _audit(fake)]
    assert "dispute_evidence_built" in actions and "dispute_evidence_sent" in actions
    again = client.post(f"{BASE}/{did}/evidence/send", json={"confirm": True}, headers=H)
    assert again.status_code == 400 and "already sent" in again.json()["detail"]
    row = _ok(client.get(BASE, headers=H))["disputes"][0]
    assert row["proposal"]["status"] == "sent" and not row["can_send_evidence"]


def test_a_pdf_changed_after_the_preview_is_not_sent(client: TestClient, fake: FakeStorageProvider) -> None:
    _number, link, _tid = _paid(client)
    did = FAKES.open_dispute(link["provider_ref"])
    rec = _ok(client.post(f"{BASE}/{did}/evidence", headers=H))
    fake.files[rec["pdf_path"]] = b"%PDF-1.3 something else"
    r = client.post(f"{BASE}/{did}/evidence/send", json={"confirm": True}, headers=H)
    assert r.status_code == 400 and "changed" in r.json()["detail"]
    assert not _calls(f"/v1/customer/disputes/{did}/provide-evidence")


def test_no_evidence_once_paypal_stops_waiting(client: TestClient) -> None:
    _number, link, _tid = _paid(client)
    did = FAKES.open_dispute(link["provider_ref"])
    _ok(client.post(f"{BASE}/{did}/evidence", headers=H))
    FAKES.disputes[did]["status"] = "UNDER_REVIEW"
    r = client.post(f"{BASE}/{did}/evidence/send", json={"confirm": True}, headers=H)
    assert r.status_code == 400 and "no longer waiting" in r.json()["detail"]


async def _facts(client: TestClient, books: Books) -> dict:
    _number, link, tid = _paid(client)
    did = FAKES.open_dispute(link["provider_ref"])
    d, inv, t = await pd._dispute(books, did, sample=False)
    return await pd.gather_facts(books, d, inv, t)


async def test_the_models_words_are_used_when_every_figure_and_date_is_in_the_books(
    client: TestClient, books: Books, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts = await _facts(client, books)
    good = (
        f"Invoice {facts['invoice_number']} for {facts['invoice_total']} was emailed to the customer on "
        f"{facts['emailed']['date']} and paid through PayPal on {facts['payment']['date']}. The PDF attached has it."
    )

    async def model(_messages, _cfg) -> str:
        return json.dumps({"notes": good})

    monkeypatch.setattr(pd, "_call_model", model)
    notes, used, reason = await pd.draft_notes(facts, UNREACHABLE)
    assert (notes, used, reason) == (good, "x", None)


@pytest.mark.parametrize(
    ("bad", "why"),
    [
        ("Invoice {n} for £999.00 was paid.", "figures that are not in the books"),
        ("Invoice {n} was delivered on 3 March 2026.", "dates that are not in the books"),
        ("Invoice {n}: see https://example.com", "contained a link"),
        ("The invoice was paid.", "did not mention the invoice number"),
    ],
)
async def test_the_models_words_are_replaced_when_a_check_fails(
    client: TestClient, books: Books, monkeypatch: pytest.MonkeyPatch, bad: str, why: str
) -> None:
    facts = await _facts(client, books)

    async def model(_messages, _cfg) -> str:
        return json.dumps({"notes": bad.format(n=facts["invoice_number"])})

    monkeypatch.setattr(pd, "_call_model", model)
    notes, _used, reason = await pd.draft_notes(facts, UNREACHABLE)
    assert notes == pd.fallback_notes(facts) and reason and why in reason


def test_dates_are_read_in_the_usual_ways() -> None:
    from datetime import date

    text = "On 6 November 2026, then November 7, 2026, 08/11/2026, 2026-11-09 and 10th Nov 2026."
    assert pd.found_dates(text) == {date(2026, 11, d) for d in (6, 7, 8, 9, 10)}


# --------------------------------------------------------------------------- #
# Lost: the reversing entry is proposed, posted only on a yes
# --------------------------------------------------------------------------- #


async def test_a_lost_dispute_proposes_taking_the_payment_back(
    client: TestClient, books: Books, fake: FakeStorageProvider
) -> None:
    number, link, _tid = _paid(client)
    did = FAKES.open_dispute(link["provider_ref"])
    FAKES.resolve_dispute(did, buyer_wins=True)
    row = _ok(client.get(BASE, headers=H))["disputes"][0]
    assert row["lost"] and row["reversal"]["can_post"] and row["reversal"]["amount_pence"] == TOTAL
    assert [(j["account"], j["debit_pence"], j["credit_pence"]) for j in row["reversal"]["journal"]] == [
        ("1100 Debtors", TOTAL, 0),
        ("1240 PayPal clearing", 0, TOTAL),
    ]
    assert (await get_invoice(books, number)).status == "paid"  # nothing posted by listing
    r = client.post(f"{BASE}/{did}/reversal", json={}, headers=H)
    assert r.status_code == 400
    _ok(client.post(f"{BASE}/{did}/reversal", json={"confirm": True}, headers=H))
    inv = await get_invoice(books, number)
    assert inv.status == "sent" and inv.balance_pence == TOTAL
    assert "dispute_reversal_posted" in [a["action"] for a in _audit(fake)]
    assert _ok(client.get(BASE, headers=H))["disputes"][0]["reversal"] is None  # proposed once
    again = client.post(f"{BASE}/{did}/reversal", json={"confirm": True}, headers=H)
    assert again.status_code == 400


def test_a_partial_refund_is_shown_but_not_posted(client: TestClient) -> None:
    _number, link, _tid = _paid(client)
    did = FAKES.open_dispute(link["provider_ref"])
    FAKES.resolve_dispute(did, buyer_wins=True)
    FAKES.disputes[did]["dispute_outcome"]["amount_refunded"] = {"currency_code": "GBP", "value": "100.00"}
    rev = _ok(client.get(BASE, headers=H))["disputes"][0]["reversal"]
    assert not rev["can_post"] and "credit note" in rev["reason"]
    r = client.post(f"{BASE}/{did}/reversal", json={"confirm": True}, headers=H)
    assert r.status_code == 400 and "credit note" in r.json()["detail"]


def test_a_won_dispute_proposes_nothing(client: TestClient) -> None:
    _number, link, _tid = _paid(client)
    did = FAKES.open_dispute(link["provider_ref"])
    FAKES.resolve_dispute(did, buyer_wins=False)
    row = _ok(client.get(BASE, headers=H))["disputes"][0]
    assert not row["lost"] and row["reversal"] is None and row["outcome"] == "RESOLVED_SELLER_FAVOUR"


# --------------------------------------------------------------------------- #
# Demo sandbox: one SAMPLE dispute, never sent to PayPal
# --------------------------------------------------------------------------- #


async def test_the_demo_shows_a_sample_dispute_and_sends_nothing(client: TestClient, books: Books) -> None:
    number = _sent_invoice(client)
    out = await pd.list_disputes(books, sample=True)
    assert out.connected and len(out.disputes) == 0  # no PayPal link and nothing paid yet: no sample
    _ok(client.post(f"/invoices/{number}/mark-paid", json={"paid_on": "2026-10-28"}, headers=H))
    out = await pd.list_disputes(books, sample=True)
    row = out.disputes[0]
    assert row.sample and row.invoice == number and row.dispute_id == f"{pd.SAMPLE_PREFIX}{number}"
    rec = await pd.build_evidence(books, row.dispute_id, None, "sam@sambuilds.co.uk", sample=True)
    assert rec.demo and rec.model == "code"
    sent = await pd.send_evidence(books, row.dispute_id, "sam@sambuilds.co.uk", sample=True)
    assert sent.status == "sent" and sent.demo
    assert not [r for r in FAKES.requests if "/v1/customer/disputes" in r.url.path]
    # outside a demo the sample does not exist
    with pytest.raises(pd.DisputeError):
        await pd.build_evidence(books, row.dispute_id, None, "sam@sambuilds.co.uk", sample=False)


# --------------------------------------------------------------------------- #
# Business and support details on the PayPal invoice
# --------------------------------------------------------------------------- #


async def test_paypal_invoice_carries_the_business_and_support_details(client: TestClient, books: Books) -> None:
    profile = {**PROFILE_JSON, "email": "hello@sambuilds.co.uk", "phone": "07700 900123", "footer_note": "Thank you."}
    await books.write_json(PROFILE, InvoiceProfile.model_validate(profile).model_dump(mode="json"))
    _connect_paypal(client)
    number = _sent_invoice(client)
    _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "paypal"}, headers=H))
    body = json.loads(_calls("/v2/invoicing/invoices")[0].content)
    assert body["invoicer"] == {
        "business_name": "Sam Builds Ltd",
        "address": {
            "country_code": "GB",
            "postal_code": "LS1 1AA",
            "address_line_1": "1 High Street",
            "admin_area_2": "Leeds",
        },
        "phones": [{"country_code": "44", "national_number": "7700900123", "phone_type": "MOBILE"}],
        "tax_id": "GB123456789",
        "additional_notes": "Email: hello@sambuilds.co.uk",
    }
    detail = body["detail"]
    assert "hello@sambuilds.co.uk or 07700 900123" in detail["note"] and number in detail["note"]
    assert detail["terms_and_conditions"].endswith("Thank you.")
    assert detail["memo"].startswith(f"Accnomos invoice {number}")


def test_a_part_paid_invoice_goes_to_paypal_as_one_line_for_the_balance(client: TestClient) -> None:
    _connect_paypal(client)
    number = _sent_invoice(client)
    pay = {"side": "sale", "date": "2026-10-25", "amount_pence": 10000, "account": "1200 Bank", "reference": "part"}
    inv_id = _ok(client.get(f"/invoices/{number}", headers=H))["event_id"]
    _ok(client.post("/payments", json={**pay, "allocations": [{"event_id": inv_id, "amount_pence": 10000}]}, headers=H))
    link = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "paypal"}, headers=H))["invoice"][
        "payment_link"
    ]
    body = json.loads(_calls("/v2/invoicing/invoices")[0].content)
    assert [i["unit_amount"]["value"] for i in body["items"]] == ["272.00"] and "tax" not in body["items"][0]
    assert FAKES.invoices[link["provider_ref"]]["amount"]["value"] == "272.00"


def test_when_paypal_totals_the_lines_differently_it_falls_back_to_one_line(client: TestClient) -> None:
    FAKES.paypal_tax_on_total = True
    _connect_paypal(client)
    draft = {
        **DRAFT,
        "lines": [{"description": f"Part {i}", "quantity": "1", "unit_price_pence": 333} for i in range(3)],
    }
    number = _ok(client.post("/invoices", json=draft, headers=H))["number"]
    _ok(client.post(f"/invoices/{number}/send", json={"confirm": True}, headers=H))
    # Accnomos rounds VAT per line: 3 × (£3.33 + 67p) = £12.00; tax once on the whole £9.99 is £2.00, so £11.99
    link = _ok(client.post(f"/invoices/{number}/payment-link", json={"provider": "paypal"}, headers=H))["invoice"][
        "payment_link"
    ]
    creates = _calls("/v2/invoicing/invoices")
    assert len(creates) == 2 and len(json.loads(creates[0].content)["items"]) == 3
    first = next(i for i in FAKES.invoices.values() if i["detail"]["invoice_number"] == f"{number}-{link['ref'][:6]}")
    assert first["status"] == "CANCELLED"
    final = FAKES.invoices[link["provider_ref"]]
    assert final["detail"]["invoice_number"] == f"{number}-{link['ref'][:6]}-1"
    assert final["amount"]["value"] == "12.00" == f"{link['amount_pence'] // 100}.{link['amount_pence'] % 100:02d}"
