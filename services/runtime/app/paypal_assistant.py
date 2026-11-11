"""Talk to your accountant about PayPal: the assistant (typed or spoken) acts on PayPal and answers money questions.

Same rules as every other Ask card (docs/ACTIONS.md): the model reads the instruction into a structured intent and may
word a message; code finds the invoices, works out every figure in pence, and builds a signed card; nothing is sent,
created or moved until the user approves it (POST /actions/approve). The phrases: docs/ACTIONS.md, "PayPal: talk to
your accountant".

Two cards:

* ``remind_unpaid``: "send a PayPal reminder to everyone who owes me", "remind JM Trading through PayPal". For each
  unpaid invoice whose Pay online link is a PayPal invoice on the connected account, PayPal sends its own reminder
  (Invoicing v2 ``POST /v2/invoicing/invoices/{id}/remind``); an invoice without one gets the usual reminder email
  (app/ai/remind.py, checked by code). The card lists who, how much and how many days overdue. Tap only: it sends.
* ``payment_link_message``: "WhatsApp JM Trading the payment link". A short message for one unpaid invoice, ready to
  copy, with wa.me and sms: links that open the user's own app with the text filled in. Nothing is sent from here.
  The model may word it (checked like a reminder: invoice number and amount exactly, no other figures, no links);
  the link itself is added by code at approval, from the invoice (and made then, on PayPal, if it has none yet).

PayPal questions, answered by code with the figures (the model only words them, checked as app/ask_more.py does):
"who owes me money?" gains each customer's PayPal link status (app/ask_more.py owed_answer calls ``add_link_status``),
"what did PayPal cost me this quarter?" (PayPal fee entries: 7900 Bank charges against 1240 PayPal clearing),
"how much is sitting in PayPal?" and "when was my last PayPal payout?" (the 1240 PayPal clearing balance by the books,
online_payments.clearing_balance, and the last payout to the bank), "do I have any PayPal disputes?"
(app/paypal_disputes.py), "what is waiting in Sync PayPal?" (app/paypal_sync.py) and "which bills are due through
PayPal?" (app/billpay.py, by app/paypal_reports.py). The same figures reach Home and the month-end summary.

The calls to PayPal are the REST endpoints in app/payment_providers.py, not the PayPal Agent Toolkit: see
docs/ACTIONS.md for why (checked against paypal-agent-toolkit 1.11.0).
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, ValidationError

from app import actions as act
from app.ai import ask as ask_ai
from app.ai.config import AiConfig
from app.ai.extract import ExtractionError, parse_model_json
from app.books import Books
from app.books import today as london_today
from app.schemas import AskAnswer, AskPeriod, Clarification, KeyNumber, strict_json_schema

MAX_REMINDERS = 10  # one card; more than this and the user is told how many were left for the next one
MESSAGE_MAX = 500
_I = re.IGNORECASE

# --------------------------------------------------------------------------- #
# Reading the instruction (the model picks the kind; code keeps it honest)
# --------------------------------------------------------------------------- #

_PAYPAL = re.compile(r"\bpay\s?pal\b", _I)
_EVERYONE = re.compile(
    r"\b(?:everyone|everybody|all (?:my |the )?(?:customers|clients|debtors|unpaid|overdue|late)|anyone|"
    r"all of them|every customer|every client)\b|\bwho (?:still )?owes? me\b|\bwho owe(?:s)? us\b|\bwho hasn'?t paid\b",
    _I,
)
_MESSAGE = re.compile(r"\bwhats\s?app\b|\btext\b|\bsms\b|\bmessage\b|\bpay(?:ment)? link\b", _I)


class RemindIntent(BaseModel):
    kind: Literal["remind_unpaid"] = "remind_unpaid"
    customer_ref: str | None = None  # None: everyone with an overdue invoice


class LinkMessageIntent(BaseModel):
    kind: Literal["payment_link_message"] = "payment_link_message"
    customer_ref: str | None = None
    invoice_ref: str | None = None


def reroute(out: act.IntentModelOutput, question: str) -> act.IntentModelOutput:
    """Code's corrections to the model's kind: a chase that names PayPal or "everyone" is a PayPal reminder run; a
    reminder for everyone never keeps a customer the model made up from "everyone"."""
    if out.kind == "chase_invoice" and (_PAYPAL.search(question) or _EVERYONE.search(question)):
        out = out.model_copy(update={"kind": "remind_unpaid"})
    if out.kind == "chase_invoice" and _MESSAGE.search(question) and re.search(r"\blink\b", question, _I):
        out = out.model_copy(update={"kind": "payment_link_message"})
    return out


def parse(out: act.IntentModelOutput, question: str) -> RemindIntent | LinkMessageIntent | Clarification:
    if out.kind == "remind_unpaid":
        ref = (out.customer_ref or "").strip()
        if not ref or _EVERYONE.search(ref) or _EVERYONE.search(question):
            return RemindIntent(customer_ref=None)
        return RemindIntent(customer_ref=ref)
    ref, inv = (out.customer_ref or "").strip() or None, (out.invoice_ref or "").strip() or None
    if not (ref or inv):
        return Clarification(
            kind="payment_link_message", field="invoice", question_md="Which customer, or which invoice, is it for?"
        )
    return LinkMessageIntent(customer_ref=ref, invoice_ref=inv)


# --------------------------------------------------------------------------- #
# Unpaid invoices, with what is still owed on each (code, in pence)
# --------------------------------------------------------------------------- #


async def _unpaid(books: Books) -> list[tuple[Any, int]]:
    """(invoice, balance in pence) for each sent invoice with something left to pay, oldest due first."""
    from app import invoicing, payments

    invoices = await invoicing.list_invoices(books, "sent")
    try:
        ledger = await payments.load_ledger(books)
    except Exception:  # noqa: BLE001  a ledger that will not read: the invoice totals stand
        ledger = None
    out = []
    for inv in invoices:
        m = payments.invoice_money(inv, ledger) if ledger is not None else None
        balance = m.balance_pence if m is not None else (inv.balance_pence or inv.total_pence)
        if balance > 0:
            out.append((inv, balance))
    return sorted(out, key=lambda t: (t[0].due_date, t[0].number))


def _overdue_words(days: int, due: date) -> str:
    if days > 0:
        return f"{days} day{'s' if days != 1 else ''} overdue"
    return "due today" if days == 0 else f"due {act.uk_date(due)}"


async def _paypal_ready(books: Books) -> tuple[Any, Any]:
    """(the PayPal connection, the server's PayPal config), either None when PayPal reminders cannot be sent."""
    from app import online_payments as op

    try:
        c = await op.load_connections(books)
    except Exception:  # noqa: BLE001
        return None, None
    return c.paypal, op.paypal_config()[0]


def _paypal_invoice(inv: Any, conn: Any) -> str | None:
    """The PayPal invoice id behind the invoice's Pay online link, when it is on the connected PayPal account."""
    link = inv.payment_link
    if link is None or link.provider != "paypal" or not link.provider_ref or conn is None:
        return None
    return str(link.provider_ref) if link.account_ref == conn.merchant_id else None


async def resolve_remind(
    books: Books, intent: RemindIntent, cfg: AiConfig | None, today: date
) -> act.Draft | Clarification:
    from app import invoicing
    from app.ai import remind

    kind: Any = "remind_unpaid"
    unpaid = await _unpaid(books)
    skipped_not_due = 0
    if intent.customer_ref:
        names = list(dict.fromkeys(inv.customer.name for inv, _ in unpaid))
        hit = act.pick(
            intent.customer_ref, [act.Option(n, n) for n in names], kind, "customer", "customer with an unpaid invoice"
        )
        if isinstance(hit, Clarification):
            return hit
        chosen = [(i, b) for i, b in unpaid if act._norm(i.customer.name) == act._norm(hit.option.name)]  # noqa: SLF001
    else:
        chosen = [(i, b) for i, b in unpaid if (today - i.due_date).days > 0]
        skipped_not_due = len(unpaid) - len(chosen)
        if not chosen:
            more = (
                f" {skipped_not_due} unpaid invoice{'s are' if skipped_not_due != 1 else ' is'} not due yet."
                if (skipped_not_due)
                else ""
            )
            return Clarification(kind=kind, field="invoice", question_md="Nobody owes you anything overdue." + more)
    chosen.sort(key=lambda t: (-(today - t[0].due_date).days, t[0].number))
    left_over = len(chosen) - MAX_REMINDERS
    chosen = chosen[:MAX_REMINDERS]
    conn, pp_cfg = await _paypal_ready(books)
    profile = await invoicing.load_profile(books)
    warnings: list[str] = []
    gate = asyncio.Semaphore(3)

    async def row(inv: Any, balance: int) -> dict[str, Any] | None:
        days = (today - inv.due_date).days
        base = {
            "invoice": inv.number,
            "customer": inv.customer.name,
            "balance_pence": balance,
            "due_date": inv.due_date.isoformat(),
            "days_overdue": max(days, 0),
        }
        pp_id = _paypal_invoice(inv, conn) if pp_cfg is not None else None
        if pp_id and inv.customer.email:
            return base | {"channel": "paypal", "paypal_invoice_id": pp_id, "to": inv.customer.email}
        if not inv.customer.email:
            if pp_id or inv.payment_link:
                warnings.append(
                    f"{inv.number} ({inv.customer.name}) has no email address, so no reminder can go: say “text "
                    f"{inv.customer.name} the payment link” for a message to send yourself."
                )
            else:
                warnings.append(f"{inv.number} ({inv.customer.name}) has no email address and no payment link.")
            return None
        async with gate:
            d = await remind.draft_reminder(inv, profile, cfg, today)
        if d.fallback_reason:
            warnings.append(f"{inv.number}: the email was written by code ({d.fallback_reason})")
        return base | {"channel": "email", "to": d.to, "subject": d.subject, "body": d.body}

    rows = [r for r in await asyncio.gather(*(row(i, b) for i, b in chosen)) if r is not None]
    if not rows:
        return Clarification(
            kind=kind, field="customer", question_md="None of those invoices can be reminded: " + " ".join(warnings)
        )
    if skipped_not_due:
        warnings.append(f"Left out {skipped_not_due} unpaid invoice{'s' if skipped_not_due != 1 else ''} not due yet.")
    if left_over > 0:
        warnings.append(
            f"{left_over} more overdue invoice{'s' if left_over != 1 else ''} after these: ask again after."
        )
    if any(r["channel"] == "email" for r in rows) and conn is None:
        warnings.append("PayPal is not connected, so these go as emails. Connect it in Settings › Online payments.")
    total = sum(r["balance_pence"] for r in rows)
    n_pp = sum(1 for r in rows if r["channel"] == "paypal")
    lines = []
    for r in rows:
        how = "PayPal reminder" if r["channel"] == "paypal" else "email reminder"
        when = _overdue_words(r["days_overdue"] or (today - date.fromisoformat(r["due_date"])).days,
                              date.fromisoformat(r["due_date"]))  # fmt: skip
        lines.append(
            f"\n- **{act._md(r['customer'])}**, {r['invoice']}: **{act.money(r['balance_pence'])}**, {when} · {how} "  # noqa: SLF001
            f"to {act._md(r['to'])}"  # noqa: SLF001
        )
    summary = (
        f"**Send {len(rows)} payment reminder{'s' if len(rows) != 1 else ''}** for **{act.money(total)}** in all"
        + (f" ({n_pp} through PayPal, {len(rows) - n_pp} by email)" if n_pp and n_pp != len(rows) else "")
        + (" through PayPal" if n_pp == len(rows) else "")
        + ":"
        + "".join(lines)
    )
    preview = {
        "reminders": rows,
        "total_pence": total,
        "rows": [
            {
                "label": r["invoice"],
                "value": f"{r['customer']} · {act.money(r['balance_pence'])} · "
                f"{_overdue_words(r['days_overdue'], date.fromisoformat(r['due_date']))} · "
                + ("PayPal reminder" if r["channel"] == "paypal" else f"email to {r['to']}"),
            }
            for r in rows
        ]
        + [{"label": "Total", "value": act.money(total)}],
        "warnings": warnings,
    }
    confirm = f"Send {'this reminder' if len(rows) == 1 else f'these {len(rows)} reminders'}"
    return act.Draft(kind, summary, preview, confirm)


async def run_remind(action: Any, ctx: act.Context) -> tuple[str, dict[str, Any]]:
    """Each reminder once, checked again first (still unpaid, same PayPal invoice). One that fails does not stop the
    rest; the result says which. Nothing sent at all is an error, so the user can approve again."""
    from app import invoicing
    from app import online_payments as op
    from app.payment_providers import PayPalApi, ProviderError, client

    p = action.preview
    conn, pp_cfg = await _paypal_ready(ctx.books)
    sender = None
    sent: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    try:
        for r in p["reminders"]:
            number = r["invoice"]
            try:
                inv = await invoicing.get_invoice(ctx.books, number)
                if inv.status != "sent":
                    raise act.ActionError(f"{number} is {inv.status} now, so it was not reminded")
                if r["channel"] == "paypal":
                    if pp_cfg is None or _paypal_invoice(inv, conn) != r["paypal_invoice_id"]:
                        raise act.ActionError(f"{number}'s PayPal link has changed since the card was made")
                    async with client() as http:
                        await PayPalApi(pp_cfg, http).remind_invoice(conn.merchant_id, r["paypal_invoice_id"])
                    inv = await invoicing.get_invoice(ctx.books, number)
                    inv.reminders.append(
                        invoicing.Reminder(
                            sent_at=act.now(), sent_by=ctx.user, to=r["to"], subject="PayPal reminder", step="paypal"
                        )
                    )
                    await invoicing.save_invoice(ctx.books, inv)
                    await ctx.books.audit(
                        f"user:{ctx.user}",
                        "invoice_reminder_sent",
                        {
                            "invoice": number,
                            "to": r["to"],
                            "channel": "paypal",
                            "paypal_invoice": r["paypal_invoice_id"],
                            "count": len(inv.reminders),
                            "action": action.id,
                        },
                    )
                else:
                    if sender is None:
                        sender = ctx.mail_sender() if ctx.mail_sender else None
                        if sender is None:
                            raise act.ActionError("email is not available on this runtime")
                    await invoicing.send_reminder(
                        ctx.books, sender, number, ctx.user, to=r["to"], subject=r["subject"], body=r["body"],
                        pdf=await invoicing.sent_pdf(ctx.books, number),
                    )  # fmt: skip
                sent.append({"invoice": number, "channel": r["channel"], "to": r["to"]})
            except (act.ActionError, ProviderError, invoicing.InvoiceError, op.OnlinePaymentError,
                    FileNotFoundError, RuntimeError) as exc:  # fmt: skip
                failed.append({"invoice": number, "error": str(exc)[:200]})
    finally:
        if sender is not None and hasattr(sender, "aclose"):
            await sender.aclose()
    if not sent:
        raise act.ActionError(
            "No reminder was sent: " + "; ".join(f"{f['invoice']}: {f['error']}" for f in failed), 502
        )
    via = {"paypal": "PayPal", "email": "email"}
    text = f"Sent {len(sent)} reminder{'s' if len(sent) != 1 else ''}: " + ", ".join(
        f"{s['invoice']} ({via[s['channel']]})" for s in sent
    )
    if failed:
        text += ". **Not sent:** " + "; ".join(f"{f['invoice']}: {act._md(f['error'])}" for f in failed)  # noqa: SLF001
    return text + ".", {"sent": sent, "failed": failed}


# --------------------------------------------------------------------------- #
# A payment-link message to copy into WhatsApp or Messages
# --------------------------------------------------------------------------- #

MESSAGE_PROMPT = (
    "You write a short text or WhatsApp message from a UK small business owner to a customer about an unpaid "
    "invoice. Plain UK English, friendly and brief: at most three sentences and under 60 words, no markdown, no "
    "emoji. You are given FACTS as JSON, worked out by code. Rules: 1) Quote the invoice number and amount exactly "
    "as in FACTS; never calculate anything and quote no other figures except dates from FACTS. 2) Do not write any "
    "link, web address or bank details: the payment link is added after your message by the app. 3) Never threaten "
    "or mention fees or interest. 4) Sign off with FACTS.business_name if it is not null. Return JSON with `message`."
)


class MessageModelOutput(BaseModel):
    message: str


def message_facts(inv: Any, balance: int, business: str | None, today: date) -> dict[str, Any]:
    days = (today - inv.due_date).days
    return {
        "business_name": business,
        "customer_name": inv.customer.name,
        "invoice_number": inv.number,
        "amount_due": act.money(balance),
        "due_date": act.uk_date(inv.due_date),
        "status": "overdue" if days > 0 else "due today" if days == 0 else "not yet due",
        "days_overdue": max(days, 0),
    }


def code_message(f: dict[str, Any]) -> str:
    if f["status"] == "overdue":
        line = (
            f"Hi, a quick reminder that invoice {f['invoice_number']} for {f['amount_due']} was due on {f['due_date']}."
        )
    else:
        line = f"Hi, here is the link to pay invoice {f['invoice_number']} for {f['amount_due']}, due {f['due_date']}."
    return (
        line
        + " You can pay online with the link below. Thank you!"
        + (f" {f['business_name']}" if f["business_name"] else "")
    )


def check_message(text: str, f: dict[str, Any]) -> str | None:
    """Why the model's message cannot be used, or None."""
    from app.ai.home_summary import LINK

    if not text.strip():
        return "The model returned an empty message."
    if len(text) > MESSAGE_MAX:
        return "The model's message was too long."
    if LINK.search(text) or re.search(r"\b[a-z0-9-]+\.(?:com|co\.uk|me|uk|net|org)\b", text, _I):
        return "The model's message contained a link."
    if f["invoice_number"] not in text:
        return "The model's message did not mention the invoice number."
    if f["amount_due"] not in text:
        return "The model's message did not quote the amount exactly."
    if invented := ask_ai.KnownNumbers(f).unknown(text, all_tokens=False):
        return f"The model quoted figures that are not on the invoice ({', '.join(dict.fromkeys(invented[:3]))})."
    return None


async def word_message(f: dict[str, Any], cfg: AiConfig | None) -> tuple[str, str | None]:
    """(message, why code wrote it). Never raises for model trouble."""
    if cfg is None:
        return code_message(f), "No AI is set up, so code wrote the message."
    messages = [
        {"role": "system", "content": MESSAGE_PROMPT},
        {"role": "user", "content": f"FACTS:\n{json.dumps(f, ensure_ascii=False)}"},
    ]
    try:
        raw = await ask_ai.call_json_model(messages, cfg, strict_json_schema(MessageModelOutput), "payment_message")
        text = " ".join(MessageModelOutput.model_validate(parse_model_json(raw)).message.split())
    except (ExtractionError, ValidationError):
        return code_message(f), "The model's reply was not in the expected format."
    except Exception as exc:  # noqa: BLE001  model trouble of any kind
        return code_message(f), ask_ai._trouble(exc, cfg)  # noqa: SLF001
    if (why := check_message(text, f)) is not None:
        return code_message(f), why
    return text, None


def uk_mobile(phone: str | None) -> str | None:
    """'07700 900123' / '+44 7700 900123' / '0044…' -> '447700900123' (digits with the country code, as wa.me wants).
    None when it does not look like a phone number."""
    if not phone:
        return None
    raw = phone.strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        pass
    elif digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = "44" + digits[1:]
    return digits if 8 <= len(digits) <= 15 else None


def share_links(text: str, phone: str | None) -> tuple[str, str]:
    """(wa.me link, sms: link) that open the user's own app with the message filled in; nothing is sent by us."""
    body = quote(text, safe="")
    wa = f"https://wa.me/{phone}?text={body}" if phone else f"https://wa.me/?text={body}"
    sms = f"sms:{'+' + phone if phone else ''}?&body={body}"
    return wa, sms


async def _find_unpaid(books: Books, intent: LinkMessageIntent) -> tuple[Any, int] | Clarification:
    kind: Any = "payment_link_message"
    unpaid = await _unpaid(books)
    if intent.invoice_ref:
        digits = re.sub(r"\D", "", intent.invoice_ref).lstrip("0")
        found = [
            t
            for t in unpaid
            if t[0].number.upper() == intent.invoice_ref.strip().upper()
            or (digits and re.sub(r"\D", "", t[0].number).lstrip("0") == digits)
        ]
        if not found:
            return Clarification(
                kind=kind,
                field="invoice",
                candidates=[i.number for i, _ in unpaid[:5]],
                question_md=f"I couldn't find an unpaid invoice “{act._md(intent.invoice_ref)}”.",  # noqa: SLF001
            )
    else:
        names = list(dict.fromkeys(i.customer.name for i, _ in unpaid))
        hit = act.pick(
            intent.customer_ref or "",
            [act.Option(n, n) for n in names],
            kind,
            "customer",
            "customer with an unpaid invoice",
        )
        if isinstance(hit, Clarification):
            return hit
        found = [t for t in unpaid if act._norm(t[0].customer.name) == act._norm(hit.option.name)]  # noqa: SLF001
    if len(found) > 1:
        return Clarification(
            kind=kind,
            field="invoice",
            candidates=[i.number for i, _ in found[:5]],
            question_md="Which invoice: " + ", ".join(f"{i.number} ({act.money(b)})" for i, b in found[:5]) + "?",
        )
    return found[0]


async def _phone_of(books: Books, name: str) -> str | None:
    try:
        options = await act.customer_options(books)
    except Exception:  # noqa: BLE001  no phone is fine: the links open without a number
        return None
    for o in options:
        if act._norm(o.name) == act._norm(name) and getattr(o.data, "phone", None):  # noqa: SLF001
            return uk_mobile(o.data.phone)
    return None


async def resolve_message(
    books: Books, intent: LinkMessageIntent, cfg: AiConfig | None, today: date
) -> act.Draft | Clarification:
    from app import invoicing
    from app import online_payments as op

    kind: Any = "payment_link_message"
    hit = await _find_unpaid(books, intent)
    if isinstance(hit, Clarification):
        return hit
    inv, balance = hit
    link = inv.payment_link
    add: str | None = None
    if link is None or link.amount_pence != balance:
        add = await act._pay_online_provider(books)  # noqa: SLF001  PayPal first, then Stripe
        if add is None:
            try:
                me = (await op.load_connections(books)).paypalme
            except Exception:  # noqa: BLE001
                me = None
            add = "paypalme" if me else None
        if add is None:
            if link is None:
                return Clarification(
                    kind=kind,
                    field="invoice",
                    question_md=f"{inv.number} has no payment link and no online payments are connected. Connect "
                    "PayPal in Settings › Online payments, then ask again.",
                )
            add = None  # the old link stays; the card says its amount differs
    profile = await invoicing.load_profile(books)
    f = message_facts(inv, balance, profile.name.strip() or None, today)
    text, why = await word_message(f, cfg)
    phone = await _phone_of(books, inv.customer.name)
    warnings = [f"The message was written by code: {why}"] if why else []
    if link is not None and link.amount_pence != balance and add is None:
        warnings.append(
            f"The link on {inv.number} is for {act.money(link.amount_pence)}, not the {act.money(balance)} owed."
        )
    if not phone:
        warnings.append(f"No mobile number for {inv.customer.name} in your contacts: pick the chat yourself.")
    label = {"paypal": "PayPal", "stripe": "Stripe", "paypalme": "PayPal.me"}
    if add:
        where = f"A new {label[add]} Pay online link for {act.money(balance)} is added to {inv.number} when you approve"
    else:
        where = (
            f"The {label.get(link.provider, link.provider) if link else ''} link already on {inv.number} goes after it"
        )
    preview = {
        "invoice": inv.number,
        "customer": inv.customer.name,
        "balance_pence": balance,
        "days_overdue": f["days_overdue"],
        "due_date": inv.due_date.isoformat(),
        "phone": phone,
        "message": text,
        "add_link": add,
        "link_url": link.url if (link is not None and not add) else None,
        "rows": [
            {
                "label": "Invoice",
                "value": f"{inv.number} · {inv.customer.name} · {act.money(balance)} · "
                f"{_overdue_words((today - inv.due_date).days, inv.due_date)}",
            },
            {"label": "Message", "value": text},
            {"label": "Link", "value": where},
            {"label": "To", "value": f"+{phone}" if phone else "you choose the chat"},
        ],  # fmt: skip
        "warnings": warnings,
    }
    summary = (
        f"**A payment message for {act._md(inv.customer.name)}** about **{inv.number}** "  # noqa: SLF001
        f"(**{act.money(balance)}**), to send yourself by WhatsApp or text:\n\n> {act._md(text)}\n\n"  # noqa: SLF001
        f"{where}. Nothing is sent from here."
    )
    confirm = "Add the link and get the message" if add else "Get the message with the link"
    return act.Draft(kind, summary, preview, confirm)


async def run_message(action: Any, ctx: act.Context) -> tuple[str, dict[str, Any]]:
    """Make the link if the card said so, then the text with it (added by code) and the wa.me / sms: links."""
    from app import invoicing
    from app import online_payments as op

    p = action.preview
    try:
        inv = await invoicing.get_invoice(ctx.books, p["invoice"])
    except FileNotFoundError as exc:
        raise act.ActionError("That invoice no longer exists; ask again.", 409) from exc
    if inv.status != "sent":
        raise act.ActionError(f"{inv.number} is {inv.status} now; ask again.", 409)
    if p.get("add_link"):
        try:
            inv, _warning = await op.add_link(ctx.books, inv.number, p["add_link"], ctx.user)
        except (op.OnlinePaymentError, invoicing.InvoiceError) as exc:
            raise act.ActionError(f"The payment link could not be added: {exc}", 502) from exc
    link = inv.payment_link
    if link is None:
        raise act.ActionError(f"{inv.number} has no payment link now; ask again.", 409)
    if p.get("link_url") and link.url != p["link_url"]:
        raise act.ActionError(f"The payment link on {inv.number} has changed since the card was made; ask again.", 409)
    line = invoicing.pay_online_line(inv) or f"Pay online: {link.url}"
    text = f"{p['message']}\n\n{line}"
    wa, sms = share_links(text, p.get("phone"))
    await ctx.books.audit(
        f"user:{ctx.user}",
        "payment_message_prepared",
        {"invoice": inv.number, "provider": link.provider, "link_added": bool(p.get("add_link")), "action": action.id},
    )
    return (
        f"Message for {act._md(inv.customer.name)} about {inv.number} is ready, with the link. "  # noqa: SLF001
        "Copy it, or open WhatsApp or Messages below to send it yourself.",
        {"invoice": inv.number, "message": text, "whatsapp_url": wa, "sms_url": sms, "payment_link": link.url},
    )


# --------------------------------------------------------------------------- #
# Questions: who owes me (with PayPal link status), PayPal fees, money held in PayPal
# --------------------------------------------------------------------------- #

_FEES = re.compile(
    r"\bfees?\b|\bcost(?:s|ing)?\b|\bcharg(?:e|es|ed|ing)\b|\b(?:take|took|taken|keep|kept)\b|\bspen[dt] on\b", _I
)
_HELD = re.compile(
    r"\bsitting\b|\bbalance\b|\bheld\b|\bhold(?:s|ing)?\b|\b(?:in|left in|waiting in|inside) (?:my |our |the )?"
    r"pay\s?pal\b|\bpay\s?pal (?:account|balance)\b|\bnot (?:yet )?paid out\b",
    _I,
)


_DISPUTES = re.compile(r"\bdisputes?\b|\bchargebacks?\b|\bclaims?\b|\bcase opened\b", _I)
_BILLS = re.compile(
    r"\bbills?\b|\bsuppliers?\b|\bpay(?:ing)? out\b.*\b(?:due|upcoming|next)\b|\bupcoming (?:payments?|payouts?)\b|"
    r"\bpayouts? (?:to|for) (?:my |our |the )?(?:suppliers?|bills?)\b",
    _I,
)
_WAITING = re.compile(
    r"\bsync(?:ed|ing)?\b|\bto approve\b|\bawaiting\b|\bwaiting (?:for )?(?:me|my approval|approval)\b|"
    r"\bnot (?:yet )?(?:approved|posted|in (?:my|the|our) books)\b|\bunapproved\b",
    _I,
)
_PAYOUT = re.compile(r"\bpayouts?\b|\bpaid out\b|\btransfer(?:red)? to (?:my |our |the )?bank\b", _I)

Kind = Literal["fees", "held", "disputes", "waiting", "bills"]


def question_kind(question: str) -> Kind | None:
    """A question about PayPal's fees, the money it holds or pays out, its disputes, the payments waiting in Sync
    PayPal or the bills due through it; None for anything else (and for instructions)."""
    if not _PAYPAL.search(question) or act.looks_like_action(question):
        return None
    if _DISPUTES.search(question):
        return "disputes"
    if _BILLS.search(question):
        return "bills"
    if _WAITING.search(question):
        return "waiting"
    if _FEES.search(question):
        return "fees"
    if _HELD.search(question) or _PAYOUT.search(question):
        return "held"
    return None


_SPAN_SAID = re.compile(
    r"\b(?:week|month|quarter|year|today|yesterday|ytd)\b|"
    r"\b(?:jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b|\b(?:in|for) may\b",
    _I,
)


def _pct(part: int, whole: int) -> str | None:
    if whole <= 0:
        return None
    return str((Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


async def fee_facts(books: Books, question: str, today: date) -> dict[str, Any]:
    """PayPal's fees over the span asked about ("this quarter" by default): the 7900 Bank charges entries posted
    against 1240 PayPal clearing (or with PayPal as the counterparty), reversals netted; and what came in through
    PayPal (debits to 1240 that are not reversals), for the fee as a percentage. All in pence, by code."""
    from app.ai.home_summary import gbp
    from app.ask_pnl import span_words
    from app.ask_router import pnl_span
    from app.journal import CATEGORY_ACCOUNTS, PAYPAL_CLEARING
    from app.paypal_reports import period_totals

    fees_account = CATEGORY_ACCOUNTS["Bank charges"]
    q = question if _SPAN_SAID.search(question) else f"{question} this quarter"  # PayPal's cost: the quarter
    s = pnl_span(q, today)
    t = period_totals(await books.list_events(s.start, s.end))
    fees, entries, received = t.fees_pence, t.fee_entries, t.received_pence
    return {
        "span": span_words(s),
        "paypal_fees": gbp(fees),
        "fee_entries": entries,
        "received_through_paypal": gbp(received),
        "fees_as_percent_of_received": _pct(fees, received),
        "account": f"{fees_account}, against {PAYPAL_CLEARING}",
        "_pence": {"fees": fees, "received": received},
    }


def fee_code_text(f: dict[str, Any]) -> str:
    if not f["fee_entries"] and not f["_pence"]["fees"]:
        return (
            f"No PayPal fees are in your books for {f['span']}. Fees are posted when you approve a PayPal payment "
            "found on Invoices (or import your PayPal transactions)."
        )
    pct = f"; that is {f['fees_as_percent_of_received']}% of the {f['received_through_paypal']} you received " \
          "through PayPal" if f["fees_as_percent_of_received"] else ""  # fmt: skip
    return (
        f"PayPal cost you {f['paypal_fees']} in fees over {f['span']}, from {f['fee_entries']} "
        f"fee entr{'ies' if f['fee_entries'] != 1 else 'y'}{pct}."
    )


async def held_facts(books: Books) -> dict[str, Any]:
    from app import online_payments as op
    from app.ai.home_summary import gbp
    from app.journal import PAYPAL_CLEARING

    held = await op.clearing_balance(books, "paypal")
    payouts = [x for x in await op._payouts(books) if x.provider == "paypal" and not x.reversal_event_id]  # noqa: SLF001
    last = max(payouts, key=lambda x: x.date) if payouts else None
    waiting = [(i, b) for i, b in await _unpaid(books) if i.payment_link and i.payment_link.provider == "paypal"]
    return {
        "held_in_paypal_by_your_books": gbp(held),
        "account": PAYPAL_CLEARING,
        "last_paypal_payout_to_your_bank": {"date": act.uk_date(last.date), "amount": gbp(last.amount_pence)}
        if last
        else None,
        "unpaid_invoices_with_a_paypal_link": len(waiting),
        "owed_on_those_invoices": gbp(sum(b for _, b in waiting)),
        "_pence": {"held": held},
    }


def held_code_text(f: dict[str, Any]) -> str:
    held = f["_pence"]["held"]
    if held == 0:
        out = "By your books, nothing is sitting in PayPal: every PayPal payment you approved has been paid out."
    elif held < 0:
        out = (
            f"Your PayPal clearing account shows {f['held_in_paypal_by_your_books']}: more was paid out than your "
            "books show coming in. Approve the PayPal payments waiting on Invoices."
        )
    else:
        out = (
            f"By your books, {f['held_in_paypal_by_your_books']} is sitting in PayPal: payments you approved, less "
            "PayPal's fees, not yet paid out to your bank."
        )
    if f["last_paypal_payout_to_your_bank"]:
        lp = f["last_paypal_payout_to_your_bank"]
        out += f" The last payout was {lp['amount']} on {lp['date']}."
    if f["unpaid_invoices_with_a_paypal_link"]:
        n = f["unpaid_invoices_with_a_paypal_link"]
        out += (
            f" {n} unpaid invoice{'s' if n != 1 else ''} with a PayPal link could bring in "
            f"{f['owed_on_those_invoices']} more."
        )
    return out


def _uk(d: date | None) -> str | None:
    return None if d is None else act.uk_date(d)


async def disputes_facts(books: Books, demo: bool) -> dict[str, Any]:
    """PayPal's disputes not yet resolved, from app/paypal_disputes.py (read only), with the soonest reply date."""
    from app import paypal_disputes as pd
    from app.ai.home_summary import gbp

    try:
        got = await asyncio.wait_for(pd.list_disputes(books, sample=demo), 8.0)
    except Exception:  # noqa: BLE001 - PayPal slow or unreachable: say so, never guess
        return {"asked_paypal": False, "_open": 0}
    live = [d for d in got.disputes if d.status != "RESOLVED"]
    mine = [d for d in live if d.status == "WAITING_FOR_SELLER_RESPONSE"]
    dates = [d.respond_by for d in mine if d.respond_by]
    f: dict[str, Any] = {
        "asked_paypal": True,
        "paypal_connected": got.connected,
        "open_disputes": len(live),
        "waiting_for_your_reply": len(mine),
        "amount_in_open_disputes": gbp(sum(d.amount_pence or 0 for d in live)),
        "disputes": [
            {
                "customer": d.customer or "not one of your invoices",
                "invoice": d.invoice,
                "amount": gbp(d.amount_pence or 0),
                "reason": d.reason_text,
                "status": d.status.replace("_", " ").lower(),
                "reply_by": _uk(d.respond_by),
                "sample": d.sample,
            }
            for d in live[:5]
        ],
        "_open": len(live),
    }
    if dates:
        f["reply_by"] = _uk(min(dates))
    if got.problem:
        f["problem"] = got.problem
    return f


def disputes_code_text(f: dict[str, Any]) -> str:
    if not f.get("asked_paypal"):
        return "PayPal did not answer just now, so I cannot say whether you have disputes open. Try again shortly."
    if not f["paypal_connected"] and not f["_open"]:
        return (
            "PayPal is not connected to these books, so there are no PayPal disputes to show. Connect it in Settings."
        )
    if not f["_open"]:
        return "You have no open PayPal disputes."
    n, mine = f["open_disputes"], f["waiting_for_your_reply"]
    out = f"You have {n} open PayPal dispute{'s' if n != 1 else ''}, {f['amount_in_open_disputes']} in all"
    out += f"; {mine} {'is' if mine == 1 else 'are'} waiting for your reply" if mine else ""
    out += f", the soonest by {f['reply_by']}." if f.get("reply_by") else "."
    return (
        out
        + " Open Invoices to see each one and the evidence Accnomos has drafted; nothing is sent until you approve it."
    )


async def waiting_facts(books: Books, demo: bool) -> dict[str, Any]:
    """What Sync PayPal is holding for approval: payments PayPal listed that are not in the books yet."""
    from app import paypal_sync as ps
    from app.ai.home_summary import gbp

    v = await ps.view(books, demo)
    todo = [i for i in v.items if i.status == "proposed"]
    return {
        "payments_waiting_for_approval": len(todo),
        "net_of_fees_in_them": gbp(sum(i.net_pence for i in todo)),
        "paypal_fees_in_them": gbp(sum(i.fee_pence for i in todo)),
        "oldest": _uk(min((i.date for i in todo), default=None)),
        "last_synced": _uk(v.last_synced_at.date()) if v.last_synced_at else None,
        "sample_history": v.sample,
        "_waiting": len(todo),
        "_available": v.available,
    }


def waiting_code_text(f: dict[str, Any]) -> str:
    if not f["_available"]:
        return "PayPal is not connected to these books yet, so there is nothing to sync. Connect it in Settings."
    if not f["last_synced"] and not f["_waiting"]:
        return "You have not synced PayPal yet. Open Invoices and choose Sync PayPal to bring in its transactions."
    if not f["_waiting"]:
        return f"Nothing is waiting in Sync PayPal (last synced {f['last_synced']}): every payment it found is decided."
    n = f["payments_waiting_for_approval"]
    return (
        f"{n} PayPal payment{'s are' if n != 1 else ' is'} waiting in Sync PayPal for your approval, "
        f"{f['net_of_fees_in_them']} after PayPal's fees; the oldest is from {f['oldest']}. "
        "Nothing is posted until you approve each one."
    )


async def bills_facts(books: Books) -> dict[str, Any]:
    """Bills you approved and planned to pay through PayPal, by when they fall due (app/billpay.py), none paid yet."""
    from app.ai.home_summary import gbp
    from app.paypal_reports import bill_payments

    b = await bill_payments(books, london_today())
    if b is None:
        return {"bills_planned_through_paypal": 0, "_n": 0}
    return {
        "bills_planned_through_paypal": b.due_now_count + b.within_30_days_count,
        "due_now_or_overdue": {"bills": b.due_now_count, "amount": gbp(b.due_now_pence)},
        "due_within_7_days": {"bills": b.within_7_days_count, "amount": gbp(b.within_7_days_pence)},
        "due_within_30_days": {"bills": b.within_30_days_count, "amount": gbp(b.within_30_days_pence)},
        "_n": b.due_now_count + b.within_30_days_count,
        "_pence": {"now": b.due_now_pence, "d7": b.within_7_days_pence, "d30": b.within_30_days_pence},
    }


def bills_code_text(f: dict[str, Any]) -> str:
    if not f["_n"]:
        return (
            "No approved bills are planned for PayPal and falling due in the next 30 days. Choose PayPal as the way to "
            "pay a bill, and save the supplier's PayPal email, on Purchases."
        )
    now, d7, d30 = f["due_now_or_overdue"], f["due_within_7_days"], f["due_within_30_days"]
    parts = []
    if now["bills"]:
        parts.append(f"{now['bills']} bill{'s' if now['bills'] != 1 else ''} ({now['amount']}) due now or overdue")
    if d7["bills"]:
        parts.append(f"{d7['bills']} ({d7['amount']}) due in the next 7 days")
    if d30["bills"] and d30["bills"] != d7["bills"]:
        parts.append(f"{d30['bills']} ({d30['amount']}) due within 30 days")
    return (
        "Through PayPal you have " + ", ".join(parts) + ". Nothing is paid until you approve each payout on Purchases."
    )


_BASE_RULES = (
    " Rules: 1) Quote figures exactly as they appear in FACTS (they carry £ and commas); never add, subtract or "
    "estimate. 2) Two or three short sentences of plain UK English markdown, no headings, no tables, no links. "
)
_PAYPAL_RULES = (
    _BASE_RULES + "3) Say these are by the books (what was approved), not PayPal's own live balance. Return JSON with "
    "answer_md and confidence."
)
_ANSWER_RULES = _BASE_RULES + "3) Return JSON with answer_md and confidence."
FEES_PROMPT = (
    "You answer a UK small business owner's question about what PayPal cost them, from FACTS worked out by code from "
    "their own ledger (PayPal fee entries). If paypal_fees is £0.00 say there are no PayPal fees in the books for "
    "that span." + _PAYPAL_RULES
)
HELD_PROMPT = (
    "You answer a UK small business owner's question about how much money is sitting in their PayPal account, from "
    "FACTS worked out by code from their ledger (the PayPal clearing account: payments approved, less fees, less "
    "payouts to the bank)." + _PAYPAL_RULES
)


DISPUTES_PROMPT = (
    "You answer a UK small business owner's question about their PayPal disputes from FACTS read from PayPal and "
    "matched to their invoices by code. Say how many are open, how many wait for their reply and by when, and the "
    "amount; never say a dispute is won or lost unless FACTS says so; never promise an outcome." + _ANSWER_RULES
)
WAITING_PROMPT = (
    "You answer a UK small business owner's question about the PayPal payments waiting in Sync PayPal for their "
    "approval, from FACTS worked out by code. Say how many wait and their figure after fees; remind them nothing is "
    "posted until they approve it." + _ANSWER_RULES
)
BILLS_PROMPT = (
    "You answer a UK small business owner's question about the supplier bills they have planned to pay through "
    "PayPal, from FACTS worked out by code (approved bills only, by due date). Nothing is paid until they approve "
    "each payout." + _ANSWER_RULES
)


async def question_answer(
    question: str, books: Books, cfg: AiConfig | None, period: AskPeriod, today: date, demo: bool = False
) -> AskAnswer | None:
    """The answer to a PayPal question (fees, money held or paid out, disputes, payments waiting in Sync PayPal,
    bills due through PayPal), or None when it is none of them."""
    from app import ask_more
    from app.books import EVENTS

    which = question_kind(question)
    if which is None:
        return None
    src = f"{EVENTS}/"
    if which == "fees":
        f = await fee_facts(books, question, today)
        code_text, prompt, name = fee_code_text(f), FEES_PROMPT, "ask_paypal_fees"
        keys = [
            KeyNumber(label=f"PayPal fees, {f['span']}", value=f["paypal_fees"], source=src),
            KeyNumber(label="Received through PayPal", value=f["received_through_paypal"], source=src),
        ]
        if f["fees_as_percent_of_received"]:
            keys.append(KeyNumber(label="Fees as % of received", value=f"{f['fees_as_percent_of_received']}%",
                                  source=src))  # fmt: skip
        nothing = not f["_pence"]["fees"]
    elif which == "held":
        f = await held_facts(books)
        code_text, prompt, name = held_code_text(f), HELD_PROMPT, "ask_paypal_held"
        keys = [
            KeyNumber(label="PayPal (books)", value=f["held_in_paypal_by_your_books"], source=src),
        ]  # fmt: skip
        if f["unpaid_invoices_with_a_paypal_link"]:
            keys.append(KeyNumber(label="Owed on invoices with a PayPal link", value=f["owed_on_those_invoices"],
                                  source=src))  # fmt: skip
        nothing = False
    elif which == "disputes":
        f = await disputes_facts(books, demo)
        code_text, prompt, name = disputes_code_text(f), DISPUTES_PROMPT, "ask_paypal_disputes"
        keys = []
        if f.get("asked_paypal"):
            keys.append(KeyNumber(label="Open PayPal disputes", value=str(f["open_disputes"]), source=src))
            if f["_open"]:
                keys.append(KeyNumber(label="In open disputes", value=f["amount_in_open_disputes"], source=src))
        nothing = not f["_open"]
    elif which == "waiting":
        f = await waiting_facts(books, demo)
        code_text, prompt, name = waiting_code_text(f), WAITING_PROMPT, "ask_paypal_waiting"
        keys = [KeyNumber(label="Waiting in Sync PayPal", value=str(f["_waiting"]), source=src)]
        if f["_waiting"]:
            keys.append(KeyNumber(label="After PayPal's fees", value=f["net_of_fees_in_them"], source=src))
        nothing = not f["_waiting"]
    else:
        f = await bills_facts(books)
        code_text, prompt, name = bills_code_text(f), BILLS_PROMPT, "ask_paypal_bills"
        keys = (
            [
                KeyNumber(label="Bills due within 7 days", value=f["due_within_7_days"]["amount"], source=src),
                KeyNumber(label="Bills due within 30 days", value=f["due_within_30_days"]["amount"], source=src),
            ]
            if f["_n"]
            else []
        )
        nothing = not f["_n"]
    shown = {k: v for k, v in f.items() if not k.startswith("_")}
    if nothing:
        text, by, why = code_text, "code", None
    else:
        text, by, why = await ask_more.worded(question, shown, prompt, code_text, cfg, name)
    return AskAnswer(
        answer_md=text,
        key_numbers=keys,
        citations=[src],
        suggested_actions=[],
        confidence="high" if by == "model" or nothing else "medium",
        model=cfg.model if (cfg and by == "model") else "code",
        period=period,
        fallback_reason=why,
    )


async def add_link_status(books: Books, facts: dict[str, Any]) -> None:
    """Into owed_facts (debtors): each customer's unpaid invoices with a PayPal link, and the totals. Counts only, by
    code; a failure leaves the facts as they were."""
    try:
        unpaid = await _unpaid(books)
    except Exception:  # noqa: BLE001
        return
    by: dict[str, dict[str, int]] = {}
    for inv, _b in unpaid:
        row = by.setdefault(act._norm(inv.customer.name), {"paypal": 0, "other": 0, "none": 0})  # noqa: SLF001
        link = inv.payment_link
        row["paypal" if link and link.provider in ("paypal", "paypalme") else "other" if link else "none"] += 1
    for c in facts.get("contacts", []):
        row = by.get(act._norm(c["name"]))  # noqa: SLF001
        if row:
            c["invoices_with_a_paypal_link"] = row["paypal"]
            c["invoices_without_a_pay_link"] = row["none"]
    facts["invoices_with_a_paypal_link"] = sum(r["paypal"] for r in by.values())
    facts["invoices_without_a_pay_link"] = sum(r["none"] for r in by.values())


def link_status_text(facts: dict[str, Any]) -> str:
    """The sentence code adds to "who owes me" about PayPal links (empty when there are no unpaid invoices)."""
    with_pp = facts.get("invoices_with_a_paypal_link")
    without = facts.get("invoices_without_a_pay_link")
    if with_pp is None or (not with_pp and not without):
        return ""
    out = f" {with_pp} of the unpaid invoices ha{'ve' if with_pp != 1 else 's'} a PayPal link"
    if without:
        out += f"; {without} ha{'ve' if without != 1 else 's'} no payment link"
    return out + ". Say “send a PayPal reminder to everyone who owes me” to chase them."
