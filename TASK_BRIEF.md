# Task: Inbox triage on the dashboard — replies summarised, suggested answers as Outlook drafts, to-dos extracted

Accnomos monorepo (public; UK English; no secrets; stateless runtime). Read first: `services/runtime/app/{intake.py,routes_mail.py}`,
`packages/connectors/.../msgraph.py` (mail provider), `ai/ask.py` (model backends + strict JSON), `apps/web/src/components/home/*`,
`apps/web/src/lib/{runtime.ts,msal.ts}`.

## Goal
Home shows an **Inbox** card: the last 7 days of business-relevant threads (customers, suppliers, HMRC, accountant), each with a
one-line summary, a suggested reply and extracted to-dos with due dates. "Draft reply" creates an **Outlook draft** (Graph
`POST /me/messages` with `isDraft`, or `createReply`) — the user sends from Outlook; Accnomos never sends automatically. "Add to list"
saves the to-do in `_System/Todos/todos.json` (user's folder).

## Runtime
- Scopes: `Mail.Read` (existing) for reading; `Mail.ReadWrite` requested only when the user clicks *Draft reply* (incremental consent).
- `POST /mail/triage {since_days=7, max_threads=20}`: code first — fetch messages (`$select=id,conversationId,subject,from,receivedDateTime,
  bodyPreview,isRead,webLink`, skip newsletters/no-reply/own-domain-only threads, group by `conversationId`); then one strict-JSON model
  call per thread (user's AI config) with the *bodyPreview* only (≤ 255 chars each, never full bodies in this task) returning
  `{category: customer|supplier|hmrc|accountant|other, summary, needs_reply: bool, suggested_reply: str|null, todos: [{text, due: date|null}]}`;
  code validates and clips. Response lists threads with `web_link`.
- `POST /mail/draft-reply {message_id, body}` → Graph createReply + PATCH body → returns the draft `webLink`. Audit line.
- `GET/POST/DELETE /todos` on `_System/Todos/todos.json`.
- Tests: grouping/filtering, model stub, draft creation call shape (fake mail provider gains `create_reply_draft`), todos CRUD.

## Web
- Home `InboxTriage` card (collapsed list, expand → summary, suggested reply with *Draft in Outlook*, to-dos with *Add*), a `Todos` tile,
  "Last triage" time in localStorage. Settings: "Inbox triage" switch under Automation. `pnpm run build` passes; README row;
  `docs/INBOX.md` (what is read, what is written, what is never done).
Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify with a real mailbox.
