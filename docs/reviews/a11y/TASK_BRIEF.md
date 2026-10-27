# Task: Accessibility and performance pass on the web app (axe via Playwright, Lighthouse-style budgets), fix what fails

Accnomos monorepo (public; UK English; no new runtime dependencies; `@axe-core/playwright` may be added as a devDependency only).
Read first `apps/web/e2e/*`, `playwright.config.ts`, `apps/web/src/components/States.tsx`, `AppNav.tsx`, `review/*`, `settings/*`,
`apps/web/src/app/globals.css`, `apps/web/next.config.*`, `apps/web/public/.htaccess` (headers).

## Deliverables
1. `e2e/a11y.spec.ts`: axe-core on every page in the phone smoke list, signed out and signed in (test mode), failing on `serious`
   and `critical` violations; the first run's violations listed in the commit message; then fix them in the app (labels, contrast with
   the existing tokens, focus order, dialog roles, `aria-live` regions, table headers, button names). No rule disabled without a one-line reason.
2. Keyboard-only walk: Home → Review → approve one sample → Settings tab change → Ask question, all via Tab/Enter/shortcuts; a spec
   asserts focus is visible and never trapped (dialogs return focus).
3. Performance: static export sizes per route (`next build` output) recorded in `docs/PERF.md`; any route over 250 kB first-load JS
   gets a code-split (`next/dynamic`) for its heavy component; images under `public/brand` served at the sizes used (check
   `hero.jpg` and `feature-1024x500.png` are not loaded on phones where unused); `prefers-reduced-motion` respected.
4. `.htaccess`: `Cache-Control` for hashed assets (1 year, immutable) vs HTML (no-cache); confirm the security headers stay.
`pnpm run build`, `npx eslint src`, `pnpm run e2e` green. Commit in small steps; do not push. Finish with `git log --oneline -8` and the
before/after violation counts and bundle sizes.
