# Review: `claude/sample-books` (Load sample books)

Brief: anyone signed in on accnomos.com with an **empty** Accnomos folder presses **Load sample books** and gets exactly
the judge books `tools/seed_demo.py` builds (fictional Bramblewood Joinery Ltd, six months, every feature, every document
labelled *SAMPLE — FICTIONAL COMPANY*), with no token copying. Never wipes anything; survives reloads, other tabs, an
expired Graph token and a runtime restart.

## What was built

| Part | What | Where |
|---|---|---|
| One code path | `seed()` is now `for step in seed_steps(plan): await step.run(books, resuming=False)`. 54 steps (folders, staff/jobs, vehicle, VAT status, mail intake, one step per document (38), contacts, invoices, credit note, mileage claim, statements, payments, reconciliation, pay run and to-dos, Inbox, Books.xlsx, reports). Steps not yet started run exactly as before, so the CLI writes what it wrote | `tools/seed_demo.py` |
| Resumable steps | `resuming=True` is passed only to the step a run stopped in. It then looks before it writes: proposals by their fixed ids, `_System/docs` records, a filed copy with the same bytes, intake's record (or the Inbox copy), invoice/credit-note numbers (a number taken but not saved is given back), the sent PDF, a filed statement whose lines were not stored, payment records (an entry posted without its record gets its record; a record without its line match or invoice status gets those), rule codings by their line hash (finished before the matcher runs), timesheets by id, journeys by content, the report file. An approval cut between posting and saving is finished (`_finish_approval`), including the Always-do-this rule | `tools/seed_demo.py` |
| Runtime | `POST /books/sample` (and `/books/sample/continue`, the same handler), `GET /books/sample`. 409 + plain sentence unless the folder has no ledger entries, proposals or contacts (the check lists folders only, so Home's visit stays cheap). Background `asyncio` task per folder (key: hash of account kind + drive item id), its own `GraphStorageProvider`; progress after every step in `_System/sample_seed.json` `{state, step, done, total, steps, started_at, updated_at, finished_at, error, business, today, stagger}` (GET hides `today`/`stagger`, and adds `empty` for state `none`). A second POST while running hands the run its fresh token (`set_token`) and returns the status. A refused token (401/403, or an error some app code reported in its own way after which `ensure_root` is refused) → `needs_token`, the run waits up to 10 min for the next POST, then redoes the step it was on. A run that went quiet (no progress for 3 min, or the process restarted) is resumed by the next POST from the recorded step, same plan day and stagger. `failed` records "OneDrive refused a request (HTTP n) at “step”…" or "Loading stopped at “step”…", never Graph text; press again carries on. Resuming refuses books with entries the seed did not make (409). Per-folder rate limit (`SAMPLE_RATE_PER_MIN`, 10). Audit `sample_books_started` and `sample_books_loaded` (business, events, steps). 503 if the seed is not installed | `services/runtime/app/sample_books.py`, `app/main.py` |
| Connectors | `GraphStorageProvider.set_token()` | `packages/connectors/.../msgraph.py` |
| Image | `deploy/Dockerfile.runtime` copies `tools/seed_demo.py`, `evals/gold`, `evals/harness/render.py`, installs `fonts-dejavu-core` | `deploy/` |
| Web | `SampleBooks` card on Home (signed in, dashboard loaded) and on Connect's last step: "Try it with sample books" + the brief's sentence + **Load sample books** → progress bar (`role=progressbar`, value text "n of N steps done: step"), current step in an `aria-live` line, an *All steps* list (`aria-current="step"`), focus moved to the card heading. Polls every 3 s; POSTs `/continue` every 4 min and on `needs_token`. Done → Home reloads (Connect opens Home) and shows a **SAMPLE — FICTIONAL COMPANY** banner. Never shown when GET says the folder is not empty. Failed → the sentence and *Carry on loading sample books*; 409 → the runtime's sentence | `apps/web/src/components/home/SampleBooks.tsx`, `src/lib/runtime.ts` (`sampleStatus`, `postSample`), `src/app/page.tsx`, `components/onboarding/ReadyPanel.tsx` |
| Test mode | Nothing new needed: the test runtime's fake storage is used by the run directly (same object as the requests); the full plan runs in ~4 s, with a yield between steps so the server keeps answering | — |
| Docs | README row; `docs/DEMO.md` (judges can use their own Microsoft account and press Load sample books); `docs/HONESTY.md` new section; `docs/submission/CHECKLIST.md` (prepare the judge account with the button); `tools/seed_demo.md` §0 and the corrected call count | |

## What I verified

From the worktree root: `source .v/bin/activate`;
`export PYTHONPATH=$PWD/packages/ledger/src:$PWD/packages/connectors/src:$PWD/services/runtime:$PWD/tools`.

- `python -m pytest services/runtime packages evals -q` → **1525 passed, 1 skipped** (main before this branch: 1444
  passed, 1 skipped per `docs/reviews/seed-demo-2/REVIEW.md`; 10 min 15 s here, on 2 CPUs shared with the sweep below).
- `python -m pytest services/runtime/tests/test_sample_books.py -q` → **26 passed** (~95 s): loads into an empty folder and
  the books equal the CLI's (59 events, approvers, kinds, amounts, proposal states, 25 Inbox files, invoice states, bank
  line states, 6 Autopilot rules, every non-`_System` file name, one report); status shape (GET keys, file keeps
  `today`/`stagger`); audit `sample_books_loaded` once with actor `user:judge@example.com` and `{business, events: 59,
  steps}`; a second press while running is the same run and hands over its token; a press after done writes nothing;
  409 for a folder with an event, a proposal, or contacts, and for CLI-seeded books (nothing written); token refused after
  40 and 2,600 storage calls → `needs_token` → `/continue` → done, same books; run gone + stale file after 300 and 1,700
  calls → GET `needs_token` → POST resumes from the recorded step, same books, one `sample_books_started`; a quiet run
  elsewhere is left alone; a Graph 500 whose text holds `eyJ…` and `/Users/…` is recorded as "OneDrive refused a request
  (HTTP 500) at “…”" with neither string in the status or the file, and pressing again finishes; resuming refuses books
  with someone else's entry; per-folder rate limit (3rd POST → 429 with Retry-After, another folder unaffected); 401
  without a token, 400 without X-User; ten named windows (the token refused inside one two-write action, see HONESTY)
  each come out as the CLI's books; the Dockerfile COPY lines. The two windows added last were checked to fail on the
  code before their fix.
- `python -m pytest services/runtime/tests/test_seed_demo.py -q` → **35 passed, 1 skipped**: the CLI is unchanged
  (including "a second run changes nothing" byte for byte and the part-seeded/foreign refusals).
- **Resume sweep (scratch harness, not committed):** an uncut run makes 11,341 storage calls and 710 writes/moves. For
  every write *w* the run was cut with the token refused at *w* and at *w*+1, resumed with `resuming=True` for the
  step it stopped in, and its books compared with the CLI's: 1,420 runs. First passes found 11 failures (sent PDF ×3,
  statement lines, exact payment's invoice copy ×2, rule coding ×4, intake ×1); after the fixes, offsets 0, 2, 5, 7
  of every ten writes (568 runs) re-ran on the final code with 0 failures, offsets 1, 3, 4, 6, 8, 9 (852 runs) ran before
  the last fix with 0 failures, and every cut inside the two steps that last fix touched (264 runs) re-ran with 0.
- `ruff check` → all passed; `ruff format --check` → 318 files already formatted; `pyright services/runtime/app` → 0
  errors; `pyright tools/seed_demo.py` → 6 errors, the same pydantic-default noise as on main (none new).
- Web (`apps/web`): `pnpm exec eslint .` clean; `pnpm run build` OK; `pnpm exec tsc --noEmit` after it: 0 errors.
- e2e on web 3800 / runtime 9481 / relay 9489 (`E2E_WEB_PORT`, `E2E_RUNTIME_PORT`, `E2E_RELAY_PORT`, `E2E_PYTHON`;
  `pnpm run e2e:build` then `pnpm exec playwright test`): **201 passed, 1 failed**, the failure being
  `site-health.spec.ts:10` (hard-codes 3100). `sample-books.spec.ts` (3 tests): an empty folder → card with the brief's
  sentence → Enter on **Load sample books** → progress bar with "n of N steps done", focus on the card heading → Home
  reloads with the **SAMPLE — FICTIONAL COMPANY** banner, "sample books for Bramblewood Joinery Ltd", *Owed to you*
  £17,950, no button; Connect's last step then says "Sample books are loaded"; a folder with one posted receipt shows no
  button on Home or Connect; Connect's last step offers the button for an empty folder. The full seed on the fakes takes
  about 4 s of the 12 s test.

## What remains

- **Never run against a real OneDrive or a real Graph token.** How long it takes there is unmeasured. On the fake the full
  seed makes about 11,300 storage calls (mostly listings and reads around each approval), each roughly one Graph request,
  so it may well exceed the hour a token lasts; the handover is designed for that but only tested on fakes. Graph
  throttling during a long run is untested (429/503 are retried by the client).
- The resume is proven on the fake by refusing the token after a write (and at the write) for every write of an uncut run
  (see above) and by named tests for each two-write window found. A refusal at a non-write call is covered only where the
  sweep's neighbouring cuts land on it, and only one stop per run was tried (the harness allows up to three).
- The background run lives in the runtime process. With more than one runtime process, a POST that reaches another
  process during a live run only reports it; after 3 minutes without progress that process takes over (no lock across
  processes; two processes could then both run for a moment if the first was only slow).
- If the page is closed for more than 10 minutes after the token expires, the run stops; it carries on when the user next
  opens Home (the card shows "Carry on…" from GET's `needs_token`) — it does not finish on its own.
- The seed's documents are rendered on the runtime's event loop (PIL, a few tens of ms each), not in a thread.
- The business name in Connect (used by the scan to tell sales from purchases) is not set for the user; HONESTY says so.
- The runtime image was not rebuilt here (no Docker in this session); the Dockerfile test only checks the COPY lines.
- Repairs on resume duplicate small parts of `approve()` (`_finish_approval`), `record_payment` (adopting an orphan
  payment entry), `import_bank_csv` (`_finish_import`) and invoicing (sequence rewind, sent PDF) inside the seed; app code
  was not changed for them. Audit lines from a repaired action are shorter than the originals.
- `site-health.spec.ts` hard-codes port 3100 and fails on the 3800 ports used here (ignored, as instructed).
