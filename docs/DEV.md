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
- Every automatic action writes one line to `_System/audit/{yyyy-mm}.jsonl` in the user's folder.
- Branch names: `muse/*` (Muse Code jobs), `claude/*` (Claude Code jobs on the Spark); every merge is reviewed.
