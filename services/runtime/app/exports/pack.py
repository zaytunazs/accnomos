"""The Accountant pack (one zip of the main reports, VAT returns and contacts, with a README), the open ledger JSON,
the contact list, and one zip per package of every import file for it.

The ledger JSON ("accnomos-ledger", version 1) is documented in docs/ARCHITECTURE.md and describes itself in its
"schema" key: every approved event with its balanced lines, in integer pence, plus the chart the events use.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app import reports as rp
from app.deadlines import period_containing, period_id
from app.exports import writers
from app.exports.accounts import RETAINED, klass, split_account
from app.exports.mapping import PACKAGES, problems, resolve
from app.exports.registry import (
    ExportContext,
    ExportSpec,
    ReportDoc,
    Row,
    Section,
    catalogue,
    columns,
    doc_from,
    register,
    span_label,
    uk_day,
)
from app.exports.vendors import chart

LEDGER_FORMAT = "accnomos-ledger"
LEDGER_VERSION = 1
LEDGER_SCHEMA: dict[str, Any] = {
    "format": "Always 'accnomos-ledger'.",
    "version": "1. A new version may add keys; it never changes the meaning of one.",
    "currency": "GBP. Every amount is an integer number of pence.",
    "basis": "How the entries count: as approved, each on its own date; an undo is a new entry, never an edit.",
    "period": "{from, to}: the entries' dates included (null: every entry).",
    "accounts": "[{account, code, name, class}]: every account the entries use; class is fixed_assets, "
    "current_assets, current_liabilities, capital, sales, cost_of_sales, overheads or unclassified.",
    "events": "[{id, kind, date, lines, net, vat, counterparty, evidence, approved_by, approved_at, proposal_id, "
    "reverses, credits, file}] oldest first. kind is purchase, sale, bank, adjustment or reversal. lines are "
    "[{account, debit, credit, vat_code, memo}], one side each; debits equal credits in every event. vat_code is "
    "S (20%), R (5%), Z (0%), E (exempt), O (outside the scope), N (no VAT invoice held) or null. net and vat are the "
    "VAT-able net and the VAT the return counts. evidence is the sha256 of each source document. file is the event's "
    "own JSON file in _System/Ledger/events.",
    "totals": "{events, debits, credits}: a check that the file is complete; debits equal credits.",
}


async def ledger_json(ctx: ExportContext, whole: bool = True) -> dict[str, Any]:
    events = await ctx.events()
    paths = await ctx.event_paths()
    picked = events if whole else [e for e in events if ctx.start <= e.date <= ctx.end]
    accounts = sorted({ln.account for e in picked for ln in e.lines}, key=lambda a: (rp.account_code(a) or 99_999, a))
    out_events = []
    for e in sorted(picked, key=lambda e: (e.date, e.approved_at, e.id)):
        d = json.loads(e.model_dump_json())
        d["lines"] = [
            {
                "account": ln["account"],
                "debit": ln["debit"],
                "credit": ln["credit"],
                "vat_code": ln["vat_code"],
                "memo": ln["memo"],
            }
            for ln in d["lines"]
        ]
        d["file"] = paths.get(e.id)
        out_events.append(d)
    return {
        "format": LEDGER_FORMAT,
        "version": LEDGER_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "currency": "GBP",
        "amounts": "integer pence",
        "basis": rp.BASIS,
        "sample": rp.is_sample(events),
        "period": None if whole else {"from": ctx.start.isoformat(), "to": ctx.end.isoformat()},
        "schema": LEDGER_SCHEMA,
        "accounts": [
            {"account": a, "code": split_account(a)[0] or None, "name": split_account(a)[1], "class": klass(a)}
            for a in accounts
        ],
        "events": out_events,
        "totals": {
            "events": len(out_events),
            "debits": sum(ln.debit for e in picked for ln in e.lines),
            "credits": sum(ln.credit for e in picked for ln in e.lines),
        },
    }


async def build_ledger_preview(ctx: ExportContext) -> ReportDoc:
    data = await ledger_json(ctx)
    cols = columns(("key", "Key"), ("value", "What it holds"))
    rows = [Row(cells={"key": k, "value": v}) for k, v in LEDGER_SCHEMA.items()]
    t = data["totals"]
    return doc_from(
        "ledger-json",
        "Ledger (open JSON)",
        "every approved entry",
        [
            Section(
                title="Ledger JSON",
                columns=cols,
                rows=rows,
                note=f"{t['events']} entries; debits {t['debits']} pence, credits {t['credits']} pence.",
            )
        ],
        sample=bool(data["sample"]),
    )


async def raw_ledger(ctx: ExportContext) -> bytes:
    return (json.dumps(await ledger_json(ctx), indent=2, ensure_ascii=False) + "\n").encode()


CONTACT_COLUMNS = columns(
    ("name", "Name"),
    ("kind", "Customer or supplier"),
    ("email", "Email"),
    ("phone", "Phone"),
    ("address", "Address"),
    ("vrn", "VAT number"),
    ("company", "Company number"),
    ("terms", "Payment terms (days)", "int"),
)


async def build_contacts(ctx: ExportContext) -> ReportDoc:
    contacts = sorted(await ctx.contacts(), key=lambda c: c.name.lower())
    rows = [
        Row(
            cells={
                "name": c.name,
                "kind": c.kind,
                "email": c.email or "",
                "phone": c.phone or "",
                "address": " ".join((c.address or "").split()),
                "vrn": c.vrn or "",
                "company": c.company_number or "",
                "terms": c.terms_days,
            }
        )
        for c in contacts
    ]
    return doc_from(
        "contact-list",
        "Contact list",
        f"at {uk_day(ctx.today)}",
        [Section(title="Contacts", columns=CONTACT_COLUMNS, rows=rows)],
        sample=rp.is_sample(await ctx.events()),
    )


# --------------------------------------------------------------------------- #
# The Accountant pack
# --------------------------------------------------------------------------- #

PACK_REPORTS = (
    "trial-balance",
    "general-ledger",
    "balance-sheet",
    "profit-and-loss",
    "aged-receivables-detail",
    "aged-payables-detail",
    "journal-report",
    "audit-trail",
    "bank-reconciliation",
    "contact-list",
)


def vat_spans(start: date, end: date, start_month: int, months: int, today: date) -> list[tuple[date, date]]:
    """Every VAT period that ends inside [start, end] and has ended by `today`."""
    out = []
    s, e = period_containing(start, start_month, months)
    while s <= end:
        if start <= e <= end and e < today:
            out.append((s, e))
        s, e = period_containing(e + timedelta(days=1), start_month, months)
    return out


def _readme(ctx: ExportContext, names: list[str], warnings: list[str], sample: bool, vat_periods: list[str]) -> str:
    lines = [
        *(["SAMPLE — FICTIONAL COMPANY", ""] if sample else []),
        "Accountant pack from Accnomos",
        "",
        f"Period: {span_label(ctx.start, ctx.end)}.",
        f"Aged balances and the bank reconciliation are at {uk_day(ctx.end)}.",
        f"Generated: {datetime.now(UTC):%d/%m/%Y %H:%M} UTC.",
        "",
        "Basis",
        f"- {rp.BASIS}",
        "- Accounts are placed by their four-digit code: 0001-0999 fixed assets, 1000-1999 current assets, 2000-2999",
        "  current liabilities, 3000-3999 capital, 4000-4999 sales, 5000-5999 cost of sales, 6000-8999 overheads.",
        f"- No year-end has been closed in the books: profit before the period is one line, {RETAINED}.",
        "- VAT that cannot be reclaimed (codes N and O) is in the expense line. VAT periods in this pack: "
        + (", ".join(vat_periods) if vat_periods else "none end inside the period")
        + ".",
        "- Every figure is worked out by code from the approved ledger entries; no model is involved. Nothing in this",
        "  pack was posted to the books.",
        "",
        "What to check",
        "- The trial balance balances, and the balance sheet's net assets equal capital and reserves.",
        "- Bank and cash against the bank's own statements (bank-reconciliation.*).",
        "- Accruals, prepayments, depreciation and stock: Accnomos records none of these.",
        "- Unmapped or 'check' accounts before importing any file into another package (listed below if any).",
        "",
        "Files",
        *(f"- {n}" for n in names),
    ]
    if warnings:
        lines += ["", "Warnings", *(f"- {w}" for w in warnings)]
    return "\n".join(lines) + "\n"


async def raw_pack(ctx: ExportContext) -> bytes:
    specs = catalogue()
    files: dict[str, bytes] = {}
    warnings: list[str] = []
    sample = False
    for sid in PACK_REPORTS:
        spec = specs[sid]
        doc = await spec.build(ctx)
        sample = sample or doc.sample
        warnings += [f"{doc.title}: {w}" for w in doc.warnings]
        for fmt in ("csv", "pdf"):
            files[f"{sid}.{fmt}"] = writers.render(doc, fmt)
    vat_periods = []
    original = (ctx.start, ctx.end)
    try:
        for s, e in vat_spans(ctx.start, ctx.end, ctx.cycle.start_month, ctx.cycle.months, ctx.today):
            key = period_id(s, ctx.cycle.months)
            vat_periods.append(key)
            ctx.start, ctx.end = s, e
            for sid in ("vat-return", "vat-detail", "vat-digital-links"):
                doc = await specs[sid].build(ctx)
                warnings += [f"{key} {doc.title}: {w}" for w in doc.warnings]
                for fmt in ("csv", "pdf"):
                    files[f"vat/{key}/{sid}.{fmt}"] = writers.render(doc, fmt)
    finally:
        ctx.start, ctx.end = original
    files["ledger.json"] = (json.dumps(await ledger_json(ctx), indent=2, ensure_ascii=False) + "\n").encode()
    mappings = await ctx.mappings()
    accounts = chart(await ctx.events())
    for package in PACKAGES:
        if package == "freeagent":
            continue
        warnings += [
            f"{PACKAGES[package]}: {p}"
            for p in problems(resolve(package, a, mappings) for a in accounts)
            if p.startswith("Unmapped")
        ]
    names = ["README.txt", *sorted(files)]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", _readme(ctx, names, warnings, sample, vat_periods))
        for name in sorted(files):
            zf.writestr(name, files[name])
    return buf.getvalue()


async def build_pack_preview(ctx: ExportContext) -> ReportDoc:
    cols = columns(("file", "File"), ("what", "What it is"))
    specs = catalogue()
    rows = [Row(cells={"file": "README.txt", "what": "Period, basis, what to check and every file"})]
    rows += [Row(cells={"file": f"{sid}.csv, .pdf", "what": specs[sid].title}) for sid in PACK_REPORTS]
    spans = vat_spans(ctx.start, ctx.end, ctx.cycle.start_month, ctx.cycle.months, ctx.today)
    rows += [
        Row(
            cells={
                "file": f"vat/{period_id(s, ctx.cycle.months)}/",
                "what": f"VAT return, VAT detail and MTD digital links, {span_label(s, e)}",
            }
        )
        for s, e in spans
    ]
    rows.append(Row(cells={"file": "ledger.json", "what": "Every approved entry, open JSON"}))
    return doc_from(
        "accountant-pack",
        "Accountant pack",
        span_label(ctx.start, ctx.end),
        [Section(title="What is in the zip", columns=cols, rows=rows)],
        sample=rp.is_sample(await ctx.events()),
    )


def _package_zip(package: str):
    async def raw(ctx: ExportContext) -> bytes:
        buf = io.BytesIO()
        readme = [
            f"{PACKAGES[package]} import files from Accnomos, {span_label(ctx.start, ctx.end)}.",
            "",
            "Import journals OR invoices and bills for the same period, never both: both would count the same "
            "sales and costs twice.",
            "None of these files has been test-imported into the package.",
            "",
        ]
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for spec in catalogue().values():
                if spec.package != package:
                    continue
                doc = await spec.build(ctx)
                zf.writestr(f"{spec.id}.csv", writers.render(doc, "csv"))
                readme.append(
                    f"- {spec.id}.csv: {spec.title}. {doc.import_file.instructions if doc.import_file else ''}"
                )
                readme += [f"  {w}" for w in doc.warnings]
            zf.writestr("README.txt", "\n".join(readme) + "\n")
        return buf.getvalue()

    return raw


async def _package_preview_doc(ctx: ExportContext, package: str) -> ReportDoc:
    cols = columns(("file", "File"), ("what", "What it is"))
    rows = [Row(cells={"file": f"{s.id}.csv", "what": s.title}) for s in catalogue().values() if s.package == package]
    return doc_from(
        f"{package}-all",
        f"{PACKAGES[package]}: every file",
        span_label(ctx.start, ctx.end),
        [Section(title="What is in the zip", columns=cols, rows=rows)],
    )


def _package_preview(package: str):
    async def build(ctx: ExportContext) -> ReportDoc:
        return await _package_preview_doc(ctx, package)

    return build


register(
    ExportSpec(
        "accountant-pack",
        "pack",
        "Accountant pack",
        "TB, GL, balance sheet, P&L, aged, VAT returns and detail, contacts and a README, in one zip.",
        build_pack_preview,
        formats=("zip",),
        raw=raw_pack,
    )
)
register(
    ExportSpec(
        "ledger-json",
        "pack",
        "Ledger (open JSON)",
        "Every approved entry and its lines, documented, in integer pence.",
        build_ledger_preview,
        formats=("json",),
        params=(),
        raw=raw_ledger,
    )
)
register(
    ExportSpec(
        "contact-list",
        "payables",
        "Contact list",
        "Every customer and supplier with their details.",
        build_contacts,
        params=(),
    )
)
for _pkg in PACKAGES:
    register(
        ExportSpec(
            f"{_pkg}-all",
            "export",
            f"{PACKAGES[_pkg]}: every file (zip)",
            f"All the {PACKAGES[_pkg]} import files for the period, with a README.",
            _package_preview(_pkg),
            formats=("zip",),
            raw=_package_zip(_pkg),
            package=None,
        )
    )
