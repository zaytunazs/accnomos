# Review: second security pass

What was added after the first pass (`docs/reviews/security/REVIEW.md`): invoices, chat and voice actions, the day
planner, inbox triage and draft replies, to-dos, payroll, the folder migration, test mode, the relay's client-address
change and the Graph calls that send mail, create events and rename folders.

## How it was checked

- Every router registered in `services/runtime/app/main.py` was read, with `app/actions.py`, `invoicing.py`,
  `pdf.py`, `plan_apply.py`, `layout.py`, `paths.py`, `testmode.py`, `msgraph.py` and the relay diff since `09eab66`.
- The rules that apply to every route are now tests that walk the registered routes or parse `app/` (AST), so a new
  router cannot skip them: `services/runtime/tests/test_security_routes.py`.
- Tests: runtime 740 passed (677 before), connectors 43 (37), relay 102 (unchanged), `pnpm run build` passes.

## Findings

| Severity | Where | Finding | Outcome |
|---|---|---|---|
| High | `books.py` `_update`, `actions.py` | A new file was written with no precondition, so when the month's actions log did not exist yet two approvals at the same moment both claimed the action and both ran it (an invoice could be emailed twice) | Fixed: create-only writes (`create_only`, Graph `conflictBehavior=fail`). `test_two_approvals_at_once_execute_once` fails without the fix |
| Medium | `msgraph.py` `_request` | The Graph token was attached to any `nextLink`, `deltaLink` or cursor URL | Fixed: refused outside `https://graph.microsoft.com/`. `test_the_token_never_follows_a_link_off_graph` |
| Medium | `routes_invoices.py` logo | The declared `Content-Type` was trusted, so any bytes became `logo.png` and reached Pillow in the PDF renderer; no pixel limit | Fixed: magic bytes, decode, 4000 px. `test_logo_is_sniffed_decoded_and_size_checked` |
| Medium | `invoicing.py` `logo_path` | The profile could point the logo at any file under `_System/Invoicing/`, and a hand-edited profile at any file at all | Fixed: only the two upload targets are accepted or read. `test_a_hand_edited_logo_path_is_not_read` |
| Medium | 20 body models (actions, invoices, plan, payroll, mileage) | Unknown fields silently accepted; several free-text fields without a length cap | Fixed: `StrictBody` everywhere, caps added. `test_every_request_body_forbids_unknown_fields`, `test_every_free_text_field_in_a_body_has_a_length_cap` |
| Low | invoice, payroll, plan, mileage, timesheet bodies | Dates accepted Unix timestamps and datetimes; pence accepted `12.0`, `"12"`, `true` | Fixed: `Day`, `Pence`. `test_dates_and_money_are_parsed_strictly` |
| Low | `actions.py` | No way out of a stuck `approving` line | Fixed: never re-run; after 10 minutes rejecting the card clears it (`docs/ACTIONS.md`). `test_a_stale_approving_lock_is_never_rerun_and_rejecting_clears_it` |
| Low | `actions.py` (test mode) | A card signed in one `X-Test-Tenant` verified in another | Fixed: the tenant is part of the key in test mode. `test_in_test_mode_a_card_is_bound_to_its_tenant` |
| Low | `invoicing.py`, `payroll.py` | A failed Books.xlsx rebuild was audited under the bare e-mail address, not `user:` | Fixed. `test_every_audit_actor_is_user_or_agent` |
| Low | `actions.py` `run_mileage` | Approving a mileage action always failed (empty purpose; `add_entry` called without the user, so no `user:` audit) | Fixed. `test_approved_mileage_is_logged_and_audited_as_the_user` |
| Low | `security.py`, `deploy/nginx.conf` | A 1 MB logo could not arrive (256 KB cap) and the edge had no location for it | Fixed: 2 MB on that path in both. `test_edge_nginx_lets_every_upload_route_through_at_the_runtimes_cap` |
| Low | `pdf.py` | fpdf2 replaced `{nb}` anywhere in the document, so typed-in text could change | Fixed: private alias, control characters stripped. `test_pdf_text_cannot_use_fpdfs_page_count_alias` |
| Low | `main.py` CORS | `PATCH` (vehicle and mileage edits from the web app) was refused in the browser | Fixed. `test_cors_allows_every_method_a_route_uses_and_no_other` |
| Low | `routes_jobs.py` | `MarkInvoicedBody.entry_ids` had no item limit (left open by the first pass) | Fixed: 1000 ids of up to 32 characters |
| Info | test mode | Inert without `ACCNOMOS_TEST_MODE=1` | Confirmed and now tested in a fresh interpreter; workflows checked |
| Info | relay | Client address from the last `X-Forwarded-For` hop; `CF-Connecting-IP` no longer read (closes the first pass's open item) | Confirmed |
| Accepted | see `docs/SECURITY.md` | Test-mode tenants by header; Graph's download redirect; one shared rate limit; to-do links; prompt injection in triage and reminders; free-form `preview`; per-process signing key; `/pdf` without `X-User`; `/health` counts | Recorded with reasons in *Accepted after the second pass* |

## Not done

- Nothing was run against `api.accnomos.com`, the images were not built and `nginx -t` was not run (config tests only).
- The action card in the web app does not yet explain the stale-lock path; the API and `docs/ACTIONS.md` do.
