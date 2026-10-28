"""The books' accounts and VAT codes -> each accounting package's own, with the user's changes saved in
_System/exports/mappings.json.

Each account resolves, in order, to: the user's choice (quality "user"); a default for its exact code ("default":
the package's own standard UK account, from the sources below); a default for its code range ("suggested": a best
fit, worth a look); the books' own code and name, created in the package by our chart-of-accounts file ("own",
QuickBooks and Sage Accounting only); or nothing ("unmapped", flagged in every preview and in the Accountant pack).
"check" marks a default that only the user can complete, such as which bank account in the package is theirs.

Sources for the package defaults (checked 28 October 2026):
- Xero UK default chart (codes, names, tax rates): tenpercentfinancial.co.uk/list-of-nominal-codes-for-xero/
  (2019) and linggardandthomas.co.uk/blog/xero-chart-of-accounts-cheat-sheet (Sept 2026), which agree on every
  code used here. Xero's own Central pages are behind a login.
- QuickBooks Online UK: Debtors and Creditors are created by QuickBooks ("Choosing the right account types in
  QuickBooks", quickbooks.intuit.com/learn-support/en-uk/help-article/chart-accounts/understanding-detail-types-
  quickbooks-online/L9IuTxhDc_GB_en_GB); VAT codes 20.0% S, 5.0% R, 0.0% Z ("Understanding VAT codes in
  QuickBooks", .../en-uk/help-article/value-added-tax/understanding-vat-codes-quickbooks/L9v5htbsT_GB_en_GB),
  Exempt and No VAT (support.zed-systems.com kb a262, expenseflow.ai tax-codes-uk-quickbooks.csv).
- Sage 50 UK default nominal codes: numericsolutions.co.uk "Sage Default Nominal Codes for a Limited Company"
  (v26) and gb-kb.sage.com solution 200427112546692 (default control accounts); tax codes T0/T1/T2/T5/T9 from
  Sage 50 Accounts help, "Tax codes for UK users".
- Sage Accounting control accounts: gb-kb.sage.com solution 222001000100121 ("Import your chart of accounts").
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel

from app.books import Books
from app.exports.accounts import split_account
from app.paths import SYSTEM
from app.reports import account_code

MAPPINGS = f"{SYSTEM}/exports/mappings.json"
Package = Literal["xero", "qbo", "sage50", "sage-accounting", "freeagent"]
PACKAGES: dict[str, str] = {
    "xero": "Xero",
    "qbo": "QuickBooks Online",
    "sage50": "Sage 50",
    "sage-accounting": "Sage Accounting",
    "freeagent": "FreeAgent",
}
Quality = Literal["user", "default", "suggested", "check", "own", "unmapped"]


class Target(BaseModel):
    code: str = ""
    name: str = ""


class Mapped(Target):
    account: str  # the books' account, "7500 Office supplies"
    quality: Quality
    note: str = ""


# Exact-code defaults: package -> books' code -> (code, name, quality, note)
_D = tuple[str, str, Quality, str]
XERO: dict[int, _D] = {
    1100: ("610", "Accounts Receivable", "default", ""),
    1200: (
        "090",
        "Business Bank Account",
        "check",
        "Use the code of your bank account in Xero. Xero may not take bank "
        "accounts on manual journals: bring bank lines in with the bank statement file instead.",
    ),
    1210: ("", "", "check", "Choose the Xero account you keep cash in (create one if needed)."),
    2100: ("800", "Accounts Payable", "default", ""),
    2200: ("820", "VAT", "default", ""),
    2210: ("825", "PAYE Payable", "suggested", "Split NI to 826 NIC Payable if your payroll does."),
    2300: ("835", "Directors' Loan Account", "default", ""),
    3200: ("960", "Retained Earnings", "default", ""),
    4000: ("200", "Sales", "default", ""),
    5000: ("310", "Cost of Goods Sold", "default", ""),
    5100: ("310", "Cost of Goods Sold", "suggested", ""),
    6200: ("400", "Advertising & Marketing", "default", ""),
    7000: ("477", "Salaries", "default", ""),
    7010: ("479", "Employers National Insurance", "default", ""),
    7020: ("482", "Pensions Costs", "suggested", ""),
    7100: ("469", "Rent", "default", ""),
    7200: ("445", "Light, Power, Heating", "default", ""),
    7300: ("449", "Motor Vehicle Expenses", "default", ""),
    7310: ("449", "Motor Vehicle Expenses", "suggested", "Mileage allowance."),
    7400: ("493", "Travel - National", "default", ""),
    7410: ("493", "Travel - National", "suggested", "Subsistence."),
    7500: ("461", "Printing & Stationery", "default", ""),
    7510: ("463", "IT Software and Consumables", "default", ""),
    7520: ("425", "Postage, Freight & Courier", "default", ""),
    7550: ("489", "Telephone & Internet", "default", ""),
    7600: ("412", "Consulting", "suggested", "Or 401 Audit & Accountancy fees, 441 Legal Expenses."),
    7700: ("433", "Insurance", "default", ""),
    7900: ("404", "Bank Fees", "default", ""),
    7999: ("429", "General Expenses", "default", ""),
}
XERO_RANGES: tuple[tuple[range, _D], ...] = (
    (range(4000, 5000), ("260", "Other Revenue", "suggested", "")),
    (range(5000, 6000), ("310", "Cost of Goods Sold", "suggested", "")),
    (range(6000, 9000), ("429", "General Expenses", "suggested", "")),
    (range(3000, 4000), ("970", "Owner A Funds Introduced", "suggested", "")),
)
SAGE50: dict[int, _D] = {
    1100: ("1100", "Debtors Control Account", "default", ""),
    1200: ("1200", "Bank Current Account", "default", ""),
    1210: ("1230", "Petty Cash", "default", "Sage's 1210 is the Bank Deposit Account, not cash."),
    2100: ("2100", "Creditors Control Account", "default", ""),
    2200: (
        "2202",
        "VAT Liability",
        "suggested",
        "The books keep one VAT account; Sage splits sales (2200) and purchase "
        "(2201) tax. Journals carry no tax code, so they land on VAT Liability.",
    ),
    2210: ("2210", "P.A.Y.E.", "default", "Split employer and employee NI to 2211 National Insurance if needed."),
    2300: ("2301", "Directors Loan Accounts (Director 1)", "suggested", ""),
    3200: ("3200", "Profit and Loss Account", "default", ""),
    4000: ("4000", "Sales Type A", "default", ""),
    5000: ("5000", "Materials Purchased", "default", ""),
    5100: ("5002", "Miscellaneous Purchases", "suggested", "Tools and small equipment."),
    6200: ("6201", "Advertising", "default", ""),
    7000: ("7000", "Gross Wages", "default", ""),
    7010: ("7006", "Employers N.I. (Non-Directors)", "suggested", "Directors' NI is 7012."),
    7020: ("7007", "Employers Pensions", "suggested", ""),
    7100: ("7100", "Rent", "default", ""),
    7200: ("7200", "Electricity", "suggested", "Gas is 7201."),
    7300: ("7304", "Miscellaneous Motor Expenses", "suggested", "Sage's 7300 is Fuel and Oil."),
    7310: ("7306", "Mileage Claims", "default", ""),
    7400: ("7400", "Travelling", "default", ""),
    7410: ("7406", "Subsistence", "default", ""),
    7500: ("7502", "Office Stationery", "default", ""),
    7510: ("7552", "Computers & Software", "default", ""),
    7520: ("7501", "Postage and Carriage", "default", ""),
    7550: ("7550", "Telephone and Fax", "default", ""),
    7600: ("7604", "Professional Fees", "default", ""),
    7700: ("8204", "Insurance", "default", ""),
    7900: ("7901", "Bank Charges", "default", ""),
    7999: ("8250", "Sundry Expenses", "default", ""),
}
SAGE50_RANGES: tuple[tuple[range, _D], ...] = (
    (range(4000, 5000), ("4900", "Miscellaneous Income", "suggested", "")),
    (range(5000, 6000), ("5002", "Miscellaneous Purchases", "suggested", "")),
    (range(6000, 9000), ("8250", "Sundry Expenses", "suggested", "")),
)
SAGE_ACCOUNTING: dict[int, _D] = {
    1100: ("1100", "Trade Debtors", "default", ""),
    2100: ("2100", "Trade Creditors", "default", ""),
    2200: ("2202", "VAT liability", "suggested", "Sage Accounting splits VAT on sales (2200) and purchases (2201)."),
    2210: ("2210", "PAYE to pay to HMRC", "default", "NIC is 2220."),
    3200: ("3100", "Profit and Loss Account", "default", ""),
    7000: ("7000", "Employee Wages and Salaries", "default", ""),
    7010: ("7020", "Employers NI", "default", ""),
    7020: ("7030", "Employer's Pension", "default", ""),
    7900: ("7900", "Bank Charges and Interest", "default", ""),
}
#: Sage Accounting control-account text (CONTROL ACCOUNT column) for the codes above.
SAGE_ACCOUNTING_CONTROL: dict[str, str] = {
    "1100": "TRADE_DEBTORS",
    "2100": "TRADE_CREDITORS",
    "2200": "TAX_ON_SALES",
    "2201": "TAX_ON_PURCHASES",
    "2202": "TAX_LIABILITY",
    "2210": "PAYE",
    "3100": "PROFIT_AND_LOSS",
    "7000": "EMPLOYEE_COSTS",
    "7020": "EMPLOYERS_NIC",
    "7030": "EMPLOYERS_PENSION",
    "7900": "BANK_CHARGES_AND_INTEREST",
}
QBO: dict[int, _D] = {
    1100: ("", "Debtors", "default", "QuickBooks creates its own Debtors account."),
    2100: ("", "Creditors", "default", "QuickBooks creates its own Creditors account."),
    1200: ("", "", "check", "Choose the bank account you set up in QuickBooks."),
}
DEFAULTS: dict[str, tuple[dict[int, _D], tuple[tuple[range, _D], ...]]] = {
    "xero": (XERO, XERO_RANGES),
    "sage50": (SAGE50, SAGE50_RANGES),
    "sage-accounting": (SAGE_ACCOUNTING, ()),
    "qbo": (QBO, ()),
    "freeagent": ({}, ()),
}
#: Packages that import the books' own chart, so an account with no default keeps its own code and name.
OWN_CHART = {"qbo", "sage-accounting"}

# VAT codes (the ledger's S, R, Z, E, O, N) -> the package's tax rate name, for sales and for purchases.
VatSide = Literal["sales", "purchases"]
VAT: dict[str, dict[VatSide, dict[str, str]]] = {
    "xero": {
        "sales": {
            "S": "20% (VAT on Income)",
            "R": "5% (VAT on Income)",
            "Z": "Zero Rated Income",
            "E": "Exempt Income",
            "O": "No VAT",
            "N": "No VAT",
        },
        "purchases": {
            "S": "20% (VAT on Expenses)",
            "R": "5% (VAT on Expenses)",
            "Z": "Zero Rated Expenses",
            "E": "Exempt Expenses",
            "O": "No VAT",
            "N": "No VAT",
        },
    },
    "qbo": {
        "sales": {"S": "20.0% S", "R": "5.0% R", "Z": "0.0% Z", "E": "Exempt", "O": "No VAT", "N": "No VAT"},
        "purchases": {"S": "20.0% S", "R": "5.0% R", "Z": "0.0% Z", "E": "Exempt", "O": "No VAT", "N": "No VAT"},
    },
    "sage50": {
        "sales": {"S": "T1", "R": "T5", "Z": "T0", "E": "T2", "O": "T9", "N": "T9"},
        "purchases": {"S": "T1", "R": "T5", "Z": "T0", "E": "T2", "O": "T9", "N": "T9"},
    },
    "sage-accounting": {
        "sales": {"S": "Standard", "R": "Lower", "Z": "Zero", "E": "Exempt", "O": "No VAT", "N": "No VAT"},
        "purchases": {"S": "Standard", "R": "Lower", "Z": "Zero", "E": "Exempt", "O": "No VAT", "N": "No VAT"},
    },
    "freeagent": {
        "sales": {"S": "20", "R": "5", "Z": "0", "E": "0", "O": "0", "N": "0"},
        "purchases": {"S": "20", "R": "5", "Z": "0", "E": "0", "O": "0", "N": "0"},
    },
}
#: What a journal line carries as its tax code: none. The VAT on these entries is already on the returns Accnomos
#: worked out, so a journal must not put it on the new package's VAT return a second time.
JOURNAL_TAX = {"xero": "No VAT", "qbo": "", "sage50": "T9", "sage-accounting": "No", "freeagent": ""}
RATES = {"S": 20, "R": 5, "Z": 0, "E": 0, "O": 0, "N": 0}


class Mappings(BaseModel):
    """User overrides only: package -> books' account -> target (None in a PUT removes one)."""

    version: int = 1
    accounts: dict[str, dict[str, Target]] = {}


async def load_mappings(books: Books) -> Mappings:
    raw = await books.read_json(MAPPINGS, None)
    if not isinstance(raw, dict):
        return Mappings()
    try:
        return Mappings.model_validate(raw)
    except ValueError:  # a hand-edited file that no longer parses: defaults, never a crash
        return Mappings()


async def save_mappings(books: Books, package: str, changes: dict[str, Target | None]) -> Mappings:
    def change(raw: Any) -> Any:
        try:
            current = Mappings.model_validate(raw) if isinstance(raw, dict) else Mappings()
        except ValueError:
            current = Mappings()
        mine = dict(current.accounts.get(package, {}))
        for account, target in changes.items():
            if target is None or not (target.code or target.name):
                mine.pop(account, None)
            else:
                mine[account] = target
        current.accounts[package] = dict(sorted(mine.items()))
        return json.loads(current.model_dump_json())

    await books._update_json(MAPPINGS, {}, change)
    return await load_mappings(books)


def resolve(package: str, account: str, mappings: Mappings) -> Mapped:
    user = mappings.accounts.get(package, {}).get(account)
    if user is not None and (user.code or user.name):
        return Mapped(account=account, code=user.code, name=user.name, quality="user")
    code = account_code(account)
    exact, ranges = DEFAULTS.get(package, ({}, ()))
    if code is not None:
        if code in exact:
            c, n, q, note = exact[code]
            return Mapped(account=account, code=c, name=n, quality=q, note=note)
        for r, (c, n, q, note) in ranges:
            if code in r:
                return Mapped(account=account, code=c, name=n, quality=q, note=note)
        if package in OWN_CHART:
            own_code, own_name = split_account(account)
            return Mapped(
                account=account,
                code=own_code,
                name=own_name,
                quality="own",
                note="Created in the package by the chart of accounts file.",
            )
    return Mapped(account=account, quality="unmapped", note="Choose an account in the package for this one.")


def resolve_all(package: str, accounts: Iterable[str], mappings: Mappings) -> list[Mapped]:
    return [resolve(package, a, mappings) for a in accounts]


def vat_name(package: str, side: VatSide, code: str | None) -> str:
    return VAT[package][side].get(code or "O", VAT[package][side]["O"])


def problems(mapped: Iterable[Mapped]) -> list[str]:
    """One warning line per account the user must look at before importing."""
    out = []
    for m in mapped:
        if m.quality == "unmapped":
            out.append(
                f"Unmapped: {m.account} (choose an account on the Mapping tab; until then it keeps its own code)."
            )
        elif m.quality == "check":
            to = " ".join(p for p in (m.code, m.name) if p)
            out.append(f"Check: {m.account}{f' -> {to}' if to else ''}. {m.note}".strip())
    return out


def target_code(m: Mapped) -> str:
    """The code to write: the mapped one, else the books' own (an unmapped account must still import somewhere)."""
    return m.code or split_account(m.account)[0] or m.account


def target_name(m: Mapped) -> str:
    return m.name or split_account(m.account)[1]
