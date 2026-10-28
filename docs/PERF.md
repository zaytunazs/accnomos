# Web performance

Budgets for the static export (`apps/web`, `next build` → `out/`), and how they are checked.

| Budget | Limit | Checked by |
|---|---|---|
| First-load JS per route, gzipped | 250 kB | `pnpm run size` (`scripts/route-sizes.mjs`, exits 1 over budget) |
| Brand images | served at the size shown; nothing loaded that a page does not show | `e2e/phone.spec.ts` (requests to `/brand/`) |
| Motion | `prefers-reduced-motion` stops animation and smooth scrolling | `e2e/phone.spec.ts`, `globals.css` |
| Caching | hashed assets a year, everything else revalidated | `public/.htaccess`, `services/runtime/tests/test_deploy_hardening.py` |

## First-load JS per route

Next 16 dropped the size column from `next build`. `scripts/route-sizes.mjs` measures it from the export
instead: for each page, every script the HTML loads or preloads, summed and gzipped (level 9). That is what a
first visit downloads before the page can hydrate. Run it after `pnpm run build`:

```sh
pnpm run build && pnpm run size          # table below; exit 1 if a route is over 250 kB
node scripts/chunk-report.mjs out/review.html   # one page's chunks, largest first
```

Measured 27 Oct 2026 (Next 16.4.3, Turbopack), production build (`NEXT_PUBLIC_TEST_MODE` unset):

| Route | Before | After |
|---|---:|---:|
| `/` | 267.2 kB | 199.6 kB |
| `/ask` | 264.2 kB | 196.6 kB |
| `/bank` | 257.9 kB | 190.2 kB |
| `/connect` | 255.3 kB | 187.7 kB |
| `/connect/ai` | 253.4 kB | 185.8 kB |
| `/connect/business` | 256.8 kB | 189.2 kB |
| `/connect/ready` | 252.6 kB | 185.0 kB |
| `/contacts` | 260.7 kB | 193.0 kB |
| `/files` | 258.4 kB | 190.8 kB |
| `/how-it-works` | 251.8 kB | 184.2 kB |
| `/invoices` | 259.2 kB | 191.6 kB |
| `/invoices/new` | 260.8 kB | 193.1 kB |
| `/jobs` | 260.4 kB | 192.8 kB |
| `/jobs/job` | 256.4 kB | 188.8 kB |
| `/payroll` | 257.8 kB | 190.2 kB |
| `/privacy` | 251.8 kB | 184.2 kB |
| `/review` | 270.6 kB | 203.1 kB |
| `/settings` | 266.8 kB | 199.2 kB |
| `/vat` | 262.8 kB | 195.2 kB |
| `/vehicles` | 257.9 kB | 190.3 kB |
| `/404`, `/_not-found` | 251.8 kB | 184.2 kB |

**Before, every route was over budget**, and not because of its own component. The floor shared by every page
(`/privacy`, which has no client code of its own) was 251.8 kB, and 68 kB of that was `@azure/msal-browser`.
`AppNav` mounts on every page and checks the account through `useAccount` → `lib/msal.ts`, which imported the
library statically. Splitting a route's own component with `next/dynamic` could not fix that, so the change is
in `lib/msal.ts`: it now loads the library with `import()` on first use (`getMsal`, `getToken`). Every other
file imports MSAL types only, and `msal.ts` says to keep it that way.

After: the shared floor is 184.2 kB and the heaviest route is `/review` at 203.1 kB, 47 kB under budget, so no
route needed a `next/dynamic` split. What makes up the floor now (gzipped): React DOM 71.8 kB, the Next
client runtime 46.5 + 7.7 kB, app shell and shared libraries 39.5 + 12.8 kB, Turbopack runtime 3.9 kB.

What this does and does not buy: with a Microsoft client id configured, each page still fetches the MSAL chunk
just after hydration, because the nav checks who is signed in. It no longer blocks parsing, hydration or the
first interaction, and it is cached for a year (see Caching). Signed out on a build without a client id, it is
never fetched.

## Images

| File | Size | Where | Loaded |
|---|---|---|---|
| `brand/hero.svg` | vector, about 3 kB | signed-out Home pitch (`/try`), every width | there only |
| `brand/feature-1024x500.png` | 524 kB | Play Store feature graphic | never by the web app |
| `brand/icon-512.png` | 113 kB | launcher icon source | never by the web app |

The hero is one flat vector (`Pitch.tsx`, since 28 Oct 2026; it replaced `hero.jpg` and `hero-800.jpg`, whose
hairline strokes resampled into stray lines when the bitmap was scaled: docs/reviews/dashboard-ui/REVIEW.md).
`phone.spec.ts` checks that at 412 px and at 1280 px the sample Home asks for `/brand/hero.svg` and nothing else from
`/brand/`.

## Motion

`globals.css` cuts every animation to one 0.01 ms iteration and every transition to 0.01 ms under
`prefers-reduced-motion: reduce` (the loading skeleton pulse, the switches). Script-driven smooth scrolling
ignores that rule, so the two places that ask for it check the media query themselves: Ask's scroll to the
newest answer, and Review's scroll to the next card after a decision. The microphone level meter while
recording is live feedback, not decoration, and stays.

## Caching (`public/.htaccess`)

- `/_next/static/…` (content-hashed JS, CSS and fonts): `Cache-Control: public, max-age=31536000, immutable`.
- Everything else (pages, RSC `.txt` payloads, `.json`, unhashed public files such as `/brand/*` and
  `auth/msal-redirect-bridge.js`): `no-cache`, so a deploy is seen at once (a 304 when nothing changed).
- Both are set on success only. An error response, such as a 404 for a chunk an old tab asks for after a
  deploy, never carries the year-long header.
- The security headers (HSTS, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, `X-Frame-Options`, CSP
  `frame-ancestors`) are unchanged and still `always`.

Checked statically only. Like the rest of the `.htaccess`, it has not been tried on Apache/Plesk
(docs/HONESTY.md). The e2e server (`e2e/serve.mjs`) sends `no-store` on purpose.
