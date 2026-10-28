"""Test mode for the end-to-end tests (apps/web/e2e): `ACCNOMOS_TEST_MODE=1`. Never set in the Docker image.

With it on, the runtime talks to nothing outside this process:

* Storage, mail (read and send), the address book and the calendar are in-memory fakes
  (accnomos_connectors.fake), one set per `X-Test-Tenant` header whatever token the request carries, so the
  browser and the runtime see one OneDrive per Playwright worker (no header: the default set). Sent mail is
  only recorded (`GET /__test/state` lists it); day plans read and write the fake calendar.
* The browser's own Graph calls (folder setup, Files, "Add a receipt") go to a small Graph look-alike at
  `/__test/graph/v1.0`, backed by the same fake storage (the test-mode web build points `lib/graph.ts` there).
* Every AI call goes to a stub at `/__test/ai` (Ollama-shaped, see app/ai/config.py). It reads a receipt only
  if it is a gold receipt rendered by evals/harness/render.py, found by the sha256 of the PNG bytes, and
  answers with that receipt's gold fields; questions get an answer built from the facts pack it is sent. It also
  reads the demo receipt (apps/web/public/sample-receipt.png: gold 001 dated 2 Nov 2026) and copies the words of
  an instruction such as "send a £100 invoice to JM Trading" into an action intent by pattern.
* "Today" is pinned to ACCNOMOS_TEST_TODAY (default 2026-10-27): the gold receipts (Jul-Sep 2026) fall in the
  previous VAT quarter, the one still to file (the VAT page and Ask default to the current one, Oct-Dec);
  timestamps stay real. The `demo` seed moves its tenant to docs/DEMO.md's stage date (4 Nov 2026).

`POST /__test/reset` empties the caller's tenant's storage and reseeds the mailbox (three gold receipts by email
plus one message that is not a receipt) and the calendar. `GET /__test/gold` lists the gold receipts;
`GET /__test/gold/{file}.png` serves one as the PNG the stub recognises.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import logging
import os
import re
from contextvars import ContextVar
from datetime import UTC, date, datetime, timedelta
from functools import cache, lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from accnomos_connectors import (
    AddressBookContact,
    CalendarEvent,
    FakeCalendarProvider,
    FakeContactsProvider,
    FakeMailProvider,
    FakeMailSender,
    FakeStorageProvider,
    MailAttachment,
    MailMessage,
)
from accnomos_connectors.base import FileRef
from app import actions, public_chat, security
from app.ai import ask as ask_ai
from app.ai import extract as extract_ai
from app.ai import verify as verify_ai
from app.ai.config import TEST_AI_MODEL
from app.schemas import CATEGORIES, AskExplanation

log = logging.getLogger("accnomos.testmode")

DEFAULT_TODAY = (
    "2026-10-27"  # the gold set's quarter (Jul-Sep 2026) is the one still to file; VAT and Ask default to Oct-Dec
)
MAIL_GOLD = ("001_standard.json", "011_standard.json", "022_standard.json")  # emailed in by the seeded suppliers
CALENDAR = "Accnomos"
SAMPLE = "SAMPLE — FICTIONAL COMPANY"
DEMO_TODAY = date(2026, 11, 4)  # docs/DEMO.md's stage date: the sample receipt (2 Nov) is in the current quarter
DEMO_RECEIPT = "sample-receipt.png"  # apps/web/public/, drawn by tools/make_sample_receipt.py
DEMO_CUSTOMER = AddressBookContact(
    id="contact-jm", display_name="JM Trading Ltd", company_name="JM Trading Ltd", emails=["accounts@jmtrading.example"]
)
# Thursday after the pinned today (Tue 27 Oct 2026): one busy hour in the morning.
PLAN_EVENT = CalendarEvent(
    id="evt-sample-thu",
    subject="Site meeting, Harbour Lane kitchen",
    location="12 Harbour Lane, Bristol BS1 4RW",
    start=datetime(2026, 10, 29, 9, 0, tzinfo=ZoneInfo("Europe/London")),
    end=datetime(2026, 10, 29, 10, 0, tzinfo=ZoneInfo("Europe/London")),
    body_preview=SAMPLE,
)


def _gold_dir() -> Path:
    env = os.getenv("ACCNOMOS_GOLD_DIR")
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        if (parent / "evals" / "gold" / "manifest.json").exists():
            return parent / "evals" / "gold"
    raise RuntimeError("evals/gold not found; set ACCNOMOS_GOLD_DIR")


@lru_cache(maxsize=1)
def _renderer() -> ModuleType:
    """evals/harness/render.py, loaded by path: the runtime package does not depend on the evals package."""
    path = _gold_dir().parent / "harness" / "render.py"
    spec = importlib.util.spec_from_file_location("accnomos_gold_render", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@lru_cache(maxsize=1)
def gold_receipts() -> dict[str, dict[str, Any]]:
    """file name -> gold JSON, in manifest order."""
    folder = _gold_dir() / "receipts"
    manifest = json.loads((_gold_dir() / "manifest.json").read_text(encoding="utf-8"))
    return {i["file"]: json.loads((folder / i["file"]).read_text(encoding="utf-8")) for i in manifest["items"]}


@cache
def gold_png(file: str) -> bytes:
    return _renderer().render_receipt(gold_receipts()[file]["printed_text"], messy=False, seed=0)


def _demo_receipt_png() -> bytes | None:
    for parent in Path(__file__).resolve().parents:
        if (path := parent / "apps" / "web" / "public" / DEMO_RECEIPT).exists():
            return path.read_bytes()
    return None  # a runtime checkout without the web app: only the gold receipts are known


@lru_cache(maxsize=1)
def _documents() -> dict[str, dict[str, Any]]:
    """Every document the stub reads: the gold receipts, and the demo receipt
    (gold 001 as printed, dated 2 Nov 2026).
    """
    return {**gold_receipts(), DEMO_RECEIPT: {**gold_receipts()["001_standard.json"], "date": "2026-11-02"}}


@lru_cache(maxsize=1)
def _by_hash() -> dict[str, str]:
    """sha256 of the PNG -> document name (the "known document hashes")."""
    known = {hashlib.sha256(gold_png(f)).hexdigest(): f for f in gold_receipts()}
    if (demo := _demo_receipt_png()) is not None:
        known[hashlib.sha256(demo).hexdigest()] = DEMO_RECEIPT
    return known


# --------------------------------------------------------------------------- #
# Gold -> what a model would have read
# --------------------------------------------------------------------------- #

_PAYMENT = {
    "card": "card",
    "cash": "cash",
    "bank transfer": "bank_transfer",
    "direct debit": "direct_debit",
    "cheque": "cheque",
}
_CATEGORY_WORDS = (  # first match wins; the gold hints are free text from the generator
    ("office", "Office supplies"),
    ("stationery", "Office supplies"),
    ("it hardware", "Office supplies"),
    ("tool", "Tools & small equipment"),
    ("hardware", "Tools & small equipment"),
    ("material", "Materials"),
    ("joinery", "Materials"),
    ("carpentry", "Materials"),
    ("parking", "Motor expenses"),
    ("transport", "Travel"),
    ("postage", "Postage"),
    ("courier", "Postage"),
    ("energy", "Utilities"),
    ("grocer", "Subsistence"),
    ("supermarket", "Subsistence"),
)


def _category(gold: dict[str, Any]) -> str:
    if gold["doc_type"] == "sales_invoice":
        return "Sales"
    hint = (gold.get("category_hint") or "").lower()
    for word, category in _CATEGORY_WORDS:
        if word in hint and category in CATEGORIES:
            return category
    return "Sundry"


def extracted_from_gold(gold: dict[str, Any]) -> dict[str, Any]:
    """The gold receipt as an `ExtractedDoc` dict, i.e. what a perfect reading would return."""
    supplier = gold.get("supplier") or {}
    customer = gold.get("customer")
    return {
        "doc_type": gold["doc_type"],
        "supplier_name": supplier.get("name") or "",
        "supplier_vat_number": supplier.get("vat_number"),
        "customer_name": customer.get("name") if isinstance(customer, dict) else customer,
        "invoice_number": gold.get("invoice_number"),
        "date": gold["date"],
        "currency": gold.get("currency") or "GBP",
        "lines": [
            {
                "description": ln.get("description") or "",
                "qty": ln.get("qty") or 1,
                "unit_price": ln.get("unit_price") or 0,
                "net": ln.get("net") or 0,
                "vat_rate": ln.get("vat_rate"),
                "vat": ln.get("vat") or 0,
            }
            for ln in gold.get("lines") or []
        ],
        "net_total": gold["net_total"],
        "vat_total": gold["vat_total"],
        "gross_total": gold["gross_total"],
        "payment_method": _PAYMENT.get((gold.get("payment_method") or "").lower(), "unknown"),
        "card_last4": gold.get("card_last4"),
        "category_guess": _category(gold),
        "confidence": 0.97,
    }


def verifier_reading_from_gold(gold: dict[str, Any]) -> dict[str, Any]:
    supplier = gold.get("supplier") or {}
    return {
        "seller": supplier.get("name") or "",
        "vat_registration": supplier.get("vat_number"),
        "issue_date": gold["date"],
        "amount_before_vat": gold["net_total"],
        "vat_amount": gold["vat_total"],
        "amount_payable": gold["gross_total"],
    }


def ask_reply(facts: dict[str, Any]) -> dict[str, Any]:
    """A grounded explanation that quotes only figures from the routed facts pack (app/ai/ask.py checks every one)."""
    this, prev = facts["this_period"], facts["previous_period"]
    if "vat" in this:
        answer = (
            f"Your net VAT (Box 5) for this quarter is {ask_ai._gbp(this['vat']['box5'])} ({this['vat_position']}), "
            f"from {this['entries']} approved entries."
        )
    elif "vat" in prev:
        answer = f"Your net VAT (Box 5) for {prev['label']} was {ask_ai._gbp(prev['vat']['box5'])}."
    else:
        answer = "The books I was given don't show that."
    return AskExplanation(answer_md=answer, confidence="high").model_dump()


_INVOICE_WORDS = re.compile(
    r"^\s*(?P<send>send|email)?\s*(?:an?\s+)?(?P<amount>£[\d,]+(?:\.\d+)?)\s+invoice\s+to\s+(?P<customer>.+?)"
    r"(?:\s+for\s+(?P<description>.+?))?[.!]?\s*$",
    re.I,
)


def intent_reply(question: str) -> dict[str, Any]:
    """The words of "send a £100 invoice to JM Trading [for …]" copied into the intent; anything else is `none`."""
    fields: dict[str, Any] = dict.fromkeys(actions.IntentModelOutput.model_fields)
    m = _INVOICE_WORDS.match(question)
    if m is None:
        return {**fields, "kind": "none"}
    return {
        **fields,
        "kind": "create_invoice",
        "customer_ref": m["customer"],
        "amount_text": m["amount"],
        "description": m["description"],
        "send": bool(m["send"]),
    }


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #


class State:
    storage: FakeStorageProvider
    mail: FakeMailProvider
    sender: FakeMailSender
    contacts: FakeContactsProvider
    calendar: FakeCalendarProvider
    seeded = False
    today: date | None = None  # the `demo` seed's stage date; None: ACCNOMOS_TEST_TODAY


TENANT_HEADER = "X-Test-Tenant"
_TENANT: ContextVar[str] = ContextVar("accnomos_test_tenant", default="")
STATE = State()  # no X-Test-Tenant header: the unit tests and a runtime started by hand
STATES: dict[str, State] = {"": STATE}


def pinned_today() -> date | None:
    """This tenant's "today" for app.books.today: the `demo` seed's date, else ACCNOMOS_TEST_TODAY."""
    s = STATES.get(_TENANT.get())
    if s is not None and s.today is not None:
        return s.today
    pinned = os.getenv("ACCNOMOS_TEST_TODAY")
    return date.fromisoformat(pinned) if pinned else None


def tenant() -> str:
    """This request's X-Test-Tenant ("" without the header)."""
    return _TENANT.get()


def current() -> State:
    """This request's fakes: one set per X-Test-Tenant, so Playwright workers never see each other's OneDrive."""
    return STATES.setdefault(_TENANT.get(), State())


async def state() -> State:
    """This tenant's fakes, seeded on first use."""
    s = current()
    if not s.seeded:
        await reset()
    return s


class TenantMiddleware:
    """Pure ASGI, outermost: sets the tenant for everything the request runs (routes, dependencies, threadpool)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        raw = dict(scope["headers"]).get(TENANT_HEADER.lower().encode(), b"")
        token = _TENANT.set(re.sub(r"[^A-Za-z0-9_.-]", "", raw.decode("latin-1"))[:64])
        try:
            await self.app(scope, receive, send)
        finally:
            _TENANT.reset(token)


def _sender(gold: dict[str, Any]) -> tuple[str, str]:
    name = (gold.get("supplier") or {}).get("name") or "Supplier"
    slug = re.sub(r"[^a-z0-9]+", "", name.lower().removesuffix(" ltd").removesuffix(" limited"))[:24] or "supplier"
    return name, f"accounts@{slug}.example"


# The business on its invoices, so an invoice can be sent without filling Settings in first.
SAMPLE_PROFILE = {
    "name": "Sam Builds Ltd",
    "address": "1 Sample Street\nBristol\nBS1 1AA",
    "email": "sam@sambuilds.example",
    "phone": "0117 496 0000",
    "vrn": "GB123456789",
    "terms_days": 30,
    "footer_note": SAMPLE,
    "bank": {"account_name": "Sam Builds Ltd", "sort_code": "00-00-00", "account_number": "00000000"},
}


def _bank_event(spec: dict[str, Any]) -> Any:
    """One posted event from evals/gold/bank/expected.json
    (purchases paid from 1200 Bank, sales owed in 1100 Debtors).
    """
    from accnomos_ledger import LedgerEvent, Line, VatCode

    gross = spec["gross_pence"]
    if spec["kind"] == "sale":
        lines = [
            Line(account="1100 Debtors", debit=gross),
            Line(account="4000 Sales", credit=gross, vat_code=VatCode.STANDARD),
        ]
    else:
        lines = [
            Line(account="7999 Sundry expenses", debit=gross, vat_code=VatCode.STANDARD),
            Line(account="1200 Bank", credit=gross),
        ]
    return LedgerEvent(
        id=spec["id"],
        kind=spec["kind"],
        date=date.fromisoformat(spec["date"]),
        lines=lines,
        net=gross,
        vat=0,
        counterparty=spec["counterparty"],
        evidence=["ab" * 32],
        approved_by="sam@sambuilds.example",
        approved_at=datetime(2026, 10, 26, tzinfo=UTC),
    )


async def _seed_bank(s: State) -> None:
    """The entries the gold Barclays statement (evals/gold/bank/barclays.csv) pays for, labelled SAMPLE there."""
    from app.books import Books

    expected = json.loads((_gold_dir() / "bank" / "expected.json").read_text(encoding="utf-8"))
    books = Books(s.storage)
    for spec in expected["events"]:
        if spec["id"].startswith("gold-bc-"):
            await books.post_event(_bank_event(spec))


async def _seed_demo(s: State) -> None:
    """docs/DEMO.md on stage (apps/web/e2e/demo.spec.ts): today is 4 Nov 2026, and JM Trading Ltd, the customer the
    presenter invoices, is in the Outlook address book (Contacts → Import from Outlook adds it)."""
    s.today = DEMO_TODAY
    s.contacts.contacts.append(DEMO_CUSTOMER.model_copy(deep=True))  # one per tenant: workers never share an object


SEEDS = {"bank": _seed_bank, "demo": _seed_demo}  # opt-in: they change the VAT figures or the date other flows check


async def reset(seed: str | None = None) -> dict[str, Any]:
    """This tenant only: empty storage; reseed the mailbox, address book, calendar and invoice profile;
    then any `seed`.
    """
    from app.invoicing import PROFILE, InvoiceProfile

    if seed is not None and seed not in SEEDS:
        raise HTTPException(400, f"unknown seed {seed!r}; one of {sorted(SEEDS)}")
    s = current()
    s.today = None
    s.storage = FakeStorageProvider()
    await s.storage.write(PROFILE, InvoiceProfile.model_validate(SAMPLE_PROFILE).model_dump_json(indent=2).encode())
    s.mail = FakeMailProvider()
    s.sender = FakeMailSender()
    s.contacts = FakeContactsProvider()
    s.calendar = FakeCalendarProvider([PLAN_EVENT])  # something for "plan my Thursday" to plan around
    received = datetime.now(UTC)
    golds = gold_receipts()
    for n, file in enumerate(MAIL_GOLD, start=1):
        gold, png = golds[file], gold_png(file)
        name, address = _sender(gold)
        s.mail.add(
            MailMessage(
                id=f"msg-{n}",
                received_at=received - timedelta(days=n),
                from_address=address,
                from_name=name,
                subject=f"Your receipt from {name}",
            ),
            (
                MailAttachment(
                    id=f"att-{n}", name=f"receipt-{file.split('_')[0]}.png", content_type="image/png", size=len(png)
                ),
                png,
            ),
        )
        s.contacts.contacts.append(
            AddressBookContact(id=f"contact-{n}", display_name=name, company_name=name, emails=[address])
        )
    s.mail.add(  # a newsletter with a calendar invite: intake must skip it
        MailMessage(
            id="msg-news",
            received_at=received - timedelta(hours=6),
            from_address="news@trade-weekly.example",
            from_name="Trade Weekly",
            subject="This week's offers",
        ),
        (
            MailAttachment(id="att-news", name="webinar.ics", content_type="text/calendar", size=900),
            b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
        ),
    )
    cal = await s.calendar.ensure_calendar(CALENDAR)
    await s.calendar.upsert_all_day_event(cal, "vat-26A3", "2026-11-07", "VAT return due (Jul–Sep 2026)", SAMPLE)
    if seed:
        await SEEDS[seed](s)
    if security.LIMITER:  # each test starts with a full request budget
        security.LIMITER.reset()
    s.seeded = True
    return {"ok": True, "mail": len(s.mail.messages), "gold": len(golds), "seed": seed}


def enable() -> None:
    """Called once by app.main when ACCNOMOS_TEST_MODE=1. Refused in the Docker image (ACCNOMOS_IMAGE=1): it carries
    evals/gold for Load sample books, so the stub AI could read receipts there, and test mode must never run."""
    if os.getenv("ACCNOMOS_IMAGE") == "1":
        raise RuntimeError("ACCNOMOS_TEST_MODE=1 is refused in the runtime image (ACCNOMOS_IMAGE=1)")
    os.environ.setdefault("ACCNOMOS_TEST_TODAY", DEFAULT_TODAY)
    os.environ.setdefault("CROP_MODE", "off")  # the stub knows the uploaded bytes, not a re-encoded crop
    # The browser's Graph and AI calls come here instead of Microsoft/Ollama; they must not eat the per-IP budget.
    security.UNLIMITED_PREFIXES = ("/__test/",)
    log.warning("ACCNOMOS_TEST_MODE=1: fake storage/mail/calendar and a stub AI; not for real books")


def warm() -> None:
    """Render every gold receipt and hash it now (~10 s), before /health answers. Done lazily, the first scan blocked
    the event loop that long, so every parallel Playwright worker's first test timed out behind it."""
    _by_hash()


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

router = APIRouter(prefix="/__test", tags=["test mode"], include_in_schema=False)


@router.post("/reset")
async def reset_route(seed: str | None = None) -> dict[str, Any]:
    return await reset(seed)


@router.get("/gold")
async def gold_list() -> list[dict[str, Any]]:
    out = []
    for file, gold in gold_receipts().items():
        out.append(
            {
                "file": file,
                "case": gold.get("gold_case"),
                "supplier": (gold.get("supplier") or {}).get("name"),
                "date": gold["date"],
                "gross": gold["gross_total"],
                "vat": gold["vat_total"],
                "net": gold["net_total"],
                "doc_type": gold["doc_type"],
                "png_sha256": hashlib.sha256(gold_png(file)).hexdigest(),
            }
        )
    return out


@router.get("/gold/{file}.png")
async def gold_image(file: str) -> Response:
    if f"{file}.json" not in gold_receipts():
        raise HTTPException(404, "no such gold receipt")
    return Response(gold_png(f"{file}.json"), media_type="image/png")


@router.get("/state")
async def state_route() -> dict[str, Any]:
    """What the fakes hold, for debugging a failed run."""
    s = await state()
    return {
        "files": sorted(s.storage.files),
        "mail_calls": s.mail.calls,
        "sent": [
            {"to": m.to, "subject": m.subject, "attachments": [a.name for a in m.attachments]} for m in s.sender.sent
        ],
        "calendar": {cid: {k: list(v) for k, v in ev.items()} for cid, ev in s.calendar.all_day.items()},
    }


# ---- stub AI (Ollama-shaped: /api/tags, /api/chat) ------------------------ #


@router.get("/ai/api/tags")
async def ai_tags() -> dict[str, Any]:
    return {"models": [{"name": TEST_AI_MODEL}]}


def _ollama(content: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": TEST_AI_MODEL,
        "message": {"role": "assistant", "content": json.dumps(content)},
        "done": True,
        "prompt_eval_count": 0,
        "eval_count": 0,
        "total_duration": 0,
    }


def bank_ai_reply(content: str) -> dict[str, Any]:
    """Deterministic coding for a bank line (app/bank_reconcile.py): the stub never invents accounts."""
    try:
        facts = json.loads(content.split("LINE:\n", 1)[1])
    except (ValueError, IndexError, AttributeError):
        facts = {}
    accounts = [a for a in (facts.get("accounts") or []) if isinstance(a, str)]
    account = next((a for a in accounts if "Sundry" in a), accounts[0] if accounts else "7999 Sundry expenses")
    return {"account": account, "vat_code": "N", "contact": None, "reason": "Test stub coding: no real model ran."}


def duplicate_reply(content: str) -> dict[str, Any]:
    """Deterministic duplicate judgement (app/ai/duplicates.py): same, keeping the first name listed."""
    first = re.search(r'^1\. "([^"]+)"', content, re.MULTILINE)
    return {
        "same": True,
        "confidence": 0.9,
        "keep_name": first.group(1) if first else "",
        "reason": "Test stub judgement: no real model ran.",
    }


def public_chat_reply(content: str) -> dict[str, Any]:
    """Deterministic website chat answer (app/public_chat.py): the first sentence of the first note it was given."""
    m = re.search(r"^\[([a-z0-9-]+)\] [^\n]*\n([^\n]+)", content, re.MULTILINE)
    if not m:
        return {"answerable": False, "answer": "", "sections": []}
    first = re.split(r"(?<=[.!?])\s+", m.group(2).strip())[0]
    return {"answerable": True, "answer": f"{first} (Test stub answer: no real model ran.)", "sections": [m.group(1)]}


@router.post("/ai/api/chat")
async def ai_chat(request: Request) -> JSONResponse:
    body = await request.json()
    messages = body.get("messages") or []
    system = next((m.get("content") for m in messages if m.get("role") == "system"), "")
    from app import bank_reconcile as bank_rec
    from app.ai import duplicates as dup_ai

    if system == bank_rec.BANK_SUGGEST_PROMPT:
        return JSONResponse(_ollama(bank_ai_reply(messages[-1]["content"])))
    if system == dup_ai.SYSTEM_PROMPT:
        return JSONResponse(_ollama(duplicate_reply(messages[-1]["content"])))
    if system == public_chat.SYSTEM_PROMPT:
        return JSONResponse(_ollama(public_chat_reply(messages[-1]["content"])))
    images = [img for m in messages for img in (m.get("images") or [])]
    if system == actions.INTENT_PROMPT:
        return JSONResponse(_ollama(intent_reply(messages[-1]["content"])))
    if system == ask_ai.SYSTEM_PROMPT:
        user = messages[-1]["content"]
        facts = json.loads(user.split("FACTS:\n", 1)[1].rsplit("\n\nQuestion:", 1)[0])
        return JSONResponse(_ollama(ask_reply(facts)))
    if not images:
        raise HTTPException(400, "stub AI: unknown request")
    digest = hashlib.sha256(base64.b64decode(images[0])).hexdigest()
    file = _by_hash().get(digest)
    if file is None:
        raise HTTPException(422, f"stub AI: not a gold receipt (sha256 {digest[:12]}…)")
    gold = _documents()[file]
    if system == extract_ai.SYSTEM_PROMPT:
        return JSONResponse(_ollama(extracted_from_gold(gold)))
    if system == verify_ai.VERIFIER_SYSTEM_PROMPT:
        return JSONResponse(_ollama(verifier_reading_from_gold(gold)))
    raise HTTPException(400, "stub AI: unknown prompt")


# ---- Graph look-alike for the browser ------------------------------------ #

GRAPH_ROOT_ID = "t-root"


def _id(path: str) -> str:
    return "t-" + base64.urlsafe_b64encode(path.encode()).decode().rstrip("=") if path else GRAPH_ROOT_ID


def _path_of(item_id: str) -> str:
    if item_id == GRAPH_ROOT_ID:
        return ""
    if not item_id.startswith("t-"):
        raise ValueError(item_id)
    raw = item_id.removeprefix("t-")
    return base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True).decode()


def _drive_item(ref: FileRef) -> dict[str, Any]:
    st = current().storage
    path = ref.path.strip("/")
    item: dict[str, Any] = {
        "id": _id(path),
        "name": ref.name or "Accnomos",
        "eTag": ref.etag,
        "webUrl": f"https://onedrive.test.invalid/Accnomos/{path}",
        "lastModifiedDateTime": (ref.modified or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
    }
    if ref.is_folder:
        prefix = f"{path}/" if path else ""
        item["size"] = sum(len(v) for k, v in st.files.items() if k.startswith(prefix))
        children = {k[len(prefix) :].split("/", 1)[0] for k in [*st.files, *st.folders] if k and k.startswith(prefix)}
        item["folder"] = {"childCount": len(children)}
    else:
        item["size"] = ref.size
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        item["file"] = {
            "mimeType": {
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "pdf": "application/pdf",
                "json": "application/json",
                "txt": "text/plain",
            }.get(ext, "application/octet-stream")
        }
    return item


def _not_found(path: str) -> JSONResponse:
    return JSONResponse({"error": {"code": "itemNotFound", "message": f"Item does not exist: {path}"}}, status_code=404)


async def _get(path: str) -> JSONResponse:
    st = current().storage
    if path in st.folders:
        return JSONResponse(_drive_item(FileRef(id="", path=path, name=path.rsplit("/", 1)[-1], is_folder=True)))
    if path in st.files:
        return JSONResponse(_drive_item(st._ref(path)))
    return _not_found(path)


_ROOTS = ("me/drive/special/approot", "me/drive/root:/Accnomos")


@router.api_route("/graph/v1.0/{rest:path}", methods=["GET", "POST", "PUT"])
async def graph(rest: str, request: Request) -> Response:
    """The handful of Graph calls apps/web/src/lib/graph.ts makes, path-addressed under the books root."""
    st = (await state()).storage
    method = request.method
    if rest == "me/drive/root/children" and method == "POST":  # work account: create /Accnomos
        return JSONResponse(_drive_item(FileRef(id="", path="", name="Accnomos", is_folder=True)), status_code=201)
    if m := re.fullmatch(r"me/drive/items/([^/]+)/children", rest):
        if method != "POST":
            return JSONResponse({"error": {"code": "notSupported"}}, status_code=400)
        try:
            parent = _path_of(m.group(1))
        except ValueError:  # not an id this look-alike handed out (binascii.Error and UnicodeDecodeError included)
            return _not_found(m.group(1))
        name = (await request.json()).get("name")
        if not isinstance(name, str) or not name.strip("/"):
            return JSONResponse({"error": {"code": "invalidRequest", "message": "name required"}}, status_code=400)
        if parent and parent not in st.folders:
            return _not_found(parent)
        path = f"{parent}/{name}".strip("/")
        if path in st.folders or path in st.files:
            return JSONResponse({"error": {"code": "nameAlreadyExists"}}, status_code=409)
        ref = await st.ensure_folder(path)
        return JSONResponse(_drive_item(ref), status_code=201)
    root = next((r for r in _ROOTS if rest == r or rest.startswith(r + ":/") or rest.startswith(r + "/")), None)
    if root is None:
        return _not_found(rest)
    tail = rest[len(root) :]
    action = ""
    if tail in ("/children", ":/children"):
        rel, action = "", "children"
    else:
        tail = tail.removeprefix(":/").removeprefix("/")
        for suffix in (":/children", ":/content"):
            if tail.endswith(suffix):
                tail, action = tail[: -len(suffix)], suffix[2:]
        rel = tail.strip("/")
    if action == "content" and method == "PUT":
        ref = await st.write(rel, await request.body())
        return JSONResponse(_drive_item(ref), status_code=201)
    if action == "content":
        if rel not in st.files:
            return _not_found(rel)
        ext = rel.rsplit(".", 1)[-1].lower()  # the Review preview reads the filed receipt
        mime = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "pdf": "application/pdf",
        }
        return Response(st.files[rel], media_type=mime.get(ext, "application/octet-stream"))
    if action == "children":
        if rel not in st.folders:
            return _not_found(rel)
        return JSONResponse({"value": [_drive_item(r) for r in await st.list(rel)]})
    return await _get(rel)
