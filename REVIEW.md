# Review: `claude/inbox-triage`

Second-agent review of the inbox triage task (`TASK_BRIEF.md`): Home *Inbox* card, Outlook reply drafts, to-dos.

## What was checked

- **Tests**, each run with absolute `-o pythonpath` so this checkout's code is imported (the shared venv points at another lane):
  - `services/runtime`: 544 passed before the review, 547 after (3 new).
  - `packages/connectors`: 32 passed. `packages/ledger`: 31 passed (not touched by this branch).
  - `services/hmrc-relay`: not touched by this branch, so not run.
  - `apps/web`: `pnpm run build` passes, before and after the review.
- **Diff read line by line** (connectors, runtime, web, docs) against the brief and the product rules:
  - Graph reads: Inbox folder only, the brief's `$select` exactly, `bodyPreview` clipped to 255 characters, no full bodies.
  - The one mailbox write is `createReply` + `PATCH`. Nothing is sent, and a test asserts no `/send` path is called.
  - `Mail.ReadWrite` is asked for only by `runtime.draftReply` (incremental consent). The pending reply is kept in
    sessionStorage across the consent redirect.
  - The AI is used only when the app sends `X-AI-Mode`, never the server's fallback model. Email text is treated as
    untrusted in the prompt. Code checks every answer: one-line summary, no links, no invented figures (`KnownNumbers`),
    no reply to no-reply senders, due dates in a sane window, to-dos de-duplicated and capped.
  - Nothing is kept server-side. Audit lines hold counts and ids only (a test asserts no sender name).
    `todos.json` lives in the user's folder, guarded by If-Match.
  - API boundaries: strict bodies (unknown keys such as `send` give 422), the `message_id` pattern, an https-only
    to-do source link, 404 / 409 / 400 / 401 mapping, Graph 401/403 → 401 via the existing handler.
  - No pence or decimal arithmetic in this feature. No synthetic company data added. UK English throughout.
- **Docs**: the README row and `docs/INBOX.md` match the code (scopes, fields, limits, what is written, what is never done).

## What I fixed

- `cdab9ad`: three wording and doc fixes.
  - The Settings copy said only the 255-character preview goes to the AI. The sender and subject go too, and it now
    says so.
  - The no-AI fallback note said "only the subject is shown"; it now says the summary is just the sender and subject.
  - A garbled comment on `MESSAGES_PER_THREAD_CAP` is fixed.
  - `docs/INBOX.md` now lists the half-made draft case as a known limit (see below).
- `be84e07`: tests the brief's behaviour implied but nobody had tested.
  - `/mail/triage` calls a model only when `X-AI-Mode` is sent, and the result reports that model.
  - A Graph 403 on `/mail/draft-reply` (no `Mail.ReadWrite`) returns 401 and writes no audit line.
  - A hand-edited `todos.json` that is not a list gives 409 on GET and POST and is left untouched.

## What remains

- **Half-made draft:** `create_reply_draft` is two Graph calls. If the `PATCH` fails after `createReply` succeeded,
  an empty reply (just the quoted thread) stays in the user's Drafts. This is now documented, not fixed: deleting it
  automatically would break the "Accnomos never deletes mail" promise, so that is a product decision.
- **Bad AI headers fall back silently:** if `X-AI-Mode` is sent but the config is invalid (for example a base URL not
  on the allow-list, or no key), triage silently runs without a model. The card then says "No AI is set up" instead
  of naming the bad setting.
- **Answered threads:** Sent Items are not read, so a thread the user already answered can still show *Reply*
  (documented in `docs/INBOX.md` Known limits).
- **Real services:** not run against a real mailbox, a real Meta or local model, or a real OneDrive. Every test uses
  a fake mailbox and fake storage with a stubbed model, plus Graph request shapes against a mock transport.
- **Web components:** no unit tests (the repo has no web test runner). They are checked only by `pnpm run build`
  (TypeScript).

## How to verify by hand

Start the runtime and `apps/web`, then sign in with a Microsoft account that has a few recent emails: one from a
customer-like address, one newsletter, one `noreply@` and one HMRC message. Set up your AI under Connect › AI, then
turn on Settings › Automation › *Inbox triage* and accept `Mail.Read`. On Home, the *Inbox* card should list only
the business threads, with category, one-line summary and to-dos. Newsletters and no-reply senders should be absent,
except gov.uk. Expand a customer thread, edit the suggested reply and tap *Draft in Outlook*. Microsoft should ask
for `Mail.ReadWrite` once, and after the redirect your edited text should still be there. Tap again: a draft
appears in Outlook Drafts as a reply in that thread with your text above the quote, and **nothing is sent**. Tap
*Add* on a to-do: it appears in the *To-dos* tile and in `_System/Todos/todos.json` in your OneDrive, and *Done*
removes it. Check `_System/audit/<yyyy-mm>.jsonl` for `mail_triaged` (counts only), `mail_draft_created`,
`todo_added` and `todo_deleted`, with no email text. Finally, clear the AI settings and refresh: threads should still
list with "sender: subject" summaries and no suggested replies.
