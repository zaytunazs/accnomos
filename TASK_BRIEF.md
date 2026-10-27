# Task: Loose ends from the reviews — /vat mock-up, job hours → invoice, relay client IP, lockfile, duplicate review items

Accnomos monorepo (public; UK English; no secrets). Read first `docs/reviews/docs-honesty/REVIEW.md` ("What remains"), `docs/HONESTY.md`,
`apps/web/src/app/vat/*`, `apps/web/src/lib/sample-vat.ts`, `apps/web/src/app/invoices/new/*`, `apps/web/src/lib/runtime.ts`
(`INVOICE_DRAFT_KEY`), `apps/web/src/components/jobs/JobDetail.tsx`, `services/hmrc-relay/relay/fraud_headers.py`, `deploy/nginx.conf`,
`uv.lock`, `pyproject.toml` files.

## Deliverables
1. `/vat` shows the static sample return only when signed out (labelled); signed in it shows the live card and the period picker only.
2. Job hours → invoice in one step: *Invoice these hours* on a job writes the proposed lines to `INVOICE_DRAFT_KEY`, `/invoices/new`
   reads it (prefilled customer and lines, editable), and after the invoice is **sent** the entries are marked invoiced with that
   invoice number automatically (`POST /jobs/{id}/mark-invoiced`), not by typing a number. Tests on the runtime side; web build.
3. Relay: client IP = last `X-Forwarded-For` hop, never `CF-Connecting-IP` (same rule as the edge; `deploy/nginx.conf` strips it
   anyway, but the relay should not trust it on its own). Update `test_fraud_headers.py`.
4. `uv lock` so the lockfile matches every `pyproject.toml` (numpy, fpdf2, pillow); `deploy/Dockerfile.*` still build from it (read
   them). If `uv lock` cannot reach the network here, say so and leave it.
5. `docs/HONESTY.md` and `docs/REMAINING.md`: tick what this branch closes; add nothing else.
Commit in small steps; do not push. Finish with `git log --oneline -8` and five lines a human must verify.
