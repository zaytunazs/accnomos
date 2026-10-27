# Task: Autopilot L1 — "Always do this for <supplier>" rules and auto-approval with audit

Accnomos monorepo (public; UK English; no secrets; stateless runtime; AI proposes, user approves, code calculates).
Read first: `README.md`, `docs/DEV.md`, `services/runtime/app/{routes_books.py,approve.py,inbox.py,pipeline.py,books.py,checks.py}`,
`packages/ledger/src/accnomos_ledger/events.py`, `apps/web/src/components/review/*`, `apps/web/src/lib/runtime.ts`.

## Goal
When the user approves a proposal with **"Always do this for <supplier>"** ticked, Accnomos saves a rule in the user's folder
(`_System/Rules/rules.json`, append/replace by supplier key). On later scans, a proposal that matches a rule **and** passes all
code checks (no warnings) is auto-approved and posted, with an audit line, and shown in Review under "Approved by Autopilot — undo".
Nothing is ever auto-approved when a check warns, when the amount is > 2× the rule's typical amount, or when the supplier's VAT number differs.

## Runtime
- Rule schema: `{ supplier_key (normalised name), category, vat_code, side, typical_gross_pence, vrn|null, created_at, created_from_proposal_id, hits }`.
- `POST /books/approve/{id}` accepts `{ "remember": true }` → writes/updates the rule.
- Scan path: after proposals are built, evaluate rules (`app/autopilot.py`): decide `auto_approve: bool` with a `reason` list; auto-approved
  ones are posted via the existing approve code path with `approved_by: "autopilot"` and recorded in `_System/Audit/autopilot/<yyyy-mm>.jsonl`.
- `POST /books/undo/{event_id}`: append a reversing ledger event (never delete) and mark the proposal back to pending.
- `GET /books/rules` and `DELETE /books/rules/{supplier_key}`.
- Tests with fake storage: rule creation, match + auto-approve, each refusal reason, undo reversal balances.

## Web
- Review card: the "Always do this for X" checkbox is wired to `remember`. A section "Approved by Autopilot (n)" with Undo buttons.
- Settings: "Autopilot rules" list with remove buttons, and a master switch (localStorage) that sends `X-Autopilot: off` to skip auto-approval.
- README row + `docs/AUTOPILOT.md` (what it does, what it never does). `pnpm run build` passes.

Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
