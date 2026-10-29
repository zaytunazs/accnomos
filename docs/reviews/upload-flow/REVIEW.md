# Review: upload → progress → confirm the type → Review (branch `claude/upload-flow`)

Owner report (live demo, accnomos.com, `DEMO_MODE=1`, AI chain Meta then local): after "Add a receipt" with two real
PDFs (a Currys receipt, a self-storage invoice) the page said "2 files added to 00 Inbox. Press Scan 00 Inbox now",
then "Reading your Inbox…" for 10+ minutes; the server logged the CORS preflight `OPTIONS /books/scan?stagger=1`
but never the POST.

## Root cause

Checked against the code on `origin/main` (29 Oct 2026), not against the live server's logs:

1. **One blocking request for the whole Inbox.** `POST /books/scan` answered only after every document was read. The
   web app (`LiveReview.scan`) and the phone (`RuntimeClient.scan`, 20 s timeout) waited on it.
2. **The demo's 00 Inbox is not empty.** The sandbox seed leaves 19 unread sample documents there
   (`app/demo.py build_full`: only 4 + 2 are pre-read). "Scan 00 Inbox now" read up to `limit=10` files, in listing
   order, so the two uploads were not even necessarily among them. Verified by building today's snapshot locally.
3. **No time budget per document or per request.** Each document can take three AI calls (read; a re-read when unsure;
   the second opinion), and in the chain each attempt may take up to `META_REQUEST_S` 120 s and then fall over to the
   next provider for up to 200 s (`app/ai/providers.py`). Ten documents × up to three calls × up to 320 s has no useful
   upper bound.
4. **The edge gives up first, the runtime does not.** `deploy/nginx.conf` allows 300 s; the browser's request is cut
   off long before the scan ends, but an ASGI handler is not cancelled when the client goes away, so the runtime kept
   reading and the access log line (written at the end) never appeared. That is the "POST never completes/logs".

Ruled out: the stagger loop (`?stagger=1` is only the VAT period for the date check), multi-page PDF handling (text of
up to 20 pages plus one render of page 1, in a worker thread; not timed on the owner's two PDFs, which I do not have), and demo storage
(in-memory, fast). AI call timeouts did exist per attempt; what was missing was a bound on the sum.

## What was built

Runtime
- `app/scan_jobs.py`, `app/routes_scan.py`: `POST /books/scan/jobs` answers at once (202); the reading runs in the
  background, and `GET /books/scan/jobs/{id}` reports each file's stage (uploaded → reading → confirm → checking →
  ready / needs a look / not read), its progress, the AI's guess of the type with its confidence, where it went and a
  plain message. `POST /books/scan/jobs/{id}/confirm` (X-User) takes the user's types; only then is a file read in full
  and routed (receipts, bills, credit notes → Review; sales invoices → Review as a sale; bank CSV → bank-lines import;
  PDF statements, payslips, anything else → Needs a look saying why; a type across sides → Needs a look, `DOC_KIND`).
  Approving stays in Review. Job state is written to `_System/Scans/<id>.json` in the user's books after every step.
- `app/ai/classify.py`: the "what kind of document is this?" call (text first, image when there is no text), strict
  schema; code's guess from the words when the model does not answer (`by: "code"`, said on the row).
- `app/ai/chain.py` `limits()`: a per-call cap and a document deadline over every AI attempt, whoever serves it; a
  spent deadline (`OutOfTime`) neither fails over nor counts against the provider's circuit breaker.
- `app/inbox.py`: `bounded()` (`SCAN_DOC_TIMEOUT_S` 180, `AI_CALL_TIMEOUT_S` 90) on every document, for jobs and for
  the old `POST /books/scan` too, which also skips files a job is reading. The per-file body was split into
  `scan_context` / `read_one` / `commit` / `finish`, shared by both paths. Progress is logged per file and step
  (`accnomos.scan`), never with a file name or an amount.
- `POST /mail/scan` `read_now: true` starts the same job for the files Outlook intake saved (`scan_job_id`).
- Test-mode stub AI answers the classifier (a gold document's own type, else code's guess).

Web
- `UploadToInbox`: photos, PDFs and bank CSVs; after the upload it starts a job for exactly those files. No Scan press.
- `components/review/ScanProgress.tsx`: a bar per file and for the job, the guess ("Looks like a receipt (90% sure)"),
  a type picker, Confirm / Confirm all, where each file went. `lib/scan-jobs.ts`: one poller per tab (1.5 s while
  reading, 10 s while waiting for the user, none when done), job ids in localStorage so it carries on across pages.
- `components/ScanBadge.tsx` in the top bar: "Reading N" / "N to confirm", linking to Review (one line in `TopBar.tsx`).
- Review changes kept small for claude/app-shell: `scan()` starts a job; `<ScanProgress>` under the notes; the cards
  reload (and "N new proposals" is announced) when files reach Review.
- Outlook intake (Settings) sends `read_now` and follows the jobs.

Android
- `RuntimeClient.startScanJob / scanJob / confirmScanJob`, `models/scan_job.dart`, `widgets/scan_progress.dart`
  (`ScanJobCard`); the capture screen starts a job for the photos it uploaded and Review's "Scan inbox" one for the
  Inbox. The old 20 s blocking scan is no longer on either path.

## Tests

- Runtime `tests/test_scan_jobs.py`, 23 tests with a slow fake model: the start call answering in under 0.4 s while
  the model takes 0.5 s; stages and per-file progress seen in order; the job file in the books; nothing read in full,
  filed or proposed before Confirm, Confirm needing X-User and refusing a second time (409); routing of a sales
  invoice, a bank CSV (lines imported, CSV moved out of the Inbox, never sent to the model), a payslip and "other";
  a type across sides → Needs a look; the classifier timing out → code's guess with the message; a document timing out
  → stays in the Inbox with the plain message; the plain `/books/scan` bounded the same way and leaving a job's files
  alone; the work continuing with nobody polling and the job found again under a refreshed token; an interrupted job;
  bad names; per-call caps and the spent-deadline rule in the chain; the classifier's parsing; code's guess (7 cases);
  Outlook intake's `read_now`. Updated: `test_security_routes.py` (allow-lists), audit summary for
  `scan_type_confirmed`.
- Runtime suite: see the gate results below.
- Playwright, test mode: `e2e/upload-flow.spec.ts` (4: receipt + bank CSV with one start call, guesses, top-bar count,
  Confirm all, routing; changing a guess to payslip; leaving the page and coming back via the top bar; Outlook intake);
  `e2e/sandbox.spec.ts` + 1 in the `DEMO_MODE=1` sandbox (only the upload is read although the sandbox Inbox holds 19
  documents; progress values; nothing in Review before Confirm; the card after). Every spec that used "Scan 00 Inbox
  now" after an upload now confirms the type (`confirmScan` in `e2e/fixtures.ts`): review, review-vat, models,
  vehicles, lookups, home, keyboard (keyboard-only Confirm), demo.
- Flutter: `apps/mobile/test/scan_jobs_test.dart` (4: wire shapes of start and confirm with the stagger query and
  X-User, the model's headline and guess parsing, a widget test that polls, shows the guess, changes the type and
  confirms, then stops polling). **Not run: no Flutter SDK in this session.**

## Risks

- The time limits are judgement, not measured on the live Meta chain; set `SCAN_DOC_TIMEOUT_S`, `AI_CALL_TIMEOUT_S`
  and `CLASSIFY_TIMEOUT_S` from real latencies.
- The classifier has no eval set; the user always confirms, so a wrong guess costs a click, not a wrong posting.
- One extra model call per document (the type). For a PDF with text it is text-only and short.
- In-process jobs assume one runtime worker (the Docker image runs one). A restart interrupts running jobs; their
  files stay in 00 Inbox and the job says so.
- A Graph token that expires during a long confirm phase fails the remaining files with "sign in again and retry";
  each phase opens the books with the token of the request that started it.
- Merge with claude/app-shell: both touch Review; this branch only replaced `scan()`'s body, the button's busy label
  ("Starting…"), and added one `<ScanProgress>` line and one `useEffect` in `LiveReview.tsx`, plus one line in
  `TopBar.tsx`.
