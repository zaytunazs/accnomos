# Review: `claude/chat-actions`

Second-agent review of the chat/voice actions task (`TASK_BRIEF.md`).

## What was checked

- `services/runtime`: `pytest -q`. Before the fixes: 275 passed, 2 skipped. After: 277 passed, 2 skipped.
  `packages/*` and `services/hmrc-relay` are not touched by this branch, so they were not re-run.
- `apps/web`: `pnpm run build` passes.
- `apps/mobile`: read the diff only. `flutter`/`dart` are not installed on this machine, so `flutter analyze` was **not** run.
- Read the whole diff: `app/actions.py`, `routes_actions.py`, `routes_ask.py`, `schemas.py`, `ai/ask.py`, `ActionCard.tsx`,
  `AskThread.tsx`, `runtime.ts`, the mobile model, client and screen, `docs/ACTIONS.md` and the README row.
- Product rules hold:
  - the model returns only a strict, enumerated intent, with figures quoted as text;
  - code parses those figures and refuses any the user did not say;
  - code resolves names against the user's lists (difflib ≥ 0.8, otherwise it asks with candidates), and the lists never go to the model;
  - VAT and totals are worked out in integer pence (half up per line), and the invoice module re-prices on approval;
  - nothing is executed without `POST /actions/approve`;
  - there is no server state: the proposal is HMAC-signed with a key derived from `ACTIONS_SIGNING_KEY` and the Graph token hash;
  - the audit log is in the user's own OneDrive and nothing is written on the server.
  - No secrets were found in the diff.
- Approve and reject routes: they need `X-Graph-Token` and `X-User` (web and mobile both send these). They map `ActionError`
  to 403/410/409/501 and module refusals to 409. Approve runs once (claim line → executed line). A failed run can be retried.
  Reject blocks approve, and approve blocks reject.

## What I fixed

- `cb22e18`:
  - Invoice line quantities were formatted with `Decimal.normalize()`, so whole tens showed as `"1E+1"` and `"1E+2"` on the card
    and in the preview. They are now plain (`"10"`, `"2.5"`).
  - Payment terms (`due_days`) from the model were accepted even if the user never said them, unlike every other figure.
    They are now ignored unless the number is in the user's words, so the profile's terms apply (as `docs/ACTIONS.md` already said).
  - Tests added for both.

## What remains

- **`flutter analyze` not run** (no Flutter SDK here). The mobile card, client and model changes have only been read.
- **Signing key across processes.** Without `ACTIONS_SIGNING_KEY`, each runtime process makes a random key. With several
  workers or replicas, or after a restart, a proposal can fail with 403 ("changed, or made in another session"). This is
  documented in `docs/ACTIONS.md`, but no deployment config sets the variable yet.
- **Stuck `approving`.** If the runtime dies between the `approving` and `executed` audit lines, that action id stays blocked
  (409) on purpose. There is no UI to clear it; the user asks again.
- **"Today" is the UTC date** (`books.now()`). Between midnight and 1am during BST, an invoice issue date, a "yesterday", or
  a due date can be one day behind the UK date. Fixing it needs `zoneinfo` plus `tzdata` in the runtime image, which the
  runtime does not use anywhere yet.
- **Audit path case.** The brief says `_System/Audit/actions/`; the code uses the repo's existing `AUDIT` constant
  (`_System/audit/actions/`), as all other audit files do. The docs match the code.
- **Invoices, chasers and mileage only work when other branches land.** Invoice and chaser actions need `app/invoicing.py`
  (`claude/invoicing`); mileage needs `app/mileage.py` with `add_entry`. Until then Ask says they aren't available. Sending
  needs `GraphMailSender` in the connectors (import-guarded); without it a "send" ends as a draft with the reason given.
- **Not run against a real model, OneDrive or Graph mail.** The voice path with an action (`/books/ask/voice`) has no route
  test, because it needs ffmpeg. It shares `_answer` with `/books/ask`, which is tested.

## How to verify by hand

1. Run the runtime with a Meta/Ollama model configured, and set `ACTIONS_SIGNING_KEY` to any long random string.
2. Sign in on the web app with a OneDrive that has some customers in contacts, plus one open job and one staff member.
3. On Ask, type "log 7.5 hours for Sam on the Elm Road job". You should get a Timesheet card with the right person, job,
   today's date and 7.5 hours.
4. Approve it. The card should show "Logged 7.5 hours…", the entry should appear on the job page, and
   `_System/audit/actions/<yyyy-mm>.jsonl` should have an `approving` line and an `executed` line.
5. Ask "log 3 hours for Hartley on Elm Road" with two similar staff names. You should see "Which staff member…" with
   name chips, and picking one should re-ask and show a card.
6. Reject a card. It should say "Rejected. Nothing was done." and a `rejected` line should be audited.
7. Edit a card's preview in devtools and approve it. You should get 403.
8. With `claude/invoicing` merged, "send a £100 invoice to JM Trading for this month's work" should show £100 + £20 VAT =
   £120, due on the profile's terms, "Work for <Month Year>". Approve it and check that the invoice number and recipient
   are shown.
9. Repeat steps 3 and 4 on the mobile Ask screen.
