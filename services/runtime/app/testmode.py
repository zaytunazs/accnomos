"""Test mode for the end-to-end tests (apps/web/e2e): `ACCNOMOS_TEST_MODE=1`. Never set in the Docker image.

With it on, the runtime talks to nothing outside this process:

* Storage, mail and the address book are in-memory fakes (accnomos_connectors.fake), shared by every request
  whatever token it carries, so the browser and the runtime see one OneDrive. A fake calendar is held too.
* The browser's own Graph calls (folder setup, Files, "Add a receipt") go to a small Graph look-alike at
  `/__test/graph/v1.0`, backed by the same fake storage (the test-mode web build points `lib/graph.ts` there).
* Every AI call goes to a stub at `/__test/ai` (Ollama-shaped, see app/ai/config.py). It reads a receipt only
  if it is a gold receipt rendered by evals/harness/render.py, found by the sha256 of the PNG bytes, and
  answers with that receipt's gold fields; questions get an answer built from the facts pack it is sent.
* "Today" is pinned to ACCNOMOS_TEST_TODAY (default 2026-10-27) so the gold receipts (Jul-Sep 2026) fall in
  the quarter the VAT page and Ask default to (the last complete one); timestamps stay real.

`POST /__test/reset` empties storage and reseeds the mailbox (three gold receipts by email plus one message
that is not a receipt) and the calendar. `GET /__test/gold` lists the gold receipts; `GET /__test/gold/{file}.png`
serves one as the PNG the stub recognises.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

from accnomos_connectors import (
    AddressBookContact,
    FakeCalendarProvider,
    FakeContactsProvider,
    FakeMailProvider,
    FakeStorageProvider,
    MailAttachment,
    MailMessage,
)
from accnomos_connectors.base import FileRef
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.ai import ask as ask_ai
from app.ai import extract as extract_ai
from app.ai import verify as verify_ai
from app.ai.config import TEST_AI_MODEL
from app.schemas import CATEGORIES, AskModelOutput

log = logging.getLogger("accnomos.testmode")

DEFAULT_TODAY = "2026-10-27"  # VAT and Ask default to the last complete quarter: Jul-Sep 2026, the gold set's
MAIL_GOLD = ("001_standard.json", "011_standard.json", "022_standard.json")  # emailed in by the seeded suppliers
CALENDAR = "Accnomos"


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


@lru_cache(maxsize=None)
def gold_png(file: str) -> bytes:
    return _renderer().render_receipt(gold_receipts()[file]["printed_text"], messy=False, seed=0)


@lru_cache(maxsize=1)
def _by_hash() -> dict[str, str]:
    """sha256 of the rendered PNG -> gold file name (the "known document hashes")."""
    return {hashlib.sha256(gold_png(f)).hexdigest(): f for f in gold_receipts()}


# --------------------------------------------------------------------------- #
# Gold -> what a model would have read
# --------------------------------------------------------------------------- #

_PAYMENT = {"card": "card", "cash": "cash", "bank transfer": "bank_transfer", "direct debit": "direct_debit", "cheque": "cheque"}
_CATEGORY_WORDS = (  # first match wins; the gold hints are free text from the generator
    ("office", "Office supplies"), ("stationery", "Office supplies"), ("it hardware", "Office supplies"),
    ("tool", "Tools & small equipment"), ("hardware", "Tools & small equipment"),
    ("material", "Materials"), ("joinery", "Materials"), ("carpentry", "Materials"),
    ("parking", "Motor expenses"), ("transport", "Travel"), ("postage", "Postage"), ("courier", "Postage"),
    ("energy", "Utilities"), ("grocer", "Subsistence"), ("supermarket", "Subsistence"),
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
                "description": ln.get("description") or "", "qty": ln.get("qty") or 1, "unit_price": ln.get("unit_price") or 0,
                "net": ln.get("net") or 0, "vat_rate": ln.get("vat_rate"), "vat": ln.get("vat") or 0,
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
        "seller": supplier.get("name") or "", "vat_registration": supplier.get("vat_number"), "issue_date": gold["date"],
        "amount_before_vat": gold["net_total"], "vat_amount": gold["vat_total"], "amount_payable": gold["gross_total"],
    }


def ask_reply(facts: dict[str, Any]) -> dict[str, Any]:
    """A grounded answer that quotes only figures from the facts pack (app/ai/ask.py checks every one)."""
    key_numbers = [k.model_dump() for k in ask_ai._fact_key_numbers(facts)]
    box5, prev_box5 = key_numbers[0]["value"], key_numbers[1]["value"]
    answer = (
        f"Your net VAT (Box 5) for this quarter is {box5} ({facts['derived']['vat_position']}), "
        f"from {facts['this_period']['entries']} approved entries. Last quarter it was {prev_box5}."
    )
    out = {
        "answer_md": answer, "key_numbers": key_numbers, "citations": ask_ai.vat_sources(facts),
        "suggested_actions": [{"label": "Open the VAT return", "kind": "open_vat", "arg": None}], "confidence": "high",
    }
    return AskModelOutput.model_validate(out).model_dump()


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #


class State:
    storage: FakeStorageProvider
    mail: FakeMailProvider
    contacts: FakeContactsProvider
    calendar: FakeCalendarProvider
    seeded = False


STATE = State()


async def state() -> State:
    """The shared fakes, seeded on first use."""
    if not STATE.seeded:
        await reset()
    return STATE


def _sender(gold: dict[str, Any]) -> tuple[str, str]:
    name = (gold.get("supplier") or {}).get("name") or "Supplier"
    slug = re.sub(r"[^a-z0-9]+", "", name.lower().removesuffix(" ltd").removesuffix(" limited"))[:24] or "supplier"
    return name, f"accounts@{slug}.example"


async def reset() -> dict[str, Any]:
    """Empty storage; reseed the mailbox, address book and calendar from the gold set."""
    STATE.storage = FakeStorageProvider()
    STATE.mail = FakeMailProvider()
    STATE.contacts = FakeContactsProvider()
    STATE.calendar = FakeCalendarProvider()
    received = datetime.now(UTC)
    golds = gold_receipts()
    for n, file in enumerate(MAIL_GOLD, start=1):
        gold, png = golds[file], gold_png(file)
        name, address = _sender(gold)
        STATE.mail.add(
            MailMessage(id=f"msg-{n}", received_at=received - timedelta(days=n), from_address=address, from_name=name,
                        subject=f"Your receipt from {name}"),
            (MailAttachment(id=f"att-{n}", name=f"receipt-{file.split('_')[0]}.png", content_type="image/png", size=len(png)), png),
        )
        STATE.contacts.contacts.append(AddressBookContact(id=f"contact-{n}", display_name=name, company_name=name, emails=[address]))
    STATE.mail.add(  # a newsletter with a calendar invite: intake must skip it
        MailMessage(id="msg-news", received_at=received - timedelta(hours=6), from_address="news@trade-weekly.example",
                    from_name="Trade Weekly", subject="This week's offers"),
        (MailAttachment(id="att-news", name="webinar.ics", content_type="text/calendar", size=900), b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"),
    )
    cal = await STATE.calendar.ensure_calendar(CALENDAR)
    await STATE.calendar.upsert_all_day_event(cal, "vat-26A3", "2026-11-07", "VAT return due (Jul–Sep 2026)", "SAMPLE — FICTIONAL COMPANY")
    STATE.seeded = True
    return {"ok": True, "mail": len(STATE.mail.messages), "gold": len(golds)}


def enable() -> None:
    """Called once by app.main when ACCNOMOS_TEST_MODE=1."""
    os.environ.setdefault("ACCNOMOS_TEST_TODAY", DEFAULT_TODAY)
    os.environ.setdefault("CROP_MODE", "off")  # the stub knows the uploaded bytes, not a re-encoded crop
    log.warning("ACCNOMOS_TEST_MODE=1: fake storage/mail/calendar and a stub AI; not for real books")


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

router = APIRouter(prefix="/__test", tags=["test mode"], include_in_schema=False)


@router.post("/reset")
async def reset_route() -> dict[str, Any]:
    return await reset()


@router.get("/gold")
async def gold_list() -> list[dict[str, Any]]:
    out = []
    for file, gold in gold_receipts().items():
        out.append({
            "file": file, "case": gold.get("gold_case"), "supplier": (gold.get("supplier") or {}).get("name"),
            "date": gold["date"], "gross": gold["gross_total"], "vat": gold["vat_total"], "net": gold["net_total"],
            "doc_type": gold["doc_type"], "png_sha256": hashlib.sha256(gold_png(file)).hexdigest(),
        })
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
        "files": sorted(s.storage.files), "mail_calls": s.mail.calls,
        "calendar": {cid: {k: list(v) for k, v in ev.items()} for cid, ev in s.calendar.events.items()},
    }


# ---- stub AI (Ollama-shaped: /api/tags, /api/chat) ------------------------ #


@router.get("/ai/api/tags")
async def ai_tags() -> dict[str, Any]:
    return {"models": [{"name": TEST_AI_MODEL}]}


def _ollama(content: dict[str, Any]) -> dict[str, Any]:
    return {"model": TEST_AI_MODEL, "message": {"role": "assistant", "content": json.dumps(content)}, "done": True,
            "prompt_eval_count": 0, "eval_count": 0, "total_duration": 0}


@router.post("/ai/api/chat")
async def ai_chat(request: Request) -> JSONResponse:
    body = await request.json()
    messages = body.get("messages") or []
    system = next((m.get("content") for m in messages if m.get("role") == "system"), "")
    images = [img for m in messages for img in (m.get("images") or [])]
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
    gold = gold_receipts()[file]
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
    raw = item_id.removeprefix("t-")
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()


def _drive_item(ref: FileRef) -> dict[str, Any]:
    st = STATE.storage
    path = ref.path.strip("/")
    item: dict[str, Any] = {
        "id": _id(path), "name": ref.name or "Accnomos", "eTag": ref.etag,
        "webUrl": f"https://onedrive.test.invalid/Accnomos/{path}",
        "lastModifiedDateTime": (ref.modified or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
    }
    if ref.is_folder:
        prefix = f"{path}/" if path else ""
        item["size"] = sum(len(v) for k, v in st.files.items() if k.startswith(prefix))
        children = {k[len(prefix):].split("/", 1)[0] for k in [*st.files, *st.folders] if k and k.startswith(prefix)}
        item["folder"] = {"childCount": len(children)}
    else:
        item["size"] = ref.size
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        item["file"] = {"mimeType": {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "pdf": "application/pdf",
                                     "json": "application/json", "txt": "text/plain"}.get(ext, "application/octet-stream")}
    return item


def _not_found(path: str) -> JSONResponse:
    return JSONResponse({"error": {"code": "itemNotFound", "message": f"Item does not exist: {path}"}}, status_code=404)


async def _get(path: str) -> JSONResponse:
    st = STATE.storage
    if path in st.folders:
        return JSONResponse(_drive_item(FileRef(id="", path=path, name=path.rsplit("/", 1)[-1], is_folder=True)))
    if path in st.files:
        return JSONResponse(_drive_item(st._ref(path)))
    return _not_found(path)


_ROOTS = ("me/drive/special/approot", "me/drive/root:/Accnomos")


@router.api_route("/graph/v1.0/{rest:path}", methods=["GET", "POST", "PUT"])
async def graph(rest: str, request: Request) -> JSONResponse:
    """The handful of Graph calls apps/web/src/lib/graph.ts makes, path-addressed under the books root."""
    st = (await state()).storage
    method = request.method
    if rest == "me/drive/root/children" and method == "POST":  # work account: create /Accnomos
        return JSONResponse(_drive_item(FileRef(id="", path="", name="Accnomos", is_folder=True)), status_code=201)
    if m := re.fullmatch(r"me/drive/items/([^/]+)/children", rest):
        if method != "POST":
            return JSONResponse({"error": {"code": "notSupported"}}, status_code=400)
        parent = _path_of(m.group(1))
        body = await request.json()
        path = f"{parent}/{body['name']}".strip("/")
        if path in st.folders or path in st.files:
            return JSONResponse({"error": {"code": "nameAlreadyExists"}}, status_code=409)
        ref = await st.ensure_folder(path)
        return JSONResponse(_drive_item(ref), status_code=201)
    root = next((r for r in _ROOTS if rest == r or rest.startswith(r + ":/") or rest.startswith(r + "/")), None)
    if root is None:
        return _not_found(rest)
    tail = rest[len(root):]
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
        return _not_found(rel) if rel not in st.files else JSONResponse({"error": {"code": "useDownloadUrl"}}, status_code=400)
    if action == "children":
        if rel not in st.folders:
            return _not_found(rel)
        return JSONResponse({"value": [_drive_item(r) for r in await st.list(rel)]})
    return await _get(rel)
