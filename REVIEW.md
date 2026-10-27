# Review: `claude/a11y`

Second-agent review of the accessibility and performance pass (`TASK_BRIEF.md`), 27 Oct 2026.

## What was checked

- **Tests, all green at the end:** `pytest -q` in `services/runtime` (675 passed, 1 skipped), `packages/ledger` (33),
  `packages/connectors` (37), `services/hmrc-relay` (102), `evals` (153). Only `services/runtime` is touched by the branch
  (one `.htaccess` test); the rest were run anyway. `cd apps/web && pnpm run build` passes, `npx eslint src e2e scripts`
  is clean, and `pnpm run e2e` gives **107 passed** (3.3 min).
- **The first full e2e run failed 1 of 106**: the keyboard walk, flaky (1 in 4 with `--repeat-each=4`). The cause was in
  the app, not the spec (see fixes).
- **Diff read in full:** lazy MSAL (`lib/msal.ts`), the axe fixes (`AppNav` badge naming, `ReviewImage`, `SetupChecklist`,
  `/privacy` region, `/files` nested link, landmarks, `/jobs/job` h1), the `<dialog>` Explain, Review's reduced-motion
  scroll, the phone hero, `.htaccess` caching plus its test, `docs/PERF.md`, README. No secrets, user data or server-side
  writes. No new runtime dependency (`@axe-core/playwright` is a devDependency only). No rule is disabled in
  `a11y.spec.ts`. UK English throughout.
- **Numbers re-measured:** `pnpm run size` matches every row of `docs/PERF.md` (shared floor 184.2 kB, `/review`
  203.1 kB, all under 250 kB). The commit messages list the first run's violations (3 serious rules, 24 nodes) as the
  brief asked.

## What I fixed

| Commit | Fix |
|---|---|
| `cfb0c1e` | Lint rule: any value import of `@azure/msal-browser` outside `lib/msal.ts`'s `import()` fails `eslint`. The 68 kB first-load saving was held up only by a comment. Checked with a throwaway value import. |
| `c83ce16` | Review's scan put "N new proposals" in the live region *before* reloading the queue. J pressed straight after the announcement (or a screen-reader user acting on it) found an empty list. This was the flaky keyboard walk. Now announced after `load()`; 5 of 5 repeats pass. |
| `5c81e7f` | Explain drawer: a click on the panel's own padding counted as a backdrop click and closed it. Padding moved to an inner wrapper. The drawer also follows a native `close`, so state can't stay "open" while the dialog is shut. New e2e test (click inside, backdrop, focus return, reopen); it fails on the old component. |
| `2f098a9` | README: merged the two contradicting "Checked 27 Oct" paragraphs (one sat in the middle of a table) and gave real counts; e2e row now says 107/33. `msal.ts` comment said ~80 kB; it is 68 kB. |

## What remains

- The 250 kB budget (`pnpm run size`) is manual: nothing in `pnpm run e2e`, `eslint` or CI runs it, so a regression
  would go unnoticed until someone runs it. The new lint rule only guards the MSAL case.
- `.htaccess` caching is checked statically (regex test). It has never been served by Apache/Plesk, so the `<If>` merge
  order that gives `/_next/static/` the year-long header is unverified.
- With a Microsoft client id configured, every page still fetches the MSAL chunk just after hydration. It is off the
  critical path, not gone (docs/PERF.md says so).
- axe covers 19 pages × signed out/in at phone width, plus 4 pages at 1280 px. `/how-it-works` is not in the list,
  and desktop width is not covered beyond those 4. No screen reader or real phone has been tried. Automated axe finds
  only part of WCAG.
- `public/brand/feature-1024x500.png` (524 kB) and `icon-512.png` ship in the static export although no page loads
  them. That's harmless to users but adds deploy weight.
- `TASK_BRIEF.md` is committed on the branch (`2229442`, message "wip: checkpoint after implement pass"). Drop or squash
  it before merge if briefs shouldn't live in the repo.
- `.github/workflows/e2e.yml` has still never run on GitHub; all e2e results are local.

## How to verify by hand

Run `pnpm install && pnpm run build && pnpm run size` in `apps/web`: every route should print under 250 kB, and
`/review` should be the largest at about 203 kB. Then `pnpm run e2e`, which should give 107 passed, including
`a11y.spec.ts` and `keyboard.spec.ts`. To try it yourself, serve the export (`npx serve out`) and open `/` in Chrome
at 412 px wide. DevTools → Network → Img should show only `brand/hero-800.jpg`; at 1280 px only `brand/hero.jpg`.
Unplug the mouse and Tab from the top of `/ask`: every stop has a visible ring. Press Enter on the "?" beside "Where
answers come from": Tab stays inside the drawer, Escape closes it and focus returns to "?". Clicking blank space
inside the drawer keeps it open; clicking the dimmed page closes it. In DevTools → Rendering, emulate
`prefers-reduced-motion: reduce` and check the loading skeletons stop pulsing.
