"""Test mode for the end-to-end tests (apps/web/e2e): `ACCNOMOS_TEST_MODE=1`. Never set in the Docker image.

With it on, the runtime talks to nothing outside this process:

* Storage, mail (read and send), the address book and the calendar are in-memory fakes
  (accnomos_connectors.fake), one set per `X-Test-Tenant` header, so the browser and the runtime see one OneDrive
  per Playwright worker (no header: the default set). A token "test-token.<account>" is another Microsoft account
  of that tenant, with fakes of its own (TEST_ACCOUNT_TOKEN: linked profiles, docs/ARCHITECTURE.md). Sent mail is
  only recorded (`GET /__test/state` lists it); day plans read and write the fake calendar.
* The browser's own Graph calls (folder setup, Files, "Add a receipt") go to a small Graph look-alike at
  `/__test/graph/v1.0`, backed by the same fake storage (the test-mode web build points `lib/graph.ts` there).
* Every AI call goes to a stub at `/__test/ai` (Ollama-shaped, see app/ai/config.py). It reads a receipt only
  if it is a gold receipt rendered by evals/harness/render.py, found by the sha256 of the PNG bytes, and
  answers with that receipt's gold fields; questions get an answer built from the facts pack it is sent. It also
  reads the demo receipt (apps/web/public/sample-receipt.png: gold 001 dated 2 Nov 2026) and copies the words of
  an instruction such as "send a £100 invoice to JM Trading" into an action intent by pattern.
* Stripe and PayPal (payment links, app/online_payments.py) are the fakes in app/online_fakes.py: their API calls
  never leave the process, and `/__test/stripe/*` and `/__test/paypal/*` are the pages a browser would see there
  (a consent screen that agrees at once, and a "Pay £…" page per link, so a test can play the customer).
* TrueLayer (bank feeds, app/bank_feeds.py) is the fake in app/bankfeed_fakes.py: `/__test/truelayer/` is the
  bank picker, which agrees at once, and its mock bank's six transactions overlap the gold Barclays CSV by three.
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
    FakeSharingProvider,
    FakeStorageProvider,
    MailAttachment,
    MailMessage,
)
from accnomos_connectors.base import Identity, SharedRoot
from accnomos_connectors.fake import FakeSharingWorld
from app import actions, fake_graph, public_chat, security
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
# Every linked mailbox (Settings › Email intake) holds the first of those again (the same file reaching two
# mailboxes: intake must copy it once) and one receipt of its own.
LINKED_GOLD = ("001_standard.json", "033_standard.json")
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


_QTY = r"(?:(?P<qty>\d+)\s*(?:x|×|rolls? of|packs? of|boxes of|of)?\s+)?"
_FOR_JOB = r"(?:\s+for\s+(?:the\s+)?(?P<job>.+?)\s+job)?"
_SHOPPING_WORDS = (
    re.compile(
        rf"^\s*(?:please\s+)?add\s+{_QTY}(?P<item>.+?){_FOR_JOB}\s+to\s+(?:my|the)\s+shopping\s+list"
        rf"{_FOR_JOB.replace('job>', 'job2>')}[.!]?\s*$",
        re.I,
    ),
    re.compile(
        rf"^\s*(?:please\s+)?(?:remember to|remind me to|i need to)\s+(?:order|buy|get)\s+{_QTY}(?P<item>.+?)"
        rf"{_FOR_JOB}[.!]?\s*$",
        re.I,
    ),
)


def intent_reply(question: str) -> dict[str, Any]:
    """The words of "send a £100 invoice to JM Trading [for …]" or "add [6] packing tape to my shopping list" copied
    into the intent; anything else is `none`."""
    fields: dict[str, Any] = dict.fromkeys(actions.IntentModelOutput.model_fields)
    for rx in _SHOPPING_WORDS:
        if shop := rx.match(question):
            job = shop.groupdict().get("job") or shop.groupdict().get("job2")
            return {
                **fields,
                "kind": "add_to_shopping_list",
                "item_text": shop["item"],
                "quantity_text": shop["qty"],
                "job_ref": job,
            }
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


def spending_reply(content: str) -> dict[str, Any]:
    """A summary quoting only figures from the spending facts (app/ai/spending.py checks every one)."""
    facts = json.loads(content.split("FACTS:\n", 1)[1])
    t = facts["this_period"]
    answer = f"You spent £{t['spent']} before VAT in {t['label']} across {t['purchases']} purchases."
    if t["by_category"]:
        answer += f" Most went on {t['by_category'][0]['name']}."
    if facts["recurring"]:
        answer += f" {facts['recurring'][0]['supplier']} is a regular cost."
    return AskExplanation(answer_md=answer, confidence="high").model_dump()


def items_reply(content: str) -> dict[str, Any]:
    """Deterministic same-product verdicts (app/ai/items.py): every numbered pair is "same"; code's rules decide."""
    pairs = re.findall(r"^(\d+)\. ", content, re.MULTILINE)
    return {"verdicts": [{"pair": int(n), "same": True} for n in pairs]}


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #


class State:
    storage: FakeStorageProvider
    mail: FakeMailProvider
    sender: FakeMailSender
    contacts: FakeContactsProvider
    calendar: FakeCalendarProvider
    linked: dict[str, FakeMailProvider]  # linked mailbox address -> its fake, made on first use
    world: FakeSharingWorld  # everyone's OneDrive as far as sharing goes; the signed-in user's books are in it
    seeded = False
    today: date | None = None  # the `demo` seed's stage date; None: ACCNOMOS_TEST_TODAY

    def linked_mail(self, address: str) -> FakeMailProvider:
        """The fake behind a linked mailbox, whatever token came with it (as for the signed-in one)."""
        if address not in self.linked:
            self.linked[address] = _linked_mailbox(address)
        return self.linked[address]


TENANT_HEADER = "X-Test-Tenant"
#: The signed-in test user (apps/web/src/lib/msal-test.ts) owns `storage`; it is this drive and item in the world.
OWNER = "sam@sambuilds.example"
OWN_ROOT = SharedRoot(drive_id="t-drive", item_id="t-root")
WEB_BASE = "https://onedrive.test.invalid/Accnomos"  # what "Open in OneDrive" links point at in test mode
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


async def sharing(user: str | None) -> FakeSharingProvider:
    """This tenant's sharing world as `user` (X-User; the signed-in test user when absent)."""
    s = await state()
    me = (user or OWNER).strip().lower()
    own = next(
        (
            SharedRoot(drive_id=d, item_id=i)
            for (d, i), (o, n, _st) in s.world.folders.items()
            if o == me and n == "Accnomos"
        ),
        None,
    )
    return FakeSharingProvider(s.world, Identity(email=me), own=own)


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


#: A second (third…) test account's token: "test-token.<account>". It gets a OneDrive, mailbox and calendar of its
#: own, as another Microsoft account would (the web's test sign-in mints it, apps/web/src/lib/msal-test.ts; the
#: profile switcher's e2e test uses it). Plain "test-token", or any other token, is the tenant's first account.
TEST_ACCOUNT_TOKEN = re.compile(r"test-token\.([a-z0-9-]{1,32})")


def account_suffix(headers: dict[bytes, bytes]) -> str:
    """'~<account>' for a second test account's token (X-Graph-Token, or the Graph look-alike's Authorization)."""
    raw = headers.get(b"x-graph-token") or headers.get(b"authorization") or b""
    token = raw.decode("latin-1").strip().removeprefix("Bearer ").strip()
    m = TEST_ACCOUNT_TOKEN.fullmatch(token)
    return f"~{m.group(1)}" if m else ""


class TenantMiddleware:
    """Pure ASGI, outermost: sets the tenant for everything the request runs (routes, dependencies, threadpool)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        raw = headers.get(TENANT_HEADER.lower().encode(), b"")
        tenant = re.sub(r"[^A-Za-z0-9_.-]", "", raw.decode("latin-1"))[:64]
        token = _TENANT.set(tenant + account_suffix(headers))
        try:
            await self.app(scope, receive, send)
        finally:
            _TENANT.reset(token)


def _sender(gold: dict[str, Any]) -> tuple[str, str]:
    name = (gold.get("supplier") or {}).get("name") or "Supplier"
    slug = re.sub(r"[^a-z0-9]+", "", name.lower().removesuffix(" ltd").removesuffix(" limited"))[:24] or "supplier"
    return name, f"accounts@{slug}.example"


def _linked_mailbox(address: str) -> FakeMailProvider:
    mail, golds, received = FakeMailProvider(), gold_receipts(), datetime.now(UTC)
    for n, file in enumerate(LINKED_GOLD, start=1):
        name, sender = _sender(golds[file])
        png = gold_png(file)
        mail.add(
            MailMessage(
                id=f"{address}-msg-{n}",
                received_at=received - timedelta(days=n, hours=2),
                from_address=sender,
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
    return mail


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


async def _seed_purchases(s: State) -> None:
    """A few months of approved purchases with line items (app/sample_purchases.py), for Spending, Cheaper options
    and the shopping list."""
    from app.books import Books
    from app.sample_purchases import seed_purchases

    await seed_purchases(Books(s.storage))


#: The `accountant` seed: two clients who shared their books with the test user (who is their accountant here).
CLIENTS = (
    ("jo@harbourjoinery.example", "c1-drive", "c1-root", "Harbour Joinery Ltd", "business", "write"),
    ("priya@patel-lettings.example", "c2-drive", "c2-root", "Patel Lettings", "landlord", "read"),
)


async def _seed_accountant(s: State) -> None:
    """Two clients' books shared with OWNER (one view and edit, one view only), each with a proposal waiting in
    Review and the client's own profile in _System/accountant.json; the second has a query waiting on the client.
    Also a folder that is shared but is not a set of books (the portal must leave it out)."""
    from app import accountant
    from app.books import RECEIPTS, Books
    from app.queries import Query, QueryMessage, QuerySubject

    for n, (owner, drive, item, name, kind, role) in enumerate(CLIENTS, start=1):
        storage = FakeStorageProvider()
        books = Books(storage)
        await books.ensure_tree()
        root = s.world.add_folder(owner, drive, item, "Accnomos", storage)
        client = FakeSharingProvider(s.world, Identity(email=owner), own=root)
        await client.invite(root, OWNER, role, "")  # type: ignore[arg-type]
        if role == "read":
            await client.invite(root, OWNER, "write", "", path="_System/queries")
        profile = accountant.ClientProfile(name=name, kind=kind, vat_registered=n == 1)  # type: ignore[arg-type]
        when = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
        record = accountant.AccountantFile(
            profile=profile,
            root=root,
            invitations=[
                accountant.Invitation(
                    id=f"inv{n}",
                    kind="own",
                    email=OWNER,
                    role="edit" if role == "write" else "read",
                    method="graph",
                    invited_at=when,
                    invited_by=owner,
                )  # fmt: skip
            ],
        )
        await books.write_json(accountant.ACCOUNTANT, record.model_dump(mode="json"))
        gold = extracted_from_gold(gold_receipts()[MAIL_GOLD[n - 1]])
        await books.save_proposal(_seed_proposal(f"5eed000{n}", gold))  # proposal ids are hex
        await books.audit(f"user:{owner}", "approved", {"proposal": f"5eed000{n}"})
        if n == 2:
            q = Query(
                id="a1b2c3d4e5f6",
                subject=QuerySubject(kind="document", ref=f"{RECEIPTS}/2026-10/rent.pdf", label="October rent receipt"),
                created_at=when,
                created_by=OWNER,
                messages=[QueryMessage(ts=when, author=OWNER, role="accountant", text="Is this rent for Flat 2?")],
            )
            await books.write_json(f"_System/queries/{q.id}.json", q.model_dump(mode="json", exclude={"waiting_on"}))
    other = FakeStorageProvider()
    await other.write("Holiday/plan.txt", b"not books")
    s.world.add_folder("jo@harbourjoinery.example", "c1-drive", "c1-photos", "Photos", other)
    await FakeSharingProvider(s.world, Identity(email="jo@harbourjoinery.example")).invite(
        SharedRoot(drive_id="c1-drive", item_id="c1-photos"), OWNER, "read", ""
    )


def _seed_proposal(pid: str, extracted: dict[str, Any]) -> Any:
    from app.schemas import Proposal

    return Proposal.model_validate(
        {
            "id": pid,
            "doc_sha256": hashlib.sha256(pid.encode()).hexdigest(),
            "extracted": extracted,
            "checks": [],
            "status": "proposed",
            "reasons": [],
            "suggested_filename": f"{pid}.png",
            "journal_draft": [],
            "model": "seed",
            "elapsed_s": 0.0,
            "created_at": datetime(2026, 10, 21, 10, 0, tzinfo=UTC).isoformat(),
        }
    )


SEEDS = {
    "bank": _seed_bank,
    "demo": _seed_demo,
    "purchases": _seed_purchases,
    "accountant": _seed_accountant,
}  # opt-in: they change the VAT figures or the date other flows check


async def reset(seed: str | None = None) -> dict[str, Any]:
    """This tenant only: empty storage; reseed the mailbox, address book, calendar and invoice profile;
    then any `seed`.
    """
    from app.invoicing import PROFILE, InvoiceProfile

    if seed is not None and seed not in SEEDS:
        raise HTTPException(400, f"unknown seed {seed!r}; one of {sorted(SEEDS)}")
    s = current()
    s.today = None
    s.storage = FakeStorageProvider(web_base=WEB_BASE)
    s.world = FakeSharingWorld()
    s.world.add_folder(OWNER, OWN_ROOT.drive_id, OWN_ROOT.item_id, "Accnomos", s.storage)
    await s.storage.write(PROFILE, InvoiceProfile.model_validate(SAMPLE_PROFILE).model_dump_json(indent=2).encode())
    s.mail = FakeMailProvider()
    s.linked = {}
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


#: Written by deploy/Dockerfile.runtime. Unlike ACCNOMOS_IMAGE, `docker run -e` cannot take it away.
IMAGE_MARKER = Path("/etc/accnomos-image")


def enable() -> None:
    """Called once by app.main when ACCNOMOS_TEST_MODE=1. Refused in the Docker image (ACCNOMOS_IMAGE=1, or the
    IMAGE_MARKER file): it carries evals/gold for Load sample books, so the stub AI could read receipts there, and
    test mode must never run."""
    if os.getenv("ACCNOMOS_IMAGE") == "1" or IMAGE_MARKER.exists():
        raise RuntimeError("ACCNOMOS_TEST_MODE=1 is refused in the runtime image (ACCNOMOS_IMAGE=1)")
    os.environ.setdefault("ACCNOMOS_TEST_TODAY", DEFAULT_TODAY)
    os.environ.setdefault("CROP_MODE", "off")  # the stub knows the uploaded bytes, not a re-encoded crop
    # The browser's Graph and AI calls come here instead of Microsoft/Ollama; they must not eat the per-IP budget.
    security.UNLIMITED_PREFIXES = ("/__test/",)
    from app import online_fakes, online_payments

    online_fakes.install(online_payments.public_base())  # Stripe and PayPal calls go to the fakes, never out
    from app import bankfeed_fakes

    bankfeed_fakes.install()  # TrueLayer calls (bank feeds) go to the fakes, never out
    log.warning("ACCNOMOS_TEST_MODE=1: fake storage/mail/calendar and a stub AI; not for real books")


def warm() -> None:
    """Render every gold receipt and hash it now (~10 s), before /health answers. Done lazily, the first scan blocked
    the event loop that long, so every parallel Playwright worker's first test timed out behind it."""
    _by_hash()


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

router = APIRouter(prefix="/__test", tags=["test mode"], include_in_schema=False)


def _payment_pages() -> None:
    from app.online_fakes import router as fakes_router  # the providers' pages a browser sees: consent, pay

    router.include_router(fakes_router)
    from app.bankfeed_fakes import router as bankfeed_router  # TrueLayer's bank picker, already agreed

    router.include_router(bankfeed_router)


_payment_pages()


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
        "linked_mail_calls": {address: m.calls for address, m in s.linked.items()},
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


def close_reply(content: str) -> dict[str, Any]:
    """The month-end summary (app/ai/close_summary.py) in words that quote only the counts it was given."""
    facts = json.loads(content.split("FACTS:\n", 1)[1])
    needs, blocking = facts["needs_you"], facts["blocking"]
    text = f"Test stub summary for {facts['month']}: {needs} to look at, {blocking} blocking the close."
    return {"summary_md": text}


def duplicate_reply(content: str) -> dict[str, Any]:
    """Deterministic duplicate judgement (app/ai/duplicates.py): same, keeping the first name listed."""
    first = re.search(r'^1\. "([^"]+)"', content, re.MULTILINE)
    return {
        "same": True,
        "confidence": 0.9,
        "keep_name": first.group(1) if first else "",
        "reason": "Test stub judgement: no real model ran.",
    }


@router.api_route("/ai/down/{rest:path}", methods=["GET", "POST"])
async def ai_down(rest: str) -> JSONResponse:
    """A provider that is down (ACCNOMOS_TEST_AI_DOWN, app/ai/providers.py): every call answers 503."""
    return JSONResponse({"error": f"stub AI: this provider is down ({rest})"}, status_code=503)


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
    from app.ai import close_summary

    if system == close_summary.SYSTEM_PROMPT:
        return JSONResponse(_ollama(close_reply(messages[-1]["content"])))
    from app.ai import items as items_ai
    from app.ai import spending as spending_ai

    if system == spending_ai.SYSTEM_PROMPT:
        return JSONResponse(_ollama(spending_reply(messages[-1]["content"])))
    if system == items_ai.SYSTEM_PROMPT:
        return JSONResponse(_ollama(items_reply(messages[-1]["content"])))
    if system == public_chat.SYSTEM_PROMPT:
        return JSONResponse(_ollama(public_chat_reply(messages[-1]["content"])))
    from app import cashflow

    if system == cashflow.SYSTEM_PROMPT:  # one line quoting two of the forecast's own figures
        facts = json.loads(messages[-1]["content"].split("FACTS:\n", 1)[1])
        line = f"Your bank is {facts['bank_balance_today']} today and {facts['balance_in_90_days']} in 90 days."
        return JSONResponse(_ollama({"line": line}))
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

GRAPH_ROOT_ID = fake_graph.GRAPH_ROOT_ID
_id = fake_graph.item_id
_path_of = fake_graph.path_of


@router.api_route("/graph/v1.0/{rest:path}", methods=["GET", "POST", "PUT"])
async def graph(rest: str, request: Request) -> Response:
    """The handful of Graph calls apps/web/src/lib/graph.ts makes (app/fake_graph.py), over this tenant's fakes."""
    return await fake_graph.respond((await state()).storage, rest, request, WEB_BASE)
