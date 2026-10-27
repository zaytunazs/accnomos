"""Your data, out: POST /books/export saves one zip in 07 Reports/Exports.

The zip holds the books as plain files (the same JSON the app wrote, copied
byte for byte), the audit trail, the saved VAT returns, an index of the invoice
PDFs (the PDFs themselves stay where they are filed, under 03 Sales), a
README.txt explaining every file, and one CSV per main table (ledger lines,
contacts, invoices, payments) so it opens in Excel.

The zip is written to the user's own OneDrive through their own token, like any
other runtime write: it is never streamed through a third party. It is capped
at MAX_EXPORT_FILES source files and MAX_EXPORT_BYTES source bytes (413 beyond
that), audited as `data_exported`, and idempotent per day: a second run the
same day gets " (2)" via Books.free_path, nothing is overwritten.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date
from typing import Any

from app.books import AUDIT, Books
from app.books import today as current_date
from app.paths import REPORTS, SALES, VAT_RETURNS

#: Where the zips live, under 07 Reports.
EXPORTS = f"{REPORTS}/Exports"
#: accnomos-export-2026-10-27.zip
EXPORT_PREFIX = "accnomos-export-"
#: Refused with 413 beyond either of these (source files read, before zipping).
MAX_EXPORT_FILES = 2000
MAX_EXPORT_BYTES = 25 * 1024 * 1024

_INVOICES = f"{SALES}/invoices"
_CONTACTS = "_System/Contacts/contacts.json"
_PAYMENTS = "_System/Payments/payments.json"
_CREDIT_USES = "_System/Payments/credit_uses.json"
_ACCOUNT_RULES = "_System/rules.json"
_AUTOPILOT_RULES = "_System/Rules/rules.json"
_BANK_RULES = "_System/bank_rules.json"


class ExportTooBig(ValueError):
    """The books are bigger than the export caps (MAX_EXPORT_FILES / MAX_EXPORT_BYTES)."""


def export_filename(day: date) -> str:
    """'accnomos-export-2026-10-27.zip'."""
    return f"{EXPORT_PREFIX}{day.isoformat()}.zip"


async def _walk(books: Books, folder: str) -> list[str]:
    """Every file under `folder`, recursively, as full paths. Missing folders give []."""
    out: list[str] = []

    async def visit(path: str) -> None:
        try:
            items = await books.storage.list(path)
        except FileNotFoundError:
            return
        for item in sorted(items, key=lambda f: f.path):
            if item.is_folder:
                await visit(item.path)
            else:
                out.append(item.path)

    await visit(folder)
    return out


async def _read_capped(books: Books, paths: list[str], taken: dict[str, int]) -> dict[str, bytes]:
    """Read `paths`, raising ExportTooBig past the caps. `taken` counts files and bytes so far."""
    out: dict[str, bytes] = {}
    for path in paths:
        data = await books.storage.read(path)
        taken["files"] += 1
        taken["bytes"] += len(data)
        if taken["files"] > MAX_EXPORT_FILES or taken["bytes"] > MAX_EXPORT_BYTES:
            raise ExportTooBig(
                f"Your books are bigger than one export ({MAX_EXPORT_FILES} files, "
                f"{MAX_EXPORT_BYTES // 1024 // 1024} MB). Delete nothing: export in parts from the Files page instead."
            )
        out[path] = data
    return out


def _csv(rows: list[dict[str, Any]], columns: list[str]) -> bytes:
    """CSV bytes with a UTF-8 BOM, so Excel opens them as text, not mojibake."""
    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in columns})
    return buf.getvalue().encode("utf-8")


def _jsons(raw: dict[str, bytes]) -> list[dict[str, Any]]:
    """Parsed JSON objects from raw files; a hand-edited broken file is skipped, never fatal."""
    out: list[dict[str, Any]] = []
    for data in raw.values():
        try:
            obj = json.loads(data)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _readme(day: date, names: list[str]) -> str:
    lines = [
        "Your Accnomos data export.",
        "",
        f"Exported {day.isoformat()}. Everything the app knows about your business is in",
        "this zip, as plain files: the same JSON the app wrote to your OneDrive, plus",
        "one CSV per main table so it opens in Excel (open the CSVs, not the JSON,",
        "for a spreadsheet view). Money is integer pence in the JSON; the CSVs show",
        "pence too, so divide by 100 for pounds.",
        "",
        "What each file holds:",
        "- README.txt: this file.",
        "- ledger-events/: every posted ledger event, one immutable balanced journal",
        "  per file (the books themselves; a correction is a new reversing entry).",
        "- ledger-lines.csv: the same events as spreadsheet rows (one row per line).",
        "- proposals/: every Review card and its decision (proposed, needs a look,",
        "  posted, rejected).",
        "- contacts.json / contacts.csv: names and details only; money is always",
        "  worked out from the ledger events.",
        "- invoices/: every sales invoice draft, sent invoice and bill as JSON, plus",
        f"  invoice-pdfs-index.json: where each invoice PDF lives under {SALES}",
        "  (the PDFs themselves stay filed there; this export only lists them).",
        "- invoices.csv: one row per invoice.",
        "- payments.json / payments.csv: recorded payments (amount, date, account,",
        "  the split across invoices or bills) and credit_uses.json (credits applied",
        "  or refunded). A removed payment is kept, marked removed.",
        "- bank-lines.json: every imported bank statement line with its match status.",
        '- rules.json: your filing rules ("always file this supplier to that',
        '  account"); autopilot-rules.json: Autopilot rules; bank-rules.json: bank',
        "  statement rules.",
        "- audit/: the audit trail, one JSON object per line (who did what, when).",
        "- vat-returns/: the 9-box calculation and HMRC receipt saved for each",
        "  submitted period.",
        "",
        "Files in this export:",
        *(f"- {name}" for name in names if name != "README.txt"),
        "",
        "The runtime keeps nothing: this zip was written straight to your OneDrive,",
        "and the only record of it is the data_exported line in your audit trail.",
    ]
    return "\n".join(lines) + "\n"


async def build_export(books: Books, day: date) -> tuple[bytes, list[str]]:
    """(zip bytes, file names inside, README first). Raises ExportTooBig past the caps."""
    taken = {"files": 0, "bytes": 0}

    events = await _read_capped(
        books, [p for p in await _walk(books, "_System/Ledger/events") if p.endswith(".json")], taken
    )
    proposals = await _read_capped(
        books, [p for p in await _walk(books, "_System/proposals") if p.endswith(".json")], taken
    )
    contacts_raw = await _read_capped(books, [_CONTACTS] if await books.exists(_CONTACTS) else [], taken)
    invoice_jsons = await _read_capped(
        books, [f.path for f in await books.list_files(_INVOICES) if f.name.endswith(".json")], taken
    )
    sales_pdfs = [
        {"path": p, "size": len(d)}
        for p, d in (
            await _read_capped(books, [p for p in await _walk(books, SALES) if p.endswith(".pdf")], taken)
        ).items()
    ]
    payments_raw = await _read_capped(books, [p for p in (_PAYMENTS, _CREDIT_USES) if await books.exists(p)], taken)
    bank_lines = [ln.model_dump(mode="json") for ln in await books.stored_bank_lines()]
    rules_raw = await _read_capped(
        books, [p for p in (_ACCOUNT_RULES, _AUTOPILOT_RULES, _BANK_RULES) if await books.exists(p)], taken
    )
    audit_raw = await _read_capped(books, [p for p in await _walk(books, AUDIT) if p.endswith(".jsonl")], taken)
    vat_raw = await _read_capped(books, await _walk(books, VAT_RETURNS), taken)

    parsed_events = _jsons(events)
    ledger_rows: list[dict[str, Any]] = []
    for obj in parsed_events:
        for ln in obj.get("lines") or []:
            if isinstance(ln, dict):
                ledger_rows.append(
                    {
                        "event_id": obj.get("id"),
                        "date": obj.get("date"),
                        "kind": obj.get("kind"),
                        "account": ln.get("account"),
                        "debit_pence": ln.get("debit"),
                        "credit_pence": ln.get("credit"),
                        "vat_code": ln.get("vat_code"),
                        "counterparty": obj.get("counterparty"),
                        "approved_by": obj.get("approved_by"),
                    }
                )
    ledger_rows.sort(key=lambda r: (str(r["date"]), str(r["event_id"]), str(r["account"])))

    # contacts.json holds a list, not one object per file: parse it as a list.
    contact_rows: list[dict[str, Any]] = []
    for data in contacts_raw.values():
        try:
            obj = json.loads(data)
        except ValueError:
            continue
        for c in obj if isinstance(obj, list) else []:
            if isinstance(c, dict):
                contact_rows.append(
                    {
                        "id": c.get("id"),
                        "kind": c.get("kind"),
                        "name": c.get("name"),
                        "email": c.get("email"),
                        "phone": c.get("phone"),
                        "vrn": c.get("vrn"),
                        "source": c.get("source"),
                    }
                )
    contact_rows.sort(key=lambda r: str(r["name"]))

    invoice_rows: list[dict[str, Any]] = []
    for obj in _jsons(invoice_jsons):
        customer = obj.get("customer")
        invoice_rows.append(
            {
                "number": obj.get("number"),
                "status": obj.get("status"),
                "issue_date": obj.get("issue_date"),
                "customer": customer.get("name") if isinstance(customer, dict) else customer,
                "net_pence": obj.get("net_pence"),
                "vat_pence": obj.get("vat_pence"),
                "total_pence": obj.get("total_pence"),
            }
        )
    invoice_rows.sort(key=lambda r: (str(r["issue_date"]), str(r["number"])))

    payment_rows: list[dict[str, Any]] = []
    for data in payments_raw.values():
        try:
            obj = json.loads(data)
        except ValueError:
            continue
        for p in obj if isinstance(obj, list) else []:
            if isinstance(p, dict) and "allocations" in p:
                payment_rows.append(
                    {
                        "id": p.get("id"),
                        "side": p.get("side"),
                        "date": p.get("date"),
                        "amount_pence": p.get("amount_pence"),
                        "account": p.get("account"),
                        "counterparty": p.get("counterparty"),
                        "event_id": p.get("event_id"),
                    }
                )
    payment_rows.sort(key=lambda r: (str(r["date"]), str(r["id"])))

    rule_files = {
        _ACCOUNT_RULES: "rules.json",
        _AUTOPILOT_RULES: "autopilot-rules.json",
        _BANK_RULES: "bank-rules.json",
    }

    zip_files: dict[str, bytes] = {}
    for path, data in sorted(events.items()):
        zip_files[f"ledger-events/{path.removeprefix('_System/Ledger/events/')}"] = data
    for path, data in sorted(proposals.items()):
        zip_files[f"proposals/{path.rsplit('/', 1)[-1]}"] = data
    zip_files["contacts.json"] = next(iter(contacts_raw.values()), b"[]")
    for path, data in sorted(invoice_jsons.items()):
        zip_files[f"invoices/{path.rsplit('/', 1)[-1]}"] = data
    zip_files["invoices/invoice-pdfs-index.json"] = (
        json.dumps(sorted(sales_pdfs, key=lambda e: e["path"]), indent=2) + "\n"
    ).encode()
    zip_files["payments.json"] = payments_raw.get(_PAYMENTS, b"[]")
    zip_files["credit-uses.json"] = payments_raw.get(_CREDIT_USES, b"[]")
    zip_files["bank-lines.json"] = (json.dumps(bank_lines, indent=2) + "\n").encode()
    for src, name in rule_files.items():
        zip_files[name] = rules_raw.get(src, b"[]")
    for path, data in sorted(audit_raw.items()):
        zip_files[f"audit/{path.removeprefix(f'{AUDIT}/')}"] = data
    for path, data in sorted(vat_raw.items()):
        zip_files[f"vat-returns/{path.removeprefix(f'{VAT_RETURNS}/')}"] = data
    zip_files["ledger-lines.csv"] = _csv(
        ledger_rows,
        [
            "event_id",
            "date",
            "kind",
            "account",
            "debit_pence",
            "credit_pence",
            "vat_code",
            "counterparty",
            "approved_by",
        ],
    )
    zip_files["contacts.csv"] = _csv(contact_rows, ["id", "kind", "name", "email", "phone", "vrn", "source"])
    zip_files["invoices.csv"] = _csv(
        invoice_rows, ["number", "status", "issue_date", "customer", "net_pence", "vat_pence", "total_pence"]
    )
    zip_files["payments.csv"] = _csv(
        payment_rows, ["id", "side", "date", "amount_pence", "account", "counterparty", "event_id"]
    )

    names = ["README.txt", *sorted(zip_files)]
    zip_files = {"README.txt": _readme(day, names).encode(), **dict(sorted(zip_files.items()))}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in zip_files.items():
            zf.writestr(name, data)
    return buf.getvalue(), ["README.txt", *sorted(n for n in zip_files if n != "README.txt")]


async def run_export(books: Books, user: str, day: date | None = None) -> dict[str, Any]:
    """Build the zip, save it under 07 Reports/Exports (never overwriting), audit it, and describe it."""
    day = day or current_date()
    data, _names = await build_export(books, day)
    await books.storage.ensure_folder(EXPORTS)
    path = await books.free_path(EXPORTS, export_filename(day))
    ref = await books.storage.write(path, data)
    await books.audit(f"user:{user}", "data_exported", {"path": path, "files": len(_names), "size": len(data)})
    return {
        "path": path,
        "name": path.rsplit("/", 1)[1],
        "size": ref.size,
        "files": len(_names),
        "web_url": ref.web_url,
    }
