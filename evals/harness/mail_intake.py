"""Mail eval: the 20 mailbox fixtures through Outlook intake (code) and inbox triage (code + Glimmer).

    cd evals && python -m harness.mail_intake [--no-model]   # writes runs/mail_intake/{report.md,result.json}

Intake: the fixtures (evals/gold/mail/M*.json, Graph shapes) go into a FakeMailProvider and the real
`app.intake.scan_mail` runs over them on a Books on fake storage, as the signed-in user (the fixtures'
toRecipients address). Every attachment is kept (copied to "00 Inbox") or dropped; the reason for a drop
comes from the same helpers scan_mail uses (skip_reason, score < THRESHOLD, duplicate). Graded against
each fixture's `expected.intake[].treat_as` (document -> kept, ignore -> dropped, duplicate -> dropped
as a duplicate).

Triage: the fixtures carry no triage truth, so TRIAGE_EXPECTED below was written before the first run,
from fixed rules (see each reason). "either" messages are reported but not scored. The code part is
`app.triage.group_threads` (filters + grouping); the model part is `app.ai.triage.triage_thread` with
Glimmer on Ollama. The fixtures have no conversationId, so each message is its own thread, as the real
code does when Graph sends none.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for extra in (
    REPO / "services" / "runtime",
    REPO / "packages" / "ledger" / "src",
    REPO / "packages" / "connectors" / "src",
):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from accnomos_connectors import FakeMailProvider, FakeStorageProvider  # noqa: E402
from accnomos_connectors.base import MailAttachment, MailMessage  # noqa: E402

from app import intake  # noqa: E402
from app.ai.config import AiConfig  # noqa: E402
from app.books import INBOX, Books  # noqa: E402
from app.triage import _thread, group_threads  # noqa: E402
from app.triage import skip_reason as triage_skip  # noqa: E402

MAIL = REPO / "evals" / "gold" / "mail"
BUSINESS = "Bramblewood Joinery Ltd"
TODAY = date(2026, 10, 27)
GLIMMER = AiConfig(mode="local", base_url="http://localhost:11434", model="muse-glimmer:30b")

#: Written before the first run. keep -> the thread should be listed (with this category); drop -> filtered out.
TRIAGE_EXPECTED: dict[str, tuple[str, str | None, str]] = {
    "M01": ("keep", "supplier", "a subcontractor sends an invoice"),
    "M02": ("either", None, "the user's own phone address on another domain: code cannot know it is the user"),
    "M03": ("drop", None, "no-reply sender (a receipt; intake's job, not a conversation)"),
    "M04": ("keep", "supplier", "a car park operator sends an invoice from accounts@"),
    "M05": ("either", None, "the user's own phone address on another domain"),
    "M06": ("drop", None, "no-reply sender"),
    "M07": ("either", None, "the business's own second domain (bramblewoodjoinery.example)"),
    "M08": ("either", None, "the user's own phone address on another domain"),
    "M09": ("drop", None, "no-reply sender"),
    "M10": ("drop", None, "a colleague on the user's own domain"),
    "M11": ("drop", None, "a colleague on the user's own domain"),
    "M12": ("drop", None, "a colleague on the user's own domain"),
    "M13": ("either", None, "the business's own second domain"),
    "M14": ("either", None, "the business's own second domain"),
    "M15": ("drop", None, "newsletter (news@, '% off')"),
    "M16": ("drop", None, "marketing (marketing@)"),
    "M17": ("either", None, "calendar invite from a client's booking system: listing it or not are both fine"),
    "M18": ("keep", "customer", "a client accepts a staircase quote"),
    "M19": ("keep", "supplier", "a mobile provider sends an invoice"),
    "M20": ("keep", "supplier", "a timber supplier sends terms, invoice to follow"),
}


def load_fixtures() -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(MAIL.glob("M*.json"))]


def to_message(f: dict[str, Any]) -> MailMessage:
    sender = f["from"]["emailAddress"]
    return MailMessage(
        id=f["id"],
        received_at=datetime.fromisoformat(f["receivedDateTime"].replace("Z", "+00:00")),
        from_address=sender["address"].lower(),
        from_name=sender.get("name", ""),
        subject=f.get("subject", ""),
        body_preview=f.get("bodyPreview", ""),
        is_read=False,
    )


def to_attachment(a: dict[str, Any]) -> MailAttachment:
    return MailAttachment(
        id=a["id"], name=a["name"], content_type=a["contentType"], size=a["size"], is_inline=a["isInline"]
    )


def user_of(fixtures: list[dict[str, Any]]) -> str:
    return fixtures[0]["toRecipients"][0]["emailAddress"]["address"].lower()


def mailbox(fixtures: list[dict[str, Any]]) -> FakeMailProvider:
    mail = FakeMailProvider()
    for f in fixtures:
        files = [(to_attachment(a), (MAIL / a["path"]).read_bytes()) for a in f["attachments"]]
        mail.add(to_message(f), *files)
    return mail


async def run_intake(fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    user = user_of(fixtures)
    books = Books(FakeStorageProvider())
    oldest = min(to_message(f).received_at for f in fixtures)
    since_days = (intake.now() - oldest).days + 2
    res = await intake.scan_mail(books, mailbox(fixtures), since_days=since_days, user=user, max_messages=100)
    saved = {(i.message_id, i.attachment_id) for i in res.items}
    rows: list[dict[str, Any]] = []
    for f in fixtures:
        m = to_message(f)
        want = {e["attachment"]: e["treat_as"] for e in f["expected"]["intake"]}
        for a in f["attachments"]:
            att = to_attachment(a)
            kept = (m.id, att.id) in saved
            if kept:
                reason = "kept"
            elif (why := intake.skip_reason(att)) is not None:
                reason = why
            elif (sc := intake.score(m, att, user)) < intake.THRESHOLD:
                reason = f"score {sc} < {intake.THRESHOLD}"
            else:
                reason = "duplicate"
            expected = want[a["name"]]
            ok = (
                kept
                if expected == "document"
                else (not kept and (reason == "duplicate" if expected == "duplicate" else True))
            )
            rows.append(
                {
                    "fixture": f"M{f['id'][-2:].zfill(2)}",
                    "subject": m.subject,
                    "gold": a["gold"],
                    "attachment": a["name"],
                    "expected": expected,
                    "kept": kept,
                    "reason": reason,
                    "score": intake.score(m, att, user),
                    "ok": ok,
                }
            )
    # The same document mailed twice: right when exactly one copy is kept and the other dropped as a duplicate.
    # (scan_mail reads newest first, so it is the later resend that gets kept.)
    copies = Counter(r["gold"] for r in rows if r["gold"])
    for g in (g for g, n in copies.items() if n > 1):
        group = [r for r in rows if r["gold"] == g]
        right = sum(r["kept"] for r in group) == 1 and all(r["kept"] or r["reason"] == "duplicate" for r in group)
        for r in group:
            r["ok"] = right
    docs = {r["gold"] for r in rows if r["expected"] != "ignore"}  # distinct documents
    kept_docs = {r["gold"] for r in rows if r["expected"] != "ignore" and r["kept"]}
    ignores = [r for r in rows if r["expected"] == "ignore"]
    dup_groups = [g for g, n in copies.items() if n > 1]
    return {
        "user": user,
        "since_days": since_days,
        "scanned": res.scanned,
        "candidates": res.candidates,
        "saved": len(res.saved),
        "inbox_files": len(await books.list_files(INBOX)),
        "skipped_duplicates": res.skipped_duplicates,
        "errors": res.errors,
        "documents": len(docs),
        "documents_kept": len(kept_docs),
        "decoys": len(ignores),
        "decoys_dropped": sum(not r["kept"] for r in ignores),
        "duplicates": len(dup_groups),
        "duplicates_caught": sum(all(r["ok"] for r in rows if r["gold"] == g) for g in dup_groups),
        "attachments": len(rows),
        "correct": sum(r["ok"] for r in rows),
        "rows": rows,
    }


async def run_triage(fixtures: list[dict[str, Any]], use_model: bool) -> dict[str, Any]:
    from app.ai import triage as triage_ai

    user = user_of(fixtures)
    msgs = [to_message(f) for f in fixtures]
    threads, skipped = group_threads(msgs, user, max_threads=100)
    by_id = {t.latest.id: t for t in threads}
    rows: list[dict[str, Any]] = []
    for f, m in zip(fixtures, msgs, strict=True):
        key = f"M{f['id'][-2:].zfill(2)}"
        want, cat, why = TRIAGE_EXPECTED[key]
        t = by_id.get(m.id)
        row: dict[str, Any] = {
            "fixture": key,
            "subject": m.subject,
            "from": m.from_address,
            "expected": want,
            "expected_category": cat,
            "why": why,
            "kept": t is not None,
            "drop_reason": None if t else (triage_skip(m) or "own_domain"),
        }
        if t is not None:
            base = _thread(t, user)
            row["code_category"] = base.category
            if use_model:
                out = await triage_ai.triage_thread(t, base, GLIMMER, user=user, business_name=BUSINESS, today=TODAY)
                failed = bool(out.fallback_reason) and (
                    "Your AI" in out.fallback_reason or "expected format" in out.fallback_reason
                )
                row.update(
                    {
                        "category": out.category,
                        "needs_reply": out.needs_reply,
                        "summary": out.summary,
                        "todos": [x.text for x in out.todos],
                        "fallback_reason": out.fallback_reason,
                        "model_failed": failed,
                    }
                )
        row["keep_ok"] = None if want == "either" else (row["kept"] == (want == "keep"))
        row["category_ok"] = (row.get("category") == cat) if (cat and row["kept"] and use_model) else None
        rows.append(row)
    scored = [r for r in rows if r["keep_ok"] is not None]
    cats = [r for r in rows if r["category_ok"] is not None]
    return {
        "model": GLIMMER.model if use_model else None,
        "skipped": skipped,
        "threads": len(threads),
        "scored": len(scored),
        "keep_drop_agree": sum(r["keep_ok"] for r in scored),
        "category_scored": len(cats),
        "category_ok": sum(r["category_ok"] for r in cats),
        "model_failures": sum(bool(r.get("model_failed")) for r in rows),
        "rows": rows,
    }


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({100 * a / b:.0f} %)" if b else "n/a"


def report_md(res: dict[str, Any]) -> str:
    i, t = res["intake"], res["triage"]
    out = [
        "# Mail: 20 mailbox fixtures through Outlook intake and inbox triage",
        "",
        "Generated by `cd evals && python -m harness.mail_intake`. Intake is `app.intake.scan_mail` (code only) over a fake",
        f"mailbox as `{i['user']}`; triage is `app.triage.group_threads` (code) plus `app.ai.triage.triage_thread`",
        f"({t['model'] or 'model part skipped'}). Truth: `evals/gold/mail/M*.json` `expected.intake`; the triage expectation is",
        "`TRIAGE_EXPECTED` in the harness, written before the first run.",
        "",
        "## Intake (code)",
        "",
        f"- Attachments graded correctly: **{pct(i['correct'], i['attachments'])}**",
        f"- Distinct documents kept: **{pct(i['documents_kept'], i['documents'])}**; decoy attachments dropped:"
        f" **{pct(i['decoys_dropped'], i['decoys'])}**; document mailed twice saved once: **{pct(i['duplicates_caught'], i['duplicates'])}**",
        f"- scan_mail: {i['scanned']} messages with attachments scanned, {i['candidates']} candidates, {i['saved']} saved to the inbox folder,"
        f" {i['skipped_duplicates']} skipped as duplicates, {len(i['errors'])} errors",
        "",
        "| Msg | Subject | Attachment | Expected | Result | Score | |",
        "|---|---|---|---|---|---:|---|",
    ]
    for r in i["rows"]:
        out.append(
            f"| {r['fixture']} | {r['subject'][:44]} | {r['attachment']} | {r['expected']} | {r['reason']} | {r['score']} |"
            f" {'ok' if r['ok'] else '**miss**'} |"
        )
    misses = [r for r in i["rows"] if not r["ok"]]
    out += ["", "Misses:", ""]
    out += [f"- {r['fixture']} `{r['attachment']}` (expected {r['expected']}): {r['reason']}" for r in misses] or [
        "- None."
    ]
    out += [
        "",
        "Note: the fixture attachments carry gold file names (`071_utility.pdf`, `190_r_fuel.png`), not the names a supplier would",
        "use (`Invoice LMS-92838.pdf`), so the attachment-name keyword (+0.3) never fires. A document is kept only through the",
        "subject keyword, the PDF bonus and the sender not being the user. The filter was not tuned to these fixtures.",
        "",
        "Every document miss is mail from a colleague on the user's own domain (`ops@bramblewood.example`, M10-M12): `score`",
        "gives +0.15 only to senders who are not the user or their domain, so a forwarded photo with a keyword subject scores",
        "0.3 against the 0.4 threshold (a forwarded PDF scores 0.45 and is kept). That is the filter's stated design, not a",
        "crash or a parsing bug, so it is reported here and not changed. In practice a bookkeeper or colleague forwarding",
        "receipts from the same domain is a common case, and it is worth revisiting.",
        "",
        "## Triage",
        "",
        f"- Keep/drop agrees with the expectation on **{pct(t['keep_drop_agree'], t['scored'])}** unambiguous messages"
        f" ({len(t['rows']) - t['scored']} 'either' messages not scored)",
        f"- Code filter dropped: {', '.join(f'{k} {v}' for k, v in t['skipped'].items())}; {t['threads']} threads listed",
    ]
    if t["model"]:
        out.append(
            f"- Category ({t['model']}) right on **{pct(t['category_ok'], t['category_scored'])}** expected-keep threads;"
            f" model failures (no usable answer): {t['model_failures']}"
        )
    out += ["", "| Msg | From | Expected | Listed | Category (want) | Reply? | |", "|---|---|---|---|---|---|---|"]
    for r in t["rows"]:
        listed = "yes" if r["kept"] else f"no ({r['drop_reason']})"
        cat = f"{r.get('category', '-')} ({r['expected_category'] or '-'})"
        mark = "" if r["keep_ok"] is None else ("ok" if r["keep_ok"] and r["category_ok"] is not False else "**miss**")
        out.append(
            f"| {r['fixture']} | {r['from']} | {r['expected']} | {listed} | {cat} | "
            f"{'yes' if r.get('needs_reply') else '-'} | {mark} |"
        )
    if t["model"]:
        own = [r["fixture"] for r in t["rows"] if r["expected"] == "either" and r["kept"] and r.get("needs_reply")]
        out += [
            "",
            f"'Either' messages the model marked as needing a reply: {', '.join(own) or 'none'}. The user's own phone"
            " address (M02/M05/M08) and the business's second domain (M07/M13/M14) look like outside senders to code (no list of the user's"
            " other addresses), so they are listed and can be offered a reply to the user themselves.",
        ]
    out += ["", "Expectation reasons:", ""]
    out += [f"- {k}: {w}{f' ({c})' if c else ''}: {why}" for k, (w, c, why) in TRIAGE_EXPECTED.items()]
    return "\n".join(out) + "\n"


async def run(use_model: bool = True) -> dict[str, Any]:
    fixtures = load_fixtures()
    return {"intake": await run_intake(fixtures), "triage": await run_triage(fixtures, use_model)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=REPO / "evals" / "runs" / "mail_intake")
    ap.add_argument("--no-model", action="store_true", help="skip the Glimmer part of triage")
    args = ap.parse_args()
    res = asyncio.run(run(not args.no_model))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "result.json").write_text(json.dumps(res, indent=1, default=str) + "\n", encoding="utf-8")
    (args.out / "report.md").write_text(report_md(res), encoding="utf-8")
    i, t = res["intake"], res["triage"]
    print(
        f"intake: documents kept {pct(i['documents_kept'], i['documents'])}, decoys dropped {pct(i['decoys_dropped'], i['decoys'])},"
        f" duplicate caught {pct(i['duplicates_caught'], i['duplicates'])}; triage keep/drop {pct(t['keep_drop_agree'], t['scored'])},"
        f" category {pct(t['category_ok'], t['category_scored'])}, model failures {t['model_failures']}"
    )


if __name__ == "__main__":
    main()
