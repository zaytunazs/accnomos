# Task: Demo dry run — script every step of docs/DEMO.md as one Playwright flow in test mode, time it, capture the shots for the video

Accnomos monorepo (public; UK English; no secrets). Read first `docs/DEMO.md`, `docs/submission/VIDEO_SCRIPT.md`, `apps/web/e2e/*`
(fixtures, `signIn`, `createBooksFolder`, `runtime.postGold`, seeds), `services/runtime/app/testmode.py`, `docs/reviews/security-2/REVIEW.md`
("the web action card does not explain the stale-approving path").

## Deliverables
1. `apps/web/e2e/demo.spec.ts` (desktop 1280×800 and phone 390): the on-stage script as one ordered flow — connect → upload the sample
   receipt → scan → Review card (checks, verifier, crop) → approve → VAT boxes move for the current period → Ask a question (cited
   answer) → "send a £100 invoice to JM Trading" → action card → approve → invoice sent via the fake sender → Home dashboard shows it.
   Each step asserts the exact on-screen text the script quotes; `test.step` names match the script's step numbers; total time printed.
2. Screenshots at each step → `docs/submission/shots/<nn>-<step>.png` (desktop) and `…-phone.png`, under 400 kB each (PNG, scale 1);
   `docs/submission/VIDEO_SCRIPT.md` references them per timestamp.
3. Every wording mismatch between `docs/DEMO.md` and the app is fixed **in the doc** (the app is the truth) unless the app text is
   plainly wrong; list the fixes in the commit message. If a step cannot be done in test mode (real HMRC), the script says what the
   presenter does instead and the spec skips that step with the reason.
4. The web action card gets the one missing sentence for a stale `approving` state (what to do; from `docs/ACTIONS.md`).
5. `pnpm run e2e` stays green and under the CI budget (the demo spec may be its own Playwright project, `demo`, excluded from CI if it
   takes over 60 s).
Commit in small steps; do not push. Finish with `git log --oneline -8`, the total demo time, and the doc fixes list.
