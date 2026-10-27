# Developer notes

## Run locally (Windows dev box)

```powershell
# Python side (uv workspace: runtime, relay, ledger, connectors, evals)
uv sync --all-packages --all-extras
uv run pytest -q                                   # all packages

# Agent Runtime (stateless) on :8780
uv run --package accnomos-runtime uvicorn app.main:app --app-dir services/runtime --port 8780 --reload

# HMRC relay on :8787 (needs HMRC_* in .env; sandbox only)
uv run --package accnomos-hmrc-relay uvicorn relay.main:app --app-dir services/hmrc-relay --port 8787 --reload

# Web (PWA) on :3000 — needs apps/web/.env.local with NEXT_PUBLIC_MS_CLIENT_ID
cd apps/web; pnpm install; pnpm dev

# Android
cd apps/mobile; flutter run
```

Secrets live in `.env` (root, git-ignored) and `apps/web/.env.local`. See `.env.example`.

**Runtime guards that bite in development** (`docs/SECURITY.md`): CORS allows only `CORS_ORIGINS` (default
`http://localhost:3000`); an `X-AI-Base-Url` that is not `OLLAMA_BASE`, `MODEL_API_BASE` or in `AI_ALLOWED_BASE_URLS`
gets a 400 (the web app's default local URL, `http://192.168.1.176:11434`, needs
`AI_ALLOWED_BASE_URLS=http://192.168.1.176:11434`); 60 requests per minute per IP (`RATE_LIMIT_PER_MIN=0` turns it off).

**ffmpeg** must be on the runtime's `PATH` for voice questions (`POST /books/ask/voice` converts browser/phone audio to
WAV mono 16 kHz before Muse Voice Transcribe). Windows: `winget install Gyan.FFmpeg`; macOS: `brew install ffmpeg`;
Debian/Ubuntu: `apt install ffmpeg` (the runtime Docker image includes it). The runtime checks at startup: without
ffmpeg it logs a warning, `/health` reports `"voice": false` and `/books/ask/voice` answers 503. Its tests skip the
conversion cases when ffmpeg is missing. Voice works in key mode only (the user's Meta API key); local mode gets a 400.

## Evals (Meta model outputs graded against the synthetic gold set)

```powershell
cd evals
$env:OLLAMA_BASE='http://<spark>:11434'
..\.venv\Scripts\python.exe -m harness.run_extraction --mode local --messy --out runs/<name>   # Glimmer
..\.venv\Scripts\python.exe -m harness.run_extraction --mode key   --out runs/<name>          # muse-spark-1.3 (MODEL_API_KEY)
..\.venv\Scripts\python.exe -m harness.judge runs/<name> --escalate claude-sonnet-5-5         # Claude as judge (H19)
..\.venv\Scripts\python.exe -m harness.crop_bench --limit 20                                   # crop IoU; adds SAM if MODEL_API_KEY is set
```

## End-to-end tests (Playwright, test mode)

```powershell
uv sync --all-packages --all-extras                # the runtime must be importable by E2E_PYTHON (default python3)
cd apps/web; pnpm install; pnpm exec playwright install chromium
pnpm run e2e                                       # = e2e:build (test-mode export → out-e2e/) + e2e:test
$env:E2E_PYTHON='..\..\.venv\Scripts\python.exe'; pnpm run e2e:test   # Windows: point at the venv
pnpm exec playwright test e2e/review.spec.ts       # one spec (after one e2e:build); add :130 for the test on that line
pnpm exec playwright test -g "plan my Thursday"    # tests whose title matches
pnpm exec playwright test --project=phone          # only the phone-width tests
pnpm exec playwright test --ui                     # UI mode: pick, watch and time-travel tests; starts both servers too
pnpm exec playwright test e2e/review.spec.ts:130 --repeat-each=20   # hunting a flake
```

55 tests (30 desktop, 25 phone) take about 27 s locally on 4 workers; CI runs 3 workers with one retry. Rebuild with
`pnpm run e2e:build` after changing anything under `src/`: the tests run against `out-e2e/`, not the dev server.
Ports are `E2E_WEB_PORT` (3100), `E2E_RUNTIME_PORT` (8781) and `E2E_RELAY_PORT` (8789), read by both the build and
the config, so set them for both (e.g. `node --env-file=ports.env e2e/build.mjs`). Locally Playwright reuses servers
already on those ports, which may be another checkout's: give each checkout its own ports.

Playwright (`apps/web/playwright.config.ts`, Chromium only) starts both servers itself: the runtime on :8781 with
`ACCNOMOS_TEST_MODE=1` and a static host for `out-e2e/` on :3100. Each test resets the fakes and fails if any request
leaves 127.0.0.1. One spec per page: connect + folder ready; Home tiles, deadlines and the Review badge; gold receipt
upload → scan → approve → VAT boxes change for the picked period; Ask key numbers and "plan my Thursday" → day-plan
card; Invoices create → preview → send behind the confirmation tick (the fake sender records it); Bank gold Barclays
CSV → confirm a match → transfer and expense proposal; Contacts list, edit, statement; Jobs staff + hours → invoice
lines; Vehicles journey → allowance claim in Review; Payroll prepare → CSV → confirm and post; Settings tabs, deep
links, VAT period moving the Home deadlines; HMRC card (relay answered by Playwright, no real OAuth); Outlook intake
dry run; Files. Phone: every page at Pixel 7 width with no horizontal scroll, and Home, Review, Ask, VAT and Settings
at 390 px with no button cut off. Tests run in parallel (`fullyParallel`): `e2e/fixtures.ts` sends `X-Test-Tenant`
(random per worker process) from the page and from the `request` fixture, and the test-mode runtime keeps one set of
fakes per tenant, so a worker's reset never touches another's OneDrive. The runtime renders and hashes the 200 gold
receipts at startup (~10 s) before `/health` answers, so no test waits on that. CI: `.github/workflows/e2e.yml` (traces uploaded on failure; locally
`pnpm exec playwright show-trace test-results/<test>/trace.zip`).

**Runtime test mode** (`ACCNOMOS_TEST_MODE=1`, `services/runtime/app/testmode.py`). For tests only; the Docker image
sets it to 0 and does not even contain `evals/gold`, which it needs.

- Storage, mail (read and send), address book and calendar are the in-memory fakes from `accnomos_connectors.fake`,
  one set per `X-Test-Tenant` header (no header: one default set), whatever token the request carries (a token is
  still required, as in production). Sent mail
  (invoices, reminders) is only recorded. The calendar holds a sample VAT deadline and one meeting on Thursday
  29 Oct 2026 for the day planner. The browser's own Graph calls go to a look-alike at `/__test/graph/v1.0` over the
  same storage. `/__test/*` is outside the per-IP rate limit; each reset refills the limit for everything else.
- The stub AI proves the plumbing, not the models: it never reads a document it was not given the answer to.
- Every AI call is forced to a stub at `/__test/ai` (Ollama-shaped), whatever the request headers say. It reads a
  document only if it is a gold receipt rendered by `evals/harness/render.py` (matched by the PNG's sha256) and
  returns its gold fields; Ask gets an answer built from the facts pack, so grounding passes.
- `POST /__test/reset` empties the caller's tenant's storage (no other tenant's) and reseeds the mailbox (three gold receipts, one newsletter), the calendar and
  a sample invoice profile (Sam Builds Ltd, footer "SAMPLE — FICTIONAL COMPANY") so an invoice can be sent straight
  away. `POST /__test/reset?seed=bank` also posts the four entries `evals/gold/bank/barclays.csv` pays for (opt-in:
  they change the VAT figures other specs check). `GET /__test/gold` and `/__test/gold/{name}.png` list and serve the
  gold receipts; `GET /__test/state` shows the fakes, including what was "sent".
- "Today" is pinned (`ACCNOMOS_TEST_TODAY`, default 2026-10-27; also for "plan my Thursday", scan and `/extract`):
  the gold receipts (Jul–Sep 2026) fall in the previous VAT quarter, the one still to file, while VAT and Ask default
  to the current one (Oct–Dec). The e2e browser clock is set to the same day. `CROP_MODE` defaults to `off` so the
  stub sees the uploaded bytes.

**Web test build** (`NEXT_PUBLIC_TEST_MODE=1`, made by `e2e/build.mjs`): `src/lib/msal.ts` uses a fake account from
`msal-test.ts` (no network; "Sign in" sets `msal.accnomos-test.signedIn` in localStorage) and `src/lib/graph.ts` uses
the runtime's look-alike. A normal `pnpm build` folds both away: `out/` contains no fake account and no `/__test` URL
(`deploy-web.yml` checks this before publishing).

## Document crop (before extraction)

`app/ai/crop.py` crops phone photos to the receipt; it never fails the pipeline and returns the
original whenever it is unsure. The result is on the proposal as `crop` plus an ok `CROP` check.

- `CROP_MODE=auto` (default) | `code` | `off`.
- `SAM_CROP=1` lets key-mode requests call `sam-3.1` on `{MODEL_API_BASE}/responses` first
  (~$2.50 per 1k images, two calls when "receipt" finds nothing and "invoice" is tried).
  **Off by default: the request/response shape is unverified** (the Meta docs were unreachable when
  it was written). Capture a real response, replace `services/runtime/tests/fixtures/sam_response.json`,
  and check `parse_sam_boxes` against it before turning it on.
- Without SAM, Pillow + numpy find the largest bright region (Otsu); accepted at 25–95 % of the frame.
- Crops keep the upload's format (JPEG, including phone MPO files, PNG, WebP); anything else is passed
  through uncropped so the MIME type stays true.

## Deploy

- **Web:** push to `main` → GitHub Actions builds the static export and force-pushes it to branch `site`;
  Plesk's Git extension pulls `site` into `httpdocs` for accnomos.com. `.htaccess` maps `/connect` → `connect.html`.
- **Runtime + relay:** Docker on the DGX Spark, published as `api.accnomos.com` through a tunnel (never port-forward).
  Hardening checklist: `deploy/README.md`.
- **MSAL redirect URIs** registered: `http://localhost:3000/auth/callback.html`, `https://accnomos.com/auth/callback.html`.

## Conventions

- `packages/ledger` and `packages/connectors` never import provider or model code. VAT boxes come from code only.
- Runtime package is `app`; relay package is `relay` (two services, two names — they share one venv).
- Money is integer pence inside the ledger; the model returns pounds to 2 dp.
- Every automatic action writes one line to `_System/audit/{yyyy-mm}.jsonl` in the user's folder (format and the full folder layout: `docs/ARCHITECTURE.md`).
- Branch names: `muse/*` (Muse Code jobs), `claude/*` (Claude Code jobs on the Spark); every merge is reviewed.
