# Review: design research and three small web changes (`claude/research-design`)

Reviewed by the integrator on 28 Oct 2026 before merging (the branch came without a review).

## What it adds

- `docs/research/DESIGN.md` (navigation, onboarding, review cards, brand direction, ten ranked changes) and
  before/after screenshots in `docs/research/design-shots/` (about 3.9 MB).
- `apps/web/e2e/design-shots.spec.ts`: writes those screenshots; skipped unless `DESIGN_SHOTS=1`, so the normal e2e run
  never writes into `docs/`.
- Code (CSS only): the page column widens to `max-w-5xl` from the `xl` breakpoint (`AppShell.tsx`, content and footer);
  Home's figures are larger (`Tiles.tsx`, 28 px, 30 px from `sm`); *Dismiss* stays on the set-up checklist's title row
  (`SetupChecklist.tsx`, no wrap, the title takes the space).

## Checked

The code was to be merged only if green: the full gates passed on the merge commit with no flaky test (runtime 1633,
e2e 298 including the phone-width, axe and keyboard sweeps over every page at the wider canvas). Docs and screenshots
change no behaviour.

## What remains

- DESIGN.md's ten changes are proposals; only the three above are built.
