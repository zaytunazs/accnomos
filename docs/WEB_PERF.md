# Web sweep: page weight

First-load JS per page (gzipped, `node scripts/route-sizes.mjs out` after
`pnpm run build`; production build, Next 16.4.3). Budgets live in
[PERF.md](PERF.md): every route must stay under 250 kB (`pnpm run size`).

Before = [PERF.md](PERF.md) after its MSAL split; after = this sweep
(empty-state actions, skeletons, Try again strips, SAMPLE pills, two dynamic
imports). All routes stay under budget.

| Page (five heaviest) | Before | After |
|---|---:|---:|
| `/review` | 203.1 kB | 215.4 kB |
| `/contacts` | 193.0 kB | 214.3 kB |
| `/` | 199.6 kB | 213.7 kB |
| `/settings` | 199.2 kB | 213.7 kB |
| `/vat` | 195.2 kB | 211.0 kB |

The shared floor (`/privacy`, no client code of its own) rose 184.2 → 192.6 kB:
the sweep's shared UI (Try again buttons, skeletons, sample pills) lives in
the vendor/shell chunks every page loads. Page-specific code stays small.

Waste cut:

- `ReviewQueue` loads `EditSheet` (+ `lib/review-edit`, used nowhere else)
  with `next/dynamic` (`ssr: false`): 3.9 kB raw leaves first load, fetched
  only when Edit is tapped.
- `LiveFiles` loads `FilePreview` the same way: 3.3 kB raw deferred until a
  file is picked.
- No duplicate large imports found: MSAL stays lazy behind `lib/msal.ts`
  (see [PERF.md](PERF.md)); invoice dialogs share modules with inline
  components (`PaymentsPanel`, `StatusTimeline`), so splitting them would not
  move any bytes.
