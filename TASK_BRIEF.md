# Task: Chat/voice actions — "send a £100 invoice to JM Trading for this month's work" → proposal card → approve → done

Accnomos monorepo (public; UK English; no secrets; stateless runtime). Read first: `services/runtime/app/{routes_ask.py,ai/ask.py}`,
the invoicing, contacts, jobs and vehicles modules on main (`routes_invoices.py`, `contacts.py`, `jobs.py`, `mileage.py` — whatever has
landed; for anything not yet merged, read its brief in `~/spark/accnomos/jobs/*_task.md` and code against that contract behind a
feature check so the build never breaks), `ai/extract.py` (Meta/Ollama backends), `apps/web/src/app/ask/*`, `apps/mobile/lib/screens/ask_screen.dart`.

## Goal
`POST /books/ask` (and `/ask/voice`) can return, instead of or alongside an answer, a **proposed action** the user must approve.
The model only produces a structured intent; code resolves entities, computes money and executes. Nothing is sent or posted without
`POST /actions/{id}/approve`.

## Runtime
- `app/actions.py`: intent schema (strict JSON, enumerated): `create_invoice {customer_ref, description, amount_pence|null, lines[]|null,
  vat_code|null, due_days|null, send: bool}`, `chase_invoice {customer_ref|invoice_ref}`, `log_mileage {miles, from, to, job_ref|null,
  vehicle_ref|null, date|null}`, `log_timesheet {staff_ref, job_ref, hours, date|null}`, `none`. Resolution in code: customer/job/staff/
  vehicle by fuzzy match against the user's lists (difflib ≥ 0.8; otherwise return `needs_clarification` with the candidates); VAT and
  totals by code; "this month's work" → description text only.
- Proposed action object: `{ id, kind, summary_md, preview (the resolved invoice/mileage/timesheet payload), confirm_text, expires_at }`
  kept **client-side only** (returned to the client, re-posted on approve; the runtime signs it with HMAC of the session's Graph token hash
  so it can't be tampered — no server state).
- `POST /actions/approve` body `{action}` → executes via the existing modules (create invoice → PDF → send via Graph if `send`), returns
  the result; `POST /actions/reject` just audits. Audit lines in `_System/Audit/actions/<yyyy-mm>.jsonl`.
- Tests: intent parsing with a stubbed model; entity resolution incl. ambiguity; money maths; approve executes once (idempotent by action id); reject.

## Web + mobile
- Ask page: render a proposed action as a card (what will happen, to whom, amount, VAT, "Approve" / "Change" / "Reject"); after approval
  show the result (invoice number, sent to …). Voice path shows the transcript then the card.
- Mobile Ask screen: same card, minimal (Approve/Reject). `flutter analyze` clean; `pnpm run build` passes.
- README row + `docs/ACTIONS.md` (what the model decides vs what code decides).
Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
