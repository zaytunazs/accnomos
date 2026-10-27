"""Draft a payment reminder for an unpaid invoice. Facts from code, words from the user's Muse, checked by code.

Code works out the facts (amount, dates, days overdue, how many reminders went before) and the model writes a
short, polite UK-English email around them, as strict JSON. Then code checks it: every figure must be one of the
facts, the invoice number must be in it, and it may not contain links (payment details stay on the attached
invoice, never in words a model wrote). Anything else, or any model trouble, gives a plain draft written by code.

The result is only a draft: the user reads it, may edit it, and taps Send (app/invoicing.py send_reminder).
Backends are the user's own, as for Ask (app/ai/ask.py).
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.ai.ask import KnownNumbers, call_json_model
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError, parse_model_json
from app.invoicing import Invoice, InvoiceProfile, money, uk_date
from app.schemas import strict_json_schema

SUBJECT_MAX = 120
BODY_MAX = 1500

SYSTEM_PROMPT = (
    "You write a short payment reminder email for a UK small business owner to send to their customer. "
    "Plain UK English, polite and human, under 120 words, plain text (no markdown). "
    "You are given FACTS as JSON, worked out by code. Rules: "
    "1) Quote the amount, dates and invoice number exactly as they appear in FACTS; never calculate anything. "
    "2) Match FACTS.tone. Never threaten, never mention interest, fees, debt collection or legal action. "
    "3) Do not write bank details or links: say the payment details are on the attached invoice. "
    "4) If FACTS.reminders_already_sent is more than 0, say this is a follow-up. "
    "5) Sign off with FACTS.business_name (or no name if it is null). "
    "Return JSON with `subject` and `body`."
)

LINK = re.compile(r"https?://|www\.", re.IGNORECASE)


class ReminderModelOutput(BaseModel):
    subject: str
    body: str


class ReminderDraft(BaseModel):
    to: str | None
    subject: str
    body: str
    days_overdue: int
    model: str
    fallback_reason: str | None = None  # the model's words were replaced by a draft written by code


def _tone(days_overdue: int, earlier: int) -> str:
    if days_overdue <= 0:
        return "friendly heads-up that payment is due soon"
    if days_overdue <= 14 and not earlier:
        return "gentle, assume it was missed"
    if days_overdue <= 45:
        return "friendly but clear, ask when they expect to pay"
    return "firm and courteous, ask them to pay now or reply if there is a problem"


def reminder_facts(inv: Invoice, profile: InvoiceProfile, today: date) -> dict[str, Any]:
    days = inv.overdue_days(today) or 0
    return {
        "business_name": profile.name.strip() or None,
        "customer_name": inv.customer.name,
        "invoice_number": inv.number,
        "amount_due": money(inv.total_pence),
        "invoice_date": uk_date(inv.issue_date),
        "due_date": uk_date(inv.due_date),
        "status": "overdue" if days > 0 else "due today" if days == 0 else "not yet due",
        "days_overdue": max(days, 0),
        "reminders_already_sent": len(inv.reminders),
        "tone": _tone(days, len(inv.reminders)),
        "payment_details_on_invoice": profile.bank.is_set(),
    }


def fallback_draft(facts: dict[str, Any]) -> tuple[str, str]:
    """(subject, body) written by code from the facts alone."""
    n, amount, due = facts["invoice_number"], facts["amount_due"], facts["due_date"]
    follow = "Following up on my earlier email: " if facts["reminders_already_sent"] else ""
    if facts["status"] == "overdue":
        days = facts["days_overdue"]
        line = f"{follow}invoice {n} for {amount} was due on {due} and is now {days} day{'s' if days != 1 else ''} overdue."
        ask = "Could you let me know when it will be paid? If it is already on its way, thank you, and please ignore this."
    else:
        line = f"{follow}this is a quick reminder that invoice {n} for {amount} is due on {due}."
        ask = "Thank you in advance."
    line = (
        line[0].upper() + line[1:]
    )  # "Following up…: invoice" keeps its lower case; a bare sentence starts with a capital
    where = " The payment details are on the attached invoice." if facts["payment_details_on_invoice"] else ""
    body = "\n".join(
        [
            "Hello,",
            "",
            line + where,
            "",
            ask,
            "",
            "Kind regards,",
            *([facts["business_name"]] if facts["business_name"] else []),
        ]
    )
    return f"Reminder: invoice {n} ({amount})", body


def ground(out: ReminderModelOutput, facts: dict[str, Any]) -> tuple[str, str] | str:
    """The model's (subject, body) when it passes every check, otherwise the reason it does not."""
    subject, body = out.subject.strip(), out.body.strip()
    if not subject or not body:
        return "The model returned an empty email."
    if len(subject) > SUBJECT_MAX or len(body) > BODY_MAX:
        return "The model's email was too long."
    text = f"{subject}\n{body}"
    if LINK.search(text):
        return "The model's email contained a link."
    if facts["invoice_number"] not in text:
        return "The model's email did not mention the invoice number."
    if invented := KnownNumbers(facts).unknown(text, all_tokens=False):
        return f"The model quoted figures that are not on the invoice ({', '.join(dict.fromkeys(invented[:3]))})."
    return subject, body


async def _call_model(messages: list[dict[str, str]], cfg: AiConfig) -> str:
    return await call_json_model(messages, cfg, strict_json_schema(ReminderModelOutput), "payment_reminder")


async def draft_reminder(inv: Invoice, profile: InvoiceProfile, cfg: AiConfig, today: date) -> ReminderDraft:
    """Never raises for model trouble: the code-written draft stands in, with the reason."""
    facts = reminder_facts(inv, profile, today)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"FACTS:\n{json.dumps(facts, ensure_ascii=False)}"},
    ]
    reason: str | None = None
    try:
        out = ReminderModelOutput.model_validate(parse_model_json(await _call_model(messages, cfg)))
        checked = ground(out, facts)
    except httpx.HTTPStatusError as exc:
        checked = f"Your AI ({cfg.mode}) returned HTTP {exc.response.status_code}."
    except httpx.HTTPError:
        checked = f"Your AI ({cfg.mode}) could not be reached at {cfg.base_url}."
    except (ExtractionError, ValidationError):
        checked = "The model's reply was not in the expected format."
    if isinstance(checked, str):
        reason, checked = checked, fallback_draft(facts)
    subject, body = checked
    return ReminderDraft(
        to=inv.customer.email,
        subject=subject,
        body=body,
        days_overdue=facts["days_overdue"],
        model=cfg.model,
        fallback_reason=reason,
    )
