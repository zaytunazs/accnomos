# What remains

Collected from the "What remains" sections of `docs/reviews/*/REVIEW.md` and the integration review of `main`
on 27 Oct 2026. Items fixed during that review are listed at the end, so the review files can be read against it.

Severity:
- **High**: gives a wrong figure or loses data in normal use, or blocks the live demo.
- **Medium**: wrong or misleading in a real but narrower case, or unproven against the real service.
- **Low**: polish, docs, or a limit that is already stated in the product.

## Across the product

| Severity | Item |
|---|---|
| High | **Almost nothing has run against a real OneDrive.** Only sign-in, folder setup, read → approve → ledger and the VAT boxes have been run live (see the README table). Every other feature is tested on fakes only. |
| Medium | `uv.lock` is stale: the `accnomos-runtime` entry lacks `numpy` (added for crop). Docker installs with `pip` and is fine; `uv sync --frozen` would leave numpy out and the runtime would fail to import `app.ai.crop`. Run `uv lock` (uv was not available on the review machine). |
| Medium | The shared `.venv` on the Spark has editable installs from whichever lane last ran `uv sync`. Each package now has a `conftest.py`, so `pytest` uses its own checkout. `uvicorn` started from that venv still imports another lane's `accnomos_ledger`/`accnomos_connectors`, so run `uv sync --all-packages` in the checkout you serve from. |
| Medium | In key mode with no `X-Meta-Api-Key` header, `AiConfig` falls back to the server's `META_API_KEY`, so typed and voice Ask would run on the operator's key, not the user's. |
| Medium | The Autopilot on/off switch lives in the browser's `localStorage`. The Android app never sends `X-Autopilot`, so scans from the phone always run Autopilot, even if the user switched it off on the web. |
| Medium | `flutter analyze` has not been run on the current `apps/mobile` (Flutter is not installed on the review machine). That includes every call added to `runtime_client.dart` in that review. |
| Low | The web sidebar always says "AI: local Meta agent (Glimmer 30B)", whatever AI is set in Settings. |
| Low | `ruff` has not been run on `main` (not installed on the review machine). |
| Low | `POST /books/approve/{id}` is kept as an alias of `POST /books/proposals/{id}/approve` for web builds deployed before this review. Remove it after the next deploy. |
| Low | The 6 April tax-year rule is written twice: `contacts.uk_tax_year_start` and `mileage.tax_year_of`. Both are tested. |
| Low | `06 Reports/` is created at onboarding, but nothing writes to it yet. |
| Low | There are no web unit tests. The pages are checked only by `pnpm run build`. |

## Read → approve → ledger, Undo, VAT return

| Severity | Item |
|---|---|
| Low | `/books/vat` box entry counts include sales and purchases only. A reversal changes the amounts but not the count shown next to boxes 1–4 and 6–7. |
| Low | Key-mode extraction (muse-spark-1.3) is unit-tested only. |

## HMRC (sandbox)

| Severity | Item |
|---|---|
| Medium | No sandbox call has been made yet; credentials are pending. Submission from `/vat` is built and type-checked but has not been clicked through end to end. |

## Bank statements

| Severity | Item |
|---|---|
| Medium | The Barclays, Starling, Tide, Monzo and HSBC/Lloyds layouts follow the public formats but have not been checked against real exports. Unknown headers fall back to `bank`. |
| Medium | A re-export that overlaps an earlier one gets a different sha256. When every line in it was already imported, the CSV is still filed but has no stored lines, so it does not appear under Statements. |
| Low | `suggested_filename` on bank-line expense proposals ends in `.csv` and uses the raw description. Nothing reads it today (these proposals have no file). |

## Contacts

| Severity | Item |
|---|---|
| Medium | A matched bank line counts as full payment, whatever its amount. Part payments, overpayments and credit notes are not modelled, so a part-paid invoice drops out of *Aged balances* completely. |
| Low | Ageing uses the document date; no due dates or payment terms are recorded. |
| Low | Customer VAT numbers can only be set with *Edit*; they are never taken from documents. |
| Low | Outlook contacts added with "also add" are always created as customers. |
| Low | `contacts.json` is rewritten whole, so two tabs editing at once means the last write wins. |
| Low | After *Edit*, the side panel reloads the list but not the statement. Only details change, so the figures stay right. |
| Low | On work or school accounts, `Contacts.Read` may need admin consent. This is untested. |

## Files, Books.xlsx and deadlines

| Severity | Item |
|---|---|
| Medium | Books.xlsx has not been opened in Excel from a real OneDrive. |
| Low | Signed in with no saved business settings, Home *Deadlines* assumes stagger 1 without saying so. Annual accounting shows the sample tiles. |
| Low | On Files, a top-level folder's "N files" adds its sub-folders' `childCount`, which counts nested folders as well as files. |
| Low | `GET /books/deadlines` returns `start_month` normalised to 1–3, not the custom month that was sent. |

## Jobs, staff and timesheets

| Severity | Item |
|---|---|
| Medium | There is no sales invoicing. *Create invoice from unbilled hours* only shows the lines, and the user marks hours invoiced by typing an invoice number. The hooks are marked TODO in `routes_jobs.py` and `JobDetail.tsx`. |
| Medium | "Invoiced" value and margin use each person's *current* charge rate. Changing a rate restates past jobs. (This is stated in the README.) |
| Low | Mark-invoiced checks entry ids but not that hours still match the lines the user saw. |
| Low | Plain timesheet edits do not rebuild Books.xlsx. Mark-invoiced, approve and *Rebuild* do. |
| Low | When a timesheet entry's date moves to another month, it is written to the new file before it is removed from the old one. A failure in between leaves a duplicate line, never a lost one. |
| Low | A purchase can be tagged to a closed job through the API (the web picker offers only open jobs). This is on purpose, for late receipts. |

## Vehicles and mileage

| Severity | Item |
|---|---|
| Low | The web log can add and delete journeys but has no edit control (`PATCH /mileage/{id}` and the client call exist). Vehicles can be added and made inactive, but not renamed or deleted, from the page. |
| Low | The Review vehicle picker shows only when there is an active business vehicle, and never on the signed-out sample. |
| Low | Pre-filling a vehicle at scan relies on the category plus a keyword list. Repairs are caught only through "Motor expenses" or MOT/tyre wording. |

## Verifier

| Severity | Item |
|---|---|
| Medium | The Baseten model slug `meta-models/muse-spark-open` is unconfirmed. No real Baseten or Meta API verifier call has been made. |
| Medium | Mixed-rate receipts give false alarms (the verifier reads the standard-rated subtotal as net); the prompt needs a mixed-rate hint. The catch rate has not been measured: run the full 60 and real photos. |
| Low | The card cannot adopt the second reading. On disagreement the user can only approve the first reading or reject. |
| Low | Harness gold issues: `015_zero` (VAT number not printed) and `016_no_vat_number` (£0 VAT expected to need a look). |

## Document crop

| Severity | Item |
|---|---|
| Medium | The SAM 3.1 wire format is unverified, so `SAM_CROP` stays off. Capture a real response before turning it on. |
| Low | The bench scenes are synthetic; expect lower IoU on real phone photos. The flood fill is not tuned for batches. |
| Low | There is no crop chip in the UI, only a note on the verifier line. |

## Ask (typed and voice)

| Severity | Item |
|---|---|
| Medium | The Muse Voice request (`/asr/transcribe`, multipart parts, response field) comes from research notes and has not been checked against dev.meta.ai. |
| Medium | There has been no live mic run in Chrome/Edge, Firefox or Safari/iOS. |
| Low | The UI has no period picker; Ask always uses the current quarter. |

## Android

| Severity | Item |
|---|---|
| Low | Home tiles are sample data. Bank, Jobs, Contacts, Vehicles and Files are web only (the placeholder Files tab was removed). |

## Fixed in the integration review (27 Oct 2026)

- An undone **sale** was subtracted from purchases on the VAT return and in the Ask facts pack. Undo exists now, so this was live; files-books flagged it as latent before undo shipped.
- Tests in every Python package could import another checkout's code from the shared venv; each now pins its own sources.
- Bank "Confirm all exact matches" no longer confirms matches that are a penny out (bank-ui).
- `POST /mileage` no longer accepts `source: "proposal"` from a client (vehicles-mileage).
- Error text on the web shows the runtime's sentence, not `runtime POST … -> 409: {"detail": …}` (voice-ask).
- The Autopilot audit log now uses the same line format as the main audit log, and every actor is `user:` or `agent:`.
- `X-Business-Name` and `X-User` are each read in one place.
- A failed Books.xlsx rebuild after an Autopilot approval was audited as `user:autopilot`; it is now `agent:autopilot` (branch review).
- Navigation: the Android placeholder Files tab and the web's hard-coded Review badge ("3") were removed.
- `runtime.ts` and `runtime_client.dart` cover every route.
- `docs/ARCHITECTURE.md` lists every path written under the user's folder; an integration test holds the runtime to it.
