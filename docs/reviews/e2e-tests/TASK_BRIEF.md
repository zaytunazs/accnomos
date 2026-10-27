# Task: End-to-end tests — Playwright against the static web + the runtime with fake providers

Accnomos monorepo (public; UK English; no secrets). Read first: `apps/web/package.json`, `next.config.ts`, `src/lib/{msal.ts,runtime.ts,
ai-config.ts}`, `services/runtime/app/{main.py,ai/config.py}`, `packages/connectors/.../fake.py`, `evals/gold/receipts/`.

## Deliverables
1. Runtime **test mode**: env `ACCNOMOS_TEST_MODE=1` makes the runtime use `FakeStorageProvider`/`FakeMailProvider`/fake calendar seeded
   from `evals/gold` and a stub AI backend (returns gold fields for known document hashes) — never enabled in the Docker image by default;
   document it in `docs/DEV.md`.
2. Web **test sign-in**: when `NEXT_PUBLIC_TEST_MODE=1` at build time, `msal.ts` exposes a fake account (no network) — only in that build.
3. Playwright (`apps/web/e2e/`, dev dependency only, Chromium): flows — connect & folder ready, upload a gold receipt → scan → proposal →
   approve → VAT boxes change; Ask a question → key numbers present; HMRC card renders (no real OAuth); Outlook intake dry-run; Files list;
   Settings toggles persist; phone viewport smoke of every page (no horizontal scroll). `pnpm run e2e` script; CI job in
   `.github/workflows/e2e.yml` that builds the test-mode export, starts the runtime in test mode, runs Playwright, uploads traces on failure.
4. Keep runtime unit tests green; `pnpm run build` (normal mode) unchanged.
Commit in small steps; do not push. Finish with `git log --oneline -8` and the e2e run summary (pass/fail counts, duration).
