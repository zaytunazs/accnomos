# Task: Second security pass over everything added since the first (invoices, actions, planner, triage, to-dos, payroll, folder migration, test mode)

Accnomos monorepo (public; UK English; no secrets). Read first `docs/SECURITY.md`, `docs/reviews/security/REVIEW.md`, then every router
registered in `services/runtime/app/main.py` that the first pass did not cover: `routes_invoices.py`, `routes_actions.py`, `routes_plan.py`,
`routes_mail.py` (triage, draft-reply, todos), `routes_payroll.py`, `routes_jobs.py`, `routes_vehicles.py`, `routes_contacts.py`,
`routes_dashboard.py`, `paths.py` migration, `testmode.py` (must be inert unless `ACCNOMOS_TEST_MODE=1`), the relay changes, and the
connectors' Graph calls (`msgraph.py`: mail send, calendar create, folder rename).

## Deliverables (each finding fixed with a test, or recorded in `docs/SECURITY.md` as accepted with the reason)
1. **Authorisation and identity**: every route that writes needs `X-User` via `require_user`; the Graph token is the only authority;
   no route trusts a client-supplied id to reach another tenant's files (test mode tenants included). Audit lines carry `user:`/`agent:`.
2. **Input bounds**: every `StrictBody`; lengths on free text (invoice lines, notes, to-dos, reply bodies); money as int pence only;
   dates parsed strictly; file names through the safe-name helper; the logo upload is image-only (sniffed) and ≤ 1 MB; PDF text is
   escaped for fpdf (no font-injection surprises).
3. **Outbound**: the only hosts the runtime calls are Graph, the AI base URLs on the allow-list, Baseten and the relay; no URL from a
   document, email or to-do is ever fetched (SSRF); mail bodies never include raw user HTML; draft replies are text.
4. **Signed actions**: replay and tamper tests on `POST /actions/approve`; an approved action cannot run twice; the `approving` lock
   expires or can be cleared by a documented path.
5. **Test mode**: with the flag unset, every `/__test/*` route and header is absent; the Dockerfile pins it to 0; the e2e export never
   deploys (workflow check already exists — read it).
6. Rate limits and body caps on the new upload routes; the edge `nginx.conf` location list covers them.
`pytest`, relay tests, `pnpm run build` green. Commit in small steps; do not push. Finish with `git log --oneline -8` and the findings table
(severity, where, fixed/accepted).
