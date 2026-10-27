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
```

## Deploy

- **Web:** push to `main` → GitHub Actions builds the static export and force-pushes it to branch `site`;
  Plesk's Git extension pulls `site` into `httpdocs` for accnomos.com. `.htaccess` maps `/connect` → `connect.html`.
- **Runtime + relay:** Docker on the DGX Spark, published as `api.accnomos.com` through a tunnel (never port-forward).
- **MSAL redirect URIs** registered: `http://localhost:3000/auth/callback.html`, `https://accnomos.com/auth/callback.html`.

## Conventions

- `packages/ledger` and `packages/connectors` never import provider or model code. VAT boxes come from code only.
- Runtime package is `app`; relay package is `relay` (two services, two names — they share one venv).
- Money is integer pence inside the ledger; the model returns pounds to 2 dp.
- Every automatic action writes one line to `_System/audit/{yyyy-mm}.jsonl` in the user's folder.
- Branch names: `muse/*` (Muse Code jobs), `claude/*` (Claude Code jobs on the Spark); every merge is reviewed.
