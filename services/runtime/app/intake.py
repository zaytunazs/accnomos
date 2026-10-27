"""Outlook intake (F10): copy likely receipts/invoices from the user's mailbox into 00 Inbox.

Code only, no model call. The mailbox is only read (nothing is moved, flagged, marked read or
deleted); everything written goes to the user's own books folder:

    00 Inbox/<yyyy-mm-dd>_<sender-domain>_<original-name>   the copied attachment
    _System/Intake/seen.json                                what we have already copied (max 5,000, newest kept)
    _System/Intake/log/<yyyy-mm>.jsonl                      one line per saved file
    _System/audit/<yyyy-mm>.jsonl                           one line per scan (DEV.md convention)
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from accnomos_connectors.base import MailAttachment, MailMessage, MailProvider
from pydantic import BaseModel

from app.books import SYSTEM, Books, Rule, _month, _with_suffix, now
from app.paths import INBOX

log = logging.getLogger(__name__)

INTAKE = f"{SYSTEM}/Intake"
SEEN = f"{INTAKE}/seen.json"
INTAKE_LOG = f"{INTAKE}/log"
SEEN_MAX = 5000
ACTOR = "agent:intake"

MIN_SIZE = 10 * 1024
MAX_SIZE = 15 * 1024 * 1024
SIGNATURE_MAX = 40 * 1024
THRESHOLD = 0.4

ACCEPTED_TYPES = {"application/pdf", "image/jpeg", "image/jpg", "image/pjpeg", "image/png", "image/heic", "image/heif"}
ACCEPTED_EXTS = (".pdf", ".jpg", ".jpeg", ".png", ".heic")
# A letter must not come straight before the keyword ('border' is not an order); '_' and digits may.
KEYWORDS = re.compile(
    r"(?<![a-z])(receipt|invoice|inv[-_ ]?\d|bill|statement|order|payment|paid|vat|remittance|credit note|"
    r"pro ?forma|purchase|booking confirmation|tax)",
    re.IGNORECASE,
)
# Sharing a domain with these says nothing about the sender being "you".
PUBLIC_MAIL_DOMAINS = {
    "outlook.com", "hotmail.com", "hotmail.co.uk", "live.com", "live.co.uk", "msn.com", "gmail.com",
    "googlemail.com", "yahoo.com", "yahoo.co.uk", "icloud.com", "me.com", "aol.com", "btinternet.com",
    "sky.com", "virginmedia.com", "protonmail.com", "proton.me",
}
_UNSAFE = re.compile(r'[\\/:*?"<>|#%\x00-\x1f]+')  # OneDrive-forbidden and URL-awkward characters


class IntakeItem(BaseModel):
    name: str
    subject: str
    from_address: str
    score: float
    message_id: str
    attachment_id: str


class IntakeResult(BaseModel):
    scanned: int = 0
    candidates: int = 0
    saved: list[str] = []
    skipped_duplicates: int = 0
    dry_run: bool = False
    errors: list[dict[str, str]] = []
    items: list[IntakeItem] = []  # one per saved (or, in a dry run, would-be-saved) file


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
        self.seen_ids = {(s.get("message_id"), s.get("attachment_id")) for s in seen}
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
) -> IntakeResult:
    result = IntakeResult(dry_run=dry_run)
    seen: list[dict[str, Any]] = await books.read_json(SEEN, [])
    rules = await books.load_rules()
    dedupe = _Dedupe(books, seen)
    taken = {f.name for f in await books.list_files(INBOX)}
    started = now()
    new_seen: list[dict[str, Any]] = []
    log_lines: list[dict[str, Any]] = []

    messages = await mail.list_messages(started - timedelta(days=since_days), max_messages)
    result.scanned = len(messages)
    for m in messages:
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
            if (m.id, a.id) in dedupe.seen_ids:
                result.skipped_duplicates += 1
                continue
            try:
                data = await mail.download_attachment(m.id, a.id)
                if len(data) > MAX_SIZE:
                    continue
                sha = hashlib.sha256(data).hexdigest()
                if await dedupe.known(sha):
                    result.skipped_duplicates += 1
                    continue
                name = _free(target_name(m, a), taken)
                if not dry_run:
                    await books.storage.write(f"{INBOX}/{name}", data)  # >4 MB goes through an upload session
            except Exception as exc:  # noqa: BLE001
                log.warning("saving %s from %s failed: %s", a.name, m.id, exc)
                result.errors.append({"message": m.subject[:120], "attachment": a.name, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
                continue
            dedupe.hashes.add(sha)
            dedupe.seen_ids.add((m.id, a.id))
            at = now().isoformat()
            new_seen.append({"sha256": sha, "message_id": m.id, "attachment_id": a.id, "saved_as": f"{INBOX}/{name}", "at": at})
            log_lines.append({"at": at, "message_id": m.id, "from": m.from_address, "subject": m.subject[:200], "score": sc, "saved_as": f"{INBOX}/{name}", "sha256": sha})
            result.saved.append(name)
            result.items.append(IntakeItem(name=name, subject=m.subject[:200], from_address=m.from_address, score=sc, message_id=m.id, attachment_id=a.id))

    if not dry_run:
        await _record(books, new_seen, log_lines, result, since_days)
    return result


async def _record(books: Books, new_seen: list[dict[str, Any]], log_lines: list[dict[str, Any]], result: IntakeResult, since_days: int) -> None:
    if new_seen:
        await books._update_json(SEEN, [], lambda old: [*old, *new_seen][-SEEN_MAX:])
        by_month: dict[str, list[str]] = {}
        for line in log_lines:
            by_month.setdefault(_month(datetime.fromisoformat(line["at"])), []).append(json.dumps(line, ensure_ascii=False))
        for month, lines in by_month.items():
            text = ("\n".join(lines) + "\n").encode()
            await books._update(f"{INTAKE_LOG}/{month}.jsonl", lambda old, t=text: (old or b"") + t)
    await books.audit(ACTOR, "mail_scanned", {
        "since_days": since_days, "scanned": result.scanned, "candidates": result.candidates,
        "saved": len(result.saved), "skipped_duplicates": result.skipped_duplicates, "errors": len(result.errors),
    })
