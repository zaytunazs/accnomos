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

| Medium | `flutter analyze` and `flutter test` pass here but nothing on the phone has been run on a device. |
| Medium | The rate limit and the relay's spent-state set are per process; the relay must run one worker. |
| Low | The shared `.venv` on the Spark can import another checkout's `accnomos_ledger`/`accnomos_connectors`; run `uv sync --all-packages` where you serve from. |

| Low | `ruff` has not been run on `main`. |
| Low | `POST /books/approve/{id}` is an alias kept for older web builds; remove it after the next deploy. |
| Low | The one-time rename of old-named folders (`app/layout.py`) needs a run against a real OneDrive (personal and work), including a folder that is open in the OneDrive client. `POST /reports/export` writes `07 Reports/` from the web and Android, but only fake storage has been written in tests. |
| Low | No web unit tests; pages are covered by `pnpm run build` and the Playwright suite, whose CI job has never run on GitHub. |
## Read → approve → ledger, Undo, VAT return

| Severity | Item |
|---|---|

| Low | Key-mode extraction (muse-spark-1.3) is unit-tested only. |

## HMRC (sandbox) and VAT periods

| Severity | Item |
|---|---|
| Medium | No call from the app to HMRC's sandbox has been made end to end; `/vat` submission and the obligations round trip are built and type-checked only, against a faked relay. Sandbox only, untested against the live sandbox until the owner signs in. Never production. |
| Medium | "Submitted" now follows HMRC's obligations list too (`POST /books/vat/obligations` stores it; fulfilled marks the period submitted), but the list only reaches the runtime when the web app is connected and fetches it; a return filed elsewhere still shows as open until then. |
| Low | The runtime's own period key (`26A4`) is a placeholder, the same for all three months of a monthly quarter; HMRC's key is used when its dates match, and submission uses HMRC's key. |
| Medium | Company and VAT look-ups have only run against fakes: no Companies House key or HMRC sandbox call yet. Production needs the owner's HMRC production application with the Check a UK VAT number v2.0 subscription (`docs/PRODUCTION.md`). |
| Low | The runtime reaches the relay from one IP, so every user's VAT checks share the relay's per-IP limit (60 a minute by default). The `/vat` page copy still says "(sandbox)" and must follow `/health`'s `sandbox` flag before going live. |
| Low | A VAT check on a Review card is kept only when a contact already has that VAT number; for a brand-new supplier it is cached in the runtime process for 24 h and checked again after a restart. |
| Low | `?today=` on `/books/vat` and `/books/vat/periods` moves "current" and `can_submit`; the web gate is advisory. |
| Low | No flat-rate scheme, annual accounting scheme or fuel scale-charge calculation. |

## Bank statements

| Severity | Item |
|---|---|
| Medium | Barclays, Starling, Tide, Monzo and HSBC/Lloyds layouts follow public formats and have not been checked against real exports. Unknown headers fall back to `bank`. |
| Medium | Bank-rule AI codings have run against the test stub only (`testmode.bank_ai_reply`); no real Glimmer/Meta call has coded a line end to end. |
| Low | `suggested_filename` on bank-line expense proposals ends in `.csv` and uses the raw description; nothing reads it. |
| Low | The phone lists bank rules read-only; adding or editing rules needs the web app (on purpose). |

## Contacts

| Severity | Item |
|---|---|
| Low | Applying or refunding a contact's credit, paying bills, *Post as payment* and payment terms are on the web only; Android shows paid and balance but has none of these. A refund is one credit at a time (no refund split across several credits), and applying is one credit to one document per action. |
| Medium | A supplier's credit note is linked to its bill only when the reader fills `original_invoice_number` and exactly one standing bill on account from the same supplier has that number (compared ignoring case, spaces and punctuation, a prefix such as "Inv no." allowed); otherwise it stays a credit on the supplier, to apply or have refunded from Contacts. Review does not show which bill it will credit before you approve, and the link cannot be changed afterwards except by undo and re-approve. The extraction eval has not been re-run with the new field. |
| Low | A bank line matched straight to invoices on the Bank page still posts nothing until you use *Post as payment* on the invoice (then it posts Dr 1200 Bank / Cr 1100 Debtors once). Its amount is allocated in match order, within 1p per document counting as paid in full; money over is credited to the first document's contact. |
| Low | One movement counted once: a statement line is suggested to a recorded payment or refund of exactly the same signed amount, dated 5 days before to 14 days after it; a payment of a different amount, or outside that window, is not suggested (match it by hand to the payment's entry). A match to a document already settled is refused (409) with the way out named. A refund line is offered against a contact's credit only for the exact amount. |
| Low | Customer VAT numbers only via *Edit*. Outlook contacts added with "also add" are always customers. `credit_uses.json`, like `payments.json`, is rewritten whole (last write wins). |
| Low | An invoice marked paid before payments were recorded (no amount kept) counts as paid on Invoices and Home but stays open in Contacts and *Aged balances*, as before; *Remove* on it puts it back to sent. `payments.json` is rewritten whole (last write wins). |
| Low | Two tabs editing the same contact's same field at once: the second save wins on that field (edits to different contacts, or different fields, merge). |
| Low | `Contacts.Read` may need admin consent on work accounts (untested). |

## Files, Books.xlsx, dashboard and deadlines

| Severity | Item |
|---|---|
| Medium | Books.xlsx has never been opened in Excel from a real OneDrive. |
| Low | With annual accounting the Deadlines tiles show "—" (not worked out yet). `GET /books/deadlines` returns `start_month` normalised to 1–3. With no stagger sent it returns `"assumed": true` and the web says so; the Android app sends no stagger, so it always gets `assumed` and does not show the note. |
| Low | On the phone a failed dashboard refresh keeps old figures under an error line; the tiles are not marked stale, and the app does not read the per-tile `{"error"}` marker (its parser treats it as a tile with no figures; not run, no Flutter here). |

## Invoicing, jobs, vehicles, payroll

| Severity | Item |
|---|---|

| Medium | "Invoiced" value and margin use each person's *current* charge rate; changing a rate restates past jobs. |
| Medium | Not verified: sending from a real mailbox, the `Mail.Send` consent redirect, the PDF in a real viewer, logo upload to a real OneDrive. |
| Medium | Payroll is an estimate (annual thresholds ÷ 12, month 1, 1257L, category A, England/NI); the 2026–27 rates were checked against GOV.UK on 27 Oct 2026 and `tests/test_payroll_rates.py` pins them; re-check each April. No RTI. |
| Medium | Credit notes: not verified in a real PDF viewer or sent from a real mailbox. The Android app shows paid and balance but cannot record payments or make credit notes. |
| Low | If the sent copy cannot be saved after the email goes, the sale is not posted until the user retries. |
| Low | `GraphMailSender` refuses a message whose encoded request is over 4 MB (about 3 MB of attachments) with an error; sending larger files (draft plus attachment upload session) is not built. The send tick stays ticked after the message is edited. |
| Low | Plain timesheet edits do not rebuild Books.xlsx. A month-changing edit can leave a duplicate line (never a lost one). A closed job can be tagged through the API (on purpose). |
| Low | Mileage scan pre-fill uses a keyword list. |
| Low | Undoing a payroll ledger entry outside the Payroll page leaves the run "confirmed" until reopened. No salaried staff. |

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
| Medium | The Baseten verifier (`meta-models/muse-spark-open`) is wired and one real call was checked; its eval over 200 receipts is pending; no real Meta (muse-spark-1.3) verifier call has been made. |
| Medium | Mixed-rate receipts give false alarms; the prompt needs a mixed-rate hint. The catch rate is unmeasured (20 documents, Glimmer on Glimmer): run the full 60 and real photos. |
| Medium | The SAM 3.1 wire format is unverified, so `SAM_CROP` stays off. Capture a real response first. |
| Medium | The Muse Voice request (`/asr/transcribe`, multipart parts, response field) comes from research notes. No live mic run in any browser or on the phone. |
| Low | The card cannot adopt the second reading: approve the first or reject. |
| Low | Bench scenes for the crop are synthetic; the crop shows only as a note on the verifier line. Harness gold issues `015_zero` and `016_no_vat_number`. |
| Low | Ask has no period picker of its own; it uses the period picked on `/vat`. |

## Android

| Severity | Item |
|---|---|
| Low | Reports on the phone is a thin client over `GET /reports/*` with no offline copy; a failed load shows a retry, not stale figures. |
| Medium | Sign-in on a Play install (0.3.1+4 onwards, Play signing hash registered in Entra on 27 Oct) has not been tried on a real phone. |
| Medium | The phone saves a VAT stagger in Settings but sends it nowhere, so Home, the dashboard, the VAT picker and the Reports default period use calendar quarters. |
| Low | The Meta API key is not in secure storage (`apps/mobile/lib/services/settings.dart`). Payroll is read-only; Bank only confirms certain matches and lists bank rules; no HMRC filing. |

## Security and deployment

| Severity | Item |
|---|---|
| Medium | Deploy files are checked by config tests only: images not built, `docker compose up` and `nginx -t` not run, nothing tried against the live `api.accnomos.com`. |
| Low | The Graph provider's `_safe_path` raises `ValueError`, so a hand-edited unsafe path gives a 500 with a correlation id, not a 400. `Permissions-Policy` lists the deprecated `interest-cohort`. |
| Low | No caller authentication beyond holding a token; no script CSP; keys and HMRC tokens sit in browser storage. See `docs/SECURITY.md`. |
