# Task: Sales invoicing — create, PDF, send via Outlook, track payment, Muse-drafted reminders

Accnomos monorepo (public; UK English; no secrets; stateless runtime; files in the user's OneDrive). Read first: the contacts branch
work if merged (`services/runtime/app/contacts.py`, `/contacts` page) — if not on main yet, read `TASK_BRIEF.md` of that task in
`~/spark/accnomos/jobs/contacts_task.md` and code against the same `contacts.json` shape; `approve.py`, `books.py`, `projection.py`,
`packages/ledger/.../events.py`, `routes_mail.py`/`intake.py` (Graph mail patterns), `apps/web/src/lib/{runtime.ts,graph.ts,msal.ts}`.

## Data
- `03 Sales/invoices/<INV-0001>.json` (header, lines, VAT per line, totals in pence, status: draft|sent|paid|void, sent_at, paid_at,
  payment_ref) and `03 Sales/invoices/<INV-0001>.pdf`. Numbering sequence in `_System/Invoicing/sequence.json`; business profile
  (name, address, VRN, bank details for the footer, logo file path in the folder, default terms) in `_System/Invoicing/profile.json`.
- Posting: when status becomes `sent`, append the sales ledger event (code computes VAT per line and totals; the model never does).

## Runtime (`routes_invoices.py`, `invoicing.py`, `pdf.py`)
- CRUD + `POST /invoices/{id}/pdf` (ReportLab or fpdf2 — add to runtime deps; A4, UK layout: supplier block, customer block, invoice
  number/date/due, lines table, VAT summary by rate, totals, bank details, "VAT reg no", payment terms), `POST /invoices/{id}/send`
  (Graph `POST /me/sendMail` with the PDF attached **only after the user confirmed in the UI**; scope `Mail.Send` requested on demand;
  also save a copy to `03 Sales/invoices/sent/`), `POST /invoices/{id}/mark-paid` (payment_ref; link to a bank line if `routes_bank`
  has a matcher), `GET /invoices?status=`.
- Reminders: `POST /invoices/{id}/reminder-draft` → Muse (user's AI config, same backends as Ask) writes a short polite UK-English chase
  email from facts the code supplies (amount, days overdue, invoice number); returned as a draft for the user to approve, then sent via
  Graph. Never auto-sent.
- Tests: totals/VAT per line (pence), numbering, status transitions, PDF renders (smoke), send gated behind an explicit `confirm: true`.

## Web
- `/invoices` list + `/invoices/new` form (customer picker from contacts, lines with qty/unit/VAT code, live totals by code), preview PDF
  (served as data URL from the runtime response), "Send via Outlook" with a confirmation dialog, "Mark paid", reminder drafting UI.
- Business profile editor under `/connect/business` + Settings (logo upload to the folder). Nav entry. README row. `pnpm run build` passes.

Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
