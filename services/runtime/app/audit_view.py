"""The audit trail, read back for people: GET /audit (app/routes_audit.py). Reads only; never writes or edits a line.

Two logs feed it, both one JSON object per line in monthly files:

    _System/audit/{yyyy-mm}.jsonl          Books.audit(): {"ts", "actor", "action", "refs"}
    _System/audit/actions/{yyyy-mm}.jsonl  chat and voice actions (app/actions.py): {"ts", "action_id", "kind",
                                           "event": approving|executed|failed|rejected, "user", ...}

_System/audit/autopilot/ is not read: every Autopilot posting and every undo of one is already in the main log
(approve.py writes both), so reading it too would show each twice.

Every line becomes one AuditEntry with a plain-English summary from SUMMARIES below. A kind that is not in the
table still shows, as its own name ("Vehicle serviced"). Lines that do not parse are skipped, never fatal.
"""

from __future__ import annotations

import asyncio
import json
import logging
import posixpath
import re
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from pydantic import BaseModel

from app.actions import ACTIONS_AUDIT
from app.autopilot import AUTOPILOT
from app.books import AUDIT, LONDON, QUERIES_AUDIT, Books
from app.invoicing import money
from app.paths import REPORTS

log = logging.getLogger(__name__)
MAX_LIMIT = 500
DEFAULT_DAYS = 31  # the range when `from` is not given
MAX_DAYS = 366  # the widest range one request may read

# agent:<name> -> the chip the apps show. Anything else is its name, capitalised.
AGENT_LABELS = {
    "autopilot": "Autopilot",
    "intake": "Intake",
    "triage": "Triage",
    "planner": "Planner",
    "extractor": "Reader",
    "mileage": "Mileage",
    "folder-layout": "Folder tidy",
    "contacts": "Contacts",
    "backup": "Backup",
    "files": "Files",
    "close": "Month-end",
    "cis-reader": "CIS reader",
    "repeating": "Repeating",
}


class AuditRefs(BaseModel):
    proposal: str | None = None  # a Review card
    event: str | None = None  # a ledger event id
    invoice: str | None = None  # a sales invoice number
    action: str | None = None  # a chat or voice action id
    file: str | None = None  # a path in the user's OneDrive


class AuditEntry(BaseModel):
    ts: datetime
    actor: str  # as written: "user:<email>", "agent:<name>" or "accountant:<email>" (app/sharing.py)
    actor_kind: Literal["user", "agent", "accountant"]
    actor_label: str  # "You", "Autopilot", "Intake", "Triage", "Planner", ...
    event: str  # the audit action, e.g. "approved"; actions log lines are action_done / action_rejected / action_failed
    summary: str
    refs: AuditRefs


class AuditPage(BaseModel):
    start: date
    end: date
    entries: list[AuditEntry]  # newest first
    truncated: bool  # more lines matched than `limit`


# --------------------------------------------------------------------------- #
# Summaries
# --------------------------------------------------------------------------- #


def _n(refs: dict[str, Any], key: str) -> int:
    v = refs.get(key)
    if isinstance(v, list):
        return len(v)
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else many or one + 's'}"


def _pounds(refs: dict[str, Any], key: str) -> str:
    v = refs.get(key)
    return f" for {money(int(v))}" if isinstance(v, int) else ""


def _qty(v: Any) -> str:
    """7.5 stays 7.5; 100.0 is 100."""
    f = float(v)
    return str(int(f)) if f.is_integer() else f"{f:g}"


def _inv(refs: dict[str, Any]) -> str:
    return str(refs.get("invoice") or "")


def _provider(refs: dict[str, Any]) -> str:
    return {"stripe": "Stripe", "paypal": "PayPal", "paypalme": "PayPal.me"}.get(
        str(refs.get("provider")), "a provider"
    )


def _fields(refs: dict[str, Any]) -> str:
    f = refs.get("fields")
    return f" ({', '.join(str(x).replace('_', ' ') for x in f)})" if isinstance(f, list) and f else ""


def _plain(md: Any) -> str:
    """One line of markdown as text: no **, _, ` or links, at most 160 characters."""
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", str(md or ""))
    s = re.sub(r"[*_`#>]+", "", s)
    s = " ".join(s.split())
    return s if len(s) <= 160 else s[:159].rstrip() + "…"


def _moved(refs: dict[str, Any]) -> str:
    moved = [m for m in refs.get("moved") or [] if isinstance(m, dict)]
    return ", ".join(f"{m.get('old')} → {m.get('new')}" for m in moved) or "none"


VAT_STATUS = {"registered": "VAT-registered", "not_registered": "not VAT-registered", "unknown": "not known"}

# kind -> (refs, who) -> sentence. `who` is "Screwfix £12.00" when the line names a proposal we can read,
# otherwise "a document".
Summary = Callable[[dict[str, Any], str], str]
SUMMARIES: dict[str, Summary] = {
    # Review and the ledger
    "proposed": lambda r, w: (
        (
            f"Read {w} and moved it to Needs a look"
            if r.get("status") == "needs_a_look"
            else f"Read {w} and proposed an entry"
        )
        + (f" (emailed to {r['mailbox']})" if r.get("mailbox") else "")
    ),
    "approved": lambda r, w: f"Posted {w} to the ledger",
    "rejected": lambda r, w: f"Rejected {w}" + (f": {r['reason']}" if r.get("reason") else ""),
    "undone": lambda r, w: (
        f"Undid the entry for {w}"
        + (" that Autopilot posted" if r.get("originally_approved_by") == AUTOPILOT else "")
        + "; it is back in Review"
    ),
    "extract_failed": lambda r, w: f"Could not read {posixpath.basename(str(r.get('path') or '')) or 'a file'}",
    "books_rebuild_failed": lambda r, w: "Could not rebuild Books.xlsx; the ledger itself is unchanged",
    "rule_removed": lambda r, w: f"Stopped Autopilot for {r.get('supplier_key') or 'a supplier'}",
    "plan_applied": lambda r, w: (
        f"Applied the day plan for {r.get('date', 'a day')}: " + _plural(_n(r, "events"), "entry", "entries")
    ),
    # Mail
    "mail_scanned": lambda r, w: (
        "Checked Outlook"
        + (f" ({r['mailbox']})" if r.get("mailbox") else "")
        + f": {_n(r, 'saved')} saved from "
        + _plural(_n(r, "candidates"), "candidate")
    ),
    "mailbox_added": lambda r, w: f"Linked the mailbox {r.get('address') or 'a mailbox'} for receipts",
    "mailbox_updated": lambda r, w: f"Changed which mail is read from {r.get('address') or 'a mailbox'}",
    "mailbox_removed": lambda r, w: f"Unlinked the mailbox {r.get('address') or 'a mailbox'}",
    "mail_triaged": lambda r, w: (
        f"Sorted the inbox: {_plural(_n(r, 'threads'), 'thread')} from " + _plural(_n(r, "scanned"), "message")
    ),
    "mail_draft_created": lambda r, w: "Saved a reply in your Outlook drafts (not sent)",
    # Bank
    "bank_imported": lambda r, w: (
        f"Imported a {r.get('bank') or 'bank'} statement: " + _plural(_n(r, "new"), "new line")
    ),
    "bank_matched": lambda r, w: f"Matched a bank line to {_plural(_n(r, 'events'), 'entry', 'entries')}",
    "bank_unmatched": lambda r, w: "Undid a bank line match",
    "bank_transfer": lambda r, w: "Marked a bank line as a transfer between your own accounts",
    "bank_ignored": lambda r, w: "Marked a bank line as nothing to book",
    "bank_expense_proposed": lambda r, w: "Proposed an expense from a bank line",
    "bank_private_proposed": lambda r, w: "Marked a bank line as private spending",
    "bank_rule_created": lambda r, w: "Added a bank rule",
    "bank_rule_updated": lambda r, w: "Edited a bank rule",
    "bank_rule_deleted": lambda r, w: "Deleted a bank rule",
    "bank_rules_reordered": lambda r, w: "Reordered the bank rules",
    "bank_reconciled": lambda r, w: f"Reconciled a bank line ({r.get('kind') or 'match'}) through Review approval",
    "bank_feed_connected": lambda r, w: (
        f"Connected a bank feed from {r.get('bank') or 'a bank'}" + (" (sandbox)" if r.get("sandbox") else "")
    ),
    "bank_feed_synced": lambda r, w: (
        "Fetched the bank feed: "
        + _plural(_n(r, "new"), "new line")
        + (f", {_plural(_n(r, 'duplicates'), 'line')} already in a statement" if r.get("duplicates") else "")
    ),
    "bank_feed_reconfirmed": lambda r, w: f"Reconfirmed the {r.get('bank') or 'bank'} feed for another 90 days",
    "bank_feed_disconnected": lambda r, w: f"Disconnected the {r.get('bank') or 'bank'} feed",
    # Sales invoices
    "invoice_profile_saved": lambda r, w: "Saved your invoice details",
    "vat_schemes_saved": lambda r, w: "Saved your VAT scheme",
    "invoice_created": lambda r, w: f"Created invoice {_inv(r)}" + _pounds(r, "total_pence"),
    "invoice_edited": lambda r, w: f"Edited invoice {_inv(r)}" + _pounds(r, "total_pence"),
    "invoice_posted": lambda r, w: f"Posted invoice {_inv(r)} to the ledger",
    "invoice_sent": lambda r, w: f"Emailed invoice {_inv(r)}" + (f" to {r['to']}" if r.get("to") else ""),
    "invoice_reminder_sent": lambda r, w: f"Sent a reminder for invoice {_inv(r)}",
    "invoice_paid": lambda r, w: f"Marked invoice {_inv(r)} as paid",
    "invoice_part_paid": lambda r, w: f"Recorded a part payment on invoice {_inv(r)}",
    "invoice_unmarked_paid": lambda r, w: f"Took back the Mark paid on invoice {_inv(r)}",
    # Payment chasing (app/chasing.py)
    "chasing_config_saved": lambda r, w: "Saved the payment-chasing reminder steps",
    # Payments (app/payments.py) and credit notes (app/credit_notes.py)
    "payment_recorded": lambda r, w: (
        ("Recorded money in" if r.get("side") == "sale" else "Recorded a payment out")
        + _pounds(r, "amount_pence")
        + (f" against invoice {_inv(r)}" if r.get("invoice") else "")
        + (f" (CIS deduction {money(int(r['cis_deduction_pence']))})" if r.get("cis_deduction_pence") else "")
    ),
    "payment_removed": lambda r, w: "Removed a payment; its entry was reversed",
    # CIS and the VAT reverse charge (app/cis.py, app/cis_readings.py, app/routes_cis.py)
    "cis_settings_saved": lambda r, w: "Saved your CIS settings",
    "cis_statement_added": lambda r, w: (
        f"Added a CIS statement from {r.get('contractor') or 'a contractor'}" + _pounds(r, "deduction_pence")
    ),
    "cis_statement_removed": lambda r, w: "Removed a CIS statement",
    "cis_document_read": lambda r, w: (
        f"Read {posixpath.basename(str(r.get('file') or '')) or 'a document'} as "
        + (
            "a CIS statement"
            if r.get("kind") == "cis_statement"
            else "a reverse-charge invoice"
            if r.get("kind") == "reverse_charge_invoice"
            else "something else"
        )
        + "; it waits for you on the CIS page"
    ),
    "cis_reading_approved": lambda r, w: "Approved a CIS document the AI read",
    "cis_reading_rejected": lambda r, w: "Rejected a CIS document the AI read",
    "reverse_charge_bill_posted": lambda r, w: (
        f"Posted a reverse-charge bill from {r.get('supplier') or 'a subcontractor'}"
    ),
    "cis_subcontractor_saved": lambda r, w: "Saved a subcontractor's CIS details",
    "cis_payment_recorded": lambda r, w: (
        "Recorded a payment to a subcontractor under CIS"
        + (f", deducting {money(int(r['deduction_pence']))}" if isinstance(r.get("deduction_pence"), int) else "")
    ),
    "cis_payment_removed": lambda r, w: "Removed a CIS payment to a subcontractor; its entry was reversed",
    "cis_return_prepared": lambda r, w: (
        f"Prepared the CIS300 for the month to {r.get('tax_month_end') or '?'} (not submitted to HMRC)"
    ),
    "quote_saved": lambda r, w: f"Saved quote {r.get('quote') or ''}" + _pounds(r, "total_pence"),
    "payment_line_not_matched": lambda r, w: "Recorded a payment but could not match its bank line",
    # Online payments (app/online_payments.py)
    "payment_provider_connected": lambda r, w: (
        f"Connected {_provider(r)}" + (" (test mode)" if r.get("test") else "") + " for payment links"
    ),
    "payment_provider_disconnected": lambda r, w: f"Disconnected {_provider(r)}",
    "payment_link_created": lambda r, w: (
        f"Made a {_provider(r)} payment link" + _pounds(r, "amount_pence") + f" for invoice {_inv(r)}"
    ),
    "payment_link_removed": lambda r, w: f"Removed the {_provider(r)} payment link from invoice {_inv(r)}",
    "online_payment_approved": lambda r, w: (
        f"Posted a {_provider(r)} payment"
        + _pounds(r, "amount_pence")
        + f" against invoice {_inv(r)}"
        + (f", fee £{int(r['fee_pence']) // 100}.{int(r['fee_pence']) % 100:02d}" if r.get("fee_pence") else "")
    ),
    "payout_matched": lambda r, w: (
        f"Matched a bank line as a {_provider(r)} payout"
        + _pounds(r, "amount_pence")
        + ", moved from clearing to the bank"
    ),
    "payout_unmatched": lambda r, w: f"Unmatched a {_provider(r)} payout; the money is back in clearing",
    # Credits on contacts (app/credits.py)
    "credit_applied": lambda r, w: "Applied a credit on account to another document" + _pounds(r, "amount_pence"),
    "credit_refunded": lambda r, w: (
        ("Refunded a customer's credit" if r.get("side") == "sale" else "Recorded a supplier refunding a credit")
        + _pounds(r, "amount_pence")
    ),
    "refund_line_not_matched": lambda r, w: "Recorded a refund but could not match its bank line",
    "credit_use_removed": lambda r, w: (
        "Took back a refund of a credit; its entry was reversed"
        if r.get("kind") == "refund"
        else "Took back a credit applied to a document"
    ),
    "credit_note_created": lambda r, w: (
        f"Created credit note {r.get('credit_note') or ''} for invoice {_inv(r)}" + _pounds(r, "total_pence")
    ),
    "credit_note_posted": lambda r, w: f"Posted credit note {r.get('credit_note') or ''} to the ledger",
    "credit_note_sent": lambda r, w: (
        f"Emailed credit note {r.get('credit_note') or ''}" + (f" to {r['to']}" if r.get("to") else "")
    ),
    "credit_note_voided": lambda r, w: (
        f"Voided credit note {r.get('credit_note') or ''}" + (f": {r['reason']}" if r.get("reason") else "")
    ),
    "invoice_voided": lambda r, w: f"Voided invoice {_inv(r)}" + (f": {r['reason']}" if r.get("reason") else ""),
    # Products and services, quotes, purchase orders, repeating, statements (app/items.py, quotes.py, ...)
    "item_created": lambda r, w: f"Added product or service {r.get('item') or ''}",
    "item_edited": lambda r, w: f"Edited product or service {r.get('item') or ''}",
    "items_imported": lambda r, w: (
        f"Imported products and services from CSV: {_n(r, 'created')} added, {_n(r, 'updated')} updated, "
        f"{_n(r, 'skipped')} skipped"
    ),
    "quote_created": lambda r, w: f"Created quote {r.get('quote') or ''}" + _pounds(r, "total_pence"),
    "quote_edited": lambda r, w: f"Edited quote {r.get('quote') or ''}" + _pounds(r, "total_pence"),
    "quote_sent": lambda r, w: f"Emailed quote {r.get('quote') or ''}" + (f" to {r['to']}" if r.get("to") else ""),
    "quote_marked_sent": lambda r, w: f"Marked quote {r.get('quote') or ''} as sent (not emailed from here)",
    "quote_accepted": lambda r, w: f"Quote {r.get('quote') or ''} was accepted",
    "quote_declined": lambda r, w: f"Quote {r.get('quote') or ''} was declined",
    "quote_converted": lambda r, w: (
        f"Made invoice draft {_inv(r)} from quote {r.get('quote') or ''}" + _pounds(r, "total_pence")
    ),
    "purchase_order_created": lambda r, w: f"Created purchase order {r.get('order') or ''}" + _pounds(r, "total_pence"),
    "purchase_order_edited": lambda r, w: f"Edited purchase order {r.get('order') or ''}" + _pounds(r, "total_pence"),
    "purchase_order_approved": lambda r, w: f"Approved purchase order {r.get('order') or ''}",
    "purchase_order_sent": lambda r, w: (
        f"Emailed purchase order {r.get('order') or ''}" + (f" to {r['to']}" if r.get("to") else "")
    ),
    "purchase_order_marked_sent": lambda r, w: f"Marked purchase order {r.get('order') or ''} as sent",
    "purchase_order_cancelled": lambda r, w: (
        f"Cancelled purchase order {r.get('order') or ''}" + (f": {r['reason']}" if r.get("reason") else "")
    ),
    "purchase_order_converted": lambda r, w: (
        f"Wrote a bill for review from purchase order {r.get('order') or ''}" + _pounds(r, "total_pence")
    ),
    "purchase_order_matched": lambda r, w: f"Matched a supplier bill to purchase order {r.get('order') or ''}",
    "purchase_order_unlinked": lambda r, w: f"Unlinked the bill from purchase order {r.get('order') or ''}",
    "repeating_created": lambda r, w: f"Set up repeating {r.get('kind') or 'item'} {r.get('template') or ''}",
    "repeating_edited": lambda r, w: f"Edited repeating {r.get('kind') or 'item'} {r.get('template') or ''}",
    "repeating_paused": lambda r, w: f"Paused repeating {r.get('kind') or 'item'} {r.get('template') or ''}",
    "repeating_resumed": lambda r, w: f"Resumed repeating {r.get('kind') or 'item'} {r.get('template') or ''}",
    "repeating_deleted": lambda r, w: f"Stopped repeating {r.get('kind') or 'item'} {r.get('template') or ''}",
    "repeating_generated": lambda r, w: (
        f"Repeating {r.get('template') or ''} made {r.get('what') or 'a document'} for {r.get('date') or 'a date'}: "
        f"{r.get('outcome') or 'drafted'}"
    ),
    "repeating_problem": lambda r, w: (
        f"Repeating {r.get('template') or ''} could not finish for {r.get('date') or 'a date'}: "
        f"{_plain(r.get('error')) or 'unknown error'}"
    ),
    "statement_sent": lambda r, w: (
        f"Emailed a statement to {r.get('contact') or 'a customer'}"
        + (f" ({r['to']})" if r.get("to") else "")
        + _pounds(r, "closing_pence")
    ),
    # Jobs, staff, timesheets
    "job_created": lambda r, w: "Added a job",
    "job_updated": lambda r, w: "Updated a job" + (f" ({r['status']})" if r.get("status") else ""),
    "job_deleted": lambda r, w: "Deleted a job",
    "staff_created": lambda r, w: "Added a member of staff",
    "staff_updated": lambda r, w: "Updated a member of staff",
    "staff_deleted": lambda r, w: "Removed a member of staff",
    "timesheet_added": lambda r, w: "Logged time" + (f": {_qty(r['hours'])} hours" if r.get("hours") else ""),
    "timesheet_updated": lambda r, w: "Changed a timesheet entry" + _fields(r),
    "timesheet_deleted": lambda r, w: "Deleted a timesheet entry",
    "timesheet_overtime_set": lambda r, w: (
        f"Set {_plural(len(r.get('entries') or []), 'timesheet entry', 'timesheet entries')} to "
        f"{r.get('multiplier', '')}x pay (overtime)"
    ),
    "timesheets_invoiced": lambda r, w: (
        f"Marked {_plural(_n(r, 'entries'), 'timesheet entry', 'timesheet entries')} as billed on invoice {_inv(r)}"
    ),
    "timesheets_not_invoiced": lambda r, w: f"Could not mark timesheets as billed on invoice {_inv(r)}",
    # Payroll
    "payroll_prepared": lambda r, w: (
        f"Prepared payroll for {r.get('period', 'a period')}"
        + (f": estimated gross {money(int(r['est_gross_pence']))}" if isinstance(r.get("est_gross_pence"), int) else "")
    ),
    "payroll_edited": lambda r, w: f"Edited payroll for {r.get('period', 'a period')}",
    "payroll_exported": lambda r, w: f"Exported payroll for {r.get('period', 'a period')} for your payroll software",
    "payroll_confirmed": lambda r, w: (
        f"Posted payroll for {r.get('period', 'a period')} to the ledger" + _pounds(r, "gross_pence")
    ),
    "payroll_reopened": lambda r, w: f"Reopened payroll for {r.get('period', 'a period')}; its entries were undone",
    # PAYE payroll (app/payrun.py, app/routes_payrun.py)
    "payroll_employer_saved": lambda r, w: "Saved the payroll settings (PAYE references, pension scheme)",
    "payroll_employee_saved": lambda r, w: "Saved an employee's payroll record",
    "payroll_employee_deleted": lambda r, w: "Removed an employee who was never paid",
    "payrun_prepared": lambda r, w: f"Prepared pay run {r.get('run', '')}".rstrip(),
    "payrun_edited": lambda r, w: f"Edited pay run {r.get('run', '')}".rstrip(),
    "payrun_discarded": lambda r, w: f"Set aside the draft pay run {r.get('run', '')}".rstrip(),
    "payrun_proposed": lambda r, w: f"Sent pay run {r.get('run', '')} to Review".replace("  ", " "),
    "payrun_back_to_draft": lambda r, w: f"Took pay run {r.get('run', '')} back to draft".replace("  ", " "),
    "payrun_posted": lambda r, w: f"Posted pay run {r.get('run', '')} to the ledger".replace("  ", " "),
    "rti_fps_generated": lambda r, w: (
        f"Generated the FPS file for pay run {r.get('run', '')} (not sent to HMRC)".replace("  ", " ")
    ),
    "rti_eps_generated": lambda r, w: (
        f"Generated the EPS file for tax month {r.get('tax_month', '')} (not sent to HMRC)"
    ),
    # Contacts
    "contacts_refreshed": lambda r, w: f"Refreshed contacts from the ledger: {_plural(_n(r, 'contacts'), 'contact')}",
    "contact_edited": lambda r, w: "Edited a contact" + _fields(r),
    "contact_vat_status": lambda r, w: (
        "Set a supplier as " + VAT_STATUS.get(str(r.get("vat_status")), str(r.get("vat_status")))
    ),
    "contact_vat_checked": lambda r, w: (
        f"Checked VAT number {r.get('vrn', '')} with HMRC: "
        + ("registered" if r.get("registered") else "not VAT-registered")
        + {"hmrc-sandbox": " (HMRC sandbox)", "sample": " (sample)"}.get(str(r.get("source")), "")
    ),
    "contacts_imported": lambda r, w: (
        f"Imported {_plural(_n(r, 'added'), 'contact')} from your phone"
        + (f" ({_plural(_n(r, 'updated'), 'contact')} updated)" if _n(r, "updated") else "")
        if str(r.get("source")) == "phone"
        else "Imported contacts from Outlook"
    ),
    "contacts_not_same": lambda r, w: "Said some contacts are not the same business",
    "contacts_merged": lambda r, w: f"Merged into one ({r.get('name', 'a contact')})",
    "contacts_merge_undone": lambda r, w: "Undid a contact merge",
    # Import history (app/import_history.py)
    "import_file_added": lambda r, w: (
        f"Uploaded {str(r.get('kind') or 'a file').replace('_', ' ')} for the import"
        + (f": {_plural(_n(r, 'rows'), 'row')}" if r.get("rows") else "")
    ),
    "import_discarded": lambda r, w: "Started the import again",
    "opening_balances_posted": lambda r, w: (
        f"Posted opening balances at {r.get('conversion_date', 'the conversion date')}: "
        + _plural(_n(r, "accounts"), "account")
        + (f", {_plural(_n(r, 'open_items'), 'open item')}" if _n(r, "open_items") else "")
        + ("; reconciled to the source" if r.get("proved") else "; the reconciliation needs a look")
    ),
    "opening_balances_undone": lambda r, w: "Undid the opening balances; the entry was reversed",
    # Vehicles and mileage
    "vehicle_added": lambda r, w: "Added a vehicle",
    "vehicle_changed": lambda r, w: "Changed a vehicle" + _fields(r),
    "vehicle_deleted": lambda r, w: "Removed a vehicle",
    "mileage_added": lambda r, w: "Logged a journey" + (f": {_qty(r['miles'])} miles" if r.get("miles") else ""),
    "mileage_changed": lambda r, w: "Changed a journey" + _fields(r),
    "mileage_deleted": lambda r, w: "Deleted a journey",
    "mileage_proposed": lambda r, w: (
        f"Proposed a mileage claim: {_plural(_n(r, 'journeys'), 'journey')}" + _pounds(r, "pence")
    ),
    "mileage_refreshed": lambda r, w: (
        f"Updated the mileage claim: {_plural(_n(r, 'journeys'), 'journey')}" + _pounds(r, "pence")
    ),
    # MTD Income Tax, self-employment (app/routes_itsa.py)
    "itsa_update_submitted": lambda r, w: (
        f"Sent the {r.get('tax_year')} self-employment update to {r.get('period_end')} to HMRC "
        f"({'HMRC sandbox' if r.get('environment') != 'production' else 'HMRC'})"
        + (f", {'cash basis' if r.get('basis') == 'cash' else 'traditional accounting'}" if r.get("basis") else "")
        + ("" if r.get("matches") else "; it did not match the books when saved")
    ),
    "itsa_calculation_saved": lambda r, w: f"Saved HMRC's {r.get('tax_year')} tax calculation",
    "itsa_basis_changed": lambda r, w: (
        "Changed the self-employment accounting basis to "
        + ("traditional accounting" if r.get("to") == "traditional" else "the cash basis")
    ),
    "itsa_final_declaration_submitted": lambda r, w: (
        f"Made the {r.get('tax_year')} final declaration to "
        f"{'HMRC sandbox' if r.get('environment') != 'production' else 'HMRC'}"
    ),
    # Reports
    "report_exported": lambda r, w: (
        "Saved "
        + {
            "pl": "the profit and loss",
            "aged": "the aged debtors and creditors",
            "vat": "the VAT summary",
            "trend": "the monthly trend",
            "all": "all reports",
        }.get(str(r.get("report")), "a report")
        + f" to {REPORTS} as a spreadsheet"
    ),
    # Accounting tools (app/chart.py, manual_journals.py, fixed_assets.py, recode.py, tracking.py, budgets.py)
    "account_added": lambda r, w: f"Added account {r.get('code', '')} to the chart of accounts".replace("  ", " "),
    "account_edited": lambda r, w: f"Changed account {r.get('code', '')} in the chart of accounts".replace("  ", " "),
    "account_deleted": lambda r, w: f"Deleted unused account {r.get('code', '')} from the chart".replace("  ", " "),
    "accounts_imported": lambda r, w: (
        f"Imported the chart of accounts: {_n(r, 'added')} added, {_n(r, 'updated')} updated"
    ),
    "journal_drafted": lambda r, w: f"Saved journal {r.get('number', '')} as a draft" + _pounds(r, "total_pence"),
    "journal_approved": lambda r, w: (
        f"Approved journal {r.get('number', '')}: posted to the ledger"
        + (" with its reversal" if r.get("reversal") else "")
    ),
    "journal_discarded": lambda r, w: f"Discarded draft journal {r.get('number', '')}",
    "journal_voided": lambda r, w: f"Voided journal {r.get('number', '')} with a mirror entry",
    "asset_registered": lambda r, w: f"Registered fixed asset {r.get('number', '')}" + _pounds(r, "cost_pence"),
    "asset_removed": lambda r, w: f"Took fixed asset {r.get('number', '')} off the register",
    "lines_recoded": lambda r, w: f"Recoded {_plural(_n(r, 'lines'), 'line')} with adjusting entries",
    "tracking_category_added": lambda r, w: f"Added the tracking category {r.get('name', '')}".rstrip(),
    "tracking_category_renamed": lambda r, w: "Renamed a tracking category",
    "tracking_category_deleted": lambda r, w: "Deleted an unused tracking category",
    "tracking_option_added": lambda r, w: f"Added the tracking option {r.get('name', '')}".rstrip(),
    "tracking_option_edited": lambda r, w: "Changed a tracking option",
    "budget_saved": lambda r, w: f"Saved the budget from {r.get('start', 'a month')}",
    "report_saved": lambda r, w: (
        f"Saved {str(r.get('report') or 'a report').replace('-', ' ')} to {REPORTS}"
        f" as {str(r.get('format') or 'a file').upper()}"
    ),
    "export_mapping_changed": lambda r, w: f"Changed the account mapping for {r.get('package') or 'another package'}",
    "report_favourites_changed": lambda r, w: "Changed your starred reports",
    # Your data
    "data_exported": lambda r, w: f"Saved your full data export to {REPORTS}/Exports as a zip",
    # Load sample books (app/sample_books.py)
    "sample_books_started": lambda r, w: (
        f"Started loading the sample books ({r.get('business') or 'a fictional company'})"
    ),
    "sample_books_loaded": lambda r, w: (
        f"Loaded the sample books ({r.get('business') or 'a fictional company'}): "
        f"{_plural(_n(r, 'events'), 'ledger entry', 'ledger entries')}"
    ),
    # Personal finances (app/personal.py)
    "personal_categories_saved": lambda r, w: "Changed your personal spending categories",
    "personal_budgets_saved": lambda r, w: "Changed your personal monthly budgets",
    "personal_rule_added": lambda r, w: "Added personal spending rules",
    "personal_rule_deleted": lambda r, w: "Deleted a personal spending rule",
    "personal_line_categorised": lambda r, w: "Put a bank line in a personal spending category",
    "personal_goal_saved": lambda r, w: "Saved a savings goal",
    "personal_goal_deleted": lambda r, w: "Deleted a savings goal",
    # Landlords (app/property.py, app/routes_property.py)
    "property_added": lambda r, w: f"Added a let property: {r.get('name') or 'a property'}",
    "property_updated": lambda r, w: f"Changed the details of {r.get('name') or 'a let property'}",
    "property_settings_saved": lambda r, w: (
        "Changed your landlord settings" + (" (landlord mode on)" if r.get("landlord_mode") else "")
    ),
    "property_tagged": lambda r, w: "Put a ledger entry on a let property",
    "property_untagged": lambda r, w: "Took a ledger entry off a let property",
    "property_entry": lambda r, w: f"Recorded an entry{_pounds(r, 'pence')} on a let property",
    "property_document_read": lambda r, w: (
        f"Read {posixpath.basename(str(r.get('file') or '')) or 'a document'} as "
        + (
            "a letting statement"
            if r.get("kind") == "letting_statement"
            else "a mortgage statement"
            if r.get("kind") == "mortgage_statement"
            else "an insurance schedule"
            if r.get("kind") == "insurance"
            else "a property bill"
            if r.get("kind") == "invoice"
            else "something else"
        )
        + "; it waits for you on the Property page"
    ),
    "property_reading_approved": lambda r, w: "Approved a property document the AI read",
    "property_reading_rejected": lambda r, w: "Rejected a property document the AI read",
    "property_mtd_exported": lambda r, w: (
        f"Saved the UK property update for {r.get('tax_year') or 'a tax year'} as a file ready to submit"
    ),
    "property_mtd_submitted": lambda r, w: (
        f"Sent a UK property {r.get('kind') or 'update'} for {r.get('tax_year') or 'a tax year'} to HMRC's sandbox"
        + (f" (HMRC answered {r['status']})" if r.get("status") else "")
    ),
    # Files page, archive and backups (app/files.py, app/archive.py, app/backups.py)
    "files_moved": lambda r, w: f"Moved {_plural(_n(r, 'moved'), 'file')} to {r.get('to') or 'another folder'}",
    "file_renamed": lambda r, w: (
        f"Renamed {posixpath.basename(str(r.get('old') or '')) or 'a file'} to "
        f"{posixpath.basename(str(r.get('new') or '')) or 'a new name'}"
    ),
    "files_trashed": lambda r, w: f"Moved {_plural(_n(r, 'moved'), 'file')} to _Trash (nothing was deleted)",
    "files_archived": lambda r, w: (
        f"Archived {_plural(_n(r, 'files'), 'file')} up to {r.get('up_to') or 'a year'}"
        + (f" into {', '.join(map(str, r['years']))}" if isinstance(r.get("years"), list) and r["years"] else "")
        + (" and zipped them" if r.get("zips") else "")
    ),
    "archive_undone": lambda r, w: (
        f"Undid an archive run: {_plural(_n(r, 'files'), 'file')} moved back"
        + (f", {_n(r, 'skipped')} no longer in the archive" if _n(r, "skipped") else "")
    ),
    "backup_created": lambda r, w: (
        f"Backed up your books: {_plural(_n(r, 'files'), 'file')} in "
        f"{posixpath.basename(str(r.get('file') or '')) or 'a backup'}"
        + (f"; {_plural(_n(r, 'retired'), 'older backup')} moved to _Trash" if _n(r, "retired") else "")
    ),
    "backup_verified": lambda r, w: (
        f"Checked {posixpath.basename(str(r.get('file') or '')) or 'a backup'}: "
        + ("checksum and every file match" if r.get("ok") else _plural(_n(r, "problems"), "problem"))
    ),
    "backup_restored": lambda r, w: (
        f"Restored {posixpath.basename(str(r.get('file') or '')) or 'a backup'}: "
        f"{_plural(_n(r, 'restored'), 'file')} added, {_n(r, 'replaced')} replaced (old copies in _Trash)"
    ),
    # Back up now and earlier files (app/full_backup.py, app/previous_files.py)
    "full_backup_created": lambda r, w: (
        f"Full backup to {r.get('folder') or 'Accnomos Backups'}: {_plural(_n(r, 'ledger_files'), 'file')} from "
        f"the ledger and settings, Books.xlsx and an index of {_plural(_n(r, 'documents'), 'document')}"
    ),
    "previous_files_queued": lambda r, w: (
        f"Chose {_plural(_n(r, 'files'), 'earlier file')} to be read; "
        f"{_plural(_n(r, 'moved_to_inbox'), 'file')} moved into the Inbox"
    ),
    "previous_files_left": lambda r, w: f"Left {_plural(_n(r, 'files'), 'earlier file')} alone (not to be read)",
    "file_settings_saved": lambda r, w: (
        f"Backup settings: keep {_n(r, 'backup_keep')}"
        + (", back up monthly" if r.get("monthly_backup") else ", no monthly backup")
    ),
    # The month-end close (app/month_end.py)
    "close_run": lambda r, w: (
        f"Ran the month-end close for {r.get('month', 'a month')}: "
        + (
            "ready to close"
            if r.get("can_close")
            else f"{_plural(_n(r, 'needs_you'), 'thing')} for you, {_n(r, 'blocking')} blocking"
        )
    ),
    "month_closed": lambda r, w: f"Closed {r.get('month', 'a month')} (snapshot {str(r.get('snapshot', ''))[:12]})",
    "month_reclosed": lambda r, w: (
        f"Re-closed {r.get('month', 'a month')} after {_plural(_n(r, 'changes'), 'change')}"
        f" (snapshot {str(r.get('snapshot', ''))[:12]})"
    ),
    # To-dos and housekeeping
    "todo_added": lambda r, w: "Added a to-do",
    "shopping_added": lambda r, w: f"Added {r.get('description') or 'an item'} to the shopping list",
    "shopping_ticked": lambda r, w: "Ticked off a shopping list item",
    "shopping_unticked": lambda r, w: "Put a shopping list item back on the list",
    "shopping_removed": lambda r, w: "Removed a shopping list item",
    "item_match": lambda r, w: "Said two items are the same product" if r.get("same") else "Said two items differ",
    "todo_deleted": lambda r, w: "Ticked off a to-do",
    "folders_renamed": lambda r, w: f"Renamed old folders: {_moved(r)}",
    "profile_saved": lambda r, w: (
        f"Saved the profile ({str(r.get('kind', '')).replace('_', ' ')})"
        + (
            f", was {str(r['kind_was']).replace('_', ' ')}"
            if r.get("kind_was") and r.get("kind_was") != r.get("kind")
            else ""
        )
    ),
    # Your accountant (app/accountant.py, app/queries.py, app/portal.py)
    "accountant_invited": lambda r, w: (
        f"Gave {r['email']} {_access(r)} to these books" + (" (shared in OneDrive by hand)" if _manual(r) else "")
    ),
    "accountant_removed": lambda r, w: f"Took away {r['email']}'s access to these books",
    "accountant_team_opted_in": lambda r, w: f"Opted in to reviews by Accnomos accountants ({_access(r)})",
    "accountant_team_opted_out": lambda r, w: "Stopped reviews by Accnomos accountants",
    "accountant_profile_saved": lambda r, w: "Updated what your accountant sees about these books",
    "accountant_client_added": lambda r, w: "Added a client's books to the Accountant portal",
    "accountant_client_removed": lambda r, w: "Removed a client's books from the Accountant portal",
    "query_opened": lambda r, w: f"Asked a query about {_about(r)}",
    "query_replied": lambda r, w: "Answered a query",
    "query_resolved": lambda r, w: "Marked a query as resolved",
    # Ask (chat and voice) actions, from _System/audit/actions/
    "action_done": lambda r, w: (
        f"Approved from Ask: {_plain(r.get('result_md') or r.get('summary_md')) or 'an action'}"
    ),
    "action_rejected": lambda r, w: (
        f"Said no in Ask: {_plain(r.get('summary_md')) or 'an action'}"
        + (f" ({r['reason']})" if r.get("reason") else "")
    ),
    "action_failed": lambda r, w: f"An action from Ask did not finish: {_plain(r.get('error')) or 'unknown error'}",
}


def summarise(event: str, refs: dict[str, Any], who: str = "a document") -> str:
    """The sentence for one line; the kind's own name when it is not in SUMMARIES or its refs are odd."""
    fn = SUMMARIES.get(event)
    if fn is not None:
        try:
            return fn(refs, who)
        except (KeyError, TypeError, ValueError, AttributeError):
            log.warning("audit: could not summarise a %s line", event)
    return event.replace("_", " ").capitalize() or "Activity"


# --------------------------------------------------------------------------- #
# Normalising
# --------------------------------------------------------------------------- #


def _access(r: dict[str, Any]) -> str:
    return "view and edit access" if r.get("role") == "edit" else "view-only access"


def _manual(r: dict[str, Any]) -> bool:
    return r.get("method") == "manual"


_ABOUT = {
    "transaction": "a transaction",
    "document": "a document",
    "proposal": "a Review card",
    "bank_line": "a bank line",
    "invoice": "an invoice",
}


def _about(r: dict[str, Any]) -> str:
    return _ABOUT.get(str(r.get("about")), "the books")


def actor_of(actor: str) -> tuple[Literal["user", "agent", "accountant"], str]:
    """(kind, label). The owner is always "You": one OneDrive is one business. Their accountant is named."""
    if actor.startswith("user:"):
        return "user", "You"
    if actor.startswith("accountant:"):
        return "accountant", f"Accountant ({actor.removeprefix('accountant:')})"
    name = actor.removeprefix("agent:")
    return "agent", AGENT_LABELS.get(name) or name.replace("-", " ").replace("_", " ").capitalize() or "Accnomos"


def _str(v: Any) -> str | None:
    return str(v) if isinstance(v, str | int) and str(v) else None


def refs_of(refs: dict[str, Any]) -> AuditRefs:
    moved = refs.get("moved") if isinstance(refs.get("moved"), list) else []
    first_moved = moved[0].get("new") if moved and isinstance(moved[0], dict) else None
    return AuditRefs(
        proposal=_str(refs.get("proposal")),
        event=_str(refs.get("event")),
        invoice=_str(refs.get("invoice")),
        action=_str(refs.get("action")),
        file=_str(refs.get("file") or refs.get("path") or first_moved),
    )


def _parse_ts(raw: Any) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return ts if ts.tzinfo is not None else None


def from_books_line(line: dict[str, Any], names: dict[str, str]) -> AuditEntry | None:
    """One _System/audit line; None when it has no usable ts, actor or action."""
    ts, actor, event = _parse_ts(line.get("ts")), line.get("actor"), line.get("action")
    if ts is None or not isinstance(actor, str) or not isinstance(event, str):
        return None
    raw = line.get("refs")
    refs: dict[str, Any] = raw if isinstance(raw, dict) else {}
    kind, label = actor_of(actor)
    who = names.get(str(refs.get("proposal") or ""), "a document")
    return AuditEntry(
        ts=ts,
        actor=actor,
        actor_kind=kind,
        actor_label=label,
        event=event,
        summary=summarise(event, refs, who),
        refs=refs_of(refs),
    )


ACTION_EVENTS = {"executed": "action_done", "rejected": "action_rejected", "failed": "action_failed"}


def from_action_line(line: dict[str, Any]) -> AuditEntry | None:
    """One _System/audit/actions line. "approving" is the claim before the work, not an outcome: skipped."""
    ts, event = _parse_ts(line.get("ts")), ACTION_EVENTS.get(str(line.get("event")))
    if ts is None or event is None:
        return None
    user = line.get("user")
    actor = f"user:{user}" if isinstance(user, str) and user else "agent:ask"
    kind, label = actor_of(actor)
    return AuditEntry(
        ts=ts,
        actor=actor,
        actor_kind=kind,
        actor_label=label,
        event=event,
        summary=summarise(event, line),
        refs=AuditRefs(action=_str(line.get("action_id"))),
    )


def matches(e: AuditEntry, actor: str | None, kind: str | None) -> bool:
    """`actor`: "user", "agent", an agent's name ("autopilot") or a full actor ("user:sam@…").
    `kind`: an event ("approved") or a family by prefix ("invoice" is every invoice_* line, "action" every Ask one)."""
    if actor:
        a = actor.strip().lower()
        if a not in (e.actor_kind, e.actor.lower(), e.actor.lower().removeprefix("agent:")):
            return False
    if kind:
        k = kind.strip().lower()
        if e.event != k and not e.event.startswith(k + "_"):
            return False
    return True


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


def months_between(start: date, end: date) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


async def _lines(books: Books, path: str) -> Iterable[dict[str, Any]]:
    try:
        raw = await books.storage.read(path)
    except FileNotFoundError:
        return []
    out: list[dict[str, Any]] = []
    for text in raw.decode("utf-8", "replace").splitlines():
        try:
            line = json.loads(text)
        except ValueError:
            continue
        if isinstance(line, dict):
            out.append(line)
    return out


async def _supplier_names(books: Books) -> dict[str, str]:
    """proposal id -> "Screwfix £12.00", for the summaries. Empty when a proposal file cannot be read."""
    try:
        proposals = await books.list_proposals()
    except ValueError:
        log.warning("audit: proposals unreadable; summaries say 'a document'")
        return {}
    return {
        p.id: f"{p.extracted.supplier_name} {money(round(p.extracted.gross_total * 100))}".strip() for p in proposals
    }


async def read(
    books: Books,
    start: date,
    end: date,
    actor: str | None = None,
    kind: str | None = None,
    limit: int = MAX_LIMIT,
) -> AuditPage:
    """Lines dated start..end (London days, inclusive) from both logs, newest first, at most `limit` (capped at 500)."""
    limit = max(1, min(limit, MAX_LIMIT))
    lo = datetime.combine(start, time.min, LONDON).astimezone(UTC)
    hi = datetime.combine(end + timedelta(days=1), time.min, LONDON).astimezone(UTC)
    # Monthly files are keyed by month, so read the months the window touches (older files were keyed by UTC
    # month, newer ones by London month; the window covers both).
    last = (hi - timedelta(microseconds=1)).date()
    months = months_between(lo.date(), last)
    # An action's lines go in the month it was proposed, so one approved just after midnight on the 1st is a
    # month early: read one month more of that log.
    action_months = months_between((lo.replace(day=1) - timedelta(days=1)).date(), last)

    # A view-only accountant's lines (queries) are in _System/queries/audit/, the one place they may write.
    per_month = await asyncio.gather(
        *(_lines(books, f"{folder}/{m}.jsonl") for m in months for folder in (AUDIT, QUERIES_AUDIT))
    )
    books_lines = [ln for lines in per_month for ln in lines]
    named = any(isinstance(r := ln.get("refs"), dict) and r.get("proposal") for ln in books_lines)
    names = await _supplier_names(books) if named else {}
    entries = [e for ln in books_lines if (e := from_books_line(ln, names))]
    per_actions = await asyncio.gather(*(_lines(books, f"{ACTIONS_AUDIT}/{m}.jsonl") for m in action_months))
    for batch in per_actions:
        entries += [e for ln in batch if (e := from_action_line(ln))]

    kept = [e for e in entries if lo <= e.ts < hi and matches(e, actor, kind)]
    kept.sort(key=lambda e: e.ts, reverse=True)
    return AuditPage(start=start, end=end, entries=kept[:limit], truncated=len(kept) > limit)
