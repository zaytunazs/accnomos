# Task: Customers & suppliers — contact book from the ledger, statements, aged balances

Accnomos monorepo (public; UK English; no secrets; stateless runtime; data lives in the user's OneDrive folder).
Read first: `README.md`, `docs/ARCHITECTURE.md` (if present), `services/runtime/app/{routes_books.py,books.py,approve.py,projection.py}`,
`packages/ledger/src/accnomos_ledger/events.py`, `packages/connectors/src/accnomos_connectors/{base.py,msgraph.py,fake.py}`,
`apps/web/src/lib/{runtime.ts,graph.ts}`, `apps/web/src/components/files/*` (for the list style).

## Data (in the user's folder)
- `_System/Contacts/contacts.json`: `[{ id, kind: "customer"|"supplier"|"both", name, normalised_key, vrn|null, email|null, phone|null,
  address|null, default_category|null, default_vat_code|null, source: "ledger"|"outlook"|"manual", created_at, updated_at }]`.
- Derived in code on request (never stored): per-contact statement (events, running balance), totals, aged balances (0–30/31–60/61–90/90+)
  from unpaid sales/purchase documents (use the bank-matching status if present; otherwise "unmatched = unpaid").

## Runtime
- `app/contacts.py`: build/refresh contacts from ledger events (dedupe by normalised name + VRN), merge manual edits, optional Outlook
  contacts import via Graph `GET /me/contacts?$select=displayName,emailAddresses,businessPhones,companyName` (scope `Contacts.Read`,
  requested only when the user clicks Import; add `contactsScopesFor` next to `mailScopesFor`).
- Routes (`routes_contacts.py`): `GET /contacts` (with totals), `POST /contacts/refresh`, `PUT /contacts/{id}`, `POST /contacts/import-outlook`,
  `GET /contacts/{id}/statement?from&to`, `GET /contacts/aged` (debtors + creditors tables).
- Books.xlsx projection: add `Customers` and `Suppliers` sheets (name, VRN, YTD net, YTD VAT, open balance).
- Tests with fake providers: dedupe, merge of manual edits, statement balances, aged buckets, import mapping.

## Web
- New page `/contacts`: table (name, kind, open balance, YTD) with search, a side panel with the statement and "Edit", buttons "Refresh from
  books" and "Import from Outlook"; an "Aged balances" tab. Nav entry. Keep the look; `pnpm run build` passes. README row.

Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
