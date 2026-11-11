"""File it yourself: the figures as files an owner uploads to bridging or MTD software, or types into HMRC's own
Self Assessment form, when Accnomos cannot file them to HMRC itself. Pure functions; nothing here reads storage.

Three files, each as CSV and XLSX (one sheet, the same cells in both):

* **VAT bridging file** (`vat_bridging`). Since 1 November 2022 a VAT return cannot be typed into HMRC's online VAT
  account; it goes through MTD software or bridging software (VAT Notice 700/22, exemptions aside). Bridging tools
  have no standard layout: they let the user map cells, or take a column of the nine values. So the layout is fixed
  and documented here and in docs/howto/vat-return.md:

      A1:A9   box numbers 1-9          B1:B9   the nine values (B1:B5 pounds and pence, B6:B9 whole pounds)
      C1:C9   HMRC's box headings      D1:D9   the VAT (MTD) API field for each box
      A10:B10 Period start (ISO date)  A11:B11 Period end   A12:B12 Period key   A13:B13 VAT registration number
      A14:B14 what box 5 means (to pay, to reclaim, nothing)

  No header row, so a tool that asks "which column holds the nine boxes" gets B1:B9 and nothing else. Uploading the
  file is a digital link; copying or retyping the numbers is not (VAT Notice 700/22 paragraph 3.2.1).

  QuickBooks Online's bridging upload takes a CSV of the nine final values, but Intuit's page
  (quickbooks.intuit.com/uk/making-tax-digital/bridging-software/, checked 11 Nov 2026) documents no column or cell
  layout and offers no template, so no QuickBooks-specific file is made: the plain file above is the one to map.

* **Income Tax quarterly figures** (`itsa_quarterly`). MTD for Income Tax has no HMRC web form: quarterly updates go
  through HMRC-recognised MTD software or bridging software. The figures are cumulative from 6 April, under the
  Self-Employment Business API 5.0 field names (app/itsa.py), each with its SA103F box.

* **Annual Self Assessment pages** (`sa103`). People not in MTD for Income Tax can still type their return into
  HMRC's online Self Assessment. SA103S (turnover under £90,000) or SA103F, 2025-26 forms (SA103S-2026.pdf and
  SA103F_2026.pdf on gov.uk, checked 11 Nov 2026).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from openpyxl import Workbook
from openpyxl.styles import Font

from app.itsa import BY_KEY, FIELDS, SeSummary

Cell = str | int | Decimal | None
FileFormat = Literal["csv", "xlsx"]
MEDIA = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

#: Said wherever live filing from Accnomos is off. The web page and the docs use the same sentence.
PLANNED = "Filing to HMRC from Accnomos is planned."
#: £90,000: the VAT registration threshold, the SA103S limit (SA103S notes 2026: "Fill in the 'Self-employment
#: (short)' pages if your turnover was less than £90,000") and the consolidatedExpenses limit in the MTD API.
SHORT_LIMIT_PENCE = 90_000_00
PENNY = Decimal("0.01")


@dataclass
class Sheet:
    """One sheet: `rows` are the cells from A1 down, `money` the (row, column) cells (1-based) that hold pounds and
    pence, `whole` those that hold whole pounds. CSV and XLSX carry exactly the same cells."""

    kind: str
    title: str  # the sheet's name, also the file's title
    filename: str  # without extension
    rows: list[list[Cell]]
    guidance: list[str]
    layout: list[str]  # where each thing is, in words, for the page and the docs
    money: set[tuple[int, int]] = field(default_factory=set)
    whole: set[tuple[int, int]] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)  # facts the page shows (form chosen, eligibility, ...)

    def as_json(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "filename": self.filename,
            "rows": [[_json(v) for v in r] for r in self.rows],
            "guidance": self.guidance,
            "layout": self.layout,
            "warnings": self.warnings,
            **self.extra,
        }


def _json(v: Cell) -> str | int | float | None:
    return float(v) if isinstance(v, Decimal) else v


def pounds(pence: int) -> Decimal:
    """Integer pence -> Decimal pounds to 2 dp, exactly."""
    return (Decimal(pence) / 100).quantize(PENNY)


def whole_pounds(pence: int) -> int:
    """Pence dropped, towards zero (as the VAT boxes 6-9 and HMRC's own whole-pound boxes take them)."""
    return int((Decimal(pence) / 100).to_integral_value(rounding=ROUND_DOWN))


# --------------------------------------------------------------------------------------------------------------
# VAT bridging file
# --------------------------------------------------------------------------------------------------------------

#: Box -> HMRC VAT (MTD) API field (POST /organisations/vat/{vrn}/returns).
VAT_FIELDS: tuple[tuple[int, str], ...] = (
    (1, "vatDueSales"),
    (2, "vatDueAcquisitions"),
    (3, "totalVatDue"),
    (4, "vatReclaimedCurrPeriod"),
    (5, "netVatDue"),
    (6, "totalValueSalesExVAT"),
    (7, "totalValuePurchasesExVAT"),
    (8, "totalValueGoodsSuppliedExVAT"),
    (9, "totalAcquisitionsExVAT"),
)
VAT_GUIDANCE = [
    "Upload this file to your bridging software and let it read the cells: B1 to B9 hold boxes 1 to 9.",
    "Don't retype or copy and paste the numbers. HMRC's digital-links rule (VAT Notice 700/22) counts a file "
    "exported and uploaded as a digital link; copying or retyping figures is not one.",
    "A VAT return can't be typed into your HMRC online VAT account: since 1 November 2022 it has to go through "
    "Making Tax Digital software or bridging software, unless HMRC has given you an exemption.",
    "Boxes 1 to 5 are pounds and pence; boxes 6 to 9 are whole pounds with the pence dropped. Box 5 is never "
    "negative: row 14 says whether it is to pay or to reclaim.",
    "Your bridging software gets the period key from HMRC when you pick the period; check it matches row 12.",
]
VAT_LAYOUT = [
    "One sheet, no header row.",
    "A1:A9 box numbers 1 to 9; B1:B9 the values; C1:C9 HMRC's box headings; D1:D9 the HMRC API field names.",
    "B1:B5 pounds and pence (2 decimal places); B6:B9 whole pounds.",
    "Row 10 period start, row 11 period end (both YYYY-MM-DD), row 12 period key, row 13 VAT registration "
    "number, row 14 what box 5 means. Labels in column A, values in column B.",
]


def vat_bridging(
    amounts: dict[int, str],
    labels: dict[int, str],
    start: date,
    end: date,
    period_key: str,
    vrn: str | None,
    direction: Literal["pay", "reclaim", "nil"],
) -> Sheet:
    """`amounts` are the runtime's box amounts as HMRC receives them (app/routes_vat.py `box_amounts`: "1234.56" for
    boxes 1-5, "1234" for 6-9). They are checked again here, so a file can never carry a box HMRC would refuse."""
    values: dict[int, Decimal | int] = {}
    warnings: list[str] = []
    for box, _ in VAT_FIELDS:
        raw = Decimal(str(amounts.get(box, "0")))
        if box <= 5:
            values[box] = raw.quantize(PENNY)
            if values[box] != raw:
                warnings.append(f"Box {box} had more than 2 decimal places; it was rounded to the penny.")
        else:
            values[box] = int(raw.to_integral_value(rounding=ROUND_DOWN))
    box5 = abs(Decimal(values[3]) - Decimal(values[4]))
    if Decimal(values[5]) != box5:
        warnings.append("Box 5 did not equal box 3 minus box 4 without its sign; it was set to that.")
        values[5] = box5
    if Decimal(values[3]) != Decimal(values[1]) + Decimal(values[2]):
        warnings.append("Box 3 is not box 1 plus box 2: check the return on the VAT page before you upload it.")
    rows: list[list[Cell]] = [[box, values[box], labels[box], api] for box, api in VAT_FIELDS]
    meaning = {"pay": "To pay HMRC", "reclaim": "To reclaim from HMRC", "nil": "Nothing to pay or reclaim"}[direction]
    rows += [
        ["Period start", start.isoformat(), None, "periodStart"],
        ["Period end", end.isoformat(), None, "periodEnd"],
        ["Period key", period_key, None, "periodKey"],
        ["VAT registration number", vrn or None, None, "vrn"],
        ["Box 5 is", meaning, None, None],
    ]
    if not vrn:
        warnings.append("No VAT registration number was given, so B13 is empty. Add it in Settings › Business.")
    return Sheet(
        kind="vat-bridging",
        title="VAT return",
        filename=f"vat-bridging-{period_key.replace('#', '')}-{start.isoformat()}-to-{end.isoformat()}",
        rows=rows,
        guidance=VAT_GUIDANCE,
        layout=VAT_LAYOUT,
        money={(r, 2) for r in range(1, 6)},
        whole={(r, 2) for r in range(6, 10)},
        warnings=warnings,
        extra={"quickbooks_csv": False, "quickbooks_note": QUICKBOOKS_NOTE},
    )


QUICKBOOKS_NOTE = (
    "QuickBooks Online's bridging upload takes the nine final values as a CSV, but Intuit doesn't publish its column "
    "layout, so there is no QuickBooks-specific file: map B1 to B9 of this file to boxes 1 to 9 when QuickBooks asks."
)


# --------------------------------------------------------------------------------------------------------------
# Income Tax: quarterly figures (cumulative from 6 April)
# --------------------------------------------------------------------------------------------------------------

ITSA_GUIDANCE = [
    "Upload this file into HMRC-recognised Making Tax Digital software or bridging software: HMRC has no web form "
    "for quarterly updates.",
    "The figures are cumulative: 6 April to the end of the quarter. Each update replaces the one before it, so send "
    "the whole year so far, not just the last three months.",
    "Column A is the HMRC field name each figure goes to; column D is the SA103F box it ends up in.",
    "Don't retype the numbers: map the cells in your software so they stay digitally linked to your records.",
]
ITSA_LAYOUT = [
    "Row 1 headings: HMRC field, Value (£), Description, SA103F box, Group.",
    "Rows 2-4 periodIncome; rows 5-19 periodExpenses (all expenses in each category, allowable and disallowable); "
    "rows 20-34 periodDisallowableExpenses (the part of each category that can't be claimed).",
    "Row 36 consolidatedExpenses, an alternative to rows 5-34 for turnover under £90,000: send one or the other.",
    "Rows 38 onwards: tax year, period dates, accounting basis and eligibility, labels in column A, values in B.",
]
ITSA_HEAD: list[Cell] = ["HMRC field", "Value (£)", "Description", "SA103F box", "Group"]


def consolidated_eligible(turnover_pence: int) -> bool:
    return turnover_pence < SHORT_LIMIT_PENCE


def itsa_quarterly(s: SeSummary, business: str | None = None) -> Sheet:
    by_key = {f.key: f for f in s.figures}
    rows: list[list[Cell]] = [list(ITSA_HEAD)]
    money: set[tuple[int, int]] = set()

    def add(row: list[Cell]) -> None:
        rows.append(row)
        if isinstance(row[1], Decimal):
            money.add((len(rows), 2))

    for f in FIELDS:
        if f.group == "income":
            add([f"periodIncome.{f.key}", pounds(by_key[f.key].pence), f.label, str(f.box), "periodIncome"])
    add(
        [
            "periodIncome.taxTakenOffTradingIncome",
            None,
            "Tax taken off trading income (Accnomos doesn't record it: add it in your software if you had any)",
            None,
            "periodIncome",
        ]
    )
    for f in FIELDS:
        if f.group == "expenses":
            add([f"periodExpenses.{f.key}", pounds(by_key[f.key].pence), f.label, str(f.box), "periodExpenses"])
    for f in FIELDS:
        if f.group == "expenses":
            add(
                [
                    f"periodDisallowableExpenses.{f.key}Disallowable",
                    pounds(by_key[f.key].disallowable_pence),
                    f"{f.label}: disallowable part",
                    str(f.disallowable_box),
                    "periodDisallowableExpenses",
                ]
            )
    turnover = by_key["turnover"].pence
    eligible = consolidated_eligible(turnover)
    rows.append([])
    add(
        [
            "periodExpenses.consolidatedExpenses",
            pounds(s.allowable_pence),
            "All allowable expenses as one figure (instead of rows 5-34)"
            + ("" if eligible else ": not for you, turnover is £90,000 or more"),
            "17-30",
            "periodExpenses (alternative)",
        ]
    )
    rows.append([])
    meta: list[list[Cell]] = [
        ["Tax year", s.tax_year],
        ["Period start", s.period_start.isoformat()],
        ["Period end", s.period_end.isoformat()],
        ["Accounting basis", s.basis_label],
        ["Turnover so far (£)", pounds(turnover)],
        ["Consolidated expenses allowed", "yes" if eligible else "no"],
    ]
    if business:
        meta.insert(0, ["Business", business])
    for m in meta:
        add([*m, None, None, None])
    warnings = list(s.warnings) + list(s.blockers)
    if eligible:
        warnings.append(
            "Turnover so far is under £90,000, so you may send consolidatedExpenses (row 36) instead of the itemised "
            "expenses. If your turnover for the whole year will be £90,000 or more, itemise."
        )
    return Sheet(
        kind="itsa-quarterly",
        title="Quarterly update",
        filename=f"income-tax-quarterly-{s.tax_year}-6-apr-to-{s.period_end.isoformat()}",
        rows=rows,
        guidance=ITSA_GUIDANCE,
        layout=ITSA_LAYOUT,
        money=money,
        warnings=warnings,
        extra={
            "tax_year": s.tax_year,
            "period_start": s.period_start.isoformat(),
            "period_end": s.period_end.isoformat(),
            "consolidated_eligible": eligible,
            "turnover": float(pounds(turnover)),
        },
    )


# --------------------------------------------------------------------------------------------------------------
# Annual Self Assessment: SA103S / SA103F
# --------------------------------------------------------------------------------------------------------------

Form = Literal["short", "full"]
FormChoice = Literal["auto", "short", "full"]

#: SA103S 2025-26 (SA103S-2026.pdf): expense box -> the API fields whose ALLOWABLE part goes in it. The short form
#: asks for allowable expenses only; client entertainment and depreciation are never allowable (app/itsa.py).
SHORT_EXPENSES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("11", "Costs of goods bought for resale or goods used", ("costOfGoods",)),
    ("12", "Car, van and travel expenses – after private use proportion", ("carVanTravelExpenses",)),
    ("13", "Wages, salaries and other staff costs", ("wagesAndStaffCosts",)),
    ("14", "Rent, rates, power and insurance costs", ("premisesRunningCosts",)),
    ("15", "Repairs and maintenance of property and equipment", ("maintenanceCosts",)),
    ("16", "Accountancy, legal and other professional fees", ("professionalFees",)),
    ("17", "Interest and bank and credit card financial charges", ("interestOnBankOtherLoans", "financeCharges")),
    ("18", "Phone, fax, stationery and other office costs", ("adminCosts",)),
    (
        "19",
        "Other allowable business expenses – client entertaining costs are not an allowable expense",
        (
            "paymentsToSubcontractors",
            "advertisingCosts",
            "businessEntertainmentCosts",
            "irrecoverableDebts",
            "depreciation",
            "otherExpenses",
        ),
    ),
)
#: SA103F 2025-26 (SA103F_2026.pdf): box -> API fields (box 24 is advertising and business entertainment together).
FULL_EXPENSES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("17", "Cost of goods bought for resale or goods used", ("costOfGoods",)),
    ("18", "Construction industry – payments to subcontractors", ("paymentsToSubcontractors",)),
    ("19", "Wages, salaries and other staff costs", ("wagesAndStaffCosts",)),
    ("20", "Car, van and travel expenses", ("carVanTravelExpenses",)),
    ("21", "Rent, rates, power and insurance costs", ("premisesRunningCosts",)),
    ("22", "Repairs and maintenance of property and equipment", ("maintenanceCosts",)),
    ("23", "Phone, fax, stationery and other office costs", ("adminCosts",)),
    ("24", "Advertising and business entertainment costs", ("advertisingCosts", "businessEntertainmentCosts")),
    ("25", "Interest on bank and other loans", ("interestOnBankOtherLoans",)),
    ("26", "Bank, credit card and other financial charges", ("financeCharges",)),
    ("27", "Irrecoverable debts written off", ("irrecoverableDebts",)),
    ("28", "Accountancy, legal and other professional fees", ("professionalFees",)),
    ("29", "Depreciation and loss or profit on sale of assets", ("depreciation",)),
    ("30", "Other business expenses", ("otherExpenses",)),
)
SA_HEAD: list[Cell] = ["Box", "Description", "£ and pence", "Whole £", "HMRC field"]
SA_GUIDANCE = [
    "If you're not in Making Tax Digital for Income Tax, you can type these boxes into HMRC's online Self "
    "Assessment return, on the self-employment pages.",
    "Column D is each box in whole pounds with the pence dropped; totals in column D are added up from the boxes "
    "above them, so they agree with what you type.",
    "Accnomos doesn't work out capital allowances, balancing charges, goods taken for your own use, losses brought "
    "forward or tax adjustments: those boxes are listed empty for you to fill in.",
    "If you're in Making Tax Digital for Income Tax, your return goes through MTD software instead, not this form.",
]


def choose_form(turnover_pence: int, choice: FormChoice = "auto") -> Form:
    if choice != "auto":
        return choice
    return "short" if turnover_pence < SHORT_LIMIT_PENCE else "full"


def sa103(s: SeSummary, choice: FormChoice = "auto", business: str | None = None) -> Sheet:
    """Box by box for the SA103S or SA103F, from the same cumulative figures as the quarterly updates (normally the
    whole tax year, 6 April to 5 April)."""
    by_key = {f.key: f for f in s.figures}
    turnover, other = by_key["turnover"].pence, by_key["other"].pence
    form = choose_form(turnover, choice)
    rows: list[list[Cell]] = [list(SA_HEAD)]
    money: set[tuple[int, int]] = set()
    whole: set[tuple[int, int]] = set()

    def add(box: str, label: str, pence: int | None, api: str | None = None, whole_value: int | None = None) -> int:
        """Append a row; return its whole-pound figure (`whole_value` when the caller adds it up itself)."""
        w = whole_value if whole_value is not None else (whole_pounds(pence) if pence is not None else None)
        rows.append([box, label, pounds(pence) if pence is not None else None, w, api])
        if pence is not None:
            money.add((len(rows), 3))
        if w is not None:
            whole.add((len(rows), 4))
        return w or 0

    def blank(box: str, label: str) -> None:
        rows.append([box, f"{label} (not worked out by Accnomos: enter yours, if any)", None, None, None])

    warnings: list[str] = []
    if form == "short":
        w_income = add(
            "9", "Your turnover – the takings, fees, sales or money earned by your business", turnover, "turnover"
        )
        w_income += add("10", "Any other business income not included in box 9", other, "other")
        total_p = total_w = 0
        for box, label, keys in SHORT_EXPENSES:
            p = sum(by_key[k].pence - by_key[k].disallowable_pence for k in keys)
            total_p += p
            total_w += add(box, label, p, ", ".join(keys))
        add("20", "Total allowable expenses – total of boxes 11 to 19", total_p, None, total_w)
        net_p, net_w = turnover + other - total_p, w_income - total_w
        add("21", "Net profit – if your business income is more than your expenses", max(net_p, 0), None, max(net_w, 0))
        add("22", "Or, net loss – if your expenses exceed your business income", max(-net_p, 0), None, max(-net_w, 0))
        for box, label in (
            ("23", "Annual Investment Allowance"),
            ("24", "Allowance for small balance of unrelieved expenditure"),
            ("24.1", "Zero-emission car allowance"),
            ("25", "Other capital allowances"),
            ("25.1", "The Structures and Buildings Allowance"),
            ("25.2", "Freeport and Investment Zones Structures and Buildings Allowance"),
            ("26", "Total balancing charges"),
            ("27", "Goods and/or services for your own use"),
        ):
            blank(box, label)
        add(
            "28",
            "Net business profit for tax purposes (box 21 when boxes 22 to 27 are empty; otherwise work it out as "
            "the form's notes say)",
            max(net_p, 0),
            None,
            max(net_w, 0),
        )
        if turnover >= SHORT_LIMIT_PENCE:
            warnings.append("Turnover is £90,000 or more, so HMRC expects the full pages (SA103F), not the short ones.")
        title, form_name = "SA103S", "Self-employment (short), SA103S"
    else:
        w_income = add(
            "15", "Your turnover – the takings, fees, sales or money earned by your business", turnover, "turnover"
        )
        w_income += add("16", "Any other business income not included in box 15", other, "other")
        total_p = total_w = 0
        dis_rows: list[tuple[str, str, int]] = []
        for (box, label, keys), dbox in zip(FULL_EXPENSES, range(32, 46), strict=True):
            p = sum(by_key[k].pence for k in keys)
            total_p += p
            total_w += add(box, label, p, ", ".join(keys))
            dis_rows.append(
                (
                    str(dbox),
                    f"Disallowable: {label[0].lower()}{label[1:]}",
                    sum(by_key[k].disallowable_pence for k in keys),
                )
            )
        add("31", "Total expenses (total of boxes 17 to 30)", total_p, None, total_w)
        dis_p = dis_w = 0
        for box, label, p in dis_rows:
            dis_p += p
            dis_w += add(box, label, p)
        add("46", "Total disallowable expenses (total of boxes 32 to 45)", dis_p, None, dis_w)
        net_p, net_w = turnover + other - total_p, w_income - total_w
        add("47", "Net profit – if your business income is more than your expenses", max(net_p, 0), None, max(net_w, 0))
        add(
            "48",
            "Or, net loss – if your expenses are more than your business income",
            max(-net_p, 0),
            None,
            max(-net_w, 0),
        )
        blank("49-57", "Capital allowances")
        blank("59", "Balancing charge on sales of assets or on the cessation of business use")
        blank("60", "Goods and services for your own use")
        warnings.append(
            "Boxes 47 and 48 are income less total expenses, as the form asks. The disallowable expenses in box 46 "
            "are added back in the form's tax adjustments, after box 60: fill those in on HMRC's form."
        )
        title, form_name = "SA103F", "Self-employment (full), SA103F"
    rows.append([])
    meta: list[tuple[str, str]] = [
        ("Form", form_name),
        ("Tax year", s.tax_year),
        ("Period", f"{s.period_start.isoformat()} to {s.period_end.isoformat()}"),
        ("Accounting basis", s.basis_label),
    ]
    if business:
        meta.insert(0, ("Business", business))
    for k, v in meta:
        rows.append([k, v, None, None, None])
    year_end = date(s.period_start.year + 1, 4, 5)
    if s.period_end < year_end:
        warnings.append(
            f"These figures run to {s.period_end.isoformat()}, not the end of the tax year (5 April {year_end.year}). "
            "Use the whole year's figures on your return."
        )
    warnings += list(s.warnings)
    return Sheet(
        kind="sa103",
        title=title,
        filename=f"{title.lower()}-{s.tax_year}",
        rows=rows,
        guidance=SA_GUIDANCE,
        layout=[
            "Row 1 headings: Box, Description, £ and pence, Whole £, HMRC field. One row per box, in the form's order.",
            "Totals and net profit or loss are added up from the boxes above them, in each column.",
        ],
        money=money,
        whole=whole,
        warnings=warnings,
        extra={
            "form": form,
            "form_choice": choice,
            "suggested_form": choose_form(turnover),
            "turnover": float(pounds(turnover)),
            "tax_year": s.tax_year,
        },
    )


# --------------------------------------------------------------------------------------------------------------
# Writers: the same cells in CSV and XLSX
# --------------------------------------------------------------------------------------------------------------


def _safe(v: Cell) -> Cell:
    """Spreadsheets run text that starts with = + - @ as a formula: prefix it (OWASP CSV injection)."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def _text(v: Cell) -> str:
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    return str(_safe(v))


def to_csv(sheet: Sheet) -> bytes:
    """Plain UTF-8 without a byte-order mark (some bridging tools read a BOM as part of A1), CRLF line ends."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    for row in sheet.rows:
        w.writerow([_text(v) for v in row])
    return out.getvalue().encode("utf-8")


def to_xlsx(sheet: Sheet) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = sheet.title[:31]
    for r, row in enumerate(sheet.rows, start=1):
        for c, v in enumerate(row, start=1):
            if v is None:
                continue
            cell = ws.cell(row=r, column=c, value=float(v) if isinstance(v, Decimal) else _safe(v))
            if (r, c) in sheet.money:
                cell.number_format = "0.00"
            elif (r, c) in sheet.whole:
                cell.number_format = "0"
    if sheet.kind != "vat-bridging":  # the bridging file has no header row
        for c in ws[1]:
            c.font = Font(bold=True)
    for col, width in zip("ABCDE", (34, 16, 60, 14, 30), strict=False):
        ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def render(sheet: Sheet, fmt: FileFormat) -> bytes:
    return to_csv(sheet) if fmt == "csv" else to_xlsx(sheet)


__all__ = [
    "BY_KEY",
    "MEDIA",
    "PLANNED",
    "Sheet",
    "itsa_quarterly",
    "render",
    "sa103",
    "vat_bridging",
]
