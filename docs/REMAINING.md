# What remains

What is still open on `main`, by area and severity, from the "What remains" section of every `docs/reviews/*/REVIEW.md` and a
check of the code on 27 Oct 2026. The same gaps as a flat list: `docs/HONESTY.md`. Anything fixed is not listed.

Severity:
- **High**: gives a wrong figure or loses data in normal use, or blocks the live demo.
- **Medium**: wrong or misleading in a real but narrower case, or unproven against the real service.
- **Low**: polish, docs, or a limit that is already stated in the product.

## Across the product

| Severity | Item |
|---|---|
| High | **Almost nothing has run against a real OneDrive, a real Meta key, HMRC's sandbox or a phone.** Only sign-in, folder setup, read → approve → ledger and the VAT boxes were run by hand (maintainers' word; no log committed). Everything else is tested on fakes. |
| Medium | In key mode with no `X-Meta-Api-Key` header, `AiConfig` falls back to the server's `META_API_KEY`: typed and voice Ask would run on the operator's key. A product decision, not changed. |

| Medium | `flutter analyze` and `flutter test` have never been run on the current `apps/mobile`. |
| Medium | The rate limit and the relay's spent-state set are per process; the relay must run one worker. |
| Low | The shared `.venv` on the Spark can import another checkout's `accnomos_ledger`/`accnomos_connectors`; run `uv sync --all-packages` where you serve from. |

| Low | `ruff` has not been run on `main`. |
| Low | `POST /books/approve/{id}` is an alias kept for older web builds; remove it after the next deploy. |
| Low | The 6 April tax-year rule is written twice (`contacts.uk_tax_year_start`, `mileage.tax_year_of`). Both are tested. |
| Low | `07 Reports/` is created at onboarding but nothing writes to it. The one-time rename of old-named folders (`app/layout.py`) needs a run against a real OneDrive (personal and work), including a folder that is open in the OneDrive client. |
| Low | No web unit tests; pages are covered by `pnpm run build` and the Playwright suite, whose CI job has never run on GitHub. |
## Read → approve → ledger, Undo, VAT return

| Severity | Item |
|---|---|
| Low | `/books/vat` entry counts include sales and purchases only: a reversal changes the amounts but not the count shown next to boxes 1–4 and 6–7. |
| Low | Key-mode extraction (muse-spark-1.3) is unit-tested only. |
| Low | An undo is dated like the original; if that VAT period was submitted, the correction belongs in the current period. |

## HMRC (sandbox) and VAT periods

| Severity | Item |
|---|---|
| Medium | No call from the app to HMRC's sandbox has been made end to end; `/vat` submission is built and type-checked only. Never production. |
| Medium | The runtime makes no HMRC obligations call, so "submitted" means a receipt our own submission saved; a return filed elsewhere shows as open. |
| Low | The runtime's own period key (`26A4`) is a placeholder, the same for all three months of a monthly quarter; submission uses HMRC's key. |
| Low | `?today=` on `/books/vat` and `/books/vat/periods` moves "current" and `can_submit`; the web gate is advisory. |
| Low | No flat-rate scheme, annual accounting scheme or fuel scale-charge calculation. |

## Bank statements

| Severity | Item |
|---|---|
| Medium | Barclays, Starling, Tide, Monzo and HSBC/Lloyds layouts follow public formats and have not been checked against real exports. Unknown headers fall back to `bank`. |
| Medium | A re-export that overlaps an earlier one gets a different sha256; if every line was already imported, the CSV is filed but has no stored lines and does not appear under Statements. |
| Low | `suggested_filename` on bank-line expense proposals ends in `.csv` and uses the raw description; nothing reads it. |
| Low | The web "Confirm all exact matches" penny rule has no automated test. |

## Contacts

| Severity | Item |
|---|---|
| Medium | A matched bank line counts as full payment. Part payments, overpayments and credit notes are not modelled, so a part-paid invoice drops out of *Aged balances*. |
| Low | Ageing counts from the document date and ignores invoice due dates. Customer VAT numbers only via *Edit*. Outlook contacts added with "also add" are always customers. |
| Low | `contacts.json` is rewritten whole: two tabs editing at once means last write wins. After *Edit* the side panel does not reload the statement (figures stay right). |
| Low | `Contacts.Read` may need admin consent on work accounts (untested). |

## Files, Books.xlsx, dashboard and deadlines

| Severity | Item |
|---|---|
| Medium | Books.xlsx has never been opened in Excel from a real OneDrive. |
| Low | With no saved business settings, Home *Deadlines* assumes stagger 1 without saying so. With annual accounting the tiles show "—" (not worked out yet). `GET /books/deadlines` returns `start_month` normalised to 1–3. |
| Low | On Files, a top-level folder's "N files" counts nested folders as well as files. |
| Low | One provider-level read failure fails the whole dashboard request (401/502 for Graph, else 500); only parse errors are isolated per tile. On the phone a failed refresh keeps old figures under an error line; the tiles are not marked stale. |

## Invoicing, jobs, vehicles, payroll

| Severity | Item |
|---|---|

| Medium | "Invoiced" value and margin use each person's *current* charge rate; changing a rate restates past jobs. |
| Medium | Not verified: sending from a real mailbox, the `Mail.Send` consent redirect, the PDF in a real viewer, logo upload to a real OneDrive. |
| Medium | Payroll is an estimate (annual thresholds ÷ 12, month 1, 1257L, category A, England/NI); the 2026–27 rates were checked against GOV.UK on 27 Oct 2026 by the payrun author only (no test pins them). No RTI. |
| Low | No credit notes; *Mark paid* does not post to 1200 Bank; a paid invoice cannot be voided. If the sent copy cannot be saved after the email goes, the sale is not posted until the user retries. |
| Low | `GraphMailSender.MAX_INLINE` (3 MB) checks raw bytes, so an attachment near 3 MB can just exceed Graph's 4 MB request limit once base64-encoded. The send tick stays ticked after the message is edited. |
| Low | Plain timesheet edits do not rebuild Books.xlsx. A month-changing edit can leave a duplicate line (never a lost one). A closed job can be tagged through the API (on purpose). |
| Low | The web mileage log has no edit control (`PATCH /mileage/{id}` exists); vehicles cannot be renamed or deleted from the page; the Review vehicle picker needs an active business vehicle; scan pre-fill uses a keyword list. |
| Low | Undoing a payroll ledger entry outside the Payroll page leaves the run "confirmed" until reopened. No salaried staff. |
| Low | `MarkInvoicedBody.entry_ids` has no item limit beyond the 256 KB body cap. |

## Chat actions, inbox, planner

| Severity | Item |
|---|---|
| Medium | Not run against a real model, mailbox, calendar or OneDrive. |
| Medium | Without `ACTIONS_SIGNING_KEY` (empty by default in `deploy/docker-compose.yml`), a restart or several workers make action cards fail with 403. |
| Medium | First-time calendar consent redirects through Microsoft and loses the plan; plan again and Apply again. |
| Low | An action stuck in `approving` is never re-run on its own (409); after 10 minutes rejecting the card clears it, but the app does not yet explain that in the card. A "send" ends as a draft when `Mail.Send` was never granted. |
| Low | Two Applies at the same moment can both create events (no lock). Planner: Europe/London only, rule-of-thumb travel, only VAT returns count as due, no per-job picker, the rationale model sees event subjects and, with no `X-AI-*` headers, runs on the server's default model. |
| Low | A bad `X-AI-*` setting makes triage run without a model, saying only "No AI is set up". A failed second Graph call leaves an empty draft in Drafts. Sent Items are not read, so an answered thread can still show *Reply*. |

## Verifier, crop, Ask and voice

| Severity | Item |
|---|---|
| Medium | The Baseten slug `meta-models/muse-spark-open` is unconfirmed; the verifier needs a Baseten key on the server (the demo has none); no real Baseten or Meta verifier call has been made. |
| Medium | Mixed-rate receipts give false alarms; the prompt needs a mixed-rate hint. The catch rate is unmeasured (20 documents, Glimmer on Glimmer): run the full 60 and real photos. |
| Medium | The SAM 3.1 wire format is unverified, so `SAM_CROP` stays off. Capture a real response first. |
| Medium | The Muse Voice request (`/asr/transcribe`, multipart parts, response field) comes from research notes. No live mic run in any browser or on the phone. |
| Low | The card cannot adopt the second reading: approve the first or reject. |
| Low | Bench scenes for the crop are synthetic; the crop shows only as a note on the verifier line. Harness gold issues `015_zero` and `016_no_vat_number`. |
| Low | Ask has no period picker of its own; it uses the period picked on `/vat`. |

## Android

| Severity | Item |
|---|---|
| Medium | Play signing hash → Entra is pending (maintainers' status): a release or Play build may not be able to sign in. The app defaults to the debug key's hash (`broker_redirect_uri_registered: false`). |
| Medium | The phone saves a VAT stagger in Settings but sends it nowhere, so Home, the dashboard and the VAT picker use calendar quarters. |
| Low | The Meta API key is not in secure storage (`apps/mobile/lib/services/settings.dart`). Payroll is read-only; Bank only confirms certain matches; no HMRC filing. |

## Security and deployment

| Severity | Item |
|---|---|
| Medium | Deploy files are checked by config tests only: images not built, `docker compose up` and `nginx -t` not run, nothing tried against the live `api.accnomos.com`. |
| Low | The Graph provider's `_safe_path` raises `ValueError`, so a hand-edited unsafe path gives a 500 with a correlation id, not a 400. `Permissions-Policy` lists the deprecated `interest-cohort`. |
| Low | No caller authentication beyond holding a token; no script CSP; keys and HMRC tokens sit in browser storage. See `docs/SECURITY.md`. |
