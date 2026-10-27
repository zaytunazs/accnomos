# Task: Web Review page — the demo centrepiece: keyboard flow, crop/original toggle, bulk rule approvals, edit validation

Accnomos monorepo (public; UK English; no secrets). Read first `apps/web/src/components/review/LiveReview.tsx`, `components/review/*`,
`lib/runtime.ts` (`approve`, `reject`, `undo`, `rules`), `services/runtime/app/{approve.py,autopilot.py,pipeline.py,schemas.py}`
(`Proposal.crop`, `verification`, `checks`), `docs/AUTOPILOT.md`, `docs/reviews/sam-crop/REVIEW.md`, `docs/reviews/verifier/REVIEW.md`.

## Deliverables
1. **Keyboard**: J/K move between cards, A approve, E edit, R reject (with a confirm for R), U undo the last decision; a visible
   shortcut hint; focus never lost after a decision (next card focused). Screen-reader labels.
2. **Image**: thumbnail opens a side-by-side of the original and the code crop (when `crop.method != "none"`), with the crop note;
   zoom on click; keyboard-closable. Big images lazy-loaded.
3. **Verifier and checks** on the card: a compact line per failed check with the plain-English reason (already in `checks[].message`),
   the verifier verdict with the fields that disagreed highlighted in the edit sheet. Never show raw codes.
4. **Edit sheet**: net + VAT = gross in pence, VAT rate vs code, date not in the future, VRN format; Save & approve disabled while
   invalid with the reason; only changed fields sent as `edits` (same contract as Android).
5. **Rule matches**: when a saved Autopilot rule matches a proposal and the level is L1, the card says so and offers *Approve all N
   rule matches* with one confirm; each approval is a normal `POST …/approve` (no new runtime route).
6. **Signed out**: the sample cards keep every affordance working locally (approve removes the card, undo brings it back) and the
   `SAMPLE — FICTIONAL COMPANY` label; phone width (390) has no horizontal scroll and the action row never wraps.
`pnpm run build`, `npx eslint src` clean; add the Review flow to the e2e suite if `apps/web/e2e` exists. Commit in small steps; do
not push. Finish with `git log --oneline -8` and five things a human should check in a browser.
