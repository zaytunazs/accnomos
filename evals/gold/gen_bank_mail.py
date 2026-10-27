#!/usr/bin/env python3
"""Bank statement CSVs and mailbox fixtures built from the gold documents 061-200 (pure code, seeded).

    cd evals && python gold/gen_bank_mail.py

Bank: gold/bank/{barclays,starling,tide}_{julaug,sepoct}.csv + expected_matches.json (the truth).
  About 70 % of the 140 new documents get a payment line; the rest are unmatched on purpose. Noise: card
  refs and truncated upper-case merchant names, 1p rounding, payment lag, split (part) payments, and
  unrelated lines (wages, rent, HMRC, bank fees, transfers, payments from customers we never invoiced).
Mail: gold/mail/MNN.json (Graph-style message + attachments + the intake outcome we expect) and the
  attachment files under gold/mail/attachments/ (messy renders of gold docs, as PNG or image-only PDF, plus
  decoy files). Only renders at or under 300 KB are used as attachments.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import re
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from harness.render_gold import gold_files, png_to_pdf, render_one  # noqa: E402

BANK = HERE / "bank"
MAIL = HERE / "mail"
ATT = MAIL / "attachments"
SEED = 2027
TARGET = 0.70
MAX_PNG = 300 * 1024
OWNER = "Bramblewood Joinery Ltd"
PERIODS = {"julaug": (date(2026, 7, 1), date(2026, 8, 31)), "sepoct": (date(2026, 9, 1), date(2026, 10, 31))}
HEADERS = {
    "barclays": ["Number", "Date", "Account", "Amount", "Subcategory", "Memo"],
    "starling": ["Date", "Counter Party", "Reference", "Type", "Amount (GBP)", "Balance (GBP)", "Spending Category"],
    "tide": [
        "Transaction ID",
        "Transaction Date",
        "Transaction Type",
        "Transaction Information",
        "Paid In",
        "Paid Out",
        "Balance",
    ],
}
NOISE = [  # (label, min £, max £, sign, kind)
    ("WAGES RUN", 1800, 3200, -1, "payroll"),
    ("HMRC PAYE/NIC", 600, 1400, -1, "tax"),
    ("HMRC VAT", 800, 2600, -1, "tax"),
    ("MILL LANE PROPERTIES RENT", 950, 950, -1, "rent"),
    ("INSURANCE DIRECT DD", 64, 64, -1, "insurance"),
    ("ACCOUNT FEE", 7, 7, -1, "bank fee"),
    ("TRANSFER FROM SAVINGS", 500, 2000, 1, "transfer"),
    ("TRANSFER TO SAVINGS", 300, 1500, -1, "transfer"),
    ("SAM HARTLEY DRAWINGS", 400, 900, -1, "drawings"),
    ("PAYMENT RECEIVED CLIENT 0117", 150, 2400, 1, "income (no invoice on file)"),
]


def load_docs() -> list[dict]:
    docs = []
    for idx, p in enumerate(gold_files()):
        if int(p.name[:3]) < 61:
            continue
        g = json.loads(p.read_text(encoding="utf-8"))
        g["_file"], g["_idx"] = p.name, idx
        docs.append(g)
    return docs


def mon(d: date) -> str:
    return d.strftime("%d %b").upper()


def pay_plan(g: dict, rng: random.Random) -> list[dict] | None:
    """Payment events (date, signed pence, kind) for one gold doc, or None if it never reaches the bank."""
    when = date.fromisoformat(g["date"])
    gross = g["gross_pence"]
    pm = g["payment_method"]
    if pm == "cash":
        return None
    out = -1 if g["side"] == "purchase" else 1
    if g["is_credit_note"]:
        out = -out  # a refund moves the opposite way to the original document
    amount = abs(gross)
    lag = {"card": rng.randint(0, 2), "direct debit": rng.randint(9, 11)}.get(
        pm, rng.randint(2, 28) if g["side"] == "sale" else rng.randint(1, 14)
    )
    kind = "card" if pm == "card" else ("direct debit" if pm == "direct debit" else "bacs")
    events = [{"date": when + timedelta(days=lag), "pence": out * amount, "kind": kind}]
    if kind == "bacs" and amount > 30000 and rng.random() < 0.3:  # deposit + balance
        part = round(amount * rng.choice((0.3, 0.4, 0.5)))
        events = [
            {"date": events[0]["date"], "pence": out * part, "kind": "part"},
            {
                "date": events[0]["date"] + timedelta(days=rng.randint(7, 25)),
                "pence": out * (amount - part),
                "kind": "part",
            },
        ]
    elif kind == "card" and rng.random() < 0.06:  # pre-auth / rounding: 1p out
        events[0]["pence"] += out * rng.choice((-1, 1))
        events[0]["kind"] = "rounding"
    return events


def account_of(g: dict) -> str:
    if g["side"] == "sale" or g["is_credit_note"]:
        return "tide"
    return "starling" if g["payment_method"] == "card" else "barclays"


def description(bank: str, g: dict, ev: dict, rng: random.Random) -> tuple[str, str, str]:
    """(description, reference, type) for a payment line."""
    name = g["supplier"]["name"] if g["side"] == "purchase" else g["customer"]["name"]
    up = re.sub(r"\s+", " ", name.upper())
    card = g["card_last4"] or f"{rng.randint(1000, 9999)}"
    inv = g["invoice_number"] or ""
    if ev["kind"] in ("card", "rounding"):
        if bank == "starling":
            return name.title(), f"Card payment {mon(ev['date'])} ****{card}", "CARD PAYMENT"
        return f"CARD PAYMENT TO {up[:24]} ON {mon(ev['date'])} CD {card}", "", "CARD"
    if ev["kind"] == "direct debit":
        return f"{up[:22]} DD REF {rng.randint(10**6, 10**7 - 1)}", "", "DIRECT DEBIT"
    tail = " (PART)" if ev["kind"] == "part" else ""
    if bank == "starling":
        return name.title(), f"{inv}{tail}".strip(), "FASTER PAYMENT"
    if bank == "tide":
        return f"{up[:30]} {inv}{tail}".strip(), "", "Faster Payment " + ("In" if ev["pence"] > 0 else "Out")
    return f"{up[:28]} {inv}{tail} FP {mon(ev['date'])} {rng.randint(100000, 999999)}".strip(), "", "FP"


def build_bank() -> tuple[list[dict], dict]:
    rng = random.Random(SEED)
    docs = load_docs()
    eligible = [g for g in docs if g["payment_method"] != "cash"]
    chosen = rng.sample(eligible, k=round(TARGET * len(docs)) + 6)  # a few drop out if paid after 31 Oct
    rows: dict[tuple[str, str], list[dict]] = {(b, p): [] for b in HEADERS for p in PERIODS}
    matched: dict[str, list[dict]] = {}
    for g in chosen:
        evs = pay_plan(g, rng)
        if not evs or any(e["date"] > PERIODS["sepoct"][1] for e in evs):
            continue
        for ev in evs:
            period = "julaug" if ev["date"] <= PERIODS["julaug"][1] else "sepoct"
            bank = account_of(g)
            d, ref, typ = description(bank, g, ev, rng)
            rows[(bank, period)].append(
                {
                    "date": ev["date"],
                    "pence": ev["pence"],
                    "desc": d,
                    "ref": ref,
                    "type": typ,
                    "doc": g["_file"],
                    "kind": ev["kind"],
                }
            )
            matched.setdefault(g["_file"], []).append({"kind": ev["kind"], "pence": ev["pence"]})
    # keep ~70 %: trim extras at random so the headline ratio is exact-ish
    want = round(TARGET * len(docs))
    keep = set(rng.sample(sorted(matched), k=min(want, len(matched))))
    for k, lst in rows.items():
        rows[k] = [r for r in lst if r["doc"] in keep]
    matched = {f: v for f, v in matched.items() if f in keep}
    # unrelated noise lines
    for k in rows:
        lo, hi = PERIODS[k[1]]
        for label, a, b, sign, kind in rng.sample(NOISE, k=rng.randint(6, 8)):  # each at most once per statement
            if sign > 0 and k[0] != "tide" or (sign < 0 and k[0] == "tide" and kind == "transfer"):
                continue
            rows[k].append(
                {
                    "date": lo + timedelta(days=rng.randint(0, (hi - lo).days)),
                    "pence": sign * round(rng.uniform(a, b) * 100),
                    "desc": label,
                    "ref": "",
                    "type": "TRANSFER",
                    "doc": None,
                    "kind": kind,
                }
            )
    return docs, {"rows": rows, "matched": matched}


def write_bank(built: dict, docs: list[dict]) -> dict:
    BANK.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED + 1)
    truth_rows: list[dict] = []
    for (bank, period), lst in built["rows"].items():
        lst.sort(key=lambda r: (r["date"], r["pence"]))
        opening = rng.randint(4000, 9000) * 100
        bal, name = opening, f"{bank}_{period}.csv"
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(HEADERS[bank])
        for n, r in enumerate(lst, 1):
            bal += r["pence"]
            amt = f"{r['pence'] / 100:.2f}"
            if bank == "barclays":
                w.writerow([n, r["date"].strftime("%d/%m/%Y"), "20-45-31 40291178", amt, r["type"], r["desc"]])
            elif bank == "starling":
                cat = (
                    "INCOME"
                    if r["pence"] > 0
                    else (
                        "BILLS_AND_SERVICES" if r["doc"] is None else rng.choice(("GENERAL", "SHOPPING", "TRANSPORT"))
                    )
                )
                w.writerow(
                    [r["date"].strftime("%d/%m/%Y"), r["desc"], r["ref"], r["type"], amt, f"{bal / 100:.2f}", cat]
                )
            else:
                paid_in = f"{r['pence'] / 100:.2f}" if r["pence"] > 0 else ""
                paid_out = f"{-r['pence'] / 100:.2f}" if r["pence"] < 0 else ""
                w.writerow(
                    [
                        f"TD{rng.randint(10**9, 10**10 - 1)}",
                        r["date"].isoformat(),
                        r["type"],
                        r["desc"],
                        paid_in,
                        paid_out,
                        f"{bal / 100:.2f}",
                    ]
                )
            truth_rows.append(
                {
                    "file": name,
                    "row": n,
                    "date": r["date"].isoformat(),
                    "amount_pence": r["pence"],
                    "gold": r["doc"],
                    "kind": r["kind"],
                }
            )
        (BANK / name).write_text(buf.getvalue(), encoding="utf-8")
    matched = built["matched"]
    unmatched = sorted(g["_file"] for g in docs if g["_file"] not in matched)
    truth = {
        "seed": SEED,
        "documents": len(docs),
        "documents_with_payment": len(matched),
        "share": round(len(matched) / len(docs), 3),
        "split_payment_docs": sorted(f for f, v in matched.items() if len(v) > 1),
        "rounding_docs": sorted(f for f, v in matched.items() if any(e["kind"] == "rounding" for e in v)),
        "documents_without_payment": unmatched,
        "rows": truth_rows,
    }
    (BANK / "expected_matches.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    return truth


# ------------------------------------------------------------------ mail


def tiny_png(text: str, size: tuple[int, int], seed: int) -> bytes:
    rng = random.Random(seed)
    img = Image.new("RGB", size, (rng.randint(30, 200), rng.randint(30, 200), rng.randint(30, 200)))
    ImageDraw.Draw(img).text((8, size[1] // 3), text, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def tiny_pdf(text: str) -> bytes:
    img = Image.new("RGB", (420, 300), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for i, line in enumerate(text.split("\n")):
        d.text((24, 24 + 18 * i), line, fill=(20, 20, 20))
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=100)
    return buf.getvalue()


def tracking_gif() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), (255, 255, 255)).save(buf, format="GIF")
    return buf.getvalue()


def zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("terms.txt", "Standard terms of trade. SAMPLE — FICTIONAL COMPANY\n")
    return buf.getvalue()


ICS = (
    "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Sample//EN\nMETHOD:REQUEST\nBEGIN:VEVENT\nUID:sample-0001@example\n"
    "DTSTART:20261014T090000Z\nDTEND:20261014T093000Z\nSUMMARY:Site visit - SAMPLE — FICTIONAL COMPANY\nEND:VEVENT\nEND:VCALENDAR\n"
).encode()


def build_mail(docs: list[dict]) -> int:
    rng = random.Random(SEED + 2)
    ATT.mkdir(parents=True, exist_ok=True)
    MAIL.mkdir(parents=True, exist_ok=True)
    pool: list[tuple[dict, bytes]] = []
    for g in docs:
        if g["gold_case"] in ("credit_note", "edge_torn_faded"):
            continue
        png = render_one(HERE / "receipts" / g["_file"], g["_idx"], messy=True)
        if len(png) <= MAX_PNG:
            pool.append((g, png))
    rng.shuffle(pool)
    pool_iter = iter(pool)
    attachments: dict[str, bytes] = {}

    def put(name: str, data: bytes, ctype: str, inline: bool = False, gold: str | None = None) -> dict:
        attachments[name] = data
        return {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "id": hashlib.sha1(name.encode()).hexdigest()[:20],
            "name": name,
            "contentType": ctype,
            "size": len(data),
            "isInline": inline,
            "path": f"attachments/{name}",
            "gold": gold,
        }

    def doc_att(as_pdf: bool) -> tuple[dict, dict]:
        g, png = next(pool_iter)
        stem = g["_file"][:-5]
        a = (
            put(f"{stem}.pdf", png_to_pdf(png), "application/pdf", gold=g["_file"])
            if as_pdf
            else put(f"{stem}.png", png, "image/png", gold=g["_file"])
        )
        return g, a

    mails: list[dict] = []

    def message(
        n: int,
        subject: str,
        sender: tuple[str, str],
        when: datetime,
        body: str,
        atts: list[dict],
        expected: list[dict],
        note: str,
        kind: str,
    ):
        mails.append(
            {
                "id": f"AAMk-sample-{n:02d}",
                "receivedDateTime": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "subject": subject,
                "from": {"emailAddress": {"name": sender[0], "address": sender[1]}},
                "toRecipients": [
                    {"emailAddress": {"name": "Sam Hartley", "address": "sam.hartley@bramblewood.example"}}
                ],
                "hasAttachments": bool(atts),
                "bodyPreview": body[:120],
                "body": {"contentType": "text", "content": body},
                "attachments": atts,
                "label": "SAMPLE — FICTIONAL COMPANY",
                "kind": kind,
                "expected": {"intake": expected, "note": note},
            }
        )

    def slug(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", name.lower())[:18] or "supplier"

    def ts(g: dict, extra_days: int = 0) -> datetime:
        return datetime.fromisoformat(g["date"]) + timedelta(
            days=extra_days, hours=rng.randint(7, 17), minutes=rng.randint(0, 59), seconds=rng.randint(0, 59)
        )

    # 01-09: one document each (PNG photo or image-only PDF), from supplier or forwarded from a phone
    for n in range(1, 10):
        g, a = doc_att(as_pdf=n % 3 == 0)
        sup = g["supplier"]["name"]
        if n % 3 == 1:
            sender, subj, body = (
                (sup, f"accounts@{slug(sup)}.example"),
                f"Invoice {g['invoice_number'] or 'attached'} from {sup}",
                f"Hi,\n\nPlease find attached our invoice. Payment terms as stated.\n\nKind regards\nAccounts\n{sup}",
            )
        elif n % 3 == 2:
            sender, subj, body = ("Sam Hartley", "sam.hartley.phone@mailbox.example"), "Receipt", "Sent from my phone"
        else:
            sender, subj, body = (
                (sup, f"noreply@{slug(sup)}.example"),
                f"Your receipt from {sup}",
                f"Thanks for your purchase on {g['date']}. Your receipt is attached.",
            )
        message(
            n,
            subj,
            (sender[0], sender[1]),
            ts(g),
            body,
            [a],
            [{"attachment": a["name"], "treat_as": "document", "gold": g["_file"]}],
            "single document",
            "document",
        )
    # 10-12: two documents in one message
    for n in range(10, 13):
        (g1, a1), (g2, a2) = doc_att(False), doc_att(n == 11)
        message(
            n,
            "Invoices for August" if n == 10 else "Two receipts",
            ("Operations", "ops@bramblewood.example"),
            ts(g1, 1),
            "Two for the books please.",
            [a1, a2],
            [
                {"attachment": a1["name"], "treat_as": "document", "gold": g1["_file"]},
                {"attachment": a2["name"], "treat_as": "document", "gold": g2["_file"]},
            ],
            "two documents",
            "document",
        )
    # 13-14: the same file arrives twice (duplicate detection)
    g, a = doc_att(False)
    sup = g["supplier"]["name"]
    for n, subj in ((13, f"Invoice from {sup}"), (14, f"Re: Invoice from {sup} - resending")):
        message(
            n,
            subj,
            (sup, f"accounts@{slug(sup)}.example"),
            ts(g, 0 if n == 13 else 2),
            "Please find attached." if n == 13 else "Resending in case it was missed.",
            [dict(a)],
            [{"attachment": a["name"], "treat_as": "document" if n == 13 else "duplicate", "gold": g["_file"]}],
            "second copy is a duplicate by hash",
            "duplicate",
        )
    # 15-20: decoys
    logo, banner, pixel = (
        tiny_png("SAMPLE TRADE MAG", (200, 60), 15),
        tiny_png("AUTUMN SALE", (600, 120), 16),
        tracking_gif(),
    )
    d0 = datetime(2026, 9, 21, 6, 30, 0)
    message(
        15,
        "This week in joinery: 10% off oak",
        ("Joinery Weekly", "news@joineryweekly.example"),
        d0,
        "Autumn offers inside. Unsubscribe at the bottom.",
        [
            put("logo.png", logo, "image/png", True),
            put("banner.png", banner, "image/png", True),
            put("open.gif", pixel, "image/gif", True),
        ],
        [{"attachment": n_, "treat_as": "ignore", "gold": None} for n_ in ("logo.png", "banner.png", "open.gif")],
        "newsletter with inline images and a tracking pixel",
        "decoy",
    )
    message(
        16,
        "Our new catalogue is here",
        ("Oakhill Fixings Marketing", "marketing@oakhillfixings.example"),
        d0 + timedelta(days=9),
        "Catalogue attached - no order needed.",
        [
            put(
                "catalogue_autumn.pdf",
                tiny_pdf("Oakhill Fixings\nAutumn catalogue\nNot an invoice\nSAMPLE — FICTIONAL COMPANY"),
                "application/pdf",
            ),
            put("promo.png", tiny_png("PROMO", (500, 200), 17), "image/png", True),
        ],
        [
            {"attachment": "catalogue_autumn.pdf", "treat_as": "ignore", "gold": None},
            {"attachment": "promo.png", "treat_as": "ignore", "gold": None},
        ],
        "marketing PDF is not a financial document",
        "decoy",
    )
    message(
        17,
        "Invitation: Site visit, Wed 14 Oct 09:00",
        ("Calendar", "calendar@clientsuite.example"),
        d0 + timedelta(days=15),
        "You are invited. Accept or decline.",
        [put("invite.ics", ICS, "text/calendar"), put("map.png", tiny_png("MAP", (300, 300), 18), "image/png", True)],
        [
            {"attachment": "invite.ics", "treat_as": "ignore", "gold": None},
            {"attachment": "map.png", "treat_as": "ignore", "gold": None},
        ],
        "calendar invite",
        "decoy",
    )
    message(
        18,
        "Re: Quote for staircase",
        ("Harrogate Heritage Interiors", "jo@harrogateheritage.example"),
        d0 + timedelta(days=20),
        "Thanks, that works for us.\n\n-- \nJo Marsh | Harrogate Heritage Interiors",
        [
            put("image001.png", tiny_png("HHI", (180, 50), 19), "image/png", True),
            put("image002.jpg", tiny_png("LINKEDIN", (24, 24), 20), "image/jpeg", True),
        ],
        [
            {"attachment": "image001.png", "treat_as": "ignore", "gold": None},
            {"attachment": "image002.jpg", "treat_as": "ignore", "gold": None},
        ],
        "reply with signature images only",
        "decoy",
    )
    g, a = doc_att(True)
    sup = g["supplier"]["name"]
    message(
        19,
        f"Invoice {g['invoice_number'] or ''} attached".strip(),
        (sup, f"billing@{slug(sup)}.example"),
        ts(g, 1),
        f"Invoice attached.\n\n{sup}\nFollow us on social",
        [a, put("signature_logo.png", tiny_png(sup[:12], (160, 48), 21), "image/png", True)],
        [
            {"attachment": a["name"], "treat_as": "document", "gold": g["_file"]},
            {"attachment": "signature_logo.png", "treat_as": "ignore", "gold": None},
        ],
        "one real document plus a signature logo",
        "mixed",
    )
    message(
        20,
        "Terms of trade and invoice to follow",
        ("Calder Valley Supplies", "orders@caldervalley.example"),
        d0 + timedelta(days=30),
        "Our terms are attached; the invoice will follow tomorrow.",
        [put("terms.zip", zip_bytes(), "application/zip")],
        [{"attachment": "terms.zip", "treat_as": "ignore", "gold": None}],
        "unsupported type; the invoice itself has not arrived",
        "decoy",
    )
    for name, data in attachments.items():
        (ATT / name).write_bytes(data)
    for m in mails:
        n = int(m["id"].rsplit("-", 1)[1])
        (MAIL / f"M{n:02d}.json").write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")
    return len(mails)


def main() -> None:
    docs, built = build_bank()
    truth = write_bank(built, docs)
    print(
        f"bank: {truth['documents_with_payment']}/{truth['documents']} documents paid ({truth['share']:.0%}); "
        f"{len(truth['split_payment_docs'])} split, {len(truth['rounding_docs'])} rounding; {len(truth['rows'])} rows"
    )
    print("mail:", build_mail(docs), "fixtures")


if __name__ == "__main__":
    main()
