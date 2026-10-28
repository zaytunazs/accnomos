"""The chart of accounts: codes, names, types and default VAT codes, in `_System/Accounting/accounts.json`.

Ledger lines name an account as "<code> <name>" ("7500 Office supplies"), so that string is what a posting keeps for
ever. Hence the rules:

- a code never changes; a name can change only while nothing has been posted to the account (entries already
  posted carry the old name, and reports group by it);
- an account with postings is never deleted, only archived (it then stops being offered for new entries);
- the accounts code posts to by itself (debtors, creditors, bank, VAT control, sales, payroll, depreciation …) are
  `system` accounts: they can be renamed while unused but never archived or deleted;
- the type must fit the code range the reports use (app/reports.py places accounts by code): 0000–0999 fixed
  assets, 1000–1999 current assets and bank, 2000–2999 liabilities, 3000–3999 equity, 4000–4999 revenue,
  5000–5999 direct costs, 6000–8999 overheads. 9000–9999 is not used.

Until the user saves a change the file does not exist and the standard UK small-business chart below is shown.
Nothing here posts to the ledger.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, computed_field

from accnomos_ledger.events import LedgerEvent
from app.books import SYSTEM, Books, now
from app.journal import (
    BANK,
    CASH,
    CATEGORY_ACCOUNTS,
    CREDITORS,
    DEBTORS,
    OWNER_LOAN,
    PAYPAL_CLEARING,
    SALES,
    STRIPE_CLEARING,
    SUNDRY,
    VAT_CONTROL,
)
from app.validation import LENIENT, StrictBody

ACCOUNTING = f"{SYSTEM}/Accounting"
ACCOUNTS = f"{ACCOUNTING}/accounts.json"

AccountType = Literal[
    "fixed_asset", "current_asset", "bank", "current_liability", "equity", "revenue", "direct_costs", "overhead"
]
VatDefault = Literal["S", "R", "Z", "E", "O", "N"]
TYPE_LABELS: dict[str, str] = {
    "fixed_asset": "Fixed asset",
    "current_asset": "Current asset",
    "bank": "Bank",
    "current_liability": "Liability",
    "equity": "Equity",
    "revenue": "Revenue",
    "direct_costs": "Direct costs",
    "overhead": "Overhead",
}
RANGES: dict[str, tuple[int, int]] = {
    "fixed_asset": (0, 999),
    "current_asset": (1000, 1999),
    "bank": (1000, 1999),
    "current_liability": (2000, 2999),
    "equity": (3000, 3999),
    "revenue": (4000, 4999),
    "direct_costs": (5000, 5999),
    "overhead": (6000, 8999),
}
P_AND_L = {"revenue", "direct_costs", "overhead"}

DEPRECIATION = "8000 Depreciation"
DISPOSALS = "8010 Profit or loss on disposal of assets"
PAYROLL_LIABILITIES = "2210 Payroll liabilities"
WAGES = "7000 Gross wages"
EMPLOYER_NI = "7010 Employer's NI"
#: Accounts the code posts to by name: renaming or archiving them would break postings made by code.
SYSTEM_ACCOUNTS = frozenset(
    {
        BANK,
        CASH,
        STRIPE_CLEARING,
        PAYPAL_CLEARING,
        DEBTORS,
        CREDITORS,
        VAT_CONTROL,
        SALES,
        OWNER_LOAN,
        SUNDRY,
        PAYROLL_LIABILITIES,
        WAGES,
        EMPLOYER_NI,
        DEPRECIATION,
        DISPOSALS,
        *CATEGORY_ACCOUNTS.values(),
    }
)
#: Control accounts: other features keep their own detail behind them (invoices, bills, bank lines, the VAT return),
#: so manual journals and recodes stay off them.
CONTROL_ACCOUNTS = frozenset({DEBTORS, CREDITORS, VAT_CONTROL, PAYROLL_LIABILITIES})
_CODE = re.compile(r"^\d{4}$")


class Account(BaseModel):
    code: str = Field(pattern=r"^\d{4}$")
    name: str = Field(min_length=1, max_length=80)
    type: AccountType
    vat_default: VatDefault | None = None
    archived: bool = False
    system: bool = False
    description: str | None = Field(None, max_length=200)

    @computed_field
    @property
    def label(self) -> str:
        return f"{self.code} {self.name}"


def _a(label: str, type_: str, vat: str | None = None, description: str | None = None) -> Account:
    code, name = label.split(" ", 1)
    return Account(
        code=code,
        name=name,
        type=type_,  # type: ignore[arg-type]
        vat_default=vat,  # type: ignore[arg-type]
        system=label in SYSTEM_ACCOUNTS,
        description=description,
    )


def default_chart() -> list[Account]:
    """A standard UK small-business chart, using the codes Accnomos already posts to."""
    expenses = [
        _a(label, "direct_costs" if label < "6000" else "overhead", "S") for label in CATEGORY_ACCOUNTS.values()
    ]
    for a in expenses:
        if a.label in ("7310 Motor — mileage allowance", "7700 Insurance", "7900 Bank charges"):
            a.vat_default = "E"  # mileage allowance is not a supply; insurance and bank charges are exempt
    rows = [
        _a("0020 Plant and machinery", "fixed_asset", "S"),
        _a("0021 Plant and machinery depreciation", "fixed_asset"),
        _a("0030 Office equipment", "fixed_asset", "S"),
        _a("0031 Office equipment depreciation", "fixed_asset"),
        _a("0040 Motor vehicles", "fixed_asset", "S"),
        _a("0041 Motor vehicles depreciation", "fixed_asset"),
        _a("0050 Computer equipment", "fixed_asset", "S"),
        _a("0051 Computer equipment depreciation", "fixed_asset"),
        _a(DEBTORS, "current_asset", None, "Customers who owe you (sales invoices)"),
        _a(BANK, "bank"),
        _a(CASH, "bank"),
        _a(STRIPE_CLEARING, "current_asset", None, "Card payments taken through Stripe links, until Stripe pays out"),
        _a(PAYPAL_CLEARING, "current_asset", None, "Payments taken through PayPal links, until PayPal pays out"),
        _a("1300 Prepayments", "current_asset"),
        _a(CREDITORS, "current_liability", None, "Suppliers you owe (bills)"),
        _a(VAT_CONTROL, "current_liability", None, "VAT charged less VAT reclaimed"),
        _a(PAYROLL_LIABILITIES, "current_liability"),
        _a(OWNER_LOAN, "current_liability"),
        _a("2400 Accruals", "current_liability"),
        _a("3000 Capital", "equity"),
        _a("3100 Retained earnings", "equity"),
        _a("3200 Drawings", "equity"),
        _a(SALES, "revenue", "S"),
        _a("4900 Other income", "revenue", "S"),
        *expenses,
        _a("5200 Subcontractors", "direct_costs", "S"),
        _a(WAGES, "overhead"),
        _a(EMPLOYER_NI, "overhead"),
        _a(SUNDRY, "overhead", "S"),
        _a(DEPRECIATION, "overhead", None, "Book depreciation; capital allowances are worked out separately for tax"),
        _a(DISPOSALS, "overhead", None, "A gain shows as a negative overhead"),
    ]
    return sorted(rows, key=lambda a: a.code)


class ChartError(ValueError):
    """The chart cannot be changed as asked."""


def type_fits(code: str, type_: str) -> bool:
    lo, hi = RANGES[type_]
    return lo <= int(code) <= hi


def posting_counts(events: Iterable[LedgerEvent]) -> Counter[str]:
    """Account label -> how many ledger lines name it (every posted event, undone or not)."""
    return Counter(ln.account for e in events for ln in e.lines)


async def load_chart(books: Books) -> tuple[list[Account], bool]:
    """(accounts by code, whether the user has saved a chart). A hand-broken file raises ChartError."""
    raw = await books.read_json(ACCOUNTS, None)
    if raw is None:
        return default_chart(), False
    try:
        rows = [Account.model_validate(r, **LENIENT) for r in raw["accounts"]]
    except (KeyError, TypeError, ValidationError) as exc:
        raise ChartError(
            "The chart of accounts file could not be read; fix or remove _System/Accounting/accounts.json"
        ) from exc
    return sorted(rows, key=lambda a: a.code), True


async def save_chart(books: Books, accounts: list[Account], user: str, action: str, refs: dict) -> None:
    payload = {
        "accounts": [a.model_dump(mode="json") for a in sorted(accounts, key=lambda a: a.code)],
        "updated_by": user,
        "updated_at": now().isoformat(),
    }
    await books._update_json(ACCOUNTS, None, lambda _old: payload)
    await books.audit(f"user:{user}", action, refs)


def find(accounts: Iterable[Account], label_or_code: str) -> Account | None:
    """By "7500 Office supplies" or by "7500"."""
    code = label_or_code.strip()[:4]
    return next((a for a in accounts if a.code == code), None) if _CODE.match(code) else None


def active_account(accounts: Iterable[Account], label: str) -> Account:
    """The chart's account for a label typed on a journal or a recode; ChartError if unknown or archived."""
    a = find(accounts, label)
    if a is None:
        raise ChartError(f"{label.strip() or 'That account'} is not in your chart of accounts")
    if a.archived:
        raise ChartError(f"{a.label} is archived; restore it on the chart of accounts first")
    return a


class AccountIn(StrictBody):
    code: str = Field(pattern=r"^\d{4}$", max_length=4)
    name: str = Field(min_length=1, max_length=80)
    type: AccountType
    vat_default: VatDefault | None = None
    description: str | None = Field(None, max_length=200)


class AccountEdit(StrictBody):
    name: str | None = Field(None, min_length=1, max_length=80)
    type: AccountType | None = None
    vat_default: VatDefault | None = None
    clear_vat_default: bool = False
    description: str | None = Field(None, max_length=200)
    archived: bool | None = None


def _clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise ChartError("Give the account a name")
    return name


def add_account(accounts: list[Account], body: AccountIn) -> Account:
    if find(accounts, body.code):
        raise ChartError(f"Code {body.code} is already used by {find(accounts, body.code).label}")  # type: ignore[union-attr]
    if not type_fits(body.code, body.type):
        lo, hi = RANGES[body.type]
        raise ChartError(f"{TYPE_LABELS[body.type]} accounts use codes {lo:04d} to {hi:04d}")
    name = _clean_name(body.name)
    if any(a.name.casefold() == name.casefold() for a in accounts):
        raise ChartError(f"There is already an account called {name}")
    acc = Account(code=body.code, name=name, type=body.type, vat_default=body.vat_default, description=body.description)
    accounts.append(acc)
    return acc


def edit_account(accounts: list[Account], code: str, body: AccountEdit, postings: Counter[str]) -> Account:
    acc = find(accounts, code)
    if acc is None:
        raise FileNotFoundError(f"No account {code}")
    used = postings.get(acc.label, 0)
    if body.name is not None and _clean_name(body.name) != acc.name:
        if used:
            raise ChartError(
                f"{acc.label} has {used} posted line{'s' if used != 1 else ''}, which keep the name they were posted "
                "with. Add a new account and recode them to it instead."
            )
        new = _clean_name(body.name)
        if acc.system:
            raise ChartError(f"{acc.label} is one Accnomos posts to by itself, so its name stays")
        if any(a is not acc and a.name.casefold() == new.casefold() for a in accounts):
            raise ChartError(f"There is already an account called {new}")
        acc.name = new
    if body.type is not None and body.type != acc.type:
        if not type_fits(acc.code, body.type):
            lo, hi = RANGES[body.type]
            raise ChartError(f"{TYPE_LABELS[body.type]} accounts use codes {lo:04d} to {hi:04d}")
        acc.type = body.type
    if body.clear_vat_default:
        acc.vat_default = None
    elif body.vat_default is not None:
        acc.vat_default = body.vat_default
    if body.description is not None:
        acc.description = body.description.strip() or None
    if body.archived is not None:
        if body.archived and acc.system:
            raise ChartError(f"{acc.label} is one Accnomos posts to by itself, so it can't be archived")
        acc.archived = body.archived
    return acc


def delete_account(accounts: list[Account], code: str, postings: Counter[str]) -> Account:
    acc = find(accounts, code)
    if acc is None:
        raise FileNotFoundError(f"No account {code}")
    if acc.system:
        raise ChartError(f"{acc.label} is one Accnomos posts to by itself, so it can't be deleted")
    if postings.get(acc.label):
        raise ChartError(f"{acc.label} has postings, so it can't be deleted. Archive it instead.")
    accounts.remove(acc)
    return acc


CSV_COLUMNS = ("code", "name", "type", "vat_default", "archived", "description")


def to_csv(accounts: Iterable[Account]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNS)
    for a in accounts:
        name = a.name if not a.name.startswith(("=", "+", "-", "@")) else f"'{a.name}"
        w.writerow([a.code, name, a.type, a.vat_default or "", "yes" if a.archived else "no", a.description or ""])
    return buf.getvalue()


class ImportResult(BaseModel):
    added: list[str] = []
    updated: list[str] = []
    unchanged: int = 0
    errors: list[str] = []  # "Row 3: ..."; when there are any, nothing was saved


def import_csv(accounts: list[Account], text: str, postings: Counter[str]) -> ImportResult:
    """Add new codes and update existing ones (type, VAT default, archived, description; the name only while unused).
    All or nothing: any bad row and the chart is left as it was."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    fields = [f.strip().lower() for f in reader.fieldnames or []]
    if "code" not in fields or "name" not in fields or "type" not in fields:
        return ImportResult(errors=["The first row must name the columns, with at least code, name and type"])
    result = ImportResult()
    work = [a.model_copy() for a in accounts]
    seen: set[str] = set()
    for n, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not any(row.values()):
            continue
        code = row.get("code", "").zfill(4) if row.get("code", "").isdigit() else row.get("code", "")
        type_ = row.get("type", "").lower().replace(" ", "_")
        type_ = {label.lower().replace(" ", "_"): key for key, label in TYPE_LABELS.items()}.get(type_, type_)
        vat = row.get("vat_default", "").upper() or None
        archived = row.get("archived", "").lower() in ("yes", "true", "1", "y")
        name = row.get("name", "").removeprefix("'")
        try:
            if code in seen:
                raise ChartError(f"code {code} is in the file twice")
            seen.add(code)
            existing = find(work, code) if _CODE.match(code) else None
            if existing is None:
                acc = add_account(
                    work,
                    AccountIn.model_validate(
                        {
                            "code": code,
                            "name": name,
                            "type": type_,
                            "vat_default": vat,
                            "description": row.get("description") or None,
                        }
                    ),
                )
                acc.archived = archived
                result.added.append(acc.label)
            else:
                before = existing.model_dump()
                edit_account(
                    work,
                    code,
                    AccountEdit.model_validate(
                        {
                            "name": name or None,
                            "type": type_,
                            "vat_default": vat,
                            "clear_vat_default": vat is None,
                            "description": row.get("description", ""),
                            **({"archived": archived} if "archived" in row and row["archived"] else {}),
                        }
                    ),
                    postings,
                )
                if existing.model_dump() != before:
                    result.updated.append(existing.label)
                else:
                    result.unchanged += 1
        except ChartError as exc:
            result.errors.append(f"Row {n}: {exc}")
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(x) for x in first["loc"])
            result.errors.append(f"Row {n}: {where}: {first['msg']}")
    if not result.errors:
        accounts[:] = work
    else:
        result.added, result.updated, result.unchanged = [], [], 0
    return result
