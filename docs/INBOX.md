# Inbox triage

Home's *Inbox* card lists the last 7 days of business email (customers, suppliers, HMRC, your accountant), each thread
with a one-line summary, a suggested reply and the to-dos in it. Turn it on in **Settings › Automation › Inbox triage**.

Code: `services/runtime/app/triage.py` (reading, filtering, grouping), `app/ai/triage.py` (the model call and its
checks), `app/todos.py`, `app/routes_mail.py`, `app/routes_todos.py`; Graph calls in
`packages/connectors/src/accnomos_connectors/msgraph.py` (`list_recent`, `create_reply_draft`); web in
`apps/web/src/components/home/{InboxTriage,TodosTile}.tsx` and `components/settings/InboxTriageSetting.tsx`.

## Permissions

| Scope | Asked for | Used for |
|---|---|---|
| `Mail.Read` | when you switch Inbox triage on (or Outlook intake) | reading the Inbox list |
| `Mail.ReadWrite` | the first time you tap *Draft in Outlook* | saving that one reply as a draft |

`Mail.Send` is **not** used by triage. (Invoices ask for it separately when you send one.)

## What is read

- **Only the Inbox folder** (`/me/mailFolders/inbox/messages`), not Junk, Deleted, Sent, Drafts or archives, for the
  last 7 days (at most 250 messages).
- **Only these fields:** `id, conversationId, subject, from, receivedDateTime, bodyPreview, isRead, webLink`.
  `bodyPreview` is the first 255 characters of the email that Outlook already keeps. **Full bodies and attachments
  are never fetched** by triage.
- Dropped by code before any AI sees them: newsletters and bulk mail (sender such as `newsletter@`, `marketing@`, or
  "unsubscribe" / "view in browser" / "webinar" in the subject or preview), no-reply senders (`noreply@`,
  `donotreply@`, `notifications@`, `mailer-daemon@` …) and threads where every message is from you or a colleague
  on your own domain (only your exact address counts if you use Gmail, Outlook.com and similar). Senders on
  `gov.uk` are **never** dropped, even from a no-reply address, because HMRC writes that way.
- What goes to the AI, per thread (at most 20 threads): today's date, your business name, the subject, and for the
  newest 5 messages the sender's name and address, the date and the preview (≤ 255 characters each).

## Which AI

Your own, as chosen in the app (Meta Model API key or your local model). If the app sends no AI choice, **no model
is called** and each thread shows "sender: subject" written by code. Triage never falls back to a model configured
on the server. Email text is passed to the model as untrusted data; the prompt tells it never to follow
instructions inside emails, and code checks everything it returns:

- **category** must be one of customer, supplier, hmrc, accountant, other (strict JSON schema);
- **summary** is cut to one line of 160 characters;
- **suggested reply** is offered only if the model says a reply is needed *and* the sender can be answered (never to
  a no-reply address, so never "to HMRC"). It is dropped (the rest of the answer is kept, with a note) if it is over
  1,500 characters, contains a link, or quotes a figure that is not in the subject or previews;
- **to-dos**: at most 5, one line each, duplicates removed; a due date is kept only if it is a real `YYYY-MM-DD`
  between 7 days ago and a year ahead, otherwise the to-do has no date.

If the model fails or answers in the wrong shape, the thread is still listed, with the code-written summary and the
reason.

## What is written

| Where | What | When |
|---|---|---|
| Your Outlook **Drafts** | one reply: Graph `POST /me/messages/{id}/createReply`, then `PATCH` of its body with your text above the quoted thread | only when you tap *Draft in Outlook* |
| `_System/Todos/todos.json` (your folder) | `{id, text, due, source: {message_id, subject, web_link}, created_at, created_by}` | when you tap *Add*; *Done* removes it |
| `_System/audit/<yyyy-mm>.jsonl` (your folder) | `mail_triaged` (counts only: messages read, threads, skipped, model failures, model name), `mail_draft_created` (message id, draft id, length of the reply), `todo_added`, `todo_deleted` | each triage, draft and to-do change |
| This browser, `localStorage` | the switch (`accnomos.triage.mail`) and the time and thread count of the last triage | |
| This browser, `sessionStorage` | the last triage result and a reply waiting for Microsoft consent; gone when the tab closes | |

Home triages again when the last result is more than 30 minutes old, or when you tap *Refresh*.

## What is never done

- **Nothing is ever sent.** A draft waits in Outlook until you open it, check it and press Send yourself.
- Nothing in the mailbox is moved, flagged, categorised, marked read or deleted.
- No full email bodies or attachments are read by triage.
- Nothing is kept on the Accnomos server: the runtime is stateless; mail text exists only for the length of the request.
- No previews, summaries or suggested replies are written to your OneDrive. A to-do you add keeps its own text, the
  email's subject and a link to it; audit lines keep counts and ids only.
- No model you did not choose sees your email.

## API

| Route | Body | Returns |
|---|---|---|
| `POST /mail/triage` | `{since_days: 1–30 = 7, max_threads: 1–50 = 20}` | `{since_days, scanned, skipped: {no_reply, newsletter, own_domain}, threads: [{conversation_id, message_id, subject, from_name, from_address, received_at, unread, message_count, web_link, category, summary, needs_reply, suggested_reply, todos: [{text, due}], fallback_reason}], model, generated_at}` |
| `POST /mail/draft-reply` | `{message_id, body}` (needs `X-User`) | `{draft_id, web_link}`; 404 if the email is gone |
| `GET /todos` | | to-dos, soonest due first, undated last |
| `POST /todos` | `{text, due?, source?}` (needs `X-User`) | 201 new; 200 with the existing entry if the same text from the same email is already there |
| `DELETE /todos/{id}` | (needs `X-User`) | the removed to-do; 404 if not there |

All take the usual `X-Graph-Token` / `X-Account-Kind` headers; AI headers are optional for triage.

## Known limits

- The preview is all the AI sees, so a request buried past the first 255 characters is missed, and summaries of long
  threads are only as good as their newest few previews.
- The no-reply and newsletter rules are simple patterns: an automated email from an unusual address can get through
  (it usually lands under *Other*), and a real person writing from `notifications@` would be dropped.
- Your own replies live in Sent Items, which is not read, so a thread you have already answered can still say *Reply*.
- A draft is two Graph calls (`createReply`, then `PATCH`). If the second fails, an empty reply (just the quoted
  thread) is left in Drafts and the app shows the error; Accnomos does not delete it, so delete it in Outlook.
- `webLink` opens Outlook on the web; whether it opens the desktop app depends on your system.

# Documents in 00 Inbox: formats and email receipts

Whatever lands in `00 Inbox` (uploaded, captured on the phone, or copied by Outlook intake) is read by the same
extractor prompt, goes through the same checks and becomes the same Review card. Before any model sees a file,
`services/runtime/app/formats.py` (`prepare`) makes it readable. The type comes from the file's bytes, not its name.

| What arrives | What the model gets | Filed as |
|---|---|---|
| JPEG, PNG, WebP | the photo, turned upright when its EXIF orientation says so | the original |
| HEIC/HEIF (iPhone) | a JPEG made from it (`pillow-heif`) | the JPEG; the Inbox scan moves the HEIC to `_System/Originals/`, never deletes it. Outlook intake saves the JPEG straight away |
| PDF with text | page 1 rendered at 200 dpi (at most 2,400 px a side) **and** page 1's text, both in one request | the PDF |
| Scanned PDF (no text layer) | page 1 rendered, nothing else | the PDF |
| Email body (`.eml.txt`) | the text only: sender, date, subject, then the body | the `.txt` |

- **A multi-page PDF is one document.** Every page's text is extracted (so the page count is known), but only page 1's
  text and image go to the model: on almost every invoice the supplier, date, VAT number and totals are on page 1. A
  total printed only on page 2 is missed, and the card says "PDF, N pages: page 1 read".
- **A scanner batch (several receipts in one PDF) is not split.** It is read as one document from page 1. Splitting
  by page on request is not built; until it is, scan receipts one per file or split the PDF before uploading.
- Document text goes to the model between markers, as data from the document, never instructions; the Verifier gets the
  same text. A text document is not re-read at higher resolution (the same text reads the same twice).
- The card shows a note (`SOURCE`) with what was done: "PDF, 3 pages: page 1 read", "HEIC photo converted to JPEG",
  "Photo turned upright (EXIF orientation)", "Email text, read without an image".

## Limits

| Limit | What happens |
|---|---|
| 25 MB per file | Inbox scan: not downloaded, stays in `00 Inbox`, listed as an error each scan until replaced. `POST /extract`: 413. Outlook intake: not copied |
| 50 million pixels per image (a 48 MP phone photo fits) | refused from the image header, before decoding: an image bomb costs nothing |
| 20 pages per PDF | refused: "PDF has N pages; up to 20 are read. Split it and send the invoice on its own" |
| 20,000 characters of document text to the model | the rest is cut (Outlook intake also keeps at most 100,000 characters of a body) |

A file that is refused for any reason other than size (too many pixels or pages, damaged, password-protected, a HEIC
on a server without `pillow-heif`: "export the photo as JPEG") becomes a **needs-a-look card** (`UNREADABLE`) with the
reason, filed in `02 Needs a look`, so it never blocks the Inbox. `POST /extract` answers 422 with the same message.

## Receipts written in an email (Outlook intake)

Many receipts never come as an attachment: ride and delivery apps, online shops, software subscriptions. Outlook intake
(`app/intake.py`) also lists **Inbox** messages **without attachments** from the same 14 days (Graph
`/me/mailFolders/inbox/messages`, `hasAttachments eq false`, with `bodyPreview`). Plain code, no AI:

1. **Worth reading?** From the listing alone: not from you or your own domain, not from a bulk sender
   (`news@`, `marketing@`, `offers@` …), no sale words in the subject (`% off`, sale, deals, webinar …), and a receipt
   word in the subject or preview (receipt, invoice, order, payment, paid, trip, ride, booking, subscription, billing,
   VAT, total …). Only then is the full body fetched, as plain text (`Prefer: outlook.body-content-type="text"`).
2. **Looks like a receipt?** A *total*, *VAT*, *invoice*, *receipt*, *amount paid/due/charged* or *balance due* label
   followed by a currency amount (£, €, $, GBP, EUR, USD) on the same line, or the label alone and the amount on the
   next line (how Graph writes an HTML table as text). "£1,450 plus VAT" in a reply is prose and does not count.
3. **Saved** as `00 Inbox/<yyyy-mm-dd>_<sender-domain>_<subject>.eml.txt`: `From`, `Date` and `Subject` lines, then the
   body. Deduplicated like attachments (message id in `seen.json` with `attachment_id: "body"`, and the file's hash).

Bodies that are not receipts are not saved and not logged; they are fetched again on the next check if still in the
window. Tested on six fictional fixtures, `evals/gold/mail/B01.json` to `B06.json` (three receipts, three decoys), and
the twenty attachment fixtures, whose results do not change.
