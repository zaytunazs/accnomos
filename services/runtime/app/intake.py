"""Outlook intake (F10): copy likely receipts/invoices from the user's mailbox into 00 Inbox.

Code only, no model call. The mailbox is only read (nothing is moved, flagged, marked read or
deleted); everything written goes to the user's own books folder:

    00 Inbox/<yyyy-mm-dd>_<sender-domain>_<original-name>   the copied attachment (a HEIC photo as a JPEG)
    00 Inbox/<yyyy-mm-dd>_<sender-domain>_<subject>.eml.txt a receipt written in the body of a mail with no attachment
    _System/Intake/seen.json                                what we have already copied (max 5,000, newest kept),
                                                            with the mailbox each file came from
    _System/mail/mailboxes.json                             the linked mailboxes and their last check (app/mailboxes.py)
    _System/Intake/log/<yyyy-mm>.jsonl                      one line per saved file
    _System/audit/<yyyy-mm>.jsonl                           one line per scan (DEV.md convention)

Body receipts (Uber, Amazon, SaaS bills): only Inbox messages without attachments are listed; the full body is
fetched only when the subject or preview has a receipt word, and kept only when a total/VAT line carries a
currency amount (`looks_like_receipt`). Mail from the user, and marketing mail, is never kept.

One call reads one mailbox (`mailbox`, default the signed-in one): its folder and sender allow/deny lists apply.
The same file arriving in two mailboxes is copied once (content hash against seen.json, the filed documents and
00 Inbox); the mailbox it came from is kept in seen.json, the intake log and the audit line, and the Inbox scan
puts it on the proposal (`source_mailbox`).
"""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel

from accnomos_connectors.base import MailAttachment, MailMessage, MailProvider
from app.books import SYSTEM, Books, Rule, _month, _with_suffix, now
from app.formats import MAX_BYTES, FormatError, is_heif, prepare
from app.mailboxes import PRIMARY_ID, Mailbox, primary_mailbox, record_scan, sender_allowed
from app.paths import INBOX

log = logging.getLogger(__name__)

INTAKE = f"{SYSTEM}/Intake"
SEEN = f"{INTAKE}/seen.json"
INTAKE_LOG = f"{INTAKE}/log"
SEEN_MAX = 5000
ACTOR = "agent:intake"

MIN_SIZE = 10 * 1024
MAX_SIZE = MAX_BYTES  # 25 MB, as everywhere a document comes in
SIGNATURE_MAX = 40 * 1024
THRESHOLD = 0.4
BODY_ID = "body"  # attachment_id recorded for a body receipt
BODY_MAX_CHARS = 100_000

ACCEPTED_TYPES = {"application/pdf", "image/jpeg", "image/jpg", "image/pjpeg", "image/png", "image/heic", "image/heif"}
ACCEPTED_EXTS = (".pdf", ".jpg", ".jpeg", ".png", ".heic", ".heif")
# A letter must not come straight before the keyword ('border' is not an order); '_' and digits may.
KEYWORDS = re.compile(
    r"(?<![a-z])(receipt|invoice|inv[-_ ]?\d|bill|statement|order|payment|paid|vat|remittance|credit note|"
    r"pro ?forma|purchase|booking confirmation|tax)",
    re.IGNORECASE,
)
# Sharing a domain with these says nothing about the sender being "you".
PUBLIC_MAIL_DOMAINS = {
    "outlook.com",
    "hotmail.com",
    "hotmail.co.uk",
    "live.com",
    "live.co.uk",
    "msn.com",
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "yahoo.co.uk",
    "icloud.com",
    "me.com",
    "aol.com",
    "btinternet.com",
    "sky.com",
    "virginmedia.com",
    "protonmail.com",
    "proton.me",
}
_UNSAFE = re.compile(r'[\\/:*?"<>|#%\x00-\x1f]+')  # OneDrive-forbidden and URL-awkward characters

# Body receipts. Worth fetching the body: a receipt word in the subject or preview.
BODY_HINT = re.compile(
    r"(?<![a-z])(receipt|invoice|order|payment|paid|trip|ride|booking|subscription|renewal|billing|bill|vat|total)",
    re.IGNORECASE,
)
# Kept: total/VAT/invoice/receipt followed by a currency amount (`looks_like_receipt`). Graph's HTML-to-text
# conversion often puts a table's label and amount on separate lines.
LABEL_GAP = 30  # characters allowed between the label and its amount, e.g. ' (20%) ' or ' incl. VAT: '
MONEY = re.compile(
    r"(£|€|\$|\b(GBP|EUR|USD)\s?)\s?\d{1,3}(,\d{3})*(\.\d{2})?\b|\b\d+(,\d{3})*\.\d{2}\s?(GBP|EUR|USD)\b",
    re.IGNORECASE,
)
TOTAL_LABEL = re.compile(r"(?<![a-z])(total|vat|invoice|receipt|amount (paid|due|charged)|balance due)(?![a-z])", re.I)
# Bulk senders (Inbox triage drops them too): their mail is marketing, never a receipt.
BULK_SENDER = re.compile(
    r"^(newsletters?|news|marketing|promotions?|promo|offers|deals|digest|updates|mailer)([-_.+].*)?$"
)
MARKETING_SUBJECT = re.compile(r"% off\b|\bsale\b|newsletter|webinar|deals?\b|offers?\b|discount", re.IGNORECASE)


class IntakeItem(BaseModel):
    name: str
    subject: str
    from_address: str
    score: float
    message_id: str
    attachment_id: str
    mailbox: str = ""  # the address it came from


class IntakeResult(BaseModel):
    mailbox_id: str = PRIMARY_ID
    mailbox: str = ""  # address of the mailbox read
    scanned: int = 0
    candidates: int = 0
    saved: list[str] = []
    skipped_duplicates: int = 0
    dry_run: bool = False
    errors: list[dict[str, str]] = []
    items: list[IntakeItem] = []  # one per saved (or, in a dry run, would-be-saved) file
    filtered_senders: int = 0  # messages left out by the mailbox's sender allow/deny lists
    scan_job_id: str | None = None  # with `read_now`: the background job reading the saved files (app/scan_jobs.py)


# ---------------------------------------------------------------------- #
# Pure helpers (tested directly)
# ---------------------------------------------------------------------- #


def domain_of(address: str) -> str:
    return address.rsplit("@", 1)[-1].strip().lower() if "@" in address else ""


def skip_reason(a: MailAttachment) -> str | None:
    """Why this attachment is not a receipt/invoice candidate, or None to keep it."""
    name = a.name.lower()
    if a.is_inline and not is_pdf(a):  # Apple Mail marks real PDF attachments inline
        return "inline"
    if name.endswith(".ics") or a.content_type == "text/calendar":
        return "calendar"
    if fnmatch.fnmatch(name, "image0*.png") and a.size < SIGNATURE_MAX:
        return "signature"
    if a.content_type not in ACCEPTED_TYPES and not name.endswith(ACCEPTED_EXTS):
        return "type"
    if a.size < MIN_SIZE:
        return "too_small"
    if a.size > MAX_SIZE:
        return "too_large"
    return None


def is_pdf(a: MailAttachment) -> bool:
    return a.content_type == "application/pdf" or a.name.lower().endswith(".pdf")


def is_from_self(m: MailMessage, user: str | None) -> bool:
    if not user:
        return False
    user = user.lower()
    if m.from_address == user:
        return True
    dom = domain_of(user)
    return bool(dom) and dom not in PUBLIC_MAIL_DOMAINS and domain_of(m.from_address) == dom


def known_supplier(m: MailMessage, rules: list[Rule]) -> bool:
    """A user rule's supplier pattern matches the sender's name or domain (rules come from approvals)."""
    hay = [m.from_name, domain_of(m.from_address).split(".")[0]]
    for r in rules:
        try:
            if any(h and re.search(r.match.supplier_regex, h, re.IGNORECASE) for h in hay):
                return True
        except re.error:
            continue
    return False


def score(m: MailMessage, a: MailAttachment, user: str | None, rules: list[Rule] | None = None) -> float:
    """Cheap 0–1 likelihood that this attachment is a receipt or invoice."""
    s = 0.0
    if m.from_address and not is_from_self(m, user):
        s += 0.15
    if KEYWORDS.search(m.subject or ""):
        s += 0.3
    if KEYWORDS.search(a.name):
        s += 0.3
    if is_pdf(a):
        s += 0.15
    if rules and known_supplier(m, rules):
        s += 0.25
    return round(min(1.0, s), 2)


def safe_component(text: str, limit: int) -> str:
    text = _UNSAFE.sub("_", text).strip(" ._")
    return text[:limit].rstrip(" .") or "unknown"


def target_name(m: MailMessage, a: MailAttachment) -> str:
    """'2026-10-21_screwfix.com_Invoice 123.pdf' (the extension is kept even when the name is cut)."""
    stem, dot, ext = a.name.rpartition(".")
    if not dot or not stem or len(ext) > 5:
        stem, ext = a.name, ""
    original = safe_component(stem, 80) + (f".{safe_component(ext, 5).lower()}" if ext else "")
    day = m.received_at.astimezone(UTC).strftime("%Y-%m-%d")
    return f"{day}_{safe_component(domain_of(m.from_address) or 'unknown', 60)}_{original}"


def body_worth_reading(m: MailMessage, user: str | None) -> bool:
    """Cheap test on what the listing already has, before the full body is fetched."""
    if not m.from_address or is_from_self(m, user):
        return False
    if BULK_SENDER.match(m.from_address.split("@", 1)[0]) or MARKETING_SUBJECT.search(m.subject or ""):
        return False
    return bool(BODY_HINT.search(m.subject or "") or BODY_HINT.search(m.body_preview or ""))


def looks_like_receipt(text: str) -> bool:
    """A total/VAT/invoice/receipt label followed by a currency amount: on the same line ('VAT (20%) £2.00'), or
    the label alone and the amount starting the next line ('Order Total:' / '£64.97'). Prose that mentions VAT
    after a price ('£1,450 plus VAT', a quote) does not count."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for i, line in enumerate(lines):
        for label in TOTAL_LABEL.finditer(line):
            rest = line[label.end() :]
            amount = MONEY.search(rest)
            if amount and amount.start() <= LABEL_GAP:
                return True
            if len(rest.strip(" :.-–\t")) == 0 and i + 1 < len(lines) and MONEY.match(lines[i + 1]):
                return True
    return False


def body_document(m: MailMessage, text: str) -> bytes:
    """What is saved: who sent it and when (the reader needs the supplier), then the body as plain text."""
    sender = f"{m.from_name} <{m.from_address}>" if m.from_name else m.from_address
    head = f"From: {sender}\nDate: {m.received_at.astimezone(UTC).strftime('%Y-%m-%d %H:%M')} UTC\n"
    return f"{head}Subject: {m.subject}\n\n{text.strip()[:BODY_MAX_CHARS]}\n".encode()


def body_name(m: MailMessage) -> str:
    """'2026-10-21_uber.com_Your Tuesday evening trip with Uber.eml.txt'."""
    day = m.received_at.astimezone(UTC).strftime("%Y-%m-%d")
    subject = safe_component(m.subject or "receipt", 80)
    return f"{day}_{safe_component(domain_of(m.from_address) or 'unknown', 60)}_{subject}.eml.txt"


def as_jpeg_if_heic(a: MailAttachment, data: bytes) -> tuple[MailAttachment, bytes]:
    """A HEIC photo becomes a JPEG on arrival. Without a HEIC reader the original is kept: the Inbox scan then
    shows a card asking for a JPEG."""
    if not is_heif(data):
        return a, data
    try:
        prep = prepare(data, a.name)
    except FormatError:
        return a, data
    if prep.converted_from is None or prep.image is None:
        return a, data
    stem = a.name.rpartition(".")[0] or a.name
    return a.model_copy(update={"name": f"{stem}.jpg", "content_type": "image/jpeg"}), prep.image


def _free(name: str, taken: set[str]) -> str:
    candidate, n = name, 1
    while candidate in taken:
        n += 1
        candidate = _with_suffix(name, n)
    taken.add(candidate)
    return candidate


# ---------------------------------------------------------------------- #
# The scan
# ---------------------------------------------------------------------- #


class _Dedupe:
    """Hashes already in the books; the Inbox is only read (and hashed) when a candidate needs it."""

    def __init__(self, books: Books, seen: list[dict[str, Any]]) -> None:
        self.books = books
        # Message ids are per mailbox; entries from before linked mailboxes are the signed-in one's.
        self.seen_ids = {(s.get("mailbox_id", PRIMARY_ID), s.get("message_id"), s.get("attachment_id")) for s in seen}
        self.hashes = {s["sha256"] for s in seen if s.get("sha256")}
        self._loaded = False

    async def known(self, sha: str) -> bool:
        if sha in self.hashes:
            return True
        if not self._loaded:
            hashes = await self.books.known_hashes()  # processed and filed already
            for f in await self.books.list_files(INBOX):
                hashes.add(hashlib.sha256(await self.books.storage.read(f.path)).hexdigest())
            self.hashes |= hashes
            self._loaded = True
        return sha in self.hashes


async def scan_mail(
    books: Books,
    mail: MailProvider,
    *,
    since_days: int = 14,
    dry_run: bool = False,
    user: str | None = None,
    max_messages: int = 50,
    bodies: bool = True,
    mailbox: Mailbox | None = None,
) -> IntakeResult:
    """Copy likely receipts from the last `since_days` into 00 Inbox: attachments of up to `max_messages` mails with
    attachments, and (`bodies`) receipts written in up to `max_messages` mails without. `mail` reads `mailbox`
    (default: the signed-in one, `user`)."""
    box = mailbox or primary_mailbox(user)
    folder = None if box.folder == "all" else box.folder
    result = IntakeResult(dry_run=dry_run, mailbox_id=box.id, mailbox=box.address)

    def wanted(m: MailMessage) -> bool:
        """Through the mailbox's sender lists."""
        if not sender_allowed(m.from_address, box.allow_senders, box.deny_senders):
            result.filtered_senders += 1
            return False
        return True

    seen: list[dict[str, Any]] = await books.read_json(SEEN, [])
    rules = await books.load_rules()
    dedupe = _Dedupe(books, seen)
    taken = {f.name for f in await books.list_files(INBOX)}
    started = now()
    new_seen: list[dict[str, Any]] = []
    log_lines: list[dict[str, Any]] = []

    def keep(m: MailMessage, attachment_id: str, name: str, sha: str, sc: float) -> None:
        dedupe.hashes.add(sha)
        dedupe.seen_ids.add((box.id, m.id, attachment_id))
        at = now().isoformat()
        saved_as = f"{INBOX}/{name}"
        new_seen.append(
            {
                "sha256": sha,
                "message_id": m.id,
                "attachment_id": attachment_id,
                "saved_as": saved_as,
                "at": at,
                "mailbox_id": box.id,
                "mailbox": box.address,
            }
        )
        log_lines.append(
            {
                "at": at,
                "mailbox": box.address,
                "message_id": m.id,
                "from": m.from_address,
                "subject": m.subject[:200],
                "score": sc,
                "saved_as": saved_as,
                "sha256": sha,
            }
        )
        result.saved.append(name)
        result.items.append(
            IntakeItem(
                name=name,
                subject=m.subject[:200],
                from_address=m.from_address,
                score=sc,
                message_id=m.id,
                attachment_id=attachment_id,
                mailbox=box.address,
            )
        )

    def failed(m: MailMessage, what: str, exc: Exception) -> None:
        log.warning("saving %s from %s failed: %s", what, m.id, exc)
        result.errors.append(
            {"message": m.subject[:120], "attachment": what, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        )

    since = started - timedelta(days=since_days)
    messages = await mail.list_messages(since, max_messages, folder=folder)
    result.scanned = len(messages)
    for m in messages:
        if not wanted(m):
            continue
        try:
            attachments = await mail.list_attachments(m.id)
        except FileNotFoundError:
            continue  # deleted between listing and now
        except Exception as exc:  # noqa: BLE001  one bad message must not stop the scan
            log.warning("listing attachments of %s failed: %s", m.id, exc)
            result.errors.append({"message": m.subject[:120], "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            continue
        for a in attachments:
            if skip_reason(a):
                continue
            sc = score(m, a, user, rules)
            if sc < THRESHOLD:
                continue
            result.candidates += 1
            if (box.id, m.id, a.id) in dedupe.seen_ids:
                result.skipped_duplicates += 1
                continue
            try:
                data = await mail.download_attachment(m.id, a.id)
                if len(data) > MAX_SIZE:
                    continue
                saved, data = await asyncio.to_thread(as_jpeg_if_heic, a, data)
                sha = hashlib.sha256(data).hexdigest()
                if await dedupe.known(sha):
                    result.skipped_duplicates += 1
                    continue
                name = _free(target_name(m, saved), taken)
                if not dry_run:
                    await books.storage.write(f"{INBOX}/{name}", data)  # >4 MB goes through an upload session
            except Exception as exc:  # noqa: BLE001
                failed(m, a.name, exc)
                continue
            keep(m, a.id, name, sha, sc)

    if bodies:  # receipts written in the body of mail without attachments, saved as .eml.txt
        try:
            plain = await mail.list_without_attachments(since, max_messages, folder=folder)
        except Exception as exc:  # noqa: BLE001  the attachments already copied still count
            log.warning("listing mail without attachments failed: %s", exc)
            result.errors.append({"message": "mail without attachments", "error": f"{type(exc).__name__}: {exc}"[:200]})
            plain = []
        result.scanned += len(plain)
        for m in plain:
            if not wanted(m) or not body_worth_reading(m, user):
                continue
            if (box.id, m.id, BODY_ID) in dedupe.seen_ids:
                result.candidates += 1
                result.skipped_duplicates += 1
                continue
            try:
                text = await mail.message_text(m.id)
            except FileNotFoundError:
                continue
            except Exception as exc:  # noqa: BLE001
                failed(m, "message body", exc)
                continue
            if not looks_like_receipt(text):
                continue
            result.candidates += 1
            data = body_document(m, text)
            sha = hashlib.sha256(data).hexdigest()
            if await dedupe.known(sha):
                result.skipped_duplicates += 1
                continue
            name = _free(body_name(m), taken)
            try:
                if not dry_run:
                    await books.storage.write(f"{INBOX}/{name}", data)
            except Exception as exc:  # noqa: BLE001
                failed(m, "message body", exc)
                continue
            keep(m, BODY_ID, name, sha, 1.0)

    if not dry_run:
        await _record(books, new_seen, log_lines, result, since_days, box)
    return result


async def _record(
    books: Books,
    new_seen: list[dict[str, Any]],
    log_lines: list[dict[str, Any]],
    result: IntakeResult,
    since_days: int,
    box: Mailbox,
) -> None:
    if new_seen:
        await books._update_json(SEEN, [], lambda old: [*old, *new_seen][-SEEN_MAX:])
        by_month: dict[str, list[str]] = {}
        for line in log_lines:
            by_month.setdefault(_month(datetime.fromisoformat(line["at"])), []).append(
                json.dumps(line, ensure_ascii=False)
            )
        for month, lines in by_month.items():
            text = ("\n".join(lines) + "\n").encode()
            await books._update(f"{INTAKE_LOG}/{month}.jsonl", lambda old, t=text: (old or b"") + t)
    await books.audit(
        ACTOR,
        "mail_scanned",
        {
            "mailbox_id": box.id,
            "mailbox": box.address,
            "kind": box.kind,
            "folder": box.folder,
            "since_days": since_days,
            "scanned": result.scanned,
            "candidates": result.candidates,
            "saved": len(result.saved),
            "skipped_duplicates": result.skipped_duplicates,
            "errors": len(result.errors),
            "filtered_senders": result.filtered_senders,
        },
    )
    await record_scan(books, box, len(result.saved), None)
