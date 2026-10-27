# Task: Audit trail page — every action in the books, who or what did it (user vs agent), filters, export; nothing editable

Accnomos monorepo (public; UK English; no secrets). The runtime already writes `_System/audit/*.jsonl` (books), `_System/audit/actions/`
(chat/voice actions) and Autopilot lines with `user:<email>` / `agent:<name>` actors. Read first `services/runtime/app/books.py` (`audit`,
`audit_autopilot`), every `books.audit(` call (`grep -rn "audit(" services/runtime/app`), `docs/ARCHITECTURE.md` (audit actors),
`docs/ACTIONS.md`, `docs/AUTOPILOT.md`, `apps/web/src/components/settings/SettingsPanels.tsx` (the dead "Open _System/audit" link).

## Deliverables
1. `GET /audit?from=&to=&actor=&kind=&limit=` reads the month files for the range (newest first, capped at 500), normalises every
   line to `{ts, actor, actor_kind: user|agent, event, summary, refs: {proposal, event, invoice, action, file}}` with a plain-English
   summary per event kind (a table in `app/audit_view.py`; unknown kinds fall back to the kind name). Read-only; tests on fake storage
   covering a day with approvals, an undo, an Autopilot post, an action, a triage run, a folder rename.
2. Web `/audit`: a timeline grouped by day with actor chips (You / Autopilot / Intake / Triage / Planner), filters, each row linking to
   the thing (Review card, invoice, file); "Export CSV" (reuse the existing csv helper); Settings' audit link points here. Signed out: a
   labelled sample day.
3. Android: a read-only Audit screen in More (list, day headers, actor chips); thin client call only.
4. `docs/ARCHITECTURE.md` audit section updated; README row; e2e spec (`audit.spec.ts`) that performs three actions and sees them.
Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
